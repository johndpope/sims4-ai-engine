from protocolbuffers import InteractionOps_pb2 as interaction_protocol, Sims_pb2 as protocols, Consts_pb2
from protocolbuffers.DistributorOps_pb2 import Operation
from distributor.ops import GenericProtocolBufferOp
from distributor.rollback import ProtocolBufferRollback
from distributor.shared_messages import create_icon_info_msg, IconInfoData
from distributor.system import Distributor
from gsi_handlers import posture_graph_handlers
from interactions.choices import ChoiceMenu, toggle_show_interaction_failure_reason
from interactions.context import InteractionContext
from interactions.priority import Priority
from interactions.utils.routing import push_backoff
from server.config_service import ContentModes
from server.pick_info import PickInfo, PickType, PICK_USE_TERRAIN_OBJECT
from server_commands.argument_helpers import get_optional_target, OptionalTargetParam, RequiredTargetParam, TunableInstanceParam
from sims4.commands import Output
from sims4.localization import TunableLocalizedStringFactory, create_tokens
from sims4.tuning.tunable import TunableResourceKey
import autonomy.content_sets
import enum
import interactions.social.social_mixer_interaction
import interactions.utils.outcome
import objects.terrain
import postures.transition_sequence
import routing
import services
import sims4.commands
import sims4.log
import sims4.reload
import telemetry_helper
logger = sims4.log.Logger('Interactions')
TELEMETRY_GROUP_PIE_MENU = 'PIEM'
TELEMETRY_HOOK_CREATE_PIE_MENU = 'PIEM'
writer = sims4.telemetry.TelemetryWriter(TELEMETRY_GROUP_PIE_MENU)
with sims4.reload.protected(globals()):
    _make_pass = False
    _show_interaction_tuning_name = False

class InteractionCommandsTuning:
    __qualname__ = 'InteractionCommandsTuning'
    MAKE_PASS_INTERACTION_NAME = TunableLocalizedStringFactory(description="\n        The localized string used to create interaction choice names when 'make pass' mode is active.\n        ")
    INTERACTION_TUNING_NAME = TunableLocalizedStringFactory(description='\n        The localized string used to create interaction choice names and\n        display the tuning name next to it.\n        ')

def _active_sim(client):
    if client:
        return client.active_sim

@sims4.commands.Command('interactions.posture_graph_build')
def build_posture_graph(_connection=None):
    services.current_zone().posture_graph_service.rebuild()

@sims4.commands.Command('interactions.posture_graph_export')
def export_posture_graph(_connection=None):
    services.current_zone().posture_graph_service.export()

@sims4.commands.Command('interactions.posture_graph_gsi_min_progress')
def posture_graph_min_gsi_progress(min_progress:int=0, _connection=None):
    posture_graph_handlers.gsi_min_progress = min_progress

@sims4.commands.Command('interactions.make_pass', command_type=sims4.commands.CommandType.DebugOnly)
def make_pass(enable:bool=None, auto_run=None, _connection=None):
    global _make_pass
    if enable is None:
        enable = not _make_pass
    _make_pass = enable
    interactions.choices.log_to_cheat_console(_make_pass, _connection)
    sims4.commands.output('Make pass mode {}.'.format('enabled' if _make_pass else 'disabled'), _connection)

@sims4.commands.Command('interactions.show_interaction_tuning_name', command_type=sims4.commands.CommandType.DebugOnly)
def show_interaction_tuning_name(enable:bool=None, _connection=None):
    global _show_interaction_tuning_name
    if enable is None:
        enable = not _show_interaction_tuning_name
    _show_interaction_tuning_name = enable

@sims4.commands.Command('interactions.show_failure_reason')
def show_interaction_failure_reason(enable:bool=None, _connection=None):
    toggle_show_interaction_failure_reason(enable=enable)

