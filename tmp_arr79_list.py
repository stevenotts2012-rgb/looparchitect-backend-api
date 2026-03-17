#!/usr/bin/env python3
import requests

# Check if arrangement 79 is now showing as processing in the list
list_resp = requests.get("https://web-production-3afc5.up.railway.app/api/v1/arrangements?include_unsaved=true", timeout=30)
if list_resp.status_code == 200:
    arrangements = list_resp.json()
    for arr in arrangements:
        if arr.get('id') == 79:
            print(f"Arrangement 79 in list endpoint:")
            print(f"  Status: {arr.get('status')}")
            print(f"  Progress: {arr.get('progress')}")
            print(f"  Message: {arr.get('progress_message')}")
            break
    else:
        print("Arrangement 79 not found in list")
else:
    print(f"Failed: {list_resp.status_code}")
