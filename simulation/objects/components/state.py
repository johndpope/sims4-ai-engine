from collections import namedtuple
import collections
import operator
import random
import weakref
import alarms
from audio.primitive import TunablePlayAudio
from autonomy.autonomy_modifier import TunableAutonomyModifier, AutonomyModifier
from broadcasters.broadcaster_request import BroadcasterRequest
from broadcasters.environment_score.environment_score_state import EnvironmentScoreState
import caches
import clock
from element_utils import CleanupType, build_element
from element_utils import build_critical_section_with_finally
import enum
from event_testing import test_events
import event_testing
from event_testing.resolver import SingleObjectResolver
from graph_algos import topological_sort
from interactions import ParticipantType
from interactions.base.picker_tunables import TunableBuffWeightMultipliers
from interactions.interaction_finisher import FinishingType
from interactions.utils.animation import TunableAnimationObjectOverrides
from interactions.utils.audio import ApplyAudioEffect
from interactions.utils.tunable_icon import TunableIcon
from objects import TunableVisibilityState, TunableGeometryState, TunableMaterialState, TunableModelOrDefault, TunableMaterialVariant, PaintingState
import objects
from objects.components import Component, componentmethod, componentmethod_with_fallback
from objects.components.needs_state_value import NeedsStateValue
from objects.components.types import STATE_COMPONENT, CANVAS_COMPONENT, FLOWING_PUDDLE_COMPONENT, VIDEO_COMPONENT, LIGHTING_COMPONENT, CRAFTING_COMPONENT
from objects.components.video import RESOURCE_TYPE_VP6
from objects.object_enums import ResetReason
from placement import FindGoodLocationContext
import placement
from protocolbuffers import SimObjectAttributes_pb2 as protocols
from services import get_instance_manager
import services
import sims.bills_enums
from sims4 import math
from sims4.callback_utils import CallableList
from sims4.localization import TunableLocalizedString
from sims4.math import MAX_FLOAT
from sims4.random import random_chance, weighted_random_item
from sims4.tuning.instances import TunedInstanceMetaclass
from sims4.tuning.tunable import HasTunableReference, TunableEnumEntry, TunableVariant, Tunable, OptionalTunable, TunableTuple, TunableMapping, TunableReference, TunableInterval, TunableList, TunableResourceKey, HasTunableFactory, TunableRange, TunableFactory, HasTunableSingletonFactory, AutoFactoryInit, TunableColor, TunableSimMinute, TunablePercent, TunableSet
from sims4.utils import classproperty, Result
import sims4.zone_utils
from singletons import DEFAULT, UNSET
from snippets import TunableColorSnippet
from statistics.statistic_ops import ObjectStatisticChangeOp
from vfx import PlayMultipleEffects, PlayEffect
logger = sims4.log.Logger('StateComponent')

def get_supported_state(definition):
    state_component_tuning = definition.cls._components.state
    if state_component_tuning is None:
        return
    supported_states = set()
    tuning_states = set()
    for state in state_component_tuning.states:
        tuning_states.add(state.default_value)
    for tuned_state_value in tuning_states:
        if hasattr(tuned_state_value, 'state'):
            supported_states.add(tuned_state_value.state)
        else:
            state_from_list = None
            for state_value in tuned_state_value:
                if state_from_list is None:
                    state_from_list = state_value.state
                    supported_states.add(state_value.state)
                else:
                    while state_from_list != state_value.state:
                        logger.error("Random state value {} on object {}, does'nt match the other states inside the random list.", state_value, definition, owner='camilogarcia')
    return supported_states

class OptionalTunableClientStateChangeItem(OptionalTunable):
    __qualname__ = 'OptionalTunableClientStateChangeItem'

    def __init__(self, tunable, **kwargs):
        super().__init__(disabled_value=UNSET, disabled_name='leave_unchanged', enabled_name='apply_new_value', tunable=tunable, **kwargs)

class StatisticModifierList(HasTunableFactory, AutoFactoryInit):
    __qualname__ = 'StatisticModifierList'
    FACTORY_TUNABLES = {'autonomy_modifiers': TunableList(description='\n            List of possible Modifiers that may happen when a statistic gets \n            hit, this will modify the objects statistics behavior.\n            ', tunable=TunableAutonomyModifier(locked_args={'relationship_multipliers': None})), 'periodic_statistic_change': TunableTuple(description='\n            The stat change apply on the target within the state value.\n            ', interval=TunableSimMinute(description='\n            The number of sim minutes in between each application of the tuned operations.\n            Note: This operation sets an alarm, which has performance implications,\n            so please see a GPE before setting to a number lower than 5 mins.\n            ', default=60), operations=TunableList(tunable=ObjectStatisticChangeOp.TunableFactory()))}

    def __init__(self, target, **kwargs):
        super().__init__(**kwargs)
        self.target = target
        self.handles = []
        self._alarm_handle = None
        self._operations_on_alarm = []

    def start(self):
        self.target.add_statistic_component()
        for modifier in self.autonomy_modifiers:
            self.handles.append(self.target.add_statistic_modifier(modifier))
        self._start_statistic_gains()

    def stop(self, *_, **__):
        self.target.add_statistic_component()
        for handle in self.handles:
            self.target.remove_statistic_modifier(handle)
        self._end_statistic_gains()

    def _start_statistic_gains(self):
        periodic_mods = {}
        interval = self.periodic_statistic_change.interval
        operations = self.periodic_statistic_change.operations
        inv_interval = 1/interval
        if operations:
            for stat_op in operations:
                stat = stat_op.stat
                if stat is not None and stat.continuous:
                    if stat not in periodic_mods.keys():
                        periodic_mods[stat] = 0
                    mod_per_sec = stat_op.get_value()*inv_interval
                    periodic_mods[stat] += mod_per_sec
                else:
                    self._operations_on_alarm.append(stat_op)
        auto_mod = AutonomyModifier(statistic_modifiers=periodic_mods)
        handle = self.target.add_statistic_modifier(auto_mod)
        self.handles.append(handle)
        time_span = clock.interval_in_sim_minutes(interval)
        if self._operations_on_alarm:
            self._alarm_handle = alarms.add_alarm(self, time_span, self._do_gain, repeating=True)
        return True

    def _end_statistic_gains(self):
        if self._alarm_handle is not None:
            alarms.cancel_alarm(self._alarm_handle)
            self._alarm_handle = None

    def _do_gain(self, _):
        for statistic_op in self._operations_on_alarm:
            statistic_op.apply_to_object(self.target)

class LotStatisticModifierList(HasTunableFactory, AutoFactoryInit):
    __qualname__ = 'LotStatisticModifierList'
    FACTORY_TUNABLES = {'statistic_changes': TunableList(description='\n            statistic changes to apply to lot when state gets set\n            ', tunable=ObjectStatisticChangeOp.TunableFactory())}

    def __init__(self, target, **kwargs):
        super().__init__(**kwargs)
        self.target = target

    def start(self):
        current_zone = services.current_zone()
        lot = current_zone.lot
        lot.add_statistic_component()
        for statistic_op in self.statistic_changes:
            statistic_op.apply_to_object(lot)

    def stop(self, *_, **__):
        current_zone = services.current_zone()
        lot = current_zone.lot
        lot.add_statistic_component()
        for statistic_op in self.statistic_changes:
            statistic_op.remove_from_object(lot)

