"""
Lead & Re-engagement Agent - Manages lead detection and automated customer outreach.

Specializes in:
- Detecting new leads from conversations
- Tracking lead status
- Automated re-engagement based on configurable rules
- Win-back campaigns for lapsed customers
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '../../.env'))

from agentfield import Agent, AIConfig
from shared.db import (
    init_db, 
    create_lead, 
    get_leads_by_phone,
    get_business_by_id,
    get_or_create_customer,
    update_customer_service,
    set_customer_opt_out,
    create_reengagement_rule,
    get_reengagement_rules,
    toggle_reengagement_rule,
    delete_reengagement_rule,
    get_customers_due_for_reengagement,
    log_reengagement_sent,
    mark_reengagement_responded,
    get_reengagement_stats,
    get_all_businesses,
)

AGENTFIELD_URL = os.getenv("AGENTFIELD_URL", "http://localhost:8080")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

app = Agent(
    node_id="leads",
    agentfield_server=AGENTFIELD_URL,
    ai_config=AIConfig(
        model="anthropic/claude-haiku-4-5-20251001",
        api_key=ANTHROPIC_API_KEY,
        temperature=0.4,
        max_tokens=400,
    ),
)


# ============== Lead Detection ==============

@app.reasoner()
async def detect_lead(message: str, phone: str, business_id: str) -> dict:
    """Analyze a message to determine if it represents a new lead."""
    
    existing = get_leads_by_phone(business_id, phone)
    if existing:
        return {"is_lead": False, "reason": "Already existing lead"}
    
    result = await app.ai(
        system="""Analyze if this customer message indicates they want to hire or book a service.

Respond with JSON:
{"is_lead": true/false, "confidence": "high/medium/low", "reason": "brief explanation"}""",
        user=message,
    )
    
    return {"analysis": str(result)}


@app.skill(name="create_lead")
def create_new_lead(business_id: str, phone: str, description: str) -> dict:
    """Create a new lead in the database."""
    lead = create_lead(business_id, phone, job_description=description)
    return {"lead_id": lead.id, "status": lead.status}


# ============== Customer Tracking ==============

@app.skill(name="record_service")
def record_customer_service(
    business_id: str, 
    phone: str, 
    service_type: str,
    service_date: str = None,
    customer_name: str = None
) -> dict:
    """
    Record that a customer received a service. Call this when an appointment is completed.
    This updates the customer's last service date for re-engagement tracking.
    """
    customer = update_customer_service(
        business_id=business_id,
        phone=phone,
        service_type=service_type,
        service_date=service_date,
        name=customer_name
    )
    return {
        "customer_id": customer.id,
        "name": customer.name,
        "total_visits": customer.total_visits,
        "last_service": customer.last_service_date,
        "last_service_type": customer.last_service_type
    }


@app.skill(name="opt_out_customer")
def opt_out_customer(business_id: str, phone: str) -> dict:
    """Opt a customer out of re-engagement messages."""
    set_customer_opt_out(business_id, phone, opted_out=True)
    return {"status": "opted_out", "phone": phone}


# ============== Re-engagement Rules ==============

@app.skill(name="add_reengagement_rule")
def add_reengagement_rule(
    business_id: str,
    name: str,
    days: int,
    message_template: str,
    service_type: str = None,
    priority: int = 0
) -> dict:
    """
    Create a new re-engagement rule.
    
    Message template can use these placeholders:
    - {name} - Customer's name (or "there" if unknown)
    - {service} - Last service type
    - {business_name} - Business name
    - {days} - Days since last service
    
    Examples:
    - Haircut (30 days): "Hi {name}! It's been {days} days since your last haircut. Ready for a fresh look?"
    - Dental (180 days): "Hi {name}, you're due for your 6-month checkup at {business_name}. Want to schedule?"
    - Auto (90 days): "Hey {name}, your car is due for service! It's been {days} days since your last visit."
    """
    rule = create_reengagement_rule(
        business_id=business_id,
        name=name,
        days_since_last_service=days,
        message_template=message_template,
        service_type=service_type,
        priority=priority
    )
    return {
        "rule_id": rule.id,
        "name": rule.name,
        "days": rule.days_since_last_service,
        "template": rule.message_template
    }


@app.skill(name="list_reengagement_rules")
def list_reengagement_rules(business_id: str, include_disabled: bool = False) -> dict:
    """List all re-engagement rules for a business."""
    rules = get_reengagement_rules(business_id, enabled_only=not include_disabled)
    return {
        "rules": [
            {
                "id": r.id,
                "name": r.name,
                "service_type": r.service_type or "all",
                "days": r.days_since_last_service,
                "template": r.message_template,
                "enabled": r.enabled,
                "priority": r.priority
            }
            for r in rules
        ]
    }


@app.skill(name="toggle_rule")
def toggle_rule(rule_id: str, enabled: bool) -> dict:
    """Enable or disable a re-engagement rule."""
    toggle_reengagement_rule(rule_id, enabled)
    return {"rule_id": rule_id, "enabled": enabled}


@app.skill(name="remove_rule")
def remove_rule(rule_id: str) -> dict:
    """Delete a re-engagement rule."""
    delete_reengagement_rule(rule_id)
    return {"rule_id": rule_id, "deleted": True}


# ============== Re-engagement Generation ==============

def format_reengagement_message(template: str, customer, business, days_since: int) -> str:
    """Format a re-engagement message template with customer data."""
    name = customer.name if customer.name else "there"
    service = customer.last_service_type or "service"
    business_name = business.business_name if business else "our business"
    
    return template.format(
        name=name,
        service=service,
        business_name=business_name,
        days=days_since
    )


@app.reasoner()
async def generate_reengagement_message(
    customer_phone: str,
    customer_name: str,
    service_type: str,
    days_since: int,
    business_context: dict
) -> dict:
    """
    Generate a personalized re-engagement message using AI.
    Falls back to this when no template is provided.
    """
    result = await app.ai(
        system=f"""You are writing a friendly re-engagement SMS for {business_context.get('business_name', 'a business')}.

