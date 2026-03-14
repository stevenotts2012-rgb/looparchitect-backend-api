import urllib.request, urllib.error, time, datetime
url = "https://web-production-3afc5.up.railway.app/health"
print("Waiting for Railway build to complete (max 15 min)...")
for i in range(1, 61):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    try:
        r = urllib.request.urlopen(url, timeout=15)
        print(f"[{ts}] {i}: HTTP {r.status} UP - Railway is live"); break
    except urllib.error.HTTPError as e:
        print(f"[{ts}] {i}: HTTP {e.code} - server up, responding with error")
        break
    except Exception as ex:
        msg = str(ex)[:60]
        if i % 4 == 0:
            print(f"[{ts}] {i}: not yet ({msg}), still waiting...")
    time.sleep(15)
