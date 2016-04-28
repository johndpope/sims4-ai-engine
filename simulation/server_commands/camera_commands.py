import camera
import sims4.commands
import sims4.math

@sims4.commands.Command('update.camera.information', command_type=sims4.commands.CommandType.Live)
def update_camera_information(sim_id:int=None, target_x:float=None, target_y:float=None, target_z:float=None, camera_x:float=None, camera_y:float=None, camera_z:float=None, follow_mode:bool=None, _connection=None):
    camera.update(sim_id=sim_id, target_position=sims4.math.Vector3(target_x, target_y, target_z), camera_position=sims4.math.Vector3(camera_x, camera_y, camera_z), follow_mode=follow_mode)

