from interactions.base.picker_interaction import ObjectPickerInteraction
from interactions.base.picker_strategy import StatePickerEnumerationStrategy
from interactions.base.super_interaction import SuperInteraction
from objects.components.gardening_components import GardeningTuning
from sims4.utils import flexmethod

class GardeningSpliceInteraction(SuperInteraction):
    __qualname__ = 'GardeningSpliceInteraction'

    def _run_interaction_gen(self, timeline):
        result = yield super()._run_interaction_gen(timeline)
        if result:
            shoot = self.target.gardening_component.create_shoot()
            try:
                if shoot is not None and self.sim.inventory_component.player_try_add_object(shoot):
                    shoot.update_ownership(self.sim.sim_info)
                    shoot = None
                    return True
            finally:
                if shoot is not None:
                    shoot.destroy(source=self, cause='Failed to add shoot to player inventory.')
        return False

class GardeningGraftPickerInteraction(ObjectPickerInteraction):
    __qualname__ = 'GardeningGraftPickerInteraction'

    @flexmethod
    def _get_objects_gen(cls, inst, target, context, **kwargs):
        for shoot in context.sim.inventory_component:
            while target.gardening_component.can_splice_with(shoot):
                yield shoot

    def __init__(self, *args, **kwargs):
        choice_enumeration_strategy = StatePickerEnumerationStrategy()
        super().__init__(choice_enumeration_strategy=choice_enumeration_strategy, *args, **kwargs)

class GardeningGraftInteraction(SuperInteraction):
    __qualname__ = 'GardeningGraftInteraction'

    def _run_interaction_gen(self, timeline):
        result = yield super()._run_interaction_gen(timeline)
        if result:
            shoot = self.carry_target
            self.target.gardening_component.add_fruit(shoot)
            tree_fruit_names = self.target.gardening_component.root_stock_name_list
            self.target.gardening_component._spliced_description = GardeningTuning.get_spliced_description(tree_fruit_names)
            self.target.set_state(GardeningTuning.SPLICED_STATE_VALUE.state, GardeningTuning.SPLICED_STATE_VALUE)
            shoot.transient = True
        return False

