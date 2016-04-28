from animation.posture_manifest import Hand, SlotManifest
from interactions.constraints import Anywhere, Constraint
from objects.definition import Definition
from objects.object_enums import ResetReason
from postures import PostureTrack, posture_specs
from postures.posture_interactions import HoldNothing
from postures.posture_specs import PostureSpecVariable, BODY_INDEX, BODY_POSTURE_TYPE_INDEX, BODY_TARGET_INDEX, SURFACE_INDEX, SURFACE_TARGET_INDEX, CARRY_INDEX, CARRY_TARGET_INDEX, CARRY_POSTURE_TYPE_INDEX, CARRY_HAND_INDEX, SURFACE_SLOT_TYPE_INDEX, PostureAspectCarry, PostureAspectSurface, get_carry_posture_aop
from postures.posture_state_spec import PostureStateSpec
from sims4.repr_utils import standard_repr
import carry
import postures
import sims4.log
logger = sims4.log.Logger('Postures')

class PostureState:
    __qualname__ = 'PostureState'

    def _get_default_carry_aspect(self, track):
        return postures.create_posture(HoldNothing.CARRY_NOTHING_POSTURE_TYPE, self.sim, None, track=track)

    def __init__(self, sim, current_posture_state, posture_spec, var_map, invalid_expected=False, body_state_spec_only=False):
        self._constraint_intersection = None
        self._constraint_intersection_dirty = True
        self._spec = posture_spec
        self._sim_ref = sim.ref()
        self._linked_posture_state = None
        self._valid = True
        self._constraints = {}
        self._invalid_expected = invalid_expected
        self.body_state_spec_only = body_state_spec_only
        self._posture_constraint = None
        self._posture_constraint_strict = None
        body_index = BODY_INDEX
        body_posture_type_index = BODY_POSTURE_TYPE_INDEX
        body_target_index = BODY_TARGET_INDEX
        spec_body = posture_spec[body_index]
        self.body_target = spec_body[body_target_index]
        if current_posture_state is None or spec_body[body_posture_type_index] != current_posture_state.body.posture_type or spec_body[body_target_index] != current_posture_state.body.target:
            animation_context = None
            if current_posture_state is not None and not current_posture_state.body.mobile and not spec_body[body_posture_type_index].mobile:
                animation_context = current_posture_state.body.animation_context
            self._aspect_body = postures.create_posture(spec_body[body_posture_type_index], self.sim, self.body_target, animation_context=animation_context)
        else:
            self._aspect_body = current_posture_state.body
        posture_manifest = self._aspect_body.get_provided_postures(surface_target=self.surface_target, concrete=True)
        posture_manifest = posture_manifest.get_constraint_version(self.sim)
        posture_state_spec = PostureStateSpec(posture_manifest, SlotManifest(), self._aspect_body.target or PostureSpecVariable.ANYTHING)
        self.body_posture_state_constraint = Constraint(debug_name='PostureStateManifestConstraint', posture_state_spec=posture_state_spec)
        if body_state_spec_only:
            self._constraints[self] = self.body_posture_state_constraint
            return
        body_slot_constraint = self._aspect_body.slot_constraint
        if body_slot_constraint is not None:
            body_posture_constraint = self.body_posture_state_constraint.intersect(body_slot_constraint)
        else:
            body_posture_constraint = self.body_posture_state_constraint
        self._constraints[self] = body_posture_constraint
        if current_posture_state is not None:
            curr_spec_carry_target = current_posture_state.get_posture_spec(var_map)[CARRY_INDEX][CARRY_TARGET_INDEX]
        spec_carry = posture_spec[CARRY_INDEX]
        spec_carry_target = spec_carry[CARRY_TARGET_INDEX]
        if current_posture_state is not None and spec_carry_target != curr_spec_carry_target:
            if spec_carry_target is None:
                current_carry_target = var_map.get(curr_spec_carry_target)
                current_carry_track = current_posture_state.get_carry_track(current_carry_target)
                if current_carry_track == PostureTrack.RIGHT:
                    self._aspect_carry_right = self._get_default_carry_aspect(PostureTrack.RIGHT)
                    self._aspect_carry_left = current_posture_state.left
                else:
                    self._aspect_carry_left = self._get_default_carry_aspect(PostureTrack.LEFT)
                    self._aspect_carry_right = current_posture_state.right
                    spec_carry_posture_type = spec_carry[CARRY_POSTURE_TYPE_INDEX]
                    if spec_carry_target not in var_map:
                        raise KeyError
                    if spec_carry_posture_type not in var_map:
                        aop = posture_specs.get_carry_posture_aop(sim, var_map[spec_carry_target])
                        carry_posture_type = aop.affordance._carry_posture_type
                        if carry_posture_type is None:
                            raise KeyError
                        var_map += {PostureSpecVariable.POSTURE_TYPE_CARRY_OBJECT: carry_posture_type}
                    carry_target = var_map[spec_carry_target]
                    carry_posture_type = var_map[spec_carry_posture_type]
                    if spec_carry[CARRY_HAND_INDEX] in var_map:
                        hand = var_map[spec_carry[CARRY_HAND_INDEX]]
                    else:
                        for hand in sim.posture_state.get_free_hands():
                            while hand in carry_target.allowed_hands:
                                break
                        raise RuntimeError('No allowable free hand was empty.')
                    new_carry_aspect = postures.create_posture(carry_posture_type, self.sim, carry_target, track=self.hand_to_track(hand))
                    if hand == Hand.LEFT:
                        self._aspect_carry_left = new_carry_aspect
                        if current_posture_state is not None:
                            self._aspect_carry_right = current_posture_state.right
                        else:
                            self._aspect_carry_right = self._get_default_carry_aspect(PostureTrack.RIGHT)
                            if hand == Hand.RIGHT:
                                self._aspect_carry_right = new_carry_aspect
                                if current_posture_state is not None:
                                    self._aspect_carry_left = current_posture_state.left
                                else:
                                    self._aspect_carry_right = self._get_default_carry_aspect(PostureTrack.LEFT)
                                    raise RuntimeError('Invalid value specified for hand: {}'.format(hand))
                            else:
                                raise RuntimeError('Invalid value specified for hand: {}'.format(hand))
                    elif hand == Hand.RIGHT:
                        self._aspect_carry_right = new_carry_aspect
                        if current_posture_state is not None:
                            self._aspect_carry_left = current_posture_state.left
                        else:
                            self._aspect_carry_right = self._get_default_carry_aspect(PostureTrack.LEFT)
                            raise RuntimeError('Invalid value specified for hand: {}'.format(hand))
                    else:
                        raise RuntimeError('Invalid value specified for hand: {}'.format(hand))
            else:
                spec_carry_posture_type = spec_carry[CARRY_POSTURE_TYPE_INDEX]
                if spec_carry_target not in var_map:
                    raise KeyError
                if spec_carry_posture_type not in var_map:
                    aop = posture_specs.get_carry_posture_aop(sim, var_map[spec_carry_target])
                    carry_posture_type = aop.affordance._carry_posture_type
                    if carry_posture_type is None:
                        raise KeyError
                    var_map += {PostureSpecVariable.POSTURE_TYPE_CARRY_OBJECT: carry_posture_type}
                carry_target = var_map[spec_carry_target]
                carry_posture_type = var_map[spec_carry_posture_type]
                if spec_carry[CARRY_HAND_INDEX] in var_map:
                    hand = var_map[spec_carry[CARRY_HAND_INDEX]]
                else:
                    for hand in sim.posture_state.get_free_hands():
                        while hand in carry_target.allowed_hands:
                            break
                    raise RuntimeError('No allowable free hand was empty.')
                new_carry_aspect = postures.create_posture(carry_posture_type, self.sim, carry_target, track=self.hand_to_track(hand))
                if hand == Hand.LEFT:
                    self._aspect_carry_left = new_carry_aspect
                    if current_posture_state is not None:
                        self._aspect_carry_right = current_posture_state.right
                    else:
                        self._aspect_carry_right = self._get_default_carry_aspect(PostureTrack.RIGHT)
                        if hand == Hand.RIGHT:
                            self._aspect_carry_right = new_carry_aspect
                            if current_posture_state is not None:
                                self._aspect_carry_left = current_posture_state.left
                            else:
                                self._aspect_carry_right = self._get_default_carry_aspect(PostureTrack.LEFT)
                                raise RuntimeError('Invalid value specified for hand: {}'.format(hand))
                        else:
                            raise RuntimeError('Invalid value specified for hand: {}'.format(hand))
                elif hand == Hand.RIGHT:
                    self._aspect_carry_right = new_carry_aspect
                    if current_posture_state is not None:
                        self._aspect_carry_left = current_posture_state.left
                    else:
                        self._aspect_carry_right = self._get_default_carry_aspect(PostureTrack.LEFT)
                        raise RuntimeError('Invalid value specified for hand: {}'.format(hand))
                else:
                    raise RuntimeError('Invalid value specified for hand: {}'.format(hand))
        elif current_posture_state is not None:
            self._aspect_carry_left = current_posture_state.left
            self._aspect_carry_right = current_posture_state.right
        elif spec_carry_target is not None:
            carry_target = var_map[spec_carry_target]
            spec_carry_posture_type = spec_carry[CARRY_POSTURE_TYPE_INDEX]
            carry_posture_type = var_map.get(spec_carry_posture_type)
            if carry_posture_type is None:
                aop = get_carry_posture_aop(sim, carry_target)
                if aop is None and invalid_expected:
                    return
                carry_posture_type = aop.affordance._carry_posture_type
            if spec_carry[CARRY_HAND_INDEX] in var_map:
                hand = var_map[spec_carry[CARRY_HAND_INDEX]]
            else:
                hand = carry_target.allowed_hands[0]
            new_carry_aspect = postures.create_posture(carry_posture_type, self.sim, carry_target, track=self.hand_to_track(hand))
            if hand == Hand.LEFT:
                self._aspect_carry_left = new_carry_aspect
                self._aspect_carry_right = self._get_default_carry_aspect(PostureTrack.RIGHT)
            else:
                self._aspect_carry_right = new_carry_aspect
                self._aspect_carry_left = self._get_default_carry_aspect(PostureTrack.LEFT)
        else:
            self._aspect_carry_left = self._get_default_carry_aspect(PostureTrack.LEFT)
            self._aspect_carry_right = self._get_default_carry_aspect(PostureTrack.RIGHT)

    def __repr__(self):
        return standard_repr(self, *self.aspects)

    @property
    def valid(self):
        return self._valid and bool(self.constraint_intersection)

    @property
    def spec(self):
        return self._spec

    def get_posture_spec(self, var_map):
        if not var_map:
            return self._spec.clone()
        carry_target = var_map.get(PostureSpecVariable.CARRY_TARGET) or var_map.get(PostureSpecVariable.INTERACTION_TARGET)
        if carry_target is not None and carry_target.definition is not carry_target and carry_target.carryable_component is not None:
            carry_posture = self.get_carry_posture(carry_target)
        else:
            carry_posture = None
        if carry_posture is not None:
            if PostureSpecVariable.HAND in var_map:
                required_hand = PostureState.track_to_hand(carry_posture.track)
                if required_hand != var_map[PostureSpecVariable.HAND]:
                    return
            source_carry = PostureAspectCarry((PostureSpecVariable.POSTURE_TYPE_CARRY_OBJECT, PostureSpecVariable.CARRY_TARGET, PostureSpecVariable.HAND))
        else:
            source_carry = PostureAspectCarry((PostureSpecVariable.POSTURE_TYPE_CARRY_NOTHING, None, PostureSpecVariable.HAND))
        surface_spec = self._spec[SURFACE_INDEX]
        surface_target = surface_spec[SURFACE_TARGET_INDEX]
        if surface_target is not None:
            var_map_surface_target = var_map.get(PostureSpecVariable.SURFACE_TARGET, None)
            if var_map_surface_target is None or surface_target == var_map_surface_target:
                var_map_carry_target = var_map.get(PostureSpecVariable.CARRY_TARGET, PostureSpecVariable.CARRY_TARGET)
                if carry_target is not None and (carry_posture is None and carry_target.definition is not carry_target) and not carry_target.is_surface(include_parts=True):
                    surface_spec = PostureAspectSurface((surface_target, PostureSpecVariable.SLOT, PostureSpecVariable.CARRY_TARGET))
                    spec = self._spec.clone(carry=source_carry, surface=surface_spec)
                    if spec._validate_surface(var_map) and (var_map_carry_target is None or var_map_carry_target.parent is surface_target):
                        return spec
                surface_spec = PostureAspectSurface((surface_target, PostureSpecVariable.SLOT, None))
                spec = self._spec.clone(carry=source_carry, surface=surface_spec)
                if spec._validate_surface(var_map):
                    return spec
            surface_spec = PostureAspectSurface((surface_target, None, None))
            spec = self._spec.clone(carry=source_carry, surface=surface_spec)
            if spec._validate_surface(var_map):
                return spec
        surface_spec = PostureAspectSurface((None, None, None))
        spec = self._spec.clone(carry=source_carry, surface=surface_spec)
        if spec._validate_surface(var_map):
            return spec

    def _get_posture_constraint(self, strict=False):
        posture_state_constraint = self.body_posture_state_constraint
        posture_state_constraint = posture_state_constraint.get_holster_version()
        if posture_state_constraint.valid and not self.body_state_spec_only:
            carry_left_constraint = carry.create_carry_constraint(self.left.target, Hand.LEFT, strict=strict)
            posture_state_constraint = posture_state_constraint.intersect(carry_left_constraint)
            if posture_state_constraint.valid:
                carry_right_constraint = carry.create_carry_constraint(self.right.target, Hand.RIGHT, strict=strict)
                posture_state_constraint = posture_state_constraint.intersect(carry_right_constraint)
        return posture_state_constraint

    @property
    def posture_constraint(self):
        if self._posture_constraint is None:
            self._posture_constraint = self._get_posture_constraint()
        return self._posture_constraint

    @property
    def posture_constraint_strict(self):
        if self._posture_constraint_strict is None:
            self._posture_constraint_strict = self._get_posture_constraint(strict=True)
        return self._posture_constraint_strict

    @property
    def sim(self):
        if self._sim_ref is not None:
            return self._sim_ref()

    @property
    def linked_posture_state(self):
        return self._linked_posture_state

    @linked_posture_state.setter
    def linked_posture_state(self, posture_state):
        self._set_linked_posture_state(posture_state)
        posture_state._set_linked_posture_state(self)
        self.body.linked_posture = posture_state.body

    def _set_linked_posture_state(self, posture_state):
        self._linked_posture_state = posture_state

    @property
    def body(self):
        return self._aspect_body

    @property
    def left(self):
        return self._aspect_carry_left

    @property
    def right(self):
        return self._aspect_carry_right

    @property
    def aspects(self):
        if self.body_state_spec_only:
            return ()
        return (self.body, self.left, self.right)

    @property
    def carry_aspects(self):
        return (self.left, self.right)

    @property
    def surface_target(self):
        surface = self._spec[SURFACE_INDEX][SURFACE_TARGET_INDEX]
        if (surface is None or self.body.mobile) and self.body.target is not None and self.body.target.is_surface():
            return self.body.target
        return surface

    @property
    def carry_targets(self):
        return (self.left.target, self.right.target)

    def get_aspect(self, track):
        if track == PostureTrack.BODY:
            return self.body
        if track == PostureTrack.LEFT:
            return self.left
        if track == PostureTrack.RIGHT:
            return self.right

    @property
    def has_geometry(self):
        raise RuntimeError('[bhill] This function is believed to be dead code and is scheduled for pruning. If this exception has been raised, the code is not dead and this exception should be removed.')
        constraint_insteraction = self.constraint_intersection
        if constraint_insteraction is not None:
            for constraint in constraint_insteraction:
                while constraint.geometry is not None:
                    return True
        return False

    def add_constraint(self, handle, constraint):
        if not constraint.valid:
            logger.error('Attempt to add an invalid constraint {} to posture_state {}.', constraint, self, owner='bhill', trigger_breakpoint=True)
        test_constraint = self.constraint_intersection.intersect(constraint)
        if not (self._invalid_expected or test_constraint.valid):
            logger.warn('Attempt to add a constraint to {} which is incompatible with already-registered constraints: {} + {}.', self, constraint, self.constraint_intersection)
        self._constraints[handle] = constraint
        self._constraint_intersection_dirty = True

    def remove_constraint(self, handle):
        if handle in self._constraints:
            del self._constraints[handle]
            self._constraint_intersection_dirty = True
            self._constraint_intersection = None

    @property
    def constraint_intersection(self):
        if self._constraint_intersection_dirty:
            intersection = Anywhere()
            for constraint in set(self._constraints.values()):
                new_intersection = intersection.intersect(constraint)
                if not self._invalid_expected and not new_intersection.valid:
                    logger.error('Invalid constraint intersection for PostureState:{}', self)
                    intersection = new_intersection
                    break
                intersection = new_intersection
            self._constraint_intersection_dirty = False
            self._constraint_intersection = intersection
        return self._constraint_intersection

    def compatible_with(self, constraint):
        intersection = self.constraint_intersection
        if not intersection.valid:
            return False
        intersection = constraint.intersect(intersection)
        if not intersection.valid:
            return False
        return True

    def compatible_with_pre_resolve(self, constraint):
        for constraint_existing in self._constraints.values():
            while constraint_existing is constraint:
                return True
        return self.compatible_with(constraint)

    def get_slot_info(self):
        surface = self._spec[SURFACE_INDEX]
        return (surface[SURFACE_TARGET_INDEX], surface[SURFACE_SLOT_TYPE_INDEX])

    def is_source_interaction(self, si):
        if si is not None:
            for aspect in self.aspects:
                while aspect.source_interaction is si:
                    return True
        return False

    def is_source_or_owning_interaction(self, si):
        return self.get_source_or_owned_posture_for_si(si) is not None

    def is_carry_source_or_owning_interaction(self, si):
        return self.get_source_or_owned_posture_for_si(si, carry_only=True) is not None

    def get_source_or_owned_posture_for_si(self, si, carry_only=False):
        if self.left.source_interaction is si or si in self.left.owning_interactions:
            return self.left
        if self.right.source_interaction is si or si in self.right.owning_interactions:
            return self.right
        if carry_only:
            return
        if self.body.source_interaction is si or si in self.body.owning_interactions:
            return self.body

    def _hand_to_track(self, hand) -> PostureTrack:
        raise RuntimeError('[bhill] This function is believed to be dead code and is scheduled for pruning. If this exception has been raised, the code is not dead and this exception should be removed.')
        if hand == Hand.LEFT:
            return PostureTrack.LEFT
        return PostureTrack.RIGHT

    def _track_to_hand(self, track) -> Hand:
        raise RuntimeError('[bhill] This function is believed to be dead code and is scheduled for pruning. If this exception has been raised, the code is not dead and this exception should be removed.')
        if track == PostureTrack.LEFT:
            return Hand.LEFT
        return Hand.RIGHT

    @property
    def connectivity_handles(self):
        if self.body.target is not None:
            return self.body.target.connectivity_handles

    def kickstart_gen(self, timeline):
        for aspect in self.aspects:
            yield aspect.kickstart_gen(timeline, self)
        self._valid = True

    def on_reset(self, reset_reason):
        for aspect in self.aspects:
            aspect.reset()
        self._valid = False

    def _carrying(self, track, **kwargs):
        posture = self.left if track == PostureTrack.LEFT else self.right
        return self._carrying_posture(posture, **kwargs)

    def _carrying_posture(self, posture, ignore_target=None, only_target=None):
        if posture is not None and posture.is_active_carry:
            if ignore_target is None and only_target is None:
                return True
            target = posture.target

            def target_is(other):
                if target is None:
                    return False
                if isinstance(other, int):
                    return target.definition.id == other
                if isinstance(other, Definition):
                    return target.definition == other
                return target is other

            if ignore_target is None or not target_is(ignore_target):
                if only_target is None or target_is(only_target):
                    return True
        return False

    def get_carry_state(self, target=None, override_posture=None):
        if override_posture is not None:
            if override_posture.track == PostureTrack.LEFT:
                carry_state = (self._carrying_posture(override_posture, ignore_target=target), self._carrying(PostureTrack.RIGHT, ignore_target=target))
            else:
                carry_state = (self._carrying(PostureTrack.LEFT, ignore_target=target), self._carrying_posture(override_posture, ignore_target=target))
        else:
            carry_state = (self._carrying(PostureTrack.LEFT, ignore_target=target), self._carrying(PostureTrack.RIGHT, ignore_target=target))
        return carry_state

    def get_carry_track(self, target):
        if target is None:
            return
        if self._carrying(PostureTrack.LEFT, only_target=target):
            return PostureTrack.LEFT
        if self._carrying(PostureTrack.RIGHT, only_target=target):
            return PostureTrack.RIGHT

    def is_carrying(self, target):
        if self.get_carry_track(target) is not None:
            return True
        return False

    def get_carry_posture(self, target):
        if self.left.target is target:
            return self.left
        if self.right.target is target:
            return self.right

    def get_posture_for_si(self, si):
        for posture in self.aspects:
            while posture is not None and posture.source_interaction == si:
                return posture

    def get_other_carry_posture(self, target):
        track = self.get_carry_track(target)
        if track is None:
            return
        if track is PostureTrack.LEFT:
            result = self.get_aspect(PostureTrack.RIGHT)
        else:
            result = self.get_aspect(PostureTrack.LEFT)
        if result is not None and result.target is not None:
            return result

    def get_free_carry_track(self, obj=None) -> PostureTrack:
        if obj is not None and obj.carryable_component is None:
            logger.error('Obj {} has no carryable component.', obj, owner='tastle')
            return
        allowed_hands = obj.carryable_component.allowed_hands if obj is not None else (Hand.RIGHT, Hand.LEFT)
        if self.sim.handedness == Hand.RIGHT:
            preferred_track = PostureTrack.RIGHT
            unpreferred_track = PostureTrack.LEFT
        else:
            preferred_track = PostureTrack.LEFT
            unpreferred_track = PostureTrack.RIGHT
        if self.track_to_hand(preferred_track) in allowed_hands and not self._carrying(preferred_track):
            return preferred_track
        if self.track_to_hand(unpreferred_track) in allowed_hands and not self._carrying(unpreferred_track):
            return unpreferred_track

    def get_free_hands(self):
        if not self._carrying(PostureTrack.RIGHT):
            if not self._carrying(PostureTrack.LEFT):
                return (Hand.RIGHT, Hand.LEFT)
            return (Hand.RIGHT,)
        if not self._carrying(PostureTrack.LEFT):
            return (Hand.LEFT,)
        return ()

    @staticmethod
    def hand_to_track(hand) -> PostureTrack:
        if hand == Hand.LEFT:
            return PostureTrack.LEFT
        return PostureTrack.RIGHT

    @staticmethod
    def track_to_hand(track) -> Hand:
        if track == PostureTrack.LEFT:
            return Hand.LEFT
        return Hand.RIGHT

