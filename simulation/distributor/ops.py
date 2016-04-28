import weakref
from distributor.rollback import ProtocolBufferRollback
from protocolbuffers import Animation_pb2, DistributorOps_pb2, Routing_pb2, Sims_pb2, Area_pb2, InteractionOps_pb2, Commodities_pb2, UI_pb2 as ui_ops
from protocolbuffers.Consts_pb2 import MGR_UNMANAGED
from sims4.repr_utils import standard_repr, standard_float_tuple_repr, standard_brief_id_repr, standard_angle_repr
import distributor.fields
import distributor.system
import protocolbuffers.Audio_pb2
import protocolbuffers.VFX_pb2
import services
import sims4.color
import sims4.hash_util
import sims4.log
__unittest__ = 'test.distributor.ops_test'
protocol_constants = DistributorOps_pb2.Operation

def record(obj, op):
    if not obj.valid_for_distribution:
        sims4.log.error('Distributor', 'Attempting to record an Op ({}) onto an object ({}) that is not on the client.', op, obj)
        return
    distributor_instance = distributor.system.Distributor.instance()
    distributor_instance.add_op(obj, op)

class DistributionSet(weakref.WeakSet):
    __qualname__ = 'DistributionSet'
    __slots__ = ('obj',)

    def __init__(self, obj):
        super().__init__()
        self.obj = obj

    def __repr__(self):
        return standard_repr(self, set(self))

    def add(self, item):
        super().add(item)
        obj = self.obj
        if getattr(obj, 'valid_for_distribution', True):
            master = item.master
            if master is None or master is obj:
                from distributor.system import Distributor
                distributor = Distributor.instance()
                distributor.add_op(obj, item)

class Op:
    __qualname__ = 'Op'

    def __init__(self, immediate=False, **kwargs):
        super().__init__(**kwargs)
        self._additional_channels = set()
        self._force_execution_on_tag = False
        if immediate:
            self._primary_channel_mask_override = 0
        else:
            self._primary_channel_mask_override = None

    def __repr__(self):
        return standard_repr(self)

    @property
    def is_create_op(self):
        return False

    def add_additional_channel(self, manager_id, object_id, mask=None):
        if mask is None:
            mask = 4294967295
        channel = (manager_id, object_id, 0 if self._force_execution_on_tag and manager_id != MGR_UNMANAGED else mask)
        self._additional_channels.add(channel)

    def block_tag(self, tag):
        self.add_additional_channel(MGR_UNMANAGED, tag)

    def block_on_tag(self, tag, force_execute_on_tag=True):
        _prev_tag_execution_state = self._force_execution_on_tag
        self._force_execution_on_tag = self._force_execution_on_tag or force_execute_on_tag
        self.add_additional_channel(MGR_UNMANAGED, tag)
        if self._force_execution_on_tag != _prev_tag_execution_state:
            old_channels = self._additional_channels
            self._additional_channels = set()
            for channel in old_channels:
                self._additional_channels.add((channel[0], channel[1], 0 if self._force_execution_on_tag and channel[0] != MGR_UNMANAGED else channel[2]))

    def write(self, msg):
        raise NotImplementedError

class ElementDistributionOpMixin(Op):
    __qualname__ = 'ElementDistributionOpMixin'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._master_ref = None
        self._attached = False

    @property
    def master(self):
        master = self._master_ref
        master = master() if master is not None else None
        return master

    @master.setter
    def master(self, value):
        self._master_ref = value.ref() if value is not None else None

    @property
    def is_attached(self):
        return self._attached

    def attach(self, *objects, master=None):
        self._attached = True
        if master:
            self.master = master
        elif self.master is None:
            self.master = objects[0]
        for obj in objects:
            obj.primitives.add(self)

    def detach(self, *objects):
        master = self.master
        self._attached = False
        for obj in objects:
            if obj.primitives is not None:
                obj.primitives.discard(self)
            while obj is master:
                self.master = None

class GenericCreate(Op):
    __qualname__ = 'GenericCreate'

    @property
    def is_create_op(self):
        return True

    def __init__(self, obj, op, additional_ops=()):
        super().__init__()
        self._fill_in_operation_list(obj, op)
        for additional_op in additional_ops:
            with ProtocolBufferRollback(op.operation_list.operations) as op_msg:
                additional_op.write(op_msg)
        self.data = op.SerializeToString()

    def _fill_in_operation_list(self, obj, create_op):
        operations = create_op.operation_list.operations
        distributor.fields.Field.fill_in_operation_list(obj, operations, for_create=True)
        for primitive in obj.primitives:
            while obj is primitive.master:
                with ProtocolBufferRollback(operations) as op_msg:
                    primitive.write(op_msg)

class SparseMessageOp(Op):
    __qualname__ = 'SparseMessageOp'
    TYPE = None

    def __init__(self, value):
        super().__init__()
        self.value = value

    def write(self, msg):
        msg.type = self.TYPE
        msg.data = self.value.SerializeToString()

class GenericProtocolBufferOp(Op):
    __qualname__ = 'GenericProtocolBufferOp'

    def __init__(self, type_constant, protocol_buffer):
        super().__init__()
        self.type_constant = type_constant
        self.protocol_buffer = protocol_buffer

    def write(self, msg):
        msg.type = self.type_constant
        msg.data = self.protocol_buffer.SerializeToString()

class ObjectCreate(GenericCreate):
    __qualname__ = 'ObjectCreate'

    def __init__(self, obj, *args, **kwargs):
        op = DistributorOps_pb2.ObjectCreate()
        op.def_id = obj.definition.id
        op.visible_to_automation = obj.VISIBLE_TO_AUTOMATION
        for component in obj.definition.components:
            op.components.append(component)
        super().__init__(obj, op, *args, **kwargs)
        self.data = op.SerializeToString()

    def write(self, msg):
        msg.type = protocol_constants.OBJECT_CREATE
        msg.data = self.data

class ObjectDelete(Op):
    __qualname__ = 'ObjectDelete'

    def write(self, msg):
        msg.type = protocol_constants.OBJECT_DELETE

class SocialGroupCreate(GenericCreate):
    __qualname__ = 'SocialGroupCreate'

    def __init__(self, obj, *args, **kwargs):
        op = DistributorOps_pb2.SocialGroupCreate()
        super().__init__(obj, op, *args, **kwargs)

    def write(self, msg):
        msg.type = protocol_constants.SOCIAL_GROUP_CREATE
        msg.data = self.data

class SocialGroupUpdate(Op):
    __qualname__ = 'SocialGroupUpdate'

    def __init__(self, social_group_members):
        super().__init__()
        self._social_group_members = social_group_members

    def write(self, msg):
        op = DistributorOps_pb2.SocialGroupUpdate()
        for social_group_member in self._social_group_members:
            social_group_member_msg = op.members.add()
            social_group_member_msg.sim_id = social_group_member.sim_id
            social_context_bit = social_group_member.social_context_bit
            while social_context_bit is not None:
                social_group_member_msg.social_context_bit_id = social_context_bit.guid64
        msg.type = protocol_constants.SOCIAL_GROUP_UPDATE
        msg.data = op.SerializeToString()

class SocialGroupDelete(Op):
    __qualname__ = 'SocialGroupDelete'

    def write(self, msg):
        msg.type = protocol_constants.SOCIAL_GROUP_DELETE

class SimInfoCreate(GenericCreate):
    __qualname__ = 'SimInfoCreate'

    def __init__(self, obj, *args, **kwargs):
        op = DistributorOps_pb2.SimInfoCreate()
        super().__init__(obj, op, *args, **kwargs)

    def write(self, msg):
        msg.type = protocol_constants.SIM_INFO_CREATE
        msg.data = self.data

class SimInfoDelete(Op):
    __qualname__ = 'SimInfoDelete'

    def write(self, msg):
        msg.type = protocol_constants.SIM_INFO_DELETE

class ClientCreate(GenericCreate):
    __qualname__ = 'ClientCreate'

    def __init__(self, obj, *args, is_active=False, **kwargs):
        op = DistributorOps_pb2.ClientCreate()
        op.account_id = obj.account.id
        op.household_id = obj.household_id
        op.is_active = is_active
        super().__init__(obj, op, *args, **kwargs)

    def write(self, msg):
        msg.type = protocol_constants.CLIENT_CREATE
        msg.data = self.data

class ClientDelete(Op):
    __qualname__ = 'ClientDelete'

    def write(self, msg):
        msg.type = protocol_constants.CLIENT_DELETE

class SetAudioEffects(Op):
    __qualname__ = 'SetAudioEffects'

    def __init__(self, audio_effects):
        super().__init__()
        self.op = DistributorOps_pb2.SetAudioEffects()
        for (key, effect_id) in audio_effects.items():
            audio_effect_msg = self.op.audio_effects.add()
            audio_effect_msg.key = sims4.hash_util.hash64(key)
            audio_effect_msg.effect_id = sims4.hash_util.hash64(effect_id)

    def __repr__(self):
        output = 'SetAudioEffects(Op):\n'
        for audio_effect_msg in self.op.audio_effects:
            output += '   Effect Key: {}, Effect Id: {}\n'.format(audio_effect_msg.key, audio_effect_msg.effect_id)
        return output

    def write(self, msg):
        msg.type = protocol_constants.SET_AUDIO_EFFECTS
        msg.data = self.op.SerializeToString()

