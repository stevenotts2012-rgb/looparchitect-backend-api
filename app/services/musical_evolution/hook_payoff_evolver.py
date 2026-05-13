import logging
logger=logging.getLogger(__name__)
def apply(sections,state):
    hooks=[s for s in sections if 'hook' in str(s.get('name','')).lower()]
    for i,h in enumerate(hooks):
        h.setdefault('variations',[]).append({'variation_type':'hook_payoff_moment','bar':h.get('bar_start',0),'duration_bars':1,'intensity':0.85,'params':{}})
        h['variations'].append({'variation_type':'hook_downbeat_impact','bar':h.get('bar_start',0),'duration_bars':1,'intensity':0.86,'params':{}})
        if i>0: h['variations'].append({'variation_type':'hook2_bigger_payoff','bar':h.get('bar_start',0),'duration_bars':2,'intensity':0.9,'params':{}}); logger.info('HOOK2_PAYOFF_ESCALATED')
        state.add(h.get('name',''),'hook_payoff_moment')
    logger.info('HOOK_PAYOFF_EVOLUTION_APPLIED')
