
class ParameterizedAutonomyRequestInfo:
    __qualname__ = 'ParameterizedAutonomyRequestInfo'

    def __init__(self, commodities, static_commodities, objects, retain_priority, retain_carry_target=True, objects_to_ignore=None, affordances=None, randomization_override=None, radius_to_consider=0, consider_scores_of_zero=False):
        self.commodities = commodities
        self.static_commodities = static_commodities
        self.objects = objects
        self.retain_priority = retain_priority
        self.objects_to_ignore = objects_to_ignore
        self.affordances = affordances
        self.retain_carry_target = retain_carry_target
        self.randomization_override = randomization_override
        self.radius_to_consider = radius_to_consider
        self.consider_scores_of_zero = consider_scores_of_zero

