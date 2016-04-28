from _sims4_collections import frozendict
from broadcasters.environment_score.environment_score_tuning import EnvironmentScoreTuning
from objects.components import Component, componentmethod_with_fallback
import gsi_handlers
import interactions
import objects.components.types
import services
import sims4.log
logger = sims4.log.Logger('Environment Score')

class EnvironmentScoreComponent(Component, component_name=objects.components.types.ENVIRONMENT_SCORE_COMPONENT, allow_dynamic=True):
    __qualname__ = 'EnvironmentScoreComponent'
    ENVIRONMENT_SCORE_ZERO = (frozendict(), 0, 0, ())

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._broadcaster = None
        definition = self.owner.definition
        self._environment_scores = {}
        self._negative_environment_score = definition.negative_environment_score
        self._positive_environment_score = definition.positive_environment_score
        for (index, tag) in enumerate(definition.environment_score_mood_tags):
            mood = EnvironmentScoreTuning.ENVIRONMENT_SCORE_MOODS.get(tag)
            while mood is not None:
                score = definition.environment_scores[index]
                if score is not None:
                    self._environment_scores[mood] = score
        self._has_static_scoring = None
        self._state_environment_scores = []

    def _start_broadcaster(self):
        if not self.should_broadcast:
            return
        broadcaster_service = services.current_zone().broadcaster_service
        if broadcaster_service is not None and self._broadcaster is None:
            self._broadcaster = EnvironmentScoreTuning.ENVIRONMENT_SCORE_BROADCASTER(broadcasting_object=self.owner)
            broadcaster_service.add_broadcaster(self._broadcaster)

    def _stop_broadcaster(self):
        if self._broadcaster is not None:
            broadcaster_service = services.current_zone().broadcaster_service
            if broadcaster_service is not None:
                broadcaster_service.remove_broadcaster(self._broadcaster)
            self._broadcaster = None

    def on_add(self, *_, **__):
        self._start_broadcaster()

    def on_remove(self, *_, **__):
        self._stop_broadcaster()

    def on_added_to_inventory(self):
        self._stop_broadcaster()

    def on_removed_from_inventory(self):
        self._start_broadcaster()

    @property
    def has_static_scoring(self):
        if self._has_static_scoring is None:
            self._has_static_scoring = self.owner.environment_score_trait_modifiers or (self._environment_scores or (self._negative_environment_score != 0 or self._positive_environment_score != 0))
        return self._has_static_scoring

    @property
    def should_broadcast(self):
        if not self.has_static_scoring and not self.is_mood_scoring_enabled() and len(self._state_environment_scores) <= 1:
            return False
        return True

    @componentmethod_with_fallback(lambda mood: 0)
    def get_base_environment_score(self, mood):
        return self._environment_scores.get(mood, 0)

    def add_state_environment_score(self, environment_score_state):
        self._state_environment_scores.append(environment_score_state)
        if environment_score_state.state_value is not EnvironmentScoreTuning.DISABLED_STATE_VALUE:
            self._start_broadcaster()

    def remove_state_environment_score(self, environment_score_state):
        if environment_score_state in self._state_environment_scores:
            self._state_environment_scores.remove(environment_score_state)
        if not self.should_broadcast:
            self._stop_broadcaster()

    def is_mood_scoring_enabled(self):
        for state in self._state_environment_scores:
            while state.state_value is EnvironmentScoreTuning.DISABLED_STATE_VALUE:
                return False
        return True

    @objects.components.componentmethod_with_fallback(lambda _: [])
    def potential_component_interactions(self, context, **kwargs):
        affordance = None
        (mood_scores, _, _, _) = self._compute_environment_score(sim=None, ignore_disabled_state=True)
        has_mood_scoring = mood_scores is not None and sum(mood_scores.values()) > 0
        if not has_mood_scoring:
            return
        state_values = [state.state_value for state in self._state_environment_scores]
        if EnvironmentScoreTuning.ENABLED_STATE_VALUE in state_values:
            affordance = EnvironmentScoreTuning.DISABLE_AFFORDANCE
        elif EnvironmentScoreTuning.DISABLED_STATE_VALUE in state_values:
            affordance = EnvironmentScoreTuning.ENABLE_AFFORDANCE
        if affordance is not None:
            yield interactions.aop.AffordanceObjectPair(affordance, self.owner, affordance, None, **kwargs)

    @componentmethod_with_fallback(lambda sim: EnvironmentScoreComponent.ENVIRONMENT_SCORE_ZERO)
    def get_environment_score(self, sim=None, ignore_disabled_state=False):
        (mood_scores, negative_score, positive_score, contributions) = self._compute_environment_score(sim, ignore_disabled_state=ignore_disabled_state)
        if not mood_scores and negative_score == 0 and positive_score == 0:
            (mood_scores, negative_score, positive_score, contributions) = self.ENVIRONMENT_SCORE_ZERO
        return (mood_scores, negative_score, positive_score, contributions)

    def _compute_environment_score(self, sim=None, ignore_disabled_state=False):
        object_mood_modifiers = {}
        negative_modifiers = (0, 1)
        positive_modifiers = (0, 1)
        contributions = []
        gsi_enabled = sim is not None and gsi_handlers.sim_handlers_log.environment_score_archiver.enabled
        if sim is not None:
            trait_tracker = sim.sim_info.trait_tracker
        else:
            trait_tracker = None
        if trait_tracker is not None:
            for (trait, trait_modifiers) in self.owner.environment_score_trait_modifiers.items():
                while trait in trait_tracker.equipped_traits:
                    (object_mood_modifiers, negative_modifiers, positive_modifiers) = trait_modifiers.combine_modifiers(object_mood_modifiers, negative_modifiers, positive_modifiers)
                    if gsi_enabled:
                        contributions.extend(gsi_handlers.sim_handlers_log.get_environment_score_object_contributions(self.owner, 'Trait: {} on Object:{}'.format(trait.__name__, gsi_handlers.gsi_utils.format_object_name(self.owner)), trait_modifiers))
        for state in self._state_environment_scores:
            while not (ignore_disabled_state and state.state_value is EnvironmentScoreTuning.DISABLED_STATE_VALUE):
                if state.state_value is EnvironmentScoreTuning.ENABLED_STATE_VALUE:
                    pass
                value_base_modifiers = state.base_modifiers
                (object_mood_modifiers, negative_modifiers, positive_modifiers) = value_base_modifiers.combine_modifiers(object_mood_modifiers, negative_modifiers, positive_modifiers)
                if gsi_enabled:
                    contributions.extend(gsi_handlers.sim_handlers_log.get_environment_score_object_contributions(self.owner, 'State Value: ' + state.state_value.__name__, value_base_modifiers))
                while trait_tracker is not None:
                    while True:
                        for (trait, state_trait_modifiers) in state.trait_modifiers.items():
                            while trait in trait_tracker.equipped_traits:
                                (object_mood_modifiers, negative_modifiers, positive_modifiers) = state_trait_modifiers.combine_modifiers(object_mood_modifiers, negative_modifiers, positive_modifiers)
                                if gsi_enabled:
                                    contributions.extend(gsi_handlers.sim_handlers_log.get_environment_score_object_contributions(self.owner, 'Trait: {} in State Value: {}'.format(trait.__name__, state.state_value.__name__), state_trait_modifiers))
        mood_scores = {}
        instance_manager = services.get_instance_manager(sims4.resources.Types.MOOD)
        for mood in instance_manager.types.values():
            if ignore_disabled_state or self.is_mood_scoring_enabled():
                mood_score = self._environment_scores.get(mood, 0)
                current_mood_score = mood_scores.get(mood, 0)
                if gsi_enabled and mood_score != 0:
                    contributions.append({'object': gsi_handlers.gsi_utils.format_object_name(self.owner), 'object_id': self.owner.id, 'source': 'Definition : ' + self.owner.definition.name, 'score_affected': mood.__name__, 'adder': mood_score, 'multiplier': 1})
                mood_modifiers = object_mood_modifiers.get(mood)
                if mood_modifiers is not None:
                    (adder, multiplier) = mood_modifiers
                    current_mood_score = current_mood_score + (mood_score + adder)*multiplier
                else:
                    current_mood_score = current_mood_score + mood_score
            else:
                current_mood_score = 0
            mood_scores[mood] = current_mood_score
        if gsi_enabled and self._negative_environment_score != 0:
            contributions.append({'object': gsi_handlers.gsi_utils.format_object_name(self.owner), 'object_id': self.owner.id, 'source': 'Definition : ' + self.owner.definition.name, 'score_affected': 'NEGATIVE SCORING', 'adder': self._negative_environment_score, 'multiplier': 1})
        if gsi_enabled and self._positive_environment_score != 0:
            contributions.append({'object': gsi_handlers.gsi_utils.format_object_name(self.owner), 'object_id': self.owner.id, 'source': 'Definition : ' + self.owner.definition.name, 'score_affected': 'POSITIVE SCORING', 'adder': self._positive_environment_score, 'multiplier': 1})
        negative_score = (self._negative_environment_score + negative_modifiers[0])*negative_modifiers[1]
        positive_score = (self._positive_environment_score + positive_modifiers[0])*positive_modifiers[1]
        return (mood_scores, negative_score, positive_score, contributions)

