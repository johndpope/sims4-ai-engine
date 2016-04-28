import functools
from animation.posture_manifest import Hand, PostureManifest, PostureManifestEntry, MATCH_ANY, SlotManifest, MATCH_NONE, AnimationParticipant
from distributor.system import Distributor
from element_utils import build_critical_section, build_critical_section_with_finally, must_run, build_element
from interactions import ParticipantType
from interactions.aop import AffordanceObjectPair
from interactions.context import InteractionContext, QueueInsertStrategy
from interactions.priority import Priority
from interactions.utils.animation import ArbElement, animate, flush_all_animations, create_run_animation, disable_asm_auto_exit
from objects import VisibilityState
from postures import PostureTrack, AllPosturesType, ALL_POSTURES, create_posture
from postures.posture_specs import PostureSpecVariable, PostureOperation, SURFACE_INDEX, SURFACE_SLOT_TYPE_INDEX, SURFACE_SLOT_TARGET_INDEX, SURFACE_TARGET_INDEX
from postures.posture_state_spec import PostureStateSpec
from postures.transition import PostureTransition
from sims4.tuning.tunable import TunableFactory, TunableReference, Tunable, TunableEnumEntry
from singletons import DEFAULT
import animation.arb
import element_utils
import elements
import interactions.constraints
import postures
import services
import sims4.log
import sims4.service_manager
logger = sims4.log.Logger('Carry')
SCRIPT_EVENT_ID_START_CARRY = 700
SCRIPT_EVENT_ID_STOP_CARRY = 701

class CarryPostureStaticTuning:
    __qualname__ = 'CarryPostureStaticTuning'
    POSTURE_CARRY_NOTHING = TunableReference(description='\n            Reference to the posture that represents carrying nothing\n            ', manager=services.get_instance_manager(sims4.resources.Types.POSTURE), class_restrictions='CarryingNothing')
    POSTURE_CARRY_OBJECT = TunableReference(description='\n        Reference to the posture that represents carrying an Object\n        ', manager=services.get_instance_manager(sims4.resources.Types.POSTURE), class_restrictions='CarryingObject')

PARAM_CARRY_TRACK = 'carryTrack'
PARAM_CARRY_STATE = 'carryState'

def set_carry_track_param_if_needed(asm, sim, carry_target_name, carry_target, carry_track=DEFAULT):
    posture_carry_track = sim.posture_state.get_carry_track(carry_target)
    if posture_carry_track is not None:
        carry_track = posture_carry_track
    if carry_track is None or carry_track is DEFAULT:
        return False
    return set_carry_track_param(asm, carry_target_name, carry_target, carry_track)

def set_carry_track_param(asm, carry_target_name, carry_target, carry_track):
    if asm.set_actor_parameter(carry_target_name, carry_target, PARAM_CARRY_TRACK, carry_track.name.lower()):
        return True
    if asm.set_parameter('carrytrack', carry_track.name.lower()):
        logger.warn('Parameter carrytrack in {} should be renamed to {}:carryTrack.', asm.name, carry_target_name)
        return True
    return False

def create_enter_carry_posture(sim, posture_state, carry_target, track):
    from postures.posture_state import PostureState
    var_map = {PostureSpecVariable.CARRY_TARGET: carry_target, PostureSpecVariable.HAND: PostureState.track_to_hand(track), PostureSpecVariable.POSTURE_TYPE_CARRY_OBJECT: CarryPostureStaticTuning.POSTURE_CARRY_OBJECT}
    pick_up_operation = PostureOperation.PickUpObject(PostureSpecVariable.POSTURE_TYPE_CARRY_OBJECT, PostureSpecVariable.CARRY_TARGET)
    new_source_aop = pick_up_operation.associated_aop(sim, var_map)
    new_posture_spec = pick_up_operation.apply(posture_state.get_posture_spec(var_map), enter_carry_while_holding=True)
    if new_posture_spec is None:
        raise RuntimeError('[jpollak] Failed to create new_posture_spec in enter_carry_while_holding!')
    new_posture_state = PostureState(sim, posture_state, new_posture_spec, var_map)
    new_posture = new_posture_state.get_aspect(track)
    from carry.carry_postures import CarryingNothing
    if new_posture is None or isinstance(new_posture, CarryingNothing):
        raise RuntimeError('[jpollak] Failed to create a valid new_posture ({}) from new_posture_state ({}) in enter_carry_while_holding!'.format(new_posture, new_posture_state))
    new_posture.external_transition = True
    return (new_posture_state, new_posture, new_source_aop, var_map)

