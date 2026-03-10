import os
import sqlite3
from typing import Optional, List
from uuid import uuid4
from contextlib import contextmanager
from datetime import datetime as dt

from .types import Business, Message, Lead, Appointment, Customer, ReengagementRule, ReengagementLog, ReengagementCampaign

DATABASE_PATH = os.getenv("DATABASE_PATH", "./genie.db")


@contextmanager
def get_db():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.executescript("""
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
                segment TEXT DEFAULT 'regular',
                lifetime_value REAL DEFAULT 0,
                avg_visit_interval INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(business_id, phone)
            );

            CREATE TABLE IF NOT EXISTS reengagement_rules (
                id TEXT PRIMARY KEY,
                business_id TEXT NOT NULL REFERENCES businesses(id),
                name TEXT NOT NULL,
                service_type TEXT,
                days_since_last_service INTEGER NOT NULL,
                max_days INTEGER,
                message_template TEXT NOT NULL,
                enabled INTEGER DEFAULT 1,
                priority INTEGER DEFAULT 0,
                rule_type TEXT DEFAULT 'standard',
                sequence_order INTEGER DEFAULT 1,
                sequence_delay_days INTEGER DEFAULT 0,
                customer_segment TEXT DEFAULT 'all',
                discount_offer TEXT,
                send_window_start INTEGER DEFAULT 9,
                send_window_end INTEGER DEFAULT 18,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS reengagement_log (
                id TEXT PRIMARY KEY,
                business_id TEXT NOT NULL REFERENCES businesses(id),
                customer_id TEXT NOT NULL REFERENCES customers(id),
                rule_id TEXT NOT NULL REFERENCES reengagement_rules(id),
                message_sent TEXT NOT NULL,
                sent_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                response_received INTEGER DEFAULT 0,
                booked_appointment INTEGER DEFAULT 0,
                sequence_position INTEGER DEFAULT 1,
                campaign_id TEXT
            );

            CREATE TABLE IF NOT EXISTS reengagement_campaigns (
                id TEXT PRIMARY KEY,
                business_id TEXT NOT NULL REFERENCES businesses(id),
                customer_id TEXT NOT NULL REFERENCES customers(id),
                campaign_type TEXT NOT NULL,
                status TEXT DEFAULT 'active',
                started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_message_at DATETIME,
                messages_sent INTEGER DEFAULT 0,
                converted INTEGER DEFAULT 0
            );

            -- Index for faster lookups
            CREATE INDEX IF NOT EXISTS idx_customers_segment ON customers(business_id, segment);
            CREATE INDEX IF NOT EXISTS idx_customers_last_service ON customers(business_id, last_service_date);
            CREATE INDEX IF NOT EXISTS idx_reengagement_log_campaign ON reengagement_log(campaign_id);
            CREATE INDEX IF NOT EXISTS idx_campaigns_status ON reengagement_campaigns(business_id, status);
        """)
        conn.commit()


