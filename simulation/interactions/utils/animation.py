#ERROR: jaddr is None
from collections import namedtuple
import _math
import random
import weakref
from animation import get_animation_object_by_id, get_event_handler_error_for_missing_object, get_animation_object_for_event, AnimationContext, get_throwaway_animation_context
from animation.posture_manifest import PostureManifestOverrideValue, PostureManifestOverrideKey, PostureManifest, MATCH_ANY, MATCH_NONE, AnimationParticipant
from distributor.rollback import ProtocolBufferRollback
from element_utils import build_critical_section, build_critical_section_with_finally, build_element, must_run, do_all
from interactions import ParticipantTypeReactionlet, ParticipantType
from interactions.utils.animation_selector import TunableAnimationSelector
from interactions.utils.balloon import TunableBalloon
from native.animation import get_mirrored_joint_name_hash, get_joint_transform_from_rig
from objects.components.types import IDLE_COMPONENT
from objects.definition_manager import DefinitionManager
from protocolbuffers import DistributorOps_pb2 as protocols
from sims4.callback_utils import CallableList, consume_exceptions
from sims4.collections import frozendict
from sims4.repr_utils import standard_repr
from sims4.tuning.instances import TunedInstanceMetaclass
from sims4.tuning.tunable import TunableFactory, Tunable, TunableList, TunableTuple, TunableReference, TunableResourceKey, TunableVariant, OptionalTunable, TunableMapping, TunableSingletonFactory, HasTunableReference
from sims4.tuning.tunable_base import SourceQueries, SourceSubQueries, FilterTag
from sims4.utils import classproperty, flexmethod
from singletons import DEFAULT, UNSET
import animation
import animation.arb
import animation.asm
import animation.posture_manifest
import clock
import distributor.ops
import element_utils
import elements
import enum
import gsi_handlers.interaction_archive_handlers
import routing
import services
import sims4.log
import sims4.reload
logger = sims4.log.Logger('Animation')
dump_logger = sims4.log.LoggerClass('Animation')
with sims4.reload.protected(globals()):
    _nested_arb_depth = 0
    _nested_arb_detach_callbacks = None
    _log_arb_contents = False
    AUTO_EXIT_REF_TAG = 'auto_exit'

class AsmAutoExitInfo:
    __qualname__ = 'AsmAutoExitInfo'

    def __init__(self):
        self.clear()

    def clear(self):
        if hasattr(self, 'asm') and self.asm is not None:
            animation_context = self.asm[2]
            animation_context.release_ref(AUTO_EXIT_REF_TAG)
        self.asm = None
        self.apply_carry_interaction_mask = 0
        self.locked = False

class _FakePostureState:
    __qualname__ = '_FakePostureState'

    def get_carry_state(self, *_, **__):
        return (False, False)

    def get_carry_track(self, *_, **__):
        pass

    def get_carry_posture(self, *_, **__):
        pass

    @property
    def surface_target(self):
        pass

FAKE_POSTURE_STATE = _FakePostureState()

class StubActor:
    __qualname__ = 'StubActor'
    additional_interaction_constraints = None
    age = UNSET
    is_valid_posture_graph_object = False
    party = None

    def __init__(self, guid, template=None, debug_name=None, parent=None):
        self.id = guid
        self.template = template
        self.debug_name = debug_name
        self.parent = parent
        self.asm_auto_exit = AsmAutoExitInfo()

    def __repr__(self):
        return 'StubActor({})'.format(self.debug_name or self.id)

    def ref(self, *args):
        return weakref.ref(self, *args)

    def resolve(self, cls):
        return self

    def is_in_inventory(self):
        return False

    def is_in_sim_inventory(self, sim=None):
        return False

    @property
    def LineOfSight(self):
        if self.template is not None:
            return self.template.lineofsight_component

    @property
    def parts(self):
        if self.template is not None:
            return self.template.parts

    @property
    def is_part(self):
        if self.template is not None:
            return self.template.is_part
        return False

    @property
    def part_suffix(self):
        if self.template is not None:
            return self.template.part_suffix

    def is_mirrored(self, *args, **kwargs):
        if self.template is not None:
            return self.template.is_mirrored(*args, **kwargs)
        return False

    @property
    def location(self):
        routing_surface = routing.SurfaceIdentifier(sims4.zone_utils.get_zone_id(True) or 0, 0, routing.SURFACETYPE_WORLD)
        return sims4.math.Location(sims4.math.Transform(), routing_surface)

    @property
    def transform(self):
        return self.location.transform

    @property
    def position(self):
        return self.transform.translation

    @property
    def orientation(self):
        return self.transform.orientation

    @property
    def forward(self):
        return self.orientation.transform_vector(sims4.math.Vector3.Z_AXIS())

    @property
    def routing_surface(self):
        return self.location.routing_surface

    @property
    def intended_transform(self):
        return self.transform

    @property
    def intended_position(self):
        return self.position

    @property
    def intended_forward(self):
        return self.forward

    @property
    def intended_routing_surface(self):
        return self.routing_surface

    @property
    def is_sim(self):
        if self.template is not None:
            return self.template.is_sim
        return False

    @property
    def rig(self):
        if self.template is not None:
            return self.template.rig

    def get_anim_overrides(self, target_name):
        if self.template is not None:
            return self.template.get_anim_overrides(target_name)

    def get_param_overrides(self, target_name, only_for_keys=None):
        if self.template is not None:
            return self.template.get_param_overrides(target_name, only_for_keys)

    @property
    def custom_posture_target_name(self):
        if self.template is not None:
            return self.template.custom_posture_target_name

    @property
    def route_target(self):
        import interactions.utils.routing
        return (interactions.utils.routing.RouteTargetType.OBJECT, self)

    @property
    def posture_state(self):
        if self.template is not None:
            return self.template.posture_state
        return FAKE_POSTURE_STATE

    def get_social_group_constraint(self, si):
        import interactions.constraints
        return interactions.constraints.Anywhere()

    def filter_supported_postures(self, postures, *args, **kwargs):
        if self.template is not None:
            return self.template.filter_supported_postures(postures, *args, **kwargs)
        return postures

    @property
    def definition(self):
        if self.template is not None:
            return self.template.definition

def clip_event_type_name(event_type):
    for (name, val) in vars(animation.ClipEventType).items():
        while val == event_type:
            return name
    return 'Unknown({})'.format(event_type)

def create_run_animation(arb):
    if arb.empty:
        return

    def run_animation(_):
        arb_accumulator = services.current_zone().arb_accumulator_service
        arb_accumulator.add_arb(arb)

    return build_element(run_animation)

def flush_all_animations(timeline):
    arb_accumulator = services.current_zone().arb_accumulator_service
    yield arb_accumulator.flush(timeline)

def flush_all_animations_instantly(timeline):
    arb_accumulator = services.current_zone().arb_accumulator_service
    yield arb_accumulator.flush(timeline, animate_instantly=True)

def get_actors_for_arb_sequence(*arb_sequence):
    all_actors = set()
    om = services.object_manager()
    if om:
        for arb in arb_sequence:
            if isinstance(arb, list):
                arbs = arb
            else:
                arbs = (arb,)
            for sub_arb in arbs:
                for actor_id in sub_arb._actors():
                    actor = om.get(actor_id)
                    if actor is None:
                        pass
                    all_actors.add(actor)
    return all_actors