def enter_carry_while_holding(si, obj=None, carry_obj_participant_type=None, callback=None, create_si_fn=DEFAULT, sim_participant_type=ParticipantType.Actor, carry_posture_id=DEFAULT, owning_affordance=DEFAULT, sequence=None, carry_sim=DEFAULT, track=DEFAULT):
    sim = si.get_participant(sim_participant_type) if carry_sim is DEFAULT else carry_sim
    context = si.context.clone_for_sim(sim)
    if carry_obj_participant_type is not None:
        obj = si.get_participant(carry_obj_participant_type)
        if obj is None:
            raise ValueError('[bhill] Attempt to perform an enter carry while holding with None as the carried object. SI: {}'.format(si))
    if track is DEFAULT:
        track = si.carry_track
    if track is None:
        raise RuntimeError("[jpollak] enter_carry_while_holding: Interaction does not have a carry_track, which means its animation tuning doesn't have a carry target or create target specified in object editor or the posture manifest from the swing graph does not require a specific object.")
    if carry_posture_id is DEFAULT:
        carry_posture_id = CarryPostureStaticTuning.POSTURE_CARRY_OBJECT
    if create_si_fn is DEFAULT:
        if owning_affordance is DEFAULT:
            raise AssertionError("[bhill] No create_si_fn was provided and we don't know how to make one.")

        def create_si_fn():
            aop = AffordanceObjectPair(owning_affordance, obj, owning_affordance, None)
            return (aop, context)

    def set_up_transition_gen(timeline):
        nonlocal sequence
        (new_posture_state, new_posture, new_source_aop, var_map) = create_enter_carry_posture(sim, sim.posture_state, obj, track)
        got_callback = False

        def event_handler_enter_carry(event_data):
            nonlocal got_callback
            if got_callback:
                logger.warn('Animation({}) calling to start a carry multiple times', event_data.event_data.get('clip_name'))
                return
            got_callback = True
            arb = animation.arb.Arb()
            locked_params = new_posture.get_locked_params(None)
            old_carry_posture = sim.posture_state.get_aspect(track)
            if old_carry_posture is not None:
                old_carry_posture.append_exit_to_arb(arb, new_posture_state, new_posture, var_map)
            new_posture.append_transition_to_arb(arb, old_carry_posture, locked_params=locked_params, in_xevt_handler=True)
            ArbElement(arb).distribute()

        si.animation_context.register_event_handler(event_handler_enter_carry, handler_id=SCRIPT_EVENT_ID_START_CARRY)

        def maybe_do_transition_gen(timeline):

            def push_si_gen(timeline):
                context = InteractionContext(sim, InteractionContext.SOURCE_POSTURE_GRAPH, si.priority, run_priority=si.run_priority, insert_strategy=QueueInsertStrategy.NEXT, must_run_next=True, group_id=si.group_id)
                result = new_source_aop.interaction_factory(context)
                if not result:
                    return result
                source_interaction = result.interaction
                new_posture.source_interaction = source_interaction
                owning_interaction = None
                if create_si_fn is not None:
                    (aop, context) = create_si_fn()
                    if aop is not None and context is not None and aop.test(context):
                        result = aop.interaction_factory(context)
                        if result:
                            owning_interaction = result.interaction
                            owning_interaction.acquire_posture_ownership(new_posture)
                            aop.execute_interaction(owning_interaction)
                if owning_interaction is None:
                    si.acquire_posture_ownership(new_posture)
                yield source_interaction.run_direct_gen(timeline)
                return result

            def call_callback(_):
                if callback is not None:
                    callback(new_posture, new_posture.source_interaction)

            if got_callback:
                result = yield element_utils.run_child(timeline, must_run([PostureTransition(new_posture, new_posture_state, context, var_map), push_si_gen, call_callback]))
                return result
            return True

        sequence = disable_asm_auto_exit(sim, sequence)
        with si.cancel_deferred((si,)):
            yield element_utils.run_child(timeline, must_run(build_critical_section(build_critical_section(sequence, flush_all_animations), maybe_do_transition_gen)))

    return build_element(set_up_transition_gen)

