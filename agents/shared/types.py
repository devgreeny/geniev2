from dataclasses import dataclass
from typing import Optional
from datetime import datetime


@dataclass
class Business:
    id: str
    owner_name: str
    business_name: str
    services: Optional[str]
    pricing: Optional[str]
    location: Optional[str]
    hours: Optional[str]
    availability: Optional[str]
    custom_context: Optional[str]
    owner_phone: str
    customer_phone: str
    private_number: str
    customer_number: str
    created_at: str
    updated_at: str


@dataclass
class Message:
    id: str
    business_id: str
    participant_phone: str
    role: str  # 'owner' | 'customer'
    direction: str  # 'inbound' | 'outbound'
    message: str
    created_at: str


@dataclass
class Lead:
    id: str
    business_id: str
    customer_phone: str
    customer_name: Optional[str]
    job_description: Optional[str]
    status: str  # 'new' | 'notified' | 'booked' | 'closed'
    created_at: str


@dataclass
class Appointment:
    id: str
    business_id: str
    customer_phone: str
    customer_name: Optional[str]
    service: str
    datetime: str
    duration: int  # minutes
    status: str  # 'pending' | 'confirmed' | 'completed' | 'cancelled'
    notes: Optional[str]
    created_at: str


@dataclass 
class Invoice:
    id: str
    business_id: str
    customer_phone: str
    amount: float
    description: str
    status: str  # 'draft' | 'sent' | 'paid' | 'overdue'
    due_date: Optional[str]
    paid_at: Optional[str]
    created_at: str


@dataclass
class Customer:
    id: str
    business_id: str
    phone: str
    name: Optional[str]
    email: Optional[str]
    last_service_date: Optional[str]
    last_service_type: Optional[str]
    total_visits: int
    notes: Optional[str]
    opted_out: bool
    segment: Optional[str]  # 'vip', 'at_risk', 'new', 'regular' - auto-calculated or manual override
    lifetime_value: float  # Total revenue from this customer
    avg_visit_interval: Optional[int]  # Average days between visits
    created_at: str
    updated_at: str


@dataclass
class ReengagementRule:
    id: str
    business_id: str
    name: str
    service_type: Optional[str]  # None = applies to all services
    days_since_last_service: int
    max_days: Optional[int]  # Upper bound (for targeting specific windows)
    message_template: str  # Uses {name}, {service}, {business_name}, {days}, {discount} placeholders
    enabled: bool
    priority: int
    rule_type: str  # 'standard', 'winback', 'followup', 'seasonal'
    sequence_order: int  # For follow-up sequences (1 = first message, 2 = second, etc.)
    sequence_delay_days: int  # Days to wait after previous message in sequence
    customer_segment: Optional[str]  # 'vip', 'at_risk', 'new', 'all'
    discount_offer: Optional[str]  # e.g., "10%" or "$20 off"
    send_window_start: int  # Hour to start sending (0-23)
    send_window_end: int  # Hour to stop sending (0-23)
    created_at: str


@dataclass
class ReengagementLog:
    id: str
    business_id: str
    customer_id: str
    rule_id: str
    message_sent: str
    sent_at: str
    response_received: bool
    booked_appointment: bool
    sequence_position: int  # Which message in sequence this was
    campaign_id: Optional[str]  # Group messages in same campaign


@dataclass
class ReengagementCampaign:
    """Track a campaign of messages to a customer."""
    id: str
    business_id: str
    customer_id: str
    campaign_type: str  # 'standard', 'winback', 'seasonal'
    status: str  # 'active', 'completed', 'converted', 'opted_out'
    started_at: str
    last_message_at: Optional[str]
    messages_sent: int
    converted: bool
