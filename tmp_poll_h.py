import urllib.request, urllib.error, time, datetime
url = "https://web-production-3afc5.up.railway.app/health"
print("Waiting for Railway to come back up (max 5 min)...")
for i in range(1, 21):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    try:
        r = urllib.request.urlopen(url, timeout=12)
        print(f"[{ts}] {i}: HTTP {r.status} UP"); break
    except urllib.error.HTTPError as e: print(f"[{ts}] {i}: HTTP {e.code}")
    except Exception as ex: print(f"[{ts}] {i}: {str(ex)[:70]}")
    time.sleep(15)