@sims4.commands.Command('interactions.has_choices', command_type=sims4.commands.CommandType.Live)
def has_choices(target_id:int=None, pick_type=PickType.PICK_TERRAIN, x:float=0.0, y:float=0.0, z:float=0.0, lot_id:int=0, level:int=0, control:int=0, alt:int=0, shift:int=0, reference_id:int=0, _connection=None):
    if target_id is None:
        return
    zone = services.current_zone()
    client = zone.client_manager.get(_connection)
    if client is None:
        return
    sim = _active_sim(client)
    shift_held = bool(shift)
    if shift_held:
        if client.household.cheats_enabled or __debug__:
            _send_interactable_message(client, target_id, True)
        else:
            _send_interactable_message(client, target_id, False)
        return
    context = None
    pick_type = int(pick_type)
    pick_pos = sims4.math.Vector3(x, y, z)
    routing_surface = routing.SurfaceIdentifier(zone.id, level, routing.SURFACETYPE_WORLD)
    target = zone.find_object(target_id)
    if pick_type in PICK_USE_TERRAIN_OBJECT or lot_id and lot_id != services.active_lot().lot_id:
        location = sims4.math.Location(sims4.math.Transform(pick_pos), routing_surface)
        target = objects.terrain.TerrainPoint(location)
    elif pick_type == PickType.PICK_SIM and target is None:
        target = sim
    elif pick_type == PickType.PICK_OBJECT and target is not None and target.object_routing_surface is not None:
        pick_type = int(pick_type)
        routing_surface = target.object_routing_surface
        location = sims4.math.Location(sims4.math.Transform(pick_pos), routing_surface)
        target = objects.terrain.TerrainPoint(location)
    is_interactable = False
    if target is not None:
        pick = PickInfo(pick_type, target, pick_pos, routing_surface, lot_id, bool(alt), bool(control))
        context = client.create_interaction_context(sim, pick=pick)
        for aop in target.potential_interactions(context):
            result = ChoiceMenu.is_valid_aop(aop, context, False, user_pick_target=target)
            if not result and not result.tooltip:
                pass
            is_interactable = aop.affordance.allow_user_directed
            if not is_interactable:
                is_interactable = aop.affordance.has_pie_menu_sub_interactions(aop.target, context, **aop.interaction_parameters)
            while is_interactable:
                break
        if not is_interactable and sim is not None:
            while True:
                for si in sim.si_state:
                    potential_targets = si.get_potential_mixer_targets()
                    while True:
                        for potential_target in potential_targets:
                            if target is potential_target:
                                break
                            while potential_target.is_part and potential_target.part_owner is target:
                                break
                    while autonomy.content_sets.any_content_set_available(sim, si.super_affordance, si, context, potential_targets=(target,), include_failed_aops_with_tooltip=True):
                        is_interactable = True
                        break
    _send_interactable_message(client, target_id, is_interactable, True)

def _send_interactable_message(client, target_id, is_interactable, immediate=False):
    msg = interaction_protocol.Interactable()
    msg.object_id = target_id
    msg.is_interactable = is_interactable
    distributor = Distributor.instance()
    distributor.add_event(Consts_pb2.MSG_OBJECT_IS_INTERACTABLE, msg, immediate)

class PieMenuActions(enum.Int, export=False):
    __qualname__ = 'PieMenuActions'
    SHOW_PIE_MENU = 0
    SHOW_DEBUG_PIE_MENU = 1
    INTERACTION_QUEUE_FULL_TOOLTIP = 2
    INTERACTION_QUEUE_FULL_STR = TunableLocalizedStringFactory(description="\n        Tooltip string shown to the user instead of a pie menu when the Sim's queue\n        is full of interactions.\n        ")
    POSTURE_INCOMPATIBLE_ICON = TunableResourceKey(description='\n        Icon to be displayed when pie menu option is not compatible with\n        current posture of the sim.\n        ', default='PNG:missing_image', resource_types=sims4.resources.CompoundTypes.IMAGE)

def should_generate_pie_menu(client, sim, shift_held):
    can_queue_interactions = sim is None or (sim.queue is None or sim.queue.can_queue_visible_interaction())
    if shift_held:
        if __debug__ or client.household.cheats_enabled:
            return PieMenuActions.SHOW_DEBUG_PIE_MENU
        if can_queue_interactions:
            return PieMenuActions.SHOW_PIE_MENU
        return PieMenuActions.INTERACTION_QUEUE_FULL_TOOLTIP
    else:
        if can_queue_interactions:
            return PieMenuActions.SHOW_PIE_MENU
        return PieMenuActions.INTERACTION_QUEUE_FULL_TOOLTIP