The customer's info:
- Name: {customer_name or 'Unknown'}
- Last service: {service_type}
- Days since last visit: {days_since}

Business info:
- Services: {business_context.get('services', 'Various services')}
- Current availability: {business_context.get('availability', 'Available')}

Write a SHORT, warm, personalized message (2-3 sentences max) to encourage them to book again.
Don't be pushy or salesy. Sound human and friendly.
Do NOT mention that you're an AI or automated system.""",
        user=f"Write a re-engagement message for a customer who got a {service_type} {days_since} days ago.",
    )
    
    return {"message": str(result)}


@app.skill(name="get_pending_reengagements")
def get_pending_reengagements(business_id: str) -> dict:
    """
    Get all customers who are due for re-engagement messages.
    Returns customers matched with their applicable rules.
    """
    due = get_customers_due_for_reengagement(business_id)
    business = get_business_by_id(business_id)
    
    results = []
    for item in due:
        customer = item["customer"]
        rule = item["rule"]
        days = item["days_since_service"]
        
        # Format the message from template
        message = format_reengagement_message(
            rule.message_template,
            customer,
            business,
            days
        )
        
        results.append({
            "customer_id": customer.id,
            "customer_phone": customer.phone,
            "customer_name": customer.name,
            "last_service": customer.last_service_type,
            "days_since_service": days,
            "rule_id": rule.id,
            "rule_name": rule.name,
            "message": message
        })
    
    return {"pending": results, "count": len(results)}


@app.skill(name="send_reengagement")
def mark_reengagement_as_sent(
    business_id: str,
    customer_id: str,
    rule_id: str,
    message: str
) -> dict:
    """
    Log that a re-engagement message was sent.
    Call this after actually sending the SMS.
    """
    log_id = log_reengagement_sent(business_id, customer_id, rule_id, message)
    return {"log_id": log_id, "status": "logged"}


@app.skill(name="mark_responded")
def mark_customer_responded(customer_id: str, booked: bool = False) -> dict:
    """Mark that a customer responded to a re-engagement (and optionally booked)."""
    mark_reengagement_responded(customer_id, booked)
    return {"customer_id": customer_id, "booked": booked}


@app.skill(name="get_stats")
def get_stats(business_id: str) -> dict:
    """Get re-engagement campaign statistics."""
    return get_reengagement_stats(business_id)


# ============== Batch Processing ==============

@app.skill(name="process_all_reengagements")
def process_all_reengagements() -> dict:
    """
    Process re-engagements for ALL businesses.
    Returns a list of messages that should be sent.
    This is meant to be called by a cron job or scheduler.
    """
    all_pending = []
    businesses = get_all_businesses()
    
    for business in businesses:
        pending = get_pending_reengagements(business.id)
        for item in pending.get("pending", []):
            item["business_id"] = business.id
            item["business_name"] = business.business_name
            item["from_number"] = business.customer_number  # Number to send SMS from
            all_pending.append(item)
    
    return {
        "pending_messages": all_pending,
        "total_count": len(all_pending),
        "businesses_processed": len(businesses)
    }


