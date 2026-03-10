"""
Customer Memory Module - Persistent memory for individual customers.

Stores customer preferences, history, and patterns in markdown files.
Designed to be business-agnostic and work for any service type.
"""

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

# Memory files are stored in customer_memory/{business_id}/{phone_hash}.md
MEMORY_BASE_PATH = os.getenv("CUSTOMER_MEMORY_PATH", "./customer_memory")


def _sanitize_phone(phone: str) -> str:
    """Convert phone to safe filename format."""
    # Remove all non-digits, keep last 10 digits
    digits = re.sub(r'\D', '', phone)
    return digits[-10:] if len(digits) >= 10 else digits


def _get_memory_path(business_id: str, phone: str) -> Path:
    """Get the path to a customer's memory file."""
    safe_phone = _sanitize_phone(phone)
    return Path(MEMORY_BASE_PATH) / business_id / f"{safe_phone}.md"


def _ensure_memory_dir(business_id: str) -> None:
    """Ensure the memory directory exists for a business."""
    path = Path(MEMORY_BASE_PATH) / business_id
    path.mkdir(parents=True, exist_ok=True)


def load_customer_memory(business_id: str, phone: str) -> Optional[str]:
    """
    Load a customer's memory file as raw markdown.
    Returns None if no memory exists.
    """
    path = _get_memory_path(business_id, phone)
    if path.exists():
        return path.read_text(encoding='utf-8')
    return None


def save_customer_memory(business_id: str, phone: str, content: str) -> None:
    """
    Save/overwrite a customer's memory file.
    """
    _ensure_memory_dir(business_id)
    path = _get_memory_path(business_id, phone)
    path.write_text(content, encoding='utf-8')


def parse_memory_sections(memory_content: str) -> Dict[str, Any]:
    """
    Parse a memory markdown file into structured sections.
    
    Expected format:
    # Customer: [Name]
    Phone: [number]
    First Contact: [date]
    Last Contact: [date]
    
    ## Preferences
    - key: value
    
    ## Service History
    - [date] service details
    
    ## Notes
    Free-form notes
    """
    sections = {
        "name": None,
        "phone": None,
        "first_contact": None,
        "last_contact": None,
        "preferences": {},
        "service_history": [],
        "notes": "",
    }
    
    if not memory_content:
        return sections
    
    # Parse header
    name_match = re.search(r'^# Customer:\s*(.+)$', memory_content, re.MULTILINE)
    if name_match:
        sections["name"] = name_match.group(1).strip()
    
    phone_match = re.search(r'^Phone:\s*(.+)$', memory_content, re.MULTILINE)
    if phone_match:
        sections["phone"] = phone_match.group(1).strip()
    
    first_contact_match = re.search(r'^First Contact:\s*(.+)$', memory_content, re.MULTILINE)
    if first_contact_match:
        sections["first_contact"] = first_contact_match.group(1).strip()
    
    last_contact_match = re.search(r'^Last Contact:\s*(.+)$', memory_content, re.MULTILINE)
    if last_contact_match:
        sections["last_contact"] = last_contact_match.group(1).strip()
    
    # Parse preferences section
    pref_match = re.search(r'## Preferences\n(.*?)(?=\n## |\Z)', memory_content, re.DOTALL)
    if pref_match:
        pref_lines = pref_match.group(1).strip().split('\n')
        for line in pref_lines:
            # Parse "- key: value" format
            kv_match = re.match(r'^-\s*([^:]+):\s*(.+)$', line.strip())
            if kv_match:
                key = kv_match.group(1).strip().lower().replace(' ', '_')
                value = kv_match.group(2).strip()
                sections["preferences"][key] = value
    
    # Parse service history section
    history_match = re.search(r'## Service History\n(.*?)(?=\n## |\Z)', memory_content, re.DOTALL)
    if history_match:
        history_lines = history_match.group(1).strip().split('\n')
        for line in history_lines:
            line = line.strip()
            if line.startswith('-'):
                sections["service_history"].append(line[1:].strip())
    
    # Parse notes section
    notes_match = re.search(r'## Notes\n(.*?)(?=\n## |\Z)', memory_content, re.DOTALL)
    if notes_match:
        sections["notes"] = notes_match.group(1).strip()
    
    return sections


def format_memory_markdown(
    phone: str,
    name: Optional[str] = None,
    first_contact: Optional[str] = None,
    last_contact: Optional[str] = None,
    preferences: Optional[Dict[str, str]] = None,
    service_history: Optional[List[str]] = None,
    notes: Optional[str] = None,
) -> str:
    """
    Format customer memory data into markdown.
    """
    now = datetime.now().strftime("%Y-%m-%d")
    
    lines = [
        f"# Customer: {name or 'Unknown'}",
        f"Phone: {phone}",
        f"First Contact: {first_contact or now}",
        f"Last Contact: {last_contact or now}",
        "",
        "## Preferences",
    ]
    
    if preferences:
        for key, value in preferences.items():
            # Convert snake_case back to Title Case for display
            display_key = key.replace('_', ' ').title()
            lines.append(f"- {display_key}: {value}")
    else:
        lines.append("- (none recorded yet)")
    
    lines.extend(["", "## Service History"])
    
    if service_history:
        for entry in service_history[-10:]:  # Keep last 10 entries
            lines.append(f"- {entry}")
    else:
        lines.append("- (no history yet)")
    
    lines.extend(["", "## Notes"])
    lines.append(notes or "(no notes)")
    
    return "\n".join(lines)