def create_exit_carry_posture(sim, target, interaction, use_posture_animations):
    from postures.posture_state import PostureState
    failure_result = (None, None, None, None, None)
    slot_manifest = interaction.slot_manifest
    old_carry_posture = sim.posture_state.get_carry_posture(target)
    if old_carry_posture is None:
        return failure_result
    spec_surface = sim.posture_state.spec[SURFACE_INDEX]
    if spec_surface is not None and spec_surface[SURFACE_SLOT_TYPE_INDEX] is not None:
        put_down_operation = PostureOperation.PutDownObjectOnSurface(PostureSpecVariable.POSTURE_TYPE_CARRY_NOTHING, spec_surface[SURFACE_TARGET_INDEX], spec_surface[SURFACE_SLOT_TYPE_INDEX], PostureSpecVariable.CARRY_TARGET)
    else:
        put_down_operation = PostureOperation.PutDownObject(PostureSpecVariable.POSTURE_TYPE_CARRY_NOTHING, PostureSpecVariable.CARRY_TARGET)
    var_map = {PostureSpecVariable.CARRY_TARGET: target, PostureSpecVariable.HAND: PostureState.track_to_hand(old_carry_posture.track), PostureSpecVariable.POSTURE_TYPE_CARRY_NOTHING: CarryPostureStaticTuning.POSTURE_CARRY_NOTHING, PostureSpecVariable.SLOT: slot_manifest, PostureSpecVariable.SLOT_TEST_DEFINITION: interaction.create_target}
    current_spec = sim.posture_state.get_posture_spec(var_map)
    if current_spec is None:
        logger.warn('Failed to get posture spec for var_map: {} for {}', sim.posture_state, var_map)
        return failure_result
    new_posture_spec = put_down_operation.apply(current_spec)
    if new_posture_spec is None:
        logger.warn('Failed to apply put_down_operation: {}', put_down_operation)
        return failure_result
    if not new_posture_spec.validate_destination((new_posture_spec,), var_map, interaction.affordance):
        logger.warn('Failed to validate put down spec {}  with var map {}', new_posture_spec, var_map)
        return failure_result
    new_posture_state = PostureState(sim, sim.posture_state, new_posture_spec, var_map)
    new_posture = new_posture_state.get_aspect(old_carry_posture.track)
    new_posture.source_interaction = interaction.super_interaction
    new_posture.external_transition = not use_posture_animations
    posture_context = postures.context.PostureContext(interaction.context.source, interaction.priority, None)
    transition = postures.transition.PostureTransition(new_posture, new_posture_state, posture_context, var_map)
    transition.must_run = True
    return (old_carry_posture, new_posture, new_posture_state, transition, var_map)

def exit_carry_while_holding(interaction, callback=None, sequence=None, sim_participant_type=ParticipantType.Actor, use_posture_animations=False, carry_system_target=None):
    si = interaction.super_interaction
    sim = interaction.get_participant(sim_participant_type)
    target = interaction.carry_target or interaction.target

    def set_up_transition_gen(timeline):
        (old_carry_posture, new_posture, _, transition, var_map) = create_exit_carry_posture(sim, target, interaction, use_posture_animations)
        if transition is None:
            yield element_utils.run_child(timeline, sequence)
            return
        exited_carry = False
        if not use_posture_animations:

            def event_handler_exit_carry(event_data):
                nonlocal exited_carry
                exited_carry = True
                arb = animation.arb.Arb()
                old_carry_posture.append_exit_to_arb(arb, None, new_posture, var_map, exit_while_holding=True)
                new_posture.append_transition_to_arb(arb, old_carry_posture, in_xevt_handler=True)
                ArbElement(arb, master=sim).distribute()

            interaction.animation_context.register_event_handler(event_handler_exit_carry, handler_id=SCRIPT_EVENT_ID_STOP_CARRY)
        if callback is not None:
            interaction.animation_context.register_event_handler(callback, handler_id=SCRIPT_EVENT_ID_STOP_CARRY)

        def maybe_do_transition(timeline):
            if not use_posture_animations and not exited_carry:
                event_handler_exit_carry(None)
                if callback is not None:
                    callback()
            if use_posture_animations or exited_carry:
                interaction_target_was_target = False
                si_target_was_target = False
                if interaction.target == target:
                    interaction_target_was_target = True
                    interaction.set_target(None)
                if old_carry_posture.target_is_transient and si.target == target:
                    si_target_was_target = True
                    si.set_target(None)
                if carry_system_target is not None:
                    old_carry_posture.carry_system_target = carry_system_target

                def do_transition(timeline):
                    result = yield element_utils.run_child(timeline, transition)
                    if result:
                        interaction_target_was_target = False
                        si_target_was_target = False
                        new_posture.source_interaction = None
                        return True
                    return False

                def post_transition(_):
                    if interaction_target_was_target:
                        interaction.set_target(target)
                    if si_target_was_target:
                        si.set_target(target)
                    if carry_system_target is not None:
                        old_carry_posture.carry_system_target = None

                yield element_utils.run_child(timeline, must_run(build_critical_section_with_finally(do_transition, post_transition)))

        new_sequence = disable_asm_auto_exit(sim, sequence)
        yield element_utils.run_child(timeline, build_critical_section(build_critical_section(new_sequence, flush_all_animations), maybe_do_transition))

    return build_element(set_up_transition_gen)