class SetLocation(Op):
    __qualname__ = 'SetLocation'

    def __init__(self, location):
        super().__init__()
        self.op = DistributorOps_pb2.SetLocation()
        if location.transform is not None:
            self.op.transform.translation.x = location.transform.translation.x
            self.op.transform.translation.y = location.transform.translation.y
            self.op.transform.translation.z = location.transform.translation.z
            self.op.transform.orientation.x = location.transform.orientation.x
            self.op.transform.orientation.y = location.transform.orientation.y
            self.op.transform.orientation.z = location.transform.orientation.z
            self.op.transform.orientation.w = location.transform.orientation.w
        if location.routing_surface is not None:
            self.op.level = location.routing_surface.secondary_id
        if location.parent is not None:
            self.op.parent_id = location.parent.id
        self.op.slot_hash = location.slot_hash
        if location.joint_name_or_hash is not None:
            self.op.joint_name_hash = location.joint_name_hash

    def __repr__(self):
        return standard_repr(self, parent=standard_brief_id_repr(self.op.parent_id), slot_hash=hex(self.op.slot_hash), joint_name_hash=hex(self.op.joint_name_hash), translation=standard_float_tuple_repr(self.op.transform.translation.x, self.op.transform.translation.y, self.op.transform.translation.z), orientation=standard_float_tuple_repr(self.op.transform.orientation.x, self.op.transform.orientation.y, self.op.transform.orientation.z, self.op.transform.orientation.w), level=self.op.level)

    def write(self, msg):
        msg.type = protocol_constants.SET_LOCATION
        msg.data = self.op.SerializeToString()

def create_route_msg_src(route_id, actor, path, start_time, wait_time, track_override=None):
    route_pb = Routing_pb2.Route(id=route_id)
    last_routing_surface_id = None
    for n in path.nodes:
        node_pb = route_pb.nodes.add()
        node_loc = node_pb.location
        (node_loc.translation.x, node_loc.translation.y, node_loc.translation.z) = n.position
        (node_loc.orientation.x, node_loc.orientation.y, node_loc.orientation.z, node_loc.orientation.w) = n.orientation
        node_pb.action = n.action
        node_pb.time = n.time
        node_pb.walkstyle = n.walkstyle
        if n.portal_object_id != 0:
            portal_object = services.object_manager(actor.zone_id).get(n.portal_object_id)
            if portal_object is not None:
                node_pb.portal_object_id = n.portal_object_id
                portal_object.add_portal_events(n.portal_id, actor, n.time, route_pb)
                node_data = portal_object.add_portal_data(n.portal_id, actor, n.walkstyle)
                if node_data is not None:
                    node_pb.node_data.type = node_data.type
                    node_pb.node_data.data = node_data.data
        while last_routing_surface_id is None or last_routing_surface_id != n.routing_surface_id:
            node_pb.routing_surface_id.primary_id = n.routing_surface_id.primary_id
            node_pb.routing_surface_id.secondary_id = n.routing_surface_id.secondary_id
            node_pb.routing_surface_id.type = n.routing_surface_id.type
            last_routing_surface_id = n.routing_surface_id
    for polys in path.nodes.obstacles():
        obstacle_polys_pb = route_pb.obstacle_polygons.add()
        for data in polys:
            poly_pb = obstacle_polys_pb.polygons.add()
            routing_surface_id = data[1]
            poly_pb.routing_surface_id.primary_id = routing_surface_id.primary_id
            poly_pb.routing_surface_id.secondary_id = routing_surface_id.secondary_id
            poly_pb.routing_surface_id.type = routing_surface_id.type
            for p in data[0]:
                point_pb = poly_pb.points.add()
                point_pb.pos.x = p.x
                point_pb.pos.y = p.y
    zone_id = actor.zone_id
    zone = services._zone_manager.get(zone_id)
    route_time = zone.game_clock.monotonic_time() - start_time
    route_pb.time = route_time.in_real_world_seconds()
    ROUTING_TIME_BUFFER_MS = 100
    route_pb.absolute_time_ms = int(zone.game_clock.monotonic_time().absolute_ticks() + ROUTING_TIME_BUFFER_MS + wait_time*1000.0)
    if track_override is not None:
        route_pb.track = track_override
    return route_pb

class RouteUpdate(Op):
    __qualname__ = 'RouteUpdate'
    __slots__ = ('id', 'actor', 'path', 'start_time', 'wait_time', 'track_override')

    def __init__(self, route_id, actor, path, start_time, wait_time, track_override=None):
        super().__init__()
        self.id = route_id
        self.actor = actor
        self.path = path
        self.start_time = start_time
        self.track_override = track_override
        self.wait_time = wait_time

    def __repr__(self):
        return standard_repr(self, self.id)

    def write(self, msg):
        op = create_route_msg_src(self.id, self.actor, self.path, self.start_time, self.wait_time, track_override=self.track_override)
        msg.type = protocol_constants.ROUTE_UPDATE
        msg.data = op.SerializeToString()

class FocusEventAdd(Op):
    __qualname__ = 'FocusEventAdd'

    def __init__(self, event_id, layer, score, source, target, bone, offset, blocking, distance_curve=None, facing_curve=None, flags=0):
        super().__init__()
        self.id = event_id
        self.source = source
        self.target = target
        self.bone = bone
        self.offset = offset
        self.layer = layer
        self.score = score
        self.blocking = blocking
        self.distance_curve = distance_curve
        self.facing_curve = facing_curve
        self.flags = flags

    def __repr__(self):
        return standard_repr(self, self.id)

    def write(self, msg):
        op = Animation_pb2.FocusEvent()
        op.id = self.id
        op.type = Animation_pb2.FocusEvent.FOCUS_ADD
        op.source_id = self.source
        op.target_id = self.target
        op.joint_name_hash = self.bone
        (op.offset.x, op.offset.y, op.offset.z) = self.offset
        op.layer = self.layer
        op.score = self.score
        if self.distance_curve is not None:
            for c in self.distance_curve:
                curve_data = op.distance_curve.add()
                curve_data.input_value = c[0]
                curve_data.output_value = c[1]
        if self.facing_curve is not None:
            for c in self.facing_curve:
                curve_data = op.facing_curve.add()
                curve_data.input_value = c[0]
                curve_data.output_value = c[1]
        if self.blocking:
            msg.type = protocol_constants.FOCUS
        else:
            msg.type = protocol_constants.FOCUS_NON_BLOCKING
        if self.flags != 0:
            op.flags = self.flags
        msg.data = op.SerializeToString()

class FocusEventDelete(Op):
    __qualname__ = 'FocusEventDelete'

    def __init__(self, source_id, event_id, blocking):
        super().__init__()
        self.source_id = source_id
        self.id = event_id
        self.blocking = blocking

    def __repr__(self):
        return standard_repr(self, self.id)

    def write(self, msg):
        op = Animation_pb2.FocusEvent()
        op.source_id = self.source_id
        op.id = self.id
        op.type = Animation_pb2.FocusEvent.FOCUS_DELETE
        if self.blocking:
            msg.type = protocol_constants.FOCUS
        else:
            msg.type = protocol_constants.FOCUS_NON_BLOCKING
        msg.data = op.SerializeToString()

class FocusEventClear(Op):
    __qualname__ = 'FocusEventClear'

    def __init__(self, source_id, blocking):
        super().__init__()
        self.source_id = source_id
        self.blocking = blocking

    def write(self, msg):
        op = Animation_pb2.FocusEvent()
        op.source_id = self.source_id
        op.type = Animation_pb2.FocusEvent.FOCUS_CLEAR
        if self.blocking:
            msg.type = protocol_constants.FOCUS
        else:
            msg.type = protocol_constants.FOCUS_NON_BLOCKING
        msg.data = op.SerializeToString()

class FocusEventModifyScore(Op):
    __qualname__ = 'FocusEventModifyScore'

    def __init__(self, source_id, event_id, score, blocking):
        super().__init__()
        self.source_id = source_id
        self.id = event_id
        self.score = score
        self.blocking = blocking

    def __repr__(self):
        return standard_repr(self, self.id)

    def write(self, msg):
        op = Animation_pb2.FocusEvent()
        op.source_id = self.source_id
        op.id = self.id
        op.score = self.score
        op.type = Animation_pb2.FocusEvent.FOCUS_MODIFY_SCORE
        if self.blocking:
            msg.type = protocol_constants.FOCUS
        else:
            msg.type = protocol_constants.FOCUS_NON_BLOCKING
        msg.data = op.SerializeToString()