class AnimationSleepElement(elements.SubclassableGeneratorElement):
    __qualname__ = 'AnimationSleepElement'

    def __init__(self, duration_must_run, duration_interrupt, duration_repeat, enable_optional_sleep_time=True):
        if duration_interrupt != 0 and duration_repeat != 0:
            raise AssertionError('An animation with both interrupt and repeat duration is not allowed.')
        super().__init__()
        self._duration_must_run = duration_must_run
        self._duration_interrupt = duration_interrupt
        self._duration_repeat = duration_repeat
        self._stop_requested = False
        self.enable_optional_sleep_time = enable_optional_sleep_time
        self._optional_time_elapsed = 0

    @classmethod
    def shortname(cls):
        return 'AnimSleep'

    @property
    def optional_time_elapsed(self):
        return self._optional_time_elapsed

    def _run_gen(self, timeline):
        if self._duration_must_run > 0:
            yield element_utils.run_child(timeline, elements.SleepElement(clock.interval_in_real_seconds(self._duration_must_run)))
        if self._stop_requested:
            return False
        if self._duration_repeat > 0.0:
            while not self._stop_requested:
                yield element_utils.run_child(timeline, elements.SleepElement(clock.interval_in_real_seconds(self._duration_repeat)))
        elif self.enable_optional_sleep_time and self._duration_interrupt > 0:
            then = timeline.now
            yield element_utils.run_child(timeline, elements.SoftSleepElement(clock.interval_in_real_seconds(self._duration_interrupt)))
            now = timeline.now
            self._optional_time_elapsed = (now - then).in_real_world_seconds()
        else:
            yield element_utils.run_child(timeline, element_utils.sleep_until_next_tick_element())
        return True

    def _soft_stop(self):
        super()._soft_stop()
        self._stop_requested = True

class ArbElement(distributor.ops.ElementDistributionOpMixin, elements.SubclassableGeneratorElement):
    __qualname__ = 'ArbElement'
    _BASE_ROOT_STRING = 'b__subroot__'

    def __init__(self, arb, event_records=None, master=None):
        super().__init__()
        self.arb = arb
        self.enable_optional_sleep_time = True
        self._attached_actors = []
        self._default_handlers_registered = False
        self.event_records = event_records
        self._stop_requested = False
        self._duration_total = None
        self._duration_must_run = None
        self._duration_interrupt = None
        self._duration_repeat = None
        self._objects_to_reset = []
        self.master = master
        self._add_block_tags_for_event_records(event_records)

    def __repr__(self):
        if self.event_records is not None:
            event_tags = [event_record.tag for event_record in self.event_records]
            return standard_repr(self, tags=event_tags)
        return standard_repr(self)

    def _actors(self, main_timeline_only=False):
        actors = []
        if self.arb.is_valid():
            om = services.object_manager()
            if om:
                try:
                    actors_iter = self.arb._actors(main_timeline_only)
                except:
                    actors_iter = self.arb._actors()
                while True:
                    for actor_id in actors_iter:
                        actor = om.get(actor_id)
                        while actor is not None:
                            actors.append(actor)
        return actors

    def _get_asms_from_arb_request_info(self):
        return ()

    def _log_event_records(self, log_fn, only_errors):
        log_records = []
        errors_found = False
        for record in self.event_records:
            if record.errors:
                errors_found = True
                for error in record.errors:
                    log_records.append((True, record, error))
            else:
                log_records.append((False, record, None))
        if errors_found:
            log_fn('Errors occurred while handling clip events:')
        if errors_found or not only_errors:
            for (is_error, record, message) in log_records:
                if only_errors and not is_error:
                    pass
                event_type = clip_event_type_name(record.event_type)
                if message:
                    message = ': ' + str(message)
                log_fn('  {}: {}#{:03}{}'.format(record.clip_name, event_type, record.event_id, message))
            self.arb.log_request_history(log_fn)

    def _add_block_tags_for_event_records(self, event_records):
        if event_records:
            for event in event_records:
                self.block_tag(event.tag)

    def attach(self, *actors):
        new_attachments = [a for a in actors if a not in self._attached_actors]
        if new_attachments:
            super().attach(*new_attachments)
            mask = 0
            for (_, suffix) in self.arb._actor_instances():
                while suffix is not None:
                    mask |= 1 << int(suffix)
            if not mask:
                mask = 4294967295
            for attachment in new_attachments:
                self.add_additional_channel(attachment.manager.id, attachment.id, mask=mask)
        self._attached_actors.extend(new_attachments)

    def detach(self, *detaching_objects):
        global _nested_arb_detach_callbacks
        if self.master not in detaching_objects:
            for detaching_object in detaching_objects:
                self._attached_actors.remove(detaching_object)
            super().detach(*detaching_objects)
            return
        if _nested_arb_depth > 0:
            if _nested_arb_detach_callbacks is None:
                _nested_arb_detach_callbacks = CallableList()
            super_self = super()
            _nested_arb_detach_callbacks.append(lambda : super_self.detach(*self._attached_actors))
            return True
        if _nested_arb_detach_callbacks is not None:
            cl = _nested_arb_detach_callbacks
            _nested_arb_detach_callbacks = None
            cl()
        super().detach(*self._attached_actors)

    def add_object_to_reset(self, obj):
        self._objects_to_reset.append(obj)

    def execute_and_merge_arb(self, arb, safe_mode):
        if self.event_records is None:
            raise RuntimeError("Attempt to merge an Arb into an ArbElement that hasn't had handle_events() called: {} into {}.".format(arb, self))
        arb_element = ArbElement(arb)
        (event_records, _) = arb_element.handle_events()
        self.event_records.extend(event_records)
        self._additional_channels.update(arb_element._additional_channels)
        self._add_block_tags_for_event_records(event_records)
        self.arb.append(arb, safe_mode)

    def handle_events(self):
        global _nested_arb_depth
        if not self._default_handlers_registered:
            self._register_default_handlers()
            self._default_handlers_registered = True
        sleep = _nested_arb_depth == 0
        _nested_arb_depth += 1
        event_context = consume_exceptions('Animation', 'Exception raised while handling clip events:')
        event_records = self.arb.handle_events(event_context=event_context)
        _nested_arb_depth -= 1
        return (event_records, sleep)

    def distribute(self):
        gen = self._run_gen()
        try:
            next(gen)
            logger.error('ArbElement.distribute attempted to yield.')
        except StopIteration as exc:
            return exc.value

    def _run_gen(self, timeline=None):
        if not self.arb.is_valid():
            return False
        actors = self._actors()
        if not actors and not self._objects_to_reset:
            return True
        animation_sleep_element = None
        with distributor.system.Distributor.instance().dependent_block():
            self.attach(*actors)
            if self.event_records is None:
                (self.event_records, sleep) = self.handle_events()
            else:
                sleep = True
            self._log_event_records(dump_logger.error, True)
            for actor in actors:
                actor.update_reference_arb(self.arb)
            while sleep and timeline is not None:
                (self._duration_total, self._duration_must_run, self._duration_repeat) = self.arb.get_timing()
                self._duration_interrupt = self._duration_total - self._duration_must_run
                while self._duration_must_run or self._duration_repeat:
                    animation_sleep_element = AnimationSleepElement(self._duration_must_run, self._duration_interrupt, self._duration_repeat, enable_optional_sleep_time=self.enable_optional_sleep_time)
        if not (animation_sleep_element is not None and services.current_zone().animate_instantly):
            yield element_utils.run_child(timeline, animation_sleep_element)
        self.detach(*self._attached_actors)
        return True

    def write(self, msg):
        from protocolbuffers import Animation_pb2 as animation_protocols
        if self.event_records is None:
            logger.error('ArbElement is being distributed before it has completed the non-blocking portion of _run().')
            return
        if self.arb.empty and not self._objects_to_reset:
            logger.warn('An empty Arb is being distributed')
            return
        msg.type = protocols.Operation.ARB
        arb_pb = animation_protocols.AnimationRequestBlock()
        arb_pb.arb_data = self.arb._bytes()
        for event in self.event_records:
            netRecord = arb_pb.event_handlers.add()
            netRecord.event_type = event.event_type
            netRecord.event_id = event.event_id
            netRecord.tag = event.tag
        for object_to_reset in self._objects_to_reset:
            with ProtocolBufferRollback(arb_pb.objects_to_reset) as moid_to_reset_msg:
                moid_to_reset_msg.manager_id = object_to_reset.manager.id
                moid_to_reset_msg.object_id = object_to_reset.id
        msg.data = arb_pb.SerializeToString()

    def _register_default_handlers(self):
        self.arb.register_event_handler(self._event_handler_snap, animation.ClipEventType.Snap)
        self.arb.register_event_handler(self._event_handler_parent, animation.ClipEventType.Parent)
        self.arb.register_event_handler(self._event_handler_visibility, animation.ClipEventType.Visibility)

    def _event_handler_snap(self, event_data):
        asms = self._get_asms_from_arb_request_info()
        (early_out, object_to_snap) = get_animation_object_for_event(event_data, 'event_actor_id', 'object to be snapped', asms=asms)
        if early_out is not None:
            return
        (early_out, snap_reference_object) = get_animation_object_for_event(event_data, 'snap_actor_id', 'snap reference object', asms=asms)
        if early_out is not None:
            return
        v = event_data.event_data['snap_translation']
        q = event_data.event_data['snap_orientation']
        suffix = event_data.event_data['snap_actor_suffix']
        base_transform = snap_reference_object.transform
        if suffix is not None:
            base_joint = self._BASE_ROOT_STRING + suffix
            base_transform = _math.Transform.concatenate(get_joint_transform_from_rig(snap_reference_object.rig, base_joint), base_transform)
        snap_transform = _math.Transform(v, q)
        object_to_snap.transform = _math.Transform.concatenate(snap_transform, base_transform)

    def _event_handler_parent(self, event_data):
        asms = self._get_asms_from_arb_request_info()
        (early_out, child_object) = get_animation_object_for_event(event_data, 'parent_child_id', 'child', asms=asms)
        if early_out is not None:
            return
        v = event_data.event_data['parent_translation']
        q = event_data.event_data['parent_orientation']
        transform = _math.Transform(v, q)
        parent_id = event_data.event_data['parent_parent_id']
        if parent_id is None:
            pass
        else:
            parent_object = get_animation_object_by_id(int(parent_id))
            if parent_object is None:
                return get_event_handler_error_for_missing_object('parent', parent_id)
            self.add_additional_channel(child_object.manager.id, child_object.id)
            joint_name_hash = int(event_data.event_data['parent_joint_name_hash'])
            if event_data.event_data['clip_is_mirrored']:
                joint_name_hash = get_mirrored_joint_name_hash(parent_object.rig, joint_name_hash)
            child_object.set_parent(parent_object, transform, joint_name_hash)

    def _event_handler_visibility(self, event_data):
        from objects import VisibilityState
        asms = self._get_asms_from_arb_request_info()
        (early_out, target_object) = get_animation_object_for_event(event_data, 'target_actor_id', 'target', asms=asms, allow_obj=False)
        if early_out is not None:
            (early_out, target_object) = get_animation_object_for_event(event_data, 'target_actor_id', 'target', asms=asms, allow_prop=False)
            if early_out is not None:
                return
        visible = event_data.event_data['visibility_state']
        if visible is not None:
            curr_visibility = target_object.visibility or VisibilityState(True, False, False)
            target_object.visibility = VisibilityState(visible, curr_visibility.inherits, curr_visibility.enable_drop_shadow)

    def _debug_test_handlers(self):

        def _event_handler_all(event_data):
            print('Calling _event_handler_all:')
            print(event_data.event_type, event_data.event_id, event_data.event_data)

        self.arb.register_event_handler(_event_handler_all)
        print('--------Testing event handlers--------')
        eventRecords = self.arb.handle_events()
        print('--------------------------------------')
        return eventRecords

