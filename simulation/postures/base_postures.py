from contextlib import contextmanager
import collections
from animation.posture_manifest import AnimationParticipant
from element_utils import do_all
from postures.posture import Posture
from sims4.tuning.tunable import Tunable
from sims4.utils import classproperty
import sims4.log
import sims4.reload
logger = sims4.log.Logger('BasePosture')
with sims4.reload.protected(globals()):
    _sims_that_create_puppet_postures = collections.Counter()

@contextmanager
def create_puppet_postures(sim):
    count = _sims_that_create_puppet_postures[sim]
    count += 1
    _sims_that_create_puppet_postures[sim] = count
    try:
        yield None
    finally:
        count = _sims_that_create_puppet_postures[sim]
        count -= 1
        if count < 0:
            raise AssertionError('Bookkeeping error in create_puppet_postures for {}'.format(sim))
        if count == 0:
            del _sims_that_create_puppet_postures[sim]
        else:
            _sims_that_create_puppet_postures[sim] = count

class MultiSimPosture(Posture):
    __qualname__ = 'MultiSimPosture'
    INSTANCE_TUNABLES = {'_actor_b_param_name': Tunable(str, 'y', description='The name of the actor parameter for all posture ASMs. By default, this is x.')}

    @classproperty
    def multi_sim(cls):
        return True

    def __init__(self, sim, target, track, *, master=True, **kwargs):
        super().__init__(sim, target, track, **kwargs)
        self._master = master
        self._setting_up = False
        if sim in _sims_that_create_puppet_postures:
            self._master = False
            self._set_actor_name_to_b_actor_name()

    @property
    def linked_sim(self):
        return self._linked_posture.sim

    @property
    def is_puppet(self):
        return not self._master

    @property
    def linked_posture(self):
        return self._linked_posture

    @linked_posture.setter
    def linked_posture(self, posture):
        if not self._master:
            posture.linked_posture = self
            return
        self._set_linked_posture(posture)
        posture._set_linked_posture(self)
        posture._master = False
        posture._set_actor_name_to_b_actor_name()
        posture.rebind(posture.target, animation_context=self._animation_context)

    def _set_actor_name_to_b_actor_name(self):
        self._actor_param_name = self._actor_b_param_name

    def _set_linked_posture(self, posture):
        self._linked_posture = posture

    def append_transition_to_arb(self, *args, **kwargs):
        if not self.is_puppet:
            super().append_transition_to_arb(*args, **kwargs)
        else:
            self.linked_posture.append_transition_to_arb(*args, **kwargs)

    def append_idle_to_arb(self, arb):
        if not self.is_puppet:
            self.asm.request(self._state_name, arb)
            self.linked_posture.asm.set_current_state(self._state_name)
        else:
            self.linked_posture.append_idle_to_arb(arb)

    def append_exit_to_arb(self, *args, **kwargs):
        if not self.is_puppet:
            super().append_exit_to_arb(*args, **kwargs)
        else:
            self.linked_posture.append_exit_to_arb(*args, **kwargs)

    def _setup_asm_posture(self, *args, **kwargs):
        return super().setup_asm_posture(*args, **kwargs)

    def setup_asm_posture(self, asm, sim, target, **kwargs):
        if self._setup_asm_posture(asm, sim, target, **kwargs):
            linked_posture = self.linked_posture
            if linked_posture is not None:
                if asm.set_actor(linked_posture._actor_param_name, linked_posture.sim, actor_participant=AnimationParticipant.TARGET):
                    return asm.add_potentially_virtual_actor(linked_posture._actor_param_name, linked_posture.sim, linked_posture.target_name, linked_posture.target, target_participant=AnimationParticipant.CONTAINER)
                return False
            return True
        return False

    def _setup_asm_interaction(self, *args, **kwargs):
        raise RuntimeError('[bhill] This function is believed to be dead code and is scheduled for pruning. If this exception has been raised, the code is not dead and this exception should be removed.')
        return super().setup_asm_interaction(*args, **kwargs)

    def _post_route_clothing_change(self, *args, **kwargs):
        return super().post_route_clothing_change(*args, **kwargs)

    def _exit_clothing_change(self, *args, **kwargs):
        return super().exit_clothing_change(*args, **kwargs)

    def post_route_clothing_change(self, *args, **kwargs):
        return self.get_linked_clothing_change(self._post_route_clothing_change, self.linked_posture._post_route_clothing_change, *args, **kwargs)

    def exit_clothing_change(self, *args, sim=None, **kwargs):
        return self.get_linked_clothing_change(self._exit_clothing_change, self.linked_posture._exit_clothing_change, *args, **kwargs)

    def get_linked_clothing_change(self, change_func, linked_change_func, *args, **kwargs):
        clothing_change = change_func(*args, **kwargs)
        if self.linked_posture is not None:
            linked_clothing_change = linked_change_func(sim=self.linked_posture.sim, *args, **kwargs)
        if clothing_change is not None or linked_clothing_change is not None:
            clothing_change = do_all(clothing_change, linked_clothing_change)
        return clothing_change

class AdjacentPartPosture(Posture):
    __qualname__ = 'AdjacentPartPosture'

    @classmethod
    def is_valid_target(cls, sim, target, adjacent_sim=None, adjacent_target=None, **kwargs):
        if not target.is_part:
            return False
        if adjacent_sim is None:
            return sim.posture.posture_type is cls
        if target.may_reserve(sim) or target.usable_by_transition_controller(sim.queue.transition_controller):
            for adjacent_part in target.adjacent_parts_gen():
                while adjacent_part.may_reserve(adjacent_sim) or target.usable_by_transition_controller(sim.queue.transition_controller):
                    if adjacent_target is not None and adjacent_part is not adjacent_target:
                        pass
                    if adjacent_part.supports_posture_type(cls):
                        return True
        return False

class IntimatePartPosture(MultiSimPosture, AdjacentPartPosture):
    __qualname__ = 'IntimatePartPosture'

    def setup_asm_posture(self, asm, sim, target, **kwargs):
        if super().setup_asm_posture(asm, sim, target, **kwargs):
            if self.linked_posture is not None:
                asm.set_parameter('isMirrored', True if self.is_mirrored else False)
            return True
        return False

    def setup_asm_interaction(self, asm, sim, target, actor_name, target_name, **kwargs):
        if super().setup_asm_interaction(asm, sim, target, actor_name, target_name, **kwargs):
            if self.linked_posture is not None:
                is_mirrored = self.is_mirrored
                if self.is_puppet:
                    is_mirrored = not is_mirrored
                asm.set_parameter('isMirrored', True if is_mirrored else False)
            return True
        return False

    @property
    def is_mirrored(self):
        if self._linked_posture is None:
            is_mirrored = super().is_mirrored
            if self.is_puppet:
                is_mirrored = not is_mirrored
            return is_mirrored
        if self.is_puppet:
            return self.linked_posture.is_mirrored
        linked_target = self.linked_posture.target
        return self.target.is_mirrored(linked_target)

