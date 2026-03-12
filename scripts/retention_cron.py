#!/usr/bin/env python3
"""
Retention Engine v1 - Simplified 3-Campaign System

This script runs 3 focused retention campaigns:
1. NO-SHOW RESCUE - Contact customers who missed appointments
2. WIN-BACK (30/60 day) - Re-engage lapsed customers  
3. POST-VISIT REBOOK - Nudge customers after completed visits

Stop conditions: replied, booked, opted-out

Usage:
    # Run all campaigns
    python scripts/retention_cron.py

    # Dry run (preview what would be sent)
    python scripts/retention_cron.py --dry-run

    # Run specific campaign only
    python scripts/retention_cron.py --campaign no_show
    python scripts/retention_cron.py --campaign win_back
    python scripts/retention_cron.py --campaign post_visit

    # Run for specific business
    python scripts/retention_cron.py --business-id <id>

    # Show recent campaign logs
    python scripts/retention_cron.py --logs

Cron setup (recommended):
    # Run 3x daily: 10am, 2pm, 6pm
    0 10,14,18 * * * cd /path/to/genie && python scripts/retention_cron.py >> logs/retention.log 2>&1
"""

import os
import sys
import argparse
import requests
import time
from datetime import datetime
from typing import Optional

# Add agents to path for shared modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '../.env'))

from shared.db import (
    init_db,
    get_all_businesses,
    get_business_by_id,
    get_customer_by_phone,
    get_or_create_customer,
    # No-show detection
    get_no_show_appointments,
    mark_appointment_no_show,
    # Win-back
    get_lapsed_customers,
    # Post-visit
    get_completed_appointments_since,
    # Stop conditions
    has_upcoming_appointment,
    was_customer_contacted_recently,
    # Logging
    create_campaign_run,
    complete_campaign_run,
    log_campaign_message,
    get_recent_campaign_runs,
)

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://localhost:8080")
DEMO_MODE = os.getenv("DEMO_MODE", "false").lower() == "true"

# Rate limiting
DELAY_BETWEEN_MESSAGES = 1.0  # seconds


# ============== Message Templates ==============
# Simple, human, pilot-ready messages

TEMPLATES = {
    "no_show_rescue": """Hey {name}! We missed you at your appointment today. No worries - life happens! Would you like to reschedule? Just reply with a day/time that works. - {business_name}""",
    
    "win_back_30": """Hi {name}! It's been about a month since we've seen you at {business_name}. Ready for another visit? Reply to book! 😊""",
    
    "win_back_60": """Hey {name}! We miss you at {business_name}! It's been a while - reply and let's get you scheduled. We'd love to see you again!""",
    
    "post_visit_rebook": """Thanks for coming in today, {name}! 🙌 When would you like your next appointment at {business_name}? Reply with a day/time and I'll get you booked!""",
}


def format_message(template_key: str, customer_name: Optional[str], business_name: str) -> str:
    """Format a message template with customer/business info."""
    name = customer_name or "there"
    template = TEMPLATES.get(template_key, TEMPLATES["win_back_30"])
    return template.format(name=name, business_name=business_name)


def send_sms(to: str, from_number: str, message: str, dry_run: bool = False) -> bool:
    """Send SMS via gateway."""
    if dry_run:
        print(f"    [DRY RUN] Would send to {to}")
        return True
    
    if DEMO_MODE:
        print(f"    [DEMO] 📱 → {to}: {message[:50]}...")
        return True
    
    try:
        response = requests.post(
            f"{GATEWAY_URL}/api/send-sms",
            json={"to": to, "from": from_number, "message": message},
            timeout=10
        )
        response.raise_for_status()
        return True
    except Exception as e:
        print(f"    ✗ Failed to send to {to}: {e}")
        return False


# ============== Campaign 1: No-Show Rescue ==============

