from _weakrefset import WeakSet
from math import floor
from protocolbuffers import UI_pb2 as ui_protocols
import native.animation
from build_buy import get_object_decosize, get_object_slotset
from distributor.system import Distributor
from event_testing import test_events
from interactions.utils.animation import ArbElement
from objects import VisibilityState, MaterialState
from objects.components import forward_to_components, forward_to_components_gen
from objects.components.censor_grid_component import CensorState
from objects.components.types import CARRYABLE_COMPONENT
from objects.definition import Definition
from objects.game_object_properties import GameObjectProperty
from objects.object_enums import ResetReason
from objects.slots import RuntimeSlot, DecorativeSlotTuning, get_slot_type_set_from_key
from services.reset_and_delete_service import ResetRecord
from sims4.tuning.tunable import TunablePercent, TunableSimMinute
from singletons import EMPTY_SET
import alarms
import animation.arb
import caches
import date_and_time
import distributor.ops
import distributor.sparse
import enum
import objects.definition
import routing
import services
import sims4.log
import uid
logger = sims4.log.Logger('Objects', default_owner='PI')
with sims4.reload.protected(globals()):
    lockout_visualization = False

def get_default_location():
    return sims4.math.Location(sims4.math.Transform(), routing.SurfaceIdentifier(0, 0, routing.SURFACETYPE_WORLD))

class ObjectParentType(enum.Int, export=False):
    __qualname__ = 'ObjectParentType'
    PARENT_NONE = 0
    PARENT_OBJECT = 1
    PARENT_COLUMN = 2
    PARENT_WALL = 3
    PARENT_FENCE = 4
    PARENT_POST = 5