def swap_carry_while_holding(interaction, original_carry_target, new_carry_object, callback=None, sequence=None, sim_participant_type=ParticipantType.Actor, carry_system_target=None):
    si = interaction.super_interaction
    sim = interaction.get_participant(sim_participant_type)

    def set_up_transition(timeline):
        (original_carry_posture, carry_nothing_posture, carry_nothing_posture_state, transition_to_carry_nothing, carry_nothing_var_map) = create_exit_carry_posture(sim, original_carry_target, interaction, False)
        if transition_to_carry_nothing is None:
            return False
        (final_posture_state, final_posture, final_source_aop, final_var_map) = create_enter_carry_posture(sim, carry_nothing_posture_state, new_carry_object, original_carry_posture.track)
        got_callback = False

        def event_handler_swap_carry(event_data):
            nonlocal got_callback
            if got_callback:
                logger.warn('Animation({}) calling to start a carry multiple times', event_data.event_data.get('clip_name'))
                return
            got_callback = True
            arb_exit = animation.arb.Arb()
            original_carry_posture.append_exit_to_arb(arb_exit, None, carry_nothing_posture, carry_nothing_var_map, exit_while_holding=True)
            carry_nothing_posture.append_transition_to_arb(arb_exit, original_carry_posture, in_xevt_handler=True)
            ArbElement(arb_exit).distribute()
            original_carry_posture.target.transient = True
            original_carry_posture.target.clear_parent(sim.transform, sim.routing_surface)
            original_carry_posture.target.remove_from_client()
            arb_enter = animation.arb.Arb()
            locked_params = final_posture.get_locked_params(None)
            if carry_nothing_posture is not None:
                carry_nothing_posture.append_exit_to_arb(arb_enter, final_posture_state, final_posture, final_var_map)
            final_posture.append_transition_to_arb(arb_enter, carry_nothing_posture, locked_params=locked_params, in_xevt_handler=True)
            ArbElement(arb_enter).distribute()

        interaction.animation_context.register_event_handler(event_handler_swap_carry, handler_id=SCRIPT_EVENT_ID_START_CARRY)
        if callback is not None:
            interaction.animation_context.register_event_handler(callback, handler_id=SCRIPT_EVENT_ID_START_CARRY)

        def maybe_do_transition(timeline):

            def push_si(_):
                context = InteractionContext(sim, InteractionContext.SOURCE_POSTURE_GRAPH, si.priority, run_priority=si.run_priority, insert_strategy=QueueInsertStrategy.NEXT, must_run_next=True, group_id=si.group_id)
                result = final_source_aop.interaction_factory(context)
                if not result:
                    return result
                final_source_interaction = result.interaction
                si.acquire_posture_ownership(final_posture)
                yield final_source_interaction.run_direct_gen(timeline)
                final_posture.source_interaction = final_source_interaction
                return result

            if not got_callback:
                event_handler_swap_carry(None)
                if callback is not None:
                    callback()
            if original_carry_posture.target_is_transient:
                if interaction.target == original_carry_target:
                    interaction_target_was_target = True
                    interaction.set_target(None)
                else:
                    interaction_target_was_target = False
                if si.target == original_carry_target:
                    si_target_was_target = True
                    si.set_target(None)
                else:
                    si_target_was_target = False
            else:
                interaction_target_was_target = False
                si_target_was_target = False
            if carry_system_target is not None:
                original_carry_posture.carry_system_target = carry_system_target

            def do_transition(timeline):
                nonlocal interaction_target_was_target, si_target_was_target
                result = yield element_utils.run_child(timeline, transition_to_carry_nothing)
                if not result:
                    return False
                interaction_target_was_target = False
                si_target_was_target = False
                carry_nothing_posture.source_interaction = None
                return True

            def post_transition(_):
                if interaction_target_was_target:
                    interaction.set_target(original_carry_target)
                if si_target_was_target:
                    si.set_target(original_carry_target)
                if carry_system_target is not None:
                    original_carry_posture.carry_system_target = None

            exit_carry_result = yield element_utils.run_child(timeline, must_run(build_critical_section_with_finally(do_transition, post_transition)))
            if not (got_callback and exit_carry_result):
                raise RuntimeError('[maxr] Failed to exit carry: {}'.format(original_carry_posture))
            if got_callback:
                context = si.context.clone_for_sim(sim)
                yield element_utils.run_child(timeline, (PostureTransition(final_posture, final_posture_state, context, final_var_map), push_si))

        new_sequence = disable_asm_auto_exit(sim, sequence)
        yield element_utils.run_child(timeline, build_critical_section(build_critical_section(new_sequence, flush_all_animations), maybe_do_transition))

    return (set_up_transition,)

