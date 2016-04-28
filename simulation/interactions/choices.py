import collections
import weakref
from event_testing.results import TestResult, EnqueueResult
from sims4.localization import LocalizationHelperTuning
from singletons import DEFAULT
from uid import unique_id, UniqueIdGenerator
import gsi_handlers.sim_handlers_log
import sims4.log
__all__ = ['ChoiceMenu']
_normal_logger = sims4.log.LoggerClass('Interactions')
logger = _normal_logger
with sims4.reload.protected(globals()):
    _show_interaction_failure_reason = False

def toggle_show_interaction_failure_reason(enable=False):
    global _show_interaction_failure_reason
    _show_interaction_failure_reason = enable if enable is not None else not _show_interaction_failure_reason

def log_to_cheat_console(enable:bool=None, _connection=None):
    pass

class MenuItem:
    __qualname__ = 'MenuItem'
    __slots__ = ('choice', 'result', 'category_key', 'deprecated', 'target_invalid')

    def __init__(self, choice, result, category_key):
        self.choice = choice
        self.result = result
        self.category_key = category_key
        self.deprecated = False
        self.target_invalid = False

    def __repr__(self):
        return str(self.choice)

@unique_id('revision')
class ChoiceMenu:
    __qualname__ = 'ChoiceMenu'

    def __init__(self, aops, context, user_pick_target=None, make_pass=False):
        self.context = context
        self.menu_items = collections.OrderedDict()
        self.make_pass = make_pass
        if context.sim is not None:

            def remove_sim(k, selfref=weakref.ref(self)):
                self = selfref()
                if self is not None:
                    self.clear()

            self.simref = context.sim.ref(remove_sim)
        self.objects = weakref.WeakKeyDictionary()

        def remove(k, selfref=weakref.ref(self)):
            self = selfref()
            if self is not None:
                id_list = self.objects.data.get(k)
                del self.objects.data[k]
                if id_list:
                    while True:
                        for choice_id in id_list:
                            self.menu_items[choice_id].deprecated = True
                            self.menu_items[choice_id].target_invalid = True

        self.objects._remove = remove
        if aops is not None:
            for aop in aops:
                result = self.add_aop(aop, user_pick_target=user_pick_target)
                if not result and not result.tooltip:
                    pass
                if result:
                    result = DEFAULT
                potentials = aop.affordance.potential_pie_menu_sub_interactions_gen(aop.target, context, **aop.interaction_parameters)
                for (mixer_aop, mixer_aop_result) in potentials:
                    if result is not DEFAULT:
                        mixer_aop_result = result
                    self.add_aop(mixer_aop, result_override=mixer_aop_result, do_test=False)
        if gsi_handlers.sim_handlers_log.pie_menu_generation_archiver.enabled:
            gsi_handlers.sim_handlers_log.archive_pie_menu_option(context.sim, user_pick_target)

    def __len__(self):
        return len(self.menu_items)

    def __iter__(self):
        return iter(self.menu_items.items())

    def deprecate_aop(self, aop):
        raise RuntimeError('[bhill] This function is believed to be dead code and is scheduled for pruning. If this exception has been raised, the code is not dead and this exception should be removed.')
        menu_item = self.menu_items.get(aop.aop_id)
        if menu_item is not None:
            menu_item.deprecated = True

    def invalidate_choices_based_on_target(self, target):
        id_list = self.objects.get(target)
        if id_list is not None:
            del self.objects[target]
            for choice_id in id_list:
                menu_item = self.menu_items[choice_id]
                menu_item.deprecated = True
                menu_item.target_invalid = True

    @staticmethod
    def is_valid_aop(aop, context, make_pass, user_pick_target=None, result_override=DEFAULT, do_test=True):
        test_result = None
        result = TestResult.TRUE
        if result_override is not DEFAULT:
            result = result_override
        else:
            if not make_pass:
                if user_pick_target is not None and user_pick_target.check_affordance_for_suppression(context.sim, aop, user_directed=True):
                    result = TestResult(False, '{} failed, aop is being suppressed.', aop)
                else:
                    result = aop.test(context)
                    test_result = str(result)
            else:
                result = aop.can_make_test_pass(context)
            if not result:
                logger.info('Test Failure: {}: {}', aop, result.reason)
            if not result:
                if _show_interaction_failure_reason:
                    result = TestResult(result.result, tooltip=lambda *_, reason=result.reason, **__: LocalizationHelperTuning.get_name_value_pair('Failure', reason))
                elif not result.tooltip:
                    result = TestResult(False, '{} failed and has no tooltip', aop)
            if do_test and make_pass and aop.test(context):
                result = TestResult(False, '{} already passes', aop)
        if gsi_handlers.sim_handlers_log.pie_menu_generation_archiver.enabled:
            gsi_handlers.sim_handlers_log.log_aop_result(context.sim, aop, result, test_result)
        return result

    def add_aop(self, aop, user_pick_target=None, result_override=DEFAULT, do_test=True):
        result = ChoiceMenu.is_valid_aop(aop, self.context, self.make_pass, user_pick_target=user_pick_target, result_override=result_override, do_test=do_test)
        if aop.affordance.allow_user_directed is False:
            if _show_interaction_failure_reason:
                if result:
                    failure_result = TestResult(False, tooltip=lambda *_, **__: LocalizationHelperTuning.get_name_value_pair('Failure', 'Not allowed user-directed'))
                else:
                    failure_result = result
                self._add_menu_item(aop, failure_result)
            return result
        if not result and not result.tooltip:
            return result
        self._add_menu_item(aop, result)
        return result

    def _add_menu_item(self, aop, result):
        category = aop.affordance.get_pie_menu_category(**aop.interaction_parameters)
        category_key = None if category is None else category.guid64
        self.menu_items[aop.aop_id] = MenuItem(aop, result, category_key)
        if aop.target is not None:
            id_list = self.objects.get(aop.target)
            if id_list is None:
                id_list = []
                self.objects[aop.target] = id_list
            id_list.append(aop.aop_id)

    def select(self, choice_id):
        if self.context.sim is not None and self.context.sim.queue.visible_len() >= self.context.sim.max_interactions:
            return EnqueueResult.NONE
        context = self.context.clone_for_user_directed_choice()
        selection = self.menu_items.get(choice_id)
        if selection is not None:
            if selection.result:
                if not self.make_pass:
                    return selection.choice.test_and_execute(context)
                return selection.choice.make_test_pass(context)
            else:
                logger.warn('Attempt to select invalid interaction from a ChoiceMenu')
        if not self.make_pass:
            return EnqueueResult.NONE
        return TestResult.NONE

    def clear(self):
        self.menu_items.clear()
        self.objects = None
        self.context = None
        self.simref = None

