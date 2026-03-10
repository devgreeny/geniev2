"""
Scheduling Agent - Handles appointment booking, rescheduling, and cancellation.

Specializes in:
- Booking new appointments
- Rescheduling existing appointments  
- Canceling appointments
- Checking appointment status
- Using customer memory for smart suggestions
"""

import os
import sys
import json
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '../../.env'))

from agentfield import Agent, AIConfig

from shared.db import (
    init_db, 
    create_appointment, 
    get_appointments_by_business,
    get_appointments_by_phone,
    get_appointment_by_id,
    reschedule_appointment,
    cancel_appointment,
    get_or_create_customer,
    update_customer_service,
    mark_reengagement_responded,
)
from shared.memory import (
    get_memory_summary,
    load_customer_memory,
    parse_memory_sections,
    update_customer_memory,
)

AGENTFIELD_URL = os.getenv("AGENTFIELD_URL", "http://localhost:8080")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

app = Agent(
    node_id="scheduling",
    agentfield_server=AGENTFIELD_URL,
    ai_config=AIConfig(
        model="anthropic/claude-haiku-4-5-20251001",
        api_key=ANTHROPIC_API_KEY,
        temperature=0.2,
        max_tokens=500,
    ),
)


async def classify_scheduling_intent(message: str) -> dict:
    """Classify what the customer wants to do with their appointment."""
    result = await app.ai(
        system="""Analyze this message and determine the customer's scheduling intent.

Respond with JSON only:
{
  "intent": "BOOK" | "RESCHEDULE" | "CANCEL" | "CHECK_STATUS" | "GENERAL",
  "has_datetime": true/false,
  "datetime_mentioned": "extracted date/time or null",
  "has_service": true/false,
  "service_mentioned": "extracted service or null",
  "confidence": "high" | "medium" | "low"
}

Examples:
- "I need to reschedule my appointment" → {"intent": "RESCHEDULE", "has_datetime": false, ...}
- "Cancel my haircut" → {"intent": "CANCEL", "has_service": true, "service_mentioned": "haircut", ...}
- "Can I come in Saturday at 2pm?" → {"intent": "BOOK", "has_datetime": true, "datetime_mentioned": "Saturday 2pm", ...}
- "When's my next appointment?" → {"intent": "CHECK_STATUS", ...}
- "Do you do fades?" → {"intent": "GENERAL", ...}""",
        user=message,
    )
    
    try:
        result_text = str(result).strip()
        # Handle markdown code blocks
        if "```" in result_text:
            result_text = result_text.split("```")[1]
            if result_text.startswith("json"):
                result_text = result_text[4:]
            result_text = result_text.strip()
        
        start = result_text.find("{")
        end = result_text.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(result_text[start:end])
    except:
        pass
    
    return {"intent": "GENERAL", "confidence": "low"}


def format_appointment(appt) -> str:
    """Format an appointment for display."""
    try:
        dt = datetime.strptime(appt.datetime, "%Y-%m-%d %H:%M")
        formatted = dt.strftime("%A, %B %d at %I:%M %p")
    except:
        formatted = appt.datetime
    
    return f"{appt.service} on {formatted}"


def format_appointments_list(appointments: list) -> str:
    """Format a list of appointments for display."""
    if not appointments:
        return "No upcoming appointments found."
    
    lines = []
    for i, appt in enumerate(appointments, 1):
        lines.append(f"{i}. {format_appointment(appt)}")
    
    return "\n".join(lines)