class TunableEnterCarryWhileHolding(TunableFactory):
    __qualname__ = 'TunableEnterCarryWhileHolding'
    FACTORY_TYPE = staticmethod(enter_carry_while_holding)

    def __init__(self, *args, description='Enter the carry for the target or carry_target of an interaction. The animations played during the interaction should exit the carry via an XEVT.', **kwargs):
        super().__init__(carry_obj_participant_type=TunableEnumEntry(description='\n                The object that will be carried.\n                ', tunable_type=ParticipantType, default=ParticipantType.CarriedObject), sim_participant_type=TunableEnumEntry(description='\n                The Sim that will get a new carry.\n                ', tunable_type=ParticipantType, default=ParticipantType.Actor), owning_affordance=TunableReference(description='\n                The interaction that will be pushed that will own the carry\n                state (e.g. a put down).\n                ', manager=services.get_instance_manager(sims4.resources.Types.INTERACTION)), description=description, *args, **kwargs)

class TunableExitCarryWhileHolding(TunableFactory):
    __qualname__ = 'TunableExitCarryWhileHolding'
    FACTORY_TYPE = staticmethod(exit_carry_while_holding)

    def __init__(self, *args, description='Exit the carry for the target or carry_target of an interaction.  The animations played during the interaction should exit the carry via an XEVT.', **kwargs):
        super().__init__(description=description, sim_participant_type=TunableEnumEntry(description='\n                 The Sim that will exit a carry.\n                 ', tunable_type=ParticipantType, default=ParticipantType.Actor), *args, **kwargs)

def interact_with_carried_object(sim, target, posture_state=DEFAULT, interaction=None, create_target_track=None, animation_context=None, must_run=False, sequence=()):
    if interaction.staging and sim.posture_state.is_source_or_owning_interaction(interaction):
        return sequence
    if not must_run and interaction is not None and interaction.disable_carry_interaction_mask:
        return sequence
    is_carrying_other_object = False
    animation_contexts = set()
    target_ref = target.ref() if target is not None else None

    def maybe_do_begin(_):
        nonlocal posture_state, is_carrying_other_object
        if posture_state is DEFAULT:
            posture_state = sim.posture_state
        try:
            resolved_target = target_ref() if target_ref is not None else None
            if create_target_track is None:
                target_track = posture_state.get_carry_track(resolved_target)
                if target_track is None:
                    return
                other_carry = posture_state.get_other_carry_posture(resolved_target)
                if other_carry is None or other_carry.holstered:
                    return
            else:
                other_carry = posture_state.right if create_target_track == PostureTrack.LEFT else posture_state.left
                if other_carry.target is None:
                    return
        finally:
            del posture_state
        is_carrying_other_object = True
        if animation_context is not None:
            animation_contexts.add(animation_context)
        if interaction is not None:
            animation_contexts.add(interaction.animation_context)
        for context in animation_contexts:
            context.apply_carry_interaction_mask.append('x')

    def maybe_do_end(_):
        if not is_carrying_other_object:
            return
        for context in animation_contexts:
            context.apply_carry_interaction_mask.remove('x')

    return build_critical_section_with_finally(maybe_do_begin, sequence, maybe_do_end)