def with_event_handlers(animation_context, handler, clip_event_type, sequence=None, tag=None):
    handle = None

    def begin(_):
        nonlocal handle
        handle = animation_context.register_event_handler(handler, clip_event_type, tag=tag)

    def end(_):
        if handle is not None:
            handle.release()

    return build_critical_section(begin, sequence, end)

def get_release_contexts_fn(contexts_to_release, tag):

    def release_contexts(_):
        for context in contexts_to_release:
            context.release_ref(tag)

    return release_contexts

def release_auto_exit(actor):
    contexts_to_release = []
    for other_actor in actor.asm_auto_exit.asm[1]:
        while other_actor.is_sim:
            if other_actor.asm_auto_exit.asm is not None:
                animation_context = other_actor.asm_auto_exit.asm[2]
                contexts_to_release.append(animation_context)
                other_actor.asm_auto_exit.asm = None
    return contexts_to_release

def get_auto_exit(actors, asm=None, interaction=None):
    arb_exit = None
    contexts_to_release_all = []
    for actor in actors:
        while actor.is_sim and actor.asm_auto_exit.asm is not None:
            asm_to_exit = actor.asm_auto_exit.asm[0]
            if asm_to_exit is asm:
                pass
            if arb_exit is None:
                arb_exit = animation.arb.Arb()
            if interaction is not None and gsi_handlers.interaction_archive_handlers.is_archive_enabled(interaction):
                prev_state = asm_to_exit.current_state
            asm_to_exit.request('exit', arb_exit)
            if interaction is not None and (gsi_handlers.interaction_archive_handlers.is_archive_enabled(interaction) and interaction is not None) and not arb_exit.empty:
                gsi_handlers.interaction_archive_handlers.add_animation_data(interaction, asm_to_exit, prev_state, 'exit', arb_exit.get_contents_as_string())
            contexts_to_release = release_auto_exit(actor)
            contexts_to_release_all.extend(contexts_to_release)
    release_contexts_fn = get_release_contexts_fn(contexts_to_release_all, AUTO_EXIT_REF_TAG)
    if arb_exit is not None and not arb_exit.empty:
        element = build_critical_section_with_finally(build_critical_section(create_run_animation(arb_exit), flush_all_animations), release_contexts_fn)
        return must_run(element)
    if contexts_to_release_all:
        return must_run(build_element(release_contexts_fn))

def mark_auto_exit(actors, asm):
    if asm is None:
        return
    contexts_to_release_all = []
    for actor in actors:
        while actor.is_sim and (actor.asm_auto_exit is not None and actor.asm_auto_exit.asm is not None) and actor.asm_auto_exit.asm[0] is asm:
            contexts_to_release = release_auto_exit(actor)
            contexts_to_release_all.extend(contexts_to_release)
    if not contexts_to_release_all:
        return
    return get_release_contexts_fn(contexts_to_release_all, AUTO_EXIT_REF_TAG)

def animate(asm, target_state, **kwargs):
    return animate_states(asm, (target_state,), **kwargs)

def _create_balloon_request_callback(balloon_request=None):

    def balloon_handler_callback(_event_data):
        balloon_request.distribute()

    return balloon_handler_callback

