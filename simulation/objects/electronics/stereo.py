from protocolbuffers import Audio_pb2
from protocolbuffers.Consts_pb2 import MSG_OBJECT_AUDIO_PLAYLIST_SKIP_TO_NEXT
from protocolbuffers.DistributorOps_pb2 import Operation
from distributor.ops import GenericProtocolBufferOp
from distributor.system import Distributor
from element_utils import build_critical_section
from interactions.aop import AffordanceObjectPair
from interactions.base.immediate_interaction import ImmediateSuperInteraction
from interactions.base.super_interaction import SuperInteraction
from interactions.interaction_finisher import FinishingType
from interactions.utils.animation_reference import TunableAnimationReference
from interactions.utils.state import conditional_animation
from objects.components.state import TunableStateTypeReference, with_on_state_changed
from sims4.tuning.tunable import TunableReference, Tunable, TunableTuple
from sims4.utils import flexmethod
import element_utils
import event_testing.test_variants
import objects.components.state
import services
import sims4
logger = sims4.log.Logger('Stereo')

class ListenSuperInteraction(SuperInteraction):
    __qualname__ = 'ListenSuperInteraction'
    INSTANCE_TUNABLES = {'required_station': objects.components.state.TunableStateValueReference(description='\n            The station that this affordance listens to.\n            '), 'remote_animation': TunableAnimationReference(description='\n            The animation for using the stereo remote.\n            '), 'off_state': objects.components.state.TunableStateValueReference(description='\n            The channel that represents the off state.\n            ')}
    CHANGE_CHANNEL_XEVT_ID = 101

    @classmethod
    def _verify_tuning_callback(cls):
        super()._verify_tuning_callback()
        if cls.required_station is None:
            logger.error('Tuning: {} is missing a Required Channel.', cls.__name__)
        if cls.remote_animation is None:
            logger.error('Tuning: {} is missing a Remote Animation.', cls.__name__)

    def ensure_state(self, desired_station):
        return conditional_animation(self, desired_station, self.CHANGE_CHANNEL_XEVT_ID, self.affordance.remote_animation)

    def _changed_state_callback(self, target, state, old_value, new_value):
        if new_value != self.off_state:
            object_callback = getattr(new_value, 'on_interaction_canceled_from_state_change', None)
            if object_callback is not None:
                object_callback(self)
        self.cancel(FinishingType.OBJECT_CHANGED, cancel_reason_msg='state: interaction canceled on state change ({} != {})'.format(new_value.value, self.required_station.value))

    def _run_interaction_gen(self, timeline):
        result = yield element_utils.run_child(timeline, build_critical_section(self.ensure_state(self.affordance.required_station), objects.components.state.with_on_state_changed(self.target, self.affordance.required_station.state, self._changed_state_callback, super()._run_interaction_gen)))
        return result

class CancelOnStateChangeInteraction(SuperInteraction):
    __qualname__ = 'CancelOnStateChangeInteraction'
    INSTANCE_TUNABLES = {'cancel_state_test': event_testing.test_variants.TunableStateTest(description="the state test to run when the object's state changes. If this test passes, the interaction will cancel")}

    def _run_interaction_gen(self, timeline):
        result = yield element_utils.run_child(timeline, element_utils.build_element([self._cancel_on_state_test_pass(self.cancel_state_test, super()._run_interaction_gen)]))
        return result

    def _cancel_on_state_test_pass(self, cancel_on_state_test, *sequence):
        value = cancel_on_state_test.value

        def callback_fn(target, state, old_value, new_value):
            resolver = self.get_resolver(target=target)
            if resolver(cancel_on_state_test):
                self.cancel(FinishingType.OBJECT_CHANGED, cancel_reason_msg='state: interaction canceled on state change because new state:{} {} required state:{}'.format(new_value, cancel_on_state_test.operator, value))
                object_callback = getattr(new_value, 'on_interaction_canceled_from_state_change', None)
                if object_callback is not None:
                    object_callback(self)

        return with_on_state_changed(self.target, value.state, callback_fn, *sequence)

class SkipToNextSongSuperInteraction(ImmediateSuperInteraction):
    __qualname__ = 'SkipToNextSongSuperInteraction'
    INSTANCE_TUNABLES = {'audio_state_type': TunableStateTypeReference(description='The state type that when changed, will change the audio on the target object. This is used to get the audio channel to advance the playlist.')}

    def _run_gen(self, timeline):
        play_audio_primative = self.target.get_component_managed_state_distributable('audio_state', self.affordance.audio_state_type)
        if play_audio_primative is not None:
            msg = Audio_pb2.SoundSkipToNext()
            msg.object_id = self.target.id
            msg.channel = play_audio_primative.channel
            distributor = Distributor.instance()
            distributor.add_op_with_no_owner(GenericProtocolBufferOp(Operation.OBJECT_AUDIO_PLAYLIST_SKIP_TO_NEXT, msg))
        return True
        yield None

class StereoPieMenuChoicesInteraction(ImmediateSuperInteraction):
    __qualname__ = 'StereoPieMenuChoicesInteraction'
    INSTANCE_TUNABLES = {'channel_state_type': objects.components.state.TunableStateTypeReference(description='The state used to populate the picker.'), 'push_additional_affordances': Tunable(bool, True, description="Whether to push affordances specified by the channel. This is used for stereo's turn on and listen to... interaction"), 'off_state_pie_menu_category': TunableTuple(off_state=objects.components.state.TunableStateValueReference(description='The state value at which to display the name'), pie_menu_category=TunableReference(services.get_instance_manager(sims4.resources.Types.PIE_MENU_CATEGORY), description='Pie menu category so we can display a submenu for each outfit category'))}

    def __init__(self, aop, context, audio_channel=None, **kwargs):
        super().__init__(aop, context, **kwargs)
        self.audio_channel = audio_channel

    @flexmethod
    def get_pie_menu_category(cls, inst, stereo=None, **interaction_parameters):
        inst_or_cls = inst if inst is not None else cls
        if stereo is not None:
            current_state = stereo.get_state(inst_or_cls.channel_state_type)
            if current_state is inst_or_cls.off_state_pie_menu_category.off_state:
                return inst_or_cls.off_state_pie_menu_category.pie_menu_category
        return inst_or_cls.category

    @flexmethod
    def _get_name(cls, inst, *args, audio_channel=None, **interaction_parameters):
        if inst is not None:
            return inst.audio_channel.display_name
        return audio_channel.display_name

    @classmethod
    def potential_interactions(cls, target, context, **kwargs):
        for client_state in target.get_client_states(cls.channel_state_type):
            while client_state.show_in_picker and client_state.test_channel(target, context):
                yield AffordanceObjectPair(cls, target, cls, None, stereo=target, audio_channel=client_state)

    def _run_interaction_gen(self, timeline):
        self.audio_channel.activate_channel(interaction=self, push_affordances=self.push_additional_affordances)

