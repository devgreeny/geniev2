#!/usr/bin/env python3
"""
Re-engagement Cron Job - Intelligent Customer Outreach

Run this script periodically (e.g., daily at 10am) to send re-engagement messages
to customers who are due based on your configured rules.

Features:
- Rate limiting to avoid spam
- Smart send windows (respects business hours)
- Campaign sequence support (multi-step win-back)
- Discount code formatting
- Detailed logging and statistics

Usage:
    # One-time run
    python scripts/reengagement_cron.py

    # Dry run (see what would be sent without actually sending)
    python scripts/reengagement_cron.py --dry-run

    # Run for a specific business only
    python scripts/reengagement_cron.py --business-id <id>

    # Limit messages per business (rate limiting)
    python scripts/reengagement_cron.py --max-per-business 50

    # Process only specific rule types
    python scripts/reengagement_cron.py --rule-type winback
    python scripts/reengagement_cron.py --rule-type standard

    # Verbose output for debugging
    python scripts/reengagement_cron.py --verbose

    # As a cron job (add to crontab):
    # Run daily at 10:00 AM
    # 0 10 * * * cd /path/to/genie && python scripts/reengagement_cron.py >> logs/reengagement.log 2>&1

    # Or run multiple times for different rule types:
    # 0 10 * * * cd /path/to/genie && python scripts/reengagement_cron.py --rule-type standard >> logs/reengagement.log 2>&1
    # 0 14 * * * cd /path/to/genie && python scripts/reengagement_cron.py --rule-type winback >> logs/reengagement.log 2>&1
"""

import os
import sys
import argparse
import requests
import time
import random
from datetime import datetime

# Add agents to path for shared modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '../.env'))

from shared.db import (
    init_db,
    get_all_businesses,
    get_business_by_id,
    get_customers_due_for_reengagement,
    log_reengagement_sent,
    create_campaign,
    get_active_campaign,
    update_campaign,
    get_reengagement_stats,
)

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://localhost:8080")
DEMO_MODE = os.getenv("DEMO_MODE", "false").lower() == "true"

# Rate limiting settings
DEFAULT_MAX_PER_BUSINESS = 100  # Max messages per business per run
DEFAULT_DELAY_BETWEEN_MESSAGES = 1.0  # Seconds between messages (prevents carrier throttling)
RANDOMIZE_DELAY = True  # Add slight randomization to seem more natural


def format_message(template: str, customer, business, days_since: int, discount: str = None) -> str:
    """Format a re-engagement message template with customer data."""
    name = customer.name if customer.name else "there"
    service = customer.last_service_type or "service"
    business_name = business.business_name if business else "our business"
    year = datetime.now().year
    
    # Handle discount placeholder
    discount_text = discount if discount else ""
    
    try:
        return template.format(
            name=name,
            service=service,
            business_name=business_name,
            days=days_since,
            discount=discount_text,
            year=year
        )
    except KeyError as e:
        # If template has unrecognized placeholder, return template with what we can fill
        print(f"  ⚠️ Warning: Unknown placeholder in template: {e}")
        return template.replace("{name}", name).replace("{business_name}", business_name).replace("{days}", str(days_since))


def send_sms(to: str, from_number: str, message: str, dry_run: bool = False, verbose: bool = False) -> bool:
    """Send an SMS via the gateway."""
    if dry_run:
        print(f"  [DRY RUN] Would send to {to}: {message[:60]}...")
        return True
    
    if DEMO_MODE:
        print(f"  [DEMO] 📱 → {to}: {message[:60]}...")
        return True
    
    try:
        response = requests.post(
            f"{GATEWAY_URL}/api/send-sms",
            json={
                "to": to,
                "from": from_number,
                "message": message
            },
            timeout=10
        )
        response.raise_for_status()
        if verbose:
            print(f"  ✓ Sent to {to}: {message[:40]}...")
        else:
            print(f"  ✓ Sent to {to}")
        return True
    except requests.exceptions.Timeout:
        print(f"  ✗ Timeout sending to {to}")
        return False
    except requests.exceptions.ConnectionError:
        print(f"  ✗ Connection error sending to {to} - is gateway running?")
        return False
    except Exception as e:
        print(f"  ✗ Failed to send to {to}: {e}")
        return False


