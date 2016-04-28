import services
import sims4.log
import sims4.random
import situations
import uid
logger = sims4.log.Logger('SituationGoals')

class _GoalSetChain:
    __qualname__ = '_GoalSetChain'
    UNUSED_DISPLAY_POSITION = -1

    def __init__(self, starting_goal_set_type, chosen_goal_set_type=None, chain_id=None):
        self._starting_goal_set_type = starting_goal_set_type
        if chosen_goal_set_type is None:
            self._next_goal_sets = [starting_goal_set_type]
            self._chosen_goal_set_type = None
        else:
            self._next_goal_sets = None
            self._chosen_goal_set_type = chosen_goal_set_type
        if chain_id is None:
            self._chain_id = self._starting_goal_set_type.guid64
        else:
            self._chain_id = chain_id
        self.display_position = self.UNUSED_DISPLAY_POSITION

    def advance_goal_chain(self):
        if self._chosen_goal_set_type.chained_goal_sets is None or len(self._chosen_goal_set_type.chained_goal_sets) == 0:
            self._next_goal_sets = None
        else:
            self._next_goal_sets = list(self._chosen_goal_set_type.chained_goal_sets)
        self._chosen_goal_set_type = None

    @property
    def starting_goal_set_type(self):
        return self._starting_goal_set_type

    @property
    def chain_id(self):
        return self._chain_id

    @property
    def chosen_goal_set_type(self):
        return self._chosen_goal_set_type

    @chosen_goal_set_type.setter
    def chosen_goal_set_type(self, goal_set):
        self._chosen_goal_set_type = goal_set
        self._next_goal_sets = None

    @property
    def next_goal_sets(self):
        return self._next_goal_sets

