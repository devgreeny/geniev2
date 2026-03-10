"""
Intelligence Agent - Autonomous decision-making and proactive customer management.

This agent runs PROACTIVELY (not just in response to messages) to:
- Score and prioritize leads based on conversation analysis
- Predict customer churn before it happens
- Decide when and how to follow up with prospects
- Detect sentiment issues and trigger recovery actions
- Identify upsell/cross-sell opportunities

This is the "brain" that makes the system truly agentic.
"""

import os
import sys
from datetime import datetime, timedelta
from typing import List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '../../.env'))

from agentfield import Agent, AIConfig
from shared.db import (
    init_db,
    get_db,
    get_all_businesses,
    get_business_by_id,
    get_leads_by_phone,
    get_customers_by_business,
    get_recent_messages,
    get_customer_by_id,
    create_lead,
)

AGENTFIELD_URL = os.getenv("AGENTFIELD_URL", "http://localhost:8080")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

app = Agent(
    node_id="intelligence",
    agentfield_server=AGENTFIELD_URL,
    ai_config=AIConfig(
        model="anthropic/claude-sonnet-4-20250514",  # Use smarter model for decision-making
        api_key=ANTHROPIC_API_KEY,
        temperature=0.3,
        max_tokens=1000,
    ),
)


# ============== Lead Scoring ==============

LEAD_SCORE_CRITERIA = """
Score leads from 0-100 based on:

BUYING SIGNALS (high scores):
- Asking about pricing (+20)
- Asking about availability (+25)
- Mentioning urgency ("need it soon", "asap") (+30)
- Asking specific questions about services (+15)
- Mentioning a specific date/time (+20)
- Responding quickly to messages (+10)

NEUTRAL SIGNALS:
- General inquiries (+5)
- Asking about location/hours (+5)

NEGATIVE SIGNALS:
- Price objections ("too expensive") (-15)
- Long response delays (-10)
- Vague or non-committal responses (-10)
- Mentioning competitors (-5)
- "Just browsing" or "maybe later" (-20)

Also determine:
- recommended_action: "hot_follow_up" | "nurture" | "wait" | "close_lost"
- follow_up_message: A personalized follow-up message if action is hot_follow_up or nurture
- reasoning: Brief explanation of the score
"""


@app.reasoner()
async def score_lead(
    business_id: str,
    customer_phone: str,
    conversation_history: str
) -> dict:
    """
    Analyze a lead's conversation history and score their likelihood to convert.
    Returns score (0-100), recommended action, and suggested follow-up.
    """
    business = get_business_by_id(business_id)
    business_context = f"{business.business_name} - {business.services}" if business else "Unknown business"
    
    result = await app.ai(
        system=f"""You are a lead scoring AI for {business_context}.

{LEAD_SCORE_CRITERIA}

Respond with JSON only:
{{
    "score": <0-100>,
    "temperature": "hot" | "warm" | "cold",
    "recommended_action": "hot_follow_up" | "nurture" | "wait" | "close_lost",
    "follow_up_message": "<personalized message or null>",
    "reasoning": "<brief explanation>",
    "objections_detected": ["<any objections>"],
    "buying_signals": ["<signals detected>"]
}}""",
        user=f"Score this lead based on their conversation:\n\n{conversation_history}",
    )
    
    import json
    try:
        result_text = str(result)
        start = result_text.find("{")
        end = result_text.rfind("}") + 1
        return json.loads(result_text[start:end])
    except:
        return {"score": 50, "temperature": "warm", "recommended_action": "nurture", "error": "Failed to parse"}


@app.skill(name="score_all_leads")
def score_all_leads(business_id: str) -> dict:
    """
    Score all active leads for a business and return prioritized list.
    """
    # This will be called by the cron job
    return {"status": "queued", "business_id": business_id}


# ============== Churn Prediction ==============

CHURN_INDICATORS = """
Analyze customer behavior to predict churn risk (0-100):

HIGH RISK INDICATORS:
- Longer than usual gap since last visit (+30)
- Decreasing visit frequency (+25)
- Negative sentiment in recent messages (+20)
- Complained about service/price (+25)
- Mentioned trying competitors (+30)
- Cancelled recent appointments (+20)

MEDIUM RISK:
- Slightly longer gap than usual (+10)
- Shorter/less engaged conversations (+10)
- Asked about refunds/policies (+15)

LOW RISK (retention signals):
- Regular visit pattern (-20)
- Positive feedback (-15)
- Referred others (-20)
- Pre-booked next appointment (-25)
- VIP/loyal customer status (-10)

Also recommend a retention action if risk > 50.
"""


