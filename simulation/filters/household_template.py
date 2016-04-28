import random
from relationships.relationship import Relationship
from sims import sim_info_types
from sims4.tuning.tunable import HasTunableReference, TunableList, TunableTuple, TunableEnumEntry, TunableRange, TunableEnumWithFilter, Tunable
import filters.sim_template
import relationships.relationship_bit
import services
import sims.genealogy_tracker
import sims.sim_spawner
import sims4.log
import sims4.resources
import sims4.tuning.instances
import sims4.utils
import tag
logger = sims4.log.Logger('HouseholdTemplate', default_owner='msantander')
HOUSEHOLD_FILTER_PREFIX = ['household_member']

class HouseholdTemplate(HasTunableReference, metaclass=sims4.tuning.instances.TunedInstanceMetaclass, manager=services.get_instance_manager(sims4.resources.Types.SIM_TEMPLATE)):
    __qualname__ = 'HouseholdTemplate'
    INSTANCE_TUNABLES = {'_household_members': TunableList(description='\n            A list of sim templates that will make up the sims in this household.\n            ', tunable=TunableTuple(sim_template=filters.sim_template.TunableSimTemplate.TunableReference(description='\n                    A template to use for creating household member\n                    '), household_member_tag=TunableEnumWithFilter(description='\n                        Tag to be used to create relationship between sim\n                        members.  This does NOT have to be unique for all\n                        household templates. If you want to add more tags\n                        in the tag tuning just add with prefix of\n                        household_member.\n                        ', tunable_type=tag.Tag, default=tag.Tag.INVALID, filter_prefixes=HOUSEHOLD_FILTER_PREFIX))), '_household_funds': TunableRange(description='\n            Starting funds for this household.\n            ', tunable_type=int, default=20000, minimum=0, maximum=99999999), '_household_relationship': TunableList(description='\n            Matrix of relationship that should be applied to household members.\n            ', tunable=TunableTuple(x=TunableEnumWithFilter(description='\n                    Tag of the household member to apply relationship to.\n                    ', tunable_type=tag.Tag, default=tag.Tag.INVALID, filter_prefixes=HOUSEHOLD_FILTER_PREFIX), y=TunableEnumWithFilter(description='\n                    Tag of the household member to be the target of relationship.\n                    ', tunable_type=tag.Tag, default=tag.Tag.INVALID, filter_prefixes=HOUSEHOLD_FILTER_PREFIX), is_spouse=Tunable(description='\n                    Check if x and y are spouses.\n                    ', tunable_type=bool, default=False), family_relationship=TunableEnumEntry(description='\n                        This is the family relationship between x and y.\n                        Example: if set to Father, x is the the father of y.\n                        ', tunable_type=sims.genealogy_tracker.FamilyRelationshipIndex, default=None), relationship_bits=TunableList(description='\n                    Relationship bits that should be applied to x with\n                    the target y. Any bits with a relationship track will add\n                    relationship track at value that will add the bit to both\n                    sims.  Any bits without Triggered track will only be\n                    applied only to x unless it is a Siginificant other Bit.\n                    \n                    Example: If friendship-friend bit is supplied which has a\n                    triggered track of LTR_Friendship_Main, then\n                    LTR_Frienship_main will be added to both sims with a random\n                    value of the min/max value of the bit data tuning that will\n                    supply bit.\n                    ', tunable=relationships.relationship_bit.RelationshipBit.TunableReference())))}

    @classmethod
    def _verify_tuning_callback(cls):
        tag_to_household_member_index = {}
        for (index, household_member_data) in enumerate(cls._household_members):
            while household_member_data.household_member_tag != tag.Tag.INVALID:
                household_member_tag = household_member_data.household_member_tag
                if household_member_tag in tag_to_household_member_index:
                    logger.error('Multiple household member have the same tag {}.  Orginally found at index:{}, but also set for index:{}', household_member_tag, tag_to_household_member_index[household_member_tag], index)
                else:
                    tag_to_household_member_index[household_member_tag] = index
        if cls._household_relationship and not tag_to_household_member_index:
            logger.error('Houshold relationship has been added but there are no tag info for household members.  Please update tuning and add tags to household members: {}.', cls.__name__)
            return
        family_relationship_mapping = {}
        spouse_pairs = []
        for (index, member_relationship_data) in enumerate(cls._household_relationship):
            x_member = member_relationship_data.x
            if x_member == tag.Tag.INVALID:
                logger.error('No tag set for x in household relationship at index {}. Please update tuning and set a tag', index)
            y_member = member_relationship_data.y
            if y_member == tag.Tag.INVALID:
                logger.error('No tag set for y in household relationship at index {}. Please update tuning and set a tag', index)
            if x_member not in tag_to_household_member_index:
                logger.error('The tag set for x :{} does not exist in household members. Please update tuning and update tag or set a household member with tag', x_member)
            if y_member not in tag_to_household_member_index:
                logger.error('The tag set for y :{} does not exist in household members. Please update tuning and update tag or set a household member with tag', y_member)
            if member_relationship_data.is_spouse:
                member_index = tag_to_household_member_index[x_member]
                household_member_data = cls._household_members[member_index]
                if household_member_data.sim_template._sim_creation_info.age_variant.min_age <= sim_info_types.Age.TEEN:
                    logger.error('Trying set spouse with sims of the inappropriate age.Check sim_template at index {} if set correctly.', member_index)
                member_index = tag_to_household_member_index[y_member]
                household_member_data = cls._household_members[member_index]
                if household_member_data.sim_template._sim_creation_info.age_variant.min_age <= sim_info_types.Age.TEEN:
                    logger.error('Trying set spouse with sims of the inappropriate age.Check sim_template at index {} if set correctly.', member_index)
                spouse_pairs.append((x_member, y_member, index))
                spouse_pairs.append((y_member, x_member, index))
            family_set_at_index = family_relationship_mapping.get((x_member, y_member))
            if family_set_at_index is not None:
                logger.error('There is already a family relationship between x_member and y_member.Family set at index:{} but also set at index: {}', family_set_at_index, index)
            while member_relationship_data.family_relationship is not None:
                family_relationship_mapping[(x_member, y_member)] = index
                family_relationship_mapping[(y_member, x_member)] = index
        for (x_member, y_member, household_relationship_index) in spouse_pairs:
            family_set_at_index = family_relationship_mapping.get((x_member, y_member))
            while family_set_at_index is not None:
                logger.error('Spouse is set for {} and {}, but also have family relationship. Update tuning: either uncheck spouse at index: {} or remove family relationship in household relationshipat index {}', x_member, y_member, household_relationship_index, family_set_at_index)

    @sims4.utils.classproperty
    def template_type(cls):
        return filters.sim_template.SimTemplateType.HOUSEHOLD

    @classmethod
    def get_household_members(cls):
        return cls._household_members

    @sims4.utils.classproperty
    def has_teen_or_below(cls):
        return any(household_member_data.sim_template._sim_creation_info.age_variant.min_age <= sim_info_types.Age.TEEN for household_member_data in cls._household_members)

    @sims4.utils.classproperty
    def num_members(cls):
        return len(cls._household_members)

    @sims4.utils.classproperty
    def has_spouse(cls):
        for household_relationship in cls._household_relationship:
            while household_relationship.is_spouse or Relationship.MARRIAGE_RELATIONSHIP_BIT in set(household_relationship.relationship_bits):
                return True
        return False

    @classmethod
    def create_household(cls, zone_to_fill_id, account, creation_source:str='household_template'):
        (household, _) = cls._create_household(zone_to_fill_id, account, [household_member.sim_template.sim_creator for household_member in cls._household_members], creation_source=creation_source)
        return household

    @classmethod
    def get_sim_infos_from_household(cls, zone_id, insertion_indexes_to_sim_creators, creation_source:str='household_template'):
        sim_creators = []
        for (index, household_member) in enumerate(cls._household_members):
            if index in insertion_indexes_to_sim_creators:
                sim_creators.append(insertion_indexes_to_sim_creators[index])
            else:
                sim_creators.append(household_member.sim_template.sim_creator)
        (household, sim_infos) = cls._create_household(zone_id, None, sim_creators, indexes_sim_info_to_return=insertion_indexes_to_sim_creators.keys(), creation_source=creation_source)
        return (household, sim_infos)

    @classmethod
    def _create_household(cls, home_zone_id, account, sim_creators, indexes_sim_info_to_return=None, creation_source:str='household_template'):
        if home_zone_id is None:
            home_zone_id = 0
        (created_sim_infos, household) = sims.sim_spawner.SimSpawner.create_sim_infos(sim_creators, zone_id=home_zone_id, account=account, starting_funds=cls._household_funds, creation_source=creation_source)
        household.home_zone_id = home_zone_id
        tag_to_sim_info = {}
        sim_infos_to_return = None if indexes_sim_info_to_return is None else []
        for (index, created_sim_info) in enumerate(created_sim_infos):
            household_member_data = cls._household_members[index]
            household_member_data.sim_template.add_template_data_to_sim(created_sim_info)
            created_sim_info.is_npc = True
            if household_member_data.household_member_tag != tag.Tag.INVALID:
                tag_to_sim_info[household_member_data.household_member_tag] = created_sim_info
            while indexes_sim_info_to_return is not None and index in indexes_sim_info_to_return:
                sim_infos_to_return.append(created_sim_info)
        if not tag_to_sim_info:
            return (household, sim_infos_to_return)
        for member_relationship_data in cls._household_relationship:
            source_sim_info = tag_to_sim_info.get(member_relationship_data.x)
            target_sim_info = tag_to_sim_info.get(member_relationship_data.y)
            if member_relationship_data.is_spouse:
                source_sim_info.update_spouse_sim_id(target_sim_info.id)
                target_sim_info.update_spouse_sim_id(source_sim_info.id)
            while member_relationship_data.family_relationship is not None:
                target_sim_info.set_and_propagate_family_relation(member_relationship_data.family_relationship, source_sim_info)
        household.set_default_relationships()
        for member_relationship_data in cls._household_relationship:
            source_sim_info = tag_to_sim_info.get(member_relationship_data.x)
            target_sim_info = tag_to_sim_info.get(member_relationship_data.y)
            for bit_to_add in member_relationship_data.relationship_bits:
                bit_triggered_track = bit_to_add.triggered_track
                if bit_triggered_track is not None:
                    bit_track_node = bit_to_add.triggered_track.get_bit_track_node_for_bit(bit_to_add)
                else:
                    bit_track_node = None
                if bit_track_node is not None:
                    rand_score = random.randint(bit_track_node.min_rel, bit_track_node.max_rel)
                    source_sim_info.relationship_tracker.add_relationship_score(target_sim_info.id, rand_score, bit_triggered_track)
                    target_sim_info.relationship_tracker.add_relationship_score(source_sim_info.id, rand_score, bit_triggered_track)
                else:
                    source_sim_info.relationship_tracker.add_relationship_bit(target_sim_info.id, bit_to_add, force_add=True)
                    while bit_to_add is Relationship.MARRIAGE_RELATIONSHIP_BIT:
                        target_sim_info.relationship_tracker.add_relationship_bit(source_sim_info.id, bit_to_add, force_add=True)
        return (household, sim_infos_to_return)