def run_no_show_rescue(business_id: str, dry_run: bool = False) -> dict:
    """
    Contact customers who missed their appointments.
    Checks appointments from last 24 hours that weren't completed/cancelled.
    """
    business = get_business_by_id(business_id)
    if not business:
        return {"error": "Business not found"}
    
    print(f"\n  🚨 NO-SHOW RESCUE for {business.business_name}")
    
    # Start campaign run log
    run = create_campaign_run(business_id, "no_show_rescue") if not dry_run else None
    
    # Get potential no-shows (past appointments still pending/confirmed)
    no_shows = get_no_show_appointments(business_id, hours_ago=24)
    
    stats = {
        "targeted": len(no_shows),
        "sent": 0,
        "failed": 0,
        "skipped_opted_out": 0,
        "skipped_already_booked": 0,
        "skipped_already_contacted": 0,
    }
    
    if not no_shows:
        print("    No no-shows detected ✓")
        if run:
            complete_campaign_run(run.id, **stats)
        return stats
    
    print(f"    Found {len(no_shows)} potential no-shows")
    
    for appt in no_shows:
        # Get/create customer record
        customer = get_customer_by_phone(business_id, appt.customer_phone)
        if not customer:
            customer = get_or_create_customer(business_id, appt.customer_phone, appt.customer_name)
        
        # STOP CONDITIONS
        # 1. Opted out
        if customer.opted_out:
            print(f"    → {appt.customer_name or appt.customer_phone}: SKIP (opted out)")
            stats["skipped_opted_out"] += 1
            continue
        
        # 2. Already has upcoming appointment (already rebooked)
        if has_upcoming_appointment(business_id, appt.customer_phone):
            print(f"    → {appt.customer_name or appt.customer_phone}: SKIP (already booked)")
            stats["skipped_already_booked"] += 1
            continue
        
        # 3. Already contacted recently for no-show
        if was_customer_contacted_recently(business_id, appt.customer_phone, "no_show_rescue", days=3):
            print(f"    → {appt.customer_name or appt.customer_phone}: SKIP (already contacted)")
            stats["skipped_already_contacted"] += 1
            continue
        
        # Send the message
        message = format_message("no_show_rescue", customer.name or appt.customer_name, business.business_name)
        
        success = send_sms(
            to=appt.customer_phone,
            from_number=business.customer_number,
            message=message,
            dry_run=dry_run
        )
        
        if success:
            print(f"    → {appt.customer_name or appt.customer_phone}: SENT ✓")
            stats["sent"] += 1
            
            if not dry_run:
                # Mark appointment as no-show
                mark_appointment_no_show(appt.id)
                
                # Log the message
                log_campaign_message(
                    campaign_run_id=run.id,
                    business_id=business_id,
                    customer_phone=appt.customer_phone,
                    campaign_type="no_show_rescue",
                    message_sent=message,
                    customer_name=customer.name or appt.customer_name,
                    trigger_reason=f"no_show:appt:{appt.id}"
                )
        else:
            stats["failed"] += 1
        
        time.sleep(DELAY_BETWEEN_MESSAGES)
    
    if run:
        complete_campaign_run(run.id, **stats)
    
    return stats


# ============== Campaign 2: Win-Back (30/60 day) ==============

def run_win_back(business_id: str, dry_run: bool = False) -> dict:
    """
    Re-engage customers who haven't visited in 30+ or 60+ days.
    30-day: friendly check-in
    60-day: more urgent, we miss you
    """
    business = get_business_by_id(business_id)
    if not business:
        return {"error": "Business not found"}
    
    print(f"\n  🔄 WIN-BACK CAMPAIGN for {business.business_name}")
    
    # Run 30-day and 60-day separately
    stats_30 = _run_win_back_tier(business, 30, 45, "win_back_30", dry_run)
    stats_60 = _run_win_back_tier(business, 60, 90, "win_back_60", dry_run)
    
    return {
        "30_day": stats_30,
        "60_day": stats_60,
        "total_sent": stats_30["sent"] + stats_60["sent"]
    }


