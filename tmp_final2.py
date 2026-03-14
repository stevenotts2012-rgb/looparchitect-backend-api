import urllib.request, urllib.error, time, datetime, json, struct, math

BACKEND = "https://web-production-3afc5.up.railway.app"
upload_url = f"{BACKEND}/api/v1/loops/with-file"
sr = 22050

def sine_wav(freq, dur_ms):
    n = sr * dur_ms // 1000
    pcm = b"".join(struct.pack("<h", int(32000*math.sin(2*math.pi*freq*i/sr))) for i in range(n))
    hdr = struct.pack("<4sI4s4sIHHIIHH4sI", b"RIFF",36+len(pcm),b"WAVE",b"fmt ",16,1,1,sr,sr*2,2,16,b"data",len(pcm))
    return hdr + pcm

def silent_start_wav(silence_ms, freq, dur_ms):
    n = sr * dur_ms // 1000; s = sr * silence_ms // 1000
    pcm = b"".join(struct.pack("<h", 0 if i < s else int(32000*math.sin(2*math.pi*freq*i/sr))) for i in range(n))
    hdr = struct.pack("<4sI4s4sIHHIIHH4sI", b"RIFF",36+len(pcm),b"WAVE",b"fmt ",16,1,1,sr,sr*2,2,16,b"data",len(pcm))
    return hdr + pcm

def post(url, meta, files):
    b = "----Bnd6666"
    parts = [f'--{b}\r\nContent-Disposition: form-data; name="loop_in"\r\n\r\n{json.dumps(meta)}\r\n'.encode()]
    for name, fname, data in files:
        parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{name}"; filename="{fname}"\r\nContent-Type: audio/wav\r\n\r\n'.encode() + data + b"\r\n")
    parts.append(f"--{b}--\r\n".encode())
    body = b"".join(parts)
    req = urllib.request.Request(url, data=body, headers={"Content-Type": f"multipart/form-data; boundary={b}", "accept": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=90) as r: return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e: return e.code, json.loads(e.read() or b"{}")
    except Exception as ex: return None, {"error": str(ex)[:100]}

wav = sine_wav(440, 8000)
print("Polling for new Railway build...")
ready = False
for i in range(1, 20):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    s, r = post(upload_url, {"name":"probe","genre":"house"}, [("file","p.wav",wav)])
    detail = r.get("detail","") if isinstance(r,dict) else ""
    if s in (200,201):
        print(f"[{ts}] {i}: HTTP {s} — NEW build live, DB columns present"); ready = True; break
    elif "UndefinedColumn" in str(detail):
        print(f"[{ts}] {i}: OLD build (UndefinedColumn), waiting 20s...")
    elif s is None:
        print(f"[{ts}] {i}: Deploy in progress, waiting 20s...")
    else:
        print(f"[{ts}] {i}: HTTP {s} {str(detail)[:120]}")
        if s != 500: ready = True; break
    time.sleep(20)

if not ready:
    print("Column still missing — check Railway dashboard"); import sys; sys.exit(1)

print()
print("=== Test 1: Single loop upload (baseline) ===")
s1, r1 = post(upload_url, {"name":"Smoke-Test-Loop","genre":"house"}, [("file","loop.wav",sine_wav(440,8000))])
d1 = r1 if isinstance(r1, dict) else {}
print(f"  HTTP {s1}  id={d1.get('id')}  is_stem_pack={d1.get('is_stem_pack')}")
if s1 not in (200,201): print(f"  Error: {json.dumps(r1)[:300]}")

print()
print("=== Test 2: Stem upload with start-offset mismatch ===")
kick = sine_wav(80, 8000)
bass = silent_start_wav(600, 55, 8000)
s2, r2 = post(upload_url, {"name":"Stem-Offset-Test","genre":"house"}, [("stem_files","kick.wav",kick),("stem_files","bass.wav",bass)])
d2 = r2 if isinstance(r2, dict) else {}
meta = d2.get("stem_metadata") or {}
warn = meta.get("warnings") or []
align_warn = (meta.get("alignment") or {}).get("warnings") or []
all_w = warn + align_warn
print(f"  HTTP {s2}  id={d2.get('id')}  is_stem_pack={d2.get('is_stem_pack')}")
print(f"  warnings: {warn}")
print(f"  alignment.warnings: {align_warn}")
print(f"  fallback_to_loop: {meta.get('fallback_to_loop')}")
if s2 in (200,201):
    if any("misalign" in w.lower() or "offset" in w.lower() or "aligned" in w.lower() for w in all_w):
        print("  *** PASS: upload succeeded WITH misalignment warning ***")
    else:
        print("  OK: upload succeeded (alignment clean or warning wording varies)")
else:
    detail2 = d2.get("detail","") if d2 else str(r2)
    if "misalign" in str(detail2).lower():
        print(f"  FAIL: still blocking on misalignment: {str(detail2)[:200]}")
    else:
        print(f"  ERROR {s2}: {str(detail2)[:200]}")
print("Done.")