def animate_states(asm, begin_states, end_states=None, sequence=(), require_end=True, overrides=None, balloon_requests=None, setup_asm=None, cleanup_asm=None, enable_auto_exit=True, repeat_begin_states=False, interaction=None, **kwargs):
    if asm is not None:
        requires_begin_flush = bool(sequence)
        all_actors = set()
        do_gsi_logging = interaction is not None and gsi_handlers.interaction_archive_handlers.is_archive_enabled(interaction)

        def do_begin(timeline):
            nonlocal all_actors
            if overrides:
                overrides.override_asm(asm)
            if setup_asm is not None:
                setup_asm(asm)
            if do_gsi_logging:
                for (actor_name, (actor, _, _)) in asm._actors.items():
                    actor = actor()
                    gsi_handlers.interaction_archive_handlers.add_asm_actor_data(interaction, asm, actor_name, actor)
            if begin_states:
                arb_begin = animation.arb.Arb()
                if balloon_requests:
                    remaining_balloons = list(balloon_requests)
                    for balloon_request in balloon_requests:
                        balloon_delay = balloon_request.delay or 0
                        if balloon_request.delay_randomization > 0:
                            balloon_delay += random.random()*balloon_request.delay_randomization
                        while asm.context.register_custom_event_handler(_create_balloon_request_callback(balloon_request=balloon_request), None, balloon_delay, allow_stub_creation=True):
                            remaining_balloons.remove(balloon_request)
                    if remaining_balloons:
                        logger.error('Failed to schedule all requested balloons for {}', asm)
                if do_gsi_logging:
                    gsi_archive_logs = []
                if asm.current_state == 'exit':
                    asm.set_current_state('entry')
                for state in begin_states:
                    if do_gsi_logging:
                        prev_state = asm.current_state
                        arb_buffer = arb_begin.get_contents_as_string()
                    asm.request(state, arb_begin)
                    while do_gsi_logging:
                        arb_begin_str = arb_begin.get_contents_as_string()
                        current_arb_str = arb_begin_str[arb_begin_str.find(arb_buffer) + len(arb_buffer):]
                        gsi_archive_logs.append((prev_state, state, current_arb_str))
                actors_begin = get_actors_for_arb_sequence(arb_begin)
                all_actors = all_actors | actors_begin
                sequence = create_run_animation(arb_begin)
                if asm.current_state == 'exit':
                    auto_exit_releases = mark_auto_exit(actors_begin, asm)
                    if auto_exit_releases is not None:
                        sequence = build_critical_section_with_finally(sequence, auto_exit_releases)
                auto_exit_element = get_auto_exit(actors_begin, asm=asm, interaction=interaction)
                if auto_exit_element is not None:
                    sequence = (auto_exit_element, sequence)
                if enable_auto_exit and asm.current_state != 'exit':
                    auto_exit_actors = {actor for actor in all_actors if not actor.asm_auto_exit.locked}
                    while True:
                        for actor in auto_exit_actors:
                            if actor.asm_auto_exit.asm is None:
                                actor.asm_auto_exit.asm = (asm, auto_exit_actors, asm.context)
                                asm.context.add_ref(AUTO_EXIT_REF_TAG)
                            else:
                                while actor.asm_auto_exit.asm[0] != asm:
                                    raise RuntimeError('Multiple ASMs in need of auto-exit simultaneously: {} and {}'.format(actor.asm_auto_exit.asm[0], asm))
                if do_gsi_logging:
                    for (prev_state, state, current_arb_str) in gsi_archive_logs:
                        gsi_handlers.interaction_archive_handlers.add_animation_data(interaction, asm, prev_state, state, current_arb_str)
                if requires_begin_flush:
                    sequence = build_critical_section(sequence, flush_all_animations)
                sequence = build_element(sequence)
                if sequence is not None:
                    result = yield element_utils.run_child(timeline, sequence)
                else:
                    result = True
                return result
            return True

        def do_end(timeline):
            nonlocal all_actors
            arb_end = animation.arb.Arb()
            if do_gsi_logging:
                gsi_archive_logs = []
            if end_states:
                for state in end_states:
                    if do_gsi_logging:
                        prev_state = asm.current_state
                        arb_buffer = arb_end.get_contents_as_string()
                    asm.request(state, arb_end)
                    while do_gsi_logging:
                        arb_end_str = arb_end.get_contents_as_string()
                        current_arb_str = arb_end_str[arb_end_str.find(arb_buffer) + len(arb_buffer):]
                        gsi_archive_logs.append((prev_state, state, current_arb_str))
            actors_end = get_actors_for_arb_sequence(arb_end)
            all_actors = all_actors | actors_end
            if requires_begin_flush or not arb_end.empty:
                sequence = create_run_animation(arb_end)
            else:
                sequence = None
            if asm.current_state == 'exit':
                auto_exit_releases = mark_auto_exit(all_actors, asm)
                if auto_exit_releases is not None:
                    sequence = build_critical_section_with_finally(sequence, auto_exit_releases)
            if sequence:
                auto_exit_element = get_auto_exit(actors_end, asm=asm, interaction=interaction)
                if do_gsi_logging:
                    for (prev_state, state, current_arb_str) in gsi_archive_logs:
                        gsi_handlers.interaction_archive_handlers.add_animation_data(interaction, asm, prev_state, state, current_arb_str)
                if auto_exit_element is not None:
                    sequence = (auto_exit_element, sequence)
                result = yield element_utils.run_child(timeline, sequence)
                return result
            return True

        if repeat_begin_states:

            def do_soft_stop(timeline):
                loop.trigger_soft_stop()

            loop = elements.RepeatElement(build_element(do_begin))
            sequence = do_all(loop, build_element([sequence, do_soft_stop]))
        sequence = build_element([do_begin, sequence])
        if require_end:
            sequence = build_critical_section(sequence, do_end)
        else:
            sequence = build_element([sequence, do_end])
    if cleanup_asm is not None:
        sequence = build_critical_section_with_finally(sequence, lambda _: cleanup_asm(asm))
    return sequence

class InteractionAsmType(enum.IntFlags, export=False):
    __qualname__ = 'InteractionAsmType'
    Unknown = 0
    Interaction = 1
    Outcome = 2
    Response = 4
    Reactionlet = 8
    Canonical = 16

class TunableParameterMapping(TunableMapping):
    __qualname__ = 'TunableParameterMapping'

    def __init__(self, **kwargs):
        super().__init__(key_name='name', value_type=TunableVariant(default='string', boolean=Tunable(bool, False), string=Tunable(str, 'value'), integral=Tunable(int, 0)), **kwargs)

class AnimationOverrides:
    __qualname__ = 'AnimationOverrides'

    def __init__(self, overrides=None, params=frozendict(), vfx=frozendict(), sounds=frozendict(), props=frozendict(), prop_state_values=frozendict(), manifests=frozendict(), required_slots=None, balloons=None, reactionlet=None, animation_context=None):
        if overrides is None:
            self.params = frozendict(params)
            self.vfx = frozendict(vfx)
            self.sounds = frozendict(sounds)
            self.props = frozendict(props)
            self.prop_state_values = frozendict(prop_state_values)
            self.manifests = frozendict(manifests)
            self.required_slots = required_slots or ()
            self.balloons = balloons or ()
            self.reactionlet = reactionlet or None
            self.animation_context = animation_context or None
            self.balloon_target_override = None
        else:
            self.params = frozendict(params, overrides.params)
            self.vfx = frozendict(vfx, overrides.vfx)
            self.sounds = frozendict(sounds, overrides.sounds)
            self.props = frozendict(props, overrides.props)
            self.prop_state_values = frozendict(prop_state_values, overrides.prop_state_values)
            self.manifests = frozendict(manifests, overrides.manifests)
            self.required_slots = overrides.required_slots or (required_slots or ())
            self.balloons = overrides.balloons or (balloons or ())
            self.reactionlet = overrides.reactionlet or (reactionlet or None)
            self.animation_context = overrides.animation_context or (animation_context or None)
            self.balloon_target_override = overrides.balloon_target_override or None

    def __call__(self, overrides=None, **kwargs):
        if not overrides and not kwargs:
            return self
        if kwargs:
            overrides = AnimationOverrides(overrides=overrides, **kwargs)
        return AnimationOverrides(overrides=overrides, params=self.params, vfx=self.vfx, sounds=self.sounds, props=self.props, prop_state_values=self.prop_state_values, manifests=self.manifests, required_slots=self.required_slots, balloons=self.balloons, reactionlet=self.reactionlet, animation_context=self.animation_context)

    def __repr__(self):
        items = []
        for name in ('params', 'vfx', 'sounds', 'props', 'manifests', 'required_slots', 'balloons', 'reactionlet', 'animation_context'):
            value = getattr(self, name)
            while value:
                items.append('{}={}'.format(name, value))
        return '{}({})'.format(type(self).__name__, ', '.join(items))

    def __bool__(self):
        if self.params or (self.vfx or (self.props or (self.prop_state_values or (self.manifests or (self.required_slots or (self.balloons or self.reactionlet)))))) or self.animation_context:
            return True
        return False

    def __eq__(self, other):
        if self is other:
            return True
        if type(self) != type(other):
            return False
        if self.params != other.params or (self.vfx != other.vfx or (self.sounds != other.sounds or (self.props != other.props or (self.prop_state_values != other.prop_state_values or (self.manifests != other.manifests or (self.required_slots != other.required_slots or (self.balloons != other.balloons or (self.reactionlet != other.reactionlet or self.animation_context != other.animation_context)))))))) or self.balloon_target_override != other.balloon_target_override:
            return False
        return True

    def override_asm(self, asm, actor=None, suffix=None):
        if self.params:
            for (param_name, param_value) in self.params.items():
                if isinstance(param_name, tuple):
                    (param_name, actor_name) = param_name
                else:
                    actor_name = None
                if actor_name is not None:
                    if asm.set_actor_parameter(actor_name, actor, param_name, param_value, suffix):
                        pass
                    logger.warn('Parameter {} in {} should be renamed to {}:{}.', param_name, asm.name, actor_name, param_name)
                else:
                    asm.set_parameter(param_name, param_value)
        if self.props:
            for (prop_name, definition) in self.props.items():
                asm.set_prop_override(prop_name, definition)
        if self.prop_state_values:
            for (prop_name, state_values) in self.prop_state_values.items():
                asm.store_prop_state_values(prop_name, state_values)
        if self.vfx:
            for (vfx_actor_name, vfx_override_name) in self.vfx.items():
                asm.set_vfx_override(vfx_actor_name, vfx_override_name)
        if self.sounds:
            for (name, key) in self.sounds.items():
                sound_id = key.instance if key is not None else None
                asm.set_sound_override(name, sound_id)
        if asm is not None and self.animation_context:
            asm.context = AnimationContext()