@sims4.commands.Command('interactions.choices', command_type=sims4.commands.CommandType.Live)
def generate_choices(target_id:int=None, pick_type=PickType.PICK_TERRAIN, x:float=0.0, y:float=0.0, z:float=0.0, lot_id:int=0, level:int=0, control:int=0, alt:int=0, shift:int=0, reference_id:int=0, preferred_object_id:int=0, _connection=None):
    if alt or control:
        return 0
    if target_id is None:
        return 0
    zone = services.current_zone()
    client = zone.client_manager.get(_connection)
    sim = _active_sim(client)
    shift_held = bool(shift)
    context = None
    choice_menu = None
    target = None
    preferred_object = None
    if preferred_object_id is not None:
        preferred_object = services.object_manager().get(preferred_object_id)
    preferred_objects = set() if preferred_object is None else {preferred_object}
    pie_menu_action = should_generate_pie_menu(client, sim, shift_held)
    show_pie_menu = pie_menu_action == PieMenuActions.SHOW_PIE_MENU
    show_debug_pie_menu = pie_menu_action == PieMenuActions.SHOW_DEBUG_PIE_MENU
    if show_pie_menu or show_debug_pie_menu:
        if show_pie_menu:
            shift_held = False
        pick_type = int(pick_type)
        pick_pos = sims4.math.Vector3(x, y, z)
        routing_surface = routing.SurfaceIdentifier(zone.id, level, routing.SURFACETYPE_WORLD)
        target = zone.find_object(target_id)
        if pick_type == PickType.PICK_PORTRAIT:
            sim_info = services.sim_info_manager().get(target_id)
            if sim_info is None or sim_info.is_dead:
                return 0
            if sim is None:
                return 0
            picked_item_ids = set([target_id])
            context = client.create_interaction_context(sim, target_sim_id=target_id)
            context.add_preferred_objects(preferred_objects)
            potential_interactions = list(sim.potential_relation_panel_interactions(context, picked_item_ids=picked_item_ids))
            choice_menu = ChoiceMenu(potential_interactions, context, user_pick_target=sim_info)
            client.set_choices(choice_menu)
        elif pick_type == PickType.PICK_SKEWER:
            sim_info = services.sim_info_manager().get(target_id)
            skewer_sim = None
            if sim_info is None or sim_info.is_dead:
                return 0
            skewer_sim = sim_info.get_sim_instance()
            context = client.create_interaction_context(skewer_sim)
            context.add_preferred_objects(preferred_objects)
            potential_interactions = list(sim_info.sim_skewer_affordance_gen(context))
            choice_menu = ChoiceMenu(potential_interactions, context)
            client.set_choices(choice_menu)
        else:
            if pick_type in PICK_USE_TERRAIN_OBJECT or pick_type == PickType.PICK_OBJECT and lot_id and lot_id != services.active_lot().lot_id:
                location = sims4.math.Location(sims4.math.Transform(pick_pos), routing_surface)
                target = objects.terrain.TerrainPoint(location)
                pick_type = PickType.PICK_TERRAIN
            elif pick_type == PickType.PICK_SIM and target is None:
                target = sim
            elif pick_type == PickType.PICK_OBJECT and target.object_routing_surface is not None:
                pick_type = int(pick_type)
                routing_surface = target.object_routing_surface
                location = sims4.math.Location(sims4.math.Transform(pick_pos), routing_surface)
                target = objects.terrain.TerrainPoint(location)
            else:
                preferred_objects.add(target)
            if target is not None:
                pick = PickInfo(pick_type, target, pick_pos, routing_surface, lot_id, bool(alt), bool(control), shift_held)
                context = client.create_interaction_context(sim, pick=pick, shift_held=shift_held)
                context.add_preferred_objects(preferred_objects)
                interaction_parameters = client.get_interaction_parameters()
                potential_interactions = list(target.potential_interactions(context, **interaction_parameters))
                with sims4.callback_utils.invoke_enter_exit_callbacks(sims4.callback_utils.CallbackEvent.CONTENT_SET_GENERATE_ENTER, sims4.callback_utils.CallbackEvent.CONTENT_SET_GENERATE_EXIT):
                    choice_menu = ChoiceMenu(potential_interactions, context, user_pick_target=target, make_pass=_make_pass)
                if not shift_held and sim is not None:
                    for si in sim.si_state:
                        potential_targets = si.get_potential_mixer_targets()
                        while True:
                            for potential_target in potential_targets:
                                if target is potential_target:
                                    break
                                while potential_target.is_part and potential_target.part_owner is target:
                                    break
                        content_set = autonomy.content_sets.generate_content_set(sim, si.super_affordance, si, context, potential_targets=(target,), check_posture_compatibility=True, include_failed_aops_with_tooltip=True)
                        for (_, aop, test_result) in content_set:
                            choice_menu.add_aop(aop, result_override=test_result, do_test=False)
                client.set_choices(choice_menu)
    msg = create_pie_menu_message(sim, context, choice_menu, reference_id, pie_menu_action, target=target)
    distributor = Distributor.instance()
    distributor.add_event(Consts_pb2.MSG_PIE_MENU_CREATE, msg, True)
    num_choices = len(msg.items)
    if num_choices > 0:
        if pick_type in (PickType.PICK_PORTRAIT, PickType.PICK_SIM):
            with telemetry_helper.begin_hook(writer, TELEMETRY_HOOK_CREATE_PIE_MENU, sim=sim) as hook:
                hook.write_int('piid', reference_id)
                hook.write_enum('kind', pick_type)
                hook.write_int('tsim', target_id)
        else:
            with telemetry_helper.begin_hook(writer, TELEMETRY_HOOK_CREATE_PIE_MENU, sim=sim) as hook:
                hook.write_int('piid', reference_id)
                if target is not None and getattr(target, 'definition'):
                    hook.write_guid('tobj', target.definition.id)
                else:
                    hook.write_int('tobj', 0)
                hook.write_enum('kind', pick_type)
    return num_choices

