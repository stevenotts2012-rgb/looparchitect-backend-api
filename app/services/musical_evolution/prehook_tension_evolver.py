import logging
logger=logging.getLogger(__name__)
def apply(sections,state):
    for i,s in enumerate(sections):
        n=str(s.get('name','')).lower()
        if 'pre_hook' in n or ('verse' in n and i+1<len(sections) and 'hook' in str(sections[i+1].get('name','')).lower()):
            for ev in ('prehook_tension_pull','drum_fill_pre_hook','melody_pickup_pre_hook','hook_anticipation_pause'):
                s.setdefault('variations',[]).append({'variation_type':ev,'bar':s.get('bar_start',0),'duration_bars':1,'intensity':0.8,'params':{}}); state.add(s.get('name',''),ev)
    logger.info('PREHOOK_TENSION_EVOLUTION_APPLIED')
