import enum
import event_testing
from interactions import ParticipantType
from interactions.inventory_loot import InventoryLoot
from interactions.money_payout import MoneyChange
from interactions.utils.loot import LootActions
from interactions.utils.loot_ops import CollectibleShelveItem, StateChangeLootOp
from sims4.tuning.tunable import TunableVariant, TunableList
from statistics.statistic_ops import TunableStatisticChange
from ui.ui_dialog import UiDialogOkCancel

class LiveDragTuning:
    __qualname__ = 'LiveDragTuning'
    LIVE_DRAG_SELL_DIALOG = UiDialogOkCancel.TunableFactory(description='\n        The dialog to show when the user tries to sell an object via Live Drag.\n        ')
    LIVE_DRAG_SELL_STACK_DIALOG = UiDialogOkCancel.TunableFactory(description='\n        The dialog to show when the user tries to sell a stack via Live Drag.\n        ')

class LiveDragState(enum.Int, export=False):
    __qualname__ = 'LiveDragState'
    NOT_LIVE_DRAGGING = Ellipsis
    LIVE_DRAGGING = Ellipsis

class LiveDragLocation(enum.Int, export=False):
    __qualname__ = 'LiveDragLocation'
    INVALID = 0
    GAMEPLAY_UI = 1
    BUILD_BUY = 2
    GAMEPLAY_SCRIPT = 3

class TunableLiveDragTestVariant(TunableVariant):
    __qualname__ = 'TunableLiveDragTestVariant'

    def __init__(self, description='A single tunable test for Live Dragged objects and their potential targets.', test_excluded=(), **kwargs):
        super().__init__(description=description, state=event_testing.test_variants.TunableStateTest(locked_args={'tooltip': None}), statistic=event_testing.test_variants.TunableStatThresholdTest(locked_args={'tooltip': None}), **kwargs)

class TunableLiveDragTestSet(event_testing.tests.TestListLoadingMixin):
    __qualname__ = 'TunableLiveDragTestSet'
    DEFAULT_LIST = event_testing.tests.TestList()

    def __init__(self, description=None, **kwargs):
        if description is None:
            description = 'A list of tests.  All tests must succeed to pass the TestSet.'
        super().__init__(description=description, tunable=TunableLiveDragTestVariant(), **kwargs)

class LiveDragLootActions(LootActions):
    __qualname__ = 'LiveDragLootActions'
    INSTANCE_TUNABLES = {'loot_actions': TunableList(TunableVariant(statistics=TunableStatisticChange(locked_args={'advertise': False, 'chance': 1, 'tests': None}, include_relationship_ops=False), collectible_shelve_item=CollectibleShelveItem.TunableFactory(), inventory_loot=InventoryLoot.TunableFactory(subject_participant_type_options={'description': '\n                            The participant type who has the inventory that the\n                            object goes into during this loot.\n                            ', 'optional': False}, target_participant_type_options={'description': '\n                            The participant type of the object which gets to\n                            switch inventories in the loot.\n                            ', 'default_participant': ParticipantType.LiveDragActor}), state_change=StateChangeLootOp.TunableFactory(), money_loot=MoneyChange.TunableFactory()))}

    def __iter__(self):
        return iter(self.loot_actions)

