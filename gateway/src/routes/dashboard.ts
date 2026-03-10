import { Router } from 'express';
import type { Request, Response } from 'express';
import { getDb } from '../services/db.js';

const router = Router();
const BUSINESS_ID = process.env.DEFAULT_BUSINESS_ID || '';

// Get recent messages
router.get('/messages', (_req: Request, res: Response) => {
  try {
    const db = getDb();
    const messages = db.prepare(`
      SELECT id, direction, message, participant_phone, role, created_at 
      FROM conversations 
      WHERE business_id = ?
      ORDER BY created_at DESC 
      LIMIT 100
    `).all(BUSINESS_ID);
    res.json(messages);
  } catch (err) {
    console.error('[dashboard] Error fetching messages:', err);
    res.status(500).json({ error: 'Failed to fetch messages' });
  }
});

// Get business info
router.get('/business', (_req: Request, res: Response) => {
  try {
    const db = getDb();
    const business = db.prepare('SELECT * FROM businesses WHERE id = ?').get(BUSINESS_ID);
    if (business) {
      res.json(business);
    } else {
      res.status(404).json({ error: 'Business not found' });
    }
  } catch (err) {
    console.error('[dashboard] Error fetching business:', err);
    res.status(500).json({ error: 'Failed to fetch business' });
  }
});

// Update business info
router.put('/business', (req: Request, res: Response) => {
  try {
    const db = getDb();
    const { business_name, services, pricing, hours, availability, custom_context } = req.body;
    
    db.prepare(`
      UPDATE businesses SET 
        business_name = ?, services = ?, pricing = ?, hours = ?, 
        availability = ?, custom_context = ?, updated_at = CURRENT_TIMESTAMP
      WHERE id = ?
    `).run(business_name, services, pricing, hours, availability, custom_context, BUSINESS_ID);
    
    const updated = db.prepare('SELECT * FROM businesses WHERE id = ?').get(BUSINESS_ID);
    res.json(updated);
  } catch (err) {
    console.error('[dashboard] Error updating business:', err);
    res.status(500).json({ error: 'Failed to update business' });
  }
});

// Get leads
router.get('/leads', (_req: Request, res: Response) => {
  try {
    const db = getDb();
    const leads = db.prepare(`
      SELECT * FROM leads 
      WHERE business_id = ?
      ORDER BY created_at DESC
    `).all(BUSINESS_ID);
    res.json(leads);
  } catch (err) {
    console.error('[dashboard] Error fetching leads:', err);
    res.status(500).json({ error: 'Failed to fetch leads' });
  }
});

// Get stats
router.get('/stats', (_req: Request, res: Response) => {
  try {
    const db = getDb();
    
    const today = new Date().toISOString().split('T')[0];
    
    const messagesToday = db.prepare(`
      SELECT COUNT(*) as count FROM conversations 
      WHERE business_id = ? AND date(created_at) = date(?)
    `).get(BUSINESS_ID, today) as { count: number };
    
    const totalMessages = db.prepare(`
      SELECT COUNT(*) as count FROM conversations WHERE business_id = ?
    `).get(BUSINESS_ID) as { count: number };
    
    const newLeads = db.prepare(`
      SELECT COUNT(*) as count FROM leads WHERE business_id = ? AND status = 'new'
    `).get(BUSINESS_ID) as { count: number };
    
    const activeCustomers = db.prepare(`
      SELECT COUNT(DISTINCT participant_phone) as count FROM conversations 
      WHERE business_id = ? AND role = 'customer' AND created_at > datetime('now', '-7 days')
    `).get(BUSINESS_ID) as { count: number };
    
    res.json({
      messages_today: messagesToday?.count || 0,
      total_conversations: totalMessages?.count || 0,
      new_leads: newLeads?.count || 0,
      active_customers: activeCustomers?.count || 0,
    });
  } catch (err) {
    console.error('[dashboard] Error fetching stats:', err);
    res.status(500).json({ error: 'Failed to fetch stats' });
  }
});

export default router;
