from sims4.tuning.tunable import Tunable

class StatisticComponentGlobalTuning:
    __qualname__ = 'StatisticComponentGlobalTuning'
    DEFAULT_RADIUS_TO_CONSIDER_OFF_LOT_OBJECTS = Tunable(description='\n        The radius from the Sim that an off-lot object must be for a Sim to consider it.\n        If the object is not on the active lot and outside of this radius, the Sim will \n        ignore it.\n        ', tunable_type=float, default=20)
    DEFAULT_OFF_LOT_TOLERANCE = Tunable(description="\n        The tolerance for when a Sim is considered off the lot.  If a Sim is off the \n        lot but within this tolerance, he will be considered on the lot from autonomy's \n        perspective.  Note that this only effects autonomy, nothing else. \n        ", tunable_type=float, default=5)

