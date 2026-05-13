import logging
logger=logging.getLogger(__name__)
BASS=("bass","808","sub")
def apply(sections,state,variation_index=0):
    for s in sections:
        n=s.get('name','').lower(); roles=[str(r).lower() for r in s.get('active_stem_roles',[])]
        if not any(any(k in r for k in BASS) for r in roles): continue
        v=s.setdefault('variations',[])
        m={'verse':'bass_groove_pocket','pre_hook':'bass_pause_pre_hook','hook':'bass_hook_power','verse_2':'bass_verse2_pocket_change','hook_2':'bass_hook2_lift','bridge':'bass_bridge_dropout','outro':'bass_outro_simplify'}
        ev=next((val for k,val in m.items() if k in n),'bass_groove_pocket')
        intensity=0.65 if variation_index==0 else 0.82
        v.append({'variation_type':ev,'bar':s.get('bar_start',0),'duration_bars':1,'intensity':intensity,'params':{}}); state.add(s.get('name',''),ev)
        if 'pre_hook' in n: v.append({'variation_type':'bass_tension_pullback','bar':s.get('bar_start',0),'duration_bars':1,'intensity':0.76,'params':{}}); v.append({'variation_type':'bass_pause','bar':s.get('bar_start',0),'duration_bars':1,'intensity':0.8,'params':{'pause_bars':0.12}}); logger.info('PREHOOK_BASS_PULLBACK')
        if 'hook' in n: v.append({'variation_type':'bass_hook_reentry','bar':s.get('bar_start',0),'duration_bars':1,'intensity':0.85,'params':{}}); v.append({'variation_type':'stem_gain_change','bar':s.get('bar_start',0),'duration_bars':2,'intensity':0.86,'params':{'gain_db':2.5,'stems':'bass,808,sub'}}); logger.info('HOOK_BASS_EXPANSION')
        if 'bridge' in n: logger.info('BASS_BRIDGE_DROPOUT_APPLIED')
    logger.info('BASS_EVOLUTION_APPLIED')
