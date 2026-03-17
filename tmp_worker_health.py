import requests
import json

print("Testing worker health endpoint...")

try:
    # Try the backend directly
    url = "https://web-production-3afc5.up.railway.app/api/v1/health/worker"
    print(f"Testing {url}")
    r = requests.get(url, timeout=30)
    print(f"Status: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print(json.dumps(data, indent=2))
    else:
        print(f"Error: {r.text[:300]}")
except Exception as e:
    print(f"Exception: {e}")

# Also try root health
try:
    url = "https://web-production-3afc5.up.railway.app/health/worker"
    print(f"\nTrying {url}")
    r = requests.get(url, timeout=30)
    print(f"Status: {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        print(json.dumps(data, indent=2))
    else:
        print(f"Not found at root")
except Exception as e:
    print(f"Exception: {e}")
