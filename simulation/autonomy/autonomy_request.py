import enum
import interactions
import services
import sims4.log
import singletons
logger = sims4.log.Logger('Autonomy', default_owner='rez')

class AutonomyPostureBehavior(enum.Int, export=False):
    __qualname__ = 'AutonomyPostureBehavior'
    FULL = 0
    IGNORE_SI_STATE = 1
    BEST_ALWAYS = 2

class AutonomyDistanceEstimationBehavior(enum.Int, export=False):
    __qualname__ = 'AutonomyDistanceEstimationBehavior'
    FULL = 0
    ALLOW_UNREACHABLE_LOCATIONS = 1
    IGNORE_DISTANCE = 2
    BEST_ALWAYS = 3

class AutonomyRequest:
    __qualname__ = 'AutonomyRequest'

    def __init__(self, sim, autonomy_mode=None, commodity_list=None, static_commodity_list=None, skipped_static_commodities=None, object_list=None, ignored_object_list=None, affordance_list=None, sleep_element=None, context=None, is_script_request=False, ignore_user_directed_and_autonomous=False, posture_behavior=AutonomyPostureBehavior.FULL, distance_estimation_behavior=AutonomyDistanceEstimationBehavior.FULL, record_test_result=None, constraint=None, consider_scores_of_zero=False, skipped_affordance_list=None, ignore_lockouts=False, apply_opportunity_cost=True, push_super_on_prepare=False, radius_to_consider=0, off_lot_autonomy_rule_override=None, autonomy_mode_label_override=None, **interaction_parameters):
        logger.assert_raise(autonomy_mode is not None, 'autonomy_mode cannot be None in the AutonomyRequest.')
        self._sim_ref = sim.ref()
        self.object_list = object_list
        self.ignored_object_list = ignored_object_list
        self.affordance_list = affordance_list
        self.skipped_affordance_list = skipped_affordance_list
        self.constraint = constraint
        self.sleep_element = sleep_element
        self.is_script_request = is_script_request
        self.ignore_user_directed_and_autonomous = ignore_user_directed_and_autonomous
        self.posture_behavior = posture_behavior
        self.distance_estimation_behavior = distance_estimation_behavior
        self.consider_scores_of_zero = consider_scores_of_zero
        self.record_test_result = record_test_result
        self.ignore_lockouts = ignore_lockouts
        self.apply_opportunity_cost = apply_opportunity_cost
        self.push_super_on_prepare = push_super_on_prepare
        self.radius_to_consider_squared = radius_to_consider*radius_to_consider
        self.off_lot_autonomy_rule_override = off_lot_autonomy_rule_override
        self.valid = True
        self.kwargs = interaction_parameters
        self._interactions_to_invalidate = []
        self.valid_interactions = None
        self.gsi_data = None
        self.similar_aop_cache = {}
        if context is None:
            self.context = interactions.context.InteractionContext(self.sim, interactions.context.InteractionContext.SOURCE_AUTONOMY, interactions.priority.Priority.Low, client=None, pick=None)
        else:
            self.context = context
        if commodity_list:
            if static_commodity_list:
                commodity_list = set(commodity_list)
                static_commodity_list = set(static_commodity_list)
                all_commodities = commodity_list.union(static_commodity_list)
            else:
                commodity_list = set(commodity_list)
                static_commodity_list = None
                all_commodities = commodity_list
        elif static_commodity_list:
            static_commodity_list = set(static_commodity_list)
            commodity_list = None
            all_commodities = static_commodity_list
        else:
            commodity_list = None
            static_commodity_list = None
            all_commodities = None
        if skipped_static_commodities:
            self.skipped_static_commodities = set(skipped_static_commodities)
        else:
            self.skipped_static_commodities = None
        self.commodity_list = commodity_list
        self.static_commodity_list = static_commodity_list
        self.all_commodities = all_commodities
        self.interactions_to_invalidate = []
        self.timestamp = services.time_service().sim_now
        self.autonomy_mode = autonomy_mode(self)
        self.autonomy_mode_label = autonomy_mode_label_override or str(self.autonomy_mode)

    def __repr__(self):
        return '<{}Request for {!s}>'.format(self.autonomy_mode_label, self.sim)

    @property
    def sim(self):
        return self._sim_ref()

    @property
    def has_commodities(self):
        if self.all_commodities:
            return True
        return False

    def on_interaction_created(self, interaction):
        self._interactions_to_invalidate.append(interaction)

    def invalidate_created_interactions(self, excluded_si=None):
        for interaction in self._interactions_to_invalidate:
            if not interaction.is_super:
                pass
            if interaction is excluded_si:
                pass
            interaction.invalidate()
        self._interactions_to_invalidate.clear()

    def objects_to_score_gen(self, motives:set=singletons.DEFAULT):
        if motives is singletons.DEFAULT:
            motives = self.all_commodities
        if not self.object_list:
            autonomy_rule = self.sim.get_off_lot_autonomy_rule_type() if self.off_lot_autonomy_rule_override is None else self.off_lot_autonomy_rule_override
            off_lot_radius = self.sim.get_off_lot_autonomy_radius()
            sim_is_on_active_lot = self.sim.is_on_active_lot(tolerance=self.sim.get_off_lot_autonomy_tolerance())
            for obj in services.object_manager().advertising_objects_gen(motives):
                if self.ignored_object_list and obj in self.ignored_object_list:
                    pass
                if not self.sim.autonomy_component.get_autonomous_availability_of_object(obj, autonomy_rule, off_lot_radius, sim_is_on_active_lot):
                    pass
                yield obj
            for obj in self.sim.inventory_component:
                if self.ignored_object_list and obj in self.ignored_object_list:
                    pass
                yield obj
        elif not motives:
            for obj in self.object_list:
                if self.ignored_object_list and obj in self.ignored_object_list:
                    pass
                yield obj
        else:
            for obj in self.object_list:
                while obj.commodity_flags & motives:
                    if self.ignored_object_list and obj in self.ignored_object_list:
                        pass
                    yield obj

