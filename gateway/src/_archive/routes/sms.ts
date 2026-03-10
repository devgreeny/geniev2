import { Router } from 'express';
import type { Request, Response } from 'express';
import { executeAgent, healthCheck } from '../services/agentfield.js';
import { sendSms } from '../services/vonage.js';
import { getBusinessByCustomerNumber, getBusinessByPrivateNumber, saveMessage, getAllBusinesses } from '../services/db.js';

const router = Router();

interface VonageInboundSms {
  msisdn: string;
  to: string;
  text: string;
  messageId?: string;
}

interface TwilioInboundSms {
  From: string;
  To: string;
  Body: string;
}

const FALLBACK_MESSAGE = "We're having a little trouble right now. We'll get back to you shortly!";

router.post('/inbound', async (req: Request, res: Response) => {
  const vonageBody = req.body as VonageInboundSms;
  const twilioBody = req.body as TwilioInboundSms;

  const from = vonageBody.msisdn ? `+${vonageBody.msisdn}` : twilioBody.From;
  const to = vonageBody.to ? `+${vonageBody.to}` : twilioBody.To;
  const message = vonageBody.text ?? twilioBody.Body;

  if (!from || !to || !message) {
    res.status(400).send('Bad Request');
    return;
  }

  console.log(`[sms] Inbound from ${from} to ${to}: ${message}`);

  res.status(200).send('OK');

  const businessByPrivate = getBusinessByPrivateNumber(to);
  const businessByCustomer = getBusinessByCustomerNumber(to);
  const business = businessByPrivate ?? businessByCustomer;

  if (!business) {
    console.warn(`[sms] No business found for number ${to}`);
    return;
  }

  const isOwner = from === business.owner_phone;
  const role = isOwner ? 'owner' : 'customer';

  saveMessage(business.id, from, role, 'inbound', message);

  try {
    const agentFieldHealthy = await healthCheck();
    
    if (!agentFieldHealthy) {
      console.error('[sms] AgentField not available, sending fallback');
      await sendSms(from, to, FALLBACK_MESSAGE);
      return;
    }

    const result = await executeAgent('master', 'handle_message', {
      phone: from,
      message: message,
      business_id: business.id,
      is_owner: isOwner,
    });

    const response = result.output?.response ?? FALLBACK_MESSAGE;
    
    await sendSms(from, to, response);
    saveMessage(business.id, from, role, 'outbound', response);
    
    console.log(`[sms] Response sent to ${from}`);
  } catch (err) {
    console.error('[sms] Error handling message:', err);
    try {
      await sendSms(from, to, FALLBACK_MESSAGE);
    } catch (sendErr) {
      console.error('[sms] Failed to send fallback:', sendErr);
    }
  }
});

router.get('/inbound', async (req: Request, res: Response) => {
  const { msisdn, to, text } = req.query as Record<string, string>;

  if (!msisdn || !to || !text) {
    res.status(400).send('Bad Request');
    return;
  }

  console.log(`[sms] Inbound (GET) from +${msisdn} to +${to}: ${text}`);

  res.status(200).send('OK');

  const business = getBusinessByCustomerNumber(`+${to}`) ?? getBusinessByPrivateNumber(`+${to}`);

  if (!business) {
    console.warn(`[sms] No business found for number +${to}`);
    return;
  }

  const from = `+${msisdn}`;
  const isOwner = from === business.owner_phone;
  const role = isOwner ? 'owner' : 'customer';

  saveMessage(business.id, from, role, 'inbound', text);

  try {
    const result = await executeAgent('master', 'handle_message', {
      phone: from,
      message: text,
      business_id: business.id,
      is_owner: isOwner,
    });

    const response = result.output?.response ?? FALLBACK_MESSAGE;
    await sendSms(from, `+${to}`, response);
    saveMessage(business.id, from, role, 'outbound', response);
    console.log(`[sms] Response sent to ${from}`);
  } catch (err) {
    console.error('[sms] Error handling message:', err);
    try {
      await sendSms(from, `+${to}`, FALLBACK_MESSAGE);
    } catch (sendErr) {
      console.error('[sms] Failed to send fallback:', sendErr);
    }
  }
});

// ============== Re-engagement Endpoints ==============

interface SendSmsRequest {
  to: string;
  from: string;
  message: string;
}

// Direct SMS sending endpoint (for re-engagement cron job)
router.post('/send', async (req: Request, res: Response) => {
  const { to, from, message } = req.body as SendSmsRequest;
  
  if (!to || !from || !message) {
    res.status(400).json({ error: 'Missing required fields: to, from, message' });
    return;
  }
  
  console.log(`[sms] Outbound re-engagement to ${to}: ${message.slice(0, 50)}...`);
  
  try {
    await sendSms(to, from, message);
    res.json({ success: true, to, message_preview: message.slice(0, 50) });
  } catch (err) {
    console.error('[sms] Send failed:', err);
    res.status(500).json({ error: 'Failed to send SMS', details: String(err) });
  }
});