def _migrate_db():
    """Run migrations for new columns (safe to run multiple times)."""
    with get_db() as conn:
        # Check and add missing columns to customers
        cursor = conn.execute("PRAGMA table_info(customers)")
        existing_cols = {row['name'] for row in cursor.fetchall()}
        
        if 'segment' not in existing_cols:
            conn.execute("ALTER TABLE customers ADD COLUMN segment TEXT DEFAULT 'regular'")
        if 'lifetime_value' not in existing_cols:
            conn.execute("ALTER TABLE customers ADD COLUMN lifetime_value REAL DEFAULT 0")
        if 'avg_visit_interval' not in existing_cols:
            conn.execute("ALTER TABLE customers ADD COLUMN avg_visit_interval INTEGER")
        
        # Check and add missing columns to reengagement_rules
        cursor = conn.execute("PRAGMA table_info(reengagement_rules)")
        existing_cols = {row['name'] for row in cursor.fetchall()}
        
        if 'max_days' not in existing_cols:
            conn.execute("ALTER TABLE reengagement_rules ADD COLUMN max_days INTEGER")
        if 'rule_type' not in existing_cols:
            conn.execute("ALTER TABLE reengagement_rules ADD COLUMN rule_type TEXT DEFAULT 'standard'")
        if 'sequence_order' not in existing_cols:
            conn.execute("ALTER TABLE reengagement_rules ADD COLUMN sequence_order INTEGER DEFAULT 1")
        if 'sequence_delay_days' not in existing_cols:
            conn.execute("ALTER TABLE reengagement_rules ADD COLUMN sequence_delay_days INTEGER DEFAULT 0")
        if 'customer_segment' not in existing_cols:
            conn.execute("ALTER TABLE reengagement_rules ADD COLUMN customer_segment TEXT DEFAULT 'all'")
        if 'discount_offer' not in existing_cols:
            conn.execute("ALTER TABLE reengagement_rules ADD COLUMN discount_offer TEXT")
        if 'send_window_start' not in existing_cols:
            conn.execute("ALTER TABLE reengagement_rules ADD COLUMN send_window_start INTEGER DEFAULT 9")
        if 'send_window_end' not in existing_cols:
            conn.execute("ALTER TABLE reengagement_rules ADD COLUMN send_window_end INTEGER DEFAULT 18")
        
        # Check and add missing columns to reengagement_log
        cursor = conn.execute("PRAGMA table_info(reengagement_log)")
        existing_cols = {row['name'] for row in cursor.fetchall()}
        
        if 'sequence_position' not in existing_cols:
            conn.execute("ALTER TABLE reengagement_log ADD COLUMN sequence_position INTEGER DEFAULT 1")
        if 'campaign_id' not in existing_cols:
            conn.execute("ALTER TABLE reengagement_log ADD COLUMN campaign_id TEXT")
        
        # Create campaigns table if needed
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reengagement_campaigns (
                id TEXT PRIMARY KEY,
                business_id TEXT NOT NULL REFERENCES businesses(id),
                customer_id TEXT NOT NULL REFERENCES customers(id),
                campaign_type TEXT NOT NULL,
                status TEXT DEFAULT 'active',
                started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_message_at DATETIME,
                messages_sent INTEGER DEFAULT 0,
                converted INTEGER DEFAULT 0
            )
        """)
        
        conn.commit()


def get_business_by_customer_number(number: str) -> Optional[Business]:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM businesses WHERE customer_number = ?", (number,)
        ).fetchone()
        if row:
            return Business(**dict(row))
    return None


def get_business_by_private_number(number: str) -> Optional[Business]:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM businesses WHERE private_number = ?", (number,)
        ).fetchone()
        if row:
            return Business(**dict(row))
    return None


def get_business_by_id(business_id: str) -> Optional[Business]:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM businesses WHERE id = ?", (business_id,)
        ).fetchone()
        if row:
            return Business(**dict(row))
    return None


def save_message(
    business_id: str,
    phone: str,
    role: str,
    direction: str,
    message: str
) -> str:
    msg_id = str(uuid4())
    with get_db() as conn:
        conn.execute(
            """INSERT INTO conversations 
               (id, business_id, participant_phone, role, direction, message) 
               VALUES (?, ?, ?, ?, ?, ?)""",
            (msg_id, business_id, phone, role, direction, message)
        )
        conn.commit()
    return msg_id


def get_recent_messages(
    business_id: str,
    role: str,
    hours_back: int = 48,
    limit: int = 20
) -> List[Message]:
    with get_db() as conn:
        rows = conn.execute(
            """SELECT * FROM conversations
               WHERE business_id = ? AND role = ?
               AND created_at >= datetime('now', '-' || ? || ' hours')
               ORDER BY created_at DESC
               LIMIT ?""",
            (business_id, role, hours_back, limit)
        ).fetchall()
        return [Message(**dict(row)) for row in rows]


def create_lead(
    business_id: str,
    customer_phone: str,
    job_description: Optional[str] = None,
    customer_name: Optional[str] = None
) -> Lead:
    lead_id = str(uuid4())
    with get_db() as conn:
        conn.execute(
            """INSERT INTO leads 
               (id, business_id, customer_phone, customer_name, job_description) 
               VALUES (?, ?, ?, ?, ?)""",
            (lead_id, business_id, customer_phone, customer_name, job_description)
        )
        conn.commit()
        row = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
        return Lead(**dict(row))


def get_leads_by_phone(business_id: str, phone: str) -> List[Lead]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM leads WHERE business_id = ? AND customer_phone = ?",
            (business_id, phone)
        ).fetchall()
        return [Lead(**dict(row)) for row in rows]


def update_business_context(business_id: str, field: str, value: str):
    allowed = ['availability', 'pricing', 'hours', 'services', 'custom_context']
    if field not in allowed:
        return
    with get_db() as conn:
        conn.execute(
            f"UPDATE businesses SET {field} = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (value, business_id)
        )
        conn.commit()


def create_appointment(
    business_id: str,
    customer_phone: str,
    service: str,
    datetime_str: str,
    duration: int = 60,
    customer_name: Optional[str] = None,
    notes: Optional[str] = None
) -> Appointment:
    appt_id = str(uuid4())
    with get_db() as conn:
        conn.execute(
            """INSERT INTO appointments 
               (id, business_id, customer_phone, customer_name, service, datetime, duration, notes) 
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (appt_id, business_id, customer_phone, customer_name, service, datetime_str, duration, notes)
        )
        conn.commit()
        row = conn.execute("SELECT * FROM appointments WHERE id = ?", (appt_id,)).fetchone()
        return Appointment(**dict(row))


