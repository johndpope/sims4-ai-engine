from objects.components.types import NativeComponent, LIVE_DRAG_COMPONENT
from objects.object_enums import ResetReason
from server.live_drag_tuning import LiveDragState, LiveDragLocation
from sims4.tuning.tunable import HasTunableFactory
import distributor.fields
import distributor.ops
import gsi_handlers
import services
import sims4.log
logger = sims4.log.Logger('LiveDragComponent', default_owner='rmccord')

class LiveDragComponent(NativeComponent, HasTunableFactory, component_name=LIVE_DRAG_COMPONENT, key=2125782609):
    __qualname__ = 'LiveDragComponent'
    FACTORY_TUNABLES = {}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._can_live_drag = True
        self._live_drag_user = None
        self._start_system = LiveDragLocation.INVALID
        self._live_drag_state = LiveDragState.NOT_LIVE_DRAGGING
        self._household_permission = True

    @property
    def live_drag_state(self):
        return self._live_drag_state

    @distributor.fields.ComponentField(op=distributor.ops.SetCanLiveDrag, default=None)
    def can_live_drag(self):
        return self._can_live_drag

    @property
    def active_household_has_sell_permission(self):
        owning_household_id = self.owner.get_household_owner_id()
        active_household_id = services.active_household_id()
        return owning_household_id == active_household_id

    def set_can_live_drag(self, can_drag):
        if self.can_live_drag == can_drag:
            return
        self._can_live_drag = can_drag
        self._resend_live_draggable()
        self.log_can_live_drag()
        inventoryitem_component = self.owner.inventoryitem_component
        if inventoryitem_component is not None:
            inventory = inventoryitem_component.get_inventory()
            if inventory is not None:
                inventory.push_inventory_item_update_msg(self.owner)

    _resend_live_draggable = can_live_drag.get_resend()

    def component_reset(self, reset_reason):
        if self.live_drag_state == LiveDragState.NOT_LIVE_DRAGGING:
            return
        if reset_reason == ResetReason.BEING_DESTROYED:
            self._live_drag_user.cancel_live_drag(self.owner, LiveDragLocation.GAMEPLAY_SCRIPT)

    def on_add(self):
        self.owner.register_on_use_list_changed(self._on_owner_in_use_list_changed)

    def on_remove(self):
        self.owner.unregister_on_use_list_changed(self._on_owner_in_use_list_changed)

    def set_active_household_live_drag_permission(self):
        owning_household_id = self.owner.get_household_owner_id()
        active_household_id = services.active_household_id()
        if active_household_id is not None and owning_household_id is not None and owning_household_id != active_household_id:
            self._household_permission = False
        else:
            self._household_permission = True
        if self.can_live_drag and not self._household_permission:
            self.set_can_live_drag(False)
        return self._household_permission

    def on_post_load(self):
        self.set_active_household_live_drag_permission()

    def log_can_live_drag(self):
        if gsi_handlers.live_drag_handlers.live_drag_archiver.enabled:
            gsi_handlers.live_drag_handlers.archive_live_drag('Can Live Drag', 'Operation', LiveDragLocation.GAMEPLAY_SCRIPT, 'Client', live_drag_object=self.owner, live_drag_object_id=self.owner.id)

    def _on_owner_in_use_list_changed(self, user, added):
        if self.can_live_drag and added and user is not self._live_drag_user:
            self.set_can_live_drag(False)
            if self._live_drag_state == LiveDragState.LIVE_DRAGGING:
                self._live_drag_user.send_live_drag_cancel(self.owner.id, live_drag_end_system=LiveDragLocation.GAMEPLAY_SCRIPT)
        elif not self.can_live_drag and (not added and not any(user is not self._live_drag_user for user in self.owner.get_users())) and self._household_permission:
            self.set_can_live_drag(True)

    def is_valid_drop_target(self, test_obj):
        owning_household_id = self.owner.get_household_owner_id()
        if test_obj.is_sim and owning_household_id is not None and owning_household_id != test_obj.household_id:
            return False
        if test_obj.live_drag_target_component is not None:
            return test_obj.live_drag_target_component.can_add(self.owner)
        if test_obj.inventory_component is not None:
            return test_obj.inventory_component.can_add(self.owner)
        return False

    def get_valid_drop_object_ids(self):
        drop_target_ids = []
        for test_obj in services.object_manager().values():
            while not test_obj.is_hidden() and self.is_valid_drop_target(test_obj):
                drop_target_ids.append(test_obj.id)
        if self.owner.inventoryitem_component is not None:
            return (drop_target_ids, self.owner.inventoryitem_component.get_stack_id())
        return (drop_target_ids, None)

    def start_live_dragging(self, reserver, start_system):
        if self.owner.in_use:
            return False
        self._live_drag_user = reserver
        self.owner.reserve(reserver, self)
        self._live_drag_state = LiveDragState.LIVE_DRAGGING
        return True

    def cancel_live_dragging(self, should_reset=True):
        if self._live_drag_user is not None and self.owner.in_use_by(self._live_drag_user):
            self.owner.release(self._live_drag_user, self)
        if should_reset:
            self.owner.reset(ResetReason.RESET_EXPECTED, self, 'cancel live drag.')
        self._live_drag_user = None
        self._live_drag_state = LiveDragState.NOT_LIVE_DRAGGING