class FocusEventForceUpdate(Op):
    __qualname__ = 'FocusEventForceUpdate'

    def __init__(self, source_id, blocking):
        super().__init__()
        self.source_id = source_id
        self.blocking = blocking

    def write(self, msg):
        op = Animation_pb2.FocusEvent()
        op.source_id = self.source_id
        op.type = Animation_pb2.FocusEvent.FOCUS_FORCE_UPDATE
        if self.blocking:
            msg.type = protocol_constants.FOCUS
        else:
            msg.type = protocol_constants.FOCUS_NON_BLOCKING
        msg.data = op.SerializeToString()

class FocusEventDisable(Op):
    __qualname__ = 'FocusEventDisable'

    def __init__(self, source_id, disable, blocking):
        super().__init__()
        self.source_id = source_id
        self.disable = disable
        self.blocking = blocking

    def write(self, msg):
        op = Animation_pb2.FocusEvent()
        op.source_id = self.source_id
        op.flags = self.disable
        op.type = Animation_pb2.FocusEvent.FOCUS_DISABLE
        if self.blocking:
            msg.type = protocol_constants.FOCUS
        else:
            msg.type = protocol_constants.FOCUS_NON_BLOCKING
        msg.data = op.SerializeToString()

class FocusEventPrint(Op):
    __qualname__ = 'FocusEventPrint'

    def __init__(self, source_id):
        super().__init__()
        self.source_id = source_id

    def write(self, msg):
        op = Animation_pb2.FocusEvent()
        op.source_id = self.source_id
        op.type = Animation_pb2.FocusEvent.FOCUS_PRINT
        msg.type = protocol_constants.FOCUS_NON_BLOCKING
        msg.data = op.SerializeToString()

class RouteCancel(Op):
    __qualname__ = 'RouteCancel'

    def __init__(self, route_id, time):
        super().__init__()
        self.id = route_id
        self.time = time

    def __repr__(self):
        return standard_repr(self, self.id)

    def write(self, msg):
        op = DistributorOps_pb2.RouteCancel()
        op.id = self.id
        op.time = self.time
        msg.type = protocol_constants.ROUTE_CANCEL
        msg.data = op.SerializeToString()

class SetModel(Op):
    __qualname__ = 'SetModel'

    def __init__(self, model_with_material_variant):
        super().__init__()
        (self.key, self.variant_id) = model_with_material_variant

    def __repr__(self):
        return standard_repr(self, self.key, self.variant_id)

    def write(self, msg):
        op = DistributorOps_pb2.SetModel()
        op.key.type = self.key.type
        op.key.instance = self.key.instance
        op.key.group = self.key.group
        if self.variant_id is not None:
            op.variant_id = self.variant_id
        else:
            op.variant_id = 0
        msg.type = protocol_constants.SET_MODEL
        msg.data = op.SerializeToString()

class SetRig(Op):
    __qualname__ = 'SetRig'

    def __init__(self, key):
        super().__init__()
        self.key = key

    def __repr__(self):
        return standard_repr(self, self.key)

    def write(self, msg):
        op = DistributorOps_pb2.SetRig()
        op.key.type = self.key.type
        op.key.instance = self.key.instance
        op.key.group = self.key.group
        msg.type = protocol_constants.SET_RIG
        msg.data = op.SerializeToString()

class SetCanLiveDrag(Op):
    __qualname__ = 'SetCanLiveDrag'

    def __init__(self, can_live_drag):
        super().__init__()
        self.can_live_drag = can_live_drag

    def __repr__(self):
        return standard_repr(self, self.can_live_drag)

    def write(self, msg):
        op = DistributorOps_pb2.SetCanLiveDrag()
        op.can_live_drag = self.can_live_drag
        msg.type = protocol_constants.SET_CAN_LIVE_DRAG
        msg.data = op.SerializeToString()

class LiveDragStart(Op):
    __qualname__ = 'LiveDragStart'

    def __init__(self, live_drag_object_id, start_system, valid_drop_target_ids, valid_stack_id, sell_value):
        super().__init__()
        self.live_drag_object_id = live_drag_object_id
        self.start_system = start_system
        self.valid_drop_target_ids = valid_drop_target_ids
        self.valid_stack_id = valid_stack_id
        self.sell_value = sell_value

    def __repr__(self):
        return 'Live Drag Start: live_drag_object: {}, valid targets: {}'.format(self.live_drag_object_id, standard_repr(self.valid_drop_target_ids))

    def write(self, msg):
        op = DistributorOps_pb2.LiveDragStart()
        op.live_drag_object_id = self.live_drag_object_id
        op.drag_start_system = int(self.start_system)
        op.drop_object_ids.extend(self.valid_drop_target_ids)
        op.sell_value = self.sell_value
        if self.valid_stack_id is not None:
            op.stack_id = self.valid_stack_id
        msg.type = protocol_constants.LIVE_DRAG_START
        msg.data = op.SerializeToString()

class LiveDragEnd(Op):
    __qualname__ = 'LiveDragEnd'

    def __init__(self, live_drag_object_id, start_system, end_system, next_stack_object_id):
        super().__init__()
        self.live_drag_object_id = live_drag_object_id
        self.start_system = start_system
        self.end_system = end_system
        self.next_stack_object_id = next_stack_object_id

    def __repr__(self):
        return 'Live Drag End: live_drag_object: {}'.format(self.live_drag_object_id)

    def write(self, msg):
        op = DistributorOps_pb2.LiveDragEnd()
        op.live_drag_object_id = self.live_drag_object_id
        op.drag_start_system = int(self.start_system)
        op.drag_end_system = int(self.end_system)
        if self.next_stack_object_id is not None:
            op.next_drag_object_id = self.next_stack_object_id
        msg.type = protocol_constants.LIVE_DRAG_END
        msg.data = op.SerializeToString()

class LiveDragCancel(Op):
    __qualname__ = 'LiveDragCancel'

    def __init__(self, live_drag_object_id, start_system, end_system):
        super().__init__()
        self.live_drag_object_id = live_drag_object_id
        self.start_system = start_system
        self.end_system = end_system

    def __repr__(self):
        return 'Live Drag Cancel: live_drag_object: {}'.format(self.live_drag_object_id)

    def write(self, msg):
        op = DistributorOps_pb2.LiveDragCancel()
        op.live_drag_object_id = self.live_drag_object_id
        op.drag_start_system = int(self.start_system)
        op.drag_end_system = int(self.end_system)
        msg.type = protocol_constants.LIVE_DRAG_CANCEL
        msg.data = op.SerializeToString()

class SetRelativeLotLocation(Op):
    __qualname__ = 'SetRelativeLotLocation'

    def __init__(self, sim_id, on_active_lot, is_at_home):
        super().__init__()
        self.sim_id = sim_id
        self.on_active_lot = on_active_lot
        self.is_at_home = is_at_home

    def write(self, msg):
        op = ui_ops.SimRelativeLotLocation()
        op.sim_id = self.sim_id
        op.on_active_lot = self.on_active_lot
        op.home_zone_active = self.is_at_home
        msg.type = protocol_constants.SIM_RELATIVE_LOT_LOCATION
        msg.data = op.SerializeToString()

class SetFootprint(Op):
    __qualname__ = 'SetFootprint'

    def __init__(self, key):
        super().__init__()
        self.key = key

    def __repr__(self):
        return standard_repr(self, self.key)

    def write(self, msg):
        op = DistributorOps_pb2.SetFootprint()
        op.key.type = self.key.type
        op.key.instance = self.key.instance
        op.key.group = self.key.group
        msg.type = protocol_constants.SET_FOOTPRINT
        msg.data = op.SerializeToString()

class ResetObject(Op):
    __qualname__ = 'ResetObject'

    def __init__(self, object_id):
        super().__init__()
        self._object_id = object_id

    def __repr__(self):
        return standard_repr(self, self._object_id)

    def write(self, msg):
        op = DistributorOps_pb2.ObjectReset()
        op.object_id = self._object_id
        msg.type = protocol_constants.OBJECT_RESET
        msg.data = op.SerializeToString()

class SetRelatedObjects(Op):
    __qualname__ = 'SetRelatedObjects'

    def __init__(self, related_object_ids=None, target_id=None):
        super().__init__()
        self._related_object_ids = related_object_ids
        self._target_id = target_id

    def __repr__(self):
        return standard_repr(self, self._related_object_ids)

    def write(self, msg):
        op = DistributorOps_pb2.SetRelatedObjects()
        for obj_id in self._related_object_ids:
            op.related_object_ids.append(obj_id)
        op.target_sim_id = self._target_id
        msg.type = protocol_constants.SET_RELATED_OBJECTS
        msg.data = op.SerializeToString()

class UpdateFootprintStatus(Op):
    __qualname__ = 'UpdateFootprintStatus'

    def __init__(self, value):
        super().__init__()
        self.key = value[0]
        self.enabled = value[1]

    def __repr__(self):
        return standard_repr(self, self.key)

    def write(self, msg):
        op = DistributorOps_pb2.UpdateFootprintStatus()
        op.key.type = self.key.type
        op.key.instance = self.key.instance
        op.key.group = self.key.group
        op.enabled = self.enabled
        msg.type = protocol_constants.UPDATE_FOOTPRINT_STATUS
        msg.data = op.SerializeToString()