def get_appointments_by_business(business_id: str, status: Optional[str] = None) -> List[Appointment]:
    with get_db() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM appointments WHERE business_id = ? AND status = ? ORDER BY datetime",
                (business_id, status)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM appointments WHERE business_id = ? ORDER BY datetime",
                (business_id,)
            ).fetchall()
        return [Appointment(**dict(row)) for row in rows]


def get_appointments_by_phone(
    business_id: str, 
    phone: str, 
    status: Optional[str] = None,
    upcoming_only: bool = False
) -> List[Appointment]:
    """Get all appointments for a specific customer phone number."""
    with get_db() as conn:
        query = "SELECT * FROM appointments WHERE business_id = ? AND customer_phone = ?"
        params = [business_id, phone]
        
        if status:
            query += " AND status = ?"
            params.append(status)
        
        if upcoming_only:
            query += " AND datetime >= datetime('now')"
        
        query += " ORDER BY datetime"
        
        rows = conn.execute(query, params).fetchall()
        return [Appointment(**dict(row)) for row in rows]


def get_appointment_by_id(appointment_id: str) -> Optional[Appointment]:
    """Get a single appointment by ID."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM appointments WHERE id = ?",
            (appointment_id,)
        ).fetchone()
        if row:
            return Appointment(**dict(row))
    return None


def reschedule_appointment(
    appointment_id: str,
    new_datetime: str,
    notes: Optional[str] = None
) -> Optional[Appointment]:
    """Reschedule an appointment to a new date/time."""
    with get_db() as conn:
        # Get existing appointment
        existing = conn.execute(
            "SELECT * FROM appointments WHERE id = ?",
            (appointment_id,)
        ).fetchone()
        
        if not existing:
            return None
        
        # Update with new datetime
        update_notes = existing['notes'] or ''
        if notes:
            update_notes = f"{update_notes} | Rescheduled: {notes}".strip(' |')
        else:
            old_dt = existing['datetime']
            update_notes = f"{update_notes} | Rescheduled from {old_dt}".strip(' |')
        
        conn.execute(
            """UPDATE appointments 
               SET datetime = ?, notes = ?, status = 'pending'
               WHERE id = ?""",
            (new_datetime, update_notes, appointment_id)
        )
        conn.commit()
        
        row = conn.execute("SELECT * FROM appointments WHERE id = ?", (appointment_id,)).fetchone()
        return Appointment(**dict(row))


def cancel_appointment(appointment_id: str, reason: Optional[str] = None) -> bool:
    """Cancel an appointment. Returns True if successful."""
    with get_db() as conn:
        existing = conn.execute(
            "SELECT * FROM appointments WHERE id = ?",
            (appointment_id,)
        ).fetchone()
        
        if not existing:
            return False
        
        update_notes = existing['notes'] or ''
        cancel_note = f"Cancelled: {reason}" if reason else "Cancelled by customer"
        update_notes = f"{update_notes} | {cancel_note}".strip(' |')
        
        conn.execute(
            """UPDATE appointments 
               SET status = 'cancelled', notes = ?
               WHERE id = ?""",
            (update_notes, appointment_id)
        )
        conn.commit()
        return True


# ============== Customer Functions ==============

def _row_to_customer(row) -> Customer:
    """Convert a database row to a Customer object with proper defaults."""
    d = dict(row)
    return Customer(
        id=d['id'],
        business_id=d['business_id'],
        phone=d['phone'],
        name=d.get('name'),
        email=d.get('email'),
        last_service_date=d.get('last_service_date'),
        last_service_type=d.get('last_service_type'),
        total_visits=d.get('total_visits', 0),
        notes=d.get('notes'),
        opted_out=bool(d.get('opted_out', 0)),
        segment=d.get('segment', 'regular'),
        lifetime_value=d.get('lifetime_value', 0.0) or 0.0,
        avg_visit_interval=d.get('avg_visit_interval'),
        created_at=d['created_at'],
        updated_at=d['updated_at']
    )


def get_or_create_customer(
    business_id: str,
    phone: str,
    name: Optional[str] = None,
    email: Optional[str] = None
) -> Customer:
    """Get existing customer or create a new one."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM customers WHERE business_id = ? AND phone = ?",
            (business_id, phone)
        ).fetchone()
        
        if row:
            return _row_to_customer(row)
        
        # Create new customer
        customer_id = str(uuid4())
        conn.execute(
            """INSERT INTO customers (id, business_id, phone, name, email, segment)
               VALUES (?, ?, ?, ?, ?, 'new')""",
            (customer_id, business_id, phone, name, email)
        )
        conn.commit()
        
        row = conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
        return _row_to_customer(row)


