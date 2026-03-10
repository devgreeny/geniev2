import { Router } from 'express';
import type { Request, Response } from 'express';
import { executeAgent } from '../services/agentfield.js';
import { sendTelegramMessage } from '../services/telegram.js';
import { saveMessage, getDb } from '../services/db.js';

const router = Router();

// Hardcoded for now - Fresh Cuts Barbershop
const BUSINESS_ID = process.env.DEFAULT_BUSINESS_ID || '';
const OWNER_TELEGRAM_ID = process.env.OWNER_TELEGRAM_ID || '';

const FALLBACK_MESSAGE = "We're having a little trouble right now. We'll get back to you shortly!";

function getRecentMessages(businessId: string, participantId: string, limit = 10): string {
  try {
    const db = getDb();
    const rows = db.prepare(`
      SELECT direction, message FROM conversations 
      WHERE business_id = ? AND participant_phone = ?
      ORDER BY created_at DESC LIMIT ?
    `).all(businessId, participantId, limit) as Array<{direction: string, message: string}>;
    
    // Reverse to get chronological order and format as simple string
    const history = rows.reverse().map(row => 
      `${row.direction === 'inbound' ? 'Customer' : 'You'}: ${row.message.substring(0, 200)}`
    ).join('\n');
    
    console.log(`[telegram] Fetched ${rows.length} messages for history`);
    return history;
  } catch (err) {
    console.error('[telegram] Error fetching history:', err);
    return '';
  }
}

interface TelegramUpdate {
  update_id: number;
  message?: {
    message_id: number;
    from: {
      id: number;
      first_name: string;
      username?: string;
    };
    chat: {
      id: number;
      type: string;
    };
    date: number;
    text?: string;
  };
}

router.post('/webhook', async (req: Request, res: Response) => {
  const update = req.body as TelegramUpdate;
  
  // Acknowledge immediately
  res.status(200).send('OK');

  if (!update.message?.text) {
    return;
  }

  const chatId = update.message.chat.id;
  const userId = update.message.from.id;
  const username = update.message.from.username || update.message.from.first_name;
  const text = update.message.text;

  console.log(`[telegram] Message from ${username} (${userId}): ${text}`);

  // Determine if owner or customer based on Telegram ID
  const isOwner = OWNER_TELEGRAM_ID && userId.toString() === OWNER_TELEGRAM_ID;
  const role = isOwner ? 'owner' : 'customer';

  // Save inbound message
  if (BUSINESS_ID) {
    saveMessage(BUSINESS_ID, userId.toString(), role, 'inbound', text);
  }

  // Get conversation history for context
  const historyContext = BUSINESS_ID 
    ? getRecentMessages(BUSINESS_ID, userId.toString(), 10)
    : '';

  try {
    const result = await executeAgent('master', 'handle_message', {
      phone: userId.toString(),  // Using Telegram ID as identifier
      message: text,
      business_id: BUSINESS_ID,
      is_owner: isOwner,
      conversation_history: historyContext,
    });

    const response = result.output?.response || FALLBACK_MESSAGE;
    
    await sendTelegramMessage(chatId, response);
    
    if (BUSINESS_ID) {
      saveMessage(BUSINESS_ID, userId.toString(), role, 'outbound', response);
    }
    
    console.log(`[telegram] Response sent to ${username}`);
  } catch (err) {
    console.error('[telegram] Error:', err);
    try {
      await sendTelegramMessage(chatId, FALLBACK_MESSAGE);
    } catch (sendErr) {
      console.error('[telegram] Failed to send fallback:', sendErr);
    }
  }
});

// Health check / info endpoint
router.get('/info', async (_req: Request, res: Response) => {
  res.json({
    configured: !!process.env.TELEGRAM_BOT_TOKEN,
    business_id: BUSINESS_ID || 'not set',
    owner_configured: !!OWNER_TELEGRAM_ID,
  });
});

export default router;
