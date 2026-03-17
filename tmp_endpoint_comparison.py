#!/usr/bin/env python3
"""
Test individual vs list arrangement endpoints.
"""
import requests
import time

base_url = "https://web-production-3afc5.up.railway.app/api/v1"

# Get one arrangement ID from the list
print("Fetching first queued arrangement ID...")
list_resp = requests.get(f"{base_url}/arrangements?include_unsaved=true", timeout=30)
if list_resp.status_code == 200:
    arrangements = list_resp.json()
    queued_arrs = [a for a in arrangements if isinstance(a, dict) and a.get('status') == 'queued']
    if queued_arrs:
        arr_id = queued_arrs[0]['id']
        print(f"\nTest arrangement ID: {arr_id}")
        print(f"Status from list endpoint: {queued_arrs[0].get('status')}")
        
        # Now fetch the same arrangement individually
        print(f"\nFetching individual arrangement {arr_id}...")
        time.sleep(1)
        ind_resp = requests.get(f"{base_url}/arrangements/{arr_id}", timeout=30)
        if ind_resp.status_code == 200:
            ind_data = ind_resp.json()
            print(f"Status from GET endpoint: {ind_data.get('status')}")
            print(f"\nComparison:")
            print(f"  List status: {queued_arrs[0].get('status')}")
            print(f"  GET status:  {ind_data.get('status')}")
            if queued_arrs[0].get('status') != ind_data.get('status'):
                print(f"❌ STATUS MISMATCH - GET endpoint synced the status!")
            else:
                print(f"✅ Status consistent")
        else:
            print(f"Failed to fetch individual: {ind_resp.status_code}")
    else:
        print("No queued arrangements found")
else:
    print(f"Failed to fetch list: {list_resp.status_code}")
