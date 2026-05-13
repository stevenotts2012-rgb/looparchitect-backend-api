import logging
logger=logging.getLogger(__name__)
def apply(sections,state):
    for s in sections:
        for ev in ('micro_timing_variation','velocity_variation','groove_drift','phrase_push_pull','transition_looseness'):
            s.setdefault('variations',[]).append({'variation_type':ev,'bar':s.get('bar_start',0),'duration_bars':1,'intensity':0.45,'params':{'safe_meta_only':True}})
            state.add(s.get('name',''),ev)
    logger.info('HUMANIZATION_APPLIED')
    return 0.74
