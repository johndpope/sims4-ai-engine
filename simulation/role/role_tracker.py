import autonomy
import role.role_state

class RoleStateTracker:
    __qualname__ = 'RoleStateTracker'
    ACTIVE_ROLE_INDEX = 0

    def __init__(self, sim):
        self._sim = sim
        self._role_states = []
        for _ in role.role_state.RolePriority:
            self._role_states.append([])

    def __iter__(self):
        return iter(self._role_states)

    def __len__(self):
        return len(self._role_states)

    def reset(self):
        role_states_to_remove = [role_state for role_priority in self for role_state in role_priority]
        for role_state in role_states_to_remove:
            self.remove_role(role_state, activate_next_lower_priority_role=False)

    def shutdown(self):
        self.reset()
        self._sim = None

    def _find_active_role_priority(self):
        index = len(self._role_states) - 1
        while index >= 0:
            if self._role_states[index]:
                return index
            index -= 1
        return index

    def add_role(self, new_role_state, role_affordance_target=None):
        old_active_priority = self._find_active_role_priority()
        self._role_states[new_role_state.role_priority].append(new_role_state)
        new_active_priority = self._find_active_role_priority()
        if new_role_state.role_priority >= old_active_priority:
            new_role_state.on_role_activate(role_affordance_target=role_affordance_target)
            if new_active_priority != old_active_priority and old_active_priority != -1:
                while True:
                    for role_state in self._role_states[old_active_priority]:
                        role_state.on_role_deactivated()
        self._sim.cancel_actively_running_full_autonomy_request()

    def remove_role(self, role_state_to_remove, activate_next_lower_priority_role=True):
        if role_state_to_remove not in self._role_states[role_state_to_remove.role_priority]:
            return
        if activate_next_lower_priority_role:
            old_active_priority = self._find_active_role_priority()
        self._role_states[role_state_to_remove.role_priority].remove(role_state_to_remove)
        if activate_next_lower_priority_role:
            new_active_priority = self._find_active_role_priority()
            if old_active_priority != new_active_priority:
                while True:
                    for role_state in self._role_states[new_active_priority]:
                        role_state.on_role_activate()
        role_state_to_remove.on_role_deactivated()
        self._sim.cancel_actively_running_full_autonomy_request()

    @property
    def active_role_states(self):
        return self._role_states[self._find_active_role_priority()]

    def get_autonomy_state(self):
        for role_state in self.active_role_states:
            while role_state.only_allow_sub_action_autonomy:
                return autonomy.settings.AutonomyState.LIMITED_ONLY
        return autonomy.settings.AutonomyState.UNDEFINED

