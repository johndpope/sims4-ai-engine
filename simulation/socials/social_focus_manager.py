from interactions.utils.sim_focus import SimFocus, get_next_focus_id
from socials.geometry import SocialGeometry
import interactions.utils.sim_focus
import sims4.log
import sims4.math
import services
logger = sims4.log.Logger('Social Group')

class SocialFocusManager:
    __qualname__ = 'SocialFocusManager'

    class SimFocusEntry:
        __qualname__ = 'SocialFocusManager.SimFocusEntry'

        def __init__(self, sim, score, layer):
            self.sim_id = sim.id
            self.score = score
            self.layer = layer
            self._focus_bone = sim.focus_bone
            self._focus_ids = {}

        def add_focus_id(self, target_id, focus_id):
            self._focus_ids[target_id] = focus_id

        def get_focus_id(self, target_id):
            return self._focus_ids.get(target_id)

        def remove_focus(self, owner_sim, target_id):
            focus_id = self.get_focus_id(target_id)
            if focus_id is not None:
                interactions.utils.sim_focus.FocusDelete(owner_sim, self._sim_id, focus_id)
                del self._focus_ids[target_id]

    def __init__(self, social_group):
        self._social_group = social_group
        self._sim_focus_info = {SimFocus.LAYER_SUPER_INTERACTION: {}, SimFocus.LAYER_INTERACTION: {}}

    def shutdown(self, sim):
        if self._sim_focus_info is None:
            return
        for v in list(self._sim_focus_info.values()):
            for sim_entry in list(v.values()):
                for focus_id in list(sim_entry._focus_ids.values()):
                    if sim is None:
                        sim = services.object_manager().get(sim_entry.sim_id)
                    if sim is not None:
                        interactions.utils.sim_focus.FocusDelete(sim, sim_entry.sim_id, focus_id)
                    else:
                        interactions.utils.sim_focus.FocusDebug('Focus: Leaking focus id ' + str(focus_id))
        self._sim_focus_info = None
        self._social_group = None

    def get_key(self, layer, owner_sim, sim):
        if layer is SimFocus.LAYER_SUPER_INTERACTION:
            return (0, sim.id)
        return (owner_sim.id, sim.id)

    def add_sim(self, owner_sim, sim, score, layer):
        if self._sim_focus_info is None:
            return
        key = self.get_key(layer, owner_sim, sim)
        my_entry = self.SimFocusEntry(sim, score, layer)
        if key in self._sim_focus_info[layer]:
            my_entry = self._sim_focus_info[layer][key]
            my_entry.score = score
        else:
            self._sim_focus_info[layer][key] = my_entry
        for (k, sim_entry) in self._sim_focus_info[layer].items():
            while sim_entry.sim_id != sim.id and k[0] == key[0]:
                focus_id = my_entry.get_focus_id(sim_entry.sim_id)
                if focus_id is not None:
                    interactions.utils.sim_focus.FocusModifyScore(owner_sim, my_entry.sim_id, focus_id, sim_entry.score)
                else:
                    focus_id = get_next_focus_id()
                    my_entry.add_focus_id(sim_entry.sim_id, focus_id)
                    interactions.utils.sim_focus.FocusAdd(owner_sim, focus_id, sim_entry.layer, sim_entry.score, my_entry.sim_id, sim_entry.sim_id, sim_entry._focus_bone, sims4.math.Vector3(0, 0, 0))
                focus_id = sim_entry.get_focus_id(sim.id)
                if focus_id is not None:
                    interactions.utils.sim_focus.FocusModifyScore(owner_sim, sim_entry.sim_id, focus_id, my_entry.score)
                else:
                    focus_id = get_next_focus_id()
                    sim_entry.add_focus_id(my_entry.sim_id, focus_id)
                    interactions.utils.sim_focus.FocusAdd(owner_sim, focus_id, my_entry.layer, my_entry.score, sim_entry.sim_id, my_entry.sim_id, my_entry._focus_bone, sims4.math.Vector3(0, 0, 0))

    def clear_sim(self, owner_sim, sim, layer):
        if self._sim_focus_info is None:
            return
        key = self.get_key(layer, owner_sim, sim)
        if key in self._sim_focus_info[layer]:
            self.add_sim(owner_sim, sim, -1, layer)

    def remove_sim(self, owner_sim, sim):
        if self._sim_focus_info is None:
            return
        for layer in self._sim_focus_info.keys():
            for k in list(self._sim_focus_info[layer].keys()):
                sim_entry = self._sim_focus_info[layer][k]
                if sim_entry.sim_id != sim.id:
                    sim_entry.remove_focus(owner_sim, sim)
                else:
                    for focus_id in sim_entry._focus_ids.values():
                        interactions.utils.sim_focus.FocusDelete(owner_sim, sim.id, focus_id)
                    del self._sim_focus_info[layer][k]

    def print_info(self):
        if self._sim_focus_info is None:
            return
        interactions.utils.sim_focus.FocusDebug('Focus Man: ' + str(self) + ' ----------------------------------------')
        for (layer, v) in list(self._sim_focus_info.items()):
            interactions.utils.sim_focus.FocusDebug('Layer:' + str(layer))
            for (k, sim_entry) in v.items():
                interactions.utils.sim_focus.FocusDebug('    Key:' + str(k))
                for (target_id, focus_id) in sim_entry._focus_ids.items():
                    target_key = (k[0], target_id)
                    target_entry = self._sim_focus_info[layer].get(target_key)
                    score = 0
                    if target_entry:
                        score = target_entry.score
                    else:
                        score = 'Unknown'
                    interactions.utils.sim_focus.FocusDebug('        Sim:' + str(sim_entry.sim_id) + ' Target:' + str(target_id) + ' focus_id:' + str(focus_id) + ' Score:' + str(score))
        interactions.utils.sim_focus.FocusDebug('End Focus Man: ----------------------------------------')

    def force_update(self, owner_sim, participant_list):
        if participant_list:
            for (participant, _) in participant_list:
                interactions.utils.sim_focus.FocusForceUpdate(owner_sim, participant.id)

    def active_focus_begin(self, owner_sim, participant_list, immediate=False):
        if participant_list:
            for (participant, score) in participant_list:
                self.add_sim(owner_sim, participant, score, SimFocus.LAYER_INTERACTION)
        if immediate:
            self.force_update(owner_sim, participant_list)

    def active_focus_end(self, owner_sim, participant_list):
        if participant_list:
            for (participant, _) in participant_list:
                self.clear_sim(owner_sim, participant, SimFocus.LAYER_INTERACTION)

    def get_focus_entry_for_sim(self, owner_sim, sim, layer):
        key = self.get_key(layer, owner_sim, sim)
        if self._sim_focus_info is not None:
            return self._sim_focus_info[layer].get(key)

    def add_focus_entry_for_sim(self, owner_sim, sim, layer, entry):
        if self._sim_focus_info is None:
            return
        key = self.get_key(layer, owner_sim, sim)
        self._sim_focus_info[layer][key] = entry
        for (target_id, focus_id) in entry._focus_ids.items():
            interactions.utils.sim_focus.FocusAdd(owner_sim, focus_id, entry.layer, entry.score, sim.id, target_id, entry._focus_bone, sims4.math.Vector3.ZERO())

    def remove_focus_entry_for_sim(self, owner_sim, sim, layer):
        if self._sim_focus_info is None:
            return
        key = self.get_key(layer, owner_sim, sim)
        my_entry = self._sim_focus_info[layer].get(key)
        if my_entry is not None:
            for focus_id in my_entry._focus_ids.values():
                interactions.utils.sim_focus.FocusDelete(owner_sim, sim.id, focus_id)
            del self._sim_focus_info[layer][key]

