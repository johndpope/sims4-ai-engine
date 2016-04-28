from event_testing.tests import TunableTestSet, TunableGlobalTestSet
from interactions.utils.outcome import InteractionOutcome
from sims4.tuning.instances import lock_instance_tunables

def create_tuningless_interaction(affordance, **kwargs):
    locked_fields = dict(basic_reserve_object=None, basic_focus=None, allow_forward=False, allow_from_world=True, basic_extras=[], _constraints=[], tests=TunableTestSet.DEFAULT_LIST, test_globals=TunableGlobalTestSet.DEFAULT_LIST, test_autonomous=TunableTestSet.DEFAULT_LIST, _static_commodities=[], _false_advertisements=[], _hidden_false_advertisements=[], _cancelable_by_user=True, visible=False, simless=False, allow_autonomous=False, allow_user_directed=False, debug=False, outcome=InteractionOutcome())
    if kwargs:
        locked_fields.update(kwargs)
    lock_instance_tunables(affordance, **locked_fields)

def create_tuningless_superinteraction(affordance):
    create_tuningless_interaction(affordance)
    lock_instance_tunables(affordance, pre_add_autonomy_commodities=None, pre_run_autonomy_commodities=None, post_guaranteed_autonomy_commodities=None, post_run_autonomy_commodities=None, super_affordance_compatibility=None, basic_content=None, outfit_change=None, outfit_priority=None, joinable=None, object_reservation_tests=TunableTestSet.DEFAULT_LIST, ignore_group_socials=False)