@sims4.commands.Command('interactions.phone_choices', command_type=sims4.commands.CommandType.Live)
def generate_phone_choices(control:int=0, alt:int=0, shift:int=0, reference_id:int=0, _connection=None):
    zone = services.current_zone()
    client = zone.client_manager.get(_connection)
    sim = _active_sim(client)
    if sim is None:
        return 0
    shift_held = bool(shift)
    context = client.create_interaction_context(sim, shift_held=shift_held)
    can_queue_interactions = sim.queue is None or sim.queue.can_queue_visible_interaction()
    if can_queue_interactions:
        pie_menu_action = PieMenuActions.SHOW_PIE_MENU
        choice_menu = ChoiceMenu(sim.potential_phone_interactions(context), context)
        client.set_choices(choice_menu)
    else:
        pie_menu_action = PieMenuActions.INTERACTION_QUEUE_FULL_TOOLTIP
        choice_menu = None
    msg = create_pie_menu_message(sim, context, choice_menu, reference_id, pie_menu_action)
    distributor = Distributor.instance()
    distributor.add_event(Consts_pb2.MSG_PHONE_MENU_CREATE, msg, True)
    with telemetry_helper.begin_hook(writer, TELEMETRY_HOOK_CREATE_PIE_MENU, sim=sim) as hook:
        hook.write_int('piid', reference_id)
        hook.write_string('kind', 'phone')
    return len(msg.items)

def create_pie_menu_message(sim, context, choice_menu, reference_id, pie_menu_action, target=None):
    msg = interaction_protocol.PieMenuCreate()
    msg.sim = sim.id if sim is not None else 0
    msg.client_reference_id = reference_id
    msg.server_reference_id = 0
    if not choice_menu:
        fire_service = services.get_fire_service()
        if fire_service.fire_is_active:
            msg.disabled_tooltip = fire_service.INTERACTION_UNAVAILABLE_DUE_TO_FIRE_TOOLTIP()
            return msg
    if pie_menu_action == PieMenuActions.INTERACTION_QUEUE_FULL_TOOLTIP:
        msg.disabled_tooltip = PieMenuActions.INTERACTION_QUEUE_FULL_STR(sim)
        return msg
    create_tokens(msg.category_tokens, sim, target, None if target is None else target.get_stored_sim_info())
    if choice_menu is not None:
        msg.server_reference_id = choice_menu.revision
        for (option_id, item) in choice_menu:
            with ProtocolBufferRollback(msg.items) as item_msg:
                item_msg.id = item.choice.aop_id
                choice = item.choice
                logger.debug('%3d: %s' % (option_id, choice))
                name = choice.affordance.get_name(choice.target, context, **choice.interaction_parameters)
                (name_override_tunable, name_override_result) = choice.affordance.get_name_override_tunable_and_result(target=choice.target, context=context)
                if _make_pass:
                    name = InteractionCommandsTuning.MAKE_PASS_INTERACTION_NAME(name)
                if _show_interaction_tuning_name:
                    affordance_tuning_name = str(choice.affordance.__name__)
                    name = InteractionCommandsTuning.INTERACTION_TUNING_NAME(name, affordance_tuning_name)
                item_msg.loc_string = name
                tooltip = item.result.tooltip
                if tooltip is not None:
                    tooltip = choice.affordance.create_localized_string(tooltip, context=context, target=choice.target, **choice.interaction_parameters)
                    item_msg.disabled_text = tooltip
                else:
                    success_tooltip = choice.affordance.get_display_tooltip(override=name_override_tunable, context=context, target=choice.target, **choice.interaction_parameters)
                    if success_tooltip is not None:
                        item_msg.success_tooltip = success_tooltip
                pie_menu_icon = choice.affordance.pie_menu_icon
                category_key = item.category_key
                if name_override_tunable.new_pie_menu_icon is not None:
                    pie_menu_icon = name_override_tunable.new_pie_menu_icon
                if name_override_tunable is not None and name_override_tunable.new_pie_menu_category is not None:
                    category_key = name_override_tunable.new_pie_menu_category.guid64
                if pie_menu_icon is not None:
                    item_msg.icon_infos.append(create_icon_info_msg(IconInfoData(icon_resource=pie_menu_icon)))
                if category_key is not None:
                    item_msg.category_key = category_key
                if item.result.icon is not None:
                    item_msg.icon_infos.append(create_icon_info_msg(IconInfoData(icon_resource=item.result.icon)))
                if choice.show_posture_incompatible_icon:
                    item_msg.icon_infos.append(create_icon_info_msg(IconInfoData(icon_resource=PieMenuActions.POSTURE_INCOMPATIBLE_ICON)))
                handle_pie_menu_item_coloring(item_msg, item, sim, choice, name_override_result)
                for visual_target in choice.affordance.visual_targets_gen(choice.target, context, **choice.interaction_parameters):
                    while visual_target is not None:
                        item_msg.target_ids.append(visual_target.id)
                item_msg.score = item.choice.content_score if item.choice.content_score is not None else 0
                item_msg.pie_menu_priority = choice.affordance.pie_menu_priority
    return msg