class SetSlot(Op):
    __qualname__ = 'SetSlot'

    def __init__(self, key):
        super().__init__()
        self.key = key

    def __repr__(self):
        return standard_repr(self, self.key)

    def write(self, msg):
        op = DistributorOps_pb2.SetSlot()
        if self.key is not None:
            op.key.type = self.key.type
            op.key.instance = self.key.instance
            op.key.group = self.key.group
        else:
            op.key.type = 0
            op.key.instance = 0
            op.key.group = 0
        msg.type = protocol_constants.SET_SLOT
        msg.data = op.SerializeToString()

class SetParentType(Op):
    __qualname__ = 'SetParentType'

    def __init__(self, value):
        super().__init__()
        if value is not None:
            self.parent_type = value[0]
            self.parent_location = value[1]
        else:
            self.parent_type = 0
            self.parent_location = 0

    def __repr__(self):
        return standard_repr(self, self.parent_type, self.parent_location)

    def write(self, msg):
        op = DistributorOps_pb2.SetParentType()
        op.parent_type = self.parent_type
        op.parent_location = self.parent_location
        msg.type = protocol_constants.SET_PARENT_TYPE
        msg.data = op.SerializeToString()

class SetScale(Op):
    __qualname__ = 'SetScale'

    def __init__(self, scale):
        super().__init__()
        self.scale = scale

    def __repr__(self):
        return standard_repr(self, self.scale)

    def write(self, msg):
        op = DistributorOps_pb2.SetScale()
        op.scale = self.scale
        msg.type = protocol_constants.SET_SCALE
        msg.data = op.SerializeToString()

class SetTint(Op):
    __qualname__ = 'SetTint'

    def __init__(self, value):
        super().__init__()
        self.tint = value

    def __repr__(self):
        return standard_repr(self, self.tint)

    def write(self, msg):
        op = DistributorOps_pb2.SetTint()
        if self.tint is not None:
            (op.tint.x, op.tint.y, op.tint.z, _) = sims4.color.to_rgba(self.tint)
        else:
            op.tint.x = op.tint.y = op.tint.z = 1.0
        msg.type = protocol_constants.SET_TINT
        msg.data = op.SerializeToString()

class SetOpacity(Op):
    __qualname__ = 'SetOpacity'

    def __init__(self, opacity):
        super().__init__()
        self.opacity = opacity

    def __repr__(self):
        return standard_repr(self, self.opacity)

    def write(self, msg):
        op = DistributorOps_pb2.SetOpacity()
        if self.opacity is not None:
            op.opacity = self.opacity
        else:
            op.opacity = 1.0
        msg.type = protocol_constants.SET_OPACITY
        msg.data = op.SerializeToString()

class SetPregnancyProgress(Op):
    __qualname__ = 'SetPregnancyProgress'

    def __init__(self, pregnancy_progress):
        super().__init__()
        self.pregnancy_progress = pregnancy_progress

    def __repr__(self):
        return standard_repr(self, self.pregnancy_progress)

    def write(self, msg):
        op = DistributorOps_pb2.SetPregnancyProgress()
        if self.pregnancy_progress is not None:
            op.pregnancy_progress = self.pregnancy_progress
        else:
            op.pregnancy_progress = 0.0
        msg.type = protocol_constants.SET_PREGNANCY_PROGRESS
        msg.data = op.SerializeToString()

class SetSinged(Op):
    __qualname__ = 'SetSinged'

    def __init__(self, is_singed):
        super().__init__()
        self.is_singed = is_singed

    def __repr__(self):
        return standard_repr(self, self.is_singed)

    def write(self, msg):
        op = DistributorOps_pb2.SetSinged()
        if self.is_singed is not None:
            op.is_singed = self.is_singed
        else:
            op.is_singed = False
        msg.type = protocol_constants.SET_SINGED
        msg.data = op.SerializeToString()

class SetObjectDefStateIndex(Op):
    __qualname__ = 'SetObjectDefStateIndex'

    def __init__(self, obj_def_state_index):
        super().__init__()
        self.obj_def_state_index = obj_def_state_index

    def __repr__(self):
        return standard_repr(self, self.obj_def_state_index)

    def write(self, msg):
        op = DistributorOps_pb2.SetObjectDefStateIndex()
        op.object_def_state_index = self.obj_def_state_index
        msg.type = protocol_constants.SET_OBJECT_DEF_STATE_INDEX
        msg.data = op.SerializeToString()

class FadeOpacity(Op):
    __qualname__ = 'FadeOpacity'

    def __init__(self, opacity, duration):
        super().__init__()
        self.opacity = opacity
        self.duration = duration

    def __repr__(self):
        return '<FadeOpacity {0}, {1}>'.format(self.opacity, self.duration)

    def write(self, msg):
        op = DistributorOps_pb2.FadeOpacity()
        if self.opacity is None:
            op.target_value = 1
        else:
            op.target_value = self.opacity
        op.duration = self.duration
        msg.type = protocol_constants.FADE_OPACITY
        msg.data = op.SerializeToString()

class SetPaintingState(Op):
    __qualname__ = 'SetPaintingState'

    def __init__(self, painting_state):
        super().__init__()
        self.painting_state = painting_state

    def __repr__(self):
        return '<SetPaintingState {0}>'.format(self.painting_state)

    def write(self, msg):
        op = DistributorOps_pb2.SetPainting()
        if self.painting_state is None:
            op.painting = 0
            op.reveal_level = 0
            op.use_overlay = False
        else:
            op.painting = self.painting_state.texture_id
            op.reveal_level = self.painting_state.reveal_level
            op.use_overlay = self.painting_state.use_overlay
        msg.type = protocol_constants.SET_PAINTING
        msg.data = op.SerializeToString()

class SetLightDimmer(Op):
    __qualname__ = 'SetLightDimmer'

    def __init__(self, dimmer):
        super().__init__()
        self.dimmer = dimmer

    def __repr__(self):
        return standard_repr(self, self.dimmer)

    def write(self, msg):
        op = DistributorOps_pb2.SetLightDimmer()
        if self.dimmer is not None:
            op.dimmer = self.dimmer
        else:
            op.dimmer = 1.0
        msg.type = protocol_constants.SET_LIGHT_DIMMER
        msg.data = op.SerializeToString()

class SetLightColor(Op):
    __qualname__ = 'SetLightColor'

    def __init__(self, color):
        super().__init__()
        self._color = color

    def __repr__(self):
        return standard_repr(self, self._color)

    def write(self, msg):
        op = DistributorOps_pb2.SetLightColor()
        if self._color is not None:
            (op.color.x, op.color.y, op.color.z, _) = sims4.color.to_rgba(self._color)
        msg.type = protocol_constants.SET_LIGHT_COLOR
        msg.data = op.SerializeToString()

class SetSimSleepState(Op):
    __qualname__ = 'SetSimSleepState'

    def __init__(self, sleep):
        super().__init__()
        self.sleep = sleep

    def __repr__(self):
        return standard_repr(self, self.sleep)

    def write(self, msg):
        op = DistributorOps_pb2.SetSimSleep()
        if self.sleep is not None:
            op.sleep = self.sleep
        else:
            op.sleep = False
        msg.type = protocol_constants.SET_SIM_SLEEP
        msg.data = op.SerializeToString()

class SetCensorState(Op):
    __qualname__ = 'SetCensorState'

    def __init__(self, censor_state):
        super().__init__()
        self.censor_state = censor_state

    def __repr__(self):
        return standard_repr(self, self.censor_state)

    def write(self, msg):
        op = DistributorOps_pb2.SetCensorState()
        op.censor_state = self.censor_state
        msg.type = protocol_constants.SET_CENSOR_STATE
        msg.data = op.SerializeToString()

class SetGeometryState(Op):
    __qualname__ = 'SetGeometryState'

    def __init__(self, state_name_hash):
        super().__init__()
        self.state_name_hash = state_name_hash

    def __repr__(self):
        return standard_repr(self, self.state_name_hash)

    def write(self, msg):
        op = DistributorOps_pb2.SetGeometryState()
        if self.state_name_hash is not None:
            op.state_name_hash = self.state_name_hash
        else:
            op.state_name_hash = 0
        msg.type = protocol_constants.SET_GEOMETRY_STATE
        msg.data = op.SerializeToString()

