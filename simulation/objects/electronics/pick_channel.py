from event_testing.results import TestResult
from interactions.base.picker_interaction import PickerSuperInteraction, AutonomousPickerSuperInteraction
from interactions.base.picker_strategy import StatePickerEnumerationStrategy
from interactions.base.super_interaction import SuperInteraction
from sims4.localization import TunableLocalizedStringFactory
from sims4.tuning.instances import lock_instance_tunables
from sims4.tuning.tunable import TunableMapping, Tunable
from sims4.utils import flexmethod
from singletons import DEFAULT
import objects.components.state
import sims4.log
import ui
logger = sims4.log.Logger('PickChannel')

class PickChannelSuperInteraction(PickerSuperInteraction):
    __qualname__ = 'PickChannelSuperInteraction'
    INSTANCE_TUNABLES = {'state': objects.components.state.TunableStateTypeReference(description='The state used to populate the picker.'), 'conditional_display_names': TunableMapping(key_type=objects.components.state.TunableStateValueReference(description='The state value at which to display the name'), value_type=TunableLocalizedStringFactory(description='Localized name of this interaction'), description='A way to specify a different interaction display name for specific states of the object'), 'push_additional_affordances': Tunable(bool, True, description="Whether to push affordances specified by the channel. This is used for stereo's turn on and listen to... interaction")}

    def __init__(self, *args, **kwargs):
        choice_enumeration_strategy = StatePickerEnumerationStrategy()
        super().__init__(choice_enumeration_strategy=choice_enumeration_strategy, *args, **kwargs)

    def _run_interaction_gen(self, timeline):
        self._show_picker_dialog(self.sim, target_sim=self.sim)
        return True

    @flexmethod
    def picker_rows_gen(cls, inst, target, context, **kwargs):
        channel_list = []
        if inst is not None:
            inst._choice_enumeration_strategy.build_choice_list(self, cls.state)
            channel_list = inst._choice_enumeration_strategy.choices
        else:
            channel_list = [client_state for client_state in target.get_client_states(cls.state) if client_state.show_in_picker]
        for state in channel_list:
            is_enabled = target.get_state(cls.state).value is not state.value
            row = ui.ui_dialog_picker.ObjectPickerRow(is_enable=is_enabled, name=state.display_name, icon=state.icon, row_description=state.display_description, tag=state)
            yield row

    def on_choice_selected(self, choice_tag, **kwargs):
        state = choice_tag
        if state is not None:
            state.activate_channel(interaction=self, push_affordances=self.push_additional_affordances)

    @flexmethod
    def _get_name(cls, inst, target=DEFAULT, context=DEFAULT, **kwargs):
        inst_or_cls = inst if inst is not None else cls
        current_state = target.get_state(inst_or_cls.state)
        if current_state in inst_or_cls.conditional_display_names:
            return inst_or_cls.conditional_display_names[current_state](current_state.display_name)
        return super(PickerSuperInteraction, inst_or_cls)._get_name(target=target, context=context, **kwargs)

class PickChannelAutonomouslySuperInteraction(AutonomousPickerSuperInteraction):
    __qualname__ = 'PickChannelAutonomouslySuperInteraction'
    INSTANCE_TUNABLES = {'state': objects.components.state.TunableStateTypeReference(description='The state used to populate the picker.'), 'push_additional_affordances': Tunable(bool, True, description="Whether to push affordances specified by the channel. This is used for stereo's turn on and listen to... interaction")}

    def __init__(self, *args, **kwargs):
        super().__init__(choice_enumeration_strategy=StatePickerEnumerationStrategy(), *args, **kwargs)

    def _run_interaction_gen(self, timeline):
        self._choice_enumeration_strategy.build_choice_list(self, self.state)
        chosen_state = self._choice_enumeration_strategy.find_best_choice(self)
        if chosen_state is None:
            logger.error('{} fail to find a valid chosen state value for state {}'.format(self.__class__.__name__, self.state))
            return False
        chosen_state.activate_channel(interaction=self, push_affordances=self.push_additional_affordances)
        return True

    @classmethod
    def _test(cls, target, context, **kwargs):
        test_result = super()._test(target, context, **kwargs)
        if not test_result:
            return test_result
        if not StatePickerEnumerationStrategy.has_valid_choice(target, context, state=cls.state):
            return TestResult(False, 'No valid choice in State Picker Enumeration Strategy.')
        return TestResult.TRUE

class WatchCurrentChannelAutonomouslySuperInteraction(SuperInteraction):
    __qualname__ = 'WatchCurrentChannelAutonomouslySuperInteraction'
    INSTANCE_TUNABLES = {'state': objects.components.state.TunableStateTypeReference(description='The state used to populate the picker.')}

    def _run_interaction_gen(self, timeline):
        current_state = self.target.get_state(self.state)
        current_state.activate_channel(interaction=self, push_affordances=True)
        return True

lock_instance_tunables(AutonomousPickerSuperInteraction, allow_user_directed=False, basic_reserve_object=None, disable_transitions=True)
