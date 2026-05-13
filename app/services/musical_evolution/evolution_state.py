from dataclasses import dataclass, field

@dataclass
class EvolutionState:
    previous_section_signature: str|None=None
    used_melody_patterns:set[str]=field(default_factory=set)
    used_bass_patterns:set[str]=field(default_factory=set)
    used_drum_patterns:set[str]=field(default_factory=set)
    hook_energy_history:list[float]=field(default_factory=list)
    phrase_history:list[str]=field(default_factory=list)
    transition_history:list[str]=field(default_factory=list)
    section_contrast_history:list[float]=field(default_factory=list)
    mutation_events_by_section:dict[str,list[str]]=field(default_factory=dict)

    def add(self, section:str, event:str):
        self.mutation_events_by_section.setdefault(section,[]).append(event)
