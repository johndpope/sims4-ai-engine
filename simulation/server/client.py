import itertools
import operator
import weakref
from protocolbuffers import Sims_pb2, Consts_pb2
from protocolbuffers.Consts_pb2 import MSG_SIM_SKILL_UPDATE
from protocolbuffers.DistributorOps_pb2 import Operation, SetWhimBucks
from distributor.ops import GenericProtocolBufferOp
from distributor.rollback import ProtocolBufferRollback
from distributor.shared_messages import add_object_message
from distributor.system import Distributor
from objects import ALL_HIDDEN_REASONS, HiddenReasonFlag
from server.live_drag_tuning import LiveDragLocation, LiveDragState, LiveDragTuning
from sims4.callback_utils import CallableList
import distributor.fields
import distributor.ops
import gsi_handlers
import interactions.context
import omega
import services
import sims4.log
import sims4.zone_utils
import telemetry_helper
from objects.object_enums import ResetReason
logger = sims4.log.Logger('Client')
logger_live_drag = sims4.log.Logger('LiveDrag', default_owner='rmccord')
TELEMETRY_GROUP_ACTIVE_SIM = 'ASIM'
TELEMETRY_HOOK_ACTIVE_SIM_CHANGED = 'ASCH'
writer = sims4.telemetry.TelemetryWriter(TELEMETRY_GROUP_ACTIVE_SIM)
MSG_ID_NAMES = {}
for (name, val) in vars(Consts_pb2).items():
    if name.startswith('MSG_'):
        MSG_ID_NAMES[val] = name

def msg_id_name(msg_id):
    if msg_id in MSG_ID_NAMES:
        return MSG_ID_NAMES[msg_id]
    return 'Unknown({})'.format(msg_id)