def process_business(
    business_id: str, 
    dry_run: bool = False, 
    max_messages: int = DEFAULT_MAX_PER_BUSINESS,
    rule_type: str = None,
    verbose: bool = False
) -> dict:
    """Process re-engagements for a single business with rate limiting."""
    business = get_business_by_id(business_id)
    if not business:
        return {"error": f"Business not found: {business_id}"}
    
    print(f"\n📊 Processing: {business.business_name}")
    
    current_hour = datetime.now().hour
    due_customers = get_customers_due_for_reengagement(business_id, current_hour=current_hour)
    
    # Filter by rule type if specified
    if rule_type:
        due_customers = [d for d in due_customers if d["rule"].rule_type == rule_type]
    
    if not due_customers:
        print(f"  No customers due for re-engagement" + (f" (type: {rule_type})" if rule_type else ""))
        return {"business": business.business_name, "sent": 0, "failed": 0, "skipped": 0}
    
    print(f"  Found {len(due_customers)} customers due for re-engagement")
    if len(due_customers) > max_messages:
        print(f"  ⚠️ Rate limit: Processing only {max_messages} of {len(due_customers)} customers")
        due_customers = due_customers[:max_messages]
    
    sent = 0
    failed = 0
    skipped = 0
    
    for idx, item in enumerate(due_customers):
        customer = item["customer"]
        rule = item["rule"]
        days_since = item["days_since_service"]
        existing_campaign = item.get("campaign")
        
        # Format the message with discount if applicable
        message = format_message(
            rule.message_template,
            customer,
            business,
            days_since,
            discount=rule.discount_offer
        )
        
        if verbose:
            print(f"\n  [{idx+1}/{len(due_customers)}] Customer: {customer.name or customer.phone}")
            print(f"      Last service: {customer.last_service_type} ({days_since} days ago)")
            print(f"      Segment: {customer.segment}")
            print(f"      Rule: {rule.name} (type: {rule.rule_type}, seq: {rule.sequence_order})")
            if rule.discount_offer:
                print(f"      Discount: {rule.discount_offer}")
        else:
            print(f"  → {customer.name or customer.phone}: {rule.name}")
        
        # Send the SMS
        success = send_sms(
            to=customer.phone,
            from_number=business.customer_number,
            message=message,
            dry_run=dry_run,
            verbose=verbose
        )
        
        if success:
            if not dry_run:
                # Handle campaign tracking for sequences
                campaign_id = None
                sequence_position = rule.sequence_order
                
                if rule.rule_type in ['winback', 'followup']:
                    if existing_campaign:
                        campaign_id = existing_campaign.id
                    elif rule.sequence_order == 1:
                        # Start new campaign
                        campaign = create_campaign(
                            business_id=business_id,
                            customer_id=customer.id,
                            campaign_type=rule.rule_type
                        )
                        campaign_id = campaign.id
                        if verbose:
                            print(f"      Started new {rule.rule_type} campaign")
                
                # Log the message
                log_reengagement_sent(
                    business_id=business_id,
                    customer_id=customer.id,
                    rule_id=rule.id,
                    message_sent=message,
                    campaign_id=campaign_id,
                    sequence_position=sequence_position
                )
            sent += 1
        else:
            failed += 1
        
        # Rate limiting delay between messages
        if idx < len(due_customers) - 1:  # Don't delay after last message
            delay = DEFAULT_DELAY_BETWEEN_MESSAGES
            if RANDOMIZE_DELAY:
                delay += random.uniform(0, 0.5)  # Add 0-0.5s randomization
            if not dry_run:
                time.sleep(delay)
    
    return {
        "business": business.business_name,
        "sent": sent,
        "failed": failed,
        "skipped": skipped,
        "total_due": len(due_customers)
    }