# ============== Default Rules Setup ==============

DEFAULT_RULES = {
    # ======================
    # BEAUTY & PERSONAL CARE
    # ======================
    "haircut": {
        "name": "Haircut Follow-up",
        "days": 30,
        "template": "Hi {name}! It's been about a month since your last cut. Ready for a fresh look? Reply to book your next appointment! 💈",
        "priority": 10
    },
    "barber": {
        "name": "Barber Follow-up",
        "days": 21,
        "template": "Hey {name}! It's been {days} days since your last trim at {business_name}. Time for a fresh fade? Text back to book! ✂️",
        "priority": 10
    },
    "salon": {
        "name": "Salon Appointment Reminder",
        "days": 42,  # ~6 weeks
        "template": "Hi {name}! Your hair is probably ready for some attention. It's been {days} days since your last visit to {business_name}. Ready to book? 💇",
        "priority": 10
    },
    "color": {
        "name": "Hair Color Touch-up",
        "days": 35,  # 5 weeks typical for color
        "template": "Hi {name}! It's been about 5 weeks since your last color service. Ready for a touch-up? Reply to book at {business_name}! 🎨",
        "priority": 12  # Higher priority than general salon
    },
    "nails": {
        "name": "Nail Appointment Reminder",
        "days": 21,
        "template": "Hi {name}! Your nails are probably ready for some love. It's been {days} days since your last visit. Ready to book? 💅",
        "priority": 10
    },
    "lashes": {
        "name": "Lash Appointment Reminder",
        "days": 21,  # 2-3 weeks for fills
        "template": "Hi {name}! Your lashes are probably due for a fill. It's been {days} days since your last appointment. Book your fill at {business_name}! ✨",
        "priority": 10
    },
    "brows": {
        "name": "Brow Appointment Reminder",
        "days": 28,
        "template": "Hey {name}! It's been about a month since your last brow appointment. Time to keep them on point! Reply to book 🙂",
        "priority": 10
    },
    "waxing": {
        "name": "Waxing Reminder",
        "days": 28,
        "template": "Hi {name}! It's been {days} days since your last wax at {business_name}. Ready to stay smooth? Reply to book your next appointment!",
        "priority": 10
    },
    "facial": {
        "name": "Facial Follow-up",
        "days": 30,
        "template": "Hi {name}! It's been a month since your last facial. Your skin is probably ready for some TLC! Book your next session at {business_name} 🧖",
        "priority": 10
    },
    "massage": {
        "name": "Massage Follow-up",
        "days": 30,
        "template": "Hi {name}! It's been a month since your last massage at {business_name}. Feeling tension building up? Book your next session! 💆",
        "priority": 10
    },
    "spa": {
        "name": "Spa Follow-up",
        "days": 45,
        "template": "Hi {name}! It's been {days} days since you treated yourself at {business_name}. Ready for another relaxing visit? Reply to book! 🧘",
        "priority": 8
    },
    
    # ======================
    # HEALTH & MEDICAL
    # ======================
    "dental": {
        "name": "Dental Checkup Reminder", 
        "days": 180,
        "template": "Hi {name}, you're due for your 6-month dental checkup at {business_name}. Keeping up with regular cleanings helps prevent bigger issues. Want to schedule? 🦷",
        "priority": 10
    },
    "dental_cleaning": {
        "name": "Dental Cleaning Reminder", 
        "days": 180,
        "template": "Hi {name}! It's time for your 6-month cleaning at {business_name}. Regular cleanings keep your smile healthy! Reply to schedule 😁",
        "priority": 10
    },
    "optometry": {
        "name": "Eye Exam Reminder",
        "days": 365,
        "template": "Hi {name}! It's been a year since your last eye exam at {business_name}. Time for your annual checkup! Reply to schedule your appointment 👓",
        "priority": 10
    },
    "chiropractic": {
        "name": "Chiropractic Follow-up",
        "days": 30,
        "template": "Hi {name}! It's been {days} days since your last adjustment at {business_name}. How are you feeling? Ready to schedule your next visit?",
        "priority": 10
    },
    "physical_therapy": {
        "name": "PT Follow-up",
        "days": 14,
        "template": "Hi {name}! Just checking in from {business_name}. How are you feeling since your last session? Ready to book your next appointment?",
        "priority": 10
    },
    "dermatology": {
        "name": "Derm Checkup Reminder",
        "days": 365,
        "template": "Hi {name}! It's time for your annual skin check at {business_name}. Regular checkups are important! Reply to schedule 🩺",
        "priority": 10
    },
    
    # ======================
    # FITNESS & WELLNESS
    # ======================
    "personal_training": {
        "name": "Training Session Follow-up",
        "days": 7,
        "template": "Hey {name}! It's been a week since your last training session. Ready to keep the momentum going? Book your next session at {business_name}! 💪",
        "priority": 10
    },
    "gym": {
        "name": "Gym Check-in",
        "days": 14,
        "template": "Hey {name}! We haven't seen you at {business_name} in {days} days. Your fitness goals miss you! Come back and crush it 💪",
        "priority": 10
    },
    "yoga": {
        "name": "Yoga Class Reminder",
        "days": 14,
        "template": "Namaste {name}! It's been {days} days since your last class at {business_name}. Your mat misses you! Ready to flow? 🧘",
        "priority": 10
    },
    "pilates": {
        "name": "Pilates Follow-up",
        "days": 14,
        "template": "Hi {name}! It's been {days} days since your last Pilates session. Ready to strengthen your core? Book your next class at {business_name}!",
        "priority": 10
    },
    
    # ======================
    # PET SERVICES
    # ======================
    "pet_grooming": {
        "name": "Pet Grooming Reminder",
        "days": 42,  # ~6 weeks
        "template": "Hi {name}! It's been {days} days since your furry friend's last grooming at {business_name}. Time for a fresh look? Reply to book! 🐕",
        "priority": 10
    },
    "dog_grooming": {
        "name": "Dog Grooming Reminder",
        "days": 42,
        "template": "Hey {name}! Your pup is probably due for a grooming session. It's been {days} days! Book at {business_name} 🐶",
        "priority": 10
    },
    "vet": {
        "name": "Vet Checkup Reminder",
        "days": 365,
        "template": "Hi {name}! Your pet is due for their annual checkup at {business_name}. Keeping them healthy! Reply to schedule 🐾",
        "priority": 10
    },
    "dog_training": {
        "name": "Dog Training Follow-up",
        "days": 7,
        "template": "Hi {name}! How's the training going? It's been a week since your last session at {business_name}. Ready for the next one? 🐕‍🦺",
        "priority": 10
    },
    
    # ======================
    # AUTO & HOME SERVICES
    # ======================
    "auto_service": {
        "name": "Auto Service Reminder",
        "days": 90,
        "template": "Hey {name}! It's been {days} days since your last service. Time to keep your car running smooth! Reply to schedule your next visit. 🚗",
        "priority": 10
    },
    "oil_change": {
        "name": "Oil Change Reminder",
        "days": 90,
        "template": "Hi {name}! It's been about 3 months since your last oil change at {business_name}. Time to keep your engine happy! Reply to schedule 🚗",
        "priority": 12
    },
    "car_wash": {
        "name": "Car Wash Reminder",
        "days": 14,
        "template": "Hey {name}! Your car is probably ready for a wash. It's been {days} days! Come by {business_name} for a shine ✨🚗",
        "priority": 8
    },
    "car_detailing": {
        "name": "Detailing Follow-up",
        "days": 90,
        "template": "Hi {name}! It's been {days} days since your last detail at {business_name}. Ready to make your car shine again? Reply to book!",
        "priority": 10
    },
    "lawn_care": {
        "name": "Lawn Care Follow-up",
        "days": 14,
        "template": "Hi {name}! It's been {days} days since your last lawn service. Ready for another mow? Reply to schedule with {business_name}! 🌿",
        "priority": 10
    },
    "landscaping": {
        "name": "Landscaping Follow-up",
        "days": 30,
        "template": "Hi {name}! It's been a month since your last landscaping service. Need anything done? Reply to schedule with {business_name}! 🌳",
        "priority": 10
    },
    "pool_service": {
        "name": "Pool Service Reminder",
        "days": 7,
        "template": "Hi {name}! Time for your weekly pool service? It's been {days} days. Reply to confirm your next visit from {business_name}! 🏊",
        "priority": 10
    },
    "hvac": {
        "name": "HVAC Maintenance Reminder",
        "days": 180,
        "template": "Hi {name}! It's been 6 months since your last HVAC service. Regular maintenance keeps things running efficiently! Schedule with {business_name}? 🌡️",
        "priority": 10
    },
    "plumbing": {
        "name": "Plumbing Follow-up",
        "days": 365,
        "template": "Hi {name}! It's been a year since we last helped you. Need any plumbing work done? {business_name} is here to help! 🔧",
        "priority": 8
    },
    "cleaning": {
        "name": "Cleaning Service Follow-up",
        "days": 14,
        "template": "Hi {name}! It's been {days} days since your last cleaning. Ready for a fresh, clean space? Reply to book with {business_name}! ✨",
        "priority": 10
    },
    "house_cleaning": {
        "name": "House Cleaning Reminder",
        "days": 14,
        "template": "Hi {name}! Your home is probably ready for another cleaning. It's been {days} days! Book with {business_name} 🏠✨",
        "priority": 10
    },
    
    # ======================
    # PROFESSIONAL SERVICES
    # ======================
    "photography": {
        "name": "Photography Follow-up",
        "days": 180,
        "template": "Hi {name}! It's been 6 months since our last shoot. Have any special moments coming up? {business_name} would love to capture them! 📸",
        "priority": 8
    },
    "tattoo": {
        "name": "Tattoo Touch-up Reminder",
        "days": 30,
        "template": "Hey {name}! It's been {days} days since your tattoo. How's it healing? Remember, we offer free touch-ups if needed! - {business_name} 🎨",
        "priority": 10
    },
    "tutoring": {
        "name": "Tutoring Follow-up",
        "days": 7,
        "template": "Hi {name}! It's been a week since your last tutoring session at {business_name}. Ready for your next one? Reply to book! 📚",
        "priority": 10
    },
    "music_lessons": {
        "name": "Music Lesson Reminder",
        "days": 7,
        "template": "Hey {name}! Time to practice those skills! Ready to book your next lesson at {business_name}? 🎵",
        "priority": 10
    },
    
    # ======================
    # GENERAL FALLBACK
    # ======================
    "general": {
        "name": "General Follow-up",
        "days": 60,
        "template": "Hi {name}! It's been a while since we've seen you at {business_name}. We'd love to have you back! Reply to schedule your next visit.",
        "priority": 0  # Lower priority, catches anything not matched by specific rules
    }
}

