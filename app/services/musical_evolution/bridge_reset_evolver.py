import logging
logger=logging.getLogger(__name__)
def apply(sections,state):
    for s in sections:
        if 'bridge' in str(s.get('name','')).lower():
            for ev in ('bass_bridge_dropout','drum_bridge_dropout','melody_bridge_reset','filtered_texture','emotional_space','rebuild_to_hook_or_outro'):
                s.setdefault('variations',[]).append({'variation_type':ev,'bar':s.get('bar_start',0),'duration_bars':1,'intensity':0.75,'params':{}}); state.add(s.get('name',''),ev)
    logger.info('BRIDGE_RESET_EVOLUTION_APPLIED')
