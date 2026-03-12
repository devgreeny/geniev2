import { Router, raw } from 'express';
import type { Request, Response } from 'express';
import { 
  sendSms, 
  verifyWebhookSignature, 
  parseInboundMessage, 
  parseStatusCallback,
  getVonageNumber,
} from '../services/vonage.js';
import { executeAgent, healthCheck } from '../services/agentfield.js';
import { 
  getBusinessByCustomerNumber, 
  getBusinessByPrivateNumber, 
  saveMessage, 
  saveSmsMessage,
  getSmsMessageByVonageId,
  updateSmsStatus,
  isAiPaused,
} from '../services/db.js';

const router = Router();

const FALLBACK_MESSAGE = "We're having a little trouble right now. We'll get back to you shortly!";

/**
 * Middleware to capture raw body for signature verification
 */
router.use('/inbound', raw({ type: 'application/json' }));
router.use('/status', raw({ type: 'application/json' }));

/**
 * Get recent conversation history for context
 */
function getRecentMessages(businessId: string, participantPhone: string, limit = 10): string {
  try {
    const { getDb } = require('../services/db.js');
    const db = getDb();
    const rows = db.prepare(`
      SELECT direction, message FROM conversations 
      WHERE business_id = ? AND participant_phone = ?
      ORDER BY created_at DESC LIMIT ?
    `).all(businessId, participantPhone, limit) as Array<{direction: string, message: string}>;
    
    const history = rows.reverse().map((row: {direction: string, message: string}) => 
      `${row.direction === 'inbound' ? 'Customer' : 'You'}: ${row.message.substring(0, 200)}`
    ).join('\n');
    
    return history;
  } catch (err) {
    console.error('[vonage] Error fetching history:', err);
    return '';
  }
}

/**
 * Inbound SMS webhook from Vonage
 * POST /vonage/inbound
 */
router.post('/inbound', async (req: Request, res: Response) => {
  // Parse body (raw middleware gives us Buffer)
  let body: Record<string, unknown>;
  let rawBody: string;
  
  try {
    rawBody = Buffer.isBuffer(req.body) ? req.body.toString() : JSON.stringify(req.body);
    body = Buffer.isBuffer(req.body) ? JSON.parse(req.body.toString()) : req.body;
  } catch (err) {
    console.error('[vonage] Failed to parse inbound body:', err);
    res.status(400).send('Invalid JSON');
    return;
  }

  // Verify signature if configured
  const signature = req.headers['x-vonage-signature'] as string | undefined;
  if (!verifyWebhookSignature(rawBody, signature)) {
    console.warn('[vonage] Invalid signature on inbound webhook');
    res.status(401).send('Invalid signature');
    return;
  }

  // Parse the inbound message
  const message = parseInboundMessage(body);
  if (!message) {
    console.warn('[vonage] Could not parse inbound message');
    res.status(400).send('Invalid message format');
    return;
  }

  console.log(`[vonage] Inbound SMS from ${message.from} to ${message.to}: ${message.text}`);

  // Acknowledge immediately (Vonage requires 200 within timeout)
  res.status(200).send('OK');

  // === IDEMPOTENCY CHECK ===
  const existing = getSmsMessageByVonageId(message.messageId);
  if (existing) {
    console.log(`[vonage] Duplicate message ${message.messageId}, skipping`);
    return;
  }

  // Find business by the number that received the SMS
  const business = getBusinessByCustomerNumber(message.to) ?? getBusinessByPrivateNumber(message.to);
  
  if (!business) {
    console.warn(`[vonage] No business found for number ${message.to}`);
    // Still save the message for debugging
    saveSmsMessage({
      vonageMessageId: message.messageId,
      businessId: null,
      direction: 'inbound',
      fromNumber: message.from,
      toNumber: message.to,
      body: message.text,
      status: 'received',
    });
    return;
  }

  // Determine if sender is owner or customer
  const isOwner = message.from === business.owner_phone;
  const role = isOwner ? 'owner' : 'customer';

  // Save inbound SMS to tracking table
  saveSmsMessage({
    vonageMessageId: message.messageId,
    businessId: business.id,
    direction: 'inbound',
    fromNumber: message.from,
    toNumber: message.to,
    body: message.text,
    status: 'received',
  });

  // Save to conversations table
  saveMessage(business.id, message.from, role, 'inbound', message.text);

  // Check if AI is paused for customer messages
  if (!isOwner && isAiPaused(business.id)) {
    console.log(`[vonage] AI is paused - holding customer message from ${message.from}`);
    const holdMessage = "Thanks for your message! We'll get back to you shortly.";
    try {
      await sendAndSaveResponse(message.from, message.to, holdMessage, business.id, role);
    } catch (sendErr) {
      console.error('[vonage] Failed to send hold message:', sendErr);
    }
    return;
  }

  // Get conversation history for AI context
  const historyContext = getRecentMessages(business.id, message.from, 10);

  try {
    // Check if AgentField is healthy
    const agentFieldHealthy = await healthCheck();
    if (!agentFieldHealthy) {
      console.error('[vonage] AgentField not available, sending fallback');
      await sendAndSaveResponse(message.from, message.to, FALLBACK_MESSAGE, business.id, role);
      return;
    }

    // Execute AI agent
    const result = await executeAgent('master', 'handle_message', {
      phone: message.from,
      message: message.text,
      business_id: business.id,
      is_owner: isOwner,
      conversation_history: historyContext,
    });

    const response = result.output?.response || FALLBACK_MESSAGE;
    
    // Send response via SMS
    await sendAndSaveResponse(message.from, message.to, response, business.id, role);
    
    console.log(`[vonage] Response sent to ${message.from}`);
  } catch (err) {
    console.error('[vonage] Error handling message:', err);
    try {
      await sendAndSaveResponse(message.from, message.to, FALLBACK_MESSAGE, business.id, role);
    } catch (sendErr) {
      console.error('[vonage] Failed to send fallback:', sendErr);
    }
  }
});