# ======================
# WIN-BACK CAMPAIGN SEQUENCES
# Multi-step campaigns for lapsed customers with escalating incentives
# ======================
WINBACK_SEQUENCES = {
    "standard": [
        {
            "name": "Win-back Step 1 - Friendly Check-in",
            "sequence_order": 1,
            "days": 60,
            "max_days": 90,
            "template": "Hi {name}! It's been a while since we've seen you at {business_name}. We miss you! Reply to book your next visit.",
            "rule_type": "winback"
        },
        {
            "name": "Win-back Step 2 - Soft Incentive",
            "sequence_order": 2,
            "sequence_delay_days": 7,
            "days": 67,
            "max_days": 97,
            "template": "Hi {name}! We'd love to see you back at {business_name}. Reply 'BOOK' and we'll get you scheduled!",
            "rule_type": "followup"
        },
        {
            "name": "Win-back Step 3 - Special Offer",
            "sequence_order": 3,
            "sequence_delay_days": 7,
            "days": 74,
            "max_days": 104,
            "template": "Hi {name}! We haven't heard from you and want to make it easy to come back. Reply for a special returning customer offer! - {business_name}",
            "discount_offer": "10%",
            "rule_type": "followup"
        }
    ],
    "vip": [
        {
            "name": "VIP Win-back Step 1",
            "sequence_order": 1,
            "days": 45,
            "max_days": 60,
            "template": "Hi {name}! We've noticed it's been a while since your last visit. As one of our valued VIP customers, we wanted to reach out personally. Would you like to schedule your next appointment at {business_name}?",
            "customer_segment": "vip",
            "rule_type": "winback"
        },
        {
            "name": "VIP Win-back Step 2",
            "sequence_order": 2,
            "sequence_delay_days": 5,
            "days": 50,
            "max_days": 65,
            "template": "Hi {name}! As a thank you for being such a great customer, we'd like to offer you {discount} off your next visit. Just reply to book! - {business_name}",
            "customer_segment": "vip",
            "discount_offer": "15%",
            "rule_type": "followup"
        }
    ],
    "at_risk": [
        {
            "name": "At-Risk Recovery Step 1",
            "sequence_order": 1,
            "days": 90,
            "max_days": 120,
            "template": "Hi {name}! It's been {days} days and we miss seeing you at {business_name}! Everything okay? We'd love to have you back.",
            "customer_segment": "at_risk",
            "rule_type": "winback"
        },
        {
            "name": "At-Risk Recovery Step 2",
            "sequence_order": 2,
            "sequence_delay_days": 7,
            "days": 97,
            "max_days": 127,
            "template": "Hi {name}! We really want you back at {business_name}. Here's {discount} off your next visit - just reply to book!",
            "customer_segment": "at_risk",
            "discount_offer": "20%",
            "rule_type": "followup"
        },
        {
            "name": "At-Risk Recovery Step 3 - Final",
            "sequence_order": 3,
            "sequence_delay_days": 14,
            "days": 111,
            "max_days": 180,
            "template": "Hi {name}, last chance! Get {discount} off at {business_name}. We'd hate to lose you as a customer. Reply 'BOOK' to claim your offer!",
            "customer_segment": "at_risk",
            "discount_offer": "25%",
            "rule_type": "followup"
        }
    ]
}

