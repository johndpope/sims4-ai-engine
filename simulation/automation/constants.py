from objects.definition import Definition
from protocolbuffers.Localization_pb2 import LocalizedString
from sims4.localization import TunableLocalizedString
from sims4.tuning.instances import TunedInstanceMetaclass
from sims4.tuning.tunable import TunableList, TunableReference, Tunable, TunableBlock, TunableWallPattern, TunableRailing, TunableStairs, TunableCeilingRail, TunableFloorPattern, TunableFloorTrim, TunableRoofPattern, TunableRoofTrim, TunableStyle, TunableFence, TunableRoof, TunableFrieze
import services
import sims4.commands
interaction_manager = services.get_instance_manager(sims4.resources.Types.INTERACTION)
object_manager = services.definition_manager()

class Constants:
    __qualname__ = 'Constants'

    class LocalizationStrings:
        __qualname__ = 'Constants.LocalizationStrings'
        CHIPS = TunableLocalizedString(description='UI Dialog option for fridge snack')
        COMEDY = TunableLocalizedString(description="UI dialog option for 'comedy' TV channel")
        FRENCH_TOAST = TunableLocalizedString(description="UI Dialog option for 'french toast' fridge crafting option")
        JUICE = TunableLocalizedString(description='UI Dialog option for one-handed potable fridge snack')
        JUICEDRINK2 = TunableLocalizedString(description='UI Dialog option for a specific juicedrink type drink crafting station option')
        MAKE_CHEESECAKE = TunableLocalizedString(description='Recipe interaction name for cheesecake')
        MAKE_FRENCH_TOAST = TunableLocalizedString(description='Recipe interaction name for french toast')
        MAKE_JUICEDRINK_GENERIC = TunableLocalizedString(description='Prototype name for make generic juice-type drink interaction from a crafting station')
        MAKE_JUICEDRINK2 = TunableLocalizedString(description='Recipe interaction name for a specific juicedrink-type drink that can be crafted')
        MAKE_ROAST_CHICKEN = TunableLocalizedString(description='Recipe interaction name for roast chicken')
        ONE_HANDED_DRINK = TunableLocalizedString(description='\n            UI Dialog option for fridge snack.\n            A one-handed drink available to newly created families that is compatible with foods.')
        ONE_HANDED_SNACK = TunableLocalizedString(description='\n            UI Dialog option for fridge snack.\n            A one-handed food available to newly created families that is compatible with drinks.\n            Also pushes the eat at table interaction from the fridge.')
        ROAST_CHICKEN = TunableLocalizedString(description="UI Dialog option for 'roast chicken' fridge crafting option")
        SIMCITY_CHEESECAKE = TunableLocalizedString(description="UI Dialog option for 'cheesecake' fridge crafting option")
        TOGETHER_MODIFIER = TunableLocalizedString(description="\n            Pie Menu Dialog modifier for doing a thing 'Together'.\n            For example, Go Here Together, or Jog Here Together")

    class Interactions:
        __qualname__ = 'Constants.Interactions'
        BARSTOOL_SIT = TunableReference(manager=interaction_manager, description='sit interaction on barstool setup lot object')
        BAR_MAKE_DRINK = TunableReference(manager=interaction_manager, description='interaction used for making drink at bar')
        BAR_MAKE_DRINK_STAGING = TunableReference(manager=interaction_manager, description='staging interaction used for making drink')
        BED_WOOHOO = TunableReference(manager=interaction_manager, description='woohoo interaction on bed')
        CHAT = TunableReference(manager=interaction_manager, description='\n            A supporting interaction that is usually present when two newly introduced sims are having a friendly conversation.\n            Used to verify that sims remain socializing for a short time period after that have been introduced. A test failure will be thrown\n            if the sim is not seen in this interaction a few moments after two sims begin a friendly conversation.\n            ')
        CHEAT_MAKESPOILED = TunableReference(manager=interaction_manager, description='cheat interaction to change the state of a food commodity to spoiled')
        CLEAN_DISH_MICROWAVE = TunableReference(manager=interaction_manager, description='clean up interaction available on microwave object')
        CLEANOUT_SPOILEDFOOD_FROM_SIM = TunableReference(manager=interaction_manager, description="interaction used to clean out the spoiled food from sim's inventory")
        CLEANUP_DISH = TunableReference(manager=interaction_manager, description='clean up interaction on food plate/glass')
        COLLECT_TRASH = TunableReference(manager=interaction_manager, description='interaction used to collect trash from an indoor or outdoor trash can')
        COOK_GOURMET = TunableReference(manager=interaction_manager, description='fridge interaction that generates a dialog box for crafting options')
        COOK_HOMESTYLE = TunableReference(manager=interaction_manager, description='fridge interaction that generates a dialog box for crafting options')
        DRINK_JUICEDRINK_GENERIC = TunableReference(manager=interaction_manager, description='interaction used for drinking juice-type drinks')
        EAT_CHIPS = TunableReference(manager=interaction_manager, description='interaction used for eating food')
        EAT_FRENCH_TOAST = TunableReference(manager=interaction_manager, description='interaction used for eating food')
        EMPTY_MICROWAVE = TunableReference(manager=interaction_manager, description='interaction used to empty the microwave object')
        EMPTY_OVEN = TunableReference(manager=interaction_manager, description='interaction used to empty the oven object')
        EAT_ROAST_CHICKEN = TunableReference(manager=interaction_manager, description='interaction used for eating food')
        EMPTY_TRASH = TunableReference(manager=interaction_manager, description='interaction used for emptying a trash can')
        FRIENDLY_SOCIAL = TunableList(TunableReference(manager=interaction_manager), description='Friendly social interactions, at least one of these should be available at any given time')
        GENERIC_BED_WOOHOO = TunableReference(manager=interaction_manager, description='woohoo interaction')
        GENERIC_COOK = TunableReference(manager=interaction_manager, description='interaction used for making food')
        GO_HERE = TunableReference(manager=interaction_manager, description='terrain interaction used to make sim go to a location')
        GRAB_A_SNACK = TunableReference(manager=interaction_manager, description='interaction used on fridge to generate basic food items')
        GRAB_ROAST_CHICKEN_PLATE = TunableReference(manager=interaction_manager, description='interaction used on a multiserving object to generate a single-serving object')
        INTRODUCE = TunableReference(manager=interaction_manager, description='a friendly interaction that should be available even for two sims that do not know each other')
        KICK_OVER_OUTDOOR = TunableReference(manager=interaction_manager, description='interaction used for kicking an outdoor trash can')
        MAKE_FOOD_STAGING_BASIC = TunableReference(manager=interaction_manager, description='interaction used for making food')
        MAKE_FRENCH_TOAST = TunableReference(manager=interaction_manager, description='interaction used for making food')
        MAKE_ROAST_CHICKEN_COUNTER = TunableReference(manager=interaction_manager, description='interaction used for making food')
        NAP_SOFA = TunableReference(manager=interaction_manager, description='interaction on a sofa that satisfies energy motive')
        NAP_BED = TunableReference(manager=interaction_manager, description='interaction on a bed that satisfies energy motive')
        PICKUP_OUTDOOR = TunableReference(manager=interaction_manager, description='interaction used to pickup an outdoor trash can that is lying in the ground after being kicked')
        PLACE_IN_WORLD = TunableReference(manager=interaction_manager, description='Interaction used on sim inventory objects to place object in world')
        PLAY_IN_TRASH_PILE = TunableReference(manager=interaction_manager, description='Interaction used for playing in a trash pile')
        PRACTICE_SPEAKING = TunableReference(manager=interaction_manager, description='Interaction used on a mirror object that solves for Social motive')
        PUT_AWAY = TunableReference(manager=interaction_manager, description="Interaction used on (non-sim) object to place object in object's inventory")
        PUT_IN_INVENTORY = TunableReference(manager=interaction_manager, description="Interaction used on object to place object in sim's inventory")
        REAPER_NOMORE_WORK = TunableReference(manager=interaction_manager, description='Interaction indicates that reaper has no more work after finalizing dead sim')
        REAPER_INSPECT = TunableReference(manager=interaction_manager, description='Interaction indicates that reaper has started inspecting the dead sim')
        RESET_OBJECT = TunableReference(manager=interaction_manager, description='Debug Interaction (shift+click) used to reset objects and sims')
        RUMMAGEFORFOOD_OUTDOOR = TunableReference(manager=interaction_manager, description='Interaction used to rummage for food from an outdoor trash can')
        SETUP_LOT = TunableReference(manager=interaction_manager, description='Debug terrain interaction (shift+click) used to spawn debug b/b objects')
        SIT_CHAIR = TunableReference(manager=interaction_manager, description='interaction used to make sim sit in a chair')
        SIT_PASSIVE = TunableReference(manager=interaction_manager, description='passive interaction used when sim is sitting')
        SLEEP_BED = TunableReference(manager=interaction_manager, description='interaction on a bed that solves for energy')
        STOMP_TRASH_PILE = TunableReference(manager=interaction_manager, description='interaction on a trash pile for stomping')
        TAKE_SHOWER = TunableReference(manager=interaction_manager, description='Interaction used on shower object that solves for hygeine motive')
        TRASH_SALVAGE_SCAVENGE = TunableReference(manager=interaction_manager, description='interaction used to salvage a trash pile')
        TRASHCAN_INDOOR_THROW_AWAY = TunableReference(manager=interaction_manager, description='Interaction used on an indoor trash can to throw away trash to an outdoor trash can')
        TURN_OFF_TV = TunableReference(manager=interaction_manager, description='Interaction used to turn off tv object')
        WASH_DISH = TunableReference(manager=interaction_manager, description='Interaction used to wash dirty dish object')
        WATCH_TV = TunableList(TunableReference(manager=interaction_manager), description='Interaction used on TV object that generates a dialogbox for channel options and solves for fun motive')
        USE_TOILET = TunableReference(manager=interaction_manager, description='Gender-nonspecfic interaction used on toilet object that solves for bladder motive')
        WATCH_COMEDY = TunableReference(manager=interaction_manager, description='interaction used for watching comedy on TV')

    class ObjectDefinitions:
        __qualname__ = 'Constants.ObjectDefinitions'
        BAKE_PAN = TunableReference(manager=object_manager, description='a food baking pan block model object slots into stove')
        BAR = TunableReference(manager=object_manager, description='bar created by setup lot cheat')
        CAKE_BAKE_PAN = TunableReference(manager=object_manager, description='a cake baking pan object created during make_cheesecake interaction')
        CHAIR = TunableReference(manager=object_manager, description='Seat object created by setup lot cheat, 4 of these are placed around the dining table')
        CHEESECAKE = TunableReference(manager=object_manager, description='edible craftable object')
        CHIPS = TunableReference(manager=object_manager, description='edible object that can be placed in the world')
        COUNTER = TunableReference(manager=object_manager, description='created by setup lot cheat')
        DECO_LARGE_SLOT = TunableReference(manager=object_manager, description='A decorative object requiring a large slot')
        DECO_MEDIUM_SLOT = TunableReference(manager=object_manager, description='A decorative object requiring a medium slot')
        DECO_SMALL_SLOT = TunableReference(manager=object_manager, description='A decorative object requiring a small slot')
        DIRTY_DISH = TunableReference(manager=object_manager, description='Dirty dish object generated when cleaning out spoiled food')
        DOOR = TunableReference(manager=object_manager, description='wall-placable object that creates a portal allowing sim to walk through the wall')
        DOUBLE_BED = TunableReference(manager=object_manager, description='energy-fulfilling woohoo-compatible object created by setup lot cheat')
        EMPTY_GLASS = TunableReference(manager=object_manager, description='A drinking tumbler object that is empty')
        FRENCH_TOAST = TunableReference(manager=object_manager, description='edible single-serving craftable object')
        FRIDGE = TunableReference(manager=object_manager, description='food storage device created by setup lot cheat')
        FRY_PAN = TunableReference(manager=object_manager, description='a food fry pan block model object slots onto stove')
        HIGH_WALL_PAINTING = TunableReference(manager=object_manager, description='a painting that can be height adjusted on a wall')
        INDOOR_TRASHCAN = TunableReference(manager=object_manager, description='an indoor trash can object')
        JUICE = TunableReference(manager=object_manager, description='JuiceDrink-type cheat-spawnable craftable object compatible with sim inventory and fridge inventory')
        JUICEDRINK2 = TunableReference(manager=object_manager, description='JuiceDrink-type crafted object, requires bartending skill to create, craftable at bar')
        MICROWAVE = TunableReference(manager=object_manager, description='A Schmapple microwave object')
        MICROWAVE_DINNER = TunableReference(manager=object_manager, description='A food plate object created by cooking a microwave dinner')
        MIRROR_FLOOR = TunableReference(manager=object_manager, description='mirror created by setup lot cheat, placed on the floor')
        MIRROR_WALL = TunableReference(manager=object_manager, description='mirror that can be hung on a wall')
        OUTDOOR_TRASHCAN = TunableReference(manager=object_manager, description='An outdoor trash can')
        ROAST_CHICKEN = TunableReference(manager=object_manager, description='edible multiserving object, spawns single-serving objects')
        ROAST_CHICKEN_PLATE = TunableReference(manager=object_manager, description='edible single-serving craftable object')
        ROAST_CHICKEN_TRAY = TunableReference(manager=object_manager, description='transitional craftable object')
        RUMMAGED_MACNCHEESE_FOODPLATE = TunableReference(manager=object_manager, description='mac n cheese foodplate created by rummage interaction on outdoor trash can')
        RUMMAGED_OATMEAL_FOODPLATE = TunableReference(manager=object_manager, description='oatmeal foodplate created by rummage interaction on outdoor trash can')
        RUMMAGED_SALADGARDEN_FOODPLATE = TunableReference(manager=object_manager, description='salad garden foodplate created by rummage interaction on outdoor trash can')
        SCYTHE = TunableReference(manager=object_manager, description="Death's scythe")
        SHOWER = TunableReference(manager=object_manager, description='Hygeine-fulfilling object created by setup lot cheat')
        SIM = TunableReference(manager=object_manager, description='sim object')
        SINK = TunableReference(manager=object_manager, description='Bathroom sink object created by setup lot cheat')
        SOFA = TunableReference(manager=object_manager, description='Multi-seat seatable object created by setup lot cheat')
        STOOL = TunableReference(manager=object_manager, description='Single-seat object created by setup lot cheat')
        STOVE = TunableReference(manager=object_manager, description='a stove object created by the setup lot cheat')
        TABLE = TunableReference(manager=object_manager, description='Dining table object created by setup lot cheat')
        TABLE_SMALL_SLOT = TunableReference(manager=object_manager, description='A table with a small slot')
        TOILET = TunableReference(manager=object_manager, description='Bladder-fulfilling seatable object created by setup lot cheat')
        TOMBSTONE = TunableReference(manager=object_manager, description='A tombstone for a dead sim')
        TRASH_PILE = TunableReference(manager=object_manager, description='A trash pile')
        TRASH_PILE_SCAVENGE = TunableReference(manager=object_manager, description='A trash pile that can be scavenged for parts')
        TV = TunableReference(manager=object_manager, description='Entertainment-fulfilling chair-compatible object created by setup lot cheat')
        URN = TunableReference(manager=object_manager, description='An urn holding the ashes of a dead sim')
        WALL_LIGHT = TunableReference(manager=object_manager, description='A wall sconce light')

    class ResourceIds:
        __qualname__ = 'Constants.ResourceIds'
        BLK_FENCE_AND_CEILING_RAIL = TunableBlock(description='Build/buy block product type, has fence railing wall facet types and ceiling friezes')
        BLK_HEXAGON_3x3 = TunableBlock(description='Build/buy block product type, hexagonal 3x3 block with diagonal walls on the corners')
        BLK_L_SHAPE = TunableBlock(description='L-shaped block used for build/buy block placement and manipulation tests')
        BLK_RIGHT_ROUNDED_3x5 = TunableBlock(description='3x5 block with a flat left side and rounded right side, with a single unit wide non-rounded wall segment between the two rounded sides')
        BLK_ROUNDED_LARGE = TunableBlock(description='7x7 rounded deck')
        BLK_ROUNDED_SMALL = TunableBlock(description='3x3 rounded deck')
        BLK_SQUARE_DECK = TunableBlock(description='Build/buy block product type, outdoor block with fence railing wall facet types')
        BLK_SQUARE_ROOM_3x3 = TunableBlock(description='Build/Buy block product type, 3x3 plain square block with no automatic doors or windows')
        BLK_TRIANGLE_TR_2x2 = TunableBlock(description='Build/Buy block product type, 2x2 block with flat left and bottom sides and a diagonal top-right side')
        DROP_WALL_PRODUCT1 = TunableWallPattern(description='Generic stair drop wall product used for build/buy tests')
        DROP_WALL_PRODUCT2 = TunableWallPattern(description='Generic stair drop wall type, should be disctinct from DROP_WALL_PRODUCT1')
        RAILING_PRODUCT1 = TunableRailing(description='Generic stair railing type used for build/buy tests')
        RAILING_PRODUCT2 = TunableRailing(description='Generic stair railing type, should be distinct from railing defined in RAILING_PRODUCT1')
        ROOF_PATTERN_DEFAULT = TunableRoof(description='Roof pattern used for build/buy tests')
        STAIR_PRODUCT1 = TunableStairs(description='Generic stair type used for stair functionality testing')
        STAIR_PRODUCT2 = TunableStairs(description='Generic stair type, visually distinct from STAIR_PRODUCT1')
        STYLE1 = TunableStyle(description='Build/buy style used to verify stlye change functionality. Should be different from style defined in STYLE2')
        STYLE1_FENCE_TYPE = TunableFence(description='fence type used by style defined in STYLE1')
        STYLE1_INNER_WALL_PATTERN = TunableWallPattern(description='inner wall pattern used by style defined in STYLE1')
        STYLE1_OUTER_WALL_PATTERN = TunableWallPattern(description='outer wall pattern used by style defined in STYLE1')
        STYLE2 = TunableStyle(description='Build/buy style used to verify stlye change functionality. Should be different from style defined in STYLE1')
        STYLE2_INNER_WALL_PATTERN = TunableWallPattern(description='inner wall pattern used by style defined in STYLE2')
        STYLE2_OUTER_WALL_PATTERN = TunableWallPattern(description='outer wall pattern used by style defined in STYLE2')
        FRIEZE_PRODUCT1 = TunableFrieze(description='frieze product used by STYLE1')
        FRIEZE_PRODUCT2 = TunableFrieze(description='frieze product different from product defined in STYLE1')
        FENCE_TYPE2 = TunableFence(description='fence type different from type defined in STYLE1')
        INNER_WALL_PATTERN2 = TunableWallPattern(description='inner wall pattern different from pattern defined in STYLE1')
        OUTER_WALL_PATTERN2 = TunableWallPattern(description='outer wall pattern different from pattern defined in STYLE1')
        CEILING_RAIL2 = TunableCeilingRail(description='ceiling rail different from product defined in STYLE1')
        DECK_FLOOR_PATTERN2 = TunableFloorPattern(description='deck floor pattern different from pattern defined in STYLE1')
        INNER_FLOOR_PATTERN2 = TunableFloorPattern(description='inner floor pattern different from pattern defined in STYLE1')
        FLOOR_TRIM2 = TunableFloorTrim(description='floor trim different from trim defined in STYLE1')
        ROOF_TRIM2 = TunableRoofTrim(description='roof eave trim different from trim defined in STYLE1')
        ROOF_PATTERN2 = TunableRoofPattern(description='Roof pattern different from pattern defined in STYLE1')

    class Misc:
        __qualname__ = 'Constants.Misc'
        AUTOMATION_VERSION = Tunable(int, default=1, description='\n            This value is read by the automated test script and used to determine which test behavior should be used.\n            In general, this value should be updated whenever game behavior that the automated test relies on is changed.\n            For usage info, please see http://maxisweb/sims4/index.php?title=Automation_Dependency_Versioning_System\n            ')

