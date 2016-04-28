from event_testing.resolver import DoubleSimResolver, SingleSimResolver
from event_testing.test_variants import TunableRelationshipTest
from interactions import ParticipantType
from interactions.base.super_interaction import SuperInteraction
from ui.ui_dialog_notification import UiDialogNotification
import services

class RingDoorbellSuperInteraction(SuperInteraction):
    __qualname__ = 'RingDoorbellSuperInteraction'
    INSTANCE_TUNABLES = {'_nobody_home_failure_notification': UiDialogNotification.TunableFactory(description='\n                Notification that displays if no one was home when they tried\n                to ring the doorbell.\n                '), '_bad_relationship_failure_notification': UiDialogNotification.TunableFactory(description="\n                Notification that displays if there wasn't high enough\n                relationship with any of the household members when they\n                tried to ring the doorbell.\n                "), '_success_notification': UiDialogNotification.TunableFactory(description='\n                Notification that displays if the user succeeded in becoming\n                greeted when they rang the doorbell.\n                '), '_relationship_test': TunableRelationshipTest(description='\n                The Relationship test ran between the sim running the\n                interaction and all of the npc family members to see if they\n                are allowed in.\n                ', locked_args={'subject': ParticipantType.Actor, 'target_sim': ParticipantType.TargetSim})}

    def _try_to_be_invited_in(self):
        owner_household = services.household_manager().get(services.current_zone().lot.owner_household_id)
        resolver = self.get_resolver()
        if owner_household is None:
            dialog = self._nobody_home_failure_notification(self.sim, resolver)
            dialog.show_dialog()
            return
        owner_household_sims = tuple(owner_household.instanced_sims_gen())
        if not owner_household_sims:
            dialog = self._nobody_home_failure_notification(self.sim, resolver)
            dialog.show_dialog()
            return
        for target_sim in owner_household_sims:
            relationship_resolver = DoubleSimResolver(self.sim.sim_info, target_sim.sim_info)
            while relationship_resolver(self._relationship_test):
                dialog = self._success_notification(self.sim, resolver)
                dialog.show_dialog()
                services.get_zone_situation_manager().make_waiting_player_greeted(self.sim)
                return
        dialog = self._bad_relationship_failure_notification(self.sim, resolver)
        dialog.show_dialog()

    def _post_perform(self):
        super()._post_perform()
        self.add_exit_function(self._try_to_be_invited_in)