# ======================
# SEASONAL CAMPAIGN TEMPLATES
# Time-based campaigns for holidays and seasons
# ======================
SEASONAL_CAMPAIGNS = {
    "new_year": {
        "name": "New Year Fresh Start",
        "template": "Happy New Year {name}! 🎉 Start {year} fresh with a visit to {business_name}. Reply to book your first appointment of the year!",
        "months": [1],  # January
        "priority": 15
    },
    "valentines": {
        "name": "Valentine's Day Special",
        "template": "Hi {name}! 💕 Valentine's Day is coming up. Treat yourself (or someone special) at {business_name}! Reply to book.",
        "months": [2],  # February
        "priority": 15
    },
    "spring": {
        "name": "Spring Refresh",
        "template": "Hi {name}! 🌸 Spring is here - perfect time for a refresh at {business_name}! Reply to book your appointment.",
        "months": [3, 4],  # March-April
        "priority": 12
    },
    "mothers_day": {
        "name": "Mother's Day Special",
        "template": "Hi {name}! 💐 Mother's Day is coming up. Gift mom (or yourself!) a visit to {business_name}. Reply to book!",
        "months": [5],  # May
        "priority": 15
    },
    "summer": {
        "name": "Summer Ready",
        "template": "Hi {name}! ☀️ Summer is here! Time to look your best. Book at {business_name} - reply to schedule!",
        "months": [6, 7],  # June-July
        "priority": 12
    },
    "back_to_school": {
        "name": "Back to School",
        "template": "Hi {name}! 📚 Back to school season is here. Get ready with a visit to {business_name}! Reply to book.",
        "months": [8],  # August
        "priority": 12
    },
    "fall": {
        "name": "Fall Refresh",
        "template": "Hi {name}! 🍂 Fall is here - perfect time to refresh your look at {business_name}. Reply to book!",
        "months": [9, 10],  # Sep-Oct
        "priority": 12
    },
    "holiday": {
        "name": "Holiday Season",
        "template": "Hi {name}! 🎄 The holidays are here! Look your best for the season. Book at {business_name} - spots filling fast!",
        "months": [11, 12],  # Nov-Dec
        "priority": 15
    }
}


