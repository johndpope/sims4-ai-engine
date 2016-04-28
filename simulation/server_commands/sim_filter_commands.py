from server_commands.argument_helpers import OptionalTargetParam, get_optional_target, TunableInstanceParam, get_tunable_instance
from sims.sim_spawner import SimSpawner
import filters
import services
import sims.sim_spawner
import sims4.commands
import sims4.log
logger = sims4.log.Logger('SimFilter')

def _find_sims_with_filter(filter_type, requesting_sim, callback, _connection=None):
    if callback is None:
        sims4.commands.output('No callback supplied for _execute_filter', _connection)
        return
    requesting_sim_info = requesting_sim.sim_info if requesting_sim is not None else None
    services.sim_filter_service().submit_filter(filter_type, callback, None, requesting_sim_info=requesting_sim_info)
    sims4.commands.output('Processing filter: {}'.format(filter_type), _connection)

@sims4.commands.Command('filter.find')
def filter_find(filter_type, opt_sim:OptionalTargetParam=None, _connection=None):

    def _print_found_sims(results, callback_event_data):
        if results:
            for result in results:
                sims4.commands.output('   Sim ID:{}, score: {}'.format(result.sim_info.id, result.score), _connection)
            logger.info('Sims ID matching request {0}', results)
        else:
            sims4.commands.output('No Match Found', _connection)

    sim = get_optional_target(opt_sim, _connection)
    _find_sims_with_filter(filter_type, sim, _print_found_sims, _connection)

@sims4.commands.Command('filter.invite')
def filter_invite(filter_type, opt_sim:OptionalTargetParam=None, _connection=None):

    def _spawn_found_sims(results, callback_event_data):
        if results is not None:
            for result in results:
                sims4.commands.output('Sim : {}'.format(result.sim_info.id), _connection)
                sims.sim_spawner.SimSpawner.load_sim(result.sim_info.id)
            logger.info('Sims ID matching request {0}', results)

    sim = get_optional_target(opt_sim, _connection)
    _find_sims_with_filter(filter_type, sim, _spawn_found_sims, _connection)

@sims4.commands.Command('filter.spawn_sim')
def filter_spawn_sim(sim_id, _connection=None):
    zone_id = sims4.zone_utils.get_zone_id()
    if sims.sim_spawner.SimSpawner.load_sim(sim_id):
        sims4.commands.output('Sim ID: {} has been invited to lot: {}'.format(sim_id, zone_id), _connection)
    else:
        sims4.commands.output('filter.spawn_sim command faild for sim id: {}  to lot id: {}'.format(sim_id, zone_id), _connection)

@sims4.commands.Command('filter.create')
def filter_create(filter_type, continue_if_constraints_fail:bool=False, opt_sim:OptionalTargetParam=None, num_of_sims:int=1, _connection=None):

    def callback(sim_infos, callback_event_data):
        if sim_infos:
            for sim_info in sim_infos:
                services.get_zone_situation_manager().add_debug_sim_id(sim_info.id)
                sims.sim_spawner.SimSpawner.spawn_sim(sim_info, None)
                sims4.commands.output('Spawned {} with id {}'.format(sim_info, sim_info.id), _connection)
        else:
            sims4.commands.output('No filter with {}'.format(callback_event_data), _connection)

    sim = get_optional_target(opt_sim, _connection)
    filter_name = str(filter_type)
    services.sim_filter_service().submit_matching_filter(num_of_sims, filter_type, callback, filter_name, requesting_sim_info=sim.sim_info, continue_if_constraints_fail=continue_if_constraints_fail)
    sims4.commands.output('Processing filter: {}'.format(filter_name), _connection)

@sims4.commands.Command('filter.create_many_infos')
def filter_create_many_infos(*filter_names, _connection=None):

    def callback(results, callback_event_data):
        sims4.commands.output('Filter: {}'.format(callback_event_data), _connection)
        for result in results:
            sims4.commands.output('   Sim ID:{}, score: {}'.format(result.sim_info.id, result.score), _connection)

    for filter_name in filter_names:
        filter_type = get_tunable_instance(sims4.resources.Types.SIM_FILTER, filter_name)
        if filter_type is not None:
            services.sim_filter_service().submit_filter(filter_type, callback, callback_event_data=filter_name, create_if_needed=True)
            sims4.commands.output('Processing filter: {}'.format(filter_name), _connection)
        else:
            sims4.commands.output('Unknown filter: {}'.format(filter_name), _connection)

@sims4.commands.Command('filter.create_friends')
def filter_create_friends(number_to_create, opt_sim:OptionalTargetParam=None, _connection=None):

    def callback(sim_infos, callback_event_data):
        if sim_infos:
            for sim_info in sim_infos:
                sims4.commands.output('Created info name {}'.format(sim_info.full_name), _connection)

    sim = get_optional_target(opt_sim, _connection)
    services.sim_filter_service().submit_matching_filter(number_to_create, filters.tunable.TunableSimFilter.ANY_FILTER, callback, requesting_sim_info=sim.sim_info, continue_if_constraints_fail=True, allow_yielding=True, blacklist_sim_ids={sim_info.id for sim_info in services.sim_info_manager().values()})

@sims4.commands.Command('filter.create_from_sim_template')
def create_sim_info_from_template(sim_template, _connection=None):
    sims4.commands.output('Processing sim_template: {}'.format(sim_template), _connection)
    sim_creator = sim_template.sim_creator
    (sim_info_list, household) = SimSpawner.create_sim_infos([sim_creator], creation_source='cheat: filter.create_from_sim_template')
    if sim_info_list:
        created_sim_info = sim_info_list.pop()
        sim_template.add_template_data_to_sim(created_sim_info)
        sims4.commands.output('Finished template creation: {}'.format(household), _connection)
    else:
        sims4.commands.output('Failed to create sim info from template: {}'.format(sim_template), _connection)

@sims4.commands.Command('filter.create_from_sim_templates')
def create_sim_info_from_templates(*sim_template_names, _connection=None):
    sims4.commands.output('Processing sim_templates: {}'.format(sim_template_names), _connection)
    sim_creators = []
    sim_templates = []
    for sim_template_name in sim_template_names:
        sim_template = get_tunable_instance(sims4.resources.Types.SIM_TEMPLATE, sim_template_name)
        sim_templates.append(sim_template)
        sim_creators.append(sim_template.sim_creator)
    (household_template_type, insertion_indexes_to_sim_creators) = filters.tunable.TunableSimFilter.find_household_template_that_contains_sim_filter(sim_creators)
    if household_template_type is not None:
        sims4.commands.output('Household template for creation: {}'.format(household_template_type), _connection)
        created_sim_infos = household_template_type.get_sim_infos_from_household(0, insertion_indexes_to_sim_creators, creation_source='template: {}'.foramt(household_template_type.__name__))
        for (index, index_to_sim_creator) in enumerate(insertion_indexes_to_sim_creators.items()):
            created_sim_info = created_sim_infos[index]
            sim_template = sim_templates[sim_creators.index(index_to_sim_creator[1])]
            sims4.commands.output('Applying:{} to  {}'.format(sim_template, created_sim_info), _connection)
            sim_template.add_template_data_to_sim(created_sim_info)
        sims4.commands.output('Finished template creation: {}'.format(created_sim_infos[0].household), _connection)
    else:
        sims4.commands.output('Failed find template for creation', _connection)

