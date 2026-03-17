#!/usr/bin/env python3
import requests

arr_id = 79
url = f"https://web-production-3afc5.up.railway.app/api/v1/arrangements/{arr_id}"
print(f"Testing: {url}")
resp = requests.get(url, timeout=30)
print(f"Status: {resp.status_code}")
print(f"Response: {resp.text[:500]}")