@app.skill(name="setup_default_rules")
def setup_default_rules(business_id: str, business_type: str = "general") -> dict:
    """
    Set up default re-engagement rules for a business.
    
    Available business types (50+ categories):
    
    BEAUTY & PERSONAL CARE:
    - haircut, barber, salon, color, nails, lashes, brows, waxing, facial, massage, spa
    
    HEALTH & MEDICAL:
    - dental, dental_cleaning, optometry, chiropractic, physical_therapy, dermatology
    
    FITNESS & WELLNESS:
    - personal_training, gym, yoga, pilates
    
    PET SERVICES:
    - pet_grooming, dog_grooming, vet, dog_training
    
    AUTO & HOME SERVICES:
    - auto_service, oil_change, car_wash, car_detailing, lawn_care, landscaping
    - pool_service, hvac, plumbing, cleaning, house_cleaning
    
    PROFESSIONAL SERVICES:
    - photography, tattoo, tutoring, music_lessons
    
    GENERAL:
    - general: 60-day reminder (fallback for any business)
    
    You can set up multiple types, or just 'general' for a catch-all.
    """
    created = []
    
    if business_type == "all":
        # Set up all rules
        for btype, config in DEFAULT_RULES.items():
            rule = create_reengagement_rule(
                business_id=business_id,
                name=config["name"],
                days_since_last_service=config["days"],
                message_template=config["template"],
                service_type=btype if btype != "general" else None,
                priority=config["priority"]
            )
            created.append({"id": rule.id, "name": rule.name, "type": btype})
    else:
        # Set up specific type
        if business_type in DEFAULT_RULES:
            config = DEFAULT_RULES[business_type]
            rule = create_reengagement_rule(
                business_id=business_id,
                name=config["name"],
                days_since_last_service=config["days"],
                message_template=config["template"],
                service_type=business_type if business_type != "general" else None,
                priority=config["priority"]
            )
            created.append({"id": rule.id, "name": rule.name, "type": business_type})
        else:
            return {"error": f"Unknown business type: {business_type}", "available": list(DEFAULT_RULES.keys())}
    
    return {"created_rules": created, "count": len(created)}