def handle_pie_menu_item_coloring(item_msg, item, sim, choice, name_override_result):
    mood_result = None
    mood_intensity_result = None
    away_action = choice.interaction_parameters.get('away_action')
    away_action_sim_info = choice.interaction_parameters.get('away_action_sim_info')
    if away_action is not None:
        away_action_sim_current_mood = away_action_sim_info.get_mood()
        if away_action_sim_current_mood in away_action.mood_list:
            mood_result = away_action_sim_current_mood
            mood_intensity_result = away_action_sim_info.get_mood_intensity()
    elif item.result.influence_by_active_mood or name_override_result.influence_by_active_mood:
        mood_result = sim.get_mood()
        mood_intensity_result = sim.get_mood_intensity()
    if mood_result is not None:
        item_msg.mood = mood_result.guid64
        item_msg.mood_intensity = mood_intensity_result

@sims4.commands.Command('interactions.select', command_type=sims4.commands.CommandType.Live)
def select_choice(choice_id, reference_id:int=0, _connection=None):
    client = services.client_manager().get(_connection)
    return client.select_interaction(choice_id, reference_id)

@sims4.commands.Command('interactions.queue')
def display_queue(sim_id:int=None, _connection=None):
    output = Output(_connection)
    if sim_id is None:
        client = services.client_manager().get(_connection)
        sim = _active_sim(client)
    else:
        sim = services.object_manager().get(sim_id)
        if sim is None:
            output('Invalid Sim id {0:08x}'.format(sim_id))
            return False
    output('Super Interaction State: (num = {0})'.format(len(sim.si_state)))
    for si in sim.si_state.sis_actor_gen():
        output(' * {}'.format(str(si)))
        for subi in si.queued_sub_interactions_gen():
            output('    - {}'.format(str(subi)))
    output('Interaction Queue State: (num = {0})'.format(len(sim.queue)))
    for si in sim.queue:
        output(' * {}'.format(str(si)))
    output('Running: %s' % sim.queue.running)

@sims4.commands.Command('qa.interactions.list', command_type=sims4.commands.CommandType.Automation)
def display_queue_automation(sim_id:int=None, _connection=None):
    output = sims4.commands.AutomationOutput(_connection)
    if sim_id is None:
        client = services.client_manager().get(_connection)
        sim = _active_sim(client)
    else:
        sim = services.object_manager().get(sim_id)
    if sim is None:
        output('SimInteractionData; SimId:None')
        return False
    if sim.queue.running is None:
        output('SimInteractionData; SimId:%d, SICount:%d, RunningId:None' % (sim.id, len(sim.si_state)))
    else:
        output('SimInteractionData; SimId:%d, SICount:%d, RunningId:%d, RunningClass:%s' % (sim.id, len(sim.si_state), sim.queue.running.id, sim.queue.running.__class__.__name__))
    for si in sim.si_state.sis_actor_gen():
        output('SimSuperInteractionData; Id:%d, Class:%s' % (si.id, si.__class__.__name__))

@sims4.commands.Command('interactions.reevaluate_head')
def reevaluate_head(sim_id:int=None, _connection=None):
    output = sims4.commands.AutomationOutput(_connection)
    if sim_id is None:
        client = services.client_manager().get(_connection)
        sim = _active_sim(client)
    else:
        sim = services.object_manager().get(sim_id)
    if sim is None:
        output('SimInteractionData; SimId:None')
        return False
    for interaction in sim.queue:
        while interaction.is_super:
            interaction.transition = None
    sim.queue._get_head()