class SetVisibility(Op):
    __qualname__ = 'SetVisibility'

    def __init__(self, value):
        super().__init__()
        if value is not None:
            self.visibility = value.visibility
            self.inherits = value.inherits
            self.enable_drop_shadow = value.enable_drop_shadow
        else:
            self.visibility = True
            self.inherits = None
            self.enable_drop_shadow = False

    def __repr__(self):
        return standard_repr(self, self.visibility, self.inherits, self.enable_drop_shadow)

    def write(self, msg):
        op = DistributorOps_pb2.SetVisibility()
        if self.visibility is not None:
            op.visibility = self.visibility
        else:
            op.visibility = True
        if self.inherits is not None:
            op.inherits = self.inherits
        if self.enable_drop_shadow is not None:
            op.enable_drop_shadow = self.enable_drop_shadow
        else:
            op.enable_drop_shadow = False
        msg.type = protocol_constants.SET_VISIBILITY
        msg.data = op.SerializeToString()

class SetMaterialState(Op):
    __qualname__ = 'SetMaterialState'

    def __init__(self, value):
        super().__init__()
        if value is not None:
            self.state_name_hash = value.state_name_hash
            self.opacity = value.opacity
            self.transition = value.transition
        else:
            self.state_name_hash = 0
            self.opacity = None
            self.transition = None

    def __repr__(self):
        return standard_repr(self, self.state_name_hash)

    def write(self, msg):
        op = DistributorOps_pb2.SetMaterialState()
        if self.state_name_hash is not None:
            op.state_name_hash = self.state_name_hash
        else:
            op.state_name_hash = 0
        if self.opacity is not None:
            op.opacity = self.opacity
        if self.transition is not None:
            op.transition = self.transition
        msg.type = protocol_constants.SET_MATERIAL_STATE
        msg.data = op.SerializeToString()

class SetSortOrder(Op):
    __qualname__ = 'SetSortOrder'

    def __init__(self, sort_order):
        super().__init__()
        self.sort_order = sort_order

    def __repr__(self):
        return standard_repr(self, self.sort_order)

    def write(self, msg):
        op = DistributorOps_pb2.SetSortOrder()
        op.sort_order = self.sort_order
        msg.type = protocol_constants.SET_SORT_ORDER
        msg.data = op.SerializeToString()

class SetMoney(Op):
    __qualname__ = 'SetMoney'

    def __init__(self, amount, vfx_amount, sim, reason):
        super().__init__()
        self.amount = amount
        self.vfx_amount = vfx_amount
        self.sim_id = 0 if sim is None else sim.id
        self.reason = reason

    def __repr__(self):
        return standard_repr(self, self.amount)

    def write(self, msg):
        op = DistributorOps_pb2.SetMoney()
        op.money = self.amount
        op.sim_id = self.sim_id
        op.reason = self.reason
        op.vfx_amount = self.vfx_amount
        msg.type = protocol_constants.SET_MONEY
        msg.data = op.SerializeToString()

class InitializeCollection(Op):
    __qualname__ = 'InitializeCollection'

    def __init__(self, collection_data):
        super().__init__()
        self._collection_data = collection_data

    def __repr__(self):
        return standard_repr(self, self._collection_data)

    def write(self, msg):
        op = DistributorOps_pb2.InitializeCollection()
        for (key, value) in self._collection_data.items():
            with ProtocolBufferRollback(op.household_collections) as collection_data_msg:
                collection_data_msg.collectible_def_id = key
                collection_data_msg.collection_id = value
        msg.type = protocol_constants.COLLECTION_HOUSEHOLD_UPDATE
        msg.data = op.SerializeToString()

class SetInteractable(Op):
    __qualname__ = 'SetInteractable'

    def __init__(self, interactable):
        super().__init__()
        self.interactable = interactable

    def __repr__(self):
        return standard_repr(self, self.interactable)

    def write(self, msg):
        op = DistributorOps_pb2.SetInteractable()
        op.interactable = self.interactable
        msg.type = protocol_constants.SET_INTERACTABLE
        msg.data = op.SerializeToString()

class SetSimName(Op):
    __qualname__ = 'SetSimName'

    def __init__(self, name):
        super().__init__()
        self.name = name

    def __repr__(self):
        return standard_repr(self, self.name)

    def write(self, msg):
        op = DistributorOps_pb2.SetSimName()
        op.first = self.name[0]
        op.last = self.name[1]
        op.persona = self.name[2]
        msg.type = protocol_constants.SET_SIM_NAME
        msg.data = op.SerializeToString()

class SetSkinTone(Op):
    __qualname__ = 'SetSkinTone'

    def __init__(self, skin_tone):
        super().__init__()
        self.skin_tone = skin_tone

    def __repr__(self):
        return standard_repr(self, self.skin_tone)

    def write(self, msg):
        op = DistributorOps_pb2.SetSkinTone()
        op.skin_tone = self.skin_tone
        msg.type = protocol_constants.SET_SKIN_TONE
        msg.data = op.SerializeToString()

class SetBabySkinTone(Op):
    __qualname__ = 'SetBabySkinTone'

    def __init__(self, baby_skin_tone):
        super().__init__()
        self.baby_skin_tone = baby_skin_tone

    def __repr__(self):
        return standard_repr(self, self.baby_skin_tone)

    def write(self, msg):
        op = DistributorOps_pb2.SetBabySkinTone()
        op.baby_skin_tone = self.baby_skin_tone
        msg.type = protocol_constants.SET_BABY_SKIN_TONE
        msg.data = op.SerializeToString()

class SetVoicePitch(Op):
    __qualname__ = 'SetVoicePitch'

    def __init__(self, voice_pitch):
        super().__init__()
        self.voice_pitch = voice_pitch

    def __repr__(self):
        return standard_repr(self, self.voice_pitch)

    def write(self, msg):
        op = DistributorOps_pb2.SetVoicePitch()
        op.voice_pitch = self.voice_pitch
        msg.type = protocol_constants.SET_VOICE_PITCH
        msg.data = op.SerializeToString()

class SetVoiceActor(Op):
    __qualname__ = 'SetVoiceActor'

    def __init__(self, voice_actor):
        super().__init__()
        self.voice_actor = voice_actor

    def __repr__(self):
        return standard_repr(self, self.voice_actor)

    def write(self, msg):
        op = DistributorOps_pb2.SetVoiceActor()
        op.voice_actor = self.voice_actor
        msg.type = protocol_constants.SET_VOICE_ACTOR
        msg.data = op.SerializeToString()

class SetVoiceEffect(Op):
    __qualname__ = 'SetVoiceEffect'

    def __init__(self, voice_effect):
        super().__init__()
        self.voice_effect = voice_effect

    def __repr__(self):
        return standard_repr(self.voice_effect)

    def write(self, msg):
        op = DistributorOps_pb2.SetVoiceEffect()
        op.voice_effect = self.voice_effect
        msg.type = protocol_constants.SET_VOICE_EFFECT
        msg.data = op.SerializeToString()

class SetPhysique(Op):
    __qualname__ = 'SetPhysique'

    def __init__(self, physique):
        super().__init__()
        self.physique = physique

    def __repr__(self):
        return standard_repr(self, self.physique)

    def write(self, msg):
        op = DistributorOps_pb2.SetPhysique()
        op.physique = self.physique
        msg.type = protocol_constants.SET_PHYSIQUE
        msg.data = op.SerializeToString()

class SetFacialAttributes(Op):
    __qualname__ = 'SetFacialAttributes'

    def __init__(self, facial_attributes):
        super().__init__()
        self.facial_attributes = facial_attributes

    def __repr__(self):
        return standard_repr(self, self.facial_attributes)

    def write(self, msg):
        msg.type = protocol_constants.SET_FACIAL_ATTRIBUTES
        msg.data = self.facial_attributes or b''

class SetGeneticData(Op):
    __qualname__ = 'SetGeneticData'

    def __init__(self, genetic_data):
        super().__init__()
        self.genetic_data = genetic_data

    def __repr__(self):
        return standard_repr(self, self.genetic_data)

    def write(self, msg):
        msg.type = protocol_constants.SET_SIM_GENETIC_DATA
        msg.data = self.genetic_data or b''

class SetThumbnail(Op):
    __qualname__ = 'SetThumbnail'

    def __init__(self, key):
        super().__init__()
        self.key = key

    def __repr__(self):
        return standard_repr(self, self.key)

    def write(self, msg):
        op = DistributorOps_pb2.SetThumbnail()
        op.key.type = self.key.type
        op.key.instance = self.key.instance
        op.key.group = self.key.group
        msg.type = protocol_constants.SET_THUMBNAIL
        msg.data = op.SerializeToString()

class SetSimOutfits(Op):
    __qualname__ = 'SetSimOutfits'

    def __init__(self, outfits):
        super().__init__()
        self.outfits = outfits

    def __repr__(self):
        return standard_repr(self, self.outfits)

    def write(self, msg):
        op = DistributorOps_pb2.SetSimOutfits()
        if self.outfits:
            for outfits in self.outfits:
                outfit_message = op.outfits.add()
                outfit_message.outfit_id = outfits['outfit_id']
                outfit_message.sim_id = outfits['sim_id']
                outfit_message.version = 0
                if hasattr(outfit_message, 'type'):
                    outfit_message.type = outfits['type']
                outfit_message.part_ids.extend(outfits['parts'])
                outfit_message.body_types.extend(outfits['body_types'])
                outfit_message.match_hair_style = outfits['match_hair_style']
        msg.type = protocol_constants.SET_SIM_OUTFIT
        msg.data = op.SerializeToString()

