from collections import defaultdict
from objects.components import componentmethod
from objects.components.types import NativeComponent, FOOTPRINT_COMPONENT
from element_utils import build_critical_section_with_finally
from sims4.tuning.tunable import TunableFactory, TunableList, TunableTuple, Tunable, TunableStringHash
import distributor.fields
import distributor.ops
import placement
import routing
import sims4.log
logger = sims4.log.Logger(FOOTPRINT_COMPONENT.class_attr)

class HasFootprintComponent:
    __qualname__ = 'HasFootprintComponent'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._routing_context = None
        self._raycast_context = None

    @property
    def footprint(self):
        footprint_component = self.get_component(FOOTPRINT_COMPONENT)
        if footprint_component is not None:
            return footprint_component.footprint

    @property
    def footprint_polygon(self):
        if self.footprint is None or self.routing_surface is None:
            return
        return placement.get_placement_footprint_polygon(self.position, self.orientation, self.routing_surface, self.footprint)

    @property
    def routing_context(self):
        return self._routing_context

    def _create_routing_context(self):
        self._routing_context = routing.RoutingContext()
        footprint_key = self.footprint
        self._routing_context.footprint_key = footprint_key
        if footprint_key is not None:
            self._routing_context.object_radius = max(self.footprint_polygon.radius(), 0.001)
            self._routing_context.ignore_own_footprint = True

    def get_or_create_routing_context(self):
        if self._routing_context is None:
            self._create_routing_context()
        return self._routing_context

    def get_raycast_root(self):
        if self.parent is None:
            return self
        raycast_parent = self
        while raycast_parent.parent is not None:
            if raycast_parent.parent.footprint_polygon is not None and not raycast_parent.parent.footprint_polygon.contains(self.position):
                return raycast_parent
            raycast_parent = raycast_parent.parent
        return raycast_parent

    def raycast_context(self, for_carryable=False):
        root = self.get_raycast_root()
        if for_carryable:
            current_context = root._raycast_context
            try:
                root._create_raycast_context(for_carryable=for_carryable)
                carryable_context = root._raycast_context
            finally:
                root._raycast_context = current_context
            return carryable_context
        if root._raycast_context is None:
            root._create_raycast_context()
        return root._raycast_context

    def _create_raycast_context(self, for_carryable=False):
        from sims.sim_info import SimInfo
        self._raycast_context = routing.PathPlanContext()
        self._raycast_context.footprint_key = SimInfo.SIM_DEFINITION.get_footprint(0)
        self._raycast_context.agent_id = self.id
        self._raycast_context.agent_radius = routing.get_default_agent_radius()
        self._raycast_context.set_key_mask(routing.FOOTPRINT_KEY_ON_LOT | routing.FOOTPRINT_KEY_OFF_LOT)
        if self.is_sim:
            return
        if self.routing_context is not None:
            self_footprint_id = self.routing_context.object_footprint_id
            if self_footprint_id is not None:
                self._raycast_context.ignore_footprint_contour(self_footprint_id)
        for obj in self.children_recursive_gen(include_self=True):
            if obj is not self:
                obj._raycast_context = None
            if obj.is_sim:
                pass
            routing_context = obj.routing_context
            if routing_context is None and obj.is_part:
                routing_context = obj.part_owner.routing_context
            if routing_context is None:
                pass
            if not for_carryable and self.footprint_polygon is not None and not self.footprint_polygon.contains(obj.position):
                pass
            override_id = routing_context.object_footprint_id
            while override_id is not None:
                self._raycast_context.ignore_footprint_contour(override_id)

    def clear_raycast_context(self):
        root = self.get_raycast_root()
        root._raycast_context = None

