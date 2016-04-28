from sims4.tuning.tunable import TunableReference
import services
import sims4
with sims4.reload.protected(globals()):
    _terrain_object = None

class TerrainService(sims4.service_manager.Service):
    __qualname__ = 'TerrainService'
    TERRAIN_DEFINITION = TunableReference(description='\n        The definition used to instantiate the Terrain object.\n        ', manager=services.definition_manager(), class_restrictions='Terrain')

    def start(self):
        create_terrain_object()
        return True

    def stop(self):
        destroy_terrain_object()

def terrain_object():
    if _terrain_object is None:
        raise RuntimeError('Attempting to access the terrain object before it is created.')
    return _terrain_object

def create_terrain_object():
    global _terrain_object
    if _terrain_object is None:
        from objects.system import create_script_object
        _terrain_object = create_script_object(TerrainService.TERRAIN_DEFINITION)

def destroy_terrain_object():
    global _terrain_object
    _terrain_object = None