def _run_win_back_tier(business, min_days: int, max_days: int, campaign_type: str, dry_run: bool) -> dict:
    """Run a specific win-back tier (30 or 60 day)."""
    print(f"\n    [{min_days}-{max_days} days lapsed]")
    
    run = create_campaign_run(business.id, campaign_type) if not dry_run else None
    
    # Get lapsed customers in this window
    lapsed = get_lapsed_customers(business.id, min_days, max_days)
    
    stats = {
        "targeted": len(lapsed),
        "sent": 0,
        "failed": 0,
        "skipped_opted_out": 0,
        "skipped_already_booked": 0,
        "skipped_already_contacted": 0,
    }
    
    if not lapsed:
        print(f"      No lapsed customers in {min_days}-{max_days} day window")
        if run:
            complete_campaign_run(run.id, **stats)
        return stats
    
    print(f"      Found {len(lapsed)} lapsed customers")
    
    for customer in lapsed:
        # STOP CONDITIONS
        # 1. Opted out
        if customer.opted_out:
            stats["skipped_opted_out"] += 1
            continue
        
        # 2. Already has upcoming appointment
        if has_upcoming_appointment(business.id, customer.phone):
            print(f"      → {customer.name or customer.phone}: SKIP (already booked)")
            stats["skipped_already_booked"] += 1
            continue
        
        # 3. Already contacted for win-back recently
        if was_customer_contacted_recently(business.id, customer.phone, campaign_type, days=14):
            stats["skipped_already_contacted"] += 1
            continue
        
        # Send message
        message = format_message(campaign_type, customer.name, business.business_name)
        
        success = send_sms(
            to=customer.phone,
            from_number=business.customer_number,
            message=message,
            dry_run=dry_run
        )
        
        if success:
            print(f"      → {customer.name or customer.phone}: SENT ✓")
            stats["sent"] += 1
            
            if not dry_run:
                log_campaign_message(
                    campaign_run_id=run.id,
                    business_id=business.id,
                    customer_phone=customer.phone,
                    campaign_type=campaign_type,
                    message_sent=message,
                    customer_name=customer.name,
                    trigger_reason=f"lapsed:{min_days}d"
                )
        else:
            stats["failed"] += 1
        
        time.sleep(DELAY_BETWEEN_MESSAGES)
    
    if run:
        complete_campaign_run(run.id, **stats)
    
    return stats


# ============== Campaign 3: Post-Visit Rebook ==============

def run_post_visit_rebook(business_id: str, dry_run: bool = False) -> dict:
    """
    Nudge customers to rebook after a completed visit.
    Runs ~2-4 hours after appointment completion.
    """
    business = get_business_by_id(business_id)
    if not business:
        return {"error": "Business not found"}
    
    print(f"\n  📅 POST-VISIT REBOOK for {business.business_name}")
    
    run = create_campaign_run(business.id, "post_visit_rebook") if not dry_run else None
    
    # Get completed appointments from last 6 hours
    # (running 3x daily means we'll catch most within 2-4 hours)
    completed = get_completed_appointments_since(business_id, hours_ago=6)
    
    stats = {
        "targeted": len(completed),
        "sent": 0,
        "failed": 0,
        "skipped_opted_out": 0,
        "skipped_already_booked": 0,
        "skipped_already_contacted": 0,
    }
    
    if not completed:
        print("    No recent completed appointments")
        if run:
            complete_campaign_run(run.id, **stats)
        return stats
    
    print(f"    Found {len(completed)} recently completed appointments")
    
    for appt in completed:
        customer = get_customer_by_phone(business_id, appt.customer_phone)
        if not customer:
            customer = get_or_create_customer(business_id, appt.customer_phone, appt.customer_name)
        
        # STOP CONDITIONS
        # 1. Opted out
        if customer.opted_out:
            stats["skipped_opted_out"] += 1
            continue
        
        # 2. Already has upcoming appointment (they rebooked in-person!)
        if has_upcoming_appointment(business_id, appt.customer_phone):
            print(f"    → {appt.customer_name or appt.customer_phone}: SKIP (already rebooked)")
            stats["skipped_already_booked"] += 1
            continue
        
        # 3. Already sent post-visit message today
        if was_customer_contacted_recently(business_id, appt.customer_phone, "post_visit_rebook", days=1):
            stats["skipped_already_contacted"] += 1
            continue
        
        # Send message
        message = format_message("post_visit_rebook", customer.name or appt.customer_name, business.business_name)
        
        success = send_sms(
            to=appt.customer_phone,
            from_number=business.customer_number,
            message=message,
            dry_run=dry_run
        )
        
        if success:
            print(f"    → {appt.customer_name or appt.customer_phone}: SENT ✓")
            stats["sent"] += 1
            
            if not dry_run:
                log_campaign_message(
                    campaign_run_id=run.id,
                    business_id=business.id,
                    customer_phone=appt.customer_phone,
                    campaign_type="post_visit_rebook",
                    message_sent=message,
                    customer_name=customer.name or appt.customer_name,
                    trigger_reason=f"completed:appt:{appt.id}"
                )
        else:
            stats["failed"] += 1
        
        time.sleep(DELAY_BETWEEN_MESSAGES)
    
    if run:
        complete_campaign_run(run.id, **stats)
    
    return stats


