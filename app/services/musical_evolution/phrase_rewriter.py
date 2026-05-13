import logging
logger=logging.getLogger(__name__)
def apply(sections,state):
    score=0
    for s in sections:
        b=int(s.get('bars',0) or 0)
        if b<8: continue
        p={'phrase_a':'setup','phrase_b':'response','phrase_transition':'prepare'}
        events=['phrase_a_setup','phrase_b_response','phrase_transition_prepare']
        if b>=16: p['phrase_a2']='evolved'; events.insert(2,'phrase_a2_evolved')
        s.setdefault('phrase_plan',p); s['phrase_plan_used']=True
        for ev in events: s.setdefault('variations',[]).append({'variation_type':ev,'bar':s.get('bar_start',0),'duration_bars':1,'intensity':0.6,'params':{}}); state.add(s.get('name',''),ev)
        score+=1
    logger.info('PHRASE_REWRITE_APPLIED')
    return round(min(1.0,score/max(1,len(sections))),3)
