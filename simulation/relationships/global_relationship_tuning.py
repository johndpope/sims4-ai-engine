from sims4.tuning.tunable import TunableReference
import services
import sims4.resources

class RelationshipGlobalTuning:
    __qualname__ = 'RelationshipGlobalTuning'
    REL_INSPECTOR_TRACK = TunableReference(description='\n                                                This is the track that the rel inspector follows.  Any bits \n                                                that are apart of this track should NOT be marked visible \n                                                unless you want them showing up in both places.\n                                                ', manager=services.get_instance_manager(sims4.resources.Types.STATISTIC), class_restrictions='RelationshipTrack')
    NEIGHBOR_RELATIONSHIP_BIT = TunableReference(description='\n                                    The relationship bit automatically applied to sims who live on the \n                                    same street but in difference households.\n                                    ', manager=services.get_instance_manager(sims4.resources.Types.RELATIONSHIP_BIT))

