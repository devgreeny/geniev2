"""
Customer Service Agent - Handles customer inquiries and conversations.

Specializes in:
- Answering questions about services, pricing, hours
- Providing availability information
- Collecting customer information for leads
- General customer support
- Remembering customer preferences and history
"""

import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '../../.env'))

from agentfield import Agent, AIConfig

from shared.db import (
    init_db, 
    create_lead, 
    get_leads_by_phone,
    get_customer_by_phone,
    mark_reengagement_responded,
    get_recent_reengagement,
)
from shared.memory import (
    load_customer_memory,
    get_memory_summary,
    update_customer_memory,
    get_extraction_prompt,
    parse_memory_sections,
)

AGENTFIELD_URL = os.getenv("AGENTFIELD_URL", "http://localhost:8080")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

app = Agent(
    node_id="customer_service",
    agentfield_server=AGENTFIELD_URL,
    ai_config=AIConfig(
        model="anthropic/claude-haiku-4-5-20251001",
        api_key=ANTHROPIC_API_KEY,
        temperature=0.4,
        max_tokens=400,
    ),
)


@app.reasoner()
async def handle(phone: str, message: str, business_id: str, context: dict) -> dict:
    """
    Handle customer inquiries with business context and customer memory.
    """
    business_name = context.get("business_name", "our business")
    services = context.get("services", "our services")
    pricing = context.get("pricing", "Contact for pricing")
    hours = context.get("hours", "Contact for hours")
    availability = context.get("availability", "Available")
    custom_context = context.get("custom_context", "")
    conversation_history = context.get("conversation_history", "")
    
    # Load customer memory
    customer_memory = get_memory_summary(business_id, phone)
    full_memory = load_customer_memory(business_id, phone)
    memory_data = parse_memory_sections(full_memory) if full_memory else {}
    customer_name = memory_data.get("name") if memory_data.get("name") != "Unknown" else None
    
    # Check if new customer (no memory and no leads)
    existing_leads = get_leads_by_phone(business_id, phone)
    is_new_customer = len(existing_leads) == 0 and not full_memory
    
    # Check if this is a response to a re-engagement message
    is_reengagement_response = False
    customer = get_customer_by_phone(business_id, phone)
    if customer:
        recent_reengagement = get_recent_reengagement(business_id, customer.id)
        if recent_reengagement:
            # Customer received a re-engagement message recently and is now responding
            is_reengagement_response = True
            mark_reengagement_responded(customer.id, booked=False)
            print(f"[customer_service] Marked re-engagement response from {phone}")
    
    # Classify intent
    intent = await classify_intent(message, services)
    
    # Create lead if this looks like a new interested customer
    if intent in ["LEAD", "SCHEDULING", "PRICING"] and len(existing_leads) == 0:
        create_lead(business_id, phone, job_description=message)
        print(f"[customer_service] New lead created for {phone}")
    
    # Build memory context for the AI
    memory_context = ""
    if customer_memory:
        memory_context = f"""
CUSTOMER MEMORY (what we know about this customer):
{customer_memory}
- Use this information naturally - greet by name if known, reference their usual preferences!
"""
    
    system_prompt = f"""You are the customer service assistant for {business_name}.

BUSINESS INFORMATION:
- Services: {services}
- Pricing: {pricing}
- Hours: {hours}
- Current availability: {availability}
{f'- Additional info: {custom_context}' if custom_context else ''}
{memory_context}
{f'CONVERSATION HISTORY:\n{conversation_history}\n' if conversation_history else ''}
GUIDELINES:
- Respond as if you ARE the business (say "we" or "I", never "they")
- Be friendly, professional, and brief - this is SMS/chat
- IMPORTANT: Read the conversation history above - don't ask for info the customer already provided!
{f'- This customer is {customer_name} - use their name naturally!' if customer_name else ''}
- If they want to book, collect their name and what service they need
- If you can't answer confidently, say the owner will follow up
- Never mention AI, automation, or that you're a bot
- Keep responses to 2-3 sentences max
- {'This appears to be a new customer - be extra welcoming!' if is_new_customer else 'This is a returning customer - make them feel valued!'}
{f'- IMPORTANT: This customer is responding to a re-engagement message we sent them. Be extra warm and make booking easy!' if is_reengagement_response else ''}

DETECTED INTENT: {intent}"""

    if intent == "SCHEDULING":
        system_prompt += f"""

For scheduling requests:
- Share current availability: {availability}
- Ask what service they need if not specified
- Ask for their preferred date/time
- Confirm you'll get back to them to finalize"""
    
    elif intent == "PRICING":
        system_prompt += f"""

For pricing questions:
- Share relevant pricing: {pricing}
- If they need a custom quote, say you'll have the owner follow up
- Mention any current deals if applicable"""
    
    elif intent == "HOURS":
        system_prompt += f"""

For hours questions:
- Share business hours: {hours}
- Mention if walk-ins are welcome or appointments preferred"""

    response = await app.ai(
        system=system_prompt,
        user=message,
    )
    
    response_text = str(response)
    
    # Extract and save customer memory in background
    await extract_and_save_memory(
        business_id=business_id,
        phone=phone,
        business_type=services,
        customer_message=message,
        ai_response=response_text,
        existing_memory=full_memory,
    )
    
    # Run intelligence analysis in background (sentiment, opportunities)
    intelligence_result = await run_intelligence_analysis(
        business_id=business_id,
        phone=phone,
        message=message,
        conversation_history=conversation_history,
    )
    
    # If escalation is needed, flag it
    escalate = intelligence_result.get("escalate_to_human", False)
    alert_owner = intelligence_result.get("alert_owner", False)
    
    return {
        "reply": response_text,
        "escalate": escalate,
        "alert_owner": alert_owner,
        "alert_message": intelligence_result.get("alert_message"),
        "opportunities": intelligence_result.get("opportunities", []),
        "sentiment_score": intelligence_result.get("sentiment_score", 0),
    }


