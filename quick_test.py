#!/usr/bin/env python3
"""Simple test to create one arrangement and check result."""
import requests
import time
from sqlalchemy import create_engine, text

# Create arrangement
print("Creating arrangement...")
r = requests.post(
    'http://127.0.0.1:8000/api/v1/arrangements/generate',
    json={
        'loop_id': 1,
        'target_seconds': 60,
        'style_text_input': 'test with producer engine',
        'use_ai_parsing': True
    }
)

arr_id = r.json().get('arrangement_id')
print(f"Status: {r.status_code}, ID: {arr_id}")

# Wait
print("Waiting 8 seconds for processing...")
time.sleep(8)

# Check database
engine = create_engine('sqlite:///test.db')
with engine.connect() as conn:
    row = conn.execute(
        text(f"SELECT id, status, producer_arrangement_json IS NOT NULL FROM arrangements WHERE id = {arr_id}")
    ).fetchone()
    
    if row:
        print(f"ID: {row[0]}, Status: {row[1]}, HasProducer: {row[2]}")
        if row[2]:
            print("✅ SUCCESS - producer_arrangement_json is populated!")
        else:
            print("❌ FAIL - producer_arrangement_json is NULL")
    else:
        print(f"❌ FAIL - Arrangement {arr_id} not found in DB")
