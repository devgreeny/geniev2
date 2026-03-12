import Database from 'better-sqlite3';
import fs from 'fs';
import path from 'path';

interface Business {
  id: string;
  owner_name: string;
  business_name: string;
  services: string | null;
  pricing: string | null;
  location: string | null;
  hours: string | null;
  availability: string | null;
  custom_context: string | null;
  owner_phone: string;
  customer_phone: string;
  private_number: string;
  customer_number: string;
}

let db: Database.Database;

export function initDb(): void {
  const dbPath = process.env.DATABASE_PATH ?? './genie.db';
  console.log(`[db] Using database: ${dbPath}`);
  db = new Database(dbPath);
  db.pragma('journal_mode = WAL');
  db.pragma('foreign_keys = ON');

  const schemaPath = path.join(path.dirname(new URL(import.meta.url).pathname), '../../schema.sql');
  if (fs.existsSync(schemaPath)) {
    const schema = fs.readFileSync(schemaPath, 'utf8');
    db.exec(schema);
  }
  
  // Debug: check if businesses exist
  const count = db.prepare('SELECT COUNT(*) as cnt FROM businesses').get() as { cnt: number };
  console.log(`[db] Found ${count.cnt} businesses`);
}

export function getDb(): Database.Database {
  if (!db) throw new Error('DB not initialized');
  return db;
}

export function getBusinessByCustomerNumber(number: string): Business | null {
  return getDb().prepare('SELECT * FROM businesses WHERE customer_number = ?').get(number) as Business | null;
}

export function getBusinessByPrivateNumber(number: string): Business | null {
  return getDb().prepare('SELECT * FROM businesses WHERE private_number = ?').get(number) as Business | null;
}

export function saveMessage(
  businessId: string,
  phone: string,
  role: 'owner' | 'customer',
  direction: 'inbound' | 'outbound',
  message: string
): void {
  const id = crypto.randomUUID();
  getDb()
    .prepare(
      'INSERT INTO conversations (id, business_id, participant_phone, role, direction, message) VALUES (?, ?, ?, ?, ?, ?)'
    )
    .run(id, businessId, phone, role, direction, message);
}

export function getAllBusinesses(): Business[] {
  return getDb().prepare('SELECT * FROM businesses').all() as Business[];
}

export function getBusinessById(businessId: string): Business | null {
  return getDb().prepare('SELECT * FROM businesses WHERE id = ?').get(businessId) as Business | null;
}

// ============== SMS Message Tracking ==============

interface SmsMessage {
  id: string;
  vonage_message_id: string | null;
  business_id: string | null;
  direction: 'inbound' | 'outbound';
  from_number: string;
  to_number: string;
  body: string;
  status: string;
  status_timestamp: string | null;
  error_code: string | null;
  error_reason: string | null;
  created_at: string;
  updated_at: string;
}

export interface SaveSmsMessageInput {
  vonageMessageId: string | null;
  businessId: string | null;
  direction: 'inbound' | 'outbound';
  fromNumber: string;
  toNumber: string;
  body: string;
  status: string;
}

/**
 * Save an SMS message to the tracking table
 * Returns the created message ID
 */
export function saveSmsMessage(input: SaveSmsMessageInput): string {
  const id = crypto.randomUUID();
  getDb()
    .prepare(`
      INSERT INTO sms_messages 
      (id, vonage_message_id, business_id, direction, from_number, to_number, body, status, status_timestamp)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    `)
    .run(
      id,
      input.vonageMessageId,
      input.businessId,
      input.direction,
      input.fromNumber,
      input.toNumber,
      input.body,
      input.status,
      new Date().toISOString()
    );
  return id;
}

/**
 * Get an SMS message by Vonage message ID (for idempotency check)
 */
export function getSmsMessageByVonageId(vonageMessageId: string): SmsMessage | null {
  return getDb()
    .prepare('SELECT * FROM sms_messages WHERE vonage_message_id = ?')
    .get(vonageMessageId) as SmsMessage | null;
}

/**
 * Update SMS message status (for delivery callbacks)
 */
export function updateSmsStatus(
  vonageMessageId: string,
  update: {
    status: string;
    errorCode?: string;
    errorReason?: string;
    timestamp?: string;
  }
): boolean {
  const result = getDb()
    .prepare(`
      UPDATE sms_messages 
      SET status = ?, error_code = ?, error_reason = ?, status_timestamp = ?, updated_at = ?
      WHERE vonage_message_id = ?
    `)
    .run(
      update.status,
      update.errorCode ?? null,
      update.errorReason ?? null,
      update.timestamp ?? new Date().toISOString(),
      new Date().toISOString(),
      vonageMessageId
    );
  return result.changes > 0;
}

