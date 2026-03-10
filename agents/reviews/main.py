"""
Reviews Agent - Manages review monitoring and responses.

Specializes in:
- Monitoring reviews from various platforms
- Drafting responses to reviews
- Requesting reviews from happy customers
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
    node_id="reviews",
    agentfield_server=AGENTFIELD_URL,
    ai_config=AIConfig(
        model="anthropic/claude-haiku-4-5-20251001",
        api_key=ANTHROPIC_API_KEY,
        temperature=0.5,
        max_tokens=400,
    ),
)


@app.reasoner()
async def draft_response(review_text: str, rating: int, business_name: str) -> dict:
    """Draft a response to a customer review."""
    
    tone = "grateful and professional" if rating >= 4 else "apologetic and solution-focused"
    
    response = await app.ai(
        system=f"""Draft a response to a customer review for {business_name}.
Rating: {rating}/5 stars
Tone: {tone}

Keep it brief, authentic, and professional. Don't be overly apologetic or defensive.""",
        user=f"Review: {review_text}",
    )
    
    return {"draft_response": str(response)}


@app.reasoner()
async def request_review(customer_name: str, service: str, business_name: str) -> dict:
    """Generate a review request message for a happy customer."""
    
    response = await app.ai(
        system=f"""Generate a friendly SMS asking {customer_name} to leave a review for {business_name}.

They just received: {service}

Keep it:
- Brief (2-3 sentences)
- Warm and genuine
- Include a simple call to action""",
        user="Generate the review request",
    )
    
    return {"message": str(response)}


if __name__ == "__main__":
    init_db()
    print(f"[reviews] Starting Reviews Agent")
    print(f"[reviews] AgentField URL: {AGENTFIELD_URL}")
    app.run(port=8006)
