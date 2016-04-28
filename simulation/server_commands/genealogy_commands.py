from server_commands.argument_helpers import OptionalTargetParam, get_optional_target, RequiredTargetParam
from sims.genealogy_tracker import FamilyRelationshipIndex
from sims.sim_info_types import Age, Gender
from sims.sim_spawner import SimCreator, SimSpawner
import sims4.commands

@sims4.commands.Command('genealogy.print')
def genalogy_print(sim_id:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(sim_id, _connection)
    if sim is None:
        return False
    genealogy = sim.sim_info.genealogy
    genealogy.log_contents()
    return True

@sims4.commands.Command('genealogy.generate_dynasty')
def genealogy_random_generate(sim_id:OptionalTargetParam=None, generations:int=4, _connection=None):
    sim = get_optional_target(sim_id, _connection)
    if sim is None:
        return False

    def add_parents(child, generation=0):
        if generation >= generations:
            return
        sim_creators = (SimCreator(gender=Gender.MALE, age=Age.ADULT, last_name=child.last_name), SimCreator(gender=Gender.FEMALE, age=Age.ADULT))
        (sim_info_list, _) = SimSpawner.create_sim_infos(sim_creators, household=sim.household, account=sim.account, zone_id=sim.zone_id, creation_source='cheat: genealogy.generate_dynasty')
        sim_info_list[0].death_tracker.set_death_type(1)
        sim_info_list[1].death_tracker.set_death_type(1)
        child.set_and_propagate_family_relation(FamilyRelationshipIndex.FATHER, sim_info_list[0])
        child.set_and_propagate_family_relation(FamilyRelationshipIndex.MOTHER, sim_info_list[1])
        add_parents(sim_info_list[0], generation=generation + 1)
        add_parents(sim_info_list[1], generation=generation + 1)

    add_parents(sim.sim_info)
    sims4.commands.output('Dynasty created for {}'.format(sim), _connection)
    return True

@sims4.commands.Command('genealogy.prune')
def genealogy_prune(sim_id:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(sim_id, _connection)
    if sim is None:
        return False
    household = sim.household
    if household is None:
        return False
    household.prune_distant_relatives()
    return True

@sims4.commands.Command('genealogy.find_relation')
def genalogy_relation(x_sim, y_sim, _connection=None):
    output = sims4.commands.Output(_connection)
    sim_x = x_sim.get_target()
    bit = None
    if sim_x is not None:
        bit = sim_x.sim_info.genealogy.get_family_relationship_bit(y_sim.target_id, output)
    return bit is not None