class TunablePostureManifestCellValue(TunableVariant):
    __qualname__ = 'TunablePostureManifestCellValue'

    def __init__(self, allow_none, string_name, string_default=None, asm_source=None, source_query=None):
        if asm_source is not None:
            asm_source = '../' + asm_source
        else:
            source_query = None
        locked_args = {'match_none': animation.posture_manifest.MATCH_NONE, 'match_any': animation.posture_manifest.MATCH_ANY}
        default = 'match_any'
        kwargs = {string_name: Tunable(str, string_default, source_location=asm_source, source_query=source_query)}
        if allow_none:
            locked_args['leave_unchanged'] = None
            default = 'leave_unchanged'
        super().__init__(default=default, locked_args=locked_args, **kwargs)

class TunablePostureManifestOverrideKey(TunableSingletonFactory):
    __qualname__ = 'TunablePostureManifestOverrideKey'
    FACTORY_TYPE = PostureManifestOverrideKey

    def __init__(self, asm_source=None):
        if asm_source is not None:
            asm_source = '../' + asm_source
            source_query = SourceQueries.ASMActorSim
        else:
            source_query = None
        super().__init__(actor=TunablePostureManifestCellValue(False, 'actor_name', asm_source=asm_source, source_query=source_query), specific=TunablePostureManifestCellValue(False, 'posture_name', 'stand'), family=TunablePostureManifestCellValue(False, 'posture_name', 'stand'), level=TunablePostureManifestCellValue(False, 'overlay_level', 'FullBody'))

class TunablePostureManifestOverrideValue(TunableSingletonFactory):
    __qualname__ = 'TunablePostureManifestOverrideValue'
    FACTORY_TYPE = PostureManifestOverrideValue

    def __init__(self, asm_source=None):
        if asm_source is not None:
            asm_source = '../' + asm_source
            source_query = SourceQueries.ASMActorObject
        else:
            source_query = None
        super().__init__(left=TunablePostureManifestCellValue(True, 'actor_name', asm_source=asm_source, source_query=source_query), right=TunablePostureManifestCellValue(True, 'actor_name', asm_source=asm_source, source_query=source_query), surface=TunablePostureManifestCellValue(True, 'actor_name', 'surface', asm_source=asm_source, source_query=source_query))

RequiredSlotOverride = namedtuple('RequiredSlotOverride', ('actor_name', 'parent_name', 'slot_type'))

class TunableRequiredSlotOverride(TunableSingletonFactory):
    __qualname__ = 'TunableRequiredSlotOverride'
    FACTORY_TYPE = RequiredSlotOverride

    def __init__(self, asm_source=None):
        if asm_source is not None:
            source_query = SourceQueries.ASMActorObject
        else:
            source_query = None
        super().__init__(actor_name=Tunable(str, None, source_location=asm_source, source_query=source_query), parent_name=Tunable(str, 'surface', source_location=asm_source, source_query=source_query), slot_type=TunableReference(services.get_instance_manager(sims4.resources.Types.SLOT_TYPE)))

