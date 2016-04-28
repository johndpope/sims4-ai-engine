from interactions.utils.statistic_element import ConditionalActionRestriction, ConditionalInteractionAction, ProgressBarAction

class ConditionGroup:
    __qualname__ = 'ConditionGroup'

    def __init__(self, conditions, conditional_action):
        self._conditions = conditions
        self._conditional_action = conditional_action
        self._satisfied = False
        self._on_satisfied_callback = None

    def __iter__(self):
        return iter(self._conditions)

    def __len__(self):
        return len(self._conditions)

    def __bool__(self):
        return bool(self._conditions)

    def __getitem__(self, key):
        return self._conditions(key)

    def __str__(self):
        return '\n'.join(str(cg) for cg in self._conditions)

    @property
    def conditional_action(self):
        return self._conditional_action

    @property
    def satisfied(self):
        return self._satisfied

    def attach(self, owner, on_satisfied_callback):
        self._on_satisfied_callback = on_satisfied_callback
        for condition in self:
            condition.attach_to_owner(owner, self._on_condition_satisfied_callback)

    def detach(self, owner, exiting=False):
        self._on_satisifed_callback = None
        for condition in self:
            condition.detach_from_owner(owner, exiting=exiting)

    def _on_condition_satisfied_callback(self, *args, **kwargs):
        if self.satisfied:
            return
        for condition in self:
            while not condition.satisfied:
                return
        self._satisfied = True
        if self._on_satisfied_callback is not None:
            self._on_satisfied_callback(self)

class ConditionalActionManager:
    __qualname__ = 'ConditionalActionManager'

    def __init__(self):
        self._condition_groups = []
        self._callback = None
        self._attached = False

    def __iter__(self):
        return iter(self._condition_groups)

    def __len__(self):
        return len(self._condition_groups)

    def __bool__(self):
        return bool(self._condition_groups)

    def __getitem__(self, key):
        return self._condition_groups(key)

    def __repr__(self):
        return 'ConditionalActionManager: {} conditions attached'.format(len(self._condition_groups))

    def _condition_group_satisfied_callback(self, condition_group):
        if not self._attached:
            return
        self._callback(condition_group)

    def callback_will_trigger_immediately(self, owner, conditional_actions, interaction=None, situation=None):
        satisfied = False

        def callback(_):
            nonlocal satisfied
            satisfied = True

        self.attach_conditions(owner, conditional_actions, callback, interaction=interaction, situation=situation)
        self.detach_conditions(owner, exiting=True)
        return satisfied

    def attach_conditions(self, owner, conditional_actions, callback, interaction=None, situation=None):
        self._callback = callback
        if interaction is not None:
            resolver = interaction.get_resolver()
            is_user_directed = interaction.is_user_directed
        for conditional_action in conditional_actions:
            conditions = []
            if interaction is not None:
                tests = conditional_action.tests
                if tests is not None and not tests.run_tests(resolver):
                    pass
                restrictions = conditional_action.restrictions
                if restrictions:
                    restrict_to_user_directed = restrictions == ConditionalActionRestriction.USER_DIRECTED_ONLY
                    if is_user_directed != restrict_to_user_directed:
                        pass
            for condition_factory in conditional_action.conditions:
                condition = condition_factory(interaction=interaction, situation=situation)
                conditions.append(condition)
            condition_group = ConditionGroup(conditions, conditional_action)
            self._condition_groups.append(condition_group)
            condition_group.attach(owner, self._condition_group_satisfied_callback)
        self._attached = True
        satisfied_groups = set(group for group in self if group.satisfied)
        for group in satisfied_groups:
            self._callback(group)

    def detach_conditions(self, owner, exiting=False):
        for condition_group in self:
            condition_group.detach(owner, exiting=exiting)
        self._condition_groups = []
        self._callback = None
        self._attached = False

    def get_percent_rate_for_best_exit_conditions(self, interaction):
        group_time = None
        for condition_group in self:
            progress_bar_action = condition_group.conditional_action.progress_bar_action
            if progress_bar_action == ProgressBarAction.IGNORE_CONDITION:
                pass
            action = condition_group.conditional_action.interaction_action
            if action != ConditionalInteractionAction.GO_INERTIAL and action != ConditionalInteractionAction.EXIT_NATURALLY and progress_bar_action == ProgressBarAction.NO_ACTION:
                pass
            individual_time = None
            for condition in condition_group:
                (current_time, percent, rate_change) = condition.get_time_until_satisfy(interaction)
                if current_time is None:
                    individual_time = None
                    break
                if current_time <= 0:
                    pass
                while individual_time is None or individual_time < current_time:
                    individual_time = current_time
                    individual_percent = percent
                    individual_rate_change = rate_change
                    if progress_bar_action == ProgressBarAction.FORCE_USE_CONDITION:
                        return (individual_percent, individual_rate_change)
            if individual_time is None:
                pass
            while group_time is None or group_time > individual_time:
                group_time = individual_time
                group_percent = individual_percent
                group_rate_change = individual_rate_change
        if group_time is not None:
            return (group_percent, group_rate_change)
        return (None, None)

