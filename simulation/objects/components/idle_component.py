from weakref import WeakKeyDictionary
from animation import AnimationContext
from element_utils import build_element
from interactions.utils.animation import flush_all_animations
from objects.components import Component, types
from sims4.tuning.tunable import HasTunableFactory, TunableMapping, TunableReference
from singletons import DEFAULT
import animation.asm
import caches
import services
import sims4

class IdleComponent(Component, HasTunableFactory, component_name=types.IDLE_COMPONENT):
    __qualname__ = 'IdleComponent'
    FACTORY_TUNABLES = {'idle_animation_map': TunableMapping(description='\n            The animations that the attached object can play.\n            ', key_type=TunableReference(manager=services.get_instance_manager(sims4.resources.Types.OBJECT_STATE), class_restrictions='ObjectStateValue'), value_type=TunableReference(description='\n                The animation to play when the object is in the specified state.\n                If you want the object to stop playing idles, you must tune an\n                animation element corresponding to an ASM state that requests a\n                stop on the object.\n                ', manager=services.get_instance_manager(sims4.resources.Types.ANIMATION), class_restrictions='ObjectAnimationElement'))}

    def __init__(self, owner, idle_animation_map):
        super().__init__(owner)
        self._idle_animation_map = idle_animation_map
        self._asm_registry = WeakKeyDictionary()
        self._animation_context = AnimationContext()
        self._animation_context.add_ref(self)
        self._idle_animation_element = None
        self._current_idle_state_value = None

    def get_asm(self, asm_key, actor_name, setup_asm_func=None, use_cache=True, cache_key=DEFAULT, **kwargs):
        if use_cache:
            asm_dict = self._asm_registry.setdefault(self._animation_context, {})
            asm = None
            if asm_key in asm_dict:
                asm = asm_dict[asm_key]
                if asm.current_state == 'exit':
                    asm = None
            if asm is None:
                asm = animation.asm.Asm(asm_key, context=self._animation_context)
            asm_dict[asm_key] = asm
        else:
            asm = animation.asm.Asm(asm_key, context=self._animation_context)
        asm.set_actor(actor_name, self.owner)
        if not (setup_asm_func is not None and setup_asm_func(asm)):
            return
        return asm

    def _refresh_active_idle(self):
        if self._current_idle_state_value is not None and self._idle_animation_element is not None:
            self._trigger_idle_animation(self._current_idle_state_value.state, self._current_idle_state_value)

    def on_state_changed(self, state, old_value, new_value):
        if self._trigger_idle_animation(state, new_value) or new_value.anim_overrides is not None and old_value != new_value:
            self._refresh_active_idle()

    def _trigger_idle_animation(self, state, new_value):
        if new_value in self._idle_animation_map:
            new_animation = self._idle_animation_map[new_value]
            self._hard_stop_animation_element()
            self._current_idle_state_value = new_value
            if new_animation is not None:
                animation_element = new_animation(self.owner)
                self._idle_animation_element = build_element((animation_element, flush_all_animations))
                services.time_service().sim_timeline.schedule(self._idle_animation_element)
                return True
        return False

    def _hard_stop_animation_element(self):
        if self._idle_animation_element is not None:
            self._idle_animation_element.trigger_hard_stop()
            self._idle_animation_element = None
        self._current_idle_state_value = None

    def on_remove(self, *_, **__):
        if self._animation_context is not None:
            self._animation_context.release_ref(self)
            self._animation_context = None
        self._hard_stop_animation_element()

