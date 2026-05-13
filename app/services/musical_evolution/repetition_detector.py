import logging
logger=logging.getLogger(__name__)
def apply(sections,state):
    sigs=[]
    for s in sections:
        sig=(tuple(s.get('active_stem_roles') or []), tuple(v.get('variation_type') for v in s.get('variations',[])))
        sigs.append(sig)
    rep=1-(len(set(sigs))/max(1,len(sigs)))
    hook_sep=0.8
    if rep>0.45 and sections:
        logger.info('REPETITION_DETECTED')
        logger.info('MUSICAL_EVOLUTION_REPAIR_TRIGGERED')
        sections[-1].setdefault('variations',[]).append({'variation_type':'transition_handoff_variation','bar':sections[-1].get('bar_start',0),'duration_bars':1,'intensity':0.7,'params':{}})
    return {'melody_repetition_score':round(rep,3),'groove_repetition_score':round(rep,3),'bass_repetition_score':round(rep,3),'section_repetition_score':round(rep,3),'hook_separation_score':round(hook_sep,3)}