def update_customer_service(
    business_id: str,
    phone: str,
    service_type: str,
    service_date: Optional[str] = None,
    name: Optional[str] = None,
    amount: float = 0.0
) -> Customer:
    """Update customer's last service info (call after completing an appointment)."""
    customer = get_or_create_customer(business_id, phone, name)
    service_date = service_date or dt.now().strftime("%Y-%m-%d")
    
    with get_db() as conn:
        conn.execute(
            """UPDATE customers 
               SET last_service_date = ?, 
                   last_service_type = ?,
                   total_visits = total_visits + 1,
                   lifetime_value = lifetime_value + ?,
                   updated_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (service_date, service_type, amount, customer.id)
        )
        if name and not customer.name:
            conn.execute(
                "UPDATE customers SET name = ? WHERE id = ?",
                (name, customer.id)
            )
        conn.commit()
        
        row = conn.execute("SELECT * FROM customers WHERE id = ?", (customer.id,)).fetchone()
        customer = _row_to_customer(row)
        
        # Auto-update segment after service
        _update_customer_segment(conn, customer)
        
        row = conn.execute("SELECT * FROM customers WHERE id = ?", (customer.id,)).fetchone()
        return _row_to_customer(row)


def _update_customer_segment(conn, customer: Customer):
    """Auto-calculate customer segment based on behavior."""
    # VIP: 5+ visits OR $500+ lifetime value
    # At-risk: No visit in 2x their average interval
    # New: 1 visit
    # Regular: Everyone else
    
    segment = 'regular'
    
    if customer.total_visits <= 1:
        segment = 'new'
    elif customer.total_visits >= 5 or customer.lifetime_value >= 500:
        segment = 'vip'
    elif customer.avg_visit_interval and customer.last_service_date:
        try:
            last_visit = dt.strptime(customer.last_service_date, "%Y-%m-%d").date()
            days_since = (dt.now().date() - last_visit).days
            if days_since > customer.avg_visit_interval * 2:
                segment = 'at_risk'
        except ValueError:
            pass
    
    conn.execute(
        "UPDATE customers SET segment = ? WHERE id = ?",
        (segment, customer.id)
    )
    conn.commit()


def set_customer_opt_out(business_id: str, phone: str, opted_out: bool = True):
    """Mark a customer as opted out of re-engagement messages."""
    with get_db() as conn:
        conn.execute(
            """UPDATE customers 
               SET opted_out = ?, updated_at = CURRENT_TIMESTAMP
               WHERE business_id = ? AND phone = ?""",
            (1 if opted_out else 0, business_id, phone)
        )
        conn.commit()


def set_customer_segment(customer_id: str, segment: str):
    """Manually set customer segment (override auto-calculation)."""
    valid_segments = ['vip', 'at_risk', 'new', 'regular']
    if segment not in valid_segments:
        return
    with get_db() as conn:
        conn.execute(
            "UPDATE customers SET segment = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (segment, customer_id)
        )
        conn.commit()


def get_customers_by_business(business_id: str, segment: Optional[str] = None) -> List[Customer]:
    """Get all customers for a business, optionally filtered by segment."""
    with get_db() as conn:
        if segment:
            rows = conn.execute(
                "SELECT * FROM customers WHERE business_id = ? AND segment = ? ORDER BY updated_at DESC",
                (business_id, segment)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM customers WHERE business_id = ? ORDER BY updated_at DESC",
                (business_id,)
            ).fetchall()
        return [_row_to_customer(row) for row in rows]


def get_customer_by_id(customer_id: str) -> Optional[Customer]:
    """Get a customer by ID."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM customers WHERE id = ?",
            (customer_id,)
        ).fetchone()
        if row:
            return _row_to_customer(row)
    return None


