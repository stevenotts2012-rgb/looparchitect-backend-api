import logging
logger=logging.getLogger(__name__)
def apply(sections,state):
    for i in range(len(sections)-1):
        a,b=sections[i],sections[i+1]
        an,bn=str(a.get('name','')).lower(),str(b.get('name','')).lower()
        ev='smooth_crossfade'
        if 'verse' in an and 'hook' in bn: ev='hook_anticipation_pause'; logger.info('HOOK_IMPACT_TRANSITION')
        elif 'hook' in an and 'verse' in bn: ev='release_tail'
        elif 'bridge' in an and 'hook' in bn: ev='bridge_to_hook_rebuild'; logger.info('EMOTIONAL_RESET_TRANSITION')
        elif float(b.get('energy',0.5))>float(a.get('energy',0.5)): ev='reactive_riser'
        else: ev='reactive_downlift'
        a.setdefault('variations',[]).append({'variation_type':ev,'bar':max(0,int(a.get('bar_start',0))+max(0,int(a.get('bars',1))-1)),'duration_bars':1,'intensity':0.72,'params':{}}); state.transition_history.append(ev)
    logger.info('TRANSITION_REACTIVITY_APPLIED')
    return round(min(1.0,len(state.transition_history)/max(1,len(sections)-1)),3)