class SituationGoalTracker:
    __qualname__ = 'SituationGoalTracker'
    MAX_MINOR_GOALS = 3
    constrained_goals = set()

    def __init__(self, situation):
        self._situation = situation
        self._realized_main_goal = None
        self._main_goal_completed = False
        self._realized_minor_goals = {}
        self._goal_chains = None
        self._inherited_target_sim_info = None
        self._goal_id_generator = uid.UniqueIdGenerator(1)
        self._has_offered_goals = False
        self._completed_goals = {}

    def destroy(self):
        self._destroy_realized_goals()
        self._completed_goals = None
        self._goal_chains = None
        self._situation = None
        self._inherited_target_sim_info = None

    def save_to_seed(self, situation_seed):
        target_sim_id = 0 if self._inherited_target_sim_info is None else self._inherited_target_sim_info.id
        tracker_seedling = situation_seed.setup_for_goal_tracker_save(self._has_offered_goals, target_sim_id)
        for chain in self._goal_chains:
            tracker_seedling.add_chain(situations.situation_serialization.GoalChainSeedling(chain.starting_goal_set_type, chain.chosen_goal_set_type, chain.chain_id))
        if self._realized_main_goal is not None:
            goal_seedling = self._realized_main_goal.create_seedling()
            if self.get_main_goal_completed():
                goal_seedling.set_completed()
            tracker_seedling.set_main_goal(goal_seedling)
        for (goal, chain) in self._realized_minor_goals.items():
            goal_seedling = goal.create_seedling()
            goal_seedling.chain_id = chain.chain_id
            tracker_seedling.add_minor_goal(goal_seedling)

    def load_from_seedling(self, tracker_seedling):
        if self._has_offered_goals:
            raise AssertionError('Attempting to load goals for situation: {} but goals have already been offered.'.format(self))
        self._has_offered_goals = tracker_seedling.has_offered_goals
        if tracker_seedling.inherited_target_id != 0:
            self._inherited_target_sim_info = services.sim_info_manager().get(tracker_seedling.inherited_target_id)
        self._goal_chains = []
        for chain_seedling in tracker_seedling.chains:
            self._goal_chains.append(_GoalSetChain(chain_seedling.starting_goal_set_type, chain_seedling.chosen_goal_set_type, chain_seedling.chain_id))
        if tracker_seedling.main_goal:
            goal_seedling = tracker_seedling.main_goal
            sim_info = services.sim_info_manager().get(goal_seedling.actor_id)
            self._realized_main_goal = goal_seedling.goal_type(sim_info=sim_info, situation=self._situation, goal_id=self._goal_id_generator(), count=goal_seedling.count, reader=goal_seedling.reader)
            if goal_seedling.completed:
                self._main_goal_completed = True
            else:
                self._realized_main_goal.register_for_on_goal_completed_callback(self._on_goal_completed)
        for goal_seedling in tracker_seedling.minor_goals:
            sim_info = services.sim_info_manager().get(goal_seedling.actor_id)
            while True:
                for chain in self._goal_chains:
                    while chain.chain_id == goal_seedling.chain_id:
                        break
                logger.error('Unable to find chain with chain_id: {} during load of situation: {}', goal_seedling.chain_id, self)
            goal = goal_seedling.goal_type(sim_info=sim_info, situation=self._situation, goal_id=self._goal_id_generator(), count=goal_seedling.count, reader=goal_seedling.reader)
            self._realized_minor_goals[goal] = chain
            goal.register_for_on_goal_completed_callback(self._on_goal_completed)
        self._situation._send_goal_update_to_client()

    def _does_goal_or_goal_set_and_tags_match(self, current_tag_set, goal_or_goal_set):
        if goal_or_goal_set.role_tags:
            return bool(current_tag_set & goal_or_goal_set.role_tags)
        return True

    def _generate_current_tag_match_set(self):
        current_tag_set = set()
        for sim in self._situation.all_sims_in_situation_gen():
            if not sim.is_selectable:
                pass
            current_tag_set.update(self._situation.get_role_tags_for_sim(sim))
        return current_tag_set

    def offer_goals(self):
        self._has_offered_goals = True
        new_goals_offered = False
        if self._realized_main_goal is None and self._situation.main_goal is not None:
            self._realized_main_goal = self._situation.main_goal(situation=self._situation, goal_id=self._goal_id_generator())
            self._realized_main_goal.register_for_on_goal_completed_callback(self._on_goal_completed)
            new_goals_offered = True
        if self._goal_chains is None and self._situation.minor_goal_chains is not None:
            self._goal_chains = []
            for goal_set_ref in self._situation.minor_goal_chains:
                self._goal_chains.append(_GoalSetChain(goal_set_ref))
        if len(self._realized_minor_goals) < self.MAX_MINOR_GOALS:
            available_goal_chains = []
            current_tag_set = self._generate_current_tag_match_set()
            for possible_chain in self._goal_chains:
                if possible_chain.next_goal_sets is None:
                    pass
                if possible_chain in self._realized_minor_goals.values():
                    pass
                available_goal_chains.append(possible_chain)
            num_new_goals = self.MAX_MINOR_GOALS - len(self._realized_minor_goals)
            chosen_tuned_goals = {}
            for chain in available_goal_chains:
                for goal_set_ref in chain.next_goal_sets:
                    if not self._does_goal_or_goal_set_and_tags_match(current_tag_set, goal_set_ref):
                        pass
                    weighted_goal_refs = []
                    for wgref in goal_set_ref.goals:
                        while self._does_goal_or_goal_set_and_tags_match(current_tag_set, wgref.goal):
                            weighted_goal_refs.append((wgref.weight, wgref.goal))
                    while len(weighted_goal_refs) > 0:
                        tuned_goal = sims4.random.pop_weighted(weighted_goal_refs)
                        if SituationGoalTracker.constrained_goals and tuned_goal not in SituationGoalTracker.constrained_goals:
                            continue
                        if tuned_goal in chosen_tuned_goals:
                            continue
                        is_realized = False
                        for goal_instance in self._realized_minor_goals:
                            while tuned_goal is type(goal_instance):
                                is_realized = True
                                break
                        if is_realized:
                            continue
                        old_goal_instance = self._completed_goals.get(tuned_goal)
                        if old_goal_instance is not None and old_goal_instance[0].is_on_cooldown():
                            continue
                        while tuned_goal.can_be_given_as_goal(None, self._situation, inherited_target_sim_info=self._inherited_target_sim_info):
                            chosen_tuned_goals[tuned_goal] = chain
                            chain.chosen_goal_set_type = goal_set_ref
                            break
                            continue
                    while chain.chosen_goal_set_type is not None:
                        break
                while len(chosen_tuned_goals) >= num_new_goals:
                    break
            for tuned_goal in chosen_tuned_goals.keys():
                goal = tuned_goal(situation=self._situation, goal_id=self._goal_id_generator(), inherited_target_sim_info=self._inherited_target_sim_info)
                self._realized_minor_goals[goal] = chosen_tuned_goals[tuned_goal]
                goal.register_for_on_goal_completed_callback(self._on_goal_completed)
                new_goals_offered = True
        logger.debug('Offering Situation Goals in situation {}', self._situation)
        unused_display_priority = list(range(self.MAX_MINOR_GOALS))
        chains_needing_positions = []
        for chain in self._goal_chains:
            if chain in self._realized_minor_goals.values():
                if chain.display_position != _GoalSetChain.UNUSED_DISPLAY_POSITION:
                    unused_display_priority.remove(chain.display_position)
                else:
                    chains_needing_positions.append(chain)
                    chain.display_position = _GoalSetChain.UNUSED_DISPLAY_POSITION
            else:
                chain.display_position = _GoalSetChain.UNUSED_DISPLAY_POSITION
        for chain in chains_needing_positions:
            chain.display_position = unused_display_priority.pop()
        return new_goals_offered

    def refresh_goals(self, completed_goal=None):
        new_goals_offered = self.offer_goals()
        if new_goals_offered or completed_goal is not None:
            self._situation._send_goal_update_to_client(completed_goal)
        if self.are_all_goals_complete():
            self._situation._on_goals_completed()

    def get_goal_info(self):
        infos = []
        if self._realized_minor_goals is not None:
            for (goal, chain) in self._realized_minor_goals.items():
                infos.append((goal, chain.chosen_goal_set_type))
        if self._realized_main_goal is not None:
            infos.insert(0, (self._realized_main_goal, None))
        return infos

    def get_completed_goal_info(self):
        return self._completed_goals.values()

    def debug_force_complete_named_goal(self, goal_name, target_sim=None):
        if self._realized_minor_goals is not None:
            all_realized_goals = list(self._realized_minor_goals.keys())
        else:
            all_realized_goals = []
        if self._realized_main_goal is not None:
            all_realized_goals.insert(0, self._realized_main_goal)
        for goal in all_realized_goals:
            while goal.__class__.__name__.lower().find(goal_name.lower()) != -1:
                goal.debug_force_complete(target_sim)
                return True
        return False

    def get_main_goal(self):
        return self._realized_main_goal

    def get_main_goal_completed(self):
        return self._main_goal_completed

    def get_minor_goals(self):
        if self._realized_minor_goals is None:
            return []
        return sorted(self._realized_minor_goals.keys(), key=lambda goal: self._realized_minor_goals[goal].display_position)

    def has_offered_goals(self):
        return self._has_offered_goals

    def are_all_goals_complete(self):
        return len(self.get_minor_goals()) == 0 and (self.get_main_goal() is None or self.get_main_goal_completed())

    def _destroy_realized_goals(self):
        if self._realized_main_goal is not None:
            self._realized_main_goal.destroy()
            self._realized_main_goal = None
        if self._realized_minor_goals is not None:
            for goal in self._realized_minor_goals.keys():
                goal.destroy()
            self._realized_minor_goals = {}

    def _on_goal_completed(self, goal, goal_completed):
        if goal_completed:
            if goal is self._realized_main_goal:
                self._completed_goals[type(goal)] = (goal, None)
                self._main_goal_completed = True
            else:
                chain = self._realized_minor_goals.pop(goal, None)
                if chain is not None:
                    self._completed_goals[type(goal)] = (goal, chain.chosen_goal_set_type)
                    chain.advance_goal_chain()
            goal.decommision()
            self._inherited_target_sim_info = goal._get_actual_target_sim_info()
            self._situation.on_goal_completed(goal)
            self.refresh_goals(goal)
        else:
            self._situation._send_goal_update_to_client()

