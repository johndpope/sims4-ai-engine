#ERROR: jaddr is None
import random
import crafting
import sims4.log
from sims4.log import assert_log
logger = sims4.log.Logger('Interactions')

class PickerEnumerationStrategy:
    __qualname__ = 'PickerEnumerationStrategy'

    def __init__(self):
        self._choices = None

    def build_choice_list(self, si, **kwargs):
        raise NotImplementedError

    def find_best_choice(self, si):
        if self._choices is None:
            logger.error('Calling PickerEnumerationStrategy.find_best_choice() without first calling build_choice_list()', owner='rez')
            return
        return random.choice(self._choices)

    @classmethod
    def has_valid_choice(self, target, context, state=None):
        raise NotImplementedError

    @property
    def choices(self):
        return self._choices

class StatePickerEnumerationStrategy(PickerEnumerationStrategy):
    __qualname__ = 'StatePickerEnumerationStrategy'

    def build_choice_list(self, si, state, **kwargs):
        self._choices = [client_state for client_state in si.target.get_client_states(state) if client_state.test_channel(si.target, si.context)]

    def find_best_choice(self, si):
        if not self._choices:
            logger.error('Calling PickerEnumerationStrategy.find_best_choice() without first calling build_choice_list()', owner='rez')
            return
        weights = []
        for client_state in self._choices:
            weight = client_state.calculate_autonomy_weight(si.sim)
            weights.append((weight, client_state))
        logger.assert_log(weights, 'Failed to find choice in autonomous recipe picker', owner='rez')
        choice = sims4.random.pop_weighted(weights)
        return choice

    @classmethod
    def has_valid_choice(cls, target, context, state=None):
        for client_state in target.get_client_states(state):
            while client_state.show_in_picker and client_state.test_channel(target, context):
                return True
        return False

class RecipePickerEnumerationStrategy(PickerEnumerationStrategy):
    __qualname__ = 'RecipePickerEnumerationStrategy'

    def build_choice_list(self, si, **kwargs):
        self._choices = [recipe for recipe in si.recipes]

    def find_best_choice(self, si):
        if self._choices is None:
            logger.error('Calling PickerEnumerationStrategy.find_best_choice() without first calling build_choice_list()', owner='rez')
            return
        weights = []
        for recipe in self._choices:
            result = crafting.crafting_process.CraftingProcess.recipe_test(si.target, si.context, recipe, si.sim, 0, False, from_autonomy=True)
            while result:
                weights.append((recipe.calculate_autonomy_weight(si.sim), recipe))
        if not weights:
            logger.error('Failed to find choice in autonomous recipe picker', owner='rez')
            return
        choice = sims4.random.pop_weighted(weights)
        return choice

class SimPickerEnumerationStrategy(PickerEnumerationStrategy):
    __qualname__ = 'SimPickerEnumerationStrategy'

    def build_choice_list(self, si, sim, **kwargs):
        self._choices = [filter_result for filter_result in si._get_valid_sim_choices(si.target, si.context, **kwargs)]

    def find_best_choice(self, si):
        weights = [(filter_result.score, filter_result.sim_info.id) for filter_result in self._choices]
        choice = sims4.random.pop_weighted(weights)
        return choice

class LotPickerEnumerationStrategy(PickerEnumerationStrategy):
    __qualname__ = 'LotPickerEnumerationStrategy'

    def build_choice_list(self, si, sim, **kwargs):
        self._choices = [filter_result for filter_result in si._get_valid_lot_choices(si.target, si.context)]

    def find_best_choice(self, si):
        choice = random.choice(self._choices)
        return choice

class ObjectPickerEnumerationStrategy(PickerEnumerationStrategy):
    __qualname__ = 'ObjectPickerEnumerationStrategy'

    def build_choice_list(self, si, sim, **kwargs):
        self._choices = [obj for obj in si._get_objects_gen(si.target, si.context)]

    def find_best_choice(self, si):
        choice = random.choice(self._choices)
        return choice