def print_stats(business_id: str):
    """Print re-engagement statistics for a business."""
    stats = get_reengagement_stats(business_id)
    business = get_business_by_id(business_id)
    
    print(f"\n📈 Stats for {business.business_name if business else business_id}:")
    print(f"   Total messages sent: {stats['total_sent']}")
    print(f"   Responses received: {stats['responses']} ({stats['response_rate']:.1f}%)")
    print(f"   Bookings generated: {stats['bookings']} ({stats['booking_rate']:.1f}%)")
    
    if stats.get('by_rule_type'):
        print(f"\n   By Rule Type:")
        for rule_type, data in stats['by_rule_type'].items():
            response_rate = (data['responses'] / data['sent'] * 100) if data['sent'] > 0 else 0
            print(f"      {rule_type}: {data['sent']} sent, {data['responses']} responses ({response_rate:.1f}%)")
    
    if stats.get('by_customer_segment'):
        print(f"\n   By Customer Segment:")
        for segment, data in stats['by_customer_segment'].items():
            response_rate = (data['responses'] / data['sent'] * 100) if data['sent'] > 0 else 0
            print(f"      {segment}: {data['sent']} sent, {data['responses']} responses ({response_rate:.1f}%)")


def main():
    parser = argparse.ArgumentParser(
        description="Send re-engagement messages to due customers",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python reengagement_cron.py --dry-run              # Preview what would be sent
  python reengagement_cron.py --max-per-business 20  # Limit to 20 messages per business
  python reengagement_cron.py --rule-type winback    # Only process win-back campaigns
  python reengagement_cron.py --stats                # Show statistics only
        """
    )
    parser.add_argument("--dry-run", action="store_true", 
                        help="Show what would be sent without actually sending")
    parser.add_argument("--business-id", 
                        help="Process only a specific business")
    parser.add_argument("--max-per-business", type=int, default=DEFAULT_MAX_PER_BUSINESS,
                        help=f"Maximum messages per business (default: {DEFAULT_MAX_PER_BUSINESS})")
    parser.add_argument("--rule-type", choices=['standard', 'winback', 'followup', 'seasonal'],
                        help="Only process rules of this type")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show detailed output for each message")
    parser.add_argument("--stats", action="store_true",
                        help="Show statistics only, don't send messages")
    args = parser.parse_args()
    
    print(f"\n{'='*70}")
    print(f"🔄 Re-engagement Cron Job - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*70}")
    
    if args.dry_run:
        print("📋 DRY RUN MODE - No messages will be sent")
    if DEMO_MODE:
        print("🎭 DEMO MODE - Messages logged but not sent")
    if args.rule_type:
        print(f"🎯 Rule type filter: {args.rule_type}")
    if args.max_per_business != DEFAULT_MAX_PER_BUSINESS:
        print(f"⏱️ Rate limit: {args.max_per_business} messages per business")
    
    init_db()
    
    # Stats-only mode
    if args.stats:
        if args.business_id:
            print_stats(args.business_id)
        else:
            businesses = get_all_businesses()
            for business in businesses:
                print_stats(business.id)
        return 0
    
    results = []
    
    if args.business_id:
        # Process single business
        result = process_business(
            args.business_id, 
            dry_run=args.dry_run,
            max_messages=args.max_per_business,
            rule_type=args.rule_type,
            verbose=args.verbose
        )
        results.append(result)
    else:
        # Process all businesses
        businesses = get_all_businesses()
        print(f"\nFound {len(businesses)} businesses to process")
        
        for business in businesses:
            result = process_business(
                business.id, 
                dry_run=args.dry_run,
                max_messages=args.max_per_business,
                rule_type=args.rule_type,
                verbose=args.verbose
            )
            results.append(result)
    
    # Summary
    total_sent = sum(r.get("sent", 0) for r in results if "error" not in r)
    total_failed = sum(r.get("failed", 0) for r in results if "error" not in r)
    total_due = sum(r.get("total_due", 0) for r in results if "error" not in r)
    errors = [r for r in results if "error" in r]
    
    print(f"\n{'='*70}")
    print(f"📈 SUMMARY")
    print(f"{'='*70}")
    print(f"  Businesses processed: {len(results) - len(errors)}")
    if errors:
        print(f"  Businesses with errors: {len(errors)}")
    print(f"  Customers due: {total_due}")
    print(f"  Messages sent: {total_sent}")
    if total_failed > 0:
        print(f"  Failed: {total_failed}")
    
    if total_sent > 0 and not args.dry_run:
        print(f"\n  💡 Tip: Run with --stats to see response rates and conversions")
    
    print(f"{'='*70}\n")
    
    return 0 if total_failed == 0 and len(errors) == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