@sims4.commands.Command('qa.interactions.enable_sim_interaction_logging', command_type=sims4.commands.CommandType.Automation)
def enable_sim_interaction_logging(sim_id:int=None, _connection=None):
    output = sims4.commands.AutomationOutput(_connection)
    if sim_id is None:
        client = services.client_manager().get(_connection)
        sim = _active_sim(client)
    else:
        sim = services.object_manager().get(sim_id)
    if sim is None:
        output('SimInteractionToggleOn; SimId:None')
        return False
    sim.interaction_logging = True
    output('[AreaInstanceInteraction] SimInteractionToggleOn; SimId:%d, Logging:%d' % (sim.id, sim.interaction_logging))

@sims4.commands.Command('qa.interactions.disable_sim_interaction_logging', command_type=sims4.commands.CommandType.Automation)
def disable_sim_interaction_logging(sim_id:int=None, _connection=None):
    output = sims4.commands.AutomationOutput(_connection)
    if sim_id is None:
        client = services.client_manager().get(_connection)
        sim = _active_sim(client)
    else:
        sim = services.object_manager().get(sim_id)
    if sim is None:
        output('SimInteractionToggleOff; SimId:None')
        return False
    sim.interaction_logging = False
    output('[AreaInstanceInteraction] SimInteractionToggleOff; SimId:%d, Logging:%d' % (sim.id, sim.interaction_logging))

@sims4.commands.Command('qa.interactions.enable_sim_transition_path_logging', command_type=sims4.commands.CommandType.Automation)
def enable_sim_transition_path_logging(sim_id:int=None, _connection=None):
    output = sims4.commands.AutomationOutput(_connection)
    if sim_id is None:
        client = services.client_manager().get(_connection)
        sim = _active_sim(client)
    else:
        sim = services.object_manager().get(sim_id)
    if sim is None:
        output('SimTransitionPathToggleOn; SimId:None')
        return False
    sim.transition_path_logging = True
    output('[AreaInstanceInteraction] SimTransitionPathToggleOn; SimId:%d, Logging:%d' % (sim.id, sim.interaction_logging))

@sims4.commands.Command('qa.interactions.disable_sim_transition_path_logging', command_type=sims4.commands.CommandType.Automation)
def disable_sim_transition_path_logging(sim_id:int=None, _connection=None):
    output = sims4.commands.AutomationOutput(_connection)
    if sim_id is None:
        client = services.client_manager().get(_connection)
        sim = _active_sim(client)
    else:
        sim = services.object_manager().get(sim_id)
    if sim is None:
        output('SimTransitionPathToggleOff; SimId:None')
        return False
    sim.transition_path_logging = False
    output('[AreaInstanceInteraction] SimTransitionPathToggleOff; SimId:%d, Logging:%d' % (sim.id, sim.interaction_logging))

@sims4.commands.Command('interactions.display_outcomes')
def display_outcomes(sim_id:int=None, _connection=None):
    sim = services.object_manager().get(sim_id)
    client = services.client_manager().get(_connection)
    if not sim:
        sim = _active_sim(client)
    for si in sim.si_state.sis_actor_gen():
        sims4.commands.output('Outcome for {} = {}'.format(si.affordance, si.outcome_result), _connection)

def send_reject_response(client, sim, context_handle, cancel_reason):
    reject_msg = protocols.ServerResponseFailed()
    reject_msg.handle = context_handle
    reject_msg.reason = cancel_reason
    distributor = Distributor.instance()
    distributor.add_op_with_no_owner(GenericProtocolBufferOp(Operation.SIM_SERVER_RESPONSE_FAILED, reject_msg))
    logger.debug('    sending reject msg')

def cancel_common(interaction_id, context_handle:int=None, _connection=None, user_canceled=False):
    client = services.client_manager().get(_connection)
    sim = _active_sim(client)
    interaction = sim.find_interaction_by_id(interaction_id)
    if interaction is None:
        continuation = sim.find_continuation_by_id(interaction_id)
        if continuation is not None:
            continuation.cancel_user(cancel_reason_msg='User canceled the interaction.')
        return True
    if user_canceled == True:
        for grouped_int_info in sim.ui_manager.get_grouped_interaction_gen(interaction_id):
            if interaction_id == grouped_int_info.interaction_id:
                pass
            grouped_interaction = sim.find_interaction_by_id(grouped_int_info.interaction_id)
            while grouped_interaction is not None:
                grouped_interaction.cancel_user(cancel_reason_msg='Command interactions.cancel_si')
        if interaction.cancel_user(cancel_reason_msg='Command interactions.cancel_si'):
            return True
    elif interaction.cancel_user(cancel_reason_msg='Command interactions.cancel_si'):
        return True
    if context_handle is not None:
        send_reject_response(client, sim, context_handle, protocols.ServerResponseFailed.REJECT_CLIENT_CANCEL_SUPERINTERACTION)
    return False

