from element_utils import maybe, build_critical_section
from sims4.tuning.tunable import TunableFactory, Tunable
from objects.components.state import TunableStateValueReference
from interactions.utils.animation_reference import TunableAnimationReference
from interactions.utils.animation import flush_all_animations

def conditional_animation(interaction, value, xevt_id, animation):
    target = interaction.target
    did_set = False
    kill_handler = False

    def check_fn():
        return target.get_state(value.state).value != value.value

    def set_fn(_):
        nonlocal did_set
        if did_set:
            return
        target.set_state(value.state, value)
        did_set = True

    if animation is None:
        return maybe(check_fn, set_fn)

    def set_handler(*_, **__):
        if kill_handler:
            return
        set_fn(None)

    def setup_asm(asm):
        if xevt_id is not None:
            asm.context.register_event_handler(set_handler, handler_id=xevt_id)

    def cleanup_asm(asm):
        nonlocal kill_handler
        if xevt_id is not None:
            kill_handler = True

    return maybe(check_fn, build_critical_section(animation(interaction, setup_asm=setup_asm, cleanup_asm=cleanup_asm), flush_all_animations, set_fn))

class TunableConditionalAnimationElement(TunableFactory):
    __qualname__ = 'TunableConditionalAnimationElement'

    @staticmethod
    def _factory(*args, animation, animation_ref, sequence=(), **kwargs):
        return (conditional_animation(animation=animation_ref, *args, **kwargs), sequence)

    FACTORY_TYPE = _factory

    def __init__(self, description="If the target object isn't in the given state, use an asm and set that object's state.", **kwargs):
        super().__init__(value=TunableStateValueReference(description='The value to require'), xevt_id=Tunable(int, None, description="An xevt on which to change the state's value (optional)."), animation_ref=TunableAnimationReference(), description=description, **kwargs)