choice_collection_id_gen = UniqueIdGenerator(1)

class ChoiceMenuCollection:
    __qualname__ = 'ChoiceMenuCollection'

    def __init__(self, callback=None):
        self.menus = weakref.WeakKeyDictionary()
        self.revision = choice_collection_id_gen()
        self._callback = callback
        self._visible_choice_ids = set()

    @property
    def has_visible_choices(self):
        return len(self._visible_choice_ids)

    def get_choices_gen(self):
        for (owning_interaction, menu) in self.menus.items():
            for (choice_id, choice) in menu:
                while choice_id in self._visible_choice_ids:
                    yield (owning_interaction, choice_id, choice)

    def _cache_visible_choice_ids(self):
        self._visible_choice_ids.clear()
        for menu in self.menus.values():
            valid_choices = set(aop_id for (aop_id, menu_item) in menu if not menu_item.deprecated)
            while valid_choices:
                self._visible_choice_ids = self._visible_choice_ids.union(valid_choices)

    def _on_modified(self, reason=None):
        self.revision = choice_collection_id_gen()
        if self._callback:
            self._callback(self)
        self._cache_visible_choice_ids()

    def invalidate_choices_based_on_target(self, target):
        for menu in self.menus.values():
            menu.invalidate_choices_based_on_target(target)

    def get_sub_menu(self, owner):
        return self.menus.get(owner, None)

    def add_menu(self, menu, owner):
        if menu is not None:
            self.menus[owner] = menu
            self._on_modified()

    def remove_menu(self, owner):
        if owner in self.menus:
            del self.menus[owner]
            self._on_modified()

    def clear(self, reason=None):
        self.menus = {}
        self._on_modified()

    def select(self, choice_id):
        owner = self.get_owner_for_id(choice_id)
        if owner:
            return self.menus[owner].select(choice_id)
        logger.warn('Attempt to select invalid interaction from a ChioceMenuCollection')
        return EnqueueResult.NONE

    def get_owner_for_id(self, choice_id):
        for (owner, menu) in self.menus.items():
            while choice_id in menu.menu_items:
                return owner

