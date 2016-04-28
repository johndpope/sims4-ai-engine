from protocolbuffers import UI_pb2 as ui_protocols
import broadcasters.environment_score.environment_score_component
import objects.components.inventory
import objects.game_object
import sims4.log
import vfx
logger = sims4.log.Logger('Fishing', default_owner='TrevorLindsey')

class FishBowl(objects.game_object.GameObject):
    __qualname__ = 'FishBowl'
    VFX_SLOT_HASH = sims4.hash_util.hash32('_FX_')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._fish_vfx = None
        self.add_component(objects.components.inventory.FishBowlInventoryComponent(self))
        self.add_component(FishBowlTooltipComponent(self, custom_tooltips=None, state_value_numbers=None, state_value_strings=None))
        self._disable_tooltip()

    def get_fish(self):
        for obj in self.inventory_component:
            pass

    def fish_added(self, fish):
        current_fish = self.get_fish()
        if not current_fish or current_fish is not fish:
            logger.error("The fish_added function was called but there is\n            either no fish in this fish bowl or the fish in it doesn't match\n            the fish making the function called.")
            return
        self._fish_vfx = vfx.PlayEffect(self, current_fish.fishbowl_vfx, self.VFX_SLOT_HASH)
        self._fish_vfx.start()
        self._enable_tooltip()
        self.add_dynamic_component(objects.components.types.ENVIRONMENT_SCORE_COMPONENT.instance_attr)

    def fish_removed(self):
        if self._fish_vfx:
            self._fish_vfx.stop()
            self._fish_vfx = None
        self._disable_tooltip()
        self.remove_component(objects.components.types.ENVIRONMENT_SCORE_COMPONENT.instance_attr)

    def _ui_metadata_gen(self):
        fish = self.get_fish()
        if fish is not None:
            yield fish._ui_metadata_gen()
        else:
            return

    def get_environment_score(self, sim, ignore_disabled_state=False):
        fish = self.get_fish()
        if fish is None:
            return broadcasters.environment_score.environment_score_component.EnvironmentScoreComponent.ENVIRONMENT_SCORE_ZERO
        return fish.get_environment_score(sim, ignore_disabled_state=ignore_disabled_state)

    def potential_interactions(self, *args, **kwargs):
        fish = self.get_fish()
        if fish is not None:
            yield fish.potential_interactions(*args, **kwargs)
        yield super().potential_interactions(*args, **kwargs)

    def _enable_tooltip(self):
        self.hover_tip = ui_protocols.UiObjectMetadata.HOVER_TIP_CUSTOM_OBJECT
        self.update_object_tooltip()

    def _disable_tooltip(self):
        self.hover_tip = ui_protocols.UiObjectMetadata.HOVER_TIP_DISABLED
        self.update_object_tooltip()

class FishBowlTooltipComponent(objects.components.tooltip_component.TooltipComponent):
    __qualname__ = 'FishBowlTooltipComponent'

    def _ui_metadata_gen(self):
        fish = self.owner.get_fish()
        if fish is None:
            return
        yield fish._ui_metadata_gen()

