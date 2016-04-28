from protocolbuffers.FileSerialization_pb2 import LotCoord
from autonomy.autonomy_modifier import TunableAutonomyModifier
from build_buy import remove_object_from_buildbuy_system, add_object_to_buildbuy_system, invalidate_object_location, get_object_catalog_name, get_object_catalog_description, is_location_outside, is_location_natural_ground
from carry.carry_postures import CarryingObject
from crafting.genre import Genre
from distributor.shared_messages import IconInfoData
from interactions.utils.routing import RouteTargetType
from interactions.utils.sim_focus import FocusInterestTuning
from objects import VisibilityState
from objects.client_object_mixin import ClientObjectMixin
from objects.components import forward_to_components
from objects.game_object_properties import GameObjectProperty
from objects.mixins import UseListMixin
from objects.object_enums import ResetReason
from objects.persistence_groups import PersistenceGroups
from objects.script_object import ScriptObject
from postures.posture import TunablePostureTypeListSnippet
from sims4.tuning.tunable import Tunable, TunableList, TunableTuple
from sims4.tuning.tunable_base import FilterTag
from singletons import DEFAULT
from snippets import TunableAffordanceFilterSnippet
import alarms
import autonomy
import build_buy
import clock
import distributor.fields
import interactions.constraints
import objects.part
import placement
import routing
import services
import sims4.log
logger = sims4.log.Logger('Objects')

