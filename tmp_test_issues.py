import requests
import json

print("Testing API endpoints...")

# Test styles endpoint
try:
    url = "https://web-production-3afc5.up.railway.app/api/v1/styles"
    print(f"\n1. Testing {url}")
    r = requests.get(url, timeout=30)
    print(f"   Status: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        if isinstance(data, dict) and 'styles' in data:
            print(f"   Got {len(data['styles'])} styles")
            print(f"   First: {data['styles'][0].get('id') if data['styles'] else 'N/A'}")
        elif isinstance(data, list):
            print(f"   Got {len(data)} items")
            if data:
                print(f"   First item keys: {list(data[0].keys())}")
        else:
            print(f"   Response: {str(data)[:200]}")
    else:
        print(f"   Error: {r.text[:200]}")
except Exception as e:
    print(f"   Exception: {e}")
    import traceback
    traceback.print_exc()

# Test arrangement queue
try:
    url = "https://web-production-3afc5.up.railway.app/api/v1/arrangements?limit=5"
    print(f"\n2. Testing queue status at {url}")
    r = requests.get(url, timeout=30)
    print(f"   Status: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        if isinstance(data, list):
            print(f"   Got {len(data)} arrangements")
            queued = [a for a in data if a.get('status') == 'queued']
            processing = [a for a in data if a.get('status') == 'processing']
            done = [a for a in data if a.get('status') == 'done']
            print(f"   - Queued: {len(queued)}")
            print(f"   - Processing: {len(processing)}")
            print(f"   - Done: {len(done)}")
            if queued:
                first_q = queued[0]
                print(f"   First queued: ID {first_q.get('id')}, created {first_q.get('created_at')}")
        else:
            print(f"   Response type: {type(data)}")
    else:
        print(f"   Error: {r.text[:200]}")  
except Exception as e:
    print(f"   Exception: {e}")
    import traceback
    traceback.print_exc()