/**
 * Get SMS messages by business ID (for dashboard/debugging)
 */
export function getSmsByBusinessId(businessId: string, limit = 50): SmsMessage[] {
  return getDb()
    .prepare(`
      SELECT * FROM sms_messages 
      WHERE business_id = ? 
      ORDER BY created_at DESC 
      LIMIT ?
    `)
    .all(businessId, limit) as SmsMessage[];
}

/**
 * Get recent SMS delivery failures (for monitoring)
 */
export function getRecentSmsFailures(limit = 20): SmsMessage[] {
  return getDb()
    .prepare(`
      SELECT * FROM sms_messages 
      WHERE status IN ('failed', 'rejected', 'undeliverable')
      ORDER BY created_at DESC 
      LIMIT ?
    `)
    .all(limit) as SmsMessage[];
}

// ==================== AI Settings ====================

interface AiSettings {
  business_id: string;
  ai_paused: number;
  paused_at: string | null;
  paused_by: string | null;
  updated_at: string;
}

export function getAiSettings(businessId: string): AiSettings {
  const db = getDb();
  let settings = db.prepare('SELECT * FROM ai_settings WHERE business_id = ?').get(businessId) as AiSettings | undefined;
  
  if (!settings) {
    // Create default settings
    db.prepare('INSERT INTO ai_settings (business_id) VALUES (?)').run(businessId);
    settings = db.prepare('SELECT * FROM ai_settings WHERE business_id = ?').get(businessId) as AiSettings;
  }
  
  return settings;
}

export function isAiPaused(businessId: string): boolean {
  const settings = getAiSettings(businessId);
  return settings.ai_paused === 1;
}

export function pauseAi(businessId: string, pausedBy: string): void {
  getDb().prepare(`
    UPDATE ai_settings SET ai_paused = 1, paused_at = CURRENT_TIMESTAMP, paused_by = ?, updated_at = CURRENT_TIMESTAMP
    WHERE business_id = ?
  `).run(pausedBy, businessId);
}

export function resumeAi(businessId: string): void {
  getDb().prepare(`
    UPDATE ai_settings SET ai_paused = 0, paused_at = NULL, paused_by = NULL, updated_at = CURRENT_TIMESTAMP
    WHERE business_id = ?
  `).run(businessId);
}

// ==================== Approval Queue ====================

interface ApprovalQueueItem {
  id: string;
  business_id: string;
  recipient_phone: string;
  recipient_name: string | null;
  message_text: string;
  reason: string | null;
  status: 'pending' | 'approved' | 'rejected' | 'expired';
  created_at: string;
  reviewed_at: string | null;
  reviewed_by: string | null;
}

export function createApprovalRequest(
  businessId: string,
  recipientPhone: string,
  messageText: string,
  reason?: string,
  recipientName?: string
): string {
  const id = crypto.randomUUID();
  getDb().prepare(`
    INSERT INTO approval_queue (id, business_id, recipient_phone, recipient_name, message_text, reason)
    VALUES (?, ?, ?, ?, ?, ?)
  `).run(id, businessId, recipientPhone, recipientName || null, messageText, reason || null);
  return id;
}

export function getPendingApprovals(businessId: string): ApprovalQueueItem[] {
  return getDb().prepare(`
    SELECT * FROM approval_queue 
    WHERE business_id = ? AND status = 'pending'
    ORDER BY created_at DESC
  `).all(businessId) as ApprovalQueueItem[];
}

export function getApprovalById(id: string): ApprovalQueueItem | null {
  return getDb().prepare('SELECT * FROM approval_queue WHERE id = ?').get(id) as ApprovalQueueItem | null;
}

export function approveMessage(id: string, reviewedBy: string): ApprovalQueueItem | null {
  getDb().prepare(`
    UPDATE approval_queue SET status = 'approved', reviewed_at = CURRENT_TIMESTAMP, reviewed_by = ?
    WHERE id = ? AND status = 'pending'
  `).run(reviewedBy, id);
  return getApprovalById(id);
}

export function rejectMessage(id: string, reviewedBy: string): ApprovalQueueItem | null {
  getDb().prepare(`
    UPDATE approval_queue SET status = 'rejected', reviewed_at = CURRENT_TIMESTAMP, reviewed_by = ?
    WHERE id = ? AND status = 'pending'
  `).run(reviewedBy, id);
  return getApprovalById(id);
}

export function getPendingApprovalCount(businessId: string): number {
  const result = getDb().prepare(`
    SELECT COUNT(*) as count FROM approval_queue WHERE business_id = ? AND status = 'pending'
  `).get(businessId) as { count: number };
  return result.count;
}
