#!/usr/bin/env python3
"""Check recent arrangements in the database."""
import json
from app.db import SessionLocal
from app.models.arrangement import Arrangement

db = SessionLocal()
try:
    arrs = db.query(Arrangement).order_by(Arrangement.created_at.desc()).limit(3).all()
    
    if not arrs:
        print("No arrangements found in database")
    else:
        for a in arrs:
            print(f"\n{'='*60}")
            print(f"ID: {a.id}")
            print(f"Status: {a.status}")
            print(f"Loop: {a.loop.name if a.loop else 'N/A'}")
            print(f"BPM: {a.loop.bpm if a.loop else 'N/A'}")
            print(f"Target: {a.target_seconds}s")
            print(f"Genre: {a.genre or 'N/A'}")
            print(f"Created: {a.created_at}")
            print(f"Output: {a.output_s3_key or a.output_file_url or 'N/A'}")
            
            # Check render plan if available
            if a.render_plan_json:
                try:
                    plan = json.loads(a.render_plan_json)
                    sections = plan.get('sections', [])
                    print(f"\n📋 Render plan: {len(sections)} sections, {plan.get('total_bars', 0)} bars")
                    
                    # Check section structure
                    if sections:
                        print("\n🎵 Section breakdown:")
                        section_types = {}
                        variants_used = set()
                        
                        for i, sec in enumerate(sections[:10]):  # Show first 10
                            sec_type = sec.get('type', 'unknown')
                            sec_name = sec.get('name', sec_type)
                            bars = sec.get('bars', 0)
                            energy = sec.get('energy', 0)
                            variant = sec.get('loop_variant')
                            
                            section_types[sec_type] = section_types.get(sec_type, 0) + 1
                            if variant:
                                variants_used.add(variant)
                            
                            print(f"  {i+1}. {sec_name} ({sec_type}): {bars} bars, energy={energy:.2f}, variant={variant or 'NONE ❌'}")
                        
                        if len(sections) > 10:
                            print(f"  ... and {len(sections) - 10} more sections")
                        
                        print(f"\n📊 Section type distribution: {dict(section_types)}")
                        
                        if variants_used:
                            print(f"✅ Variants used: {sorted(variants_used)}")
                        else:
                            print("❌ NO VARIANTS ASSIGNED - this is the problem!")
                    
                    # Check loop variations info
                    loop_vars = plan.get('loop_variations', {})
                    if loop_vars and loop_vars.get('active'):
                        print(f"\n✅ Loop variation engine: ACTIVE")
                        print(f"   Variation count: {loop_vars.get('count', 0)}")
                        print(f"   Variation names: {loop_vars.get('names', [])}")
                        print(f"   Stems used: {loop_vars.get('stems_used', False)}")
                    else:
                        print(f"\n❌ Loop variation engine: INACTIVE or missing")
                        
                except Exception as e:
                    print(f"❌ Could not parse render plan: {e}")
            else:
                print("\n⚠️  No render plan found")
finally:
    db.close()