class FootprintComponent(NativeComponent, component_name=FOOTPRINT_COMPONENT, key=3355914538):
    __qualname__ = 'FootprintComponent'
    _footprint = None
    _footprints_enabled = False
    _placement_footprint_added = False
    _footprint_tracker = None
    _TOGGLE_COUNT_INDEX = 0
    _ENABLED_COUNT_INDEX = 1
    _DISABLED_COUNT_INDEX = 2
    _enabled_dict = None

    @distributor.fields.ComponentField(op=distributor.ops.SetFootprint, priority=distributor.fields.Field.Priority.HIGH)
    def footprint(self):
        return self._footprint

    @distributor.fields.ComponentField(op=distributor.ops.UpdateFootprintStatus)
    def footprint_and_status(self):
        return (self._footprint, self._footprints_enabled)

    _resend_footprint = footprint.get_resend()
    _resend_footprint_status = footprint_and_status.get_resend()

    @componentmethod
    def get_footprint(self):
        return self.footprint

    @property
    def footprints_enabled(self):
        return self._footprints_enabled

    @footprints_enabled.setter
    def footprints_enabled(self, value):
        self._footprints_enabled = value

    def apply_definition(self, definition, obj_state=0):
        value = definition.get_footprint(obj_state)
        reenable = False
        if self.footprints_enabled:
            self.disable_footprint()
            reenable = True
        self._footprint = value
        routing_context = self.owner.routing_context
        if routing_context is not None:
            routing_context.footprint_key = value
        self._resend_footprint()
        if reenable:
            self.enable_footprint()

    def on_add(self, *_, **__):
        self.footprints_enabled = True

    def on_location_changed(self, *_, **__):
        if self.owner.id:
            self.update_footprint()

    def on_parent_change(self, parent):
        if parent is not None and parent._disable_child_footprint_and_shadow:
            self.disable_footprint()
            return
        self.enable_footprint()

    def on_remove(self, *_, **__):
        self.disable_footprint(from_remove=True)

    def on_added_to_inventory(self):
        self.disable_footprint()

    def on_removed_from_inventory(self):
        self.enable_footprint()

    @property
    def _footprints_should_be_enabled(self):
        if not self.footprints_enabled:
            return False
        if self.owner.parent is not None and self.owner.parent._disable_child_footprint_and_shadow:
            return False
        if self.owner.routing_surface is None:
            return False
        return True

    def enable_footprint(self, from_remove=False):
        self.footprints_enabled = True
        self.update_footprint(from_remove=from_remove)

    def disable_footprint(self, from_remove=False):
        self.footprints_enabled = False
        self.update_footprint(from_remove=from_remove)

    def update_footprint(self, from_remove=False):
        if self._footprints_should_be_enabled:
            routing_context = self.owner.routing_context
            if routing_context is not None and routing_context.object_footprint_id is not None:
                routing.invalidate_footprint(routing_context.object_footprint_id, self._enabled_dict)
                routing_context.connectivity_groups_need_rebuild = True
            else:
                routing_context = self.owner.get_or_create_routing_context()
                object_footprint_id = routing.add_footprint(self.owner.id, self.footprint, self.owner.zone_id)
                routing_context.object_footprint_id = object_footprint_id
                self.owner.clear_raycast_context()
            if self._placement_footprint_added:
                placement.remove_placement_footprint(self.owner)
                placement.add_placement_footprint(self.owner)
            else:
                placement.add_placement_footprint(self.owner)
                self._placement_footprint_added = True
        else:
            routing_context = self.owner.routing_context
            if routing_context is not None and routing_context.object_footprint_id is not None:
                routing.remove_footprint(routing_context.object_footprint_id)
                routing_context.object_footprint_id = None
            if self._placement_footprint_added:
                placement.remove_placement_footprint(self.owner)
                self._placement_footprint_added = False
        if not from_remove:
            self._resend_footprint_status()

    def toggle_contour(self, hash_name, enable):
        routing_context = self.owner.routing_context
        if routing_context is not None:
            footprint_id = self.owner.routing_context.object_footprint_id
            if footprint_id is None:
                logger.error('Cannot toggle footprint if the object ({}) has none.', self.owner, owner='mduke')
                return
        self._enabled_dict = routing.get_footprint_polys(footprint_id)
        if hash_name not in self._enabled_dict:
            logger.error('Attempt to toggle a footprint ({}) that was not found on the object: {}.', hash_name, self.owner, owner='mduke')
            return
        curState = self._enabled_dict[hash_name]
        if curState == enable:
            logger.error('Attempt to toggle a footprint ({}) that is already set.', hash_name, owner='mduke')
            return
        self._enabled_dict[hash_name] = enable
        self.update_footprint()

    def _get_enable_and_disable_counts(self, footprint_hash):
        if self._footprint_tracker is None:
            self._footprint_tracker = defaultdict(lambda : [0, 0, 0])
        return self._footprint_tracker[footprint_hash]

    def start_toggle_footprint(self, toggle):
        counts = self._get_enable_and_disable_counts(toggle.footprint_hash)
        if toggle.enable:
            if counts[self._DISABLED_COUNT_INDEX] != 0:
                logger.error('Attempt to enable a footprint that is currently being disabled by another SI. Request will be ignored.', owner='mduke')
            elif counts[self._ENABLED_COUNT_INDEX] == 0:
                self.toggle_contour(toggle.footprint_hash, enable=True)
            counts[self._ENABLED_COUNT_INDEX] += 1
        else:
            if counts[self._ENABLED_COUNT_INDEX] != 0:
                logger.error('Attempt to disable a footprint that is currently being enabled by another SI. Request will be ignored.', owner='mduke')
            elif counts[self._DISABLED_COUNT_INDEX] == 0:
                self.toggle_contour(toggle.footprint_hash, enable=False)
            counts[self._DISABLED_COUNT_INDEX] += 1
        counts[self._TOGGLE_COUNT_INDEX] += 1

    def stop_toggle_footprint(self, toggle):
        counts = self._get_enable_and_disable_counts(toggle.footprint_hash)
        if counts[self._TOGGLE_COUNT_INDEX] == 0:
            logger.error('Tunable footprint error on book-keeping.  Stop called more times than start.', owner='mduke')
        counts[self._TOGGLE_COUNT_INDEX] -= 1
        if toggle.enable:
            counts[self._ENABLED_COUNT_INDEX] -= 1
            if counts[self._ENABLED_COUNT_INDEX] == 0:
                self.toggle_contour(toggle.footprint_hash, enable=False)
        else:
            counts[self._DISABLED_COUNT_INDEX] -= 1
            if counts[self._DISABLED_COUNT_INDEX] == 0:
                self.toggle_contour(toggle.footprint_hash, enable=True)

class TunableFootprintToggleElement(TunableFactory):
    __qualname__ = 'TunableFootprintToggleElement'

    @staticmethod
    def factory(interaction, toggles, sequence=(), **kwargs):
        target = interaction.target
        if target is None:
            logger.error('Attempt to toggle a footprint with no target')
            return sequence
        footprint_comp = target.get_component(FOOTPRINT_COMPONENT)
        if footprint_comp is None:
            logger.error('Attempt to toggle a footprint on a target ({}) with no footprint component.', target, owner='mduke')
            return sequence

        def start(*_, **__):
            for toggle in toggles:
                footprint_comp.start_toggle_footprint(toggle)

        def stop(*_, **__):
            for toggle in toggles:
                footprint_comp.stop_toggle_footprint(toggle)

        return build_critical_section_with_finally(start, sequence, stop)

    FACTORY_TYPE = factory

    def __init__(self, **kwargs):
        super().__init__(toggles=TunableList(TunableTuple(enable=Tunable(bool, True, description='If checked, we turn on the tuned footprint when the interaction begins, If not checked we turn off the tuned footprint when the interaction begins.'), footprint_hash=TunableStringHash(description='Name of the footprint to toggle')), description='List of footprints to toggle during the Interaction.'), **kwargs)

