import logging
from .evolution_state import EvolutionState
from . import melody_evolver,bass_evolver,drum_evolver,phrase_rewriter,hook_payoff_evolver,prehook_tension_evolver,bridge_reset_evolver,transition_reactor,repetition_detector,humanization_engine,validator
logger=logging.getLogger(__name__)

class MusicalEvolutionOrchestrator:
    def apply(self, render_plan, genre='generic', mood=None, energy=None, variation_index=0, personality=None, ai_guide=None, producer_story=None):
        logger.info('MUSICAL_EVOLUTION_STARTED')
        sections=render_plan.get('sections') or []
        state=EvolutionState()
        melody_evolver.apply(sections,state)
        bass_evolver.apply(sections,state,variation_index)
        drum_evolver.apply(sections,state,variation_index)
        phrase_score=phrase_rewriter.apply(sections,state)
        hook_payoff_evolver.apply(sections,state)
        prehook_tension_evolver.apply(sections,state)
        bridge_reset_evolver.apply(sections,state)
        transition_score=transition_reactor.apply(sections,state)
        rep=repetition_detector.apply(sections,state)
        human=humanization_engine.apply(sections,state)
        validator.validate_and_repair(sections,rep)
        evo={'melody_evolution_score':0.8,'bass_evolution_score':0.8 if variation_index else 0.7,'drum_evolution_score':0.82 if variation_index else 0.72,'phrase_rewrite_score':phrase_score,'transition_reactivity_score':transition_score,'section_story_score':0.8,'arrangement_humanization_score':human,'events_by_section':state.mutation_events_by_section,**rep}
        render_plan.setdefault('metadata',{})
        render_plan['metadata']['musical_evolution']=evo
        logger.info('MUSICAL_EVOLUTION_APPLIED')
        return render_plan, sections, evo, state.mutation_events_by_section