@app.reasoner()
async def handle(
    phone: str,
    message: str,
    business_id: str,
    context: dict,
) -> dict:
    """
    Handle scheduling requests with smart intent detection.
    Can book, reschedule, cancel, or check appointment status.
    """
    business_name = context.get('business_name', 'our business')
    availability = context.get('availability', 'Available')
    hours = context.get('hours', 'Contact for hours')
    services = context.get('services', 'our services')
    conversation_history = context.get('conversation_history', '')
    
    # Load customer memory
    customer_memory = get_memory_summary(business_id, phone)
    full_memory = load_customer_memory(business_id, phone)
    memory_data = parse_memory_sections(full_memory) if full_memory else {}
    customer_name = memory_data.get("name") if memory_data.get("name") != "Unknown" else None
    preferences = memory_data.get("preferences", {})
    
    # Get customer's existing appointments
    existing_appointments = get_appointments_by_phone(business_id, phone, status="pending", upcoming_only=True)
    
    # Get all booked times for availability checking
    all_appointments = get_appointments_by_business(business_id, status="pending")
    booked_times = [a.datetime for a in all_appointments]
    
    # Classify intent
    intent_info = await classify_scheduling_intent(message)
    intent = intent_info.get("intent", "GENERAL")
    
    print(f"[scheduling] Intent: {intent} for {phone}")
    
    # Build context about customer's appointments
    appt_context = ""
    if existing_appointments:
        appt_context = f"""
CUSTOMER'S UPCOMING APPOINTMENTS:
{format_appointments_list(existing_appointments)}
"""
    else:
        appt_context = "\nCUSTOMER HAS NO UPCOMING APPOINTMENTS.\n"
    
    # Build memory context
    memory_context = ""
    if customer_memory:
        memory_context = f"""
CUSTOMER MEMORY (their preferences):
{customer_memory}
"""
    
    # Handle different intents
    if intent == "CANCEL":
        return await handle_cancel(
            phone, message, business_id, context,
            existing_appointments, customer_name, conversation_history
        )
    
    elif intent == "RESCHEDULE":
        return await handle_reschedule(
            phone, message, business_id, context,
            existing_appointments, customer_name, intent_info, 
            booked_times, conversation_history
        )
    
    elif intent == "CHECK_STATUS":
        return await handle_check_status(
            phone, message, business_id, context,
            existing_appointments, customer_name
        )
    
    else:  # BOOK or GENERAL
        return await handle_booking(
            phone, message, business_id, context,
            existing_appointments, customer_name, preferences,
            intent_info, booked_times, memory_context, conversation_history
        )


async def handle_cancel(
    phone: str, message: str, business_id: str, context: dict,
    existing_appointments: list, customer_name: str, conversation_history: str
) -> dict:
    """Handle appointment cancellation."""
    business_name = context.get('business_name', 'our business')
    
    if not existing_appointments:
        response = await app.ai(
            system=f"""You are the scheduling assistant for {business_name}.
The customer wants to cancel but has no upcoming appointments.
Let them know politely and offer to help them book something instead.
Keep it brief - this is SMS.""",
            user=message,
        )
        return {"reply": str(response)}
    
    # If they have exactly one appointment, confirm cancellation
    if len(existing_appointments) == 1:
        appt = existing_appointments[0]
        
        # Check if message clearly confirms cancellation or is initial request
        confirm_check = await app.ai(
            system="""Is this message confirming a cancellation or is it an initial cancellation request?
Respond with only: CONFIRM or REQUEST""",
            user=f"Previous context: {conversation_history[-500:] if conversation_history else 'None'}\nCurrent message: {message}",
        )
        
        if "CONFIRM" in str(confirm_check).upper() or any(word in message.lower() for word in ["yes", "yeah", "yep", "confirm", "correct", "that's right", "please cancel"]):
            # Actually cancel the appointment
            success = cancel_appointment(appt.id, reason="Cancelled by customer via text")
            
            if success:
                name_greeting = f"{customer_name}, your" if customer_name else "Your"
                return {"reply": f"Done! {name_greeting} {format_appointment(appt)} has been cancelled. Let us know when you'd like to rebook! 👋"}
            else:
                return {"reply": "Sorry, I had trouble cancelling that appointment. Please try again or contact us directly."}
        else:
            # Ask for confirmation
            name_greeting = f"Hey {customer_name}!" if customer_name else "Hey!"
            return {"reply": f"{name_greeting} Just to confirm - you want to cancel your {format_appointment(appt)}? Reply 'yes' to confirm."}
    
    # Multiple appointments - ask which one
    response = await app.ai(
        system=f"""You are the scheduling assistant for {business_name}.
The customer wants to cancel but has multiple appointments:
{format_appointments_list(existing_appointments)}

Ask them which appointment they want to cancel. Be brief - this is SMS.
{f'Address them as {customer_name}.' if customer_name else ''}""",
        user=message,
    )
    return {"reply": str(response)}


