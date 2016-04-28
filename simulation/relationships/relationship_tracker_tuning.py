from relationships.relationship_bit import RelationshipBit
from relationships.relationship_track import RelationshipTrack
from sims4.tuning.tunable import AutoFactoryInit, HasTunableSingletonFactory, Tunable, TunableSet, TunableMapping, TunableEnumEntry, TunableList, TunableTuple
import enum

class DefaultGenealogyLink(enum.Int):
    __qualname__ = 'DefaultGenealogyLink'
    Roommate = 0
    FamilyMember = 1
    Spouse = 2

class DefaultRelationship(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'DefaultRelationship'
    FACTORY_TUNABLES = {'relationship_tracks': TunableList(description='\n                A list of relationship track and value pairs.\n                E.g. a spouse has Romantic relationship track value of 75. \n                ', tunable=TunableTuple(track=RelationshipTrack.TunableReference(description='\n                        The relationship track that is added to the relationship\n                        between the two sims.'), value=Tunable(int, default=0, description='\n                        The relationship track is set to this value.\n                        '))), 'relationship_bits': TunableSet(description='\n                A set of untracked relationship bits that are applied to the\n                relationship between the two sims. These are bits that are\n                provided outside of the relationship_track being set. \n                E.g. everyone in the household should have the Has Met bit\n                and the spouse should have the First Kiss bit.\n                ', tunable=RelationshipBit.TunableReference())}

    def apply(self, relationship_tracker, target_sim):
        sim_to_target_tracker = relationship_tracker.get_relationship_track_tracker(target_sim.sim_id, add=True)
        for data in self.relationship_tracks:
            track = data['track']
            value = data['value']
            relationship_track = sim_to_target_tracker.get_statistic(track, True)
            if relationship_track.get_value() < value:
                sim_to_target_tracker.set_value(track, value)
            relationship_track.update_instance_data()
        for bit in self.relationship_bits:
            sim_to_target_tracker.relationship.add_bit(bit)

class DefaultRelationshipInHousehold:
    __qualname__ = 'DefaultRelationshipInHousehold'
    RelationshipSetupMap = TunableMapping(description='\n        A mapping of the possible genealogy links in a family to the default \n        relationship values that we want to start our household members. \n        ', key_type=TunableEnumEntry(DefaultGenealogyLink, default=DefaultGenealogyLink.Roommate, description='\n            A genealogy link between the two sims in the household.\n            '), value_type=DefaultRelationship.TunableFactory(), key_name='Family Link', value_name='Default Relationship Setup')

