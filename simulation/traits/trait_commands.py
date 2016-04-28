from server_commands.argument_helpers import OptionalTargetParam, get_optional_target, TunableInstanceParam
import sims4

@sims4.commands.Command('traits.show_traits', command_type=sims4.commands.CommandType.Automation)
def show_traits(opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is not None:
        trait_tracker = sim.sim_info.trait_tracker
        if trait_tracker is None:
            sims4.commands.output("Sim {} doesn't have trait tracker".format(sim), _connection)
            return
        sims4.commands.output('Sim {} has {} traits equipped, {} slots left'.format(sim, len(trait_tracker), trait_tracker.empty_slot_number), _connection)
        for trait in trait_tracker.equipped_traits:
            s = 'Equipped: {}'.format(trait.__name__)
            sims4.commands.output(s, _connection)

@sims4.commands.Command('traits.equip_trait', command_type=sims4.commands.CommandType.Live)
def equip_trait(trait_type, opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is not None:
        trait_tracker = sim.sim_info.trait_tracker
        if trait_tracker is None:
            sims4.commands.output("Sim {} doesn't have trait tracker".format(sim), _connection)
            return False
        trait_tracker.add_trait(trait_type)
        return True
    return False

@sims4.commands.Command('traits.remove_trait', command_type=sims4.commands.CommandType.Automation)
def remove_trait(trait_type, opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is not None:
        trait_tracker = sim.sim_info.trait_tracker
        if trait_tracker is None:
            sims4.commands.output("Sim {} doesn't have trait tracker".format(sim), _connection)
            return False
        trait_tracker.remove_trait(trait_type)
        return True
    return False

@sims4.commands.Command('traits.clear_traits', command_type=sims4.commands.CommandType.Automation)
def clear_traits(opt_sim:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_sim, _connection)
    if sim is not None:
        trait_tracker = sim.sim_info.trait_tracker
        if trait_tracker is None:
            sims4.commands.output("Sim {} doesn't have trait tracker".format(sim), _connection)
            return False
        trait_tracker.clear_traits()
        return True
    return False

