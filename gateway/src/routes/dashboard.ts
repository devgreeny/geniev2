import { Router } from 'express';
import type { Request, Response } from 'express';
import { 
  getDb, 
  getPendingApprovals, 
  getApprovalById, 
  approveMessage, 
  rejectMessage,
  getAiSettings,
  pauseAi,
  resumeAi,
  isAiPaused,
  getPendingApprovalCount
} from '../services/db.js';

const router = Router();
const BUSINESS_ID = process.env.DEFAULT_BUSINESS_ID || '';

// Get recent messages
router.get('/messages', (_req: Request, res: Response) => {
  try {
    const db = getDb();
    const messages = db.prepare(`
      SELECT id, direction, message, participant_phone, role, read_at, created_at 
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

// Mark messages as read
router.post('/messages/mark-read', (req: Request, res: Response) => {
  try {
    const db = getDb();
    const { messageIds } = req.body;
    if (Array.isArray(messageIds) && messageIds.length > 0) {
      const placeholders = messageIds.map(() => '?').join(',');
      db.prepare(`
        UPDATE conversations SET read_at = CURRENT_TIMESTAMP 
        WHERE id IN (${placeholders}) AND business_id = ?
      `).run(...messageIds, BUSINESS_ID);
    }
    res.json({ success: true });
  } catch (err) {
    console.error('[dashboard] Error marking messages read:', err);
    res.status(500).json({ error: 'Failed to mark messages read' });
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

// ==================== AI Settings ====================

// Get AI settings (pause state)
router.get('/ai-settings', (_req: Request, res: Response) => {
  try {
    const settings = getAiSettings(BUSINESS_ID);
    res.json(settings);
  } catch (err) {
    console.error('[dashboard] Error fetching AI settings:', err);
    res.status(500).json({ error: 'Failed to fetch AI settings' });
  }
});

// Pause AI
router.post('/ai/pause', (req: Request, res: Response) => {
  try {
    const pausedBy = req.body.paused_by || 'dashboard';
    pauseAi(BUSINESS_ID, pausedBy);
    res.json({ success: true, message: 'AI paused', ai_paused: true });
  } catch (err) {
    console.error('[dashboard] Error pausing AI:', err);
    res.status(500).json({ error: 'Failed to pause AI' });
  }
});

// Resume AI
router.post('/ai/resume', (_req: Request, res: Response) => {
  try {
    resumeAi(BUSINESS_ID);
    res.json({ success: true, message: 'AI resumed', ai_paused: false });
  } catch (err) {
    console.error('[dashboard] Error resuming AI:', err);
    res.status(500).json({ error: 'Failed to resume AI' });
  }
});

// ==================== Approval Queue ====================

// Get pending approvals
router.get('/approvals', (_req: Request, res: Response) => {
  try {
    const approvals = getPendingApprovals(BUSINESS_ID);
    res.json(approvals);
  } catch (err) {
    console.error('[dashboard] Error fetching approvals:', err);
    res.status(500).json({ error: 'Failed to fetch approvals' });
  }
});

// Get approval count
router.get('/approvals/count', (_req: Request, res: Response) => {
  try {
    const count = getPendingApprovalCount(BUSINESS_ID);
    res.json({ count });
  } catch (err) {
    console.error('[dashboard] Error fetching approval count:', err);
    res.status(500).json({ error: 'Failed to fetch approval count' });
  }
});

// Get single approval
router.get('/approvals/:id', (req: Request, res: Response) => {
  try {
    const approval = getApprovalById(req.params.id);
    if (!approval) {
      res.status(404).json({ error: 'Approval not found' });
      return;
    }
    res.json(approval);
  } catch (err) {
    console.error('[dashboard] Error fetching approval:', err);
    res.status(500).json({ error: 'Failed to fetch approval' });
  }
});

// Approve a message
router.post('/approvals/:id/approve', (req: Request, res: Response) => {
  try {
    const reviewedBy = req.body.reviewed_by || 'dashboard';
    const approval = approveMessage(req.params.id, reviewedBy);
    if (!approval) {
      res.status(404).json({ error: 'Approval not found or already processed' });
      return;
    }
    res.json({ success: true, approval });
  } catch (err) {
    console.error('[dashboard] Error approving message:', err);
    res.status(500).json({ error: 'Failed to approve message' });
  }
});

// Reject a message
router.post('/approvals/:id/reject', (req: Request, res: Response) => {
  try {
    const reviewedBy = req.body.reviewed_by || 'dashboard';
    const approval = rejectMessage(req.params.id, reviewedBy);
    if (!approval) {
      res.status(404).json({ error: 'Approval not found or already processed' });
      return;
    }
    res.json({ success: true, approval });
  } catch (err) {
    console.error('[dashboard] Error rejecting message:', err);
    res.status(500).json({ error: 'Failed to reject message' });
  }
});

// ==================== Today View Endpoints ====================

// Get unread conversations count
router.get('/unread-count', (_req: Request, res: Response) => {
  try {
    const db = getDb();
    const result = db.prepare(`
      SELECT COUNT(*) as count FROM conversations 
      WHERE business_id = ? AND direction = 'inbound' AND read_at IS NULL
    `).get(BUSINESS_ID) as { count: number };
    res.json({ count: result?.count || 0 });
  } catch (err) {
    console.error('[dashboard] Error fetching unread count:', err);
    res.status(500).json({ error: 'Failed to fetch unread count' });
  }
});

// Get today's bookings
router.get('/today-bookings', (_req: Request, res: Response) => {
  try {
    const db = getDb();
    const today = new Date().toISOString().split('T')[0];
    const bookings = db.prepare(`
      SELECT * FROM appointments 
      WHERE business_id = ? AND date(datetime) = date(?)
      ORDER BY datetime ASC
    `).all(BUSINESS_ID, today);
    res.json(bookings);
  } catch (err) {
    console.error('[dashboard] Error fetching today bookings:', err);
    res.status(500).json({ error: 'Failed to fetch today bookings' });
  }
});

// Get campaign activity
router.get('/campaign-activity', (_req: Request, res: Response) => {
  try {
    const db = getDb();
    const today = new Date().toISOString().split('T')[0];
    
    // Get recent campaign runs
    const campaigns = db.prepare(`
      SELECT * FROM campaign_runs 
      WHERE business_id = ? AND date(created_at) >= date(?, '-7 days')
      ORDER BY created_at DESC
      LIMIT 50
    `).all(BUSINESS_ID, today);
    
    // Get campaign stats by type
    const stats = db.prepare(`
      SELECT 
        campaign_type,
        COUNT(*) as total_sent,
        SUM(CASE WHEN status = 'replied' THEN 1 ELSE 0 END) as replied,
        SUM(CASE WHEN status = 'booked' THEN 1 ELSE 0 END) as booked
      FROM campaign_runs 
      WHERE business_id = ? AND date(created_at) >= date(?, '-7 days')
      GROUP BY campaign_type
    `).all(BUSINESS_ID, today);
    
    res.json({ campaigns, stats });
  } catch (err) {
    console.error('[dashboard] Error fetching campaign activity:', err);
    res.status(500).json({ error: 'Failed to fetch campaign activity' });
  }
});

// Get funnel metrics (weekly)
router.get('/funnel-metrics', (_req: Request, res: Response) => {
  try {
    const db = getDb();
    const today = new Date().toISOString().split('T')[0];
    
    // Inbound (unique customers this week)
    const inbound = db.prepare(`
      SELECT COUNT(DISTINCT participant_phone) as count 
      FROM conversations 
      WHERE business_id = ? 
        AND direction = 'inbound' 
        AND date(created_at) >= date(?, '-7 days')
    `).get(BUSINESS_ID, today) as { count: number };
    
    // Booked appointments this week
    const booked = db.prepare(`
      SELECT COUNT(*) as count 
      FROM appointments 
      WHERE business_id = ? 
        AND date(created_at) >= date(?, '-7 days')
    `).get(BUSINESS_ID, today) as { count: number };
    
    // Completed appointments this week
    const completed = db.prepare(`
      SELECT COUNT(*) as count 
      FROM appointments 
      WHERE business_id = ? 
        AND status = 'completed'
        AND date(datetime) >= date(?, '-7 days')
    `).get(BUSINESS_ID, today) as { count: number };
    
    const inboundCount = inbound?.count || 0;
    const bookedCount = booked?.count || 0;
    const completedCount = completed?.count || 0;
    
    const conversionRate = inboundCount > 0 
      ? Math.round((bookedCount / inboundCount) * 100) 
      : 0;
    
    const showRate = bookedCount > 0 
      ? Math.round((completedCount / bookedCount) * 100) 
      : 0;
    
    res.json({
      inbound: inboundCount,
      booked: bookedCount,
      completed: completedCount,
      conversion_rate: conversionRate,
      show_rate: showRate,
    });
  } catch (err) {
    console.error('[dashboard] Error fetching funnel metrics:', err);
    res.status(500).json({ error: 'Failed to fetch funnel metrics' });
  }
});

// ==================== Today View Summary ====================

// Get complete "today view" in a single API call
router.get('/today', (_req: Request, res: Response) => {
  try {
    const db = getDb();
    const today = new Date().toISOString().split('T')[0];
    
    // Unread conversations
    const unread = db.prepare(`
      SELECT COUNT(*) as count FROM conversations 
      WHERE business_id = ? AND direction = 'inbound' AND read_at IS NULL
    `).get(BUSINESS_ID) as { count: number };
    
    // Pending approvals
    const pendingApprovals = getPendingApprovalCount(BUSINESS_ID);
    
    // Today's bookings
    const todayBookings = db.prepare(`
      SELECT COUNT(*) as count FROM appointments 
      WHERE business_id = ? AND date(datetime) = date(?)
    `).get(BUSINESS_ID, today) as { count: number };
    
    // Today's bookings list
    const bookingsList = db.prepare(`
      SELECT id, customer_name, customer_phone, service, datetime, status
      FROM appointments 
      WHERE business_id = ? AND date(datetime) = date(?)
      ORDER BY datetime ASC
    `).all(BUSINESS_ID, today);
    
    // Campaign sends today
    const campaignsSent = db.prepare(`
      SELECT COUNT(*) as count FROM campaign_runs 
      WHERE business_id = ? AND date(created_at) = date(?)
    `).get(BUSINESS_ID, today) as { count: number };
    
    // AI status
    const aiPaused = isAiPaused(BUSINESS_ID);
    
    // Funnel metrics (this week)
    const inbound = db.prepare(`
      SELECT COUNT(DISTINCT participant_phone) as count 
      FROM conversations 
      WHERE business_id = ? AND direction = 'inbound' AND date(created_at) >= date(?, '-7 days')
    `).get(BUSINESS_ID, today) as { count: number };
    
    const booked = db.prepare(`
      SELECT COUNT(*) as count 
      FROM appointments 
      WHERE business_id = ? AND date(created_at) >= date(?, '-7 days')
    `).get(BUSINESS_ID, today) as { count: number };
    
    const conversionRate = (inbound?.count || 0) > 0 
      ? Math.round(((booked?.count || 0) / (inbound?.count || 1)) * 100) 
      : 0;
    
    res.json({
      unread_conversations: unread?.count || 0,
      pending_approvals: pendingApprovals,
      today_bookings: todayBookings?.count || 0,
      bookings: bookingsList,
      campaigns_sent_today: campaignsSent?.count || 0,
      ai_paused: aiPaused,
      funnel: {
        inbound: inbound?.count || 0,
        booked: booked?.count || 0,
        conversion_rate: conversionRate,
      }
    });
  } catch (err) {
    console.error('[dashboard] Error fetching today view:', err);
    res.status(500).json({ error: 'Failed to fetch today view' });
  }
});

export default router;
