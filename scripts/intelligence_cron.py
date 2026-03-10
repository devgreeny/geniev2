#!/usr/bin/env python3
"""
Daily Intelligence Cron Job - Proactive Customer Analysis

Run this script daily to:
- Identify at-risk customers before they churn
- Score and prioritize leads
- Generate proactive outreach recommendations
- Send alerts to business owners about important actions

Usage:
    # Run daily analysis
    python scripts/intelligence_cron.py

    # Dry run (analyze but don't send alerts)
    python scripts/intelligence_cron.py --dry-run

    # Run for specific business
    python scripts/intelligence_cron.py --business-id <id>

    # Include full churn analysis (slower, more thorough)
    python scripts/intelligence_cron.py --full-analysis

    # As a cron job (add to crontab):
    # Run daily at 8:00 AM
    # 0 8 * * * cd /path/to/genie && python scripts/intelligence_cron.py >> logs/intelligence.log 2>&1
"""

import os
import sys
import argparse
import asyncio
import requests
from datetime import datetime

# Add agents to path for shared modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '../.env'))

from shared.db import (
    init_db,
    get_all_businesses,
    get_business_by_id,
    get_customers_by_business,
    get_leads_by_phone,
    get_recent_messages,
)

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://localhost:8080")
INTELLIGENCE_URL = os.getenv("INTELLIGENCE_URL", "http://localhost:8005")
DEMO_MODE = os.getenv("DEMO_MODE", "false").lower() == "true"


def send_owner_alert(business, message: str, dry_run: bool = False) -> bool:
    """Send an alert to the business owner."""
    if dry_run:
        print(f"  [DRY RUN] Would alert owner: {message[:60]}...")
        return True
    
    if DEMO_MODE:
        print(f"  [DEMO] 📱 Alert to owner: {message[:60]}...")
        return True
    
    try:
        response = requests.post(
            f"{GATEWAY_URL}/api/send-sms",
            json={
                "to": business.owner_phone,
                "from": business.private_number,
                "message": message
            },
            timeout=10
        )
        response.raise_for_status()
        print(f"  ✓ Alert sent to owner")
        return True
    except Exception as e:
        print(f"  ✗ Failed to send alert: {e}")
        return False


def analyze_business(business_id: str, dry_run: bool = False, full_analysis: bool = False) -> dict:
    """Run intelligence analysis for a business."""
    business = get_business_by_id(business_id)
    if not business:
        return {"error": f"Business not found: {business_id}"}
    
    print(f"\n🧠 Analyzing: {business.business_name}")
    
    customers = get_customers_by_business(business_id)
    print(f"  Total customers: {len(customers)}")
    
    results = {
        "business": business.business_name,
        "total_customers": len(customers),
        "at_risk": [],
        "vip_attention": [],
        "new_customer_nurture": [],
        "hot_leads": [],
    }
    
    today = datetime.now()
    
    for customer in customers:
        # Skip customers without service history
        if not customer.last_service_date:
            continue
        
        try:
            last_date = datetime.strptime(customer.last_service_date, "%Y-%m-%d")
            days_since = (today - last_date).days
        except ValueError:
            continue
        
        # Identify at-risk customers
        if customer.avg_visit_interval:
            if days_since > customer.avg_visit_interval * 2:
                results["at_risk"].append({
                    "name": customer.name or customer.phone,
                    "phone": customer.phone,
                    "days_overdue": days_since - customer.avg_visit_interval,
                    "usual_interval": customer.avg_visit_interval,
                    "lifetime_value": customer.lifetime_value,
                })
        
        # VIP customers needing attention
        if customer.segment == "vip" and days_since > 45:
            results["vip_attention"].append({
                "name": customer.name or customer.phone,
                "phone": customer.phone,
                "days_since_visit": days_since,
                "lifetime_value": customer.lifetime_value,
            })
        
        # New customers to nurture
        if customer.total_visits == 1 and 14 <= days_since <= 45:
            results["new_customer_nurture"].append({
                "name": customer.name or customer.phone,
                "phone": customer.phone,
                "first_visit": customer.last_service_date,
                "service": customer.last_service_type,
            })
    
    # Sort by priority
    results["at_risk"].sort(key=lambda x: x["lifetime_value"], reverse=True)
    results["vip_attention"].sort(key=lambda x: x["lifetime_value"], reverse=True)
    
    # Print summary
    print(f"  🚨 At-risk customers: {len(results['at_risk'])}")
    print(f"  ⭐ VIPs needing attention: {len(results['vip_attention'])}")
    print(f"  🌱 New customers to nurture: {len(results['new_customer_nurture'])}")
    
    # Send daily summary to owner if there are actions needed
    total_actions = len(results["at_risk"]) + len(results["vip_attention"]) + len(results["new_customer_nurture"])
    
    if total_actions > 0:
        summary_parts = []
        if results["at_risk"]:
            summary_parts.append(f"{len(results['at_risk'])} at-risk")
        if results["vip_attention"]:
            summary_parts.append(f"{len(results['vip_attention'])} VIPs")
        if results["new_customer_nurture"]:
            summary_parts.append(f"{len(results['new_customer_nurture'])} new customers")
        
        alert_message = f"📊 Daily Genie Report: {', '.join(summary_parts)} need attention. Check your dashboard for details!"
        
        send_owner_alert(business, alert_message, dry_run=dry_run)
    
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Run daily intelligence analysis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Analyze without sending alerts")
    parser.add_argument("--business-id",
                        help="Process only a specific business")
    parser.add_argument("--full-analysis", action="store_true",
                        help="Run full AI-powered analysis (slower)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show detailed output")
    args = parser.parse_args()
    
    print(f"\n{'='*70}")
    print(f"🧠 Intelligence Cron Job - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*70}")
    
    if args.dry_run:
        print("📋 DRY RUN MODE - No alerts will be sent")
    if DEMO_MODE:
        print("🎭 DEMO MODE - Alerts logged but not sent")
    
    init_db()
    
    all_results = []
    
    if args.business_id:
        result = analyze_business(args.business_id, dry_run=args.dry_run, full_analysis=args.full_analysis)
        all_results.append(result)
    else:
        businesses = get_all_businesses()
        print(f"\nFound {len(businesses)} businesses to analyze")
        
        for business in businesses:
            result = analyze_business(business.id, dry_run=args.dry_run, full_analysis=args.full_analysis)
            all_results.append(result)
    
    # Summary
    total_at_risk = sum(len(r.get("at_risk", [])) for r in all_results if "error" not in r)
    total_vip = sum(len(r.get("vip_attention", [])) for r in all_results if "error" not in r)
    total_new = sum(len(r.get("new_customer_nurture", [])) for r in all_results if "error" not in r)
    
    print(f"\n{'='*70}")
    print(f"📈 SUMMARY")
    print(f"{'='*70}")
    print(f"  Businesses analyzed: {len(all_results)}")
    print(f"  Total at-risk customers: {total_at_risk}")
    print(f"  Total VIPs needing attention: {total_vip}")
    print(f"  Total new customers to nurture: {total_new}")
    print(f"{'='*70}\n")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