@app.reasoner()
async def predict_churn(
    business_id: str,
    customer_id: str
) -> dict:
    """
    Predict churn risk for a customer and recommend retention actions.
    """
    customer = get_customer_by_id(customer_id)
    if not customer:
        return {"error": "Customer not found"}
    
    business = get_business_by_id(business_id)
    
    # Get conversation history
    messages = get_recent_messages(business_id, "customer", hours_back=720, limit=50)  # Last 30 days
    customer_messages = [m for m in messages if m.participant_phone == customer.phone]
    
    conversation_summary = "\n".join([
        f"[{m.direction}] {m.message[:100]}" for m in customer_messages[-10:]
    ]) if customer_messages else "No recent messages"
    
    # Calculate days since last service
    days_since_service = None
    if customer.last_service_date:
        try:
            last_date = datetime.strptime(customer.last_service_date, "%Y-%m-%d")
            days_since_service = (datetime.now() - last_date).days
        except:
            pass
    
    customer_profile = f"""
Customer: {customer.name or 'Unknown'}
Phone: {customer.phone}
Total visits: {customer.total_visits}
Last service: {customer.last_service_type} ({days_since_service} days ago)
Segment: {customer.segment}
Lifetime value: ${customer.lifetime_value:.2f}
Average visit interval: {customer.avg_visit_interval or 'Unknown'} days

Recent conversation:
{conversation_summary}
"""
    
    result = await app.ai(
        system=f"""You are a churn prediction AI for {business.business_name if business else 'a business'}.

{CHURN_INDICATORS}

Respond with JSON only:
{{
    "churn_risk": <0-100>,
    "risk_level": "low" | "medium" | "high" | "critical",
    "days_until_likely_churn": <estimated days or null>,
    "risk_factors": ["<factors contributing to risk>"],
    "retention_signals": ["<positive signals>"],
    "recommended_action": "none" | "check_in" | "offer_incentive" | "personal_outreach" | "vip_treatment",
    "retention_message": "<personalized retention message or null>",
    "offer_suggestion": "<discount/offer suggestion or null>",
    "reasoning": "<brief explanation>"
}}""",
        user=f"Predict churn risk for this customer:\n\n{customer_profile}",
    )
    
    import json
    try:
        result_text = str(result)
        start = result_text.find("{")
        end = result_text.rfind("}") + 1
        parsed = json.loads(result_text[start:end])
        parsed["customer_id"] = customer_id
        parsed["customer_name"] = customer.name
        return parsed
    except:
        return {"churn_risk": 50, "risk_level": "medium", "error": "Failed to parse"}


@app.skill(name="get_churn_risks")
def get_churn_risks(business_id: str, min_risk: int = 50) -> dict:
    """
    Get all customers above a certain churn risk threshold.
    Returns customers that need attention.
    """
    customers = get_customers_by_business(business_id)
    return {
        "customers_to_analyze": len(customers),
        "min_risk_threshold": min_risk,
        "status": "Use predict_churn() for each customer"
    }


# ============== Smart Follow-up Decisions ==============

@app.reasoner()
async def decide_follow_up(
    business_id: str,
    customer_phone: str,
    last_interaction: str,
    days_since_interaction: int,
    context: dict = None
) -> dict:
    """
    Autonomously decide whether, when, and how to follow up with a prospect.
    This is the core "agentic" decision-making function.
    """
    business = get_business_by_id(business_id)
    
    # Check existing leads
    existing_leads = get_leads_by_phone(business_id, customer_phone)
    lead_status = existing_leads[0].status if existing_leads else "unknown"
    
    result = await app.ai(
        system=f"""You are an autonomous sales AI for {business.business_name if business else 'a business'}.

Your job is to decide the OPTIMAL follow-up strategy. You must balance:
- Being persistent enough to close deals
- Not being annoying or spammy
- Personalizing based on the conversation
- Timing follow-ups strategically

Decision factors:
- Days since last interaction: {days_since_interaction}
- Lead status: {lead_status}
- Conversation ended with customer or business?
- Was there an unanswered question?
- Did they express interest or objections?

Rules:
- Never follow up more than once per day
- If they said "not interested", wait at least 14 days
- If they asked a question we didn't answer, follow up within 24h
- Hot leads (asked about booking): follow up within 4h if no response
- Warm leads: follow up in 2-3 days
- Cold leads: nurture sequence (weekly)

Respond with JSON:
{{
    "should_follow_up": true | false,
    "urgency": "immediate" | "today" | "tomorrow" | "this_week" | "next_week" | "never",
    "follow_up_type": "answer_question" | "check_in" | "offer" | "value_add" | "last_chance" | "none",
    "message": "<the exact follow-up message to send>",
    "reasoning": "<why this decision>",
    "wait_hours": <hours to wait before sending, 0 for immediate>
}}""",
        user=f"""Decide follow-up for this conversation:

Last interaction ({days_since_interaction} days ago):
{last_interaction}

Additional context: {context or 'None'}""",
    )
    
    import json
    try:
        result_text = str(result)
        start = result_text.find("{")
        end = result_text.rfind("}") + 1
        parsed = json.loads(result_text[start:end])
        parsed["customer_phone"] = customer_phone
        parsed["business_id"] = business_id
        return parsed
    except:
        return {"should_follow_up": False, "urgency": "never", "error": "Failed to parse"}