/**
 * Helper to send SMS and save to DB
 */
async function sendAndSaveResponse(
  to: string, 
  from: string, 
  text: string, 
  businessId: string, 
  role: 'owner' | 'customer'
): Promise<void> {
  const result = await sendSms(to, text, from);
  
  // Save outbound to SMS tracking
  saveSmsMessage({
    vonageMessageId: result.messageId,
    businessId,
    direction: 'outbound',
    fromNumber: from,
    toNumber: to,
    body: text,
    status: result.status,
  });

  // Save to conversations
  saveMessage(businessId, to, role, 'outbound', text);
}

/**
 * Delivery status webhook from Vonage
 * POST /vonage/status
 */
router.post('/status', async (req: Request, res: Response) => {
  // Parse body
  let body: Record<string, unknown>;
  let rawBody: string;
  
  try {
    rawBody = Buffer.isBuffer(req.body) ? req.body.toString() : JSON.stringify(req.body);
    body = Buffer.isBuffer(req.body) ? JSON.parse(req.body.toString()) : req.body;
  } catch (err) {
    console.error('[vonage] Failed to parse status body:', err);
    res.status(400).send('Invalid JSON');
    return;
  }

  // Verify signature
  const signature = req.headers['x-vonage-signature'] as string | undefined;
  if (!verifyWebhookSignature(rawBody, signature)) {
    console.warn('[vonage] Invalid signature on status webhook');
    res.status(401).send('Invalid signature');
    return;
  }

  // Parse status callback
  const status = parseStatusCallback(body);
  if (!status) {
    console.warn('[vonage] Could not parse status callback');
    res.status(400).send('Invalid status format');
    return;
  }

  console.log(`[vonage] Status update for ${status.messageId}: ${status.status}`);

  // Acknowledge immediately
  res.status(200).send('OK');

  // Update status in database
  try {
    updateSmsStatus(status.messageId, {
      status: status.status,
      errorCode: status.errorCode,
      errorReason: status.errorReason,
      timestamp: status.timestamp,
    });
  } catch (err) {
    console.error('[vonage] Failed to update status:', err);
  }
});

/**
 * Direct SMS send endpoint (for campaigns/re-engagement)
 * POST /vonage/send
 */
router.post('/send', async (req: Request, res: Response) => {
  const { to, message, from } = req.body as { to: string; message: string; from?: string };

  if (!to || !message) {
    res.status(400).json({ error: 'Missing required fields: to, message' });
    return;
  }

  const fromNumber = from || getVonageNumber();
  
  console.log(`[vonage] Direct send to ${to}: ${message.slice(0, 50)}...`);

  try {
    const result = await sendSms(to, message, fromNumber);
    
    // Save to SMS tracking (no business context)
    saveSmsMessage({
      vonageMessageId: result.messageId,
      businessId: null,
      direction: 'outbound',
      fromNumber: fromNumber,
      toNumber: to,
      body: message,
      status: result.status,
    });

    res.json({ 
      success: true, 
      message_id: result.messageId,
      status: result.status,
    });
  } catch (err) {
    console.error('[vonage] Send failed:', err);
    res.status(500).json({ error: 'Failed to send SMS', details: String(err) });
  }
});

/**
 * Health/info endpoint
 * GET /vonage/info
 */
router.get('/info', (_req: Request, res: Response) => {
  res.json({
    configured: !!(process.env.VONAGE_API_KEY && process.env.VONAGE_API_SECRET),
    number: getVonageNumber() ? `${getVonageNumber().slice(0, 4)}****` : 'not set',
    signature_verification: !!process.env.VONAGE_SIGNATURE_SECRET,
  });
});

export default router;