def update_customer_memory(
    business_id: str,
    phone: str,
    updates: Dict[str, Any],
) -> str:
    """
    Update a customer's memory with new information.
    Merges with existing data rather than replacing.
    
    updates can contain:
    - name: str
    - preferences: Dict[str, str] to merge
    - new_service: str (added to history with date)
    - notes: str (appended to existing notes)
    
    Returns the updated memory content.
    """
    existing = load_customer_memory(business_id, phone)
    now = datetime.now().strftime("%Y-%m-%d")
    
    if existing:
        data = parse_memory_sections(existing)
    else:
        data = {
            "name": None,
            "phone": phone,
            "first_contact": now,
            "last_contact": now,
            "preferences": {},
            "service_history": [],
            "notes": "",
        }
    
    # Update last contact
    data["last_contact"] = now
    
    # Update name if provided
    if updates.get("name"):
        data["name"] = updates["name"]
    
    # Merge preferences
    if updates.get("preferences"):
        data["preferences"].update(updates["preferences"])
    
    # Add new service to history
    if updates.get("new_service"):
        entry = f"[{now}] {updates['new_service']}"
        data["service_history"].append(entry)
    
    # Append notes
    if updates.get("notes"):
        existing_notes = data.get("notes", "") or ""
        if existing_notes and existing_notes != "(no notes)":
            data["notes"] = f"{existing_notes}\n[{now}] {updates['notes']}"
        else:
            data["notes"] = f"[{now}] {updates['notes']}"
    
    # Generate and save new markdown
    content = format_memory_markdown(
        phone=phone,
        name=data.get("name"),
        first_contact=data.get("first_contact"),
        last_contact=data.get("last_contact"),
        preferences=data.get("preferences"),
        service_history=data.get("service_history"),
        notes=data.get("notes"),
    )
    
    save_customer_memory(business_id, phone, content)
    return content


def get_memory_summary(business_id: str, phone: str) -> str:
    """
    Get a concise summary of customer memory for AI context.
    Returns empty string if no memory exists.
    """
    memory = load_customer_memory(business_id, phone)
    if not memory:
        return ""
    
    data = parse_memory_sections(memory)
    
    parts = []
    
    if data.get("name") and data["name"] != "Unknown":
        parts.append(f"Name: {data['name']}")
    
    if data.get("preferences"):
        prefs = [f"{k.replace('_', ' ')}: {v}" for k, v in data["preferences"].items()]
        if prefs:
            parts.append(f"Preferences: {', '.join(prefs)}")
    
    if data.get("service_history"):
        recent = data["service_history"][-3:]  # Last 3 services
        parts.append(f"Recent history: {'; '.join(recent)}")
    
    if data.get("notes") and data["notes"] != "(no notes)":
        # Just the last note line
        last_note = data["notes"].split('\n')[-1]
        if len(last_note) > 100:
            last_note = last_note[:100] + "..."
        parts.append(f"Note: {last_note}")
    
    return " | ".join(parts) if parts else ""


# AI extraction prompt template for extracting preferences from conversations
MEMORY_EXTRACTION_PROMPT = """Analyze this customer conversation and extract any useful information to remember for future interactions.

BUSINESS TYPE: {business_type}
CUSTOMER PHONE: {phone}
EXISTING MEMORY: {existing_memory}

CONVERSATION:
{conversation}

Extract the following if mentioned (respond in JSON format):
{{
  "name": "customer's name if mentioned (null if not)",
  "preferences": {{
    // Key preferences relevant to this business type. Examples:
    // For barbershop: "usual_service", "preferred_day", "preferred_time", "stylist", "price_point"
    // For plumber: "property_type", "common_issues", "preferred_contact_method"
    // For restaurant: "dietary_restrictions", "favorite_dishes", "party_size"
    // For any: "communication_style", "special_requests"
    // Only include preferences that were CLEARLY stated or demonstrated
  }},
  "new_service": "brief description of service discussed/booked, if any (null if not)",
  "notes": "any other important details worth remembering (null if nothing notable)"
}}

RULES:
- Only extract information that was CLEARLY stated or strongly implied
- Do not make assumptions or infer preferences
- Use null for fields with no information
- Keep values concise
- For preferences, use lowercase_snake_case keys
- If nothing useful to extract, return all null values"""


def get_extraction_prompt(
    business_type: str,
    phone: str,
    conversation: str,
    existing_memory: str = ""
) -> str:
    """
    Generate the prompt for AI memory extraction.
    """
    return MEMORY_EXTRACTION_PROMPT.format(
        business_type=business_type,
        phone=phone,
        existing_memory=existing_memory or "(no existing memory)",
        conversation=conversation,
    )