class ClientObjectMixin:
    __qualname__ = 'ClientObjectMixin'
    INITIAL_DEPRECIATION = TunablePercent(20, description='Amount (0%%-100%%) of depreciation to apply to an object after purchase. An item worth 10 in the catalog if tuned at 20%% will be worth 8 after purchase.')
    FADE_DURATION = TunableSimMinute(1.2, description='Default fade time (in sim minutes) for objects.')
    VISIBLE_TO_AUTOMATION = True
    _get_next_ui_metadata_handle = uid.UniqueIdGenerator()
    FORWARD_OFFSET = 0.01

    def __init__(self, definition, **kwargs):
        self._ui_metadata_stack = []
        self._ui_metadata_handles = {}
        self._ui_metadata_cache = {}
        super().__init__(definition, **kwargs)
        if definition is not None:
            self.apply_definition(definition, **kwargs)
        self.primitives = distributor.ops.DistributionSet(self)
        self._location = sims4.math.Location(sims4.math.Transform(), routing.SurfaceIdentifier(sims4.zone_utils.get_zone_id(), 0, routing.SURFACETYPE_WORLD))
        self._children = WeakSet()
        self._occupied_slot_dict = {}
        self._scale = 1
        self._parent_type = ObjectParentType.PARENT_NONE
        self._parent_location = 0
        self._build_buy_lockout = False
        self._build_buy_lockout_alarm_handler = None
        self._tint = None
        self._opacity = None
        self._censor_state = None
        self._geometry_state = None
        self._visibility = None
        self._material_state = None
        self._reference_arb = None
        self._audio_effects = {}
        self._video_playlist = None
        self._painting_state = None
        self._current_value = definition.price
        self._needs_post_bb_fixup = False
        self._needs_depreciation = False
        self._fade_out_alarm_handle = None

    def get_create_op(self, *args, **kwargs):
        additional_ops = list(self.get_additional_create_ops_gen())
        return distributor.ops.ObjectCreate(self, additional_ops=additional_ops, *args, **kwargs)

    @forward_to_components_gen
    def get_additional_create_ops_gen(self):
        pass

    def get_create_after_objs(self):
        parent = self.parent_object
        if parent is not None:
            return (parent,)
        return ()

    def get_delete_op(self):
        return distributor.ops.ObjectDelete()

    @forward_to_components
    def apply_definition(self, definition, obj_state=0):
        if not isinstance(definition, objects.definition.Definition):
            definition = services.definition_manager().get(definition)
        self._model = definition.get_model(obj_state)
        self._material_variant = definition.material_variant
        self._rig = definition.get_rig(obj_state)
        self._slot = definition.get_slot(obj_state)
        self._slots_resource = definition.get_slots_resource(obj_state)
        self._state_index = obj_state

    def set_definition(self, definition_id, ignore_rig_footprint=False):
        new_definition = services.definition_manager().get(definition_id)
        (result, error) = self.definition.is_similar(new_definition, ignore_rig_footprint=ignore_rig_footprint)
        if not result:
            logger.error('Trying to set the definition {} to an incompatible definition {}.\n {}', self.definition.id, definition_id, error, owner='nbaker')
            return False
        services.definition_manager().unregister_definition(self.definition.id, self)
        self.apply_definition(new_definition, self._state_index)
        self.definition = new_definition
        services.definition_manager().register_definition(new_definition.id, self)
        self.resend_model_with_material_variant()
        self.resend_slot()
        self.resend_state_index()
        op = distributor.ops.SetObjectDefinitionId(definition_id)
        distributor.system.Distributor.instance().add_op(self, op)
        return True

    ui_metadata = distributor.sparse.SparseField(ui_protocols.UiObjectMetadata, distributor.ops.SetUiObjectMetadata)
    custom_name = ui_metadata.generic_property('custom_name', auto_reset=True)
    custom_description = ui_metadata.generic_property('custom_description', auto_reset=True)
    hover_tip = ui_metadata.generic_property('hover_tip')
    _generic_ui_metadata_setters = {}

    def add_ui_metadata(self, name, value, defer_update=False):
        if name not in self._ui_metadata_cache:
            default_value = type(self).ui_metadata.generic_getter(name)(self)
            self._ui_metadata_cache[name] = default_value
        handle = self._get_next_ui_metadata_handle()
        data = (handle, name, value)
        self._ui_metadata_stack.append(data)
        self._ui_metadata_handles[handle] = data
        if not defer_update:
            self.update_ui_metadata()
        return handle

    def remove_ui_metadata(self, handle, defer_update=False):
        self._ui_metadata_stack.remove(self._ui_metadata_handles[handle])
        if not defer_update:
            self.update_ui_metadata()

    def update_ui_metadata(self, use_cache=True):
        ui_metadata = {}
        for (_, name, value) in self._ui_metadata_stack:
            ui_metadata[name] = value
        for (name, value) in ui_metadata.items():
            if name in self._ui_metadata_cache and self._ui_metadata_cache[name] == value and use_cache:
                pass
            if name in self._generic_ui_metadata_setters:
                setter = self._generic_ui_metadata_setters[name]
            else:
                setter = type(self).ui_metadata.generic_setter(name)
                self._generic_ui_metadata_setters[name] = setter
            setter(self, value)
        self._ui_metadata_cache = ui_metadata

    @distributor.fields.Field(op=distributor.ops.SetLocation, default=get_default_location(), direct_attribute_name='_location')
    def location(self):
        if self._location is not None:
            return self._location.duplicate()

    @location.setter
    def location(self, new_location):
        self.set_location_without_distribution(new_location)

    def set_location_without_distribution(self, new_location):
        if not isinstance(new_location, sims4.math.Location):
            raise TypeError()
        if new_location == self._location:
            return
        old_location = self._location
        events = [(self, old_location)]
        for child in self.children_recursive_gen():
            events.append((child, child._location))
        if new_location.parent != old_location.parent:
            self.pre_parent_change(new_location.parent)
            if old_location.parent is not None:
                old_location.parent._remove_child(self)
            if new_location.parent is not None:
                new_location.parent._add_child(self)
            visibility_state = self.visibility or VisibilityState()
            if new_location.parent is not None and new_location.parent._disable_child_footprint_and_shadow:
                visibility_state.enable_drop_shadow = False
            else:
                visibility_state.enable_drop_shadow = True
            self.visibility = visibility_state
        if new_location.parent is not None:
            current_inventory = self.get_inventory()
            if current_inventory is not None:
                if not current_inventory.try_remove_object_by_id(self.id):
                    raise RuntimeError('Unable to remove object: {} from the inventory: {}, parenting request will be ignored.'.format(self, current_inventory))
        posture_graph_service = services.current_zone().posture_graph_service
        with posture_graph_service.object_moving(self):
            self._location = new_location
        if new_location.parent != old_location.parent:
            self.on_parent_change(new_location.parent)
        for (obj, old_value) in events:
            obj.on_location_changed(old_value)

    def set_location(self, location):
        self.location = location

    def move_to(self, **overrides):
        self.location = self._location.clone(**overrides)

    @distributor.fields.Field(op=distributor.ops.SetAudioEffects)
    def audio_effects(self):
        return self._audio_effects

    @audio_effects.setter
    def audio_effects(self, value):
        self._audio_effects = value

    def append_audio_effect(self, key, value):
        self._audio_effects[key] = value
        self.audio_effects = self._audio_effects

    def remove_audio_effect(self, key):
        del self._audio_effects[key]
        self.audio_effects = self._audio_effects

    @forward_to_components
    def on_location_changed(self, old_location):
        pass

    @property
    def transform(self):
        return self._location.world_transform

    @transform.setter
    def transform(self, transform):
        if self.parent is not None:
            raise AssertionError('Cannot change the transform of a parented object directly. {} is parented to {}.'.format(self, self.parent))
        self.move_to(transform=transform)

    @property
    def position(self):
        return self.transform.translation

    @property
    def position_with_forward_offset(self):
        return self.position + self.forward*ClientObjectMixin.FORWARD_OFFSET

    @property
    def intended_position_with_forward_offset(self):
        return self.intended_position + self.intended_forward*ClientObjectMixin.FORWARD_OFFSET

    @property
    def orientation(self):
        return self.transform.orientation

    @property
    def forward(self):
        return self.orientation.transform_vector(self.forward_direction_for_picking)

    @property
    def routing_surface(self):
        return self._location.world_routing_surface

    @property
    def routing_location(self):
        return self.get_routing_location_for_transform(self.transform)

    def get_routing_location_for_transform(self, transform):
        return routing.Location(transform.translation, transform.orientation, self.routing_surface)

    @property
    def intended_transform(self):
        return self.transform

    @property
    def intended_position(self):
        return self.intended_transform.translation

    @property
    def intended_forward(self):
        return self.intended_transform.orientation.transform_vector(self.forward_direction_for_picking)

    @property
    def intended_routing_surface(self):
        return self.routing_surface

    @property
    def parent(self):
        return self._location.parent

    @property
    def parent_object(self):
        parent = self.parent
        if parent is not None and parent.is_part:
            parent = parent.part_owner
        return parent

    @property
    def parent_slot(self):
        parent = self.parent
        if parent is None:
            return
        bone_name_hash = self._location.joint_name_or_hash or self._location.slot_hash
        result = None
        for runtime_slot in parent.get_runtime_slots_gen(bone_name_hash=bone_name_hash):
            if result is not None:
                raise AssertionError('Multiple slots!')
            result = runtime_slot
        if result is None:
            result = RuntimeSlot(parent, bone_name_hash, frozenset())
        return result

    def get_parenting_root(self):
        result = self
        next_parent = result.parent
        while next_parent is not None:
            result = next_parent
            next_parent = result.parent
        return result

    @property
    def children(self):
        return self._children

    def children_recursive_gen(self, include_self=False):
        if include_self:
            yield self
        if self.is_part:
            obj_owner = self.part_owner
        else:
            obj_owner = self
        for child in obj_owner.children:
            yield child
            for grandchild in child.children_recursive_gen():
                yield grandchild

    def parenting_hierarchy_gen(self):
        if self.parent is not None:
            master_parent = self.parent
            while master_parent.parent is not None:
                master_parent = master_parent.parent
            for child in master_parent.children_recursive_gen(include_self=True):
                yield child
        else:
            for child in self.children_recursive_gen(include_self=True):
                yield child

    def on_reset_send_op(self, reset_reason):
        super().on_reset_send_op(reset_reason)
        if self.valid_for_distribution and reset_reason != ResetReason.BEING_DESTROYED:
            try:
                reset_op = distributor.ops.ResetObject(self.id)
                dist = Distributor.instance()
                dist.add_op(self, reset_op)
            except:
                logger.exception('Exception thrown sending reset op for {}', self)

    def on_reset_internal_state(self, reset_reason):
        if self.valid_for_distribution:
            self.geometry_state = None
            self.material_state = None
        self._reset_reference_arb()
        super().on_reset_internal_state(reset_reason)

    def on_reset_get_interdependent_reset_records(self, reset_reason, reset_records):
        super().on_reset_get_interdependent_reset_records(reset_reason, reset_records)
        for child in self.children:
            reset_records.append(ResetRecord(child, ResetReason.RESET_EXPECTED, self, 'Child'))

    @property
    def slot_hash(self):
        return self._location.slot_hash

    @slot_hash.setter
    def slot_hash(self, value):
        if self._location.slot_hash != value:
            new_location = self._location
            new_location.slot_hash = value
            self.location = new_location

    @property
    def bone_name_hash(self):
        return self._location.joint_name_or_hash or self._location.slot_hash

    @property
    def part_suffix(self) -> str:
        pass

    @distributor.fields.Field(op=distributor.ops.SetModel)
    def model_with_material_variant(self):
        return (self._model, self._material_variant)

    resend_model_with_material_variant = model_with_material_variant.get_resend()

    @model_with_material_variant.setter
    def model_with_material_variant(self, value):
        (self._model, self._material_variant) = value

    @property
    def model(self):
        return self._model

    @model.setter
    def model(self, value):
        model_res_key = None
        if isinstance(value, sims4.resources.Key):
            model_res_key = value
        elif isinstance(value, Definition):
            model_res_key = value._model[0]
            self.set_definition(value.id, ignore_rig_footprint=True)
        else:
            if value is not None:
                logger.error('Trying to set the model of object {} to the invalid value of {}.                                The object will revert to its default model instead.', self, value, owner='tastle')
            model_res_key = self.definition.get_model(self._state_index)
        self.model_with_material_variant = (model_res_key, self._material_variant)

    @property
    def material_variant(self):
        return self._material_variant

    @material_variant.setter
    def material_variant(self, value):
        if value is None:
            self.model_with_material_variant = (self._model, None)
        else:
            if not isinstance(value, str):
                raise TypeError('Model variant value must be a string')
            if not value:
                self.model_with_material_variant = (self._model, None)
            else:
                variant_hash = sims4.hash_util.hash32(value)
                self.model_with_material_variant = (self._model, variant_hash)

    @distributor.fields.Field(op=distributor.ops.SetObjectDefStateIndex, default=0)
    def state_index(self):
        return self._state_index

    resend_state_index = state_index.get_resend()

    @distributor.fields.Field(op=distributor.ops.SetRig, priority=distributor.fields.Field.Priority.HIGH)
    def rig(self):
        return self._rig

    @rig.setter
    def rig(self, value):
        if not isinstance(value, sims4.resources.Key):
            raise TypeError
        self._rig = value

    @distributor.fields.Field(op=distributor.ops.SetSlot)
    def slot(self):
        return self._slot

    resend_slot = slot.get_resend()

    @property
    def slots_resource(self):
        return self._slots_resource

    @distributor.fields.Field(op=distributor.ops.SetScale, default=1)
    def scale(self):
        return self._scale

    @forward_to_components_gen
    def scale_modifiers_gen(self):
        pass

    @scale.setter
    def scale(self, value):
        for modifier in self.scale_modifiers_gen():
            value *= modifier
        self._scale = value

    @property
    def parent_type(self):
        return self._parent_type

    @parent_type.setter
    def parent_type(self, value):
        self._parent_type = value
        self._resend_parent_type_info()

    @distributor.fields.Field(op=distributor.ops.SetParentType, default=None)
    def parent_type_info(self):
        return (self._parent_type, self._parent_location)

    @parent_type_info.setter
    def parent_type_info(self, value):
        (self._parent_type, self._parent_location) = value

    _resend_parent_type_info = parent_type_info.get_resend()

    @property
    def build_buy_lockout(self):
        return self._build_buy_lockout

    @distributor.fields.Field(op=distributor.ops.SetTint, default=None)
    def tint(self):
        if self.build_buy_lockout and lockout_visualization:
            return sims4.color.ColorARGB32(23782)
        return self._tint

    @tint.setter
    def tint(self, value):
        if value and not isinstance(value, sims4.color.ColorARGB32):
            raise TypeError('Tint value must be a Color')
        if value == sims4.color.Color.WHITE:
            self._tint = None
        else:
            self._tint = value

    resend_tint = tint.get_resend()

    @distributor.fields.Field(op=distributor.ops.SetOpacity, default=None)
    def opacity(self):
        return self._opacity

    @opacity.setter
    def opacity(self, value):
        self._opacity = self._clamp_opacity(value)

    def _clamp_opacity(self, value):
        if value is None:
            return
        try:
            value = float(value)
        except:
            raise TypeError('Opacity value must be a float')
        return sims4.math.clamp(0.0, value, 1.0)

    @distributor.fields.Field(op=distributor.ops.SetGeometryState, default=None)
    def geometry_state(self):
        return self._geometry_state

    @geometry_state.setter
    def geometry_state(self, value):
        if value is None:
            self._geometry_state = None
        else:
            if not isinstance(value, str):
                raise TypeError('Geometry State value must be a string')
            if len(value) == 0:
                self._geometry_state = None
            else:
                state_hash = sims4.hash_util.hash32(value)
                self._geometry_state = state_hash

    @distributor.fields.Field(op=distributor.ops.SetCensorState, default=None)
    def censor_state(self):
        return self._censor_state

    @censor_state.setter
    def censor_state(self, value):
        try:
            value = CensorState(value)
        except:
            raise TypeError('Censor State value must be an int')
        self._censor_state = value

    @distributor.fields.Field(op=distributor.ops.SetVisibility, default=None)
    def visibility(self):
        return self._visibility

    @visibility.setter
    def visibility(self, value):
        if not isinstance(value, VisibilityState):
            raise TypeError('Visibility must be set to value of type VisibilityState')
        self._visibility = value
        if value is not None and (value.visibility is True and value.inherits is False) and value.enable_drop_shadow is False:
            self._visibility = None

    @distributor.fields.Field(op=distributor.ops.SetMaterialState, default=None)
    def material_state(self):
        return self._material_state

    @material_state.setter
    def material_state(self, value):
        if value is None:
            self._material_state = None
        else:
            if not isinstance(value, MaterialState):
                raise TypeError('Material State must be set to value of type MaterialState')
            if value.state_name_hash == 0:
                self._material_state = None
            else:
                self._material_state = value

    @property
    def material_hash(self):
        if self.material_state is None:
            return 0
        return self.material_state.state_name_hash

    @distributor.fields.Field(op=distributor.ops.StartArb, default=None)
    def reference_arb(self):
        return self._reference_arb

    def update_reference_arb(self, arb):
        if self._reference_arb is None:
            self._reference_arb = animation.arb.Arb()
        native.animation.update_post_condition_arb(self._reference_arb, arb)

    def _reset_reference_arb(self):
        if self._reference_arb is not None:
            reset_arb_element = ArbElement(animation.arb.Arb())
            reset_arb_element.add_object_to_reset(self)
            reset_arb_element.distribute()
        self._reference_arb = None

    _NO_SLOTS = EMPTY_SET

    @property
    def deco_slot_size(self):
        return get_object_decosize(self.definition.id)

    @property
    def deco_slot_types(self):
        return DecorativeSlotTuning.get_slot_types_for_object(self.deco_slot_size)

    @property
    def slot_type_set(self):
        key = get_object_slotset(self.definition.id)
        return get_slot_type_set_from_key(key)

    @property
    def slot_types(self):
        slot_type_set = self.slot_type_set
        if slot_type_set is not None:
            return slot_type_set.slot_types
        return self._NO_SLOTS

    @property
    def ideal_slot_types(self):
        carryable = self.get_component(CARRYABLE_COMPONENT)
        if carryable is not None:
            slot_type_set = carryable.ideal_slot_type_set
            if slot_type_set is not None:
                return slot_type_set.slot_types & (self.slot_types | self.deco_slot_types)
        return self._NO_SLOTS

    @property
    def all_valid_slot_types(self):
        return self.deco_slot_types | self.slot_types

    def _add_child(self, child):
        if not isinstance(self.children, (WeakSet, set)):
            raise TypeError("self.children is not a WeakSet or a set, it's {}".format(self.children))
        self.children.add(child)
        if self.parts:
            for part in self.parts:
                part.on_children_changed()
        self.on_child_added(child)

    def _remove_child(self, child):
        if not isinstance(self.children, (WeakSet, set)):
            raise TypeError("self.children is not a WeakSet or a set, it's {}".format(self.children))
        self.children.discard(child)
        if self.parts:
            for part in self.parts:
                part.on_children_changed()
        self.on_child_removed(child)

    def on_remove_from_client(self):
        super().on_remove_from_client()
        if self._fade_out_alarm_handle is not None:
            alarms.cancel_alarm(self._fade_out_alarm_handle)
            self._fade_out_alarm_handle = None
        for primitive in tuple(self.primitives):
            primitive.detach(self)

    def post_remove(self):
        for value in objects.components.component_attributes:
            while self.has_component(value):
                self.remove_component(value)
        for primitive in tuple(self.primitives):
            primitive.detach(self)
        self.primitives = None

    @forward_to_components
    def on_child_added(self, child):
        pass

    @forward_to_components
    def on_child_removed(self, child):
        pass

    @forward_to_components
    def pre_parent_change(self, parent):
        pass

    @forward_to_components
    def on_parent_change(self, parent):
        caches.clear_all_caches()
        if parent is None:
            self.parent_type = ObjectParentType.PARENT_NONE
        else:
            self.parent_type = ObjectParentType.PARENT_OBJECT

    def set_parent(self, parent, transform=sims4.math.Transform.IDENTITY(), joint_name_or_hash=None, slot_hash=0, routing_surface=None):
        part_joint_name = joint_name_or_hash or slot_hash
        if parent is not None and (part_joint_name is not None and not parent.is_part) and parent.parts:
            for part in parent.parts:
                while part.has_slot(part_joint_name):
                    parent = part
                    break
            import animation.animation_utils
            slot_name = animation.animation_utils.unhash_bone_name(part_joint_name)
            logger.error('Trying to parent({} to {} in slot {}) and there are no parts that contain the slot type.', self, parent, slot_name)
        new_location = self._location.clone(transform=transform, joint_name_or_hash=joint_name_or_hash, slot_hash=slot_hash, parent=parent, routing_surface=routing_surface)
        self.location = new_location

    def clear_parent(self, transform, routing_surface):
        return self.set_parent(None, transform=transform, routing_surface=routing_surface)

    def remove_reference_from_parent(self):
        if self.parent is not None:
            self.parent._remove_child(self)

    @distributor.fields.Field(op=distributor.ops.VideoSetPlaylistOp, default=None)
    def video_playlist(self):
        return self._video_playlist

    @video_playlist.setter
    def video_playlist(self, playlist):
        self._video_playlist = playlist

    _resend_video_playlist = video_playlist.get_resend()

    def fade_opacity(self, opacity, duration):
        opacity = self._clamp_opacity(opacity)
        if opacity != self._opacity:
            self._opacity = opacity
            fade_op = distributor.ops.FadeOpacity(opacity, duration)
            distributor.ops.record(self, fade_op)

    def fade_in(self):
        if self.visibility is not None and not self.visibility.visibility:
            self.visibility = VisibilityState()
            self.opacity = 0
        self.fade_opacity(1, ClientObjectMixin.FADE_DURATION)

    def fade_out(self):
        self.fade_opacity(0, ClientObjectMixin.FADE_DURATION)

    def fade_and_destroy(self, **kwargs):

        def destroy(_):
            self.destroy(**kwargs)

        if self._fade_out_alarm_handle is not None:
            return
        self.fade_out()
        self._fade_out_alarm_handle = alarms.add_alarm(self, date_and_time.create_time_span(minutes=ClientObjectMixin.FADE_DURATION), destroy)

    @distributor.fields.Field(op=distributor.ops.SetValue, default=None)
    def current_value(self):
        return self._current_value

    @current_value.setter
    def current_value(self, value):
        self._current_value = value

    @property
    def depreciated_value(self):
        if not self.definition.get_can_depreciate():
            return self.catalog_value
        return self.catalog_value*(1 - self.INITIAL_DEPRECIATION)

    @property
    def catalog_value(self):
        return self.get_object_property(GameObjectProperty.CATALOG_PRICE)

    @property
    def depreciated(self):
        return not self._needs_depreciation

    def set_post_bb_fixup_needed(self):
        self._needs_post_bb_fixup = True
        self._needs_depreciation = True

    def try_post_bb_fixup(self, force_fixup=False, active_household_id=0):
        if force_fixup or self._needs_depreciation:
            if force_fixup:
                self._needs_depreciation = True
            self._on_try_depreciation(active_household_id=active_household_id)
        if force_fixup or self._needs_post_bb_fixup:
            self._needs_post_bb_fixup = False
            self.on_post_bb_fixup()

    @forward_to_components
    def on_post_bb_fixup(self):
        services.get_event_manager().process_events_for_household(test_events.TestEvent.ObjectAdd, None, obj=self)

    def _on_try_depreciation(self, active_household_id=0):
        if self._household_owner_id != active_household_id:
            return
        self._needs_depreciation = False
        if not self.definition.get_can_depreciate():
            return
        self.current_value = floor(self._current_value*(1 - self.INITIAL_DEPRECIATION))