class ChangeSimOutfit(Op):
    __qualname__ = 'ChangeSimOutfit'

    def __init__(self, outfitcategory_and_index):
        super().__init__()
        self.outfit_category = outfitcategory_and_index[0]
        self.outfit_index = outfitcategory_and_index[1]

    def __repr__(self):
        return standard_repr(self, self.outfit_category)

    def write(self, msg):
        op = DistributorOps_pb2.ChangeSimOutfit()
        op.type = self.outfit_category
        op.index = self.outfit_index
        msg.type = protocol_constants.CHANGE_SIM_OUTFIT
        msg.data = op.SerializeToString()

class UpdateClientActiveSim(Op):
    __qualname__ = 'UpdateClientActiveSim'

    def __init__(self, active_sim):
        super().__init__()
        if active_sim is not None:
            self._active_sim_id = active_sim.id
        else:
            self._active_sim_id = 0

    def __repr__(self):
        return standard_repr(self, self._active_sim_id)

    def write(self, msg):
        op = Sims_pb2.UpdateClientActiveSim()
        op.active_sim_id = self._active_sim_id
        msg.type = protocol_constants.SET_SIM_ACTIVE
        msg.data = op.SerializeToString()

class TravelSwitchToZone(Op):
    __qualname__ = 'TravelSwitchToZone'

    def __init__(self, travel_info):
        super().__init__()
        self.travel_info = travel_info

    def __repr__(self):
        return standard_repr(self, self.travel_info)

    def write(self, msg):
        op = DistributorOps_pb2.TravelSwitchToZone()
        op.sim_to_visit_id = self.travel_info[0]
        op.household_to_control_id = self.travel_info[1]
        op.zone_id = self.travel_info[2]
        op.world_id = self.travel_info[3]
        msg.type = protocol_constants.TRAVEL_SWITCH_TO_ZONE
        msg.data = op.SerializeToString()

class TravelBringToZone(Op):
    __qualname__ = 'TravelBringToZone'

    def __init__(self, summon_info):
        super().__init__()
        self.summon_info = summon_info

    def __repr__(self):
        return standard_repr(self, self.summon_info)

    def write(self, msg):
        op = DistributorOps_pb2.TravelBringToZone()
        op.sim_to_bring_id = self.summon_info[0]
        op.household_id = self.summon_info[1]
        op.zone_id = self.summon_info[2]
        op.world_id = self.summon_info[3]
        msg.type = protocol_constants.TRAVEL_BRING_TO_ZONE
        msg.data = op.SerializeToString()

class SetFocusScore(Op):
    __qualname__ = 'SetFocusScore'
    OP_TYPE = sims4.hash_util.hash32('focus_score')

    def __init__(self, focus_score):
        super().__init__()
        self.op = DistributorOps_pb2.SetActorData()
        self.op.type = self.OP_TYPE
        if focus_score is not None:
            self.op.data.append(focus_score)

    def write(self, msg):
        msg.type = protocol_constants.SET_ACTOR_DATA
        msg.data = self.op.SerializeToString()

    @property
    def focus_score(self):
        if self.op.data:
            return self.op.data[0]

    def __repr__(self):
        return standard_repr(self, self.focus_score)

class SetFocusCompatibility(Op):
    __qualname__ = 'SetFocusCompatibility'
    OP_TYPE = sims4.hash_util.hash32('focus_compatibility')

    def __init__(self, focus_compatibility):
        super().__init__()
        self.op = DistributorOps_pb2.SetActorData()
        self.op.type = self.OP_TYPE
        if focus_compatibility is not None:
            self.op.data.append(focus_compatibility)

    def write(self, msg):
        msg.type = protocol_constants.SET_ACTOR_DATA
        msg.data = self.op.SerializeToString()

class StartEffect(Op):
    __qualname__ = 'StartEffect'

    def __init__(self, effect_name, bone_name, offset, texture_index, texture_key):
        super().__init__()
        self.effect_name = effect_name
        self.bone_name = bone_name
        self.offset = offset
        self.texture_index = texture_index
        self.texture_key = texture_key

    def __repr__(self):
        return standard_repr(self, self.effect_name)

    def write(self, msg):
        op = DistributorOps_pb2.FxEvent()
        op.event_type = DistributorOps_pb2.FxEvent.EFFECT_START
        op.effect_name = self.effect_name
        op.bone_name = self.bone_name
        op.offset.x = self.offset.x
        op.offset.y = self.offset.y
        op.offset.z = self.offset.z
        op.texture_override.index = self.texture_index
        op.texture_override.key.type = self.texture_key.type
        op.texture_override.key.instance = self.texture_key.instance
        op.texture_override.key.group = self.texture_key.group
        msg.type = protocol_constants.FX
        msg.data = op.SerializeToString()

class StopEffect(Op):
    __qualname__ = 'StopEffect'

    def __init__(self):
        super().__init__()

    def write(self, msg):
        op = DistributorOps_pb2.FxEvent()
        op.event_type = DistributorOps_pb2.FxEvent.EFFECT_STOP
        msg.type = protocol_constants.FX
        msg.data = op.SerializeToString()

class StopVFX(Op):
    __qualname__ = 'StopVFX'

    def __init__(self, target_id, actor_id, stop_type=None):
        super().__init__()
        self._target_id = target_id
        self._actor_id = actor_id
        self._stop_type = stop_type

    def write(self, msg):
        op = protocolbuffers.VFX_pb2.VFXStop()
        op.object_id = self._target_id
        op.actor_id = self._actor_id
        op.transition_type = self._stop_type
        msg.type = protocol_constants.VFX_STOP
        msg.data = op.SerializeToString()

class StopSound(Op):
    __qualname__ = 'StopSound'

    def __init__(self, target_id, channel):
        super().__init__()
        self._target_id = target_id
        self._channel = channel

    def __repr__(self):
        return standard_angle_repr(self, self._channel)

    def write(self, msg):
        op = protocolbuffers.Audio_pb2.SoundStop()
        op.object_id = self._target_id
        op.channel = self._channel
        msg.type = protocol_constants.SOUND_STOP
        msg.data = op.SerializeToString()

class StartArb(Op):
    __qualname__ = 'StartArb'

    def __init__(self, arb):
        super().__init__()
        if arb is not None:
            self._arb_bytes = arb._bytes()
        else:
            self._arb_bytes = None
            sims4.log.error('Animation', 'Creating an empty ARB.')

    def write(self, msg):
        op = Animation_pb2.AnimationRequestBlock()
        if self._arb_bytes is not None:
            op.arb_data = self._arb_bytes
        msg.type = protocol_constants.ARB_INITIAL_UPDATE
        msg.data = op.SerializeToString()

class SetActorType(Op):
    __qualname__ = 'SetActorType'
    OP_TYPE = sims4.hash_util.hash32('actortype')

    def __init__(self, actor_type):
        super().__init__()
        self.op = DistributorOps_pb2.SetActorData()
        self.op.type = self.OP_TYPE
        self.op.data.append(actor_type)

    def write(self, msg):
        msg.type = protocol_constants.SET_ACTOR_DATA
        msg.data = self.op.SerializeToString()

class SetActorStateMachine(Op):
    __qualname__ = 'SetActorStateMachine'
    OP_TYPE = sims4.hash_util.hash32('statemachine')

    def __init__(self, str_name):
        super().__init__()
        self.op = DistributorOps_pb2.SetActorData()
        self.op.type = self.OP_TYPE
        hash_key = sims4.hash_util.hash64(str_name)
        self.op.data.append(hash_key & 4294967295)
        self.op.data.append(hash_key >> 32)

    def write(self, msg):
        msg.type = protocol_constants.SET_ACTOR_DATA
        msg.data = self.op.SerializeToString()

class DisablePendingHeadline(Op):
    __qualname__ = 'DisablePendingHeadline'

    def __init__(self, sim_id, group_id=None, was_canceled=False):
        super().__init__()
        self.sim_id = sim_id
        self.group_id = group_id
        self.was_canceled = was_canceled

    def write(self, msg):
        op = Sims_pb2.DisablePendingInteractionHeadline()
        op.sim_id = self.sim_id
        if self.group_id is not None:
            op.group_id = self.group_id
        op.canceled = self.was_canceled
        msg.type = protocol_constants.DISABLE_PENDING_HEADLINE
        msg.data = op.SerializeToString()

class CancelPendingHeadline(Op):
    __qualname__ = 'CancelPendingHeadline'

    def __init__(self, sim_id):
        super().__init__()
        self.sim_id = sim_id

    def write(self, msg):
        op = Sims_pb2.EnablePendingInteractionHeadline()
        op.sim_id = self.sim_id
        msg.type = protocol_constants.ENABLE_PENDING_HEADLINE
        msg.data = op.SerializeToString()

