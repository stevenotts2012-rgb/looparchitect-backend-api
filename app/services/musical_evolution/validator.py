import logging
logger=logging.getLogger(__name__)
def validate_and_repair(sections,metrics):
    repaired=False
    for s in sections:
        n=str(s.get('name','')).lower(); vars=[v.get('variation_type') for v in s.get('variations',[])]
        if 'pre_hook' in n and 'prehook_tension_pull' not in vars:
            s.setdefault('variations',[]).append({'variation_type':'prehook_tension_pull','bar':s.get('bar_start',0),'duration_bars':1,'intensity':0.75,'params':{}}); repaired=True
        if 'bridge' in n and 'melody_bridge_reset' not in vars:
            s.setdefault('variations',[]).append({'variation_type':'melody_bridge_reset','bar':s.get('bar_start',0),'duration_bars':1,'intensity':0.75,'params':{}}); repaired=True
    if repaired: logger.info('MUSICAL_EVOLUTION_VALIDATION_REPAIRED')
    logger.info('MUSICAL_EVOLUTION_VALIDATION_PASSED')
    return sections