class Client:
    __qualname__ = 'Client'
    _interaction_source = interactions.context.InteractionContext.SOURCE_PIE_MENU
    _interaction_priority = interactions.priority.Priority.High

    def __init__(self, session_id, account, household_id):
        self.id = session_id
        self.manager = None
        self._account = account
        self._household_id = household_id
        self._choice_menu = None
        self._interaction_parameters = {}
        self.active = True
        self.zone_id = sims4.zone_utils.get_zone_id()
        self._selectable_sims = SelectableSims(self)
        self._active_sim_info = None
        self._active_sim_changed = CallableList()
        self.ui_objects = weakref.WeakSet()
        self.primitives = ()
        self._live_drag_objects = []
        self._live_drag_start_system = LiveDragLocation.INVALID
        self._live_drag_is_stack = False
        self._live_drag_sell_dialog_active = False

    def __repr__(self):
        return '<Client {0:#x}>'.format(self.id)

    @property
    def account(self):
        return self._account

    @distributor.fields.Field(op=distributor.ops.UpdateClientActiveSim)
    def active_sim_info(self):
        return self._active_sim_info

    resend_active_sim_info = active_sim_info.get_resend()

    @active_sim_info.setter
    def active_sim_info(self, sim_info):
        self._set_active_sim_without_field_distribution(sim_info)

    @property
    def active_sim(self):
        if self.active_sim_info is not None:
            return self.active_sim_info.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)

    @active_sim.setter
    def active_sim(self, sim):
        self.active_sim_info = sim.sim_info

    def _set_active_sim_without_field_distribution(self, sim_info):
        if self._active_sim_info is not None and self._active_sim_info is sim_info:
            return
        current_sim = self._active_sim_info.get_sim_instance() if self._active_sim_info is not None else None
        new_sim = sim_info.get_sim_instance() if sim_info is not None else None
        if sim_info is not None:
            self._active_sim_info = sim_info
            sim_info.household.on_active_sim_changed(sim_info)
        else:
            self._active_sim_info = None
        self.notify_active_sim_changed(current_sim, new_sim)

    @property
    def choice_menu(self):
        return self._choice_menu

    @property
    def interaction_source(self):
        return self._interaction_source

    @interaction_source.setter
    def interaction_source(self, value):
        if value is None:
            del self._interaction_source
        else:
            self._interaction_source = value

    @property
    def interaction_priority(self):
        return self._interaction_priority

    @interaction_priority.setter
    def interaction_priority(self, value):
        if value is None:
            del self._interaction_priority
        else:
            self._interaction_priority = value

    @property
    def household_id(self):
        return self._household_id

    @property
    def household(self):
        household_manager = services.household_manager()
        if household_manager is not None:
            return household_manager.get(self._household_id)

    @property
    def selectable_sims(self):
        return self._selectable_sims

    def create_interaction_context(self, sim, **kwargs):
        context = interactions.context.InteractionContext(sim, self.interaction_source, self.interaction_priority, client=self, **kwargs)
        return context

    @property
    def live_drag_objects(self):
        return self._live_drag_objects

    def get_interaction_parameters(self):
        return self._interaction_parameters

    def set_interaction_parameters(self, **kwargs):
        self._interaction_parameters = kwargs

    def set_choices(self, new_choices):
        self._choice_menu = new_choices

    def select_interaction(self, choice_id, revision):
        if self.choice_menu is not None and revision == self.choice_menu.revision:
            choice_menu = self.choice_menu
            self._choice_menu = None
            self.set_interaction_parameters()
            try:
                return choice_menu.select(choice_id)
            except:
                if choice_menu.context.sim is not None:
                    choice_menu.context.sim.reset(ResetReason.RESET_ON_ERROR, cause='Exception while selecting interaction from the pie menu.')
                raise

    def get_create_op(self, *args, **kwargs):
        return distributor.ops.ClientCreate(self, is_active=True, *args, **kwargs)

    def get_delete_op(self):
        return distributor.ops.ClientDelete()

    def get_create_after_objs(self):
        active = self.active_sim
        if active is not None:
            yield active
        household = self.household
        if household is not None:
            yield household

    @property
    def valid_for_distribution(self):
        return True

    def refresh_achievement_data(self):
        active_sim_info = None
        if self.active_sim is not None:
            active_sim_info = self.active_sim.sim_info
        self.account.achievement_tracker.refresh_progress(active_sim_info)

    def send_message(self, msg_id, msg):
        if self.active:
            omega.send(self.id, msg_id, msg.SerializeToString())
        else:
            logger.warn('Message sent to client {} after it has already disconnected.', self)

    def send_serialized_message(self, msg_id, msg):
        if self.active:
            omega.send(self.id, msg_id, msg)
        else:
            logger.warn('Serialized message sent to client {} after it has already disconnected.', self)

    def set_next_sim(self):
        sim_info = self._selectable_sims.get_next_selectable(self._active_sim_info)
        if sim_info is self.active_sim_info:
            return False
        return self.set_active_sim_info(sim_info)

    def set_next_sim_or_none(self, only_if_this_active_sim_info=None):
        if only_if_this_active_sim_info is not None and self._active_sim_info is not only_if_this_active_sim_info:
            return
        sim_info = self._selectable_sims.get_next_selectable(self._active_sim_info)
        if sim_info is None:
            return self.set_active_sim_info(None)
        if sim_info is self._active_sim_info:
            return self.set_active_sim_info(None)
        return self.set_active_sim_info(sim_info)

    def set_active_sim_by_id(self, sim_id):
        if self.active_sim_info is not None and self.active_sim_info.id == sim_id:
            return False
        for sim_info in self._selectable_sims:
            while sim_info.sim_id == sim_id:
                if not sim_info.is_enabled_in_skewer:
                    return False
                return self.set_active_sim_info(sim_info)
        return False

    def set_active_sim(self, sim):
        return self.set_active_sim_info(sim.sim_info)

    def set_active_sim_info(self, sim_info):
        with telemetry_helper.begin_hook(writer, TELEMETRY_HOOK_ACTIVE_SIM_CHANGED, sim=sim_info):
            pass
        self.active_sim_info = sim_info
        return self._active_sim_info is not None

    def add_selectable_sim_info(self, sim_info, send_relationship_update=True):
        self._selectable_sims.add_selectable_sim_info(sim_info, send_relationship_update=send_relationship_update)
        if self.active_sim_info is None:
            self.set_next_sim()
        self.household.refresh_aging_updates(sim_info)

    def add_selectable_sim_by_id(self, sim_id):
        sim_info = services.sim_info_manager().get(sim_id)
        if sim_info is not None:
            self.add_selectable_sim_info(sim_info)

    def remove_selectable_sim_info(self, sim_info):
        self._selectable_sims.remove_selectable_sim_info(sim_info)
        if self.active_sim_info is None:
            self.set_next_sim()
        self.household.refresh_aging_updates(sim_info)

    def remove_selectable_sim_by_id(self, sim_id):
        if len(self._selectable_sims) <= 1:
            return False
        sim_info = services.sim_info_manager().get(sim_id)
        if sim_info is not None:
            self.remove_selectable_sim_info(sim_info)
        return True

    def make_all_sims_selectable(self):
        self.clear_selectable_sims()
        for sim_info in services.sim_info_manager().objects:
            self._selectable_sims.add_selectable_sim_info(sim_info)
        self.set_next_sim()

    def clear_selectable_sims(self):
        self.active_sim_info = None
        self._selectable_sims.clear_selectable_sims()

    def register_active_sim_changed(self, callback):
        if callback not in self._active_sim_changed:
            self._active_sim_changed.append(callback)

    def unregister_active_sim_changed(self, callback):
        if callback in self._active_sim_changed:
            self._active_sim_changed.remove(callback)

    def on_sim_added_to_skewer(self, sim_info, send_relationship_update=True):
        if send_relationship_update:
            sim_info.relationship_tracker.send_relationship_info()
        sim_info.relationship_tracker.enable_selectable_sim_track_decay()
        sim_info.on_sim_added_to_skewer()
        sim_info.commodity_tracker.send_commodity_progress_update()
        sim_info.career_tracker.on_sim_added_to_skewer()
        sim_info.send_whim_bucks_update(SetWhimBucks.LOAD)
        sim = sim_info.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)
        if sim is not None:
            sim.ui_manager.refresh_ui_data()
            services.autonomy_service().logging_sims.add(sim)
            sim.family_funds.empty_sim_personal_funds(sim)
            sim_info.aspiration_tracker.force_send_data_update()
            sim_info.aspiration_tracker.initialize_aspiration()
            sim_info.aspiration_tracker.set_update_alarm()
            sim_info.career_tracker.activate_career_aspirations()

    def on_sim_removed_from_skewer(self, sim_info, update_relationship_tracker=True):
        if update_relationship_tracker:
            if sim_info.is_child and sim_info.is_dead:
                sim_info.relationship_tracker.destroy_all_relationships()
            else:
                sim_info.relationship_tracker.enable_selectable_sim_track_decay(False)
        sim_info.aspiration_tracker.clear_update_alarm()
        sim = sim_info.get_sim_instance()
        if sim is not None:
            autonomy_service = services.autonomy_service()
            if autonomy_service is not None:
                autonomy_service.logging_sims.discard(sim)

    def clean_and_send_remaining_relationship_info(self):
        for sim_info in self.selectable_sims:
            sim_info.relationship_tracker.clean_and_send_remaining_relationship_info()

    def cancel_live_drag_on_objects(self):
        for obj in self._live_drag_objects:
            obj.live_drag_component.cancel_live_dragging()
        self._live_drag_objects = []

    def _get_stack_items_from_drag_object(self, drag_object, remove=False, is_stack=False):
        if drag_object.inventoryitem_component is None:
            return (False, None)
        previous_inventory = drag_object.inventoryitem_component.get_inventory()
        if previous_inventory is None:
            return (False, None)
        stack_id = drag_object.inventoryitem_component.get_stack_id()
        if remove:
            success = previous_inventory.try_remove_object_by_id(drag_object.id, force_remove_stack=is_stack)
        else:
            success = True
        stack_items = previous_inventory.get_stack_items(stack_id)
        return (success, stack_items)

    def remove_drag_object_and_get_next_item(self, drag_object):
        next_object_id = None
        (success, stack_items) = self._get_stack_items_from_drag_object(drag_object, remove=True)
        if success and stack_items:
            next_object_id = stack_items[0].id
        return (success, next_object_id)

    def get_live_drag_object_value(self, drag_object, is_stack=False):
        (_, stack_items) = self._get_stack_items_from_drag_object(drag_object, remove=False, is_stack=is_stack)
        value = 0
        if is_stack and stack_items:
            for item in stack_items:
                value += item.current_value*item.stack_count()
        else:
            value = drag_object.current_value
        return value

    def start_live_drag(self, live_drag_object, start_system, is_stack):
        self._live_drag_start_system = start_system
        success = True
        if is_stack:
            inventoryitem_component = live_drag_object.inventoryitem_component
            stack_id = inventoryitem_component.get_stack_id()
            current_inventory = inventoryitem_component.get_inventory()
            stack_items = current_inventory.get_stack_items(stack_id)
        else:
            stack_items = [live_drag_object]
        for item in stack_items:
            live_drag_component = live_drag_object.live_drag_component
            live_drag_component = item.live_drag_component
            if live_drag_component is None:
                logger_live_drag.error('Live Drag Start called on an object with no Live Drag Component. Object: {}'.format(item))
                self.send_live_drag_cancel(live_drag_object.id)
                return
            if item.in_use and not item.in_use_by(self) or not live_drag_component.can_live_drag:
                logger_live_drag.warn('Live Drag Start called on an object that is in use. Object: {}'.format(item))
                self.send_live_drag_cancel(item.id)
                return
            success = live_drag_component.start_live_dragging(self, start_system)
            if not success:
                break
            self._live_drag_objects.append(item)
        if not success:
            self.cancel_live_drag_on_objects()
            self.send_live_drag_cancel(live_drag_object.id, LiveDragLocation.INVALID)
        self._live_drag_is_stack = is_stack
        if gsi_handlers.live_drag_handlers.live_drag_archiver.enabled:
            gsi_handlers.live_drag_handlers.archive_live_drag('Start', 'Operation', LiveDragLocation.GAMEPLAY_SCRIPT, start_system, live_drag_object_id=live_drag_object.id)
        if live_drag_object.live_drag_component.active_household_has_sell_permission:
            sell_value = self.get_live_drag_object_value(live_drag_object, self._live_drag_is_stack) if live_drag_object.definition.get_is_deletable() else -1
        else:
            sell_value = -1
        (valid_drop_object_ids, valid_stack_id) = live_drag_component.get_valid_drop_object_ids()
        op = distributor.ops.LiveDragStart(live_drag_object.id, start_system, valid_drop_object_ids, valid_stack_id, sell_value)
        distributor_system = Distributor.instance()
        distributor_system.add_op_with_no_owner(op)

    def end_live_drag(self, source_object, target_object=None, end_system=LiveDragLocation.INVALID, location=None):
        live_drag_component = source_object.live_drag_component
        if live_drag_component is None:
            logger_live_drag.error('Live Drag End called on an object with no Live Drag Component. Object: {}'.format(source_object))
            self.send_live_drag_cancel(source_object.id, end_system)
            return
        if source_object not in self._live_drag_objects:
            logger_live_drag.warn('Live Drag End called on an object not being Live Dragged. Object: {}'.format(source_object))
            self.send_live_drag_cancel(source_object.id, end_system)
            return
        source_object_id = source_object.id
        self.cancel_live_drag_on_objects()
        next_object_id = None
        success = False
        if target_object is not None:
            live_drag_target_component = target_object.live_drag_target_component
            if live_drag_target_component is not None:
                (success, next_object_id) = live_drag_target_component.drop_live_drag_object(source_object, self._live_drag_is_stack)
            else:
                logger_live_drag.error('Live Drag Target Component missing on object: {} is now required on all drop targets.'.format(target_object))
                success = False
        else:
            success = True
            if location is not None:
                source_object.set_location(location)
            inventory_item = source_object.inventoryitem_component
            if inventory_item is not None and inventory_item.is_in_inventory():
                (success, next_object_id) = self.remove_drag_object_and_get_next_item(source_object)
        if success:
            if gsi_handlers.live_drag_handlers.live_drag_archiver.enabled:
                gsi_handlers.live_drag_handlers.archive_live_drag('End', 'Operation', LiveDragLocation.GAMEPLAY_SCRIPT, end_system, live_drag_object_id=source_object_id, live_drag_target=target_object)
            if not self._live_drag_is_stack:
                next_object_id = None
            op = distributor.ops.LiveDragEnd(source_object_id, self._live_drag_start_system, end_system, next_object_id)
            distributor_system = Distributor.instance()
            distributor_system.add_op_with_no_owner(op)
            self._live_drag_objects = []
            self._live_drag_start_system = LiveDragLocation.INVALID
            self._live_drag_is_stack = False
        else:
            self.send_live_drag_cancel(source_object_id, end_system)

    def cancel_live_drag(self, live_drag_object, end_system=LiveDragLocation.INVALID):
        live_drag_component = live_drag_object.live_drag_component
        if live_drag_component is None:
            logger_live_drag.warn('Live Drag Cancel called on an object with no Live Drag Component. Object: {}'.format(live_drag_object))
            self.send_live_drag_cancel(live_drag_object.id)
            return
        if live_drag_component.live_drag_state == LiveDragState.NOT_LIVE_DRAGGING:
            logger_live_drag.warn('Live Drag Cancel called on an object not being Live Dragged. Object: {}'.format(live_drag_object))
        else:
            self.cancel_live_drag_on_objects()
        self.send_live_drag_cancel(live_drag_object.id, end_system)

    def sell_live_drag_object(self, live_drag_object, end_system=LiveDragLocation.INVALID):
        live_drag_component = live_drag_object.live_drag_component
        if live_drag_component is None or not live_drag_object.definition.get_is_deletable():
            logger_live_drag.error("Live Drag Sell called on object with no Live Drag Component or can't be deleted. Object: {}".format(live_drag_object))
            self.send_live_drag_cancel(live_drag_object.id, end_system)
            return

        def sell_response(dialog):
            if not dialog.accepted:
                return
            value = int(self.get_live_drag_object_value(live_drag_object, self._live_drag_is_stack))
            live_drag_component.cancel_live_dragging(should_reset=False)
            object_tags = set()
            if self._live_drag_is_stack:
                (_, stack_items) = self._get_stack_items_from_drag_object(live_drag_object, remove=True, is_stack=True)
                for item in stack_items:
                    item.current_value = 0
                    item.set_stack_count(0)
                    object_tags.update(item.get_tags())
                    item.destroy(source=item, cause='Selling stack of live drag objects.')
            else:
                object_tags.update(live_drag_object.get_tags())
                if live_drag_object.is_in_inventory():
                    self.remove_drag_object_and_get_next_item(live_drag_object)
                else:
                    live_drag_object.remove_from_client()
            object_tags = frozenset(object_tags)
            live_drag_object.current_value = 0
            live_drag_object.destroy(source=live_drag_object, cause='Selling live drag object.')
            services.active_household().funds.add(value, Consts_pb2.TELEMETRY_OBJECT_SELL, self.active_sim, tags=object_tags)
            self._live_drag_objects = []
            self._live_drag_start_system = LiveDragLocation.INVALID
            self._live_drag_is_stack = False
            self._live_drag_sell_dialog_active = False

        if self._live_drag_is_stack:
            dialog = LiveDragTuning.LIVE_DRAG_SELL_STACK_DIALOG(owner=live_drag_object)
        else:
            dialog = LiveDragTuning.LIVE_DRAG_SELL_DIALOG(owner=live_drag_object)
        dialog.show_dialog(on_response=sell_response)
        self._live_drag_sell_dialog_active = True

    def send_live_drag_cancel(self, live_drag_object_id, live_drag_end_system=LiveDragLocation.INVALID):
        if gsi_handlers.live_drag_handlers.live_drag_archiver.enabled:
            gsi_handlers.live_drag_handlers.archive_live_drag('Cancel', 'Operation', LiveDragLocation.GAMEPLAY_SCRIPT, live_drag_end_system, live_drag_object_id=live_drag_object_id)
        op = distributor.ops.LiveDragCancel(live_drag_object_id, self._live_drag_start_system, live_drag_end_system)
        distributor_system = Distributor.instance()
        distributor_system.add_op_with_no_owner(op)
        if not self._live_drag_sell_dialog_active:
            self._live_drag_objects = []
            self._live_drag_start_system = LiveDragLocation.INVALID
            self._live_drag_is_stack = False

    def on_add(self):
        if self._account is not None:
            self._account.register_client(self)
        for sim_info in self._selectable_sims:
            self.on_sim_added_to_skewer(sim_info)
        distributor = Distributor.instance()
        distributor.add_object(self)
        distributor.add_client(self)
        self.send_selectable_sims_update()
        self.selectable_sims.add_watcher(self, self.send_selectable_sims_update)

    def on_remove(self):
        if self.active_sim is not None:
            self._set_active_sim_without_field_distribution(None)
        if self._account is not None:
            self._account.unregister_client(self)
        for sim_info in self._selectable_sims:
            self.on_sim_removed_from_skewer(sim_info, update_relationship_tracker=False)
        self.selectable_sims.remove_watcher(self)
        distributor = Distributor.instance()
        distributor.remove_client(self)
        self._selectable_sims = None
        self.active = False

    def get_objects_in_view_gen(self):
        for manager in services.client_object_managers():
            for obj in manager.get_all():
                yield obj

    def notify_active_sim_changed(self, old_sim, new_sim):
        self._active_sim_changed(old_sim, new_sim)

    def _get_selector_visual_type(self, sim_info):
        if sim_info.is_baby:
            return (Sims_pb2.SimPB.BABY, None)
        for career in sim_info.career_tracker.careers.values():
            if career.currently_at_work:
                return (Sims_pb2.SimPB.AT_WORK, career.career_category)
            while career.is_late:
                return (Sims_pb2.SimPB.LATE_FOR_WORK, career.career_category)
        sim = sim_info.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)
        if sim is not None and sim.has_hidden_flags(HiddenReasonFlag.RABBIT_HOLE):
            return (Sims_pb2.SimPB.OTHER, None)
        return (Sims_pb2.SimPB.NORMAL, None)

    def send_selectable_sims_update(self):
        msg = Sims_pb2.UpdateSelectableSims()
        for sim_info in self._selectable_sims:
            with ProtocolBufferRollback(msg.sims) as new_sim:
                new_sim.id = sim_info.sim_id
                new_sim.at_work = sim_info.career_tracker.currently_at_work
                new_sim.is_selectable = sim_info.is_enabled_in_skewer
                (selector_visual_type, career_category) = self._get_selector_visual_type(sim_info)
                new_sim.selector_visual_type = selector_visual_type
                if career_category is not None:
                    new_sim.career_category = career_category
                while not sim_info.is_instanced(allow_hidden_flags=ALL_HIDDEN_REASONS):
                    new_sim.instance_info.zone_id = sim_info.zone_id
                    new_sim.instance_info.world_id = sim_info.world_id
                    new_sim.firstname = sim_info.first_name
                    new_sim.lastname = sim_info.last_name
                    zone_data_proto = services.get_persistence_service().get_zone_proto_buff(sim_info.zone_id)
                    while zone_data_proto is not None:
                        new_sim.instance_info.zone_name = zone_data_proto.name
        distributor = Distributor.instance()
        distributor.add_op_with_no_owner(GenericProtocolBufferOp(Operation.SELECTABLE_SIMS_UPDATE, msg))

    @property
    def is_sim(self):
        return False

