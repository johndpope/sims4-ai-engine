from distributor.system import Distributor
from distributor.ops import FocusCamera
import services
import sims4.zone_utils
_sim_id = None
_target_position = None
_camera_position = None
_follow_mode = None
_zone_id = None
_household_id = None


def deserialize(client=None):
    global _sim_id, _target_position, _camera_position, _follow_mode, _zone_id
    save_slot_data_msg = services.get_persistence_service(
    ).get_save_slot_proto_buff()
    if save_slot_data_msg is not None and save_slot_data_msg.HasField(
            'gameplay_data'):
        gameplay_data = save_slot_data_msg.gameplay_data
        if gameplay_data.HasField('camera_data'):
            camera_data = save_slot_data_msg.gameplay_data.camera_data
            if camera_data.HasField('target_id'):
                _sim_id = camera_data.target_id
                _target_position = camera_data.target_position
                _camera_position = camera_data.camera_position
                _follow_mode = camera_data.follow_mode
                _zone_id = camera_data.zone_id
                if camera_data.HasField(
                        'household_id') and services.active_lot(
                        ).owner_household_id != camera_data.household_id:
                    return False
                if _follow_mode and services.sim_info_manager().get(
                        _sim_id) is None:
                    _sim_id = None
                    _target_position = None
                    _camera_position = None
                    _follow_mode = None
                    _zone_id = None
                    return False
                if _zone_id == sims4.zone_utils.get_zone_id():
                    op = FocusCamera(id=_sim_id, follow_mode=_follow_mode)
                    op.set_location(_target_position)
                    op.set_position(_camera_position)
                    Distributor.instance().add_op_with_no_owner(op)
                    return True
    _sim_id = None
    _target_position = None
    _camera_position = None
    _follow_mode = None
    _zone_id = None
    return False


def serialize(save_slot_data=None):
    if _sim_id is not None and _household_id is not None:
        camera_data = save_slot_data.gameplay_data.camera_data
        camera_data.target_id = _sim_id
        camera_data.target_position.x = _target_position.x
        camera_data.target_position.y = _target_position.y
        camera_data.target_position.z = _target_position.z
        camera_data.camera_position.x = _camera_position.x
        camera_data.camera_position.y = _camera_position.y
        camera_data.camera_position.z = _camera_position.z
        camera_data.follow_mode = _follow_mode
        camera_data.zone_id = _zone_id
        camera_data.household_id = _household_id


def update(sim_id=None,
           target_position=None,
           camera_position=None,
           follow_mode=None):
    global _sim_id, _target_position, _camera_position, _follow_mode, _zone_id, _household_id
    _sim_id = sim_id
    _target_position = target_position
    _camera_position = camera_position
    _follow_mode = follow_mode
    _zone_id = sims4.zone_utils.get_zone_id()
    _household_id = services.active_lot().owner_household_id


def focus_on_sim(sim=None, follow=True, client=None):
    focus_sim = sim or client.active_sim
    op = FocusCamera(id=focus_sim.id, follow_mode=follow)
    Distributor.instance().add_op_with_no_owner(op)


def focus_on_position(pos, client=None):
    op = FocusCamera()
    op.set_location(pos)
    Distributor.instance().add_op_with_no_owner(op)


def set_to_default():
    op = FocusCamera(id=0)
    Distributor.instance().add_op_with_no_owner(op)