class TunableAnimationOverrides(TunableFactory):
    __qualname__ = 'TunableAnimationOverrides'

    @staticmethod
    def _factory(*args, manifests, **kwargs):
        if manifests is not None:
            key_name = 'key'
            value_name = 'value'
            manifests_dict = {}
            for item in manifests:
                key = item[key_name]
                if key in manifests_dict:
                    import sims4.tuning.tunable
                    sims4.tuning.tunable.logger.error('Multiple values specified for {} in manifests in an animation overrides block.', key)
                else:
                    manifests_dict[key] = item[value_name]
        else:
            manifests_dict = None
        return AnimationOverrides(manifests=manifests_dict, *args, **kwargs)

    FACTORY_TYPE = _factory

    def __init__(self, asm_source=None, state_source=None, allow_reactionlets=True, override_animation_context=False, participant_enum_override=DEFAULT, description='Overrides to apply to the animation request.', **kwargs):
        if asm_source is not None:
            asm_source = '../../../' + asm_source
            clip_actor_asm_source = asm_source
            vfx_sub_query = SourceSubQueries.ClipEffectName
            sound_sub_query = SourceSubQueries.ClipSoundName
            last_slash_index = clip_actor_asm_source.rfind('/')
            clip_actor_state_source = clip_actor_asm_source[:last_slash_index + 1] + state_source
            clip_actor_state_source = '../' + clip_actor_state_source
            clip_actor_state_source = SourceQueries.ASMClip.format(clip_actor_state_source)
        else:
            clip_actor_asm_source = None
            clip_actor_state_source = None
            vfx_sub_query = None
            sound_sub_query = None
        if participant_enum_override is DEFAULT:
            participant_enum_override = (ParticipantTypeReactionlet, ParticipantTypeReactionlet.Invalid)
        if allow_reactionlets:
            kwargs['reactionlet'] = OptionalTunable(TunableAnimationSelector(description='\n                Reactionlets are short, one-shot animations that are triggered \n                via x-event.\n                X-events are markers in clips that can trigger an in-game \n                effect that is timed perfectly with the clip. Ex: This is how \n                we trigger laughter at the exact moment of the punchline of a \n                Joke\n                It is EXTREMELY important that only content authored and \n                configured by animators to be used as a Reactionlet gets \n                hooked up as Reactionlet content. If this rule is violated, \n                crazy things will happen including the client and server losing \n                time sync. \n                ', interaction_asm_type=InteractionAsmType.Reactionlet, override_animation_context=True, participant_enum_override=participant_enum_override))
        super().__init__(params=TunableParameterMapping(description='\n                This tuning is used for overriding parameters on the ASM to \n                specific values.\n                These will take precedence over those same settings coming from \n                runtime so be careful!\n                You can enter a number of overrides as key/value pairs:\n                Name is the name of the parameter as it appears in the ASM.\n                Value is the value to set on the ASM.\n                Make sure to get the type right. Parameters are either \n                booleans, enums, or strings.\n                Ex: The most common usage of this field is when tuning the \n                custom parameters on specific objects, such as the objectName \n                parameter. \n                '), vfx=TunableMapping(description="\n                VFX overrides for this animation. The key is the effect's actor\n                name. Please note, this is not the name of the vfx that would\n                normally play. This is the name of the actor in the ASM that is\n                associated to a specific effect.\n                ", key_name='original_effect', value_name='replacement_effect', value_type=TunableTuple(description='\n                    Override data for the specified effect actor.\n                    ', effect=OptionalTunable(description='\n                        Override the actual effect that is meant to be played.\n                        It can be left None to stop the effect from playing\n                        ', disabled_name='no_effect', enabled_name='play_effect', tunable=Tunable(str, '')), target_joint=OptionalTunable(description='\n                        Overrides the target joint of the VFX.  This is used in\n                        case of attractors where we want the effect to target a\n                        different place per object on the same animation\n                        ', disabled_name='no_override', enabled_name='override_joint', tunable=Tunable(str, None))), key_type=Tunable(str, None, source_location=clip_actor_asm_source, source_query=clip_actor_state_source, source_sub_query=vfx_sub_query), allow_none=True), sounds=TunableMapping(description='The sound overrides.', key_name='original_sound', value_name='replacement_sound', value_type=OptionalTunable(disabled_name='no_sound', enabled_name='play_sound', tunable=TunableResourceKey(None, (sims4.resources.Types.PROPX,), description='The sound to play.')), key_type=Tunable(str, None, source_location=clip_actor_asm_source, source_query=clip_actor_state_source, source_sub_query=sound_sub_query)), props=TunableMapping(description='\n                The props overrides.\n                ', value_type=TunableTuple(definition=TunableReference(description='\n                        The object to create to replace the prop\n                        ', manager=services.definition_manager()), from_actor=Tunable(description='\n                        The actor name inside the asm to copy the state over.\n                        ', tunable_type=str, default=None), states_to_override=TunableList(description='\n                        A list of states that will be transferred from\n                        the specified actor to the overridden prop.\n                        ', tunable=TunableReference(description='\n                            The state to apply on the props from the actor listed above.\n                            ', manager=services.get_instance_manager(sims4.resources.Types.OBJECT_STATE), class_restrictions='ObjectState')))), prop_state_values=TunableMapping(description='\n                Tunable mapping from a prop actor name to a list of state\n                values to set. If conflicting data is tuned both here and in\n                the "props" field, the data inside "props" will override the\n                data tuned here.\n                ', value_type=TunableList(description='\n                    A list of state values that will be set on the specified\n                    actor.\n                    ', tunable=TunableReference(description='\n                        A new state value to apply to prop_actor.\n                        ', manager=services.get_instance_manager(sims4.resources.Types.OBJECT_STATE), class_restrictions='ObjectStateValue'))), manifests=TunableList(description='\n                Manifests is a complex and seldom used override that lets you \n                change entries in the posture manifest from the ASM.\n                You can see how the fields, Actor, Family, Level, Specific, \n                Left, Right, and Surface, match the manifest entries in the \n                ASM. \n                ', tunable=TunableTuple(key=TunablePostureManifestOverrideKey(asm_source=asm_source), value=TunablePostureManifestOverrideValue(asm_source=asm_source))), required_slots=TunableList(TunableRequiredSlotOverride(asm_source=asm_source), description='Required slot overrides'), balloons=OptionalTunable(TunableList(description='\n                Balloons lets you add thought and talk balloons to animations. \n                This is a great way to put extra flavor into animations and \n                helps us stretch our content by creating combinations.\n                Balloon Animation Target is the participant who should display \n                the balloon.\n                Balloon Choices is a reference to the balloon to display, which \n                is its own tunable type.\n                Balloon Delay (and Random Offset) is how long, in real seconds, \n                to delay this balloon after the animation starts.  Note: for \n                looping animations, the balloon will always play immediately \n                due to a code limitation.\n                Balloon Target is for showing a balloon of a Sim or Object. \n                Set this to the participant type to show. This setting \n                overrides Balloon Choices. \n                ', tunable=TunableBalloon())), animation_context=Tunable(description="\n                Animation Context - If checked, this animation will get a fresh \n                animation context instead of reusing the animation context of \n                its Interaction.\n                Normally, animation contexts are shared across an entire Super \n                Interaction. This allows mixers to use a fresh animation \n                context.\n                Ex: If a mixer creates a prop, using a fresh animation context \n                will cause that prop to be destroyed when the mixer finishes, \n                whereas re-using an existing animation context will cause the \n                prop to stick around until the mixer's SI is done. \n                ", tunable_type=bool, default=override_animation_context), description=description, **kwargs)

class TunableAnimationObjectOverrides(TunableAnimationOverrides):
    __qualname__ = 'TunableAnimationObjectOverrides'
    LOCKED_ARGS = {'manifests': None, 'required_slots': None, 'balloons': None, 'reactionlet': None}

    def __init__(self, description='Animation overrides to apply to every ASM to which this object is added.', **kwargs):
        super().__init__(locked_args=TunableAnimationObjectOverrides.LOCKED_ARGS, **kwargs)

def get_asm_name(asm_key):
    return asm_key

def get_asm_supported_posture(asm_key, actor_name, overrides):
    context = get_throwaway_animation_context()
    posture_manifest_overrides = None
    if overrides is not None:
        posture_manifest_overrides = overrides.manifests
    asm = animation.asm.Asm(asm_key, context, posture_manifest_overrides=posture_manifest_overrides)
    return asm.get_supported_postures_for_actor(actor_name)

def disable_asm_auto_exit(sim, sequence):
    was_locked = None

    def lock(_):
        nonlocal was_locked
        was_locked = sim.asm_auto_exit.locked
        sim.asm_auto_exit.locked = True

    def unlock(_):
        sim.asm_auto_exit.locked = was_locked

    return build_critical_section(lock, sequence, unlock)

logged_missing_interaction_callstack = False

