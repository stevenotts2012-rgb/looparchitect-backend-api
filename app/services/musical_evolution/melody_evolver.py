import logging
logger=logging.getLogger(__name__)
MELODIC=("melody","harmony","pad","vocal","synth","arp")

def apply(sections,state):
    for s in sections:
        n=s.get('name','').lower(); roles=[str(r).lower() for r in s.get('active_stem_roles',[])]
        if not any(any(k in r for k in MELODIC) for r in roles):
            continue
        v=s.setdefault('variations',[])
        ev='melody_phrase_a'
        if 'pre_hook' in n: ev='prehook_melody_tension'; v.append({'variation_type':'reverse_melody_pickup','bar':s.get('bar_start',0),'duration_bars':1,'intensity':0.72,'params':{}}); logger.info('PREHOOK_MELODY_TENSION_APPLIED')
        elif 'hook_2' in n: ev='melody_hook2_lift'
        elif 'hook' in n: ev='melody_hook_lift'; v.append({'variation_type':'melody_widen_hook','bar':s.get('bar_start',0),'duration_bars':2,'intensity':0.82,'params':{}}); v.append({'variation_type':'stem_gain_change','bar':s.get('bar_start',0),'duration_bars':2,'intensity':0.85,'params':{'gain_db':3,'stems':'melody,pad,synth'}}); v.append({'variation_type':'stem_filter','bar':s.get('bar_start',0),'duration_bars':2,'intensity':0.8,'params':{'filter':'highshelf','gain_db':3}}); v.append({'variation_type':'widen_role','bar':s.get('bar_start',0),'duration_bars':2,'intensity':0.8,'params':{'stems':'melody,pad'}}); v.append({'variation_type':'melodic_call_response','bar':s.get('bar_start',0),'duration_bars':2,'intensity':0.8,'params':{}}); logger.info('HOOK_MELODY_REINFORCED')
        elif 'verse_2' in n: ev='melody_verse2_variation'
        elif 'bridge' in n: ev='melody_bridge_reset'; logger.info('BRIDGE_MELODY_RESET_APPLIED')
        elif 'outro' in n: ev='melody_outro_resolution'
        v.append({'variation_type':ev,'bar':s.get('bar_start',0),'duration_bars':max(1,int(s.get('bars',1))//2),'intensity':0.7,'params':{}}); state.add(s.get('name','section'),ev)
    logger.info('MELODY_EVOLUTION_APPLIED')