@sims4.commands.Command('interactions.force_inertial', command_type=sims4.commands.CommandType.Automation)
def interaction_force_inertial(opt_target:OptionalTargetParam=None, _connection=None):
    sim = get_optional_target(opt_target, _connection)
    if sim is None:
        return False
    for si in sim.si_state:
        si.force_inertial = True

@sims4.commands.Command('interactions.cancel', command_type=sims4.commands.CommandType.Live)
def cancel_mixer_interaction(interaction_id, mixer_id, server_ref, context_handle:int=None, _connection=None):
    logger.debug('cancel_sub_interaction {0}', interaction_id)
    client = services.client_manager().get(_connection)
    sim = _active_sim(client)
    interaction = sim.find_sub_interaction_by_aop_id(interaction_id, mixer_id)
    if interaction is not None and sim.queue.running != interaction:
        return interaction.cancel_user(cancel_reason_msg='Command interactions.cancel')
    return False

@sims4.commands.Command('interactions.cancel_si', command_type=sims4.commands.CommandType.Live)
def cancel_super_interaction(super_interaction_id, context_handle:int=None, _connection=None):
    logger.debug('cancel_super_interaction {0}', super_interaction_id)
    if __debug__ and _mixer_lock:
        return False
    return cancel_common(super_interaction_id, context_handle, _connection, user_canceled=True)

@sims4.commands.Command('interactions.run_first')
def first_interaction(target_id:int=None, _connection=None):
    target = None
    if target_id is not None:
        target = services.object_manager().get(target_id)
    client = services.client_manager().get(_connection)
    sim = _active_sim(client)
    if target is None:
        target = sim
    context = client.create_interaction_context(sim)
    affordances = list(target.potential_interactions(context))
    if affordances:
        logger.debug('Running affordance: {0}', affordances[0])
        return affordances[0].test_and_execute(context)
    return False

@sims4.commands.Command('interactions.push', command_type=sims4.commands.CommandType.Automation)
def push_interaction(affordance, opt_target:RequiredTargetParam=None, opt_sim:OptionalTargetParam=None, priority=Priority.High, _connection=None):
    target = opt_target.get_target() if opt_target is not None else None
    sim = get_optional_target(opt_sim, _connection)
    client = services.client_manager().get(_connection)
    priority = Priority(priority)
    if not sim.queue.can_queue_visible_interaction():
        sims4.commands.output('Interaction queue is full, cannot add anymore interactions.', _connection)
        return False
    context = InteractionContext(sim, InteractionContext.SOURCE_PIE_MENU, priority, client=client, pick=None)
    result = sim.push_super_affordance(affordance, target, context)
    if not result:
        output = sims4.commands.Output(_connection)
        output('Failed to push: {}'.format(result))
        return False
    return True

@sims4.commands.Command('interactions.push_all_sims')
def push_interaction_on_all_sims(affordance, opt_target:RequiredTargetParam=None, _connection=None):
    target = opt_target.get_target() if opt_target is not None else None
    client = services.client_manager().get(_connection)
    for sim_info in client.selectable_sims:
        sim = sim_info.get_sim_instance()
        while sim is not None:
            context = InteractionContext(sim, InteractionContext.SOURCE_PIE_MENU, Priority.High, client=client, pick=None)
            sim.push_super_affordance(affordance, target, context)
    return True

@sims4.commands.Command('interactions.content_mode')
def set_content_mode(mode=None, _connection=None):
    output = sims4.commands.Output(_connection)
    if mode is None:
        output('No mode specified. Please use one of: {}'.format(', '.join(ContentModes.names)))
        return False
    try:
        valid_mode = ContentModes[mode.upper()]
    except AttributeError:
        output('Invalid mode specified. Please use one of: {}'.format(', '.join(ContentModes.names)))
        return False
    services.config_service().content_mode = valid_mode
    output('Mode set to {}'.format(valid_mode.name))
    return True

@sims4.commands.Command('demo.mixer_lock')
def demo_mixer_lock(enabled=None, _connection=None):
    output = sims4.commands.Output(_connection)
    output('Mixer lock is not supported in optimized python builds.')

class InteractionModes(enum.Int, export=False):
    __qualname__ = 'InteractionModes'
    default = 0
    autonomous = 1