async def handle_reschedule(
    phone: str, message: str, business_id: str, context: dict,
    existing_appointments: list, customer_name: str, intent_info: dict,
    booked_times: list, conversation_history: str
) -> dict:
    """Handle appointment rescheduling."""
    business_name = context.get('business_name', 'our business')
    availability = context.get('availability', 'Available')
    hours = context.get('hours', 'Contact for hours')
    
    if not existing_appointments:
        response = await app.ai(
            system=f"""You are the scheduling assistant for {business_name}.
The customer wants to reschedule but has no upcoming appointments.
Let them know politely and offer to help them book something new.
Keep it brief - this is SMS.""",
            user=message,
        )
        return {"reply": str(response)}
    
    # Get the appointment to reschedule
    appt_to_reschedule = existing_appointments[0]  # Default to first
    
    # If they mentioned a new time, try to reschedule
    if intent_info.get("has_datetime") and intent_info.get("datetime_mentioned"):
        new_time = intent_info.get("datetime_mentioned")
        
        # Parse the datetime
        parse_result = await app.ai(
            system=f"""Convert this date/time to format: YYYY-MM-DD HH:MM
Current date/time for reference: {datetime.now().strftime('%Y-%m-%d %H:%M')}
Business hours: {hours}

If you can determine the exact datetime, respond with ONLY the formatted datetime.
If it's ambiguous (like "next week"), respond with: NEED_MORE_INFO
If it's clearly outside business hours, respond with: OUTSIDE_HOURS""",
            user=new_time,
        )
        
        parsed = str(parse_result).strip()
        
        if parsed == "NEED_MORE_INFO":
            response = await app.ai(
                system=f"""You are rescheduling an appointment for {business_name}.
Current appointment: {format_appointment(appt_to_reschedule)}
Customer said: {new_time}

Ask for a more specific date/time. Be brief.
Availability: {availability}
{f'Address them as {customer_name}.' if customer_name else ''}""",
                user=message,
            )
            return {"reply": str(response)}
        
        elif parsed == "OUTSIDE_HOURS":
            return {"reply": f"Sorry, that time is outside our hours ({hours}). When else works for you?"}
        
        elif len(parsed) >= 10:  # Looks like a valid datetime
            # Check if time is available
            if parsed in booked_times:
                return {"reply": f"Sorry, {new_time} is already booked. What other time works for you?"}
            
            # Perform the reschedule
            updated = reschedule_appointment(appt_to_reschedule.id, parsed)
            
            if updated:
                name_greeting = f"{customer_name}, you're" if customer_name else "You're"
                return {"reply": f"Done! {name_greeting} now booked for {format_appointment(updated)}. See you then! ✅"}
            else:
                return {"reply": "Sorry, I had trouble rescheduling. Please try again or contact us directly."}
    
    # No new time mentioned - ask when they want to reschedule to
    if len(existing_appointments) == 1:
        name_greeting = f"Hey {customer_name}!" if customer_name else "Hey!"
        return {"reply": f"{name_greeting} Sure, I can reschedule your {format_appointment(appt_to_reschedule)}. When would you like to come in instead?"}
    else:
        response = await app.ai(
            system=f"""You are the scheduling assistant for {business_name}.
The customer wants to reschedule but has multiple appointments:
{format_appointments_list(existing_appointments)}

Ask which one they want to reschedule. Be brief - this is SMS.
{f'Address them as {customer_name}.' if customer_name else ''}""",
            user=message,
        )
        return {"reply": str(response)}


async def handle_check_status(
    phone: str, message: str, business_id: str, context: dict,
    existing_appointments: list, customer_name: str
) -> dict:
    """Handle requests to check appointment status."""
    business_name = context.get('business_name', 'our business')
    
    if not existing_appointments:
        name_greeting = f"Hey {customer_name}!" if customer_name else "Hey!"
        return {"reply": f"{name_greeting} You don't have any upcoming appointments with us. Would you like to book one?"}
    
    if len(existing_appointments) == 1:
        appt = existing_appointments[0]
        name_greeting = f"{customer_name}, your" if customer_name else "Your"
        return {"reply": f"{name_greeting} next appointment is {format_appointment(appt)}. Need to make any changes?"}
    
    # Multiple appointments
    name_greeting = f"Hey {customer_name}!" if customer_name else "Hey!"
    appt_list = format_appointments_list(existing_appointments)
    return {"reply": f"{name_greeting} Here are your upcoming appointments:\n{appt_list}\n\nNeed to change anything?"}


