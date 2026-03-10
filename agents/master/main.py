"""
Master Agent - The orchestrator that routes messages to specialist agents.

Receives all inbound messages from the SMS gateway and:
1. Loads business context
2. Classifies intent
3. Routes to the appropriate specialist agent (via AgentField)
4. Returns the combined response
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '../../.env'))

from agentfield import Agent, AIConfig

from shared.db import init_db, get_business_by_id, get_recent_messages, update_business_context

AGENTFIELD_URL = os.getenv("AGENTFIELD_URL", "http://localhost:8080")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

app = Agent(
    node_id="master",
    agentfield_server=AGENTFIELD_URL,
    ai_config=AIConfig(
        model="anthropic/claude-haiku-4-5-20251001",
        api_key=ANTHROPIC_API_KEY,
        temperature=0.3,
        max_tokens=500,
    ),
)


def get_business_context(business_id: str) -> dict:
    """Load business info and recent conversation history."""
    business = get_business_by_id(business_id)
    if not business:
        return {}
    
    recent_customer = get_recent_messages(business_id, "customer", hours_back=24, limit=10)
    recent_owner = get_recent_messages(business_id, "owner", hours_back=24, limit=10)
    
    return {
        "business_id": business.id,
        "business_name": business.business_name,
        "owner_name": business.owner_name,
        "services": business.services or "Not specified",
        "pricing": business.pricing or "Contact for pricing",
        "hours": business.hours or "Contact for hours",
        "location": business.location or "Not specified",
        "availability": business.availability or "Available",
        "custom_context": business.custom_context or "",
        "recent_customer_messages": [
            {"direction": m.direction, "message": m.message} 
            for m in recent_customer
        ],
        "recent_owner_messages": [
            {"direction": m.direction, "message": m.message}
            for m in recent_owner
        ],
    }


@app.reasoner()
async def handle_message(phone: str, message: str, business_id: str, is_owner: bool, conversation_history: str = "") -> dict:
    """
    Main entry point for all SMS/Telegram messages.
    Routes to appropriate handler based on sender type.
    """
    context = get_business_context(business_id)
    
    if not context:
        return {"response": "Sorry, we couldn't find your business information. Please try again later."}
    
    # Add conversation history to context
    context["conversation_history"] = conversation_history
    
    if is_owner:
        result = await handle_owner_message(phone, message, context)
    else:
        result = await handle_customer_message(phone, message, context)
    
    return {"response": result}


async def handle_owner_message(phone: str, message: str, context: dict) -> str:
    """Handle messages from the business owner."""
    
    # First check if this is a context update
    update_check = await app.ai(
        system="""You are analyzing a message from a business owner to determine if it contains an update to their business info.
        
If the message contains an update to availability, pricing, hours, services, or other business context, respond with JSON:
{"field": "availability"|"pricing"|"hours"|"services"|"custom_context", "value": "the new value"}

If the message is NOT an update, respond with: null

Examples:
- "I'm booked until Friday" → {"field": "availability", "value": "Booked until Friday"}
- "We now charge $30 for haircuts" → {"field": "pricing", "value": "$30 for haircuts"}
- "What did I miss?" → null""",
        user=message,
    )
    
    # Parse and apply update if detected
    update_text = str(update_check).strip()
    if update_text != "null" and "{" in update_text:
        try:
            import json
            # Extract JSON from response
            start = update_text.index("{")
            end = update_text.rindex("}") + 1
            update = json.loads(update_text[start:end])
            if update and "field" in update and "value" in update:
                update_business_context(context["business_id"], update["field"], update["value"])
                print(f"[master] Updated {update['field']} for {context['business_name']}")
        except (json.JSONDecodeError, ValueError) as e:
            print(f"[master] Failed to parse update: {e}")
    
    # Build summary of recent activity
    recent_summary = "\n".join([
        f"- [{m['direction']}] {m['message'][:100]}"
        for m in context.get('recent_customer_messages', [])[:5]
    ]) or "No recent customer messages."
    
    # Generate response
    response = await app.ai(
        system=f"""You are a business assistant for {context['business_name']}, owned by {context['owner_name']}.

You help the owner manage their business via text. You can:
- Answer questions about recent customer conversations
- Summarize what's happening
- Acknowledge updates to business info
- Help draft responses

Business info:
- Services: {context['services']}
- Pricing: {context['pricing']}
- Hours: {context['hours']}
- Availability: {context['availability']}
- Notes: {context['custom_context']}

Recent customer conversations:
{recent_summary}

Keep responses brief - this is SMS. Max 2-3 sentences.""",
        user=message,
    )
    
    return str(response)


async def handle_customer_message(phone: str, message: str, context: dict) -> str:
    """Handle messages from customers - route to appropriate specialist agent."""
    
    # First, classify if this is a scheduling-related request
    scheduling_keywords = ['book', 'appointment', 'schedule', 'cancel', 'reschedule', 
                          'move', 'change', 'available', 'slot', 'time', 'when can',
                          'come in', 'see you', 'next week', 'tomorrow', 'saturday',
                          'sunday', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday']
    
    message_lower = message.lower()
    is_scheduling = any(keyword in message_lower for keyword in scheduling_keywords)
    
    # Route to appropriate agent
    if is_scheduling:
        try:
            result = await app.call(
                "scheduling.handle",
                phone=phone,
                message=message,
                business_id=context["business_id"],
                context=context,
            )
            return result.get("reply", "Thanks for your message! We'll get back to you shortly.")
        except Exception as e:
            print(f"[master] Scheduling agent call failed: {e}, falling back to customer_service")
    
    # Default: route to customer_service
    try:
        result = await app.call(
            "customer_service.handle",
            phone=phone,
            message=message,
            business_id=context["business_id"],
            context=context,
        )
        return result.get("reply", "Thanks for your message! We'll get back to you shortly.")
    except Exception as e:
        print(f"[master] Customer service agent call failed: {e}")
        # Fallback: handle directly
        response = await app.ai(
            system=f"""You are the assistant for {context['business_name']}.

Business info:
- Services: {context['services']}
- Pricing: {context['pricing']}
- Hours: {context['hours']}
- Availability: {context['availability']}

Answer the customer's question professionally. Keep it brief - this is SMS.
If you can't answer confidently, say you'll have the owner follow up.
Never mention AI or that you're automated.""",
            user=message,
        )
        return str(response)


@app.skill(name="get_context")
def get_context_skill(business_id: str) -> dict:
    """Skill for other agents to fetch business context."""
    return get_business_context(business_id)


if __name__ == "__main__":
    init_db()
    print(f"[master] Starting Master Agent")
    print(f"[master] AgentField URL: {AGENTFIELD_URL}")
    app.run(port=8001)