@app.skill(name="setup_winback_campaign")
def setup_winback_campaign(business_id: str, campaign_type: str = "standard") -> dict:
    """
    Set up a multi-step win-back campaign sequence.
    
    Win-back campaigns automatically send a series of messages to lapsed customers
    with escalating incentives to bring them back.
    
    Available campaign types:
    - standard: 3-step sequence starting at 60 days, ends with 10% off
    - vip: 2-step sequence for VIP customers, starts earlier (45 days), 15% off
    - at_risk: 3-step aggressive recovery for at-risk customers, up to 25% off
    
    Each step automatically triggers after the configured delay if customer
    hasn't responded to previous messages.
    """
    if campaign_type not in WINBACK_SEQUENCES:
        return {
            "error": f"Unknown campaign type: {campaign_type}",
            "available": list(WINBACK_SEQUENCES.keys())
        }
    
    sequence = WINBACK_SEQUENCES[campaign_type]
    created = []
    
    for step in sequence:
        rule = create_reengagement_rule(
            business_id=business_id,
            name=step["name"],
            days_since_last_service=step["days"],
            max_days=step.get("max_days"),
            message_template=step["template"],
            priority=20,  # High priority for win-back
            rule_type=step["rule_type"],
            sequence_order=step["sequence_order"],
            sequence_delay_days=step.get("sequence_delay_days", 0),
            customer_segment=step.get("customer_segment", "all"),
            discount_offer=step.get("discount_offer")
        )
        created.append({
            "id": rule.id,
            "name": rule.name,
            "sequence_order": step["sequence_order"],
            "days": step["days"],
            "discount": step.get("discount_offer")
        })
    
    return {
        "campaign_type": campaign_type,
        "created_rules": created,
        "count": len(created),
        "description": f"Created {len(created)}-step win-back sequence"
    }


@app.skill(name="setup_seasonal_campaign")
def setup_seasonal_campaign(business_id: str, season: str, custom_message: str = None) -> dict:
    """
    Set up a seasonal/holiday campaign.
    
    Available seasons:
    - new_year: January - Fresh start messaging
    - valentines: February - Valentine's Day special
    - spring: March-April - Spring refresh
    - mothers_day: May - Mother's Day special
    - summer: June-July - Summer ready
    - back_to_school: August - Back to school season
    - fall: September-October - Fall refresh
    - holiday: November-December - Holiday season
    
    You can optionally provide a custom_message to override the default template.
    Templates can use: {name}, {business_name}, {year}
    """
    if season not in SEASONAL_CAMPAIGNS:
        return {
            "error": f"Unknown season: {season}",
            "available": list(SEASONAL_CAMPAIGNS.keys())
        }
    
    campaign = SEASONAL_CAMPAIGNS[season]
    template = custom_message if custom_message else campaign["template"]
    
    # Replace {year} with current year
    from datetime import datetime
    template = template.replace("{year}", str(datetime.now().year))
    
    rule = create_reengagement_rule(
        business_id=business_id,
        name=campaign["name"],
        days_since_last_service=30,  # Active within last 30 days gets the seasonal message
        max_days=365,  # Anyone who's visited in the last year
        message_template=template,
        priority=campaign["priority"],
        rule_type="seasonal"
    )
    
    return {
        "season": season,
        "rule_id": rule.id,
        "name": rule.name,
        "template": template,
        "active_months": campaign["months"]
    }