def get_customer_by_phone(business_id: str, phone: str) -> Optional[Customer]:
    """Get a customer by business ID and phone number."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM customers WHERE business_id = ? AND phone = ?",
            (business_id, phone)
        ).fetchone()
        if row:
            return _row_to_customer(row)
    return None


# ============== Re-engagement Rules Functions ==============

def _row_to_rule(row) -> ReengagementRule:
    """Convert a database row to a ReengagementRule object with proper defaults."""
    d = dict(row)
    return ReengagementRule(
        id=d['id'],
        business_id=d['business_id'],
        name=d['name'],
        service_type=d.get('service_type'),
        days_since_last_service=d['days_since_last_service'],
        max_days=d.get('max_days'),
        message_template=d['message_template'],
        enabled=bool(d.get('enabled', 1)),
        priority=d.get('priority', 0),
        rule_type=d.get('rule_type', 'standard'),
        sequence_order=d.get('sequence_order', 1),
        sequence_delay_days=d.get('sequence_delay_days', 0),
        customer_segment=d.get('customer_segment', 'all'),
        discount_offer=d.get('discount_offer'),
        send_window_start=d.get('send_window_start', 9),
        send_window_end=d.get('send_window_end', 18),
        created_at=d['created_at']
    )


def create_reengagement_rule(
    business_id: str,
    name: str,
    days_since_last_service: int,
    message_template: str,
    service_type: Optional[str] = None,
    max_days: Optional[int] = None,
    priority: int = 0,
    rule_type: str = 'standard',
    sequence_order: int = 1,
    sequence_delay_days: int = 0,
    customer_segment: str = 'all',
    discount_offer: Optional[str] = None,
    send_window_start: int = 9,
    send_window_end: int = 18
) -> ReengagementRule:
    """Create a new re-engagement rule."""
    rule_id = str(uuid4())
    with get_db() as conn:
        conn.execute(
            """INSERT INTO reengagement_rules 
               (id, business_id, name, service_type, days_since_last_service, max_days,
                message_template, priority, rule_type, sequence_order, sequence_delay_days,
                customer_segment, discount_offer, send_window_start, send_window_end)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (rule_id, business_id, name, service_type, days_since_last_service, max_days,
             message_template, priority, rule_type, sequence_order, sequence_delay_days,
             customer_segment, discount_offer, send_window_start, send_window_end)
        )
        conn.commit()
        row = conn.execute("SELECT * FROM reengagement_rules WHERE id = ?", (rule_id,)).fetchone()
        return _row_to_rule(row)