class AnimationElement(HasTunableReference, elements.ParentElement, metaclass=TunedInstanceMetaclass, manager=services.animation_manager()):
    __qualname__ = 'AnimationElement'
    ASM_SOURCE = 'asm_key'
    INSTANCE_TUNABLES = {ASM_SOURCE: TunableResourceKey(description='\n            ASM Key is the Animation State Machine to use for this animation. \n            You are selecting from the ASMs that are in your \n            Assets/InGame/Statemachines folder, and several of the subsequent \n            fields are populated by information from this selection. \n            ', default=None, resource_types=[sims4.resources.Types.STATEMACHINE], category='asm'), 'actor_name': Tunable(description="\n            Actor Name is the name of the main actor for this animation. In \n            almost every case this will just be 'x', so please be absolutely \n            sure you know what you're doing when changing this value.\n            ", tunable_type=str, default='x', source_location=ASM_SOURCE, source_query=SourceQueries.ASMActorSim), 'target_name': Tunable(description='\n            This determines which actor the target of the interaction will be. \n            In general, this should be the object that will be clicked on to \n            create interactions that use this content.\n            This helps the posture system understand what objects you already \n            know about and which to search for. Sit says its target name is \n            sitTemplate, which means you have to sit in the chair that was \n            clicked on, whereas Eat says its target name is consumable, which \n            means you can sit in any chair in the world to eat. This ends up \n            in the var_map in the runtime. \n            ', tunable_type=str, default=None, source_location=ASM_SOURCE, source_query=SourceQueries.ASMActorAll), 'carry_target_name': Tunable(description='\n            Carry Target Name is the actor name of the carried object in this \n            ASM. This is only relevant if the Target and Carry Target are \n            different. \n            ', tunable_type=str, default=None, source_location=ASM_SOURCE, source_query=SourceQueries.ASMActorObject), 'create_target_name': Tunable(description="\n            Create Target Name is the actor name of an object that will be \n            created by this interaction. This is used frequently in the \n            crafting system but rarely elsewhere. If your interaction creates \n            an object in the Sim's hand, use this. \n            ", tunable_type=str, default=None, source_location=ASM_SOURCE, source_query=SourceQueries.ASMActorObject), 'initial_state': OptionalTunable(description="\n             The name of the initial state in the ASM to use when begin_states \n             are requested. \n             If this is untuned, which should be the case almost all the time, \n             it will use the default initial state of 'entry'. Ask your \n             animation partner if you think you want to tune this because you \n             should not have to and it is probably best to just change the \n             structure of the ASM. Remember that ASMs are re-used within a \n             single interaction, so if you are defining an outcome animation, \n             you can rely on the state to persist from the basic content.\n             ", tunable=Tunable(tunable_type=str, default=None, source_location='../' + ASM_SOURCE, source_query=SourceQueries.ASMState), disabled_value=DEFAULT, disabled_name='use_default', enabled_name='custom_state_name'), 'begin_states': TunableList(description='\n             A list of states in the ASM to run through at the beginning of \n             this element. Generally-speaking, you should always use \n             begin_states for all your state requests. The only time you would \n             need end_states is when you are making a staging-SuperInteraction. \n             In that case, the content in begin_states happens when the SI \n             first runs, before it stages, and the content in end_states will \n             happen as the SI is exiting. When in doubt, put all of your state \n             requests here.\n             ', tunable=str, source_location=ASM_SOURCE, source_query=SourceQueries.ASMState), '_overrides': TunableAnimationOverrides(description='\n            Overrides are for expert-level configuration of Animation Elements. \n            In 95% of cases, the animation element will work perfectly with no \n            overrides.\n            Overrides allow us to customize animations further using things \n            like vfx changes and also to account for some edge cases. \n            ', asm_source=ASM_SOURCE, state_source='begin_states'), 'end_states': TunableList(description="\n             A list of states to run through at the end of this element. This \n             should generally be one of two values:\n             * empty (default), which means to do no requests. This is best if \n             you don't know what to use here, as auto-exit behavior, which \n             automatically requests the 'exit' state on any ASM that is still \n             active, should handle most cases for you. Note: this is not safe \n             for elements that are used as the staging content for SIs! \n             See below!\n             * 'exit', which requests the content on the way out of the \n             statemachine. This is important to set for SuperInteractions that \n             are set to use staging basic content, as auto-exit behavior is \n             disabled in that case. This means the content on the way to exit \n             will be requested as the SI is finishing. You can put additional \n             state requests here if the ASM is more complex, but that is very \n             rare.\n             ", tunable=str, source_location=ASM_SOURCE, source_query=SourceQueries.ASMState), 'repeat': Tunable(description='\n            If this is checked, then the begin_states will loop until the\n            controlling sequence (e.g. the interaction) ends. At that point,\n            end_states will play.\n            \n            This tunable allows you to create looping one-shot states. The\n            effects of this tunable on already looping states is undefined.\n            ', tunable_type=bool, default=False, tuning_filter=FilterTag.EXPERT_MODE)}
    _child_animations = None
    _child_constraints = None

    def __init__(self, interaction=UNSET, setup_asm_additional=None, setup_asm_override=DEFAULT, overrides=None, use_asm_cache=True, **animate_kwargs):
        global logged_missing_interaction_callstack
        super().__init__()
        self.interaction = None if interaction is UNSET else interaction
        self.setup_asm_override = setup_asm_override
        self.setup_asm_additional = setup_asm_additional
        if overrides is not None:
            overrides = overrides()
        if interaction.anim_overrides is not None:
            overrides = interaction.anim_overrides(overrides=overrides)
        if not (interaction is not UNSET and interaction is not None and interaction.is_super):
            super_interaction = self.interaction.super_interaction
            if super_interaction is not None and (super_interaction.basic_content is not None and super_interaction.basic_content.content_set is not None) and super_interaction.basic_content.content_set.balloon_overrides is not None:
                balloons = super_interaction.basic_content.content_set.balloon_overrides
                overrides = overrides(balloons=balloons)
        self.overrides = self._overrides(overrides=overrides)
        self.animate_kwargs = animate_kwargs
        self._use_asm_cache = use_asm_cache
        if not (interaction is None and logged_missing_interaction_callstack):
            logger.callstack('Attempting to set up animation {} with interaction=None.', self, level=sims4.log.LEVEL_ERROR, owner='jpollak')
            logged_missing_interaction_callstack = True

    @classmethod
    def _verify_tuning_callback(cls):
        if cls.carry_target_name is not None and cls.create_target_name is not None:
            logger.error('Animation {} has specified both a carry target ({}) and a create target ({}).  This is not supported.', cls, cls.carry_target_name, cls.create_target_name, owner='tastle')

    @flexmethod
    def get_supported_postures(cls, inst):
        if inst is not None and inst.interaction is not None:
            asm = inst.get_asm()
            if asm is not None:
                return asm.get_supported_postures_for_actor(cls.actor_name)
        else:
            overrides = cls._overrides()
            return get_asm_supported_posture(cls.asm_key, cls.actor_name, overrides)
        return PostureManifest()

    @classproperty
    def name(cls):
        return get_asm_name(cls.asm_key)

    @classmethod
    def register_tuned_animation(cls, *args):
        if cls._child_animations is None:
            cls._child_animations = []
        cls._child_animations.append(args)

    @classmethod
    def add_auto_constraint(cls, *args, **kwargs):
        if cls._child_constraints is None:
            cls._child_constraints = []
        cls._child_constraints.append(args)

    def get_asm(self, use_cache=True, **kwargs):
        asm = self.interaction.get_asm(self.asm_key, self.actor_name, self.target_name, self.carry_target_name, setup_asm_override=self.setup_asm_override, posture_manifest_overrides=self.overrides.manifests, use_cache=self._use_asm_cache and use_cache, create_target_name=self.create_target_name, **kwargs)
        if asm is None:
            return
        if self.setup_asm_additional is not None:
            self.setup_asm_additional(asm)
        return asm

    @classmethod
    def append_to_arb(cls, asm, arb):
        for state_name in cls.begin_states:
            asm.request(state_name, arb)

    @classmethod
    def append_exit_to_arb(cls, asm, arb):
        for state_name in cls.end_states:
            asm.request(state_name, arb)

    def get_constraint(self, participant_type=ParticipantType.Actor):
        from interactions.constraints import Anywhere, create_animation_constraint
        if participant_type == ParticipantType.Actor:
            actor_name = self.actor_name
            target_name = self.target_name
        elif participant_type == ParticipantType.TargetSim:
            actor_name = self.target_name
            target_name = self.actor_name
        else:
            return Anywhere()
        return create_animation_constraint(self.asm_key, actor_name, target_name, self.carry_target_name, self.create_target_name, self.initial_state, self.begin_states, self.overrides)

    @property
    def reactionlet(self):
        if self.overrides is not None:
            return self.overrides.reactionlet

    @classproperty
    def run_in_sequence(cls):
        return True

    @classproperty
    def has_multiple_elements(cls):
        return False

    @classmethod
    def animation_element_gen(cls):
        yield cls

    def _run(self, timeline):
        global logged_missing_interaction_callstack
        if self.interaction is None:
            if not logged_missing_interaction_callstack:
                logger.callstack('Attempting to run an animation {} without a corresponding interaction.', self, level=sims4.log.LEVEL_ERROR)
                logged_missing_interaction_callstack = True
            return False
        if self.asm_key is None:
            return True
        asm = self.get_asm()
        if asm is None:
            return False
        if self.overrides.balloons:
            balloon_requests = TunableBalloon.get_balloon_requests(self.interaction, self.overrides)
        else:
            balloon_requests = None
        success = timeline.run_child(animate_states(asm, self.begin_states, self.end_states, overrides=self.overrides, balloon_requests=balloon_requests, repeat_begin_states=self.repeat, interaction=self.interaction, **self.animate_kwargs))
        return success