IGNORED_ATTRIBUTES = ['MODULE_TUNABLES']
prefix_map = {Constants.LocalizationStrings: 'LOCSTR', Constants.Interactions: 'CLASSN', Constants.ObjectDefinitions: 'OBJ', Constants.Misc: 'MISC', Constants.ResourceIds: 'RESOURCE'}

@sims4.commands.Command('qa.automation.get_constants', command_type=sims4.commands.CommandType.Automation)
def get_constants(_connection=None):
    sims4.commands.automation_output('[ddConstants]AutomationConstants; Data:Begin', _connection)
    for group in prefix_map:
        for attribute in dir(group):
            while not attribute in IGNORED_ATTRIBUTES:
                if attribute.startswith('__'):
                    pass
                original_value = getattr(group, attribute)
                list_values = (original_value,) if not isinstance(original_value, tuple) else original_value
                if not list_values:
                    pass
                num_values = len(list_values)
                if num_values == 0:
                    pass
                string_value = 'Key:{}, NumItems:{}'.format(attribute, num_values)
                for (idx, raw_value) in enumerate(list_values):
                    if isinstance(raw_value, (int, str, float, bool)) or raw_value is None:
                        string_value += ', Value{}:{}'.format(idx, raw_value)
                    elif isinstance(raw_value, LocalizedString):
                        string_value += ', Value{}:{}'.format(idx, raw_value.hash)
                    elif isinstance(raw_value, Definition):
                        string_value += ', Value{}:{}'.format(idx, raw_value.definition.id)
                    elif isinstance(raw_value, TunedInstanceMetaclass):
                        string_value += ', ClassName{}:{}'.format(idx, raw_value.__name__)
                        if hasattr(raw_value, 'display_name') and raw_value.display_name is not None:
                            string_value += ', DisplayName{}:{}'.format(idx, raw_value.display_name._string_id)
                        display_name_overrides = getattr(raw_value, 'display_name_overrides')
                        if display_name_overrides is not None:
                            display_name_overrides = list(display_name_overrides.get_display_names_gen())
                        else:
                            display_name_overrides = ()
                        string_value += ', NumOverrides{}:{}'.format(idx, len(display_name_overrides))
                        for (override_idx, override) in enumerate(display_name_overrides):
                            string_value += ', OverrideName{}_{}:{}'.format(idx, override_idx, override._string_id)
                    else:
                        string_value += ', Value{}:UNKNOWN_DATA_TYPE_{}'.format(idx, type(raw_value).__name__)
                sims4.commands.automation_output('[ddConstants]AutomationConstants; Data:{}, {}'.format(prefix_map[group], string_value), _connection)
    sims4.commands.automation_output('[ddConstants]AutomationConstants; Data:End', _connection)