class GameObject(ClientObjectMixin, UseListMixin, ScriptObject):
    __qualname__ = 'GameObject'
    INSTANCE_TUNABLES = {'_focus_bone': Tunable(str, '_focus_', tuning_filter=FilterTag.EXPERT_MODE, description='The name of the bone that the focus system will used to look at.'), '_transient_tuning': Tunable(bool, False, tuning_filter=FilterTag.EXPERT_MODE, description='If transient the object will always be destroyed and never put down.', display_name='Transient'), 'additional_interaction_constraints': TunableList(TunableTuple(constraint=interactions.constraints.TunableConstraintVariant(description='A constraint that must be fulfilled in order to interact with this object.'), affordance_links=TunableAffordanceFilterSnippet()), tuning_filter=FilterTag.EXPERT_MODE, description='A list of constraints that must be fulfilled in order to run the linked affordances.'), 'autonomy_modifiers': TunableList(description='\n            List of autonomy modifiers that will be applied to the tuned\n            participant type.  These can be used to tune object variations.\n            ', tunable=TunableAutonomyModifier(locked_args={'commodities_to_add': (), 'score_multipliers': {}, 'super_affordance_compatibility': None, 'super_affordance_suppression_mode': autonomy.autonomy_modifier.SuperAffordanceSuppression.AUTONOMOUS_ONLY, 'suppress_self_affordances': False, 'only_scored_static_commodities': None, 'only_scored_stats': None, 'relationship_multipliers': None})), 'set_ico_as_carry_target': Tunable(description="\n            Whether or not the crafting process should set the carry target\n            to be the ICO.  Example Usage: Sheet Music has this set to false\n            because the sheet music is in the Sim's inventory and the Sim needs\n            to carry the guitar/violin.  This is a tunable on game object\n            because the ICO in the crafting process can be any game object.\n            ", tunable_type=bool, default=True), 'supported_posture_types': TunablePostureTypeListSnippet(description='\n            The postures supported by this part. If empty, assumes all postures \n            are supported.')}

    def __init__(self, definition, **kwargs):
        super().__init__(definition, **kwargs)
        self._on_location_changed_callbacks = None
        if self._part_data:
            self._parts = []
            for part_data in self._part_data:
                self._parts.append(objects.part.Part(self, part_data))
        else:
            self._in_use = None
        self._transient = None
        self._created_constraints = {}
        self._created_constraints_dirty = True
        self._household_owner_id = None
        self.new_in_inventory = True
        zone = services.current_zone()
        account_id = build_buy.get_user_in_build_buy(zone.id)
        if account_id is not None:
            self.set_household_owner_id(zone.lot.owner_household_id)
            self.set_post_bb_fixup_needed()
            zone.set_to_fixup_on_build_buy_exit(self)
        self._hidden_flags = 0
        self._local_tags = None
        self._is_surface = {}

    def has_tag(self, tag):
        if tag in self.definition.build_buy_tags:
            return True
        if self._local_tags and self._local_tags & set(tag):
            return True
        return False

    def get_tags(self):
        if self._local_tags:
            return self._local_tags | self.definition.build_buy_tags
        return self.definition.build_buy_tags

    def append_tags(self, tag_set):
        if self._local_tags:
            self._local_tags = self._local_tags | tag_set
        else:
            self._local_tags = tag_set

    def get_icon_info_data(self):
        return IconInfoData(obj_instance=self, obj_def_id=self.definition.id, obj_geo_hash=self.geometry_state, obj_material_hash=self.material_hash)

    @property
    def catalog_name(self):
        return get_object_catalog_name(self.definition.id)

    @property
    def catalog_description(self):
        return get_object_catalog_description(self.definition.id)

    @forward_to_components
    def populate_localization_token(self, token):
        self.definition.populate_localization_token(token)

    def is_hidden(self, allow_hidden_flags=0):
        if int(self._hidden_flags) & ~int(allow_hidden_flags):
            return True
        return False

    def has_hidden_flags(self, hidden_flags):
        if int(self._hidden_flags) & int(hidden_flags):
            return True
        return False

    def hide(self, hidden_reasons_to_add):
        self._hidden_flags = self._hidden_flags | hidden_reasons_to_add

    def show(self, hidden_reasons_to_remove):
        self._hidden_flags = self._hidden_flags & ~hidden_reasons_to_remove

    @property
    def transient(self):
        if self._transient is not None:
            return self._transient
        return self._transient_tuning

    @transient.setter
    def transient(self, value):
        self._transient = value

    def get_created_constraint(self, tuned_constraint):
        if self._created_constraints_dirty:
            self._created_constraints.clear()
            for tuned_additional_constraint in self.additional_interaction_constraints:
                constraint = tuned_additional_constraint['constraint']
                while constraint is not None:
                    self._created_constraints[constraint] = constraint.create_constraint(None, self)
            self._created_constraints_dirty = False
        return self._created_constraints.get(tuned_constraint)

    @forward_to_components
    def validate_definition(self):
        pass

    def _should_invalidate_location(self):
        parent = self.parent
        if parent is None:
            return True
        return parent._should_invalidate_location()

    def _notify_buildbuy_of_location_change(self, old_location):
        if self.persistence_group == PersistenceGroups.OBJECT and self._should_invalidate_location():
            invalidate_object_location(self.id, self.zone_id)

    def set_build_buy_lockout_state(self, lockout_state, lockout_timer=None):
        if self._build_buy_lockout_alarm_handler is not None:
            alarms.cancel_alarm(self._build_buy_lockout_alarm_handler)
            self._build_buy_lockout_alarm_handler = None
        elif self._build_buy_lockout and lockout_state:
            return
        if lockout_state and lockout_timer is not None:
            time_span_real_time = clock.interval_in_real_seconds(lockout_timer)
            self._build_buy_lockout_alarm_handler = alarms.add_alarm_real_time(self, time_span_real_time, lambda *_: self.set_build_buy_lockout_state(False))
        if lockout_state and not self.build_buy_lockout:
            self.reset(ResetReason.RESET_EXPECTED)
        self._build_buy_lockout = lockout_state
        self.resend_interactable()
        self.resend_tint()

    def on_location_changed(self, old_location):
        super().on_location_changed(old_location)
        self.clear_check_line_of_sight_cache()
        if self.id:
            self._update_persistence_group()
            self._notify_buildbuy_of_location_change(old_location)
            self.manager.on_location_changed(self)
            if self._on_location_changed_callbacks is not None:
                for callback in self._on_location_changed_callbacks:
                    callback(self, old_location, self.location)
            self._created_constraints_dirty = True

    def set_object_def_state_index(self, state_index):
        if type(self) != self.get_class_for_obj_state(state_index):
            logger.error("Attempting to change object {}'s state to one that would require a different runtime class.  This is not supported.", self, owner='tastle')
        self.apply_definition(self.definition, state_index)
        self.model = self._model
        self.rig = self._rig
        self.resend_state_index()

    def register_on_location_changed(self, callback):
        if self._on_location_changed_callbacks is None:
            self._on_location_changed_callbacks = [callback]
        else:
            self._on_location_changed_callbacks.append(callback)

    def unregister_on_location_changed(self, callback):
        self._on_location_changed_callbacks.remove(callback)
        if not self._on_location_changed_callbacks:
            self._on_location_changed_callbacks = None

    def is_on_active_lot(self, tolerance=0):
        return self.persistence_group == PersistenceGroups.OBJECT

    @property
    def is_in_navmesh(self):
        if self._routing_context is not None and self._routing_context.object_footprint_id is not None:
            return True
        return False

    def footprint_polygon_at_location(self, position, orientation):
        if self.footprint is None or self.routing_surface is None:
            return
        from placement import get_placement_footprint_polygon
        return get_placement_footprint_polygon(position, orientation, self.routing_surface, self.footprint)

    @property
    def object_radius(self):
        if self._routing_context is None:
            return routing.get_default_agent_radius()
        return self._routing_context.object_radius

    @object_radius.setter
    def object_radius(self, value):
        if self._routing_context is not None:
            self._routing_context.object_radius = value

    @distributor.fields.Field(op=distributor.ops.SetFocusScore)
    def focus_score(self):
        return FocusInterestTuning.FOCUS_INTEREST_LEVEL_TO_SCORE[self._focus_score]

    def facing_object(self, obj):
        raise RuntimeError('[bhill] This function is believed to be dead code and is scheduled for pruning. If this exception has been raised, the code is not dead and this exception should be removed.')
        forward = self.forward
        to_obj = sims4.math.vector_normalize(obj.position - self.position)
        cos_of_angle = sims4.math.vector_dot(forward, to_obj)
        if cos_of_angle < 0:
            cos_of_angle = 0
        return cos_of_angle

    @property
    def persistence_group(self):
        return self._persistence_group

    @persistence_group.setter
    def persistence_group(self, value):
        self._persistence_group = value

    def _update_persistence_group(self):
        if self.is_in_inventory():
            self.persistence_group = objects.persistence_groups.PersistenceGroups.OBJECT
            return
        if self.persistence_group == objects.persistence_groups.PersistenceGroups.OBJECT:
            if not services.current_zone().lot.is_position_on_lot(self.position, 0):
                remove_object_from_buildbuy_system(self.id, self.zone_id)
                self.persistence_group = objects.persistence_groups.PersistenceGroups.IN_OPEN_STREET
        elif self.persistence_group == objects.persistence_groups.PersistenceGroups.IN_OPEN_STREET and services.current_zone().lot.is_position_on_lot(self.position, 0):
            self.persistence_group = objects.persistence_groups.PersistenceGroups.OBJECT
            add_object_to_buildbuy_system(self.id, sims4.zone_utils.get_zone_id())

    def _add_to_world(self):
        if self.persistence_group == PersistenceGroups.OBJECT:
            add_object_to_buildbuy_system(self.id, sims4.zone_utils.get_zone_id())

    def _remove_from_world(self):
        if self.persistence_group == PersistenceGroups.OBJECT:
            remove_object_from_buildbuy_system(self.id, self.zone_id)

    def on_add(self):
        super().on_add()
        self._add_to_world()
        self.register_on_location_changed(self.inside_status_change)
        self.register_on_location_changed(self.natural_ground_status_change)
        if (self.flammable or self.fire_retardant) and not self.is_sim:
            fire_service = services.get_fire_service()
            self.register_on_location_changed(fire_service.flammable_object_location_changed)
        self.object_addition_complete()

    def on_remove(self):
        super().on_remove()
        self._remove_from_world()
        self.unregister_on_location_changed(self.inside_status_change)
        self.unregister_on_location_changed(self.natural_ground_status_change)
        if self.flammable and not self.is_sim:
            fire_service = services.get_fire_service()
            if fire_service:
                self.unregister_on_location_changed(fire_service.flammable_object_location_changed)

    def on_added_to_inventory(self):
        super().on_added_to_inventory()
        self._remove_from_world()
        self.visibility = VisibilityState(False)

    def on_removed_from_inventory(self):
        super().on_removed_from_inventory()
        self._add_to_world()
        self.visibility = VisibilityState(True)

    def on_buildbuy_exit(self):
        self.inside_status_change()
        self.natural_ground_status_change()

    def inside_status_change(self, *_, **__):
        if self.zone_id:
            if self.is_outside:
                self._set_placed_outside()
            else:
                self._set_placed_inside()

    def natural_ground_status_change(self, *_, **__):
        if self.zone_id:
            if self.is_on_natural_ground():
                self._set_placed_on_natural_ground()
            else:
                self._set_placed_off_natural_ground()

    @forward_to_components
    def _set_placed_outside(self):
        pass

    @forward_to_components
    def _set_placed_inside(self):
        pass

    @forward_to_components
    def _set_placed_on_natural_ground(self):
        pass

    @forward_to_components
    def _set_placed_off_natural_ground(self):
        pass

    @forward_to_components
    def object_addition_complete(self):
        pass

    @property
    def is_outside(self):
        routing_surface = self.routing_surface
        level = 0 if routing_surface is None else routing_surface.secondary_id
        try:
            return is_location_outside(self.zone_id, self.position, level)
        except RuntimeError:
            pass

    def is_on_natural_ground(self):
        if self.parent is not None:
            return False
        routing_surface = self.routing_surface
        level = 0 if routing_surface is None else routing_surface.secondary_id
        try:
            return is_location_natural_ground(self.zone_id, self.position, level)
        except RuntimeError:
            pass

    def on_child_added(self, child):
        super().on_child_added(child)
        self.get_raycast_root().on_leaf_child_changed()

    def on_child_removed(self, child):
        super().on_child_removed(child)
        self.get_raycast_root().on_leaf_child_changed()

    def on_leaf_child_changed(self):
        if self._raycast_context is not None:
            self._create_raycast_context()

    @property
    def focus_bone(self):
        if self._focus_bone is not None:
            return sims4.hash_util.hash32(self._focus_bone)
        return 0

    @property
    def forward_direction_for_picking(self):
        return sims4.math.Vector3.Z_AXIS()

    @property
    def route_target(self):
        parts = self.parts
        if parts is None:
            return (RouteTargetType.OBJECT, self)
        return (RouteTargetType.PARTS, parts)

    def is_surface(self, include_parts=False, ignore_deco_slots=False):
        key = (include_parts, ignore_deco_slots)
        is_surface = self._is_surface.get(key)
        if is_surface is not None:
            return is_surface
        if self.inventory_component is not None:
            self._is_surface[key] = True
            return True

        def is_valid_surface_slot(slot_type):
            if (not ignore_deco_slots or not slot_type.is_deco_slot) and slot_type.is_surface:
                return True
            return False

        for runtime_slot in self.get_runtime_slots_gen():
            if not include_parts and runtime_slot.owner is not self:
                pass
            if not any(is_valid_surface_slot(slot_type) for slot_type in runtime_slot.slot_types):
                pass
            if not runtime_slot.owner.is_same_object_or_part(self):
                pass
            self._is_surface[key] = True
        self._is_surface[key] = False
        return False

    def get_save_lot_coords_and_level(self):
        lot_coord_msg = LotCoord()
        parent = self.parent
        if parent is not None and parent.is_sim:
            parent.force_update_routing_location()
            starting_position = parent.position + parent.forward
            search_flags = CarryingObject.SNAP_TO_GOOD_LOCATION_SEARCH_FLAGS
            (trans, orient) = placement.find_good_location(placement.FindGoodLocationContext(starting_position=starting_position, starting_orientation=parent.orientation, starting_routing_surface=self.location.world_routing_surface, object_footprints=(self.footprint,), object_id=self.id, search_flags=search_flags))
            if trans is None:
                logger.warn('Unable to find good location to save object{}, which is parented to sim {} and cannot go into an inventory. Defaulting to location of sim.', self, parent)
                transform = parent.transform
            else:
                transform = sims4.math.Transform(trans, orient)
            transform = services.current_zone().lot.convert_to_lot_coordinates(transform)
        elif self.persistence_group == PersistenceGroups.OBJECT:
            transform = services.current_zone().lot.convert_to_lot_coordinates(self.transform)
        else:
            transform = self.transform
        lot_coord_msg.x = transform.translation.x
        lot_coord_msg.y = transform.translation.y
        lot_coord_msg.z = transform.translation.z
        lot_coord_msg.rot_x = transform.orientation.x
        lot_coord_msg.rot_y = transform.orientation.y
        lot_coord_msg.rot_z = transform.orientation.z
        lot_coord_msg.rot_w = transform.orientation.w
        if self.location.world_routing_surface is not None:
            level = self.location.level
        else:
            level = 0
        return (lot_coord_msg, level)

    def save_object(self, object_list, *args):
        save_data = super().save_object(object_list, *args)
        if save_data is None:
            return
        save_data.slot_id = self.bone_name_hash
        (save_data.position, save_data.level) = self.get_save_lot_coords_and_level()
        save_data.scale = self.scale
        save_data.state_index = self.state_index
        save_data.cost = self.current_value
        save_data.ui_metadata = self.ui_metadata._value
        save_data.is_new = self.new_in_inventory
        self.populate_icon_canvas_texture_info(save_data)
        if self._household_owner_id is not None:
            save_data.owner_id = self._household_owner_id
        save_data.needs_depreciation = self._needs_depreciation
        save_data.needs_post_bb_fixup = self._needs_post_bb_fixup
        save_data.created_from_lot_template = False
        save_data.stack_sort_order = self.get_stack_sort_order()
        if self.material_state:
            save_data.material_state = self.material_state.state_name_hash
        if self.geometry_state:
            save_data.geometry_state = self.geometry_state
        if self.model:
            model_key = sims4.resources.get_protobuff_for_key(self.model)
            save_data.model_override_resource_key = model_key
        if self.lighting_component:
            if self.lighting_component.light_color:
                (save_data.light_color.x, save_data.light_color.y, save_data.light_color.z, _) = sims4.color.to_rgba(self.lighting_component.light_color)
            save_data.light_dimmer_value = self.lighting_component.light_dimmer
        parent = self.parent
        if parent is not None and not parent.is_sim:
            save_data.parent_id = parent.id
        if parent is None or not parent.is_sim:
            save_data.object_parent_type = self._parent_type
            save_data.encoded_parent_location = self._parent_location
        self.save_unique_inventory_objects(save_data)
        return save_data

    def load_object(self, object_data):
        if object_data.HasField('owner_id'):
            self._household_owner_id = object_data.owner_id
        self.current_value = object_data.cost
        self.new_in_inventory = object_data.is_new
        super().load_object(object_data)
        if object_data.HasField('needs_depreciation'):
            self._needs_depreciation = object_data.needs_depreciation
        if object_data.HasField('needs_post_bb_fixup'):
            self._needs_post_bb_fixup = object_data.needs_post_bb_fixup
        else:
            self._needs_post_bb_fixup = self._needs_depreciation
        self.load_unique_inventory_objects(object_data)

    def finalize(self, **kwargs):
        super().finalize(**kwargs)
        self.try_post_bb_fixup(**kwargs)

    def set_household_owner_id(self, new_owner_id):
        if self.objectage_component is None and self.manager is not None:
            household_manager = services.household_manager()
            household_manager.decrement_household_object_count(self._household_owner_id)
            household_manager.increment_household_object_count(new_owner_id)
        self._household_owner_id = new_owner_id

    def get_household_owner_id(self):
        return self._household_owner_id

    def get_object_property(self, property_type):
        if property_type == GameObjectProperty.CATALOG_PRICE:
            return self.definition.price
        if property_type == GameObjectProperty.MODIFIED_PRICE:
            return self.current_value
        if property_type == GameObjectProperty.RARITY:
            return self.get_object_rarity()
        if property_type == GameObjectProperty.GENRE:
            return Genre.get_genre_localized_string(self)
        logger.error('Requested property_type {} not found on game_object'.format(property_type), owner='camilogarcia')

    def update_ownership(self, sim, make_sim_owner=True):
        household_id = sim.household.id
        if self._household_owner_id != household_id:
            if self.ownable_component is not None:
                self.ownable_component.update_sim_ownership(None)
            self.set_household_owner_id(household_id)
        if make_sim_owner and self.ownable_component is not None:
            self.ownable_component.update_sim_ownership(sim.sim_id)

    @property
    def flammable(self):
        fire_service = services.get_fire_service()
        if fire_service is not None:
            return fire_service.is_object_flammable(self)
        return False

    def object_bounds_for_flammable_object(self, location=DEFAULT, fire_retardant_bonus=0.0):
        if location is DEFAULT:
            location = sims4.math.Vector2(self.position.x, self.position.z)
        radius = self.object_radius
        if self.fire_retardant:
            radius += fire_retardant_bonus
        object_bounds = sims4.geometry.QtCircle(location, radius)
        return object_bounds

    @property
    def is_set_as_head(self):
        if self.parent is None:
            return False
        if not self.parent.is_sim:
            return False
        if self.parent.current_object_set_as_head is None:
            return False
        parent_head = self.parent.current_object_set_as_head()
        if not self.is_same_object_or_part(parent_head):
            return False
        return True