def _get_holstering_setup_asm_func(carry_posture, carry_object):

    def setup_asm(asm):
        old_location = carry_object.location.clone()
        hide_carry_handle = None
        show_carry_handle = None

        def show_carry_object(_):
            carry_object.location = old_location
            carry_object.visibility = VisibilityState(True, True, False)
            carry_posture._event_handler_start_pose()
            show_carry_handle.release()

        def hide_carry_object(_):
            asm.set_current_state('entry')
            carry_object.visibility = VisibilityState(False, False, False)
            hide_carry_handle.release()

        hide_carry_handle = asm.context.register_event_handler(hide_carry_object, handler_id=SCRIPT_EVENT_ID_STOP_CARRY)
        show_carry_handle = asm.context.register_event_handler(show_carry_object, handler_id=SCRIPT_EVENT_ID_START_CARRY)
        asm.set_parameter('surfaceHeight', 'inventory')

    return setup_asm

def holster_carried_object(sim, interaction, unholster_predicate, flush_before_sequence=False, sequence=None):
    holstered_objects = []
    if interaction is not None and interaction.can_holster_incompatible_carries:
        for (_, carry_posture) in interaction.get_uncarriable_objects_gen(allow_holster=False, use_holster_compatibility=True):
            holstered_objects.append(carry_posture.target)
            while not carry_posture.holstered:
                sequence = holster_object(carry_posture, flush_before_sequence=flush_before_sequence, sequence=sequence)
    for (_, carry_posture, carry_object) in get_carried_objects_gen(sim):
        while carry_posture.holstered:
            if carry_object not in holstered_objects and unholster_predicate(carry_object):
                sequence = unholster_object(carry_posture, flush_before_sequence=flush_before_sequence, sequence=sequence)
    return sequence

def holster_objects_for_route(sim, sequence=None):
    for aspect in sim.posture_state.carry_aspects:
        while aspect.target is not None and aspect.target.holster_while_routing:
            sequence = holster_object(aspect, flush_before_sequence=True, sequence=sequence)
    return sequence

def hide_held_props(sim, data):
    if sim.id not in data.actors:
        return
    for si in sim.si_state:
        si.animation_context.set_all_prop_visibility(False, held_only=True)

def holster_object(carry_posture, flush_before_sequence=False, sequence=None):
    carry_object = carry_posture.target

    def _set_holster():
        carry_posture.holstered = True
        return True

    import postures.posture_interactions
    carry_nothing_posture = create_posture(postures.posture_interactions.HoldNothing.CARRY_NOTHING_POSTURE_TYPE, carry_posture.sim, None, track=carry_posture.track)

    def holster(timeline):

        def stop_carry(*_, **__):
            idle_arb = animation.arb.Arb()
            carry_nothing_posture.asm.request(carry_nothing_posture._state_name, idle_arb)
            ArbElement(idle_arb).distribute()

        arb_holster = animation.arb.Arb()
        arb_holster.register_event_handler(stop_carry, handler_id=SCRIPT_EVENT_ID_STOP_CARRY)
        carry_posture.asm.context.register_custom_event_handler(functools.partial(hide_held_props, carry_posture.sim), None, 0, allow_stub_creation=True)
        setup_asm_fn_carry = _get_holstering_setup_asm_func(carry_posture, carry_object)
        setup_asm_fn_carry(carry_posture.asm)
        carry_posture.asm.request(carry_posture._exit_state_name, arb_holster)
        carry_nothing_posture.setup_asm_posture(carry_nothing_posture.asm, carry_nothing_posture.sim, None)
        setup_asm_fn_carry_nothing = _get_holstering_setup_asm_func(carry_nothing_posture, carry_object)
        setup_asm_fn_carry_nothing(carry_nothing_posture.asm)
        carry_nothing_posture.asm.request(carry_nothing_posture._enter_state_name, arb_holster)
        holster_element = create_run_animation(arb_holster)
        if flush_before_sequence:
            holster_element = (holster_element, flush_all_animations)
        yield element_utils.run_child(timeline, holster_element)

    return (lambda _: _set_holster(), build_critical_section(interact_with_carried_object(carry_posture.sim, carry_object, interaction=carry_posture.source_interaction, animation_context=carry_posture.asm.context, must_run=True, sequence=holster), sequence, flush_all_animations))

