from objects.components.types import LIGHTING_COMPONENT
import services
import sims4
from build_buy import get_all_objects_with_flags_gen, BuyCategory
logger = sims4.log.Logger('LightingCommands')

@sims4.commands.Command('lighting.set_color_and_intensity', command_type=sims4.commands.CommandType.Live)
def set_color_and_intensity(r:int=None, g:int=None, b:int=None, intensity:float=1.0, target_id:int=None, all_lights:bool=False, _connection=None):
    color = sims4.color.from_rgba_as_int(r, g, b, 1.0)
    if all_lights:
        for obj in get_all_objects_with_flags_gen(services.object_manager().get_all(), BuyCategory.LIGHTING):
            obj.set_user_intensity_override(intensity)
            obj.set_light_color(color)
    else:
        if not target_id:
            sims4.commands.output('Must specify a target or all_light = True', _connection)
            return False
        target = services.object_manager().get(target_id)
        if target is None:
            sims4.commands.output("Can't find the specified target_id: {}".format(target_id), _connection)
            return False
        if not target.has_component(LIGHTING_COMPONENT):
            sims4.commands.output("Trying to set the light color and intensity on an object that doesn't have a lighting component: {}".format(target), _connection)
            return False
        target.set_user_intensity_override(intensity)
        target.set_light_color(color)
    return True

