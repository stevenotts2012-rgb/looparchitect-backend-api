import json, sqlite3

db = sqlite3.connect('test.db')
c = db.cursor()
c.execute('SELECT producer_arrangement_json FROM arrangements WHERE id=159')
pa_json = c.fetchone()[0]
pa = json.loads(pa_json).get('producer_arrangement', {})
secs = pa.get('sections', [])
print('Producer sections stored in DB for arrangement 159:')
for i, sec in enumerate(secs):
    st = sec.get('section_type') or sec.get('type')
    name = sec.get('name')
    bars = sec.get('bars')
    energy = sec.get('energy_level') or sec.get('energy')
    print(f'  [{i}] type={st} | name={name} | bars={bars} | energy={energy}')
db.close()