@sims4.commands.Command('interactions.set_interaction_mode')
def set_interaction_mode(mode:InteractionModes=None, source:int=None, priority:interactions.priority.Priority=None, _connection=None):
    output = sims4.commands.Output(_connection)
    client = services.client_manager().get(_connection)
    if client is None:
        return 0
    sources = {}
    for (key, val) in vars(interactions.context.InteractionContext).items():
        while key.startswith('SOURCE'):
            sources[val] = key
    if mode is None and source is None and priority is None:
        output('Source options:')
        for val in sources.values():
            output('    {}'.format(val))
        output('Priority options:')
        for val in interactions.priority.Priority:
            output('    {}'.format(val.name))
    if mode is InteractionModes.default:
        client.interaction_source = None
        client.interaction_priority = None
    elif mode is InteractionModes.autonomous:
        client.interaction_source = interactions.context.InteractionContext.SOURCE_AUTONOMY
        client.interaction_priority = interactions.priority.Priority.Low
    if source is not None:
        client.interaction_source = source
    if priority is not None:
        client.interaction_priority = priority
    source = sources.get(client.interaction_source, client.interaction_source)
    output('Client interaction mode: source={} priority={}'.format(source, client.interaction_priority.name))
    return 1

@sims4.commands.Command('interactions.debug_outcome_style_set', command_type=sims4.commands.CommandType.Automation)
def set_debug_outcome_style(debug_style, mode=None, _connection=None):
    interactions.utils.outcome.debug_outcome_style = _parse_debug_outcome_style(debug_style)

@sims4.commands.Command('interactions.debug_outcome_style_current')
def print_current_debug_outcome_style(mode=None, _connection=None):
    sims4.commands.output(interactions.utils.outcome.debug_outcome_style.__str__(), _connection)

@sims4.commands.Command('interactions.print_content_set')
def print_current_content_set(_connection=None):
    client = services.client_manager().get(_connection)
    if client is None:
        return
    sim = _active_sim(client)
    if sim is None:
        sims4.commands.output('There is no active sim.', _connection)
    else:
        has_printed = False
        context = client.create_interaction_context(sim)
        for si in sim.si_state:
            potential_targets = si.get_potential_mixer_targets()
            content_set = autonomy.content_sets.generate_content_set(sim, si.super_affordance, si, context, potential_targets=potential_targets)
            for (weight, aop, test_result) in content_set:
                affordance_name = aop.affordance.__name__ + ' '
                sims4.commands.output('affordance:{} weight:{} result:{}'.format(affordance_name, weight, test_result), _connection)
                has_printed = True
        if not has_printed:
            sims4.commands.output('Could not find an active content set.', _connection)

def _parse_debug_outcome_style(debug_outcome_style):
    input_lower = debug_outcome_style.lower()
    style = interactions.utils.outcome.DebugOutcomeStyle.NONE
    if input_lower == 'auto_succeed' or input_lower == 'success':
        style = interactions.utils.outcome.DebugOutcomeStyle.AUTO_SUCCEED
    elif input_lower == 'auto_fail' or input_lower == 'fail':
        style = interactions.utils.outcome.DebugOutcomeStyle.AUTO_FAIL
    elif input_lower == 'rotate' or input_lower == 'alternate':
        style = interactions.utils.outcome.DebugOutcomeStyle.ROTATE
    elif input_lower == 'none' or input_lower == 'off':
        style = interactions.utils.outcome.DebugOutcomeStyle.NONE
    return style

@sims4.commands.Command('interactions.lock_content_set', command_type=sims4.commands.CommandType.Automation)
def lock_content_set(*mixer_interactions, _connection=None):
    try:
        autonomy.content_sets.lock_content_sets(mixer_interactions)
    except Exception as e:
        sims4.commands.output('Content set lock failed: {}'.format(e), _connection)

@sims4.commands.Command('interactions.regenerate', command_type=sims4.commands.CommandType.Automation)
def regenerate(_connection=None):
    client = services.client_manager().get(_connection)
    sim = _active_sim(client)
    if sim is not None:
        sims4.commands.output('Regenerate Content set currently disabled.', _connection)

@sims4.commands.Command('interactions.set_social_mixer_tests_enabled')
def toggle_social_tests(enabled:bool=None):
    current = interactions.social.social_mixer_interaction.tunable_tests_enabled
    if enabled is None:
        interactions.social.social_mixer_interaction.tunable_tests_enabled = not current
    else:
        interactions.social.social_mixer_interaction.tunable_tests_enabled = enabled

@sims4.commands.Command('interactions.push_walk_away')
def push_walk_away(sim_id:int=None, _connection=None):
    if sim_id is None:
        client = services.client_manager().get(_connection)
        sim = _active_sim(client)
    else:
        sim = services.object_manager().get(sim_id)
    push_backoff(sim)

@sims4.commands.Command('interactions.toggle_interactions_in_callstack', command_type=sims4.commands.CommandType.Automation)
def toggle_interactions_in_callstack(enabled:bool=None, _connection=None):
    value = postures.transition_sequence.inject_interaction_name_in_callstack
    value = not value
    postures.transition_sequence.inject_interaction_name_in_callstack = value
    sims4.commands.output('Inject interaction names: {}'.format(value), _connection)