def get_reengagement_rules(business_id: str, enabled_only: bool = True, rule_type: Optional[str] = None) -> List[ReengagementRule]:
    """Get re-engagement rules for a business."""
    with get_db() as conn:
        query = "SELECT * FROM reengagement_rules WHERE business_id = ?"
        params = [business_id]
        
        if enabled_only:
            query += " AND enabled = 1"
        if rule_type:
            query += " AND rule_type = ?"
            params.append(rule_type)
        
        query += " ORDER BY priority DESC, sequence_order ASC"
        
        rows = conn.execute(query, params).fetchall()
        return [_row_to_rule(row) for row in rows]


def toggle_reengagement_rule(rule_id: str, enabled: bool):
    """Enable or disable a re-engagement rule."""
    with get_db() as conn:
        conn.execute(
            "UPDATE reengagement_rules SET enabled = ? WHERE id = ?",
            (1 if enabled else 0, rule_id)
        )
        conn.commit()


def delete_reengagement_rule(rule_id: str):
    """Delete a re-engagement rule."""
    with get_db() as conn:
        conn.execute("DELETE FROM reengagement_rules WHERE id = ?", (rule_id,))
        conn.commit()


# ============== Campaign Functions ==============

def create_campaign(
    business_id: str,
    customer_id: str,
    campaign_type: str
) -> ReengagementCampaign:
    """Create a new re-engagement campaign for a customer."""
    campaign_id = str(uuid4())
    with get_db() as conn:
        conn.execute(
            """INSERT INTO reengagement_campaigns 
               (id, business_id, customer_id, campaign_type)
               VALUES (?, ?, ?, ?)""",
            (campaign_id, business_id, customer_id, campaign_type)
        )
        conn.commit()
        row = conn.execute("SELECT * FROM reengagement_campaigns WHERE id = ?", (campaign_id,)).fetchone()
        d = dict(row)
        return ReengagementCampaign(
            id=d['id'],
            business_id=d['business_id'],
            customer_id=d['customer_id'],
            campaign_type=d['campaign_type'],
            status=d['status'],
            started_at=d['started_at'],
            last_message_at=d.get('last_message_at'),
            messages_sent=d.get('messages_sent', 0),
            converted=bool(d.get('converted', 0))
        )


def get_active_campaign(business_id: str, customer_id: str) -> Optional[ReengagementCampaign]:
    """Get active campaign for a customer (if any)."""
    with get_db() as conn:
        row = conn.execute(
            """SELECT * FROM reengagement_campaigns 
               WHERE business_id = ? AND customer_id = ? AND status = 'active'
               ORDER BY started_at DESC LIMIT 1""",
            (business_id, customer_id)
        ).fetchone()
        if row:
            d = dict(row)
            return ReengagementCampaign(
                id=d['id'],
                business_id=d['business_id'],
                customer_id=d['customer_id'],
                campaign_type=d['campaign_type'],
                status=d['status'],
                started_at=d['started_at'],
                last_message_at=d.get('last_message_at'),
                messages_sent=d.get('messages_sent', 0),
                converted=bool(d.get('converted', 0))
            )
    return None


def update_campaign(campaign_id: str, status: Optional[str] = None, converted: Optional[bool] = None):
    """Update campaign status."""
    with get_db() as conn:
        if status:
            conn.execute(
                "UPDATE reengagement_campaigns SET status = ? WHERE id = ?",
                (status, campaign_id)
            )
        if converted is not None:
            conn.execute(
                "UPDATE reengagement_campaigns SET converted = ?, status = 'converted' WHERE id = ?",
                (1 if converted else 0, campaign_id)
            )
        conn.commit()


# ============== Re-engagement Discovery Functions ==============