@app.skill(name="list_business_types")
def list_business_types() -> dict:
    """
    List all available business types for re-engagement rules.
    
    Returns categorized list of business types with their recommended
    re-engagement intervals.
    """
    categories = {
        "beauty_personal_care": [],
        "health_medical": [],
        "fitness_wellness": [],
        "pet_services": [],
        "auto_home_services": [],
        "professional_services": [],
        "general": []
    }
    
    categorization = {
        "beauty_personal_care": ["haircut", "barber", "salon", "color", "nails", "lashes", "brows", "waxing", "facial", "massage", "spa"],
        "health_medical": ["dental", "dental_cleaning", "optometry", "chiropractic", "physical_therapy", "dermatology"],
        "fitness_wellness": ["personal_training", "gym", "yoga", "pilates"],
        "pet_services": ["pet_grooming", "dog_grooming", "vet", "dog_training"],
        "auto_home_services": ["auto_service", "oil_change", "car_wash", "car_detailing", "lawn_care", "landscaping", "pool_service", "hvac", "plumbing", "cleaning", "house_cleaning"],
        "professional_services": ["photography", "tattoo", "tutoring", "music_lessons"],
        "general": ["general"]
    }
    
    for category, types in categorization.items():
        for btype in types:
            if btype in DEFAULT_RULES:
                config = DEFAULT_RULES[btype]
                categories[category].append({
                    "type": btype,
                    "name": config["name"],
                    "days": config["days"],
                    "description": f"Reminds customer after {config['days']} days"
                })
    
    return {
        "categories": categories,
        "total_types": len(DEFAULT_RULES),
        "winback_campaigns": list(WINBACK_SEQUENCES.keys()),
        "seasonal_campaigns": list(SEASONAL_CAMPAIGNS.keys())
    }


@app.skill(name="create_custom_rule")
def create_custom_rule(
    business_id: str,
    name: str,
    days: int,
    message: str,
    service_type: str = None,
    max_days: int = None,
    target_segment: str = "all",
    discount: str = None,
    send_start_hour: int = 9,
    send_end_hour: int = 18
) -> dict:
    """
    Create a fully custom re-engagement rule.
    
    Parameters:
    - name: Name for this rule (e.g., "Monthly Checkup Reminder")
    - days: Days since last service to trigger this rule
    - message: Message template. Use placeholders:
        - {name} - Customer's name
        - {service} - Last service type
        - {business_name} - Your business name
        - {days} - Days since last visit
        - {discount} - Discount offer (if set)
    - service_type: Only apply to customers who had this service (optional)
    - max_days: Upper limit - don't send after this many days (optional)
    - target_segment: 'all', 'vip', 'at_risk', 'new', or 'regular'
    - discount: Discount to offer (e.g., "10%", "$20 off")
    - send_start_hour: Earliest hour to send (0-23, default 9am)
    - send_end_hour: Latest hour to send (0-23, default 6pm)
    
    Example:
    create_custom_rule(
        business_id="...",
        name="3-Month Massage Reminder",
        days=90,
        message="Hi {name}! It's been {days} days since your last massage. Your body is probably craving some relief! Book now for {discount} off! 💆",
        service_type="massage",
        target_segment="vip",
        discount="15%"
    )
    """
    rule = create_reengagement_rule(
        business_id=business_id,
        name=name,
        days_since_last_service=days,
        max_days=max_days,
        message_template=message,
        service_type=service_type,
        priority=10,
        rule_type="standard",
        customer_segment=target_segment,
        discount_offer=discount,
        send_window_start=send_start_hour,
        send_window_end=send_end_hour
    )
    
    return {
        "rule_id": rule.id,
        "name": rule.name,
        "days": days,
        "max_days": max_days,
        "service_type": service_type or "all services",
        "target_segment": target_segment,
        "discount": discount,
        "send_window": f"{send_start_hour}:00 - {send_end_hour}:00",
        "message_preview": message[:100] + "..." if len(message) > 100 else message
    }


if __name__ == "__main__":
    init_db()
    print(f"[leads] Starting Lead & Re-engagement Agent")
    print(f"[leads] AgentField URL: {AGENTFIELD_URL}")
    app.run(port=8004)