class UiMetadataList(HasTunableFactory, AutoFactoryInit, NeedsStateValue):
    __qualname__ = 'UiMetadataList'
    FACTORY_TUNABLES = {'data': TunableMapping(description='\n        ', key_type=str, value_type=TunableVariant(other_value=TunableVariant(default='integral', boolean=Tunable(bool, False), string=TunableLocalizedString(), integral=Tunable(int, 0), icon=TunableIcon(), color=TunableColor()), state_value=TunableVariant(default='value', locked_args={'display_name': 'display_name', 'display_description': 'display_description', 'icon': 'icon', 'value': 'value'})))}

    def __init__(self, target, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.target = target
        self.handles = []

    def start(self):
        for (name, value) in self.data.items():
            if isinstance(value, str):
                value = getattr(self.state_value, value)
            handle = self.target.add_ui_metadata(name, value)
            self.handles.append(handle)

    def stop(self, *_, **__):
        while self.handles:
            self.target.remove_ui_metadata(self.handles.pop())

class ObjectReplacementOperation(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'ObjectReplacementOperation'
    FACTORY_TUNABLES = {'new_object': OptionalTunable(description="\n        A reference to the type of object which will be created in this\n        object's place.\n        ", tunable=TunableReference(manager=services.definition_manager())), 'destroy_original_object': Tunable(description='\n        If checked, the original object will be destroyed.  If\n        unchecked, the original object will be left around.\n        ', tunable_type=bool, default=True)}
    RESULT_REPLACEMENT_FAILED = Result(True, 'Replacement failed.')
    RESULT_OBJECT_DESTROYED = Result(False, 'Object destroyed.')

    def __call__(self, target):
        if self.new_object is None:
            if not self.destroy_original_object:
                return self.RESULT_REPLACEMENT_FAILED
            if target.in_use:
                target.transient = True
                return self.RESULT_OBJECT_DESTROYED
            target.destroy(source=self, cause='Object replacement state operation, new_object is None')
            return self.RESULT_OBJECT_DESTROYED
        new_location = None
        if target.parent_slot is not None and target.parent_slot.is_valid_for_placement(definition=self.new_object, objects_to_ignore=(target,)):
            new_location = target.location
        if new_location is None:
            if target.location.routing_surface is None:
                logger.error('Object {} in location {} is creating an object with an invalid routing surface', target, target.location, owner='camilogarcia')
                return self.RESULT_REPLACEMENT_FAILED
            fgl_context = FindGoodLocationContext(starting_location=target.location, object_footprints=[self.new_object.get_footprint(0)], ignored_object_ids=[target.id], search_flags=placement.FGLSearchFlag.STAY_IN_CONNECTED_CONNECTIVITY_GROUP | placement.FGLSearchFlag.CALCULATE_RESULT_TERRAIN_HEIGHTS | placement.FGLSearchFlag.DONE_ON_MAX_RESULTS)
            (new_position, new_orientation) = placement.find_good_location(fgl_context)
            if new_position is None or new_orientation is None:
                logger.warn('No good location found for the object {} attempting to replace object {}.', self.new_object, target, owner='tastle')
                return self.RESULT_REPLACEMENT_FAILED
            new_location = sims4.math.Location(sims4.math.Transform(new_position, new_orientation), target.routing_surface)
        created_obj = objects.system.create_object(self.new_object)
        if created_obj is None:
            logger.error('State change attempted to replace object {} with a new object {}, but failed to create the new object.', target, self.definition, owner='tastle')
            return self.RESULT_REPLACEMENT_FAILED
        created_obj.set_location(new_location)
        if self.destroy_original_object:
            if target.in_use:
                target.transient = True
            else:
                target.destroy(source=self, cause='Object replacement state operation')
        return self.RESULT_OBJECT_DESTROYED

class ValueIncreaseFactory(AutoFactoryInit, HasTunableFactory):
    __qualname__ = 'ValueIncreaseFactory'
    FACTORY_TUNABLES = {'apply_depreciation': Tunable(description='\n                Whether or not to apply initial depreciation when\n                this value change is applied.\n                \n                Example: if you are replacing an object that is\n                burned we want to make the value worth the full\n                value of the object again, but you also need to\n                apply the initial depreciation as if it was \n                purchased from buy mode.\n                ', tunable_type=bool, default=False)}

    def apply_new_value(self, target, value_change):
        initial_value = target.current_value
        return initial_value - target.current_value

    def restore_value(self, target, value_change):
        pass

class ValueDecreaseFactory(AutoFactoryInit, HasTunableFactory):
    __qualname__ = 'ValueDecreaseFactory'
    FACTORY_TUNABLES = {'covered_by_insurance': Tunable(description="\n            If checked it means that the user will be awarded an insurance\n            payment for the value lost. Currently this only happens with\n            fire insurance and there is seperate tuning in the fire service\n            for how much of the reduction is awarded as part of the insurance.\n            \n            NOTE: There is a tunable percent of the value that get's tuned here\n            that actually gets added to the insurance tally. That tuning\n            exists on services.fire_service. The name of the tunable is\n            Fire Insurance Claim Percentage.                     \n            ", tunable_type=bool, default=True)}

    def apply_new_value(self, target, value_change):
        new_value = target.current_value - value_change
        target_value = 0 if new_value <= 0 else sims4.math.ceil(new_value)
        delta = target.current_value - target_value
        target.current_value = target_value
        if self.covered_by_insurance:
            services.get_fire_service().increment_insurance_claim(delta, target)
        return delta

    def restore_value(self, target, value_change):
        if self.covered_by_insurance:
            services.get_fire_service().increment_insurance_claim(-value_change, target)

class ObjectValueChangeOperation(HasTunableFactory, AutoFactoryInit):
    __qualname__ = 'ObjectValueChangeOperation'
    FACTORY_TUNABLES = {'value_change_type': TunableVariant(decrease_value=ValueDecreaseFactory.TunableFactory(), increase_value=ValueIncreaseFactory.TunableFactory(), default='decrease_value'), 'change_percentage': TunablePercent(description='\n            A percentage of the catalog value to modify the current value of \n            the target. It will either decrease or increase the value of the \n            object based on the setting of reduce_value.\n            ', default=100)}

    def __init__(self, target, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._target = target
        self._delta = 0

    def _value_change(self):
        target = self._target
        initial_value = target.current_value
        if target.has_component(CRAFTING_COMPONENT):
            process = target.get_crafting_process()
            if process.crafted_value is not None:
                initial_value = process.crafted_value
        return initial_value*self.change_percentage

    def start(self):
        self._delta = self.value_change_type().apply_new_value(self._target, self._value_change())

    def stop(self, *_, **__):
        self.value_change_type().restore_value(self._target, self._delta)

    @property
    def delta(self):
        return self._delta

class StateComponentManagedDistributables:
    __qualname__ = 'StateComponentManagedDistributables'

    def __init__(self):
        self._distributables_map = {}

    def cleanup(self):
        while self._distributables_map:
            (state, distributable) = self._distributables_map.popitem()
            logger.debug('Cleanup: {}', state)
            distributable.stop(immediate=True)

    def apply(self, target, attr_name, state, state_value, attr_value, immediate=False):
        if state.overridden_by is not None:
            distributable_key = (attr_name, state.overridden_by)
        else:
            distributable_key = (attr_name, state)
        if distributable_key in self._distributables_map:
            self._distributables_map[distributable_key].stop(immediate=immediate)
            del self._distributables_map[distributable_key]
        if attr_value is not None:
            distributable = attr_value(target)
            logger.debug('    {} = {}', attr_name, distributable)
            if isinstance(distributable, Result):
                return distributable
            if isinstance(distributable, NeedsStateValue):
                distributable.set_state_value(state_value)
            in_inventory = target.is_in_inventory()
            if not in_inventory or attr_name not in StateChangeOperation.INVENTORY_AFFECTED_DISTRIBUTABLES:
                distributable.start()
            self._distributables_map[distributable_key] = distributable
        else:
            logger.debug('    {} = None', attr_name)

    def stop_inventory_distributables(self):
        for (distributable_key, distributable) in self._distributables_map.items():
            (attr_name, _) = distributable_key
            while attr_name in StateChangeOperation.INVENTORY_AFFECTED_DISTRIBUTABLES:
                distributable.stop(immediate=True)

    def restart_inventory_distributables(self):
        for (distributable_key, distributable) in self._distributables_map.items():
            (attr_name, _) = distributable_key
            while attr_name in StateChangeOperation.INVENTORY_AFFECTED_DISTRIBUTABLES:
                distributable.start()

    def get_distributable(self, attr_name, state):
        distributable_key = (attr_name, state)
        if distributable_key in self._distributables_map:
            return self._distributables_map[distributable_key]

class StateChangeOperation(HasTunableSingletonFactory):
    __qualname__ = 'StateChangeOperation'
    VFX_STATE = 'vfx_state'
    AUDIO_STATE = 'audio_state'
    AUDIO_EFFECT_STATE = 'audio_effect_state'
    AUTONOMY_MODIFIERS = 'autonomy_modifiers'
    BROADCASTER = 'broadcaster'
    ENVIRONMENT_SCORE = 'environment_score'
    PAINTING_REVEAL_LEVEL = 'painting_reveal_level'
    FLOWING_PUDDLE_ENABLED = 'flowing_puddle_enabled'
    REPLACE_OBJECT = 'replace_object'
    UI_METADATA = 'ui_metadata'
    VIDEO_STATE = 'video_playlist'
    VIDEO_STATE_LOOPING = 'video_playlist_looping'
    DIMMER_STATE = 'light_dimmer'
    LOT_MODIFIERS = 'lot_statistic_modifiers'
    SINGED = 'singed'
    CHANGE_VALUE = 'change_value'
    FACTORY_TUNABLES = {'tint': OptionalTunableClientStateChangeItem(tunable=TunableColorSnippet(description='A tint to apply')), 'opacity': OptionalTunableClientStateChangeItem(tunable=TunableRange(float, 1, 0, 1, description='An opacity to apply')), 'scale': OptionalTunableClientStateChangeItem(tunable=Tunable(float, 1, description='A scale to apply')), 'visibility': OptionalTunableClientStateChangeItem(tunable=TunableVisibilityState(description='A visibility state to apply')), 'geometry_state': OptionalTunableClientStateChangeItem(tunable=TunableGeometryState('geometryStateName', description='A geometry state to apply')), 'material_state': OptionalTunableClientStateChangeItem(tunable=TunableMaterialState(description='A material state to apply')), 'model': OptionalTunableClientStateChangeItem(tunable=TunableModelOrDefault(description='A model state to apply')), 'material_variant': OptionalTunableClientStateChangeItem(tunable=TunableMaterialVariant('materialVariantName', description='A material variant to apply')), 'pregnancy_progress': OptionalTunableClientStateChangeItem(tunable=TunableRange(float, 0, 0, 1, description='A pregnancy progress value to apply')), ENVIRONMENT_SCORE: OptionalTunableClientStateChangeItem(tunable=EnvironmentScoreState.TunableFactory()), PAINTING_REVEAL_LEVEL: OptionalTunableClientStateChangeItem(tunable=TunableRange(description='\n                A painting reveal level to apply.  Smaller values show less of\n                the final painting.  The maximum value fully reveals the\n                painting.\n                ', tunable_type=int, default=PaintingState.REVEAL_LEVEL_MIN, minimum=PaintingState.REVEAL_LEVEL_MIN, maximum=PaintingState.REVEAL_LEVEL_MAX)), FLOWING_PUDDLE_ENABLED: OptionalTunableClientStateChangeItem(tunable=Tunable(bool, False, description='If True, this object will start spawning puddles based on its PuddleSpawningComponentTuning.')), VFX_STATE: OptionalTunableClientStateChangeItem(tunable=OptionalTunable(disabled_name='no_vfx', enabled_name='start_vfx', tunable=TunableVariant(single_effect=PlayEffect.TunableFactory(description='A vfx state to apply'), multiple_effects=PlayMultipleEffects.TunableFactory(), default='single_effect'))), AUDIO_STATE: OptionalTunableClientStateChangeItem(tunable=OptionalTunable(disabled_name='no_audio', enabled_name='start_audio', tunable=TunablePlayAudio(description='An audio state to apply'))), AUDIO_EFFECT_STATE: OptionalTunableClientStateChangeItem(tunable=OptionalTunable(disabled_name='no_audio_effect', enabled_name='start_audio_effect', tunable=ApplyAudioEffect.TunableFactory(), description='A way to apply An audio effect (.effectx) to the object when state changes')), VIDEO_STATE: OptionalTunableClientStateChangeItem(tunable=OptionalTunable(disabled_name='no_video', enabled_name='start_video', tunable=TunableList(TunableResourceKey(None, resource_types=[RESOURCE_TYPE_VP6])))), VIDEO_STATE_LOOPING: OptionalTunableClientStateChangeItem(tunable=OptionalTunable(disabled_name='no_video', enabled_name='start_video', tunable=TunableResourceKey(None, resource_types=[sims4.resources.Types.PLAYLIST]))), 'transient': OptionalTunableClientStateChangeItem(tunable=Tunable(bool, False, description='This is what the objects transient value is set to')), AUTONOMY_MODIFIERS: OptionalTunableClientStateChangeItem(tunable=StatisticModifierList.TunableFactory()), BROADCASTER: OptionalTunableClientStateChangeItem(tunable=OptionalTunable(disabled_name='no_broadcaster', enabled_name='start_broadcaster', tunable=BroadcasterRequest.TunableFactory())), REPLACE_OBJECT: OptionalTunable(disabled_value=UNSET, tunable=ObjectReplacementOperation.TunableFactory()), UI_METADATA: OptionalTunableClientStateChangeItem(tunable=UiMetadataList.TunableFactory()), DIMMER_STATE: OptionalTunableClientStateChangeItem(tunable=TunableRange(float, 0, 0, 1, description='A dimmer value to apply')), LOT_MODIFIERS: OptionalTunableClientStateChangeItem(tunable=LotStatisticModifierList.TunableFactory()), SINGED: OptionalTunableClientStateChangeItem(tunable=Tunable(tunable_type=bool, default=True)), CHANGE_VALUE: OptionalTunable(disabled_value=UNSET, tunable=ObjectValueChangeOperation.TunableFactory())}
    CUSTOM_DISTRIBUTABLE_CHANGES = (AUDIO_EFFECT_STATE, AUDIO_STATE, AUTONOMY_MODIFIERS, BROADCASTER, ENVIRONMENT_SCORE, REPLACE_OBJECT, UI_METADATA, VFX_STATE, LOT_MODIFIERS, CHANGE_VALUE)
    INVENTORY_AFFECTED_DISTRIBUTABLES = (AUDIO_EFFECT_STATE, AUDIO_STATE, VFX_STATE)
    USE_COMPONENT_FOR = {PAINTING_REVEAL_LEVEL: CANVAS_COMPONENT.instance_attr, FLOWING_PUDDLE_ENABLED: FLOWING_PUDDLE_COMPONENT.instance_attr, VIDEO_STATE: VIDEO_COMPONENT.instance_attr, VIDEO_STATE_LOOPING: VIDEO_COMPONENT.instance_attr, DIMMER_STATE: LIGHTING_COMPONENT.instance_attr}

    def __init__(self, **ops_tuning):
        self.ops = ops_tuning

    def apply(self, target, custom_distributables, state, state_value, immediate=False):
        for (attr_name, attr_value) in self.ops.items():
            if attr_value is UNSET:
                pass
            if attr_name in self.CUSTOM_DISTRIBUTABLE_CHANGES:
                result = custom_distributables.apply(target, attr_name, state, state_value, attr_value, immediate=immediate)
                if result is not None and not result:
                    return result
                    if attr_name in self.USE_COMPONENT_FOR:
                        component_name = self.USE_COMPONENT_FOR[attr_name]
                        attr_target = getattr(target, component_name)
                        logger.debug('    {}.{} = {}', component_name, attr_name, attr_value)
                    else:
                        attr_target = target
                        logger.debug('    {} = {}', attr_name, attr_value)
                    while attr_target is not None:
                        setattr(attr_target, attr_name, attr_value)
            else:
                if attr_name in self.USE_COMPONENT_FOR:
                    component_name = self.USE_COMPONENT_FOR[attr_name]
                    attr_target = getattr(target, component_name)
                    logger.debug('    {}.{} = {}', component_name, attr_name, attr_value)
                else:
                    attr_target = target
                    logger.debug('    {} = {}', attr_name, attr_value)
                while attr_target is not None:
                    setattr(attr_target, attr_name, attr_value)
        return True

class ObjectStateMetaclass(TunedInstanceMetaclass):
    __qualname__ = 'ObjectStateMetaclass'

    def __repr__(self):
        return self.__name__

class ObjectStateValue(HasTunableReference, metaclass=ObjectStateMetaclass, manager=get_instance_manager(sims4.resources.Types.OBJECT_STATE)):
    __qualname__ = 'ObjectStateValue'

    class Severity(enum.Int):
        __qualname__ = 'ObjectStateValue.Severity'
        NONE = 0
        OKAY = 1
        DISTRESS = 2
        FAILURE = 3

    INSTANCE_TUNABLES = {'display_name': TunableLocalizedString(), 'display_description': TunableLocalizedString(), 'icon': TunableIcon(), 'severity': TunableEnumEntry(description='\n            The severity of this state.  Used to implement features such as\n            retrieving the most dire condition an object is in.\n            ', tunable_type=Severity, default=Severity.NONE), 'value': TunableVariant(locked_args={'unordered': None}, boolean=Tunable(bool, True), integral=Tunable(int, 0), decimal=Tunable(float, 0)), 'anim_overrides': OptionalTunable(TunableAnimationObjectOverrides(description='\n            Tunable class to contain param/vfx/props overrides\n            ')), 'new_client_state': StateChangeOperation.TunableFactory(description='\n            Operations to perform on any object that ends up at this state\n            value.\n            '), 'allowances': TunableTuple(description='\n            A tuple of allowances for this state.\n            ', allow_in_carry=Tunable(description='\n                If checked, this state can be enabled when this object is being\n                carried, if unchecked, this state can never be enabled when\n                this object is being carried.\n                ', tunable_type=bool, default=True), allow_out_of_carry=Tunable(description='\n                If checked, this state can be enabled when this object is not\n                being carried, if unchecked, this state can never be enabled\n                when this object is not being carried.\n                ', tunable_type=bool, default=True), allow_inside=Tunable(description='\n                If checked, this state can be enabled when this object is\n                inside, if unchecked, this state can never be enabled when this\n                object is inside.\n                ', tunable_type=bool, default=True), allow_outside=Tunable(description='\n                If checked, this state can be enabled when this object is\n                outside, if unchecked, this state can never be enabled when\n                this object is outside.\n                ', tunable_type=bool, default=True), allow_on_natural_ground=Tunable(description='\n                If checked, this state can be enabled when this object is on\n                natural ground, if unchecked, this state can never be enabled\n                when this object is on natural ground.\n                ', tunable_type=bool, default=True), allow_off_natural_ground=Tunable(description='\n                If checked, this state can be enabled when this object is not\n                on natural ground, if unchecked, this state can never be\n                enabled when this object is not on natural ground.\n                ', tunable_type=bool, default=True)), 'buff_weight_multipliers': TunableBuffWeightMultipliers(), 'remove_from_crafting_cache': Tunable(description='\n            If True, this state will cause the object to be removed from the crafting cache.\n            This should be set if you plan to test out crafting interactions while in this \n            state.  For example, when the stove breaks, it is no longer available for the Sim \n            to craft with.  Marking this as True for that state will show all recipes that \n            require the stove as grayed out in the picker.\n            ', tunable_type=bool, default=False)}
    state = None

    @classmethod
    def calculate_autonomy_weight(cls, sim):
        total_weight = 1
        for (buff, weight) in cls.buff_weight_multipliers.items():
            while sim.has_buff(buff):
                total_weight *= weight
        return total_weight

class CommodityBasedObjectStateValue(ObjectStateValue):
    __qualname__ = 'CommodityBasedObjectStateValue'
    REMOVE_INSTANCE_TUNABLES = ('value',)
    INSTANCE_TUNABLES = {'range': TunableInterval(description="\n            The commodity range this state maps to. The ranges between the commodity\n            values must have some overlap in order for the state to transition properly.\n            For instance, let's say you have two states, DIRTY and CLEAN. If you set the\n            DIRTY state to have a range between 0 and 20, and you set CLEAN state to have\n            a range of 21 to 100, the states will not change properly because of the void\n            created (between 20 and 21). At the very least, the lower bounds of one needs\n            to be the same as the upper bound for the next (i.e. DIRTY from 0 to 20 and\n            CLEAN from 20 to 100).\n            ", tunable_type=float, default_lower=0, default_upper=0), 'default_value': OptionalTunable(Tunable(description='\n                default commodity value when set to this state.\n                If disabled use average of range', tunable_type=float, default=0), disabled_name='use_range_average', enabled_name='use_default_value')}

    @classmethod
    def _tuning_loaded_callback(cls):
        value = (cls.range.lower_bound + cls.range.upper_bound)/2
        if cls.default_value is None:
            cls.value = value
        else:
            cls.value = cls.default_value
        ninety_percent_interval = 0.9*(cls.range.upper_bound - cls.range.lower_bound)
        cls.low_value = value - ninety_percent_interval/2
        cls.high_value = value + ninety_percent_interval/2

class ChannelBasedObjectStateValue(ObjectStateValue):
    __qualname__ = 'ChannelBasedObjectStateValue'
    INSTANCE_SUBCLASSES_ONLY = True
    INSTANCE_TUNABLES = {'show_in_picker': Tunable(bool, True, description='If True than this channel will not be displayed to be chosen in the channel picker dialog.')}

    @classmethod
    def activate_channel(cls, *args, **kwargs):
        raise NotImplementedError

    @classmethod
    def test_channel(cls, target, context):
        raise NotImplementedError

class VideoChannel(ChannelBasedObjectStateValue):
    __qualname__ = 'VideoChannel'
    INSTANCE_TUNABLES = {'affordance': TunableReference(services.get_instance_manager(sims4.resources.Types.INTERACTION))}

    @classmethod
    def activate_channel(cls, interaction=None, push_affordances=True):
        if not push_affordances:
            return
        if not cls.affordance:
            return
        target_object = interaction.target
        push_affordance = interaction.generate_continuation_affordance(cls.affordance)
        context = interaction.context.clone_for_continuation(interaction)
        for aop in push_affordance.potential_interactions(target_object, context):
            aop.test_and_execute(context)

    @classmethod
    def test_channel(cls, target, context):
        return cls.affordance.test(target=target, context=context)

class AudioChannel(ChannelBasedObjectStateValue):
    __qualname__ = 'AudioChannel'
    INSTANCE_TUNABLES = {'listen_affordance': TunableReference(services.get_instance_manager(sims4.resources.Types.INTERACTION))}

    @classmethod
    def activate_channel(cls, interaction=None, push_affordances=False, **kwargs):
        if push_affordances:
            cls.push_listen_affordance(interaction, interaction.context)
        elif interaction.target is not None and interaction.target.get_state(cls.state).value != cls.value:
            interaction.target.set_state(cls.state, cls)

    @classmethod
    def push_listen_affordance(cls, interaction, context):
        if cls.listen_affordance is not None:
            listen_affordance = interaction.generate_continuation_affordance(cls.listen_affordance)
            for aop in listen_affordance.potential_interactions(interaction.target, context):
                aop.test_and_execute(context)

    @classmethod
    def on_interaction_canceled_from_state_change(cls, interaction):
        continuation_context = interaction.context.clone_for_continuation(interaction)
        cls.push_listen_affordance(interaction, continuation_context)

    @classmethod
    def test_channel(cls, target, context):
        return cls.listen_affordance.test(target=target, context=context)

class TunableStateValueReference(TunableReference):
    __qualname__ = 'TunableStateValueReference'

    def __init__(self, class_restrictions=DEFAULT, **kwargs):
        if class_restrictions is DEFAULT:
            class_restrictions = ObjectStateValue
        super().__init__(manager=get_instance_manager(sims4.resources.Types.OBJECT_STATE), class_restrictions=class_restrictions, **kwargs)

class TestedStateValueReference(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'TestedStateValueReference'
    FACTORY_TUNABLES = {'tested_states': TunableList(description='\n            The first test that passes will have its state applied.\n            ', tunable=TunableTuple(tests=event_testing.tests.TunableTestSet(), state=TunableStateValueReference())), 'fallback_state': OptionalTunable(description='\n            If all tests fail, this state will be applied.\n            ', tunable=TunableStateValueReference())}

class ObjectState(HasTunableReference, metaclass=ObjectStateMetaclass, manager=get_instance_manager(sims4.resources.Types.OBJECT_STATE)):
    __qualname__ = 'ObjectState'
    INSTANCE_TUNABLES = {'display_name': TunableLocalizedString(), 'display_description': TunableLocalizedString(), 'icon': TunableIcon(), 'overridden_by': OptionalTunable(TunableReference(manager=get_instance_manager(sims4.resources.Types.OBJECT_STATE), class_restrictions='ObjectState')), '_values': TunableList(TunableStateValueReference(reload_dependent=True))}
    _sorted_values = None
    linked_stat = None
    lot_based = None

    @classproperty
    def values(cls):
        if cls._sorted_values is None:
            sorted_values = []
            ordered = True
            for value in cls._values:
                if value.value is None:
                    ordered = False
                sorted_values.append(value)
            if ordered:
                sorted_values.sort(key=lambda value: value.value)
            cls._sorted_values = sorted_values
        return cls._sorted_values

    @classmethod
    def _tuning_loaded_callback(cls):
        for value in cls._values:
            value.state = cls

class CommodityBasedObjectState(ObjectState):
    __qualname__ = 'CommodityBasedObjectState'
    INSTANCE_TUNABLES = {'linked_stat': TunableReference(get_instance_manager(sims4.resources.Types.STATISTIC), description='The statistic to link to the state.'), '_values': TunableList(TunableStateValueReference(class_restrictions=CommodityBasedObjectStateValue)), 'lot_based': Tunable(description='\n            whether the state should check the linked stat on the active lot instead of on the object itself\n            ', tunable_type=bool, default=False)}

    @classmethod
    def get_value(cls, statistic_value):
        for state_value in cls._values:
            while statistic_value >= state_value.range.lower_bound:
                upper_bound = state_value.range.upper_bound
                if upper_bound == cls.linked_stat.max_value:
                    statisfy_upper = statistic_value <= upper_bound
                else:
                    statisfy_upper = statistic_value < upper_bound
                if statisfy_upper:
                    return state_value

class TunableStateTypeReference(TunableReference):
    __qualname__ = 'TunableStateTypeReference'

    def __init__(self, class_restrictions=DEFAULT, **kwargs):
        if class_restrictions is DEFAULT:
            class_restrictions = ObjectState
        super().__init__(manager=get_instance_manager(sims4.resources.Types.OBJECT_STATE), class_restrictions=class_restrictions, **kwargs)

StateTriggerChanceKey = namedtuple('StateTriggerChanceKey', ['at_state', 'set_state'])

class StateComponent(Component, component_name=STATE_COMPONENT, persistence_key=protocols.PersistenceMaster.PersistableData.StateComponent, persistence_priority=20):
    __qualname__ = 'StateComponent'
    BROKEN_STATE_SET = TunableSet(description='\n        A set of state values that an object can be considered as broken (not usable) in the game.\n        ', tunable=TunableStateValueReference())
    _on_state_changed = None

    def __init__(self, owner, *, states, state_triggers, unique_state_changes, delinquency_state_changes):
        super().__init__(owner)
        self._states = {}
        self._state_reset_values = {}
        self._state_reset_if_time_passes_values = {}
        self._commodity_states = {}
        self._client_states = {}
        self._tested_states_on_add = {}
        self._stat_listeners = collections.defaultdict(list)
        self._state_triggers = state_triggers
        self._custom_distributables = StateComponentManagedDistributables()
        self._state_trigger_enabled = True
        self._unique_state_changes = unique_state_changes
        self._delinquency_state_changes = delinquency_state_changes
        self.states_before_delinquency = []
        if unique_state_changes is not None:
            self._verify_unique_state_changes()
        for state_info in states:
            default_value = state_info.default_value
            if default_value is not None and not isinstance(default_value, ObjectStateMetaclass):
                default_value = random.choice(default_value)
            state = default_value.state
            self._states[state] = default_value
            if state_info.reset_to_default:
                self._state_reset_values[state] = default_value
            if state_info.reset_on_load_if_time_passes:
                self._state_reset_if_time_passes_values[state] = default_value
            self._client_states[state] = state_info.client_states
            if state_info.tested_states_on_add is not None:
                self._tested_states_on_add[state] = state_info.tested_states_on_add
            while state.linked_stat is not None:
                self._commodity_states[state.linked_stat] = state

    def on_add(self):
        self._apply_tested_states()

    def on_finalize_load(self):
        self._apply_tested_states()

    def _apply_tested_states(self):
        resolver = SingleObjectResolver(self.owner)
        for (state, value) in self._tested_states_on_add.items():
            test_passed = False
            for tested_state in value.tested_states:
                while tested_state.tests.run_tests(resolver):
                    self.set_state(state, tested_state.state)
                    test_passed = True
                    break
            while not test_passed and value.fallback_state is not None:
                self.set_state(state, value.fallback_state)

    def _get_tracker(self, state):
        if state.lot_based:
            current_zone = services.current_zone()
            lot = current_zone.lot
            return lot.get_tracker(state.linked_stat)
        return self.owner.get_tracker(state.linked_stat)

    def pre_add(self, *_, **__):
        for (state, value) in self.items():
            if state.linked_stat is not None:
                tracker = self._get_tracker(state)
                linked_stat = tracker.get_statistic(state.linked_stat)
            else:
                linked_stat = None
            if linked_stat is not None and linked_stat.use_stat_value_on_initialization:
                self._set_state_from_stat(state, linked_stat, preferred_value=value, force_update=True)
            else:
                self.set_state(state, value, from_init=True)

    def on_remove_from_client(self, *_, **__):
        self._cleanup_client_state()

    def on_remove(self, *_, **__):
        self._cleanup_client_state()
        for state in self._commodity_states.values():
            stat_listeners = self._stat_listeners.get(state)
            while stat_listeners is not None:
                tracker = self._get_tracker(state)
                while True:
                    for listener in stat_listeners:
                        tracker.remove_listener(listener)
        self._stat_listeners.clear()

    def on_post_load(self, *_, **__):
        for (state, value) in self.items():
            self._trigger_on_state_changed(state, value, value)

    def component_reset(self, reset_reason):
        if reset_reason == ResetReason.BEING_DESTROYED:
            return
        if not self.owner.valid_for_distribution:
            return
        for (state, value) in self.items():
            new_value = self._state_reset_values.get(state, value)
            self._trigger_on_state_changed(state, value, new_value)

    def pre_parent_change(self, parent):
        if self.enter_carry_state is None and parent is not None and parent.is_sim:
            for value in self.values():
                while not value.allowances.allow_in_carry:
                    logger.error('Attempting to pick up object {} when its current state value {} is not compatible with carry.', self, value, owner='tastle')
        elif self.exit_carry_state is None and (parent is None or not parent.is_sim):
            for value in self.values():
                while not value.allowances.allow_out_of_carry:
                    logger.error('Attempting to put down object {} when its current state value {} is not compatible with put down.', self, value, owner='tastle')

    def on_parent_change(self, parent):
        if parent is not None and parent.is_sim:
            enter_carry_state = self.enter_carry_state
            if enter_carry_state is not None:
                self.set_state(enter_carry_state.state, enter_carry_state)
        elif parent is None or not parent.is_sim:
            exit_carry_state = self.exit_carry_state
            if exit_carry_state is not None:
                self.set_state(exit_carry_state.state, exit_carry_state)

    def _set_placed_outside(self):
        outside_placement_state = self.outside_placement_state
        if outside_placement_state is not None:
            self.set_state(outside_placement_state.state, outside_placement_state)

    def _set_placed_inside(self):
        inside_placement_state = self.inside_placement_state
        if inside_placement_state is not None:
            self.set_state(inside_placement_state.state, inside_placement_state)

    def _set_placed_on_natural_ground(self):
        on_natural_ground_placement_state = self.on_natural_ground_placement_state
        if on_natural_ground_placement_state is not None:
            self.set_state(on_natural_ground_placement_state.state, on_natural_ground_placement_state)

    def _set_placed_off_natural_ground(self):
        off_natural_ground_placement_state = self.off_natural_ground_placement_state
        if off_natural_ground_placement_state is not None:
            self.set_state(off_natural_ground_placement_state.state, off_natural_ground_placement_state)

    def on_added_to_inventory(self):
        self._custom_distributables.stop_inventory_distributables()

    def on_removed_from_inventory(self):
        self._custom_distributables.restart_inventory_distributables()

    @componentmethod
    def add_state_changed_callback(self, callback):
        if not self._on_state_changed:
            self._on_state_changed = CallableList()
        self._on_state_changed.append(callback)

    @componentmethod
    def remove_state_changed_callback(self, callback):
        self._on_state_changed.remove(callback)
        if not self._on_state_changed:
            del self._on_state_changed

    @property
    def enter_carry_state(self):
        if self._unique_state_changes is not None:
            return self._unique_state_changes.enter_carry_state

    @property
    def exit_carry_state(self):
        if self._unique_state_changes is not None:
            return self._unique_state_changes.exit_carry_state

    @property
    def outside_placement_state(self):
        if self._unique_state_changes is not None:
            return self._unique_state_changes.outside_placement_state

    @property
    def inside_placement_state(self):
        if self._unique_state_changes is not None:
            return self._unique_state_changes.inside_placement_state

    @property
    def on_natural_ground_placement_state(self):
        if self._unique_state_changes is not None:
            return self._unique_state_changes.on_natural_ground_placement_state

    @property
    def off_natural_ground_placement_state(self):
        if self._unique_state_changes is not None:
            return self._unique_state_changes.off_natural_ground_placement_state

    @property
    def delinquency_state_changes(self):
        return self._delinquency_state_changes

    def keys(self):
        return self._states.keys()

    def items(self):
        return self._states.items()

    def values(self):
        return self._states.values()

    @componentmethod
    def get_client_states(self, state):
        return self._client_states[state].keys()

    @componentmethod_with_fallback(lambda state: False)
    def has_state(self, state):
        return state in self._states

    @componentmethod
    def state_value_active(self, state_value):
        return state_value in self._states.values()

    @componentmethod
    def get_state(self, state):
        return self._states[state]

    @componentmethod
    def does_state_reset_on_load(self, state):
        return state in self._state_reset_if_time_passes_values

    @componentmethod
    def copy_state_values(self, other_object, state_list=DEFAULT):
        if other_object.has_component(STATE_COMPONENT):
            state_list = self._states.keys() if state_list is DEFAULT else state_list
            for state in list(state_list):
                while other_object.has_state(state):
                    state_value = other_object.get_state(state)
                    self.set_state(state, state_value)

    @componentmethod
    def is_object_usable(self):
        for state_value in StateComponent.BROKEN_STATE_SET:
            while self.state_value_active(state_value):
                return False
        return True

    def _verify_unique_state_changes(self):
        enter_carry_state = self.enter_carry_state
        exit_carry_state = self.exit_carry_state
        outside_placement_state = self.outside_placement_state
        inside_placement_state = self.inside_placement_state
        on_natural_ground_placement_state = self.on_natural_ground_placement_state
        off_natural_ground_placement_state = self.off_natural_ground_placement_state
        if not (enter_carry_state is not None and enter_carry_state.allowances.allow_in_carry):
            logger.error('Attempting to set enter_carry_state for {} to state value {} which is not compatible with carry. Please fix in tuning.', self.owner, enter_carry_state, owner='tastle')
            self._unique_state_changes.enter_carry_state = None
        if not (exit_carry_state is not None and exit_carry_state.allowances.allow_out_of_carry):
            logger.error('Attempting to set exit_carry_state for {} to state value {} which is not compatible with carry. Please fix in tuning.', self.owner, exit_carry_state, owner='tastle')
            self._unique_state_changes.exit_carry_state = None
        if not (outside_placement_state is not None and outside_placement_state.allowances.allow_outside):
            logger.error('Attempting to set outside_placement_state for {} to state value {} which is not compatible with outside placement. Please fix in tuning.', self.owner, outside_placement_state, owner='tastle')
            self._unique_state_changes.outside_placement_state = None
        if not (inside_placement_state is not None and inside_placement_state.allowances.allow_inside):
            logger.error('Attempting to set inside_placement_state for {} to state value {} which is not compatible with inside placement. Please fix in tuning.', self.owner, inside_placement_state, owner='tastle')
            self._unique_state_changes.inside_placement_state = None
        if not (on_natural_ground_placement_state is not None and on_natural_ground_placement_state.allowances.allow_on_natural_ground):
            logger.error('Attempting to set on_natural_ground_placement_state for {} to state value {} which is not compatible with placement on natural ground. Please fix in tuning.', self.owner, on_natural_ground_placement_state, owner='tastle')
            self._unique_state_changes.on_natural_ground_placement_state = None
        if not (off_natural_ground_placement_state is not None and off_natural_ground_placement_state.allowances.allow_off_natural_ground):
            logger.error('Attempting to set off_natural_ground_placement_state for {} to state value {} which is not compatible with placement off of natural ground. Please fix in tuning.', self.owner, off_natural_ground_placement_state, owner='tastle')
            self._unique_state_changes.off_natural_ground_placement_state = None

    def _check_allowances(self, new_value):
        if self.owner.manager is None:
            return True
        owner_parent = self.owner.parent
        if new_value.allowances.allow_in_carry or owner_parent is not None and owner_parent.is_sim:
            logger.error('Attempting to set the state of object {}, currently being carried by {} to state value {}, which is not allowed to be set during carry.', self.owner, owner_parent, new_value, owner='tastle')
            return False
        if new_value.allowances.allow_out_of_carry or owner_parent is None:
            logger.error('Attempting to set the state of object {}, currently not being carried to state value {}, which is not allowed to be set outside of carry.', self.owner, new_value, owner='tastle')
            return False
        is_outside = self.owner.is_outside
        if new_value.allowances.allow_outside or is_outside and is_outside is not None:
            logger.error('Attempting to set the state of object {}, currently outside to state value {}, which is not allowed to be set outside.', self.owner, new_value, owner='tastle')
            return False
        if new_value.allowances.allow_inside or not is_outside and is_outside is not None:
            logger.error('Attempting to set the state of object {}, currently inside to state value {}, which is not allowed to be set inside.', self.owner, new_value, owner='tastle')
            return False
        is_on_natural_ground = self.owner.is_on_natural_ground()
        if is_on_natural_ground is None:
            return True
        if new_value.allowances.allow_on_natural_ground or is_on_natural_ground and is_on_natural_ground is not None:
            logger.error('Attempting to set the state of object {}, currently on natural ground to state value {}, which is not allowed to be set on natural ground.', self.owner, new_value, owner='tastle')
            return False
        if new_value.allowances.allow_off_natural_ground or not is_on_natural_ground and is_on_natural_ground is not None:
            logger.error('Attempting to set the state of object {}, currently not on natural ground to state value {}, which is not allowed to be set when not on natural ground.', self.owner, new_value, owner='tastle')
            return False
        return True

    @componentmethod
    def set_state(self, state, new_value, from_stat=False, from_init=False, immediate=False, force_update=False):
        if not self._check_allowances(new_value):
            return
        if state not in self._states:
            logger.error("Attempting to set the value of the '{}' state on object {}, but the object's definition ({}) isn't tuned to have that state.", state.__name__, self.owner, self.owner.definition.name)
            return
        old_value = self._states[state]
        if new_value == old_value and not force_update:
            return
        if from_init or new_value != old_value:
            current_zone_id = sims4.zone_utils.get_zone_id(can_be_none=True)
            if current_zone_id is not None:
                services.get_event_manager().process_events_for_household(test_events.TestEvent.ObjectStateChange, household=services.owning_household_of_active_lot(), custom_keys=(new_value,))
        logger.debug('State change: {} -> {} ({})', old_value, new_value, 'from_init' if from_init else 'from_stat' if from_stat else 'normal')
        self._states[state] = new_value
        if not from_stat or from_init:
            self._set_stat_to_value(state, new_value)
        self._trigger_on_state_changed(state, old_value, new_value, immediate=immediate)
        caches.clear_all_caches()

    @componentmethod
    def get_most_severe_state_value(self):
        options = [(value.severity, value.__name__, value) for value in self._states.values() if value.severity]
        options.sort()
        if options:
            return options[-1][2]

    @componentmethod
    def get_state_value_from_stat_type(self, stat_type):
        for (state, value) in self.items():
            linked_stat = getattr(state, 'linked_stat', None)
            while linked_stat is not None and linked_stat is stat_type:
                return value

    @property
    def state_trigger_enabled(self):
        return self._state_trigger_enabled

    @state_trigger_enabled.setter
    def state_trigger_enabled(self, value):
        self._state_trigger_enabled = value

    def _trigger_on_state_changed(self, state, old_value, new_value, immediate=False):
        if not self._apply_client_state(state, new_value, immediate=immediate):
            return
        owner_id = self.owner.id
        in_inventory = self.owner.is_in_inventory()
        self._add_stat_listener(state, new_value)
        self.owner.on_state_changed(state, old_value, new_value)
        if in_inventory and owner_id not in services.inventory_manager():
            return
        if not in_inventory and owner_id not in services.object_manager():
            return
        if self._on_state_changed:
            self._on_state_changed(self.owner, state, old_value, new_value)
        if self._state_trigger_enabled:
            for state_trigger in self._state_triggers:
                state_trigger().trigger_state(self.owner, new_value, immediate=immediate)

    def _get_values_for_state(self, state):
        if state in self._states:
            return state.values

    def _add_stat_listener(self, state, new_value):
        stat_type = state.linked_stat
        if stat_type in self._commodity_states:
            value_list = self._get_values_for_state(state)
            tracker = self._get_tracker(state)
            if not tracker.has_statistic(stat_type):
                tracker.add_statistic(stat_type)
            stat_listeners = self._stat_listeners[state]
            if stat_listeners:
                for listener in stat_listeners:
                    tracker.remove_listener(listener)
                del stat_listeners[:]
            lower_value = None
            upper_value = None
            value_index = value_list.index(new_value)
            if value_index > 0:
                lower_value = value_list[value_index - 1]
            if value_index < len(value_list) - 1:
                upper_value = value_list[value_index + 1]

            def add_listener(preferred_value, threshold):
                listener = None

                def callback(stat_type):
                    if listener is not None:
                        tracker.remove_listener(listener)
                        if listener in stat_listeners:
                            stat_listeners.remove(listener)
                    self._set_state_from_stat(state, stat_type, preferred_value=preferred_value)

                listener = tracker.create_and_activate_listener(stat_type, threshold, callback)
                stat_listeners.append(listener)

            if lower_value is not None:
                threshold = sims4.math.Threshold()
                threshold.value = new_value.range.lower_bound
                threshold.comparison = operator.lt
                add_listener(lower_value, threshold)
            if upper_value is not None:
                threshold = sims4.math.Threshold()
                threshold.value = new_value.range.upper_bound
                threshold.comparison = operator.gt
                add_listener(upper_value, threshold)

    def _set_stat_to_value(self, state, state_value):
        stat_type = state.linked_stat
        if stat_type in self._commodity_states:
            tracker = self._get_tracker(state)
            tracker.set_value(stat_type, state_value.value, add=True)
            return True

    @staticmethod
    def get_state_from_stat(obj, state, stat=DEFAULT, preferred_value=None):
        if stat is DEFAULT:
            stat = state.linked_stat
        stat_type = stat.stat_type
        tracker = obj.get_tracker(stat_type)
        stat_value = tracker.get_value(stat_type)
        min_d = MAX_FLOAT
        new_value = None
        for value in state.values:
            while value.range.lower_bound <= stat_value <= value.range.upper_bound:
                if value is preferred_value:
                    new_value = value
                    break
                d = abs(stat_value - value.value)
                if d < min_d:
                    min_d = d
                    new_value = value
        if new_value is None:
            for value in state.values:
                d = abs(stat_value - value.value)
                while d < min_d:
                    min_d = d
                    new_value = value
            logger.warn("{}: State values don't have full coverage of the commodity range. {} has no corresponding state value.  Falling back to closest option, {}.", state, stat_value, new_value)
        return new_value

    @staticmethod
    def set_stat_from_state(obj, value):
        stat = value.state.linked_stat
        tracker = obj.get_tracker(stat)
        tracker.set_value(stat, value.value)

    def _set_state_from_stat(self, state, stat, preferred_value=None, from_init=False, **kwargs):
        if state.lot_based:
            current_zone = services.current_zone()
            target = current_zone.lot
        else:
            target = self.owner
        new_value = self.get_state_from_stat(target, state, stat, preferred_value)
        if new_value is None:
            tracker = self._get_tracker(state)
            stat_value = tracker.get_value(stat)
            logger.warn('Statistic change {} with value {} does not correspond to a {} state', stat, stat_value, state)
        logger.debug('Statistic change triggering state change: {} --> {}', stat, new_value)
        self.set_state(state, new_value, from_stat=True, from_init=from_init, **kwargs)

    def _client_states_gen(self, value):
        yield value.new_client_state
        if value.state in self._client_states:
            client_states_for_state = self._client_states[value.state]
            if value in client_states_for_state:
                new_client_state = client_states_for_state[value]
                if new_client_state is not None:
                    yield new_client_state

    @componentmethod
    def get_component_managed_state_distributable(self, attr_name, state):
        return self._custom_distributables.get_distributable(attr_name, state)

    def _apply_client_state(self, state, value, immediate=False):
        for new_client_state in self._client_states_gen(value):
            result = new_client_state.apply(self.owner, self._custom_distributables, state, value, immediate=immediate)
            while not result:
                return result
        if state.overridden_by is not None and self.has_state(state.overridden_by):
            self._apply_client_state(state.overridden_by, self.get_state(state.overridden_by), immediate=immediate)
        return True

    def _cleanup_client_state(self):
        self._custom_distributables.cleanup()

    def component_anim_overrides_gen(self):
        sorted_state_list = topological_sort(self.keys(), lambda e: (e.overridden_by,))
        for state in sorted_state_list:
            state_value = self.get_state(state)
            while state_value.anim_overrides is not None:
                yield state_value.anim_overrides

    def reapply_value_changes(self):
        owner = self.owner
        owner.current_value = owner.catalog_value
        if owner.has_component(CRAFTING_COMPONENT):
            process = owner.get_crafting_process()
            if process.crafted_value is not None:
                owner.current_value = process.crafted_value
        for state in self.keys():
            distributeable = self._custom_distributables.get_distributable('change_value', state)
            while distributeable is not None:
                distributeable.start()

    def _save_state_data(self):
        states_data = []
        states_before_delinquency_data = []

        def save_state_and_value(state, value):
            save = protocols.StateComponentState()
            new_value = self._state_reset_if_time_passes_values.get(state, value)
            save.state_name_hash = state.guid64
            save.value_name_hash = new_value.guid64
            return save

        for (state, value) in self._states.items():
            save = save_state_and_value(state, value)
            states_data.append(save)
            logger.info('[PERSISTENCE]: state {}({}).', state, value)
        for state in self.states_before_delinquency:
            save = save_state_and_value(state.state, state)
            states_before_delinquency_data.append(save)
            logger.info('[PERSISTENCE]: state before delinquency{}({}).', state.state, state)
        return (states_data, states_before_delinquency_data)

    def save(self, persistence_master_message):
        persistable_data = protocols.PersistenceMaster.PersistableData()
        persistable_data.type = protocols.PersistenceMaster.PersistableData.StateComponent
        state_save = persistable_data.Extensions[protocols.PersistableStateComponent.persistable_data]
        logger.info('[PERSISTENCE]: ----Start saving state component of {0}.', self.owner)
        (states_data, states_before_delinquency_data) = self._save_state_data()
        state_save.states.extend(states_data)
        state_save.states_before_delinquency.extend(states_before_delinquency_data)
        persistence_master_message.data.extend([persistable_data])
        logger.info('[PERSISTENCE]: ----End saving state component of {0}.', self.owner)

    def load(self, state_component_message):
        state_component_data = state_component_message.Extensions[protocols.PersistableStateComponent.persistable_data]
        logger.info('[PERSISTENCE]: ----Start loading state component of {0}.', self.owner)

        def load_state_and_value(state_info):
            object_state_manager = get_instance_manager(sims4.resources.Types.OBJECT_STATE)
            state = object_state_manager.get(state_info.state_name_hash)
            if state is None:
                logger.warn('Attempting to load an invalid state component state on {0}. Did tuning change?', self.owner)
                return (None, None)
            value = object_state_manager.get(state_info.value_name_hash)
            if value is None:
                logger.warn("Attempting to load an invalid object state value on {0}. Likely means out of date tuning was persisted. Leaving state '{1}' set to default.", self.owner, state.__name__)
                return (None, None)
            if state not in self._states:
                logger.warn("Loading a state that is valid but not part of the Object Component. Likely means out dated tuning for {0}'s state component was persisted.", self.owner)
                return (None, None)
            return (state, value)

        for state_info in state_component_data.states:
            (state, value) = load_state_and_value(state_info)
            if state is None or value is None:
                return
            logger.info('[PERSISTENCE]: {}({}).', state, value)
            self.set_state(state, value)
        for state_info in state_component_data.states_before_delinquency:
            (state, value) = load_state_and_value(state_info)
            if state is None or value is None:
                return
            logger.info('[PERSISTENCE]: {}({}).', state, value)
            self.states_before_delinquency.append(value)
        logger.info('[PERSISTENCE]: ----End loading state component of {0}.', self.owner)

class StateTriggerOperation(enum.Int):
    __qualname__ = 'StateTriggerOperation'
    AND = 0
    OR = 1
    NONE = 2

class StateTrigger(HasTunableFactory):
    __qualname__ = 'StateTrigger'
    FACTORY_TUNABLES = {'set_state': TunableStateValueReference(), 'at_states': TunableList(TunableStateValueReference()), 'set_random_state': OptionalTunable(description='\n            If enabled it will trigger a random state value out of the possible\n            weighted list.\n            This can be combined with set_state so either or both of them \n            can apply on a state triggered. \n            If a chance of nothing happening is desired you can tune an empty \n            field on the trigger_random_state list. \n            ', tunable=TunableList(description='\n                List of weighted states to be triggered.\n                ', tunable=TunableTuple(description='\n                    Pairs of states and weights to be randomly selected.\n                    ', weight=Tunable(description='\n                        ', tunable_type=int, default=1), state_value=TunableStateValueReference())), disabled_name='No_random_states', enabled_name='Trigger_random_state'), 'trigger_operation': TunableEnumEntry(description='\n            The operation to apply on the at_states to decide if we can trigger\n            the at_state. \n            AND:  trigger the new state only if the object is in all the listed \n                  states at the same time. \n            OR:   trigger the new state if the object is in any of the listed \n                  states. \n            NONE: trigger the new state only if the object is in none of the \n                  listed states.\n            ', tunable_type=StateTriggerOperation, default=StateTriggerOperation.AND), 'trigger_chance': OptionalTunable(TunableRange(description='\n                The chance to trigger the target state when we reach the at_state.', tunable_type=float, default=100, minimum=0, maximum=100))}

    def __init__(self, set_state, at_states, set_random_state, trigger_operation, trigger_chance=None):
        self._set_state = set_state
        self._at_states = at_states
        self._set_random_state = set_random_state
        self._trigger_operation = trigger_operation
        self._trigger_chance = trigger_chance

    def trigger_state(self, owner, at_state, immediate=False):
        if at_state is self._set_state:
            return
        if owner.state_value_active(self._set_state):
            return
        if self._check_triggerable(owner, at_state) and self._check_chance():
            if self._set_state:
                logger.debug('TriggerState: {}, from {}', self._set_state, at_state)
                owner.set_state(self._set_state.state, self._set_state, immediate=immediate)
            if self._set_random_state:
                weight_pairs = [(data.weight, data.state_value) for data in self._set_random_state]
                random_state_value = weighted_random_item(weight_pairs)
                if random_state_value:
                    owner.set_state(random_state_value.state, random_state_value, immediate=immediate)

    def _check_triggerable(self, owner, at_state):
        if self._trigger_operation == StateTriggerOperation.AND:
            return self._check_and(owner, at_state)
        if self._trigger_operation == StateTriggerOperation.OR:
            return self._check_or(owner, at_state)
        if self._trigger_operation == StateTriggerOperation.NONE:
            return self._check_none(owner, at_state)
        return False

    def _check_and(self, owner, at_state):
        if at_state not in self._at_states:
            return False
        for state_value in self._at_states:
            while not owner.state_value_active(state_value):
                return False
        return True

    def _check_or(self, owner, at_state):
        return at_state in self._at_states

    def _check_none(self, owner, at_state):
        if at_state in self._at_states:
            return False
        for state_value in self._at_states:
            while owner.state_value_active(state_value):
                return False
        return True

    def _check_chance(self):
        if self._trigger_chance is None:
            return True
        return random_chance(self._trigger_chance)

class TunableStateComponent(TunableFactory):
    __qualname__ = 'TunableStateComponent'
    FACTORY_TYPE = StateComponent

    def __init__(self, description='Allow persistent state to be saved for this object.', **kwargs):
        (super().__init__(states=TunableList(description='\n                Supported states for this object\n                ', tunable=TunableTuple(description='\n                    A supported state for this object\n                    ', default_value=TunableVariant(description='\n                        The default value for the state.\n                        ', reference=TunableStateValueReference(), random=TunableList(description='\n                            List of object state values to randomly choose\n                            between as the default for this state.\n                            ', tunable=TunableStateValueReference())), client_states=TunableMapping(description='\n                        A list of client states\n                        ', key_type=TunableStateValueReference(description='A state value'), value_type=StateChangeOperation.TunableFactory()), reset_to_default=Tunable(description='\n                        If checked, when the object is reset, the state will be\n                        reset to the default value. Otherwise, it will keep the\n                        current value.\n                        ', tunable_type=bool, default=False), reset_on_load_if_time_passes=Tunable(description='\n                        If checked then the object is saved with the default\n                        state rather than the current state.  If we want it\n                        to return to this state we need an interaction that\n                        is saved to put it back into it.\n                        ', tunable_type=bool, default=False), tested_states_on_add=OptionalTunable(description="\n                        The first test that passes will have its state applied.\n                        If no tests pass, the fallback state will be applied.\n                        This can be used to conditionally apply a state to an\n                        object.  For example, the Tree Rabbit Hale needs to \n                        default to the open state when it's on the Slyvan Glade\n                        venue.\n                        This runs when the object is added to the world.\n                        ", tunable=TestedStateValueReference.TunableFactory()))), state_triggers=TunableList(StateTrigger.TunableFactory()), unique_state_changes=OptionalTunable(description='\n                Special cases that will cause state changes to occur.\n                ', tunable=TunableTuple(enter_carry_state=TunableStateValueReference(description='\n                        If specified, the object will enter this state when\n                        entering carry.\n                        '), exit_carry_state=TunableStateValueReference(description='\n                        If specified, the object will enter this state when\n                        exiting carry.\n                        '), outside_placement_state=TunableStateValueReference(description='\n                        If specified, the object will enter this state when\n                        being placed outside.\n                        '), inside_placement_state=TunableStateValueReference(description='\n                        If specified, the object will enter this state when\n                        being placed inside.\n                        '), on_natural_ground_placement_state=TunableStateValueReference(description='\n                        If specified, the object will enter this state when\n                        being placed on natural ground.\n                        '), off_natural_ground_placement_state=TunableStateValueReference(description='\n                        If specified, the object will enter this state when\n                        being placed off of natural ground.\n                        '))), delinquency_state_changes=OptionalTunable(TunableMapping(description='\n                A tunable mapping linking a utility to a list of state changes\n                to apply to the owning object of this component when that\n                utility goes delinquent and is shut off.\n                ', key_type=TunableEnumEntry(description='\n                    A utility that will force state changes when it is shut\n                    off.\n                    ', tunable_type=sims.bills_enums.Utilities, default=None), value_type=TunableList(description='\n                    A tunable list of states to apply to the owning object of\n                    this component when the mapped utility is shut off.\n                    ', tunable=TunableStateValueReference()))), description=description, **kwargs),)

def state_change(target, new_value_beginning=None, new_value_ending=None, xevt_id=None, animation_context=None, criticality=CleanupType.OnCancel, sequence=()):
    queue = []
    if target is None:
        return sequence
    set_at_beginning = new_value_beginning is not None and new_value_beginning.state is not None
    set_at_ending = new_value_ending is not None and new_value_ending.state is not None
    if set_at_ending:
        did_set = False
        target_ref = weakref.ref(target)

        def set_ending(*_, **__):
            nonlocal did_set
            if not did_set:
                resolved_target = target_ref()
                if resolved_target is not None:
                    resolved_target.set_state(new_value_ending.state, new_value_ending)
                did_set = True

    if set_at_beginning:
        queue.append(lambda _: target.set_state(new_value_beginning.state, new_value_beginning))
    if set_at_ending and xevt_id is not None:
        queue.append(lambda _: animation_context.register_event_handler(set_ending, handler_id=xevt_id))
    queue.append(sequence)
    if set_at_ending:
        queue.append(set_ending)
    else:
        criticality = CleanupType.NotCritical
    queue = build_element(queue, critical=criticality)
    return queue

class TunableStateChange(TunableFactory):
    __qualname__ = 'TunableStateChange'

    @staticmethod
    def _state_change_at_beginning(new_value, **kwargs):
        return state_change(new_value_beginning=new_value, **kwargs)

    TunableAtBeginning = TunableFactory.create_auto_factory(_state_change_at_beginning, 'TunableAtBeginning', description='Change the state value at the beginning of the sequence.')

    @staticmethod
    def _state_change_at_end(new_value, **kwargs):
        return state_change(new_value_ending=new_value, **kwargs)

    TunableAtEnd = TunableFactory.create_auto_factory(_state_change_at_end, 'TunableAtEnd', description='Change the state value at the end of the sequence.', criticality=TunableEnumEntry(CleanupType, CleanupType.OnCancel, description='The criticality of making the state change.'))
    TunableOnXevt = TunableFactory.create_auto_factory(_state_change_at_end, 'TunableOnXevt', description='\n        Set the new state value in sync with an animation event with a\n        particular id. In the case no matching event occurs in the animation,\n        the value will still be set at the end of the sequence.\n        ', criticality=TunableEnumEntry(CleanupType, CleanupType.OnCancel, description='The criticality of making the state change.'), xevt_id=Tunable(int, 100, description="An xevt on which to change the state's value."))

    @staticmethod
    def _single_value(interaction, new_value):
        return new_value

    TunableSingleValue = TunableFactory.create_auto_factory(_single_value, 'TunableSingleValue', new_value=TunableStateValueReference())

    class ValueFromTestList(HasTunableSingletonFactory):
        __qualname__ = 'TunableStateChange.ValueFromTestList'

        @classproperty
        def FACTORY_TUNABLES(cls):
            from event_testing.tests import TunableTestVariant
            return {'new_values': TunableList(TunableTuple(test=TunableTestVariant(test_locked_args={'tooltip': None}), value=TunableStateValueReference())), 'fallback_value': OptionalTunable(TunableStateValueReference())}

        def __init__(self, new_values, fallback_value):
            self.new_values = new_values
            self.fallback_value = fallback_value

        def __call__(self, interaction):
            resolver = interaction.get_resolver()
            for new_value in self.new_values:
                while resolver(new_value.test):
                    return new_value.value
            return self.fallback_value

    class ValueFromTestSetList(ValueFromTestList):
        __qualname__ = 'TunableStateChange.ValueFromTestSetList'

        @classproperty
        def FACTORY_TUNABLES(cls):
            from event_testing.tests import TunableTestSet
            return {'new_values': TunableList(TunableTuple(tests=TunableTestSet(), value=TunableStateValueReference()))}

        def __call__(self, interaction):
            resolver = interaction.get_resolver()
            for new_value in self.new_values:
                while new_value.tests.run_tests(resolver):
                    return new_value.value
            return self.fallback_value

    @staticmethod
    def _factory(interaction, state_change_target, timing, new_value, **kwargs):
        actual_state_change_target = interaction.get_participant(state_change_target)
        actual_new_value = new_value(interaction)
        return timing(new_value=actual_new_value, target=actual_state_change_target, animation_context=interaction.animation_context, **kwargs)

    FACTORY_TYPE = _factory

    def __init__(self, description='Change the value of a state on a participant of an interaction.', **kwargs):
        super().__init__(state_change_target=TunableEnumEntry(ParticipantType, ParticipantType.Object, description='Who or what to change the state on.'), timing=TunableVariant(description="When to change the state's value.", immediately=TunableStateChange.TunableAtBeginning(), at_end=TunableStateChange.TunableAtEnd(), on_xevt=TunableStateChange.TunableOnXevt(), default='at_end'), new_value=TunableVariant(description='A new value to set.', single_value=TunableStateChange.TunableSingleValue(), value_from_test_list=TunableStateChange.ValueFromTestList.TunableFactory(), value_from_test_set_list=TunableStateChange.ValueFromTestSetList.TunableFactory(), default='single_value'), description=description, **kwargs)

def transience_change(target, new_value_beginning=None, new_value_ending=None, xevt_id=None, animation_context=None, criticality=CleanupType.OnCancel, sequence=()):
    queue = []
    set_at_beginning = new_value_beginning is not None
    set_at_ending = new_value_ending is not None
    if set_at_ending:
        did_set = False
        target_ref = target.ref()

        def set_ending(*_, **__):
            nonlocal did_set
            if not did_set:
                resolved_target = target_ref()
                if resolved_target is not None:
                    resolved_target.transient = new_value_ending
                did_set = True

        if xevt_id is not None:
            queue.append(lambda _: animation_context.register_event_handler(set_ending, handler_id=xevt_id))

    def set_transience(target, value):
        target.transient = value

    if set_at_beginning:
        queue.append(lambda _: set_transience(target, new_value_beginning))
    queue.append(sequence)
    if set_at_ending:
        queue.append(set_ending)
    else:
        criticality = CleanupType.NotCritical
    queue = build_element(queue, critical=criticality)
    return queue

class TunableTransienceChange(TunableFactory):
    __qualname__ = 'TunableTransienceChange'

    @staticmethod
    def _factory(interaction, who, **kwargs):
        target = interaction.get_participant(who)
        return transience_change(target=target, animation_context=interaction.animation_context, **kwargs)

    FACTORY_TYPE = _factory

    def __init__(self, description="Change the transience on the interaction's target.", **kwargs):
        super().__init__(who=TunableEnumEntry(ParticipantType, ParticipantType.Object, description='Who or what to apply this test to'), new_value_beginning=TunableVariant(locked_args={'no_change': None, 'make_transient': True, 'make_permanent': False}, default='no_change', description='A value to set transience to at the beginning (may be None)'), new_value_ending=TunableVariant(locked_args={'no_change': None, 'make_transient': True, 'make_permanent': False}, default='no_change', description='A value to set transience to at the beginning (may be None)'), xevt_id=OptionalTunable(Tunable(int, 100, description="An xevt on which to change the state's value to new_value_ending")), criticality=TunableEnumEntry(CleanupType, CleanupType.NotCritical, description='The criticality of making these state changes.'), description=description, **kwargs)

def filter_on_state_changed_callback(callback, filter_state):

    def callback_filter(target, state, old_value, new_value):
        if state != filter_state:
            return
        return callback(target, state, old_value, new_value)

    return callback_filter

def with_on_state_changed(target, filter_state, callback, *sequence):
    if filter_state is not None:
        callback = filter_on_state_changed_callback(callback, filter_state)

    def add_fn(_):
        target.add_state_changed_callback(callback)

    def remove_fn(_):
        target.remove_state_changed_callback(callback)

    return build_critical_section_with_finally(add_fn, sequence, remove_fn)

def cancel_on_state_change(interaction, value, *sequence):

    def callback_fn(target, state, old_value, new_value):
        if new_value != value:
            interaction.cancel(FinishingType.OBJECT_CHANGED, cancel_reason_msg='state: interaction canceled on state change ({} != {})'.format(new_value.value, value.value))

    return with_on_state_changed(interaction.target, value.state, callback_fn, *sequence)