async def extract_and_save_memory(
    business_id: str,
    phone: str,
    business_type: str,
    customer_message: str,
    ai_response: str,
    existing_memory: str = None,
) -> None:
    """
    Extract useful information from the conversation and save to customer memory.
    This runs after every customer interaction to build up their profile.
    """
    try:
        # Build conversation context
        conversation = f"Customer: {customer_message}\nBusiness: {ai_response}"
        
        # Get extraction prompt
        extraction_prompt = get_extraction_prompt(
            business_type=business_type,
            phone=phone,
            conversation=conversation,
            existing_memory=existing_memory or "",
        )
        
        # Extract information using AI
        result = await app.ai(
            system="You are a data extraction assistant. Extract customer information from conversations and respond ONLY with valid JSON. No explanations.",
            user=extraction_prompt,
        )
        
        result_text = str(result).strip()
        
        # Parse JSON from response (handle markdown code blocks)
        if "```" in result_text:
            # Extract JSON from code block
            json_match = result_text.split("```")[1]
            if json_match.startswith("json"):
                json_match = json_match[4:]
            result_text = json_match.strip()
        
        # Find JSON object in response
        start = result_text.find("{")
        end = result_text.rfind("}") + 1
        if start >= 0 and end > start:
            result_text = result_text[start:end]
        
        extracted = json.loads(result_text)
        
        # Only update if there's something to save
        updates = {}
        
        if extracted.get("name"):
            updates["name"] = extracted["name"]
        
        if extracted.get("preferences"):
            # Filter out null values
            prefs = {k: v for k, v in extracted["preferences"].items() if v is not None}
            if prefs:
                updates["preferences"] = prefs
        
        if extracted.get("new_service"):
            updates["new_service"] = extracted["new_service"]
        
        if extracted.get("notes"):
            updates["notes"] = extracted["notes"]
        
        if updates:
            update_customer_memory(business_id, phone, updates)
            print(f"[customer_service] Updated memory for {phone}: {list(updates.keys())}")
        
    except json.JSONDecodeError as e:
        print(f"[customer_service] Failed to parse memory extraction: {e}")
    except Exception as e:
        print(f"[customer_service] Memory extraction failed: {e}")


async def run_intelligence_analysis(
    business_id: str,
    phone: str,
    message: str,
    conversation_history: str
) -> dict:
    """
    Run sentiment analysis and opportunity detection via the intelligence agent.
    This makes every conversation smarter and more proactive.
    """
    try:
        # Call intelligence agent for sentiment analysis
        sentiment_result = await app.call(
            "intelligence.analyze_sentiment_and_escalate",
            business_id=business_id,
            customer_phone=phone,
            message=message,
            conversation_history=conversation_history,
        )
        
        # Call intelligence agent for opportunity detection
        opportunity_result = await app.call(
            "intelligence.detect_opportunities",
            business_id=business_id,
            customer_phone=phone,
            message=message,
        )
        
        return {
            **sentiment_result,
            "opportunities": opportunity_result.get("opportunities", []),
            "has_opportunity": opportunity_result.get("has_opportunity", False),
        }
    except Exception as e:
        print(f"[customer_service] Intelligence analysis failed: {e}")
        return {"sentiment_score": 0, "escalate_to_human": False, "opportunities": []}


async def classify_intent(message: str, services: str) -> str:
    """Classify the customer's intent."""
    result = await app.ai(
        system=f"""Classify this customer message for a {services} business.

Categories:
- SCHEDULING (wants to book, reschedule, or ask about availability)
- PRICING (asking about costs, quotes, estimates)
- HOURS (asking about business hours)
- SERVICES (asking what services are offered)
- LEAD (expressing interest in hiring/booking for first time)
- GENERAL (other questions or conversation)

Respond with ONLY the category name, nothing else.""",
        user=message,
    )
    return str(result).strip().upper()


@app.skill(name="get_lead_status")
def get_lead_status(business_id: str, phone: str) -> dict:
    """Check if a phone number is already a lead."""
    leads = get_leads_by_phone(business_id, phone)
    if leads:
        return {
            "is_lead": True,
            "lead_count": len(leads),
            "latest_status": leads[0].status if leads else None,
        }
    return {"is_lead": False}


if __name__ == "__main__":
    init_db()
    print(f"[customer_service] Starting Customer Service Agent")
    print(f"[customer_service] AgentField URL: {AGENTFIELD_URL}")
    app.run(port=8002)
