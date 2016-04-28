import itertools
from animation.asm import should_use_boundary_condition_cache, get_boundary_condition_cache_debug_information
from autonomy import autonomy_service, content_sets
from interactions.interaction_instance_manager import should_use_animation_constaint_cache, get_animation_constraint_cache_debug_information
from sims4.commands import CommandType
import caches
import sims4.commands
import sims4.log
logger = sims4.log.Logger('CacheCommand')

@sims4.commands.Command('caches.enable_all_caches', command_type=sims4.commands.CommandType.Automation)
def enable_all_caches(enable:bool=True, _connection=None):
    caches.skip_cache = not enable
    caches.clear_all_caches(force=True)

@sims4.commands.Command('caches.enable_asm_cache')
def enable_asm_cache(enable:bool=True, _connection=None):
    caches.use_asm_cache = True

@sims4.commands.Command('caches.disable_asm_cache')
def disable_asm_cache(enable:bool=True, _connection=None):
    caches.use_asm_cache = False

@sims4.commands.Command('caches.enable_boundary_condition_cache')
def enable_boundary_condition_cache(enable:bool=True, _connection=None):
    caches.use_boundary_condition_cache = True

@sims4.commands.Command('caches.disable_boundary_condition_cache')
def disable_boundary_condition_cache(enable:bool=True, _connection=None):
    caches.use_boundary_condition_cache = False

@sims4.commands.Command('caches.enable_constraints_cache')
def enable_constraints_cache(enable:bool=True, _connection=None):
    caches.use_constraints_cache = True

@sims4.commands.Command('caches.disable_constraints_cache')
def disable_constraints_cache(enable:bool=True, _connection=None):
    caches.use_constraints_cache = False

@sims4.commands.Command('caches.enable_autonomy_cache_double_check')
def enable_autonomy_cache_double_check(enable:bool=True, _connection=None):
    if enable:
        caches.double_check_groups.add(autonomy_service.AUTONOMY_CACHE_GROUP)
    else:
        caches.double_check_groups.discard(autonomy_service.AUTONOMY_CACHE_GROUP)

@sims4.commands.Command('caches.enable_content_set_generation_cache_double_check')
def enable_content_set_generation_cache_double_check(enable:bool=True, _connection=None):
    if enable:
        caches.double_check_groups.add(content_sets.CONTENT_SET_GENERATION_CACHE_GROUP)
    else:
        caches.double_check_groups.discard(content_sets.CONTENT_SET_GENERATION_CACHE_GROUP)

@sims4.commands.Command('caches.status', command_type=CommandType.Cheat)
def cache_status(_connection=None):
    output = sims4.commands.CheatOutput(_connection)
    output('Boundary Condition Cache Live   : {}'.format(should_use_boundary_condition_cache()))
    output('Animation Constraint Cache Live : {}'.format(should_use_animation_constaint_cache()))
    for (token, value, description) in itertools.chain(get_animation_constraint_cache_debug_information(), get_boundary_condition_cache_debug_information()):
        output('{:31} : {:<5} ({:45})'.format(token, value, description))

