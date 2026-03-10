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
