import logging
logger=logging.getLogger(__name__)
DR=("drum","perc","hat","clap","snare")
def apply(sections,state,variation_index=0):
    for s in sections:
        n=s.get('name','').lower(); roles=[str(r).lower() for r in s.get('active_stem_roles',[])]
        if not any(any(k in r for k in DR) for r in roles): continue
        v=s.setdefault('variations',[])
        base='drum_stable_groove'
        if 'pre_hook' in n: base='drum_pre_hook_fill'; v.append({'variation_type':'prehook_groove_tension','bar':s.get('bar_start',0),'duration_bars':1,'intensity':0.8,'params':{}}); logger.info('PREHOOK_GROOVE_TENSION')
        elif 'hook_2' in n: base='drum_hook2_lift'
        elif 'hook' in n: base='drum_hook_density_lift'; v.append({'variation_type':'hook_drum_density','bar':s.get('bar_start',0),'duration_bars':1,'intensity':0.88 if variation_index else 0.76,'params':{}}); v.append({'variation_type':'add_impact','bar':s.get('bar_start',0),'duration_bars':1,'intensity':0.82,'params':{}}); v.append({'variation_type':'downbeat_impact','bar':s.get('bar_start',0),'duration_bars':1,'intensity':0.87 if variation_index else 0.75,'params':{}}); logger.info('HOOK_GROOVE_ESCALATION')
        elif 'verse_2' in n: base='drum_verse2_hat_variation'
        elif 'bridge' in n: base='drum_bridge_dropout'; logger.info('GROOVE_DROPOUT_APPLIED')
        elif 'outro' in n: base='drum_outro_simplify'
        v.append({'variation_type':base,'bar':s.get('bar_start',0),'duration_bars':1,'intensity':0.7 if variation_index==0 else 0.84,'params':{}}); state.add(s.get('name',''),base)
    logger.info('DRUM_EVOLUTION_APPLIED'); logger.info('GROOVE_EVOLUTION_APPLIED')