# ============== Sentiment Analysis & Escalation ==============

@app.reasoner()
async def analyze_sentiment_and_escalate(
    business_id: str,
    customer_phone: str,
    message: str,
    conversation_history: str = ""
) -> dict:
    """
    Analyze customer sentiment in real-time and decide if escalation is needed.
    This runs on every incoming message to catch issues early.
    """
    business = get_business_by_id(business_id)
    
    result = await app.ai(
        system=f"""You are a sentiment analysis AI for {business.business_name if business else 'a business'}.

Analyze the customer's message for:
1. Overall sentiment (-100 to +100)
2. Emotional state (frustrated, angry, happy, neutral, confused, anxious)
3. Urgency level
4. Whether human intervention is needed

ESCALATION TRIGGERS (require human):
- Threats (legal, social media, etc.)
- Repeated complaints
- Request to speak to manager/owner
- Abusive language
- Complex issues AI can't resolve
- High-value customer upset
- Safety concerns

RECOVERY OPPORTUNITIES:
- Mild frustration: Acknowledge and offer solution
- Confusion: Clarify with patience
- Price concerns: Offer value explanation or discount
- Wait time complaints: Apologize and prioritize

Respond with JSON:
{{
    "sentiment_score": <-100 to +100>,
    "emotional_state": "<state>",
    "urgency": "low" | "medium" | "high" | "critical",
    "escalate_to_human": true | false,
    "escalation_reason": "<reason or null>",
    "recovery_possible": true | false,
    "recovery_action": "apologize" | "offer_discount" | "expedite" | "clarify" | "empathize" | "none",
    "suggested_response": "<AI response if not escalating>",
    "alert_owner": true | false,
    "alert_message": "<message to owner if alert needed>"
}}""",
        user=f"""Analyze this customer message:

Message: {message}

Conversation history:
{conversation_history or 'No history'}""",
    )
    
    import json
    try:
        result_text = str(result)
        start = result_text.find("{")
        end = result_text.rfind("}") + 1
        return json.loads(result_text[start:end])
    except:
        return {"sentiment_score": 0, "escalate_to_human": False, "error": "Failed to parse"}


# ============== Opportunity Detection ==============

@app.reasoner()
async def detect_opportunities(
    business_id: str,
    customer_phone: str,
    message: str,
    customer_history: dict = None
) -> dict:
    """
    Detect upsell, cross-sell, and referral opportunities from conversations.
    """
    business = get_business_by_id(business_id)
    services = business.services if business else "various services"
    
    result = await app.ai(
        system=f"""You are an opportunity detection AI for {business.business_name if business else 'a business'}.

Services offered: {services}

Detect opportunities in customer messages:

UPSELL OPPORTUNITIES:
- Customer mentions related needs
- Asking about premium options
- Expressing desire for better results
- Time-sensitive needs (willing to pay more)

CROSS-SELL OPPORTUNITIES:
- Mentions problems our other services solve
- Life events (wedding, new job, moving)
- Seasonal needs

REFERRAL OPPORTUNITIES:
- Very positive sentiment
- Mentions friends/family
- Asks if we have other locations
- Compliments the service

Respond with JSON:
{{
    "opportunities": [
        {{
            "type": "upsell" | "cross_sell" | "referral",
            "confidence": <0-100>,
            "service_to_suggest": "<service name>",
            "trigger_phrase": "<what they said that triggered this>",
            "suggested_pitch": "<natural way to mention this>"
        }}
    ],
    "has_opportunity": true | false,
    "best_opportunity": "<type of best opportunity or null>",
    "timing": "now" | "end_of_conversation" | "follow_up"
}}""",
        user=f"""Detect opportunities in this message:

Message: {message}

Customer history: {customer_history or 'New customer'}""",
    )
    
    import json
    try:
        result_text = str(result)
        start = result_text.find("{")
        end = result_text.rfind("}") + 1
        return json.loads(result_text[start:end])
    except:
        return {"has_opportunity": False, "opportunities": []}


