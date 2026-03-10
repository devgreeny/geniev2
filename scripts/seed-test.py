#!/usr/bin/env python3
"""Seed a test barbershop business for development with customers and re-engagement rules."""

import os
import sys
from uuid import uuid4
from datetime import datetime, timedelta

# Add parent directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agents'))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

from shared.db import init_db, get_db

def main():
    init_db()
    
    business_id = str(uuid4())
    
    with get_db() as conn:
        # Clear existing test data
        conn.execute("DELETE FROM reengagement_log")
        conn.execute("DELETE FROM reengagement_rules")
        conn.execute("DELETE FROM customers")
        conn.execute("DELETE FROM appointments")
        conn.execute("DELETE FROM invoices") 
        conn.execute("DELETE FROM leads")
        conn.execute("DELETE FROM conversations")
        conn.execute("DELETE FROM businesses")
        
        # Insert test barbershop
        conn.execute("""
            INSERT INTO businesses (
                id, owner_name, business_name, services, pricing, location, hours,
                availability, custom_context, owner_phone, customer_phone, 
                private_number, customer_number
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            business_id,
            'Test Owner',
            'Fresh Cuts Barbershop',
            'Haircuts, fades, beard trims, hot towel shaves',
            'Haircut $25, Fade $30, Beard trim $15, Hot towel shave $20',
            'Downtown',
            'Tue-Sat 9am-7pm, Sun 10am-4pm, Closed Monday',
            'Walk-ins welcome, appointments preferred',
            'Ask for Mike for the best fades',
            '+15089693919',  # Owner's phone
            '+15089693919',  # Customer phone (same for testing)
            '+12818247889',  # Private number (Vonage)
            '+12818247889',  # Customer service number (Vonage)
        ))
        
        # Add re-engagement rules for the barbershop
        rules = [
            {
                "id": str(uuid4()),
                "name": "Haircut Follow-up",
                "service_type": "haircut",
                "days": 30,
                "template": "Hi {name}! It's been about a month since your last cut at Fresh Cuts. Ready for a fresh look? Reply to book! 💈",
                "priority": 10
            },
            {
                "id": str(uuid4()),
                "name": "Fade Follow-up", 
                "service_type": "fade",
                "days": 21,  # Fades need touch-ups more often
                "template": "Hey {name}! Your fade is probably due for a touch-up. It's been {days} days. Want us to get you looking sharp? 🔥",
                "priority": 15
            },
            {
                "id": str(uuid4()),
                "name": "General Follow-up",
                "service_type": None,  # Catch-all
                "days": 45,
                "template": "Hi {name}! We miss you at Fresh Cuts! It's been a while since your last visit. Ready to come back? Reply to book!",
                "priority": 0
            }
        ]
        
        for rule in rules:
            conn.execute("""
                INSERT INTO reengagement_rules (id, business_id, name, service_type, days_since_last_service, message_template, enabled, priority)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?)
            """, (rule["id"], business_id, rule["name"], rule["service_type"], rule["days"], rule["template"], rule["priority"]))
        
        # Add some test customers at different stages
        customers = [
            {
                "id": str(uuid4()),
                "phone": "+15551234567",
                "name": "John Smith",
                "last_service_date": (datetime.now() - timedelta(days=35)).strftime("%Y-%m-%d"),  # Due for haircut
                "last_service_type": "haircut",
                "total_visits": 5
            },
            {
                "id": str(uuid4()),
                "phone": "+15559876543",
                "name": "Mike Johnson",
                "last_service_date": (datetime.now() - timedelta(days=25)).strftime("%Y-%m-%d"),  # Due for fade
                "last_service_type": "fade",
                "total_visits": 12
            },
            {
                "id": str(uuid4()),
                "phone": "+15555555555",
                "name": "Dave Wilson",
                "last_service_date": (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d"),  # Recent, not due
                "last_service_type": "haircut",
                "total_visits": 3
            },
            {
                "id": str(uuid4()),
                "phone": "+15556667777",
                "name": "Chris Brown",
                "last_service_date": (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d"),  # Way overdue
                "last_service_type": "beard trim",
                "total_visits": 2
            },
            {
                "id": str(uuid4()),
                "phone": "+15558889999",
                "name": None,  # Name unknown
                "last_service_date": (datetime.now() - timedelta(days=40)).strftime("%Y-%m-%d"),
                "last_service_type": "haircut",
                "total_visits": 1
            }
        ]
        
        for cust in customers:
            conn.execute("""
                INSERT INTO customers (id, business_id, phone, name, last_service_date, last_service_type, total_visits, opted_out)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0)
            """, (cust["id"], business_id, cust["phone"], cust["name"], cust["last_service_date"], cust["last_service_type"], cust["total_visits"]))
        
        conn.commit()
    
    print("✅ Test business created: Fresh Cuts Barbershop")
    print(f"   ID: {business_id}")
    print("   Customer service number: +12818247889")
    print("   Owner phone: +15089693919")
    print()
    print("📋 Re-engagement Rules:")
    for rule in rules:
        svc = rule['service_type'] or 'all services'
        print(f"   • {rule['name']}: {rule['days']} days ({svc})")
    print()
    print("👥 Test Customers:")
    for cust in customers:
        name = cust['name'] or 'Unknown'
        days_ago = (datetime.now() - datetime.strptime(cust['last_service_date'], "%Y-%m-%d")).days
        status = "✓ Due" if days_ago >= 21 else "○ Recent"
        print(f"   {status} {name}: {cust['last_service_type']} {days_ago} days ago")
    print()
    print("📱 To test re-engagement:")
    print("   1. Start the gateway and agents")
    print("   2. Run: python scripts/reengagement_cron.py --dry-run")
    print("   3. Or call: POST /sms/reengagement/process {\"dry_run\": true}")
    print()
    print("💬 Text +12818247889 to test customer service!")

if __name__ == "__main__":
    main()