// Get pending re-engagements for a business
router.get('/reengagement/pending/:businessId?', async (req: Request, res: Response) => {
  const { businessId } = req.params;
  
  try {
    const agentFieldHealthy = await healthCheck();
    if (!agentFieldHealthy) {
      res.status(503).json({ error: 'AgentField not available' });
      return;
    }
    
    if (businessId) {
      // Get pending for specific business
      const result = await executeAgent('leads', 'get_pending_reengagements', {
        business_id: businessId
      });
      res.json(result.output ?? { pending: [], count: 0 });
    } else {
      // Get pending for all businesses
      const result = await executeAgent('leads', 'process_all_reengagements', {});
      res.json(result.output ?? { pending_messages: [], total_count: 0 });
    }
  } catch (err) {
    console.error('[sms] Failed to get pending re-engagements:', err);
    res.status(500).json({ error: 'Failed to get pending re-engagements', details: String(err) });
  }
});

// Process and send all pending re-engagements
router.post('/reengagement/process', async (req: Request, res: Response) => {
  const { dry_run = false, business_id } = req.body as { dry_run?: boolean; business_id?: string };
  
  console.log(`[sms] Processing re-engagements${dry_run ? ' (DRY RUN)' : ''}${business_id ? ` for ${business_id}` : ' for all businesses'}`);
  
  try {
    const agentFieldHealthy = await healthCheck();
    if (!agentFieldHealthy) {
      res.status(503).json({ error: 'AgentField not available' });
      return;
    }
    
    // Get all pending re-engagements
    let pendingResult;
    if (business_id) {
      pendingResult = await executeAgent('leads', 'get_pending_reengagements', {
        business_id
      });
    } else {
      pendingResult = await executeAgent('leads', 'process_all_reengagements', {});
    }
    
    const pending = business_id 
      ? pendingResult.output?.pending ?? []
      : pendingResult.output?.pending_messages ?? [];
    
    if (pending.length === 0) {
      res.json({ 
        success: true, 
        message: 'No pending re-engagements', 
        sent: 0, 
        failed: 0 
      });
      return;
    }
    
    let sent = 0;
    let failed = 0;
    const results: Array<{ phone: string; success: boolean; error?: string }> = [];
    
    for (const item of pending) {
      const customerPhone = item.customer_phone;
      const fromNumber = item.from_number ?? (await getFromNumber(item.business_id));
      const message = item.message;
      
      if (!customerPhone || !fromNumber || !message) {
        failed++;
        results.push({ phone: customerPhone ?? 'unknown', success: false, error: 'Missing data' });
        continue;
      }
      
      if (dry_run) {
        console.log(`[sms] [DRY RUN] Would send to ${customerPhone}: ${message.slice(0, 50)}...`);
        sent++;
        results.push({ phone: customerPhone, success: true });
        continue;
      }
      
      try {
        await sendSms(customerPhone, fromNumber, message);
        
        // Log that we sent the message
        await executeAgent('leads', 'send_reengagement', {
          business_id: item.business_id,
          customer_id: item.customer_id,
          rule_id: item.rule_id,
          message
        });
        
        sent++;
        results.push({ phone: customerPhone, success: true });
      } catch (err) {
        console.error(`[sms] Failed to send to ${customerPhone}:`, err);
        failed++;
        results.push({ phone: customerPhone, success: false, error: String(err) });
      }
    }
    
    res.json({
      success: true,
      dry_run,
      total_pending: pending.length,
      sent,
      failed,
      results
    });
  } catch (err) {
    console.error('[sms] Failed to process re-engagements:', err);
    res.status(500).json({ error: 'Failed to process re-engagements', details: String(err) });
  }
});

// Helper to get the from number for a business
async function getFromNumber(businessId: string): Promise<string | null> {
  try {
    const businesses = getAllBusinesses();
    const business = businesses.find((b: { id: string }) => b.id === businessId);
    return business?.customer_number ?? null;
  } catch {
    return null;
  }
}

// Get re-engagement stats for a business
router.get('/reengagement/stats/:businessId', async (req: Request, res: Response) => {
  const { businessId } = req.params;
  
  try {
    const agentFieldHealthy = await healthCheck();
    if (!agentFieldHealthy) {
      res.status(503).json({ error: 'AgentField not available' });
      return;
    }
    
    const result = await executeAgent('leads', 'get_stats', {
      business_id: businessId
    });
    res.json(result.output ?? {});
  } catch (err) {
    console.error('[sms] Failed to get stats:', err);
    res.status(500).json({ error: 'Failed to get stats', details: String(err) });
  }
});

export default router;