class SelectableSims:
    __qualname__ = 'SelectableSims'

    def __init__(self, client):
        self._selectable_sim_infos = []
        self.client = client
        self._watchers = {}

    def __iter__(self):
        return iter(sorted(self._selectable_sim_infos, key=operator.attrgetter('age', 'age_progress'), reverse=True))

    def __contains__(self, sim_info):
        return sim_info in self._selectable_sim_infos

    def __bool__(self):
        if self._selectable_sim_infos:
            return True
        return False

    def __len__(self):
        return len(self._selectable_sim_infos)

    def add_selectable_sim_info(self, sim_info, send_relationship_update=True):
        if sim_info not in self._selectable_sim_infos:
            self._selectable_sim_infos.append(sim_info)
            self.client.on_sim_added_to_skewer(sim_info, send_relationship_update=send_relationship_update)
            self.notify_dirty()

    def remove_selectable_sim_info(self, sim_info):
        exists = sim_info in self._selectable_sim_infos
        if exists:
            self._selectable_sim_infos.remove(sim_info)
            self.client.on_sim_removed_from_skewer(sim_info)
            self.notify_dirty()

    def get_next_selectable(self, current_selected_sim_info):
        if not any(s.is_enabled_in_skewer for s in self):
            return
        if current_selected_sim_info is not None and (current_selected_sim_info not in self._selectable_sim_infos or not current_selected_sim_info.is_enabled_in_skewer):
            current_selected_sim_info = None
        iterator = filter(operator.attrgetter('is_enabled_in_skewer'), itertools.cycle(self))
        for sim_info in iterator:
            while current_selected_sim_info is None or sim_info is current_selected_sim_info:
                return next(iterator)

    def clear_selectable_sims(self):
        removed_list = list(self._selectable_sim_infos)
        self._selectable_sim_infos = []
        for sim_info in removed_list:
            self.client.on_sim_removed_from_skewer(sim_info)
        self.notify_dirty()

    def add_watcher(self, handle, f):
        self._watchers[handle] = f
        return handle

    def remove_watcher(self, handle):
        return self._watchers.pop(handle)

    def notify_dirty(self):
        for watcher in self._watchers.values():
            watcher()

