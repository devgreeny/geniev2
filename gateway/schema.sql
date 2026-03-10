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

CREATE TABLE IF NOT EXISTS conversations (
  id TEXT PRIMARY KEY,
  business_id TEXT NOT NULL REFERENCES businesses(id),
  participant_phone TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('owner', 'customer')),
  direction TEXT NOT NULL CHECK(direction IN ('inbound', 'outbound')),
  message TEXT NOT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS leads (
  id TEXT PRIMARY KEY,
  business_id TEXT NOT NULL REFERENCES businesses(id),
  customer_phone TEXT NOT NULL,
  customer_name TEXT,
  job_description TEXT,
  status TEXT DEFAULT 'new' CHECK(status IN ('new', 'notified', 'booked', 'closed')),
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS appointments (
  id TEXT PRIMARY KEY,
  business_id TEXT NOT NULL REFERENCES businesses(id),
  customer_phone TEXT NOT NULL,
  customer_name TEXT,
  service TEXT NOT NULL,
  datetime TEXT NOT NULL,
  duration INTEGER DEFAULT 60,
  status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'confirmed', 'completed', 'cancelled')),
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

-- Customers table to track customer info and last service dates
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

-- Re-engagement rules - configurable triggers for automated outreach
CREATE TABLE IF NOT EXISTS reengagement_rules (
  id TEXT PRIMARY KEY,
  business_id TEXT NOT NULL REFERENCES businesses(id),
  name TEXT NOT NULL,
  service_type TEXT,  -- NULL means applies to all services
  days_since_last_service INTEGER NOT NULL,  -- e.g. 30 for haircuts, 180 for dental
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
