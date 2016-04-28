from animation.posture_manifest import AnimationParticipant, PostureManifestEntry, MATCH_ANY, PostureManifest, SlotManifest
from carry import PARAM_CARRY_TRACK
from interactions.constraints import Anywhere
from interactions.utils.animation_reference import TunableAnimationReference
from objects.components import ComponentMetaclass
from postures.posture_specs import PostureSpecVariable
from postures.posture_state_spec import PostureStateSpec
from sims4.tuning.tunable import HasTunableFactory, TunableVariant, TunableList, AutoFactoryInit, HasTunableSingletonFactory
import interactions.constraints

class GenericAnimation(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'GenericAnimation'
    FACTORY_TUNABLES = {'constraints': TunableList(description='\n                The list of constraints that the Sim will fulfill before\n                using the generic animation.\n                \n                Example:\n                    A cone constraint and a facing constraint to get the\n                    Sim to stand in front of and facing the object.\n                ', tunable=interactions.constraints.TunableConstraintVariant())}

    def get_access_animation_factory(self, is_put):
        if is_put:
            return GetPutComponentMixin.GENERIC_PUT_ANIMATION
        return GetPutComponentMixin.GENERIC_GET_ANIMATION

    def get_access_constraint(self, put, inventory_owner):
        entries = []
        entries.append(PostureManifestEntry(None, MATCH_ANY, MATCH_ANY, MATCH_ANY, MATCH_ANY, MATCH_ANY, inventory_owner))
        surface_posture_manifest = PostureManifest(entries)
        surface_posture_state_spec = PostureStateSpec(surface_posture_manifest, SlotManifest().intern(), PostureSpecVariable.ANYTHING)
        constraint_total = interactions.constraints.Constraint(debug_name='Required Surface For Generic Get Put', posture_state_spec=surface_posture_state_spec)
        for constraint_factory in self.constraints:
            constraint = constraint_factory.create_constraint(None, target=inventory_owner)
            constraint_total = constraint_total.intersect(constraint)
        return constraint_total

class CustomAnimation(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'CustomAnimation'
    FACTORY_TUNABLES = {'get': TunableAnimationReference(callback=None), 'put': TunableAnimationReference(callback=None)}

    def get_access_animation_factory(self, is_put):
        if is_put:
            return self.put
        return self.get

    def get_access_constraint(self, is_put, inventory_owner):
        animation_factory = self.get_access_animation_factory(is_put)
        if animation_factory is None:
            return
        constraint = animation_factory().get_constraint()
        return constraint

class GetPutComponentMixin(HasTunableFactory, metaclass=ComponentMetaclass):
    __qualname__ = 'GetPutComponentMixin'
    GENERIC_GET_ANIMATION = TunableAnimationReference()
    GENERIC_PUT_ANIMATION = TunableAnimationReference()
    GENERIC_CONSTRAINT = Anywhere()

    @classmethod
    def register_tuned_animation(cls, *_, **__):
        pass

    @classmethod
    def add_auto_constraint(cls, participant_type, tuned_constraint, **kwargs):
        cls.GENERIC_CONSTRAINT = cls.GENERIC_CONSTRAINT.intersect(tuned_constraint)

    FACTORY_TUNABLES = {'get_put': TunableVariant(description='\n                This controls the behavior of a Sim who wants to get from or\n                put to the component owner.\n                ', default='none', locked_args={'none': None}, generic=GenericAnimation.TunableFactory(), custom=CustomAnimation.TunableFactory())}

    def __init__(self, *args, get_put=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._get_put = get_put

    def _get_access_constraint(self, sim, is_put, carry_target, resolver=None):
        if self._get_put is None:
            return
        constraint = self._get_put.get_access_constraint(is_put, self.owner)

        def constraint_resolver(animation_participant, default=None):
            if resolver is not None:
                result = resolver(animation_participant, default=default)
                if result is not default:
                    return result
            if animation_participant == AnimationParticipant.ACTOR:
                return sim
            if animation_participant in (AnimationParticipant.CARRY_TARGET, AnimationParticipant.TARGET):
                return carry_target
            if animation_participant == AnimationParticipant.SURFACE:
                return self.owner
            return default

        concrete_constraint = constraint.apply_posture_state(None, constraint_resolver)
        return concrete_constraint

    def get_surface_target(self, sim):
        inv_owner = self.owner
        body_target = sim.posture.target
        if body_target is not None and body_target.inventory_component is not None and body_target.inventory_component.inventory_type == inv_owner.inventory_component.inventory_type:
            return body_target
        return inv_owner

    def _get_access_animation(self, is_put):
        if self._get_put is None:
            return
        animation_factory = self._get_put.get_access_animation_factory(is_put)
        if animation_factory is None:
            return

        def append_animations(arb, sim, carry_target, carry_track, animation_context, surface_height):
            asm = sim.posture.get_asm(animation_context, animation_factory.asm_key, None, use_cache=False)
            asm.set_parameter('surfaceHeight', surface_height)
            sim.posture.setup_asm_interaction(asm, sim, None, animation_factory.actor_name, None, carry_target=carry_target, carry_target_name=animation_factory.carry_target_name, surface_target=self.get_surface_target(sim), carry_track=carry_track)
            asm.set_actor_parameter(animation_factory.carry_target_name, carry_target, PARAM_CARRY_TRACK, carry_track.name.lower())
            animation_factory.append_to_arb(asm, arb)
            animation_factory.append_exit_to_arb(asm, arb)

        return append_animations

