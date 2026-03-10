"""
Payments Agent - Handles invoicing and payment reminders.

Specializes in:
- Creating invoices
- Sending payment reminders
- Tracking payment status
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '../../.env'))

from agentfield import Agent, AIConfig
from shared.db import init_db

AGENTFIELD_URL = os.getenv("AGENTFIELD_URL", "http://localhost:8080")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

app = Agent(
    node_id="payments",
    agentfield_server=AGENTFIELD_URL,
    ai_config=AIConfig(
        model="anthropic/claude-haiku-4-5-20251001",
        api_key=ANTHROPIC_API_KEY,
        temperature=0.2,
        max_tokens=300,
    ),
)


@app.reasoner()
async def handle(phone: str, message: str, business_id: str, context: dict) -> dict:
    """Handle payment-related requests."""
    
    response = await app.ai(
        system=f"""You are the payments assistant for {context.get('business_name', 'a business')}.

Pricing: {context.get('pricing', 'Contact for pricing')}

Help with:
- Providing price quotes
- Explaining payment options
- Answering billing questions

Keep it brief - this is SMS.""",
        user=message,
    )
    
    return {"reply": str(response)}


if __name__ == "__main__":
    init_db()
    print(f"[payments] Starting Payments Agent")
    print(f"[payments] AgentField URL: {AGENTFIELD_URL}")
    app.run(port=8005)
