import weakref
from interactions import ParticipantType
from interactions.constraints import Anywhere, TunableGeometricConstraintVariant
from interactions.context import InteractionContext
from interactions.join_liability import JOIN_INTERACTION_LIABILITY, JoinInteractionLiability
from interactions.priority import Priority
from interactions.utils.interaction_elements import XevtTriggeredElement
from element_utils import build_critical_section_with_finally
from sims4.tuning.tunable import TunableReference, TunableEnumEntry, TunableList, Tunable
import interactions.constraints
import services

class ReactionTriggerElement(XevtTriggeredElement):
    __qualname__ = 'ReactionTriggerElement'
    FACTORY_TUNABLES = {'description': 'At the specified timing, push an affordance on other Sims on the lot.', 'reaction_affordance': TunableReference(services.affordance_manager(), description='The affordance to push on other Sims.'), 'reaction_target': TunableEnumEntry(ParticipantType, ParticipantType.Actor, description='The subject of this interaction that will be set as the target of the pushed reaction_affordance.'), 'reaction_constraints': TunableList(TunableGeometricConstraintVariant(), description='The constraints that Sims on the lot have to satisfy such that reaction_affordance is pushed on them.'), 'trigger_on_late_arrivals': Tunable(bool, False, needs_tuning=True, description='\n                                                                      If checked, Sims entering the reaction area after the reaction is first triggered will\n                                                                      also react, up until when the interaction is canceled.\n                                                                      ')}

    def __init__(self, interaction, *args, sequence=(), **kwargs):
        super().__init__(interaction, sequence=sequence, *args, **kwargs)
        self._reaction_target_sim = self.interaction.get_participant(self.reaction_target)
        self._reaction_constraint = None
        self._triggered_sims = _instances = weakref.WeakSet()

    @classmethod
    def on_affordance_loaded_callback(cls, affordance, reaction_trigger_element):

        def sim_can_execute_affordance(interaction, sim):
            context = InteractionContext(sim, InteractionContext.SOURCE_SCRIPT, Priority.High)
            return sim.test_super_affordance(reaction_trigger_element.reaction_affordance, interaction.target, context)

        affordance.register_sim_can_violate_privacy_callback(sim_can_execute_affordance)

    def _build_outer_elements(self, sequence):
        if self.trigger_on_late_arrivals:
            return build_critical_section_with_finally(sequence, self._remove_constraints)
        return sequence

    def _do_behavior(self):
        self._reaction_constraint = Anywhere()
        for tuned_reaction_constraint in self.reaction_constraints:
            self._reaction_constraint = self._reaction_constraint.intersect(tuned_reaction_constraint.create_constraint(None, target=self._reaction_target_sim))
        if self.trigger_on_late_arrivals:
            self._reaction_target_sim.reaction_triggers[self.interaction] = self
        for sim in services.sim_info_manager().instanced_sims_gen():
            self.intersect_and_execute(sim)

    def intersect_and_execute(self, sim):
        if sim in self._triggered_sims:
            return
        participants = self.interaction.get_participants(ParticipantType.AllSims)
        if sim not in participants:
            sim_constraint = interactions.constraints.Transform(sim.transform, routing_surface=sim.routing_surface)
            context = InteractionContext(sim, InteractionContext.SOURCE_SCRIPT, Priority.High)
            if sim_constraint.intersect(self._reaction_constraint).valid:
                result = sim.push_super_affordance(self.reaction_affordance, self._reaction_target_sim, context)
                if result:
                    self.interaction.add_liability(JOIN_INTERACTION_LIABILITY, JoinInteractionLiability(result.interaction))
                self._triggered_sims.add(sim)

    def _remove_constraints(self, *_, **__):
        self._reaction_target_sim.reaction_triggers.pop(self.interaction, None)