def unholster_object(carry_posture, flush_before_sequence=False, sequence=None):
    carry_object = carry_posture.target

    def _set_unholster():
        carry_posture.holstered = False
        return True

    def unholster(timeline):
        arb_unholster = animation.arb.Arb()

        def start_carry(*_, **__):
            idle_arb = animation.arb.Arb()
            carry_posture.asm.request(carry_posture._state_name, idle_arb)
            ArbElement(idle_arb).distribute()

        arb_unholster.register_event_handler(start_carry, handler_id=SCRIPT_EVENT_ID_START_CARRY)
        carry_posture.asm.context.register_custom_event_handler(functools.partial(hide_held_props, carry_posture.sim), None, 0, allow_stub_creation=True)
        carry_posture.asm.set_current_state('entry')
        carry_posture.asm.request(carry_posture._enter_state_name, arb_unholster)
        unholster_element = create_run_animation(arb_unholster)
        if flush_before_sequence:
            unholster_element = (unholster_element, flush_all_animations)
        yield element_utils.run_child(timeline, unholster_element)

    return build_critical_section(interact_with_carried_object(carry_posture.sim, carry_object, animation_context=carry_posture.asm.context, interaction=carry_posture.source_interaction, must_run=True, sequence=build_critical_section(unholster, lambda _: _set_unholster())), sequence, flush_all_animations)

def can_carry_object(posture_manifest, posture_type, hand):
    raise RuntimeError('[bhill] This function is believed to be dead code and is scheduled for pruning. If this exception has been raised, the code is not dead and this exception should be removed.')
    if posture_manifest is ALL_POSTURES:
        return True
    for posture_entry in posture_manifest:
        while posture_type in posture_entry.posture_types:
            if hand in posture_entry.free_hands:
                return True
    return False

def get_carried_objects_gen(sim):
    posture_left = sim.posture_state.left
    if posture_left is not None and posture_left.target is not None:
        yield (Hand.LEFT, posture_left, posture_left.target)
    posture_right = sim.posture_state.right
    if posture_right is not None and posture_right.target is not None:
        yield (Hand.RIGHT, posture_right, posture_right.target)

def create_carry_nothing_constraint(hand, debug_name='CarryNothing'):
    entries = []
    if hand == Hand.LEFT:
        entries = (PostureManifestEntry(None, MATCH_ANY, MATCH_ANY, MATCH_ANY, MATCH_NONE, MATCH_ANY, MATCH_ANY),)
    else:
        entries = (PostureManifestEntry(None, MATCH_ANY, MATCH_ANY, MATCH_ANY, MATCH_ANY, MATCH_NONE, MATCH_ANY),)
    carry_posture_manifest = PostureManifest(entries)
    carry_posture_state_spec = PostureStateSpec(carry_posture_manifest, SlotManifest().intern(), PostureSpecVariable.ANYTHING)
    return interactions.constraints.Constraint(debug_name=debug_name, posture_state_spec=carry_posture_state_spec)

def create_carry_constraint(target, hand=DEFAULT, strict=False, debug_name='CarryGeneric'):
    if strict and target is None:
        target = MATCH_NONE
    entries = []
    if hand is DEFAULT or hand == Hand.LEFT:
        entries.append(PostureManifestEntry(None, MATCH_ANY, MATCH_ANY, MATCH_ANY, target, MATCH_ANY, MATCH_ANY))
    if hand is DEFAULT or hand == Hand.RIGHT:
        entries.append(PostureManifestEntry(None, MATCH_ANY, MATCH_ANY, MATCH_ANY, MATCH_ANY, target, MATCH_ANY))
    carry_posture_manifest = PostureManifest(entries)
    carry_posture_state_spec = PostureStateSpec(carry_posture_manifest, SlotManifest().intern(), PostureSpecVariable.ANYTHING)
    return interactions.constraints.Constraint(debug_name=debug_name, posture_state_spec=carry_posture_state_spec)