def get_customers_due_for_reengagement(business_id: str, current_hour: Optional[int] = None) -> List[dict]:
    """
    Find customers who are due for re-engagement based on rules.
    Returns list of {customer, rule, days_since_service, campaign} dicts.
    
    Args:
        business_id: The business ID
        current_hour: Current hour (0-23) for send window filtering. If None, uses current time.
    """
    if current_hour is None:
        current_hour = dt.now().hour
    
    rules = get_reengagement_rules(business_id, enabled_only=True)
    if not rules:
        return []
    
    results = []
    today = dt.now().date()
    
    with get_db() as conn:
        # Get all active customers (not opted out, have a last service date)
        customers = conn.execute(
            """SELECT * FROM customers 
               WHERE business_id = ? 
               AND opted_out = 0 
               AND last_service_date IS NOT NULL""",
            (business_id,)
        ).fetchall()
        
        for cust_row in customers:
            customer = _row_to_customer(cust_row)
            
            if not customer.last_service_date:
                continue
                
            try:
                last_service = dt.strptime(customer.last_service_date, "%Y-%m-%d").date()
            except ValueError:
                continue
                
            days_since = (today - last_service).days
            
            # Check for active campaign
            active_campaign = get_active_campaign(business_id, customer.id)
            
            # Check each rule (already sorted by priority, then sequence_order)
            for rule in rules:
                # Check send window
                if not (rule.send_window_start <= current_hour < rule.send_window_end):
                    continue
                
                # Skip if rule is for a specific service and doesn't match
                if rule.service_type and rule.service_type != customer.last_service_type:
                    continue
                
                # Check customer segment (if rule targets specific segment)
                if rule.customer_segment != 'all' and rule.customer_segment != customer.segment:
                    continue
                
                # Check if customer is in the right day window
                if days_since < rule.days_since_last_service:
                    continue
                if rule.max_days and days_since > rule.max_days:
                    continue
                
                # For follow-up rules, check if previous message in sequence was sent
                if rule.rule_type == 'followup' and rule.sequence_order > 1:
                    # Need to have an active campaign with correct sequence position
                    if not active_campaign:
                        continue
                    if active_campaign.messages_sent != rule.sequence_order - 1:
                        continue
                    # Check delay since last message
                    if active_campaign.last_message_at:
                        try:
                            last_msg = dt.strptime(active_campaign.last_message_at[:10], "%Y-%m-%d").date()
                            if (today - last_msg).days < rule.sequence_delay_days:
                                continue
                        except ValueError:
                            pass
                
                # Check if we've already sent this rule's message recently (within 7 days)
                recent = conn.execute(
                    """SELECT id FROM reengagement_log 
                       WHERE customer_id = ? AND rule_id = ?
                       AND sent_at >= datetime('now', '-7 days')""",
                    (customer.id, rule.id)
                ).fetchone()
                
                if not recent:
                    results.append({
                        "customer": customer,
                        "rule": rule,
                        "days_since_service": days_since,
                        "campaign": active_campaign
                    })
                    break  # Only match first (highest priority) rule per customer
    
    return results


def log_reengagement_sent(
    business_id: str,
    customer_id: str,
    rule_id: str,
    message_sent: str,
    campaign_id: Optional[str] = None,
    sequence_position: int = 1
) -> str:
    """Log that a re-engagement message was sent."""
    log_id = str(uuid4())
    with get_db() as conn:
        conn.execute(
            """INSERT INTO reengagement_log 
               (id, business_id, customer_id, rule_id, message_sent, campaign_id, sequence_position)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (log_id, business_id, customer_id, rule_id, message_sent, campaign_id, sequence_position)
        )
        
        # Update campaign if exists
        if campaign_id:
            conn.execute(
                """UPDATE reengagement_campaigns 
                   SET messages_sent = messages_sent + 1, last_message_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (campaign_id,)
            )
        
        conn.commit()
    return log_id