# ============== Proactive Outreach Decisions ==============

@app.skill(name="get_proactive_actions")
def get_proactive_actions(business_id: str) -> dict:
    """
    Analyze all customers and leads to determine who needs proactive outreach TODAY.
    This is meant to be called by a daily cron job.
    
    Returns a prioritized list of actions the business should take.
    """
    actions = []
    
    business = get_business_by_id(business_id)
    if not business:
        return {"error": "Business not found"}
    
    # Get all customers
    customers = get_customers_by_business(business_id)
    
    today = datetime.now()
    
    for customer in customers:
        action = None
        priority = 0
        
        # Check for various conditions
        if customer.last_service_date:
            try:
                last_date = datetime.strptime(customer.last_service_date, "%Y-%m-%d")
                days_since = (today - last_date).days
                
                # At-risk: longer than 2x their average interval
                if customer.avg_visit_interval and days_since > customer.avg_visit_interval * 2:
                    action = {
                        "type": "churn_prevention",
                        "customer_id": customer.id,
                        "customer_name": customer.name,
                        "customer_phone": customer.phone,
                        "reason": f"No visit in {days_since} days (usually every {customer.avg_visit_interval} days)",
                        "suggested_action": "Send personalized check-in with offer"
                    }
                    priority = 80
                
                # VIP hasn't been in a while
                elif customer.segment == "vip" and days_since > 45:
                    action = {
                        "type": "vip_outreach",
                        "customer_id": customer.id,
                        "customer_name": customer.name,
                        "customer_phone": customer.phone,
                        "reason": f"VIP customer hasn't visited in {days_since} days",
                        "suggested_action": "Personal check-in from owner"
                    }
                    priority = 90
                    
            except ValueError:
                pass
        
        # New customer who only visited once (30+ days ago)
        if customer.total_visits == 1 and customer.segment == "new":
            if customer.last_service_date:
                try:
                    last_date = datetime.strptime(customer.last_service_date, "%Y-%m-%d")
                    days_since = (today - last_date).days
                    if 14 <= days_since <= 45:
                        action = {
                            "type": "new_customer_nurture",
                            "customer_id": customer.id,
                            "customer_name": customer.name,
                            "customer_phone": customer.phone,
                            "reason": f"New customer visited {days_since} days ago, no return yet",
                            "suggested_action": "Send thank you + incentive for second visit"
                        }
                        priority = 70
                except ValueError:
                    pass
        
        if action:
            action["priority"] = priority
            actions.append(action)
    
    # Sort by priority
    actions.sort(key=lambda x: x["priority"], reverse=True)
    
    return {
        "business_name": business.business_name,
        "date": today.strftime("%Y-%m-%d"),
        "total_actions": len(actions),
        "actions": actions[:20],  # Top 20 priorities
        "summary": {
            "churn_prevention": len([a for a in actions if a["type"] == "churn_prevention"]),
            "vip_outreach": len([a for a in actions if a["type"] == "vip_outreach"]),
            "new_customer_nurture": len([a for a in actions if a["type"] == "new_customer_nurture"]),
        }
    }


# ============== Batch Intelligence Processing ==============

@app.skill(name="run_daily_intelligence")
def run_daily_intelligence(business_id: str = None) -> dict:
    """
    Run all intelligence analysis for a business (or all businesses).
    This should be called by a daily cron job.
    
    Returns a summary of insights and recommended actions.
    """
    results = []
    
    if business_id:
        businesses = [get_business_by_id(business_id)]
    else:
        businesses = get_all_businesses()
    
    for business in businesses:
        if not business:
            continue
            
        # Get proactive actions
        actions = get_proactive_actions(business.id)
        
        results.append({
            "business_id": business.id,
            "business_name": business.business_name,
            "actions": actions
        })
    
    return {
        "processed_businesses": len(results),
        "results": results,
        "run_at": datetime.now().isoformat()
    }


if __name__ == "__main__":
    init_db()
    print(f"[intelligence] Starting Intelligence Agent")
    print(f"[intelligence] AgentField URL: {AGENTFIELD_URL}")
    app.run(port=8005)