async def handle_booking(
    phone: str, message: str, business_id: str, context: dict,
    existing_appointments: list, customer_name: str, preferences: dict,
    intent_info: dict, booked_times: list, memory_context: str,
    conversation_history: str
) -> dict:
    """Handle new appointment booking."""
    business_name = context.get('business_name', 'our business')
    availability = context.get('availability', 'Available')
    hours = context.get('hours', 'Contact for hours')
    services = context.get('services', 'our services')
    
    # Check if customer already has an appointment
    has_existing = len(existing_appointments) > 0
    
    # Build smart suggestion based on memory
    suggestion = ""
    if preferences:
        usual_service = preferences.get("usual_service", "")
        preferred_day = preferences.get("preferred_day", "")
        preferred_time = preferences.get("preferred_time", "")
        
        if usual_service and preferred_day and preferred_time:
            suggestion = f"Based on your history, would you like your usual {usual_service} on {preferred_day} at {preferred_time}?"
    
    # Generate response
    system_prompt = f"""You are the scheduling assistant for {business_name}.
{f'The customer is {customer_name}.' if customer_name else ''}

BUSINESS INFO:
- Services: {services}
- Hours: {hours}
- Current availability: {availability}
- Already booked times to avoid: {booked_times[:10] if booked_times else 'None yet'}
{memory_context}
{f'EXISTING APPOINTMENTS: {format_appointments_list(existing_appointments)}' if has_existing else ''}
{f'CONVERSATION HISTORY:\n{conversation_history}\n' if conversation_history else ''}

YOUR TASK:
Help the customer book an appointment. Collect:
1. Service they need (if not mentioned)
2. Preferred date/time
3. Their name (if we don't have it)

{f'SMART SUGGESTION: {suggestion}' if suggestion else ''}

GUIDELINES:
- Be brief - this is SMS (2-3 sentences max)
- If they mention a time, confirm it's available
- Use their name naturally if known
- Don't ask for info they already provided in the conversation
- Sound human and friendly, not robotic"""

    response = await app.ai(
        system=system_prompt,
        user=message,
    )
    
    # Check if we have enough info to book
    if intent_info.get("has_datetime") and intent_info.get("has_service"):
        # Try to parse and book
        booking_check = await app.ai(
            system=f"""Based on this conversation, do we have enough info to book?
Required: service type, date/time, customer name (optional but nice to have)

Respond with JSON:
{{
  "can_book": true/false,
  "service": "extracted service or null",
  "datetime": "YYYY-MM-DD HH:MM format or null",
  "customer_name": "name if mentioned or null",
  "missing": ["list of missing info"]
}}

Current date: {datetime.now().strftime('%Y-%m-%d')}
Business hours: {hours}""",
            user=f"Customer said: {message}\nConversation: {conversation_history[-500:] if conversation_history else ''}",
        )
        
        try:
            check_text = str(booking_check).strip()
            if "```" in check_text:
                check_text = check_text.split("```")[1]
                if check_text.startswith("json"):
                    check_text = check_text[4:]
            
            start = check_text.find("{")
            end = check_text.rfind("}") + 1
            if start >= 0 and end > start:
                booking_info = json.loads(check_text[start:end])
                
                if booking_info.get("can_book") and booking_info.get("service") and booking_info.get("datetime"):
                    # Actually create the appointment!
                    appt = create_appointment(
                        business_id=business_id,
                        customer_phone=phone,
                        service=booking_info["service"],
                        datetime_str=booking_info["datetime"],
                        customer_name=booking_info.get("customer_name") or customer_name,
                    )
                    
                    # Update customer memory with booking preferences
                    try:
                        # Extract day/time preferences
                        dt = datetime.strptime(booking_info["datetime"], "%Y-%m-%d %H:%M")
                        update_customer_memory(business_id, phone, {
                            "name": booking_info.get("customer_name") or customer_name,
                            "preferences": {
                                "usual_service": booking_info["service"],
                                "preferred_day": dt.strftime("%A"),
                                "preferred_time": dt.strftime("%I:%M %p").lstrip("0"),
                            },
                            "new_service": f"Booked {booking_info['service']}"
                        })
                    except Exception as e:
                        print(f"[scheduling] Memory update failed: {e}")
                    
                    name_greeting = f"{customer_name or booking_info.get('customer_name', '')}, you're".strip(", ")
                    if not name_greeting.startswith("you're"):
                        name_greeting = name_greeting.capitalize()
                    else:
                        name_greeting = "You're"
                    
                    return {"reply": f"Booked! {name_greeting} all set for {format_appointment(appt)}. See you then! ✅"}
        except Exception as e:
            print(f"[scheduling] Booking extraction failed: {e}")
    
    return {"reply": str(response)}


# ============== Skills for other agents ==============