class SetUiObjectMetadata(SparseMessageOp):
    __qualname__ = 'SetUiObjectMetadata'
    TYPE = protocol_constants.SET_UI_OBJECT_METADATA

class SituationStartOp(GenericCreate):
    __qualname__ = 'SituationStartOp'

    def __init__(self, obj, protocol_msg):
        super().__init__(obj, protocol_msg)

    def write(self, msg):
        msg.type = protocol_constants.SITUATION_START
        msg.data = self.data

class SituationEndOp(Op):
    __qualname__ = 'SituationEndOp'

    def __init__(self, protocol_msg):
        super().__init__()
        self.protocol_msg = protocol_msg

    def write(self, msg):
        msg.type = protocol_constants.SITUATION_END
        msg.data = self.protocol_msg.SerializeToString()

class SituationSimJoinedOp(Op):
    __qualname__ = 'SituationSimJoinedOp'

    def __init__(self, protocol_msg):
        super().__init__()
        self.protocol_msg = protocol_msg

    def write(self, msg):
        msg.type = protocol_constants.SITUATION_SIM_JOINED
        msg.data = self.protocol_msg.SerializeToString()

class SituationSimLeftOp(Op):
    __qualname__ = 'SituationSimLeftOp'

    def __init__(self, protocol_msg):
        super().__init__()
        self.protocol_msg = protocol_msg

    def write(self, msg):
        msg.type = protocol_constants.SITUATION_SIM_LEFT
        msg.data = self.protocol_msg.SerializeToString()

class SituationScoreUpdateOp(Op):
    __qualname__ = 'SituationScoreUpdateOp'

    def __init__(self, protocol_msg):
        super().__init__()
        self.protocol_msg = protocol_msg

    def write(self, msg):
        msg.type = protocol_constants.SITUATION_SCORE_UPDATED
        msg.data = self.protocol_msg.SerializeToString()

class SituationGoalUpdateOp(Op):
    __qualname__ = 'SituationGoalUpdateOp'

    def __init__(self, protocol_msg):
        super().__init__()
        self.protocol_msg = protocol_msg

    def write(self, msg):
        msg.type = protocol_constants.SITUATION_GOALS_UPDATE
        msg.data = self.protocol_msg.SerializeToString()

class VideoSetPlaylistOp(Op):
    __qualname__ = 'VideoSetPlaylistOp'

    def __init__(self, playlist):
        super().__init__()
        self.protocol_msg = playlist.get_protocol_msg()

    def write(self, msg):
        msg.type = protocol_constants.VIDEO_SET_PLAYLIST
        msg.data = self.protocol_msg.SerializeToString()

class HouseholdCreate(GenericCreate):
    __qualname__ = 'HouseholdCreate'

    def __init__(self, obj, *args, is_active=False, **kwargs):
        op = DistributorOps_pb2.HouseholdCreate()
        additional_ops = (distributor.ops.SetMoney(obj.funds.money, False, None, 0),)
        if is_active:
            additional_ops += (distributor.ops.InitializeCollection(obj.get_household_collections()),)
        super().__init__(obj, op, additional_ops=additional_ops, *args, **kwargs)

    def write(self, msg):
        msg.type = protocol_constants.HOUSEHOLD_CREATE
        msg.data = self.data

class HouseholdDelete(Op):
    __qualname__ = 'HouseholdDelete'

    def write(self, msg):
        msg.type = protocol_constants.HOUSEHOLD_DELETE

class SetValue(Op):
    __qualname__ = 'SetValue'

    def __init__(self, value):
        super().__init__()
        self.op = DistributorOps_pb2.SetValue()
        self.op.value = value

    def write(self, msg):
        msg.type = protocol_constants.SET_VALUE
        msg.data = self.op.SerializeToString()

class SetAge(Op):
    __qualname__ = 'SetAge'

    def __init__(self, value):
        super().__init__()
        self.op = DistributorOps_pb2.SetSimAge()
        self.op.age = value

    def write(self, msg):
        msg.type = protocol_constants.SET_SIM_AGE
        msg.data = self.op.SerializeToString()

class SetGender(Op):
    __qualname__ = 'SetGender'

    def __init__(self, value):
        super().__init__()
        self.op = DistributorOps_pb2.SetGender()
        self.op.gender = value

    def write(self, msg):
        msg.type = protocol_constants.SET_SIM_GENDER
        msg.data = self.op.SerializeToString()

class SetPrimaryAspiration(Op):
    __qualname__ = 'SetPrimaryAspiration'

    def __init__(self, aspiration_id):
        super().__init__()
        self.op = DistributorOps_pb2.SetPrimaryAspiration()
        self.op.aspiration_id = aspiration_id

    def write(self, msg):
        msg.type = protocol_constants.SET_PRIMARY_ASPIRATION
        msg.data = self.op.SerializeToString()

class SetWhimComplete(Op):
    __qualname__ = 'SetWhimComplete'

    def __init__(self, whim_guid):
        super().__init__()
        self.op = DistributorOps_pb2.SetWhimComplete()
        self.op.whim_guid64 = whim_guid

    def write(self, msg):
        msg.type = protocol_constants.SET_WHIM_COMPLETE
        msg.data = self.op.SerializeToString()

class SetCurrentWhims(Op):
    __qualname__ = 'SetCurrentWhims'

    def __init__(self, whim_goals):
        super().__init__()
        self.op = DistributorOps_pb2.SetCurrentWhims()
        if whim_goals:
            self.op.whim_goals.extend(whim_goals)

    def write(self, msg):
        msg.type = protocol_constants.SET_CURRENT_WHIMS
        msg.data = self.op.SerializeToString()

class SetWhimBucks(Op):
    __qualname__ = 'SetWhimBucks'

    def __init__(self, whim_bucks, reason):
        super().__init__()
        self.op = DistributorOps_pb2.SetWhimBucks()
        self.op.whim_bucks = whim_bucks
        self.op.reason = reason

    def write(self, msg):
        msg.type = protocol_constants.SET_WHIM_BUCKS
        msg.data = self.op.SerializeToString()

class SetTraits(Op):
    __qualname__ = 'SetTraits'

    def __init__(self, value):
        super().__init__()
        self.op = DistributorOps_pb2.SetTraits()
        self.op.trait_ids.extend(value)

    def write(self, msg):
        msg.type = protocol_constants.SET_TRAITS
        msg.data = self.op.SerializeToString()

class SetDeathType(Op):
    __qualname__ = 'SetDeathType'

    def __init__(self, value):
        super().__init__()
        self.op = DistributorOps_pb2.SetDeathType()
        if value is not None:
            self.op.death_type = value

    def write(self, msg):
        msg.type = protocol_constants.SET_SIM_DEATH_TYPE
        msg.data = self.op.SerializeToString()

class SetAgeProgress(Op):
    __qualname__ = 'SetAgeProgress'

    def __init__(self, value):
        super().__init__()
        self.op = DistributorOps_pb2.SetSimAgeProgress()
        self.op.progress = value

    def write(self, msg):
        msg.type = protocol_constants.SET_SIM_AGE_PROGRESS
        msg.data = self.op.SerializeToString()

class SetSimAgeProgressTooltipData(Op):
    __qualname__ = 'SetSimAgeProgressTooltipData'

    def __init__(self, current_day, ready_to_age_day, days_alive):
        super().__init__()
        self.op = DistributorOps_pb2.SetSimAgeProgressTooltipData()
        self.op.current_day = current_day
        self.op.ready_to_age_day = ready_to_age_day
        self.op.days_alive = days_alive

    def write(self, msg):
        msg.type = protocol_constants.SET_SIM_AGE_PROGRESS_TOOLTIP_DATA
        msg.data = self.op.SerializeToString()

class SetCurrentSkillId(Op):
    __qualname__ = 'SetCurrentSkillId'

    def __init__(self, value):
        super().__init__()
        self.op = DistributorOps_pb2.SetCurrentSkillId()
        self.op.current_skill_id = value

    def write(self, msg):
        msg.type = protocol_constants.SET_SIM_CURRENT_SKILL_ID
        msg.data = self.op.SerializeToString()

class SetGameTime(Op):
    __qualname__ = 'SetGameTime'

    def __init__(self, server_time, monotonic_time, game_time, game_speed, clock_speed, initial_game_time, super_speed):
        super().__init__()
        self.op = Area_pb2.GameTimeCommand()
        self.op.clock_speed = clock_speed
        self.op.game_speed = game_speed
        self.op.server_time = server_time
        self.op.sync_game_time = game_time + initial_game_time
        self.op.monotonic_time = monotonic_time
        self.op.super_speed = super_speed

    def write(self, msg):
        msg.type = protocol_constants.SET_GAME_TIME
        msg.data = self.op.SerializeToString()

class SetCareers(Op):
    __qualname__ = 'SetCareers'

    def __init__(self, careers):
        super().__init__()
        self.op = DistributorOps_pb2.SetCareers()
        if careers:
            for career in careers.values():
                with ProtocolBufferRollback(self.op.careers) as career_op:
                    career.populate_set_career_op(career_op)

    def write(self, msg):
        msg.type = protocol_constants.SET_CAREER
        msg.data = self.op.SerializeToString()

