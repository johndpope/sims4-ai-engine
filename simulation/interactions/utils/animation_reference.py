from collections import defaultdict
from native.animation import ASM_ACTORTYPE_SIM
from animation import get_throwaway_animation_context
from interactions import ParticipantType
from interactions.interaction_instance_manager import should_use_animation_constaint_cache
from sims4 import reload
from sims4.tuning.tunable import TunableReferenceFactory, TunableSingletonFactory
from singletons import DEFAULT
import animation.asm
import services
import sims4.log
logger = sims4.log.Logger('Animation')
with reload.protected(globals()):
    _animation_reference_usage = defaultdict(lambda : defaultdict(lambda : 0))

def get_animation_reference_usage():
    return _animation_reference_usage

class TunableAnimationReference(TunableReferenceFactory):
    __qualname__ = 'TunableAnimationReference'

    @staticmethod
    def get_default_callback(interaction_asm_type):

        def callback(cls, fields, source, *, factory, overrides, actor_participant_type=ParticipantType.Actor, target_participant_type=ParticipantType.TargetSim, **kwargs):
            if cls is None:
                return
            participant_constraint_lists = {}
            run_in_sequence = factory.run_in_sequence
            for animation_element_factory in factory.animation_element_gen():
                animation_element = animation_element_factory()
                asm_key = animation_element.asm_key
                actor_name = animation_element.actor_name
                target_name = animation_element.target_name
                carry_target_name = animation_element.carry_target_name
                create_target_name = animation_element.create_target_name
                initial_state = animation_element.initial_state
                begin_states = animation_element.begin_states
                instance_overrides = overrides()
                total_overrides = animation_element.overrides(overrides=instance_overrides)
                cls.register_tuned_animation(interaction_asm_type, asm_key, actor_name, target_name, carry_target_name, create_target_name, total_overrides, actor_participant_type, target_participant_type)
                if animation_element_factory._child_animations:
                    for child_args in animation_element_factory._child_animations:
                        cls.register_tuned_animation(*child_args)
                if should_use_animation_constaint_cache():
                    return
                if animation_element_factory._child_constraints:
                    for child_args in animation_element_factory._child_constraints:
                        cls.add_auto_constraint(*child_args)
                from interactions.utils.animation import InteractionAsmType
                while interaction_asm_type == InteractionAsmType.Interaction or (interaction_asm_type == InteractionAsmType.Canonical or interaction_asm_type == InteractionAsmType.Outcome) or interaction_asm_type == InteractionAsmType.Response:
                    from interactions.constraints import create_animation_constraint

                    def add_participant_constraint(participant_type, animation_constraint):
                        if animation_constraint is not None:
                            if interaction_asm_type == InteractionAsmType.Canonical:
                                is_canonical = True
                            else:
                                is_canonical = False
                            if run_in_sequence:
                                cls.add_auto_constraint(participant_type, animation_constraint, is_canonical=is_canonical)
                            else:
                                if participant_type not in participant_constraint_lists:
                                    participant_constraint_lists[participant_type] = []
                                participant_constraint_lists[participant_type].append(animation_constraint)

                    animation_constraint_actor = None
                    try:
                        animation_constraint_actor = create_animation_constraint(asm_key, actor_name, target_name, carry_target_name, create_target_name, initial_state, begin_states, total_overrides)
                    except:
                        if interaction_asm_type != InteractionAsmType.Outcome:
                            logger.exception('Exception while processing tuning for {}', cls)
                    add_participant_constraint(actor_participant_type, animation_constraint_actor)
                    if target_name is not None:
                        animation_context = get_throwaway_animation_context()
                        asm = animation.asm.Asm(asm_key, animation_context, posture_manifest_overrides=total_overrides.manifests)
                        target_actor_definition = asm.get_actor_definition(target_name)
                        if target_actor_definition.actor_type == ASM_ACTORTYPE_SIM:
                            animation_constraint_target = create_animation_constraint(asm_key, target_name, actor_name, carry_target_name, create_target_name, initial_state, begin_states, total_overrides)
                            add_participant_constraint(target_participant_type, animation_constraint_target)
            if not run_in_sequence and participant_constraint_lists is not None:
                from interactions.constraints import create_constraint_set
                for (participant_type, constraints_list) in participant_constraint_lists.items():
                    cls.add_auto_constraint(participant_type, create_constraint_set(constraints_list))

        return callback

    def __init__(self, class_restrictions=DEFAULT, callback=DEFAULT, interaction_asm_type=DEFAULT, allow_reactionlets=True, override_animation_context=False, participant_enum_override=DEFAULT, **kwargs):
        if interaction_asm_type is DEFAULT:
            from interactions.utils.animation import InteractionAsmType
            interaction_asm_type = InteractionAsmType.Interaction
        if callback is DEFAULT:
            callback = self.get_default_callback(interaction_asm_type)
        if class_restrictions is DEFAULT:
            class_restrictions = ('AnimationElement', 'AnimationElementSet')
        from interactions.utils.animation import TunableAnimationOverrides
        super().__init__(callback=callback, manager=services.animation_manager(), class_restrictions=class_restrictions, overrides=TunableAnimationOverrides(allow_reactionlets=allow_reactionlets, override_animation_context=override_animation_context, participant_enum_override=participant_enum_override, description='The overrides for interaction to replace the tunings on the animation elements'), **kwargs)

class TunedAnimationConstraint:
    __qualname__ = 'TunedAnimationConstraint'

    def __init__(self, animation_ref):
        self._animation_ref = animation_ref

    def create_constraint(self, *args, **kwargs):
        animation_constraints = []
        if self._animation_ref:
            for animation_element_factory in self._animation_ref.animation_element_gen():
                animation_element = animation_element_factory()
                asm_key = animation_element.asm_key
                actor_name = animation_element.actor_name
                target_name = animation_element.target_name
                carry_target_name = animation_element.carry_target_name
                create_target_name = animation_element.create_target_name
                initial_state = animation_element.initial_state
                begin_states = animation_element.begin_states
                from interactions.constraints import create_animation_constraint
                animation_constraint = create_animation_constraint(asm_key, actor_name, target_name, carry_target_name, create_target_name, initial_state, begin_states, animation_element.overrides)
                animation_constraints.append(animation_constraint)
        from interactions.constraints import create_constraint_set
        return create_constraint_set(animation_constraints)

class TunableAnimationConstraint(TunableSingletonFactory):
    __qualname__ = 'TunableAnimationConstraint'
    FACTORY_TYPE = TunedAnimationConstraint

    def __init__(self, description='A tunable type for creating animation-based constraints.', **kwargs):
        super().__init__(animation_ref=TunableAnimationReference(callback=None, description='\n                        The animation to use when generating the RequiredSlot constraint.'), **kwargs)