# ============== Main Entry Point ==============

def run_all_campaigns(business_id: str, dry_run: bool = False, campaign: str = None) -> dict:
    """Run all retention campaigns for a business."""
    results = {}
    
    if campaign is None or campaign == "no_show":
        results["no_show_rescue"] = run_no_show_rescue(business_id, dry_run)
    
    if campaign is None or campaign == "win_back":
        results["win_back"] = run_win_back(business_id, dry_run)
    
    if campaign is None or campaign == "post_visit":
        results["post_visit_rebook"] = run_post_visit_rebook(business_id, dry_run)
    
    return results


def show_logs(business_id: str = None):
    """Show recent campaign run logs."""
    if business_id:
        businesses = [get_business_by_id(business_id)]
    else:
        businesses = get_all_businesses()
    
    for business in businesses:
        if not business:
            continue
        
        print(f"\n📊 Campaign Logs: {business.business_name}")
        print("=" * 60)
        
        runs = get_recent_campaign_runs(business.id, limit=10)
        
        if not runs:
            print("  No campaign runs yet")
            continue
        
        for run in runs:
            status_icon = "✓" if run.status == "completed" else "⏳" if run.status == "running" else "✗"
            print(f"\n  {status_icon} {run.campaign_type}")
            print(f"    Started: {run.started_at}")
            print(f"    Targeted: {run.customers_targeted} | Sent: {run.messages_sent} | Failed: {run.messages_failed}")
            
            skipped = run.skipped_opted_out + run.skipped_already_booked + run.skipped_already_contacted
            if skipped > 0:
                print(f"    Skipped: {skipped} (opted_out: {run.skipped_opted_out}, booked: {run.skipped_already_booked}, contacted: {run.skipped_already_contacted})")


def main():
    parser = argparse.ArgumentParser(
        description="Retention Engine v1 - 3 Campaign System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview what would be sent without actually sending")
    parser.add_argument("--business-id",
                        help="Run for specific business only")
    parser.add_argument("--campaign", choices=["no_show", "win_back", "post_visit"],
                        help="Run specific campaign only")
    parser.add_argument("--logs", action="store_true",
                        help="Show recent campaign run logs")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Verbose output")
    args = parser.parse_args()
    
    print(f"\n{'='*70}")
    print(f"🎯 RETENTION ENGINE v1 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*70}")
    
    if args.dry_run:
        print("📋 DRY RUN MODE - No messages will be sent")
    if DEMO_MODE:
        print("🎭 DEMO MODE - Messages logged but not sent")
    if args.campaign:
        print(f"🎯 Running: {args.campaign} only")
    
    init_db()
    
    # Show logs mode
    if args.logs:
        show_logs(args.business_id)
        return 0
    
    # Run campaigns
    all_results = []
    
    if args.business_id:
        business = get_business_by_id(args.business_id)
        if not business:
            print(f"❌ Business not found: {args.business_id}")
            return 1
        result = run_all_campaigns(args.business_id, dry_run=args.dry_run, campaign=args.campaign)
        all_results.append({"business": business.business_name, **result})
    else:
        businesses = get_all_businesses()
        print(f"\nFound {len(businesses)} businesses")
        
        for business in businesses:
            print(f"\n{'─'*50}")
            print(f"📍 {business.business_name}")
            result = run_all_campaigns(business.id, dry_run=args.dry_run, campaign=args.campaign)
            all_results.append({"business": business.business_name, **result})
    
    # Summary
    print(f"\n{'='*70}")
    print("📈 SUMMARY")
    print(f"{'='*70}")
    
    total_sent = 0
    for result in all_results:
        if "no_show_rescue" in result:
            total_sent += result["no_show_rescue"].get("sent", 0)
        if "win_back" in result:
            total_sent += result["win_back"].get("total_sent", 0)
        if "post_visit_rebook" in result:
            total_sent += result["post_visit_rebook"].get("sent", 0)
    
    print(f"  Businesses processed: {len(all_results)}")
    print(f"  Total messages sent: {total_sent}")
    
    if not args.dry_run and total_sent > 0:
        print(f"\n  💡 Run with --logs to see campaign history")
    
    print(f"{'='*70}\n")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
