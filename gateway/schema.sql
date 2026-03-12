-- ================================================
-- GENIE v2 DATABASE SCHEMA
-- Core tables for SMS assistant pilot
-- ================================================

CREATE TABLE IF NOT EXISTS businesses (
  id TEXT PRIMARY KEY,
  owner_name TEXT NOT NULL,
  business_name TEXT NOT NULL,
  services TEXT,
  pricing TEXT,
  location TEXT,
  hours TEXT,
  availability TEXT,
  custom_context TEXT,
  owner_phone TEXT NOT NULL UNIQUE,
  customer_phone TEXT NOT NULL UNIQUE,
  private_number TEXT NOT NULL,
  customer_number TEXT NOT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ================================================
-- CONVERSATIONS & MESSAGES
-- ================================================

CREATE TABLE IF NOT EXISTS conversations (
  id TEXT PRIMARY KEY,
  business_id TEXT NOT NULL REFERENCES businesses(id),
  participant_phone TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('owner', 'customer')),
  direction TEXT NOT NULL CHECK(direction IN ('inbound', 'outbound')),
  message TEXT NOT NULL,
  read_at DATETIME,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- SMS messages for Vonage tracking with idempotency and delivery status
CREATE TABLE IF NOT EXISTS sms_messages (
  id TEXT PRIMARY KEY,
  vonage_message_id TEXT UNIQUE,  -- Vonage's message UUID for idempotency
  business_id TEXT REFERENCES businesses(id),
  direction TEXT NOT NULL CHECK(direction IN ('inbound', 'outbound')),
  from_number TEXT NOT NULL,
  to_number TEXT NOT NULL,
  body TEXT NOT NULL,
  status TEXT DEFAULT 'received' CHECK(status IN ('received', 'queued', 'submitted', 'delivered', 'failed', 'rejected')),
  status_timestamp DATETIME,
  error_code TEXT,
  error_reason TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_sms_vonage_message_id ON sms_messages(vonage_message_id);
CREATE INDEX IF NOT EXISTS idx_sms_business_id ON sms_messages(business_id);
CREATE INDEX IF NOT EXISTS idx_sms_status ON sms_messages(status);

-- ================================================
-- LEADS & CUSTOMERS
-- ================================================

CREATE TABLE IF NOT EXISTS leads (
  id TEXT PRIMARY KEY,
  business_id TEXT NOT NULL REFERENCES businesses(id),
  customer_phone TEXT NOT NULL,
  customer_name TEXT,
  job_description TEXT,
  status TEXT DEFAULT 'new' CHECK(status IN ('new', 'notified', 'booked', 'closed')),
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS customers (
  id TEXT PRIMARY KEY,
  business_id TEXT NOT NULL REFERENCES businesses(id),
  phone TEXT NOT NULL,
  name TEXT,
  email TEXT,
  last_service_date TEXT,
  last_service_type TEXT,
  total_visits INTEGER DEFAULT 0,
  notes TEXT,
  opted_out INTEGER DEFAULT 0,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(business_id, phone)
);

-- ================================================
-- APPOINTMENTS & INVOICES
-- ================================================

CREATE TABLE IF NOT EXISTS appointments (
  id TEXT PRIMARY KEY,
  business_id TEXT NOT NULL REFERENCES businesses(id),
  customer_phone TEXT NOT NULL,
  customer_name TEXT,
  service TEXT NOT NULL,
  datetime TEXT NOT NULL,
  duration INTEGER DEFAULT 60,
  status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'confirmed', 'completed', 'cancelled', 'no_show')),
  notes TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS invoices (
  id TEXT PRIMARY KEY,
  business_id TEXT NOT NULL REFERENCES businesses(id),
  customer_phone TEXT NOT NULL,
  amount REAL NOT NULL,
  description TEXT NOT NULL,
  status TEXT DEFAULT 'draft' CHECK(status IN ('draft', 'sent', 'paid', 'overdue')),
  due_date TEXT,
  paid_at TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ================================================
-- AI SETTINGS & OWNER CONTROL
-- ================================================

CREATE TABLE IF NOT EXISTS ai_settings (
  business_id TEXT PRIMARY KEY REFERENCES businesses(id),
  ai_paused INTEGER DEFAULT 0,
  paused_at DATETIME,
  paused_by TEXT,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Approval queue for sensitive outbound messages
CREATE TABLE IF NOT EXISTS approval_queue (
  id TEXT PRIMARY KEY,
  business_id TEXT NOT NULL REFERENCES businesses(id),
  recipient_phone TEXT NOT NULL,
  recipient_name TEXT,
  message_text TEXT NOT NULL,
  reason TEXT,  -- why this needs approval (e.g. 'promotional', 'cancellation', 'high_value')
  status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'approved', 'rejected', 'expired')),
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  reviewed_at DATETIME,
  reviewed_by TEXT
);

-- ================================================
-- RETENTION CAMPAIGNS
-- ================================================

-- Re-engagement rules - configurable triggers for automated outreach
CREATE TABLE IF NOT EXISTS reengagement_rules (
  id TEXT PRIMARY KEY,
  business_id TEXT NOT NULL REFERENCES businesses(id),
  name TEXT NOT NULL,
  service_type TEXT,  -- NULL means applies to all services
  days_since_last_service INTEGER NOT NULL,
  message_template TEXT NOT NULL,  -- Uses {name}, {service}, {business_name}, {days} placeholders
  enabled INTEGER DEFAULT 1,
  priority INTEGER DEFAULT 0,  -- Higher = checked first
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Track sent re-engagement messages to avoid spamming
CREATE TABLE IF NOT EXISTS reengagement_log (
  id TEXT PRIMARY KEY,
  business_id TEXT NOT NULL REFERENCES businesses(id),
  customer_id TEXT NOT NULL REFERENCES customers(id),
  rule_id TEXT NOT NULL REFERENCES reengagement_rules(id),
  message_sent TEXT NOT NULL,
  sent_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  response_received INTEGER DEFAULT 0,
  booked_appointment INTEGER DEFAULT 0
);

-- Campaign run logs for tracking retention campaign executions
CREATE TABLE IF NOT EXISTS campaign_runs (
  id TEXT PRIMARY KEY,
  business_id TEXT NOT NULL REFERENCES businesses(id),
  campaign_type TEXT NOT NULL CHECK(campaign_type IN ('no_show_rescue', 'win_back_30', 'win_back_60', 'post_visit_rebook')),
  started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  completed_at DATETIME,
  customers_targeted INTEGER DEFAULT 0,
  messages_sent INTEGER DEFAULT 0,
  messages_failed INTEGER DEFAULT 0,
  skipped_opted_out INTEGER DEFAULT 0,
  skipped_already_booked INTEGER DEFAULT 0,
  skipped_already_contacted INTEGER DEFAULT 0,
  status TEXT DEFAULT 'running' CHECK(status IN ('running', 'completed', 'failed'))
);

-- Track individual campaign messages sent
CREATE TABLE IF NOT EXISTS campaign_messages (
  id TEXT PRIMARY KEY,
  campaign_run_id TEXT NOT NULL REFERENCES campaign_runs(id),
  business_id TEXT NOT NULL REFERENCES businesses(id),
  customer_phone TEXT NOT NULL,
  customer_name TEXT,
  campaign_type TEXT NOT NULL,
  trigger_reason TEXT,  -- e.g., 'no_show:appt_id', '30_days_since_visit', 'completed_visit:appt_id'
  message_sent TEXT NOT NULL,
  sent_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  response_received INTEGER DEFAULT 0,
  booked_after INTEGER DEFAULT 0,
  stop_reason TEXT  -- NULL if active, 'replied', 'booked', 'opted_out' if stopped
);