class AnimationElementSet(metaclass=TunedInstanceMetaclass, manager=services.animation_manager()):
    __qualname__ = 'AnimationElementSet'
    INSTANCE_TUNABLES = {'_animation_and_overrides': TunableList(description='\n            The list of the animations which get played in sequence\n            ', tunable=TunableTuple(anim_element=AnimationElement.TunableReference(), overrides=TunableAnimationOverrides(), carry_requirements=TunableTuple(description='\n                    Specify whether the Sim must be carrying objects with\n                    specific animation properties in order to animate this\n                    particular element.\n                    ', params=TunableParameterMapping(description='\n                        A carried object must override and match these animation\n                        parameters in order for it to be valid.\n                        '), actor=Tunable(description='\n                        The carried object that fulfills the param requirements\n                        will be set as this actor on the selected element.\n                        ', tunable_type=str, default=None))))}

    def __new__(cls, interaction=None, setup_asm_additional=None, setup_asm_override=DEFAULT, overrides=None, sim=DEFAULT, **animate_kwargs):
        best_supported_posture = None
        best_anim_element_type = None
        best_carry_actor_and_object = None
        for animation_and_overrides in cls._animation_and_overrides:
            if overrides is not None:
                if callable(overrides):
                    overrides = overrides()
                overrides = animation_and_overrides.overrides(overrides=overrides)
            else:
                overrides = animation_and_overrides.overrides()
            anim_element_type = animation_and_overrides.anim_element
            if best_anim_element_type is None:
                best_anim_element_type = anim_element_type
            if interaction is None:
                logger.warn('Attempting to initiate AnimationElementSet {} without interaction, it will just construct the first AnimationElement {}.', cls.name, anim_element_type.name)
                break
            sim = sim if sim is not DEFAULT else interaction.sim
            carry_actor_name = animation_and_overrides.carry_requirements.actor
            if carry_actor_name:
                from carry import get_carried_objects_gen
                for (_, _, carry_object) in get_carried_objects_gen(sim):
                    carry_object_params = carry_object.get_anim_overrides(carry_actor_name).params
                    while all(carry_object_params[k] == v for (k, v) in animation_and_overrides.carry_requirements.params.items()):
                        break
            postures = anim_element_type.get_supported_postures()
            sim_posture_state = sim.posture_state
            from postures import get_best_supported_posture
            surface_target = MATCH_ANY if sim_posture_state.surface_target is not None else MATCH_NONE
            provided_postures = sim_posture_state.body.get_provided_postures(surface_target=surface_target)
            best_element_supported_posture = get_best_supported_posture(provided_postures, postures, sim_posture_state.get_carry_state(), ignore_carry=False)
            while best_element_supported_posture is not None:
                if best_supported_posture is None or best_element_supported_posture < best_supported_posture:
                    best_supported_posture = best_element_supported_posture
                    best_anim_element_type = anim_element_type
                    if carry_actor_name:
                        best_carry_actor_and_object = (carry_actor_name, carry_object)
                    else:
                        best_carry_actor_and_object = None
        if best_carry_actor_and_object is not None:
            setup_asm_additional_override = setup_asm_additional

            def setup_asm_additional(asm):
                if not asm.set_actor(best_carry_actor_and_object[0], best_carry_actor_and_object[1], actor_participant=AnimationParticipant.CREATE_TARGET):
                    return False
                from carry import set_carry_track_param_if_needed
                set_carry_track_param_if_needed(asm, sim, best_carry_actor_and_object[0], best_carry_actor_and_object[1])
                if setup_asm_additional_override is not None:
                    setup_asm_additional_override(asm)

        best_anim_element = best_anim_element_type(interaction=interaction, setup_asm_additional=setup_asm_additional, setup_asm_override=setup_asm_override, overrides=overrides, **animate_kwargs)
        return best_anim_element

    @classproperty
    def run_in_sequence(cls):
        return False

    @classproperty
    def has_multiple_elements(cls):
        raise RuntimeError('[bhill] This function is believed to be dead code and is scheduled for pruning. If this exception has been raised, the code is not dead and this exception should be removed.')
        return True

    @classmethod
    def animation_element_gen(cls):
        for animation_and_overrides in cls._animation_and_overrides:
            yield animation_and_overrides.anim_element

    @flexmethod
    def get_supported_postures(cls, inst):
        if inst is not None and inst.interaction is not None:
            asm = inst.get_asm()
            if asm is not None:
                return asm.get_supported_postures_for_actor(cls.actor_name)
        supported_postures = PostureManifest()
        for animation_and_overrides in cls._animation_and_overrides:
            supported_postures.update(animation_and_overrides.anim_element.get_supported_postures())
        return supported_postures

    @classproperty
    def name(cls):
        return cls.__name__

class AnimationTriplet(metaclass=TunedInstanceMetaclass, manager=services.animation_manager()):
    __qualname__ = 'AnimationTriplet'
    INSTANCE_TUNABLES = {'intro': OptionalTunable(TunableReference(manager=services.animation_manager(), class_restrictions=AnimationElement)), 'success': OptionalTunable(TunableReference(manager=services.animation_manager(), class_restrictions=AnimationElement)), 'failure': OptionalTunable(TunableReference(manager=services.animation_manager(), class_restrictions=AnimationElement))}

class AnimationTripletList(metaclass=TunedInstanceMetaclass, manager=services.animation_manager()):
    __qualname__ = 'AnimationTripletList'
    INSTANCE_TUNABLES = {'list': TunableList(TunableReference(manager=services.animation_manager(), class_restrictions=AnimationTriplet))}

class ObjectAnimationElement(elements.ParentElement, metaclass=TunedInstanceMetaclass, manager=services.animation_manager()):
    __qualname__ = 'ObjectAnimationElement'
    ASM_SOURCE = 'asm_key'
    INSTANCE_TUNABLES = {ASM_SOURCE: TunableResourceKey(None, resource_types=[sims4.resources.Types.STATEMACHINE], description='The ASM to use.', category='asm'), 'actor_name': Tunable(str, None, source_location=ASM_SOURCE, source_query=SourceQueries.ASMActorAll, description='The name of the actor in the ASM.'), 'initial_state': OptionalTunable(tunable=Tunable(str, None, source_location='../' + ASM_SOURCE, source_query=SourceQueries.ASMState, description='The name of the initial state in the ASM you expect your actor to be in when running this AnimationElement. If you do not tune this we will use the entry state which is usually what you want.'), disabled_value=DEFAULT, disabled_name='use_default', enabled_name='custom_state_name'), 'begin_states': TunableList(str, source_location=ASM_SOURCE, source_query=SourceQueries.ASMState, description='A list of states to play.'), 'end_states': TunableList(str, source_location=ASM_SOURCE, source_query=SourceQueries.ASMState, description='A list of states to play after looping.')}

    def __init__(self, owner, use_asm_cache=True, **animate_kwargs):
        super().__init__()
        self.owner = owner
        self.animate_kwargs = animate_kwargs
        self._use_asm_cache = use_asm_cache

    @classmethod
    def append_to_arb(cls, asm, arb):
        for state_name in cls.begin_states:
            asm.request(state_name, arb)

    @classmethod
    def append_exit_to_arb(cls, asm, arb):
        for state_name in cls.end_states:
            asm.request(state_name, arb)

    def get_asm(self, use_cache=True, **kwargs):
        idle_component = self.owner.get_component(IDLE_COMPONENT)
        if idle_component is None:
            return
        asm = idle_component.get_asm(self.asm_key, self.actor_name, use_cache=self._use_asm_cache and use_cache, **kwargs)
        return asm

    def _run(self, timeline):
        if self.asm_key is None:
            return True
        asm = self.get_asm()
        if asm is None:
            return False
        return timeline.run_child(animate_states(asm, self.begin_states, self.end_states, **self.animate_kwargs))

