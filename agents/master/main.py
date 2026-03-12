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

from shared.db import (
    init_db, get_business_by_id, get_recent_messages, update_business_context,
    is_ai_paused, pause_ai, resume_ai, get_ai_settings,
    get_pending_approvals, get_pending_approval_count, approve_message, reject_message, get_approval_by_id,
    get_today_summary
)

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


def parse_owner_command(message: str) -> tuple:
    """
    Parse owner commands from message.
    Returns (command_type, args) or (None, None) if not a command.
    
    Supported commands:
    - summary today / summary / today
    - pause ai / pause
    - resume ai / resume
    - approve <id> / approve
    - approvals / pending
    - reject <id>
    """
    msg_lower = message.lower().strip()
    
    # Summary command
    if msg_lower in ['summary today', 'summary', 'today', 'status', "what's up", 'whats up']:
        return ('summary', None)
    
    # Pause AI
    if msg_lower in ['pause ai', 'pause', 'stop ai', 'stop']:
        return ('pause', None)
    
    # Resume AI
    if msg_lower in ['resume ai', 'resume', 'start ai', 'start', 'unpause']:
        return ('resume', None)
    
    # List approvals
    if msg_lower in ['approvals', 'pending', 'queue', 'approval queue']:
        return ('list_approvals', None)
    
    # Approve message
    if msg_lower.startswith('approve '):
        approval_id = message[8:].strip()
        return ('approve', approval_id)
    if msg_lower == 'approve':
        return ('approve', None)  # Approve first pending
    
    # Reject message
    if msg_lower.startswith('reject '):
        approval_id = message[7:].strip()
        return ('reject', approval_id)
    
    return (None, None)


async def handle_owner_command(command: str, args, context: dict) -> str:
    """Handle specific owner commands."""
    business_id = context["business_id"]
    
    if command == 'summary':
        summary = get_today_summary(business_id)
        parts = [f"📊 Today ({summary['date']})"]
        parts.append(f"💬 {summary['customer_messages']} customer msgs from {summary['unique_customers']} people")
        parts.append(f"📅 {summary['appointments_today']} appts today, {summary['pending_appointments']} upcoming")
        
        if summary['new_leads'] > 0:
            parts.append(f"🎯 {summary['new_leads']} new leads")
        
        if summary['pending_approvals'] > 0:
            parts.append(f"⏳ {summary['pending_approvals']} msgs awaiting approval")
        
        if summary['ai_paused']:
            parts.append("🔴 AI is PAUSED")
        else:
            parts.append("🟢 AI is active")
        
        return "\n".join(parts)
    
    elif command == 'pause':
        pause_ai(business_id, "owner")
        return "🔴 AI paused. Customer messages will be held. Say 'resume' to reactivate."
    
    elif command == 'resume':
        resume_ai(business_id)
        return "🟢 AI resumed. Now responding to customers automatically."
    
    elif command == 'list_approvals':
        pending = get_pending_approvals(business_id)
        if not pending:
            return "✅ No messages pending approval."
        
        parts = [f"📋 {len(pending)} pending approval(s):"]
        for i, item in enumerate(pending[:5], 1):
            short_id = item['id'][:8]
            msg_preview = item['message_text'][:50] + "..." if len(item['message_text']) > 50 else item['message_text']
            recipient = item.get('recipient_name') or item['recipient_phone']
            parts.append(f"{i}. To {recipient}: \"{msg_preview}\" (ID: {short_id})")
        
        if len(pending) > 5:
            parts.append(f"...and {len(pending) - 5} more")
        
        parts.append("\nReply 'approve <id>' or just 'approve' to approve first one.")
        return "\n".join(parts)
    
    elif command == 'approve':
        if args:
            # Try to find approval by full ID or partial ID
            approval = get_approval_by_id(args)
            if not approval:
                # Try partial match
                pending = get_pending_approvals(business_id)
                for item in pending:
                    if item['id'].startswith(args):
                        approval = item
                        break
            
            if not approval:
                return f"❌ Approval ID '{args}' not found."
            
            approve_message(approval['id'], "owner")
            return f"✅ Approved message to {approval.get('recipient_name') or approval['recipient_phone']}"
        else:
            # Approve first pending
            pending = get_pending_approvals(business_id)
            if not pending:
                return "✅ No messages pending approval."
            
            first = pending[0]
            approve_message(first['id'], "owner")
            return f"✅ Approved message to {first.get('recipient_name') or first['recipient_phone']}: \"{first['message_text'][:50]}...\""
    
    elif command == 'reject':
        if not args:
            return "❌ Please specify an approval ID to reject."
        
        approval = get_approval_by_id(args)
        if not approval:
            # Try partial match
            pending = get_pending_approvals(business_id)
            for item in pending:
                if item['id'].startswith(args):
                    approval = item
                    break
        
        if not approval:
            return f"❌ Approval ID '{args}' not found."
        
        reject_message(approval['id'], "owner")
        return f"🚫 Rejected message to {approval.get('recipient_name') or approval['recipient_phone']}"
    
    return "❓ Unknown command."


async def handle_owner_message(phone: str, message: str, context: dict) -> str:
    """Handle messages from the business owner."""
    
    # First check if this is a command
    command, args = parse_owner_command(message)
    if command:
        print(f"[master] Owner command detected: {command} {args}")
        return await handle_owner_command(command, args, context)
    
    # Check if this is a context update
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
    
    # Get AI status
    ai_paused = is_ai_paused(context["business_id"])
    ai_status = "🔴 AI is currently PAUSED" if ai_paused else "🟢 AI is active"
    
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

Current AI status: {ai_status}

Recent customer conversations:
{recent_summary}

Owner commands available:
- "summary" or "today" - get today's overview
- "pause" - pause AI responses
- "resume" - resume AI responses
- "approvals" - see pending approval queue
- "approve" or "approve <id>" - approve a message

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
