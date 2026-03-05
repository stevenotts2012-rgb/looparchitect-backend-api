#!/usr/bin/env python3
"""Check database for producer arrangements."""
import time
from sqlalchemy import create_engine, text

print("Waiting 5 seconds for arrangement processing...")
time.sleep(5)

engine = create_engine('sqlite:///test.db')
with engine.connect() as conn:
    result = conn.execute(text('SELECT id, status, producer_arrangement_json IS NOT NULL as has_producer FROM arrangements WHERE id >= 130 ORDER BY id DESC'))
    print("\nRecent arrangements:")
    for row in result:
        print(f'  ID: {row[0]}, Status: {row[1]}, HasProducer: {row[2]}')
    
    # Also check one with content
    result2 = conn.execute(text('SELECT id, substr(producer_arrangement_json, 1, 150) FROM arrangements WHERE producer_arrangement_json IS NOT NULL ORDER BY id DESC LIMIT 1'))
    rows = result2.fetchall()
    if rows:
        print(f"\nFirst producer arrangement (ID {rows[0][0]}):")
        print(f"  Content preview: {rows[0][1]}...")
    else:
        print("\nNo arrangements with producer_arrangement_json found!")