def mark_reengagement_responded(customer_id: str, booked: bool = False):
    """Mark the most recent re-engagement as responded to."""
    with get_db() as conn:
        conn.execute(
            """UPDATE reengagement_log 
               SET response_received = 1, booked_appointment = ?
               WHERE customer_id = ?
               AND sent_at = (SELECT MAX(sent_at) FROM reengagement_log WHERE customer_id = ?)""",
            (1 if booked else 0, customer_id, customer_id)
        )
        
        # If booked, mark campaign as converted
        if booked:
            conn.execute(
                """UPDATE reengagement_campaigns 
                   SET status = 'converted', converted = 1
                   WHERE customer_id = ? AND status = 'active'""",
                (customer_id,)
            )
        
        conn.commit()


def get_recent_reengagement(business_id: str, customer_id: str, days: int = 7) -> Optional[ReengagementLog]:
    """
    Check if a customer received a re-engagement message recently.
    Returns the most recent one if found (and not yet responded to).
    """
    with get_db() as conn:
        row = conn.execute(
            """SELECT * FROM reengagement_log 
               WHERE business_id = ? AND customer_id = ? 
               AND response_received = 0
               AND sent_at >= datetime('now', '-' || ? || ' days')
               ORDER BY sent_at DESC LIMIT 1""",
            (business_id, customer_id, days)
        ).fetchone()
        
        if row:
            d = dict(row)
            return ReengagementLog(
                id=d['id'],
                business_id=d['business_id'],
                customer_id=d['customer_id'],
                rule_id=d['rule_id'],
                message_sent=d['message_sent'],
                sent_at=d['sent_at'],
                response_received=bool(d.get('response_received', 0)),
                booked_appointment=bool(d.get('booked_appointment', 0)),
                sequence_position=d.get('sequence_position', 1),
                campaign_id=d.get('campaign_id')
            )
    return None


def get_reengagement_stats(business_id: str) -> dict:
    """Get re-engagement statistics for a business."""
    with get_db() as conn:
        total = conn.execute(
            "SELECT COUNT(*) as c FROM reengagement_log WHERE business_id = ?",
            (business_id,)
        ).fetchone()['c']
        
        responded = conn.execute(
            "SELECT COUNT(*) as c FROM reengagement_log WHERE business_id = ? AND response_received = 1",
            (business_id,)
        ).fetchone()['c']
        
        booked = conn.execute(
            "SELECT COUNT(*) as c FROM reengagement_log WHERE business_id = ? AND booked_appointment = 1",
            (business_id,)
        ).fetchone()['c']
        
        # Stats by rule type
        by_type = {}
        types = conn.execute(
            """SELECT r.rule_type, COUNT(*) as sent, 
               SUM(l.response_received) as responses,
               SUM(l.booked_appointment) as bookings
               FROM reengagement_log l
               JOIN reengagement_rules r ON l.rule_id = r.id
               WHERE l.business_id = ?
               GROUP BY r.rule_type""",
            (business_id,)
        ).fetchall()
        for row in types:
            by_type[row['rule_type']] = {
                'sent': row['sent'],
                'responses': row['responses'] or 0,
                'bookings': row['bookings'] or 0
            }
        
        # Stats by customer segment
        by_segment = {}
        segments = conn.execute(
            """SELECT c.segment, COUNT(*) as sent,
               SUM(l.response_received) as responses,
               SUM(l.booked_appointment) as bookings
               FROM reengagement_log l
               JOIN customers c ON l.customer_id = c.id
               WHERE l.business_id = ?
               GROUP BY c.segment""",
            (business_id,)
        ).fetchall()
        for row in segments:
            by_segment[row['segment'] or 'unknown'] = {
                'sent': row['sent'],
                'responses': row['responses'] or 0,
                'bookings': row['bookings'] or 0
            }
        
        return {
            "total_sent": total,
            "responses": responded,
            "bookings": booked,
            "response_rate": (responded / total * 100) if total > 0 else 0,
            "booking_rate": (booked / total * 100) if total > 0 else 0,
            "by_rule_type": by_type,
            "by_customer_segment": by_segment
        }


def get_all_businesses() -> List[Business]:
    """Get all businesses (for batch processing)."""
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM businesses").fetchall()
        return [Business(**dict(row)) for row in rows]
