import json, time, sqlite3, urllib.request

payload = json.dumps({
    'loop_id': 1,
    'target_seconds': 45,
    'style_text_input': 'dark trap cinematic drop',
    'use_ai_parsing': True
}).encode()

req = urllib.request.Request(
    'http://127.0.0.1:8000/api/v1/arrangements/generate',
    data=payload,
    headers={'Content-Type': 'application/json'},
    method='POST'
)

response = json.loads(urllib.request.urlopen(req, timeout=60).read().decode())
aid = response['arrangement_id']
print(f'Generated arrangement {aid}, waiting for render...')
time.sleep(5)

db = sqlite3.connect('test.db')
c = db.cursor()

# Check final status and data
c.execute('SELECT status, producer_arrangement_json, arrangement_json FROM arrangements WHERE id=?', (aid,))
status, pj, aj = c.fetchone()

print(f'\nArrangement {aid}:')
print(f'  Status: {status}')

if pj:
    pa = json.loads(pj).get('producer_arrangement', {})
    secs = pa.get('sections', [])
    print(f'  Producer sections: {len(secs)}')
    for s in secs:
        print(f'    - {s.get("name"):12} type={s.get("section_type") or s.get("type"):12} bars={s.get("bars")}')

if aj:
    tj = json.loads(aj)
    print(f'  Timeline sections: {len(tj.get("sections", []))}')
    print(f'  Render profile: {tj.get("render_profile")}')

db.close()
