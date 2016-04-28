from date_and_time import create_time_span
from event_testing import test_events
from interactions import ParticipantType
from sims4.sim_irq_service import yield_to_irq
from sims4.tuning.tunable import Tunable
import alarms
import services

class SocialInteractionMixin:
    __qualname__ = 'SocialInteractionMixin'
    INSTANCE_TUNABLES = {'_acquire_listeners_as_resource': Tunable(description='\n            If checked, all listener Sims will be acquired as part of this\n            interaction.  If unchecked, listeners running interactions that\n            ignore socials will not play reactionlets.\n            \n            Most interactions will want not to acquire listener Sims.  Not\n            acquiring listener Sims will allow for smoother gameplay when Sims\n            are multitasking while socializing. However, interactions with\n            visually defining reactionlets, such as Tell Joke or Make Toast\n            might want to acquire all listeners and have them react.\n            ', tunable_type=bool, default=False)}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._target_interaction_event_alarm_handle = None

    @property
    def acquire_listeners_as_resource(self):
        return self._acquire_listeners_as_resource

    def _trigger_interaction_start_event(self):
        super()._trigger_interaction_start_event()
        if self.social_group is not None:
            self.social_group._on_interaction_start(self)

    def _trigger_interaction_complete_test_event(self):
        yield_to_irq()
        super()._trigger_interaction_complete_test_event()
        self._remove_target_event_auto_update()

    def _register_target_event_auto_update(self):
        target_sim = self.get_participant(ParticipantType.TargetSim)
        if target_sim is not None:
            if self._target_interaction_event_alarm_handle is not None:
                self._remove_target_event_auto_update()
            self._target_interaction_event_alarm_handle = alarms.add_alarm(self, create_time_span(minutes=15), lambda _, sim_info=target_sim.sim_info, interaction=self, custom_keys=self.get_keys_to_process_events(): services.get_event_manager().process_event(test_events.TestEvent.InteractionUpdate, sim_info=sim_info, interaction=self, custom_keys=custom_keys), True)

    def _remove_target_event_auto_update(self):
        if self._target_interaction_event_alarm_handle is not None:
            alarms.cancel_alarm(self._target_interaction_event_alarm_handle)
            self._target_interaction_event_alarm_handle = None