class SetAtWorkInfos(Op):
    __qualname__ = 'SetAtWorkInfos'

    def __init__(self, at_work_infos):
        super().__init__()
        self.op = DistributorOps_pb2.SetAtWorkInfos()
        if at_work_infos:
            self.op.at_work_infos.extend(at_work_infos)

    def write(self, msg):
        msg.type = protocol_constants.SET_AT_WORK_INFO
        msg.data = self.op.SerializeToString()

class SetAccountId(Op):
    __qualname__ = 'SetAccountId'

    def __init__(self, account_id):
        super().__init__()
        self.op = DistributorOps_pb2.SetAccountId()
        self.op.account_id = account_id

    def write(self, msg):
        msg.type = protocol_constants.SET_ACCOUNT_ID
        msg.data = self.op.SerializeToString()

class SetIsNpc(Op):
    __qualname__ = 'SetIsNpc'

    def __init__(self, is_npc):
        super().__init__()
        self.op = DistributorOps_pb2.SetIsNpc()
        self.op.is_npc = is_npc

    def write(self, msg):
        msg.type = protocol_constants.SET_IS_NPC
        msg.data = self.op.SerializeToString()

class SetFirstName(Op):
    __qualname__ = 'SetFirstName'

    def __init__(self, first_name):
        super().__init__()
        self.op = DistributorOps_pb2.SetFirstName()
        self.op.first_name = first_name

    def write(self, msg):
        msg.type = protocol_constants.SET_FIRST_NAME
        msg.data = self.op.SerializeToString()

class SetLastName(Op):
    __qualname__ = 'SetLastName'

    def __init__(self, last_name):
        super().__init__()
        self.op = DistributorOps_pb2.SetLastName()
        self.op.last_name = last_name

    def write(self, msg):
        msg.type = protocol_constants.SET_LAST_NAME
        msg.data = self.op.SerializeToString()

class SetFullNameKey(Op):
    __qualname__ = 'SetFullNameKey'

    def __init__(self, full_name_key):
        super().__init__()
        self.op = DistributorOps_pb2.SetFullNameKey()
        self.op.full_name_key = full_name_key

    def write(self, msg):
        msg.type = protocol_constants.SET_FULL_NAME_KEY
        msg.data = self.op.SerializeToString()

class SetPersona(Op):
    __qualname__ = 'SetPersona'

    def __init__(self, persona):
        super().__init__()
        self.op = DistributorOps_pb2.SetPersona()
        self.op.persona = persona

    def write(self, msg):
        msg.type = protocol_constants.SET_PERSONA
        msg.data = self.op.SerializeToString()

class SetWallsUpOrDown(Op):
    __qualname__ = 'SetWallsUpOrDown'

    def __init__(self, walls_up):
        super().__init__()
        self.op = DistributorOps_pb2.SetWallsUpOrDown()
        self.op.walls_up = walls_up

    def write(self, msg):
        msg.type = protocol_constants.SET_WALLS_UP_OR_DOWN
        msg.data = self.op.SerializeToString()

class InteractionProgressUpdate(Op):
    __qualname__ = 'InteractionProgressUpdate'

    def __init__(self, sim_id, percent, rate_change, interaction_id):
        super().__init__()
        self.op = InteractionOps_pb2.InteractionProgressUpdate()
        self.op.sim_id = sim_id
        self.op.percent = percent
        self.op.rate_change = rate_change
        self.op.interaction_id = interaction_id

    def write(self, msg):
        msg.type = protocol_constants.INTERACTION_PROGRESS_UPDATE
        msg.data = self.op.SerializeToString()

class PreloadSimOutfit(Op):
    __qualname__ = 'PreloadSimOutfit'

    def __init__(self, outfit_category_and_index_list):
        super().__init__()
        self.outfit_category_and_index_list = outfit_category_and_index_list

    def write(self, msg):
        op = DistributorOps_pb2.PreloadSimOutfit()
        for (outfit_category, outfit_index) in self.outfit_category_and_index_list:
            with ProtocolBufferRollback(op.outfits) as outfit:
                outfit.type = outfit_category
                outfit.index = outfit_index
        msg.type = protocol_constants.PRELOAD_SIM_OUTFIT
        msg.data = op.SerializeToString()

class SkillProgressUpdate(Op):
    __qualname__ = 'SkillProgressUpdate'

    def __init__(self, skill_instance_id, change_rate, curr_points):
        super().__init__()
        self.op = Commodities_pb2.SkillProgressUpdate()
        self.op.skill_id = skill_instance_id
        self.op.change_rate = change_rate
        self.op.curr_points = int(curr_points)

    def write(self, msg):
        msg.type = protocol_constants.SIM_SKILL_PROGRESS
        msg.data = self.op.SerializeToString()

class SocialContextUpdate(Op):
    __qualname__ = 'SocialContextUpdate'

    def __init__(self, social_context_bit):
        super().__init__()
        self.op = Sims_pb2.SocialContextUpdate()
        if social_context_bit is not None:
            self.op.bit_id = social_context_bit.guid64

    def write(self, msg):
        msg.type = protocol_constants.SOCIAL_CONTEXT_UPDATE
        msg.data = self.op.SerializeToString()

class RelationshipUpdate(Op):
    __qualname__ = 'RelationshipUpdate'

    def __init__(self, protocol_buffer):
        super().__init__()
        self.protocol_buffer = protocol_buffer

    def write(self, msg):
        msg.type = protocol_constants.SIM_RELATIONSHIP_UPDATE
        msg.data = self.protocol_buffer.SerializeToString()

class SetPhoneSilence(Op):
    __qualname__ = 'SetPhoneSilence'

    def __init__(self, silence):
        super().__init__()
        self.op = DistributorOps_pb2.SetPhoneSilence()
        self.op.silence = silence

    def write(self, msg):
        msg.type = protocol_constants.SET_PHONE_SILENCE
        msg.data = self.op.SerializeToString()

class SetAwayAction(Op):
    __qualname__ = 'SetAwayAction'

    def __init__(self, away_action):
        super().__init__()
        self.op = DistributorOps_pb2.SetAwayAction()
        if away_action is not None and away_action.is_running:
            if away_action.icon is not None:
                self.op.icon.type = away_action.icon.type
                self.op.icon.instance = away_action.icon.instance
                self.op.icon.group = away_action.icon.group
            self.op.tooltip = away_action.tooltip()

    def write(self, msg):
        msg.type = protocol_constants.SET_AWAY_ACTION
        msg.data = self.op.SerializeToString()

class ShowLightColorUI(Op):
    __qualname__ = 'ShowLightColorUI'

    def __init__(self, red, green, blue, intensity, target_id, all_lights):
        super().__init__()
        self._red = red
        self._green = green
        self._blue = blue
        self._intensity = intensity
        self._target_id = target_id
        self._all_lights = all_lights

    def write(self, msg):
        op = ui_ops.LightColorAndIntensity()
        op.red = self._red
        op.green = self._green
        op.blue = self._blue
        op.intensity = self._intensity
        op.target_id = self._target_id
        op.all_lights = self._all_lights
        msg.type = protocol_constants.UI_LIGHT_COLOR_SHOW
        msg.data = op.SerializeToString()

class SetObjectDefinitionId(Op):
    __qualname__ = 'SetObjectDefinitionId'

    def __init__(self, def_id):
        super().__init__()
        self.def_id = def_id

    def __repr__(self):
        return standard_repr(self, self.def_id)

    def write(self, msg):
        op = DistributorOps_pb2.SetObjectDefinitionId()
        op.def_id = self.def_id
        msg.type = protocol_constants.SET_OBJECT_DEFINITION_ID
        msg.data = op.SerializeToString()

class SetTutorialTipSatisfy(Op):
    __qualname__ = 'SetTutorialTipSatisfy'

    def __init__(self, tutorial_tip_id):
        super().__init__()
        self.op = ui_ops.SatisfyTutorialTip()
        self.op.tutorial_tip_id = tutorial_tip_id

    def write(self, msg):
        msg.type = DistributorOps_pb2.Operation.TUTORIAL_TIP_SATISFY
        msg.data = self.op.SerializeToString()

class FocusCamera(Op):
    __qualname__ = 'FocusCamera'

    def __init__(self, id=None, follow_mode=None):
        super().__init__()
        self.op = DistributorOps_pb2.FocusCamera()
        if id is not None:
            self.op.id = id
        if follow_mode is not None:
            self.op.follow_mode = follow_mode

    def write(self, msg):
        msg.type = protocol_constants.FOCUS_CAMERA
        msg.data = self.op.SerializeToString()

    def set_location(self, location):
        self.op.location.x = location.x
        self.op.location.y = location.y
        self.op.location.z = location.z

    def set_position(self, position):
        self.op.position.x = position.x
        self.op.position.y = position.y
        self.op.position.z = position.z

