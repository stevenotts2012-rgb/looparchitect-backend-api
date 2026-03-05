#!/usr/bin/env python3
"""Test arrangement generation with feature flag."""
import requests
import json
import time

# Create an arrangement with AI parsing enabled to trigger ProducerEngine
payload = {
    'loop_id': 1,
    'target_seconds': 60,
    'style_text_input': 'test arrangement with producer engine',
    'use_ai_parsing': True  # THIS TRIGGERS THE PRODUCER ENGINE PATH!
}

print('POST /api/v1/arrangements/generate')
print(f'Payload: {payload}')
r = requests.post('http://127.0.0.1:8000/api/v1/arrangements/generate', json=payload)
print(f'Status: {r.status_code}')
print(f'Response: {json.dumps(r.json(), indent=2)}')

# Wait a moment for processing
print('\nWaiting 3 seconds for arrangement processing...')
time.sleep(3)

# Get ID from response
if r.status_code in [200, 202]:
    arrangement_id = r.json().get('id') or r.json().get('arrangement_id')
    if arrangement_id:
        print(f'\nFetching arrangement {arrangement_id}...')
        r2 = requests.get(f'http://127.0.0.1:8000/api/v1/arrangements/{arrangement_id}')
        print(f'Status: {r2.status_code}')
        data = r2.json()
        print(f'Arrangement status: {data.get("status")}')
        print(f'Has producer_arrangement_json: {"producer_arrangement_json" in data}')
        if 'producer_arrangement_json' in data:
            paj = data['producer_arrangement_json']
            if paj:
                print(f'producer_arrangement_json length: {len(paj)}')
                print(f'producer_arrangement_json first 200 chars: {str(paj)[:200]}')
            else:
                print(f'producer_arrangement_json value: {paj}')
