#!/usr/bin/env python
"""Check producer arrangement structure in database."""
import sqlite3
import json

conn = sqlite3.connect('test.db')
cursor = conn.cursor()

cursor.execute('SELECT producer_arrangement_json FROM arrangements WHERE id = 162')
row = cursor.fetchone()

if row:
    data = json.loads(row[0])
    producer = data.get('producer_arrangement', {})
    
    print('PRODUCER ARRANGEMENT STRUCTURE:')
    print('='*60)
    
    sections = producer.get('sections', [])
    print(f'Sections: {len(sections)}')
    for i, sec in enumerate(sections):
        print(f'  [{i}] type={sec.get("section_type"):12} bars={sec.get("bars"):2} energy={sec.get("energy", 0):.1f}')
    
    print(f'\nTotal bars: {producer.get("total_bars")}')
    print(f'BPM: {producer.get("bpm")}')
    print(f'Key: {producer.get("key")}')
    print(f'Drum style: {producer.get("drum_style")}')
    
    transitions = producer.get('transitions', [])
    print(f'\nTransitions: {len(transitions)}')
    for i, trans in enumerate(transitions[:3]):
        print(f'  [{i}] type={trans.get("transition_type")} from_bar={trans.get("from_bar")} to_bar={trans.get("to_bar")}')
    
    variations = producer.get('all_variations', [])
    print(f'\nVariations: {len(variations)}')
    for i, var in enumerate(variations[:5]):
        print(f'  [{i}] type={var.get("variation_type")} section={var.get("section")} bars={var.get("bars")}')
    
    tracks = producer.get('tracks', [])
    print(f'\nTracks/Instruments: {len(tracks)}')
    for i, track in enumerate(tracks[:3]):
        print(f'  [{i}] {track.get("name", "unknown"):20} role={track.get("role", "unknown")}')

conn.close()
