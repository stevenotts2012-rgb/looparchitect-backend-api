import json
from app.database import SessionLocal
from app.models.arrangement import Arrangement

try:
    db = SessionLocal()
    arrangements = db.query(Arrangement).order_by(Arrangement.id.desc()).limit(3).all()
    print(f"Found {len(arrangements)} recent arrangements")
    
    for idx, arr in enumerate(arrangements):
        print(f"\n--- Arrangement {idx + 1} (ID: {arr.id}) ---")
        if arr.arrangement_json:
            try:
                data = json.loads(arr.arrangement_json)
                if 'sections' in data:
                    print(f"Sections count: {len(data['sections'])}")
                    for i, section in enumerate(data['sections'][:5]):
                        sec_type = section.get('section_type') or section.get('type') or 'unknown'
                        print(f"  [{i}] type='{sec_type}', bars={section.get('bars')}, name={section.get('name')}")
                else:
                    all_keys = list(data.keys())
                    print(f"Keys: {all_keys[:10]}")
            except Exception as e:
                print(f"Error parsing: {e}")
        else:
            print("No arrangement_json")
    
    db.close()
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
