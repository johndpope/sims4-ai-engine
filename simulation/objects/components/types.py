from collections import namedtuple
import objects.components
component_name_type = namedtuple('component_name_type', 'class_attr instance_attr')
ANIMATION_COMPONENT = component_name_type('Animation', 'animation_component')
AUDIO_COMPONENT = component_name_type('Audio', 'audio_component')
EFFECTS_COMPONENT = component_name_type('Effects', 'effects_component')
FOOTPRINT_COMPONENT = component_name_type('Footprint', 'footprint_component')
GAMEPLAY_COMPONENT = component_name_type('Gameplay', 'gameplay_component')
LIVE_DRAG_COMPONENT = component_name_type('LiveDrag', 'live_drag_component')
POSITION_COMPONENT = component_name_type('Position', 'position_component')
RENDER_COMPONENT = component_name_type('Render', 'render_component')
ROUTING_COMPONENT = component_name_type('Routing', 'routing_component')
SIM_COMPONENT = component_name_type('Sim', 'sim_component')
AFFORDANCE_TUNING_COMPONENT = component_name_type('AffordanceTuning', 'affordancetuning_component')
AUTONOMY_COMPONENT = component_name_type('Autonomy', 'autonomy_component')
BUFF_COMPONENT = component_name_type('Buffs', 'buffs_component')
CANVAS_COMPONENT = component_name_type('Canvas', 'canvas_component')
CARRYABLE_COMPONENT = component_name_type('Carryable', 'carryable_component')
CHANNEL_COMPONENT = component_name_type('Channel', 'channel_component')
CENSOR_GRID_COMPONENT = component_name_type('CensorGrid', 'censorgrid_component')
COLLECTABLE_COMPONENT = component_name_type('CollectableComponent', 'collectable_component')
CONSUMABLE_COMPONENT = component_name_type('ConsumableComponent', 'consumable_component')
CRAFTING_COMPONENT = component_name_type('Crafting', 'crafting_component')
CRAFTING_STATION_COMPONENT = component_name_type('CraftingStationComponent', 'craftingstation_component')
ENVIRONMENT_SCORE_COMPONENT = component_name_type('EnvironmentScoreComponent', 'environmentscore_component')
FLOWING_PUDDLE_COMPONENT = component_name_type('FlowingPuddle', 'flowingpuddle_component')
GAME_COMPONENT = component_name_type('Game', 'game_component')
GARDENING_COMPONENT = component_name_type('Gardening', 'gardening_component')
IDLE_COMPONENT = component_name_type('Idle', 'idle_component')
INVENTORY_COMPONENT = component_name_type('Inventory', 'inventory_component')
INVENTORY_ITEM_COMPONENT = component_name_type('InventoryItem', 'inventoryitem_component')
LIGHTING_COMPONENT = component_name_type('Lighting', 'lighting_component')
LINE_OF_SIGHT_COMPONENT = component_name_type('LineOfSight', 'lineofsight_component')
LIVE_DRAG_TARGET_COMPONENT = component_name_type('LiveDragTarget', 'live_drag_target_component')
NAME_COMPONENT = component_name_type('Name', 'name_component')
OBJECT_AGE_COMPONENT = component_name_type('ObjectAge', 'objectage_component')
OBJECT_RELATIONSHIP_COMPONENT = component_name_type('ObjectRelationship', 'objectrelationship_component')
OBJECT_TELEPORTATION_COMPONENT = component_name_type('ObjectTeleportation', 'objectteleportation_component')
OWNABLE_COMPONENT = component_name_type('Ownable', 'ownable_component')
PROXIMITY_COMPONENT = component_name_type('Proximity', 'proximity_component')
SLOT_COMPONENT = component_name_type('Slot', 'slot_component')
SPAWNER_COMPONENT = component_name_type('Spawner', 'spawner_component')
STATE_COMPONENT = component_name_type('State', 'state_component')
STATISTIC_COMPONENT = component_name_type('Statistic', 'statistic_component')
STORED_SIM_INFO_COMPONENT = component_name_type('StoredSimInfo', 'storedsiminfo_component')
TIME_OF_DAY_COMPONENT = component_name_type('TimeOfDay', 'timeofday_component')
TOOLTIP_COMPONENT = component_name_type('Tooltip', 'tooltip_component')
TOPIC_COMPONENT = component_name_type('Topic', 'topic_component')
VIDEO_COMPONENT = component_name_type('Video', 'video_component')
WELCOME_COMPONENT = component_name_type('Welcome', 'welcome_component')
FISHING_LOCATION_COMPONENT = component_name_type('FishingLocation', 'fishing_location_component')
EXAMPLE_COMPONENT = component_name_type('Example', 'example_component')

class NativeComponent(objects.components.Component, use_owner=False):
    __qualname__ = 'NativeComponent'

    @classmethod
    def create_component(cls, owner):
        return cls(owner)

    @classmethod
    def has_server_component(cls):
        return True

class ClientOnlyComponent(NativeComponent):
    __qualname__ = 'ClientOnlyComponent'

    @classmethod
    def has_server_component(cls):
        return False

class PositionComponent(ClientOnlyComponent, component_name=POSITION_COMPONENT, key=1578750580):
    __qualname__ = 'PositionComponent'

class RenderComponent(ClientOnlyComponent, component_name=RENDER_COMPONENT, key=573464449):
    __qualname__ = 'RenderComponent'

class AnimationComponent(ClientOnlyComponent, component_name=ANIMATION_COMPONENT, key=3994535597):
    __qualname__ = 'AnimationComponent'

class RoutingComponent(ClientOnlyComponent, component_name=ROUTING_COMPONENT, key=2561111181):
    __qualname__ = 'RoutingComponent'

class SimComponent(ClientOnlyComponent, component_name=SIM_COMPONENT, key=577793786):
    __qualname__ = 'SimComponent'

class AudioComponent(ClientOnlyComponent, component_name=AUDIO_COMPONENT, key=1069811801):
    __qualname__ = 'AudioComponent'

class EffectsComponent(ClientOnlyComponent, component_name=EFFECTS_COMPONENT, key=1942696649):
    __qualname__ = 'EffectsComponent'

class GameplayComponent(ClientOnlyComponent, component_name=GAMEPLAY_COMPONENT, key=89505537):
    __qualname__ = 'GameplayComponent'

