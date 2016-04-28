from interactions import ParticipantType
from interactions.utils.interaction_elements import XevtTriggeredElement
from sims4.tuning.tunable import HasTunableFactory, TunableEnumEntry, Tunable
import build_buy
import date_and_time
import element_utils
import elements

class SendToInventory(XevtTriggeredElement, HasTunableFactory):
    __qualname__ = 'SendToInventory'
    FACTORY_TUNABLES = {'description': '\n            Transfer the participant object to the household inventory as \n            a result of the interaction.\n            ', 'participant': TunableEnumEntry(description='\n            The participant of the interaction who will be sent to the\n            specified inventory.\n            ', tunable_type=ParticipantType, default=ParticipantType.Object), 'use_sim_inventory': Tunable(description="\n            If Checked, the object will be moved to the Actor's Inventory. If not\n            checked, the object will be added to the Actor's family inventory.", tunable_type=bool, default=False)}

    def _behavior_element(self, timeline):

        def _do_behavior(timeline):
            target = self.interaction.get_participant(self.participant)
            if target is None:
                return False
            target.fade_out()
            timespan = date_and_time.create_time_span(minutes=target.FADE_DURATION)
            yield element_utils.run_child(timeline, elements.SleepElement(timespan))
            sim = self.interaction.sim
            target.set_household_owner_id(sim.household_id)
            replace_reserve = False
            if target.in_use_by(sim, owner=self.interaction):
                target.release(sim, self.interaction)
                replace_reserve = True
            try:
                if target == self.interaction.target:
                    self.interaction.set_target(None)
                if self.use_sim_inventory:
                    sim.inventory_component.system_add_object(target, sim)
                else:
                    build_buy.move_object_to_household_inventory(target)
            finally:
                target.opacity = 1
                if replace_reserve:
                    target.reserve(sim, self.interaction)
            return True

        if not self.triggered:
            self.triggered = True
            if self._should_do_behavior:
                self.result = yield _do_behavior(timeline)
            else:
                self.result = None
        return self.result