@app.skill(name="get_availability")
def get_availability(business_id: str) -> dict:
    """Get available time slots for a business."""
    appointments = get_appointments_by_business(business_id, status="pending")
    return {
        "booked_slots": [
            {"datetime": a.datetime, "service": a.service, "duration": a.duration}
            for a in appointments
        ]
    }


@app.skill(name="get_customer_appointments")
def get_customer_appointments(business_id: str, phone: str) -> dict:
    """Get all appointments for a specific customer."""
    appointments = get_appointments_by_phone(business_id, phone, upcoming_only=True)
    return {
        "appointments": [
            {
                "id": a.id,
                "service": a.service,
                "datetime": a.datetime,
                "status": a.status,
                "formatted": format_appointment(a)
            }
            for a in appointments
        ],
        "count": len(appointments)
    }


@app.skill(name="book_appointment")
def book_appointment(
    business_id: str,
    customer_phone: str,
    service: str,
    datetime_str: str,
    duration: int = 60,
    customer_name: str = None,
    notes: str = None
) -> dict:
    """Book a new appointment for a customer."""
    customer = get_or_create_customer(business_id, customer_phone, name=customer_name)
    
    appointment = create_appointment(
        business_id=business_id,
        customer_phone=customer_phone,
        service=service,
        datetime_str=datetime_str,
        duration=duration,
        customer_name=customer_name or customer.name,
        notes=notes
    )
    
    if customer.id:
        mark_reengagement_responded(customer.id, booked=True)
    
    return {
        "appointment_id": appointment.id,
        "customer_id": customer.id,
        "service": service,
        "datetime": datetime_str,
        "status": "pending",
        "message": f"Appointment booked for {service} on {datetime_str}"
    }


@app.skill(name="reschedule")
def reschedule(appointment_id: str, new_datetime: str, reason: str = None) -> dict:
    """Reschedule an existing appointment."""
    updated = reschedule_appointment(appointment_id, new_datetime, reason)
    if updated:
        return {
            "success": True,
            "appointment_id": updated.id,
            "new_datetime": updated.datetime,
            "formatted": format_appointment(updated)
        }
    return {"success": False, "error": "Appointment not found"}


@app.skill(name="cancel")
def cancel(appointment_id: str, reason: str = None) -> dict:
    """Cancel an appointment."""
    success = cancel_appointment(appointment_id, reason)
    return {
        "success": success,
        "appointment_id": appointment_id,
        "message": "Appointment cancelled" if success else "Failed to cancel"
    }


@app.skill(name="complete_appointment")
def complete_appointment(
    business_id: str,
    appointment_id: str = None,
    customer_phone: str = None,
    service_type: str = None,
    amount: float = 0.0
) -> dict:
    """Mark an appointment as completed."""
    from shared.db import get_db
    
    if appointment_id:
        with get_db() as conn:
            appt = conn.execute(
                "SELECT * FROM appointments WHERE id = ?",
                (appointment_id,)
            ).fetchone()
            
            if not appt:
                return {"error": f"Appointment {appointment_id} not found"}
            
            conn.execute(
                "UPDATE appointments SET status = 'completed' WHERE id = ?",
                (appointment_id,)
            )
            conn.commit()
            
            customer_phone = appt['customer_phone']
            service_type = appt['service']
    
    if not customer_phone or not service_type:
        return {"error": "Either appointment_id or (customer_phone + service_type) required"}
    
    customer = update_customer_service(
        business_id=business_id,
        phone=customer_phone,
        service_type=service_type,
        service_date=datetime.now().strftime("%Y-%m-%d"),
        amount=amount
    )
    
    return {
        "customer_id": customer.id,
        "service_completed": service_type,
        "total_visits": customer.total_visits
    }


@app.skill(name="get_upcoming_appointments")
def get_upcoming_appointments(business_id: str, days: int = 7) -> dict:
    """Get all upcoming appointments for the next N days."""
    appointments = get_appointments_by_business(business_id, status="pending")
    
    return {
        "appointments": [
            {
                "id": a.id,
                "customer_phone": a.customer_phone,
                "customer_name": a.customer_name,
                "service": a.service,
                "datetime": a.datetime,
                "duration": a.duration,
                "notes": a.notes,
                "formatted": format_appointment(a)
            }
            for a in appointments
        ],
        "count": len(appointments)
    }


if __name__ == "__main__":
    init_db()
    print(f"[scheduling] Starting Scheduling Agent")
    print(f"[scheduling] AgentField URL: {AGENTFIELD_URL}")
    app.run(port=8003)
