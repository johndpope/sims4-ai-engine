from event_testing.results import TestResult
from interactions.base.immediate_interaction import ImmediateSuperInteraction
from sims4.tuning.tunable import Tunable
import objects
import services
import sims4

class ToggleLockImmediateInteraction(ImmediateSuperInteraction):
    __qualname__ = 'ToggleLockImmediateInteraction'
    INSTANCE_TUNABLES = {'lock_item': Tunable(bool, default=True)}

    @classmethod
    def _test(cls, target, context, **kwargs):
        inv = target.get_inventory()
        if inv is None:
            return TestResult(False, 'Item is not in an inventory.')
        if cls.lock_item:
            if inv.is_locked(target.id):
                return TestResult(False, 'Cannot lock an item that is already locked.')
            return TestResult.TRUE
        if inv.is_locked(target.id):
            return TestResult.TRUE
        return TestResult(False, 'Cannot unlock an item that is already unlocked.')

    def _run_interaction_gen(self, timeline):
        inv = self.target.get_inventory()
        inv.toggle_lock(self.target.id)
        return True

@sims4.commands.Command('inventory.clone_obj_to_inv', command_type=sims4.commands.CommandType.Automation)
def clone_obj_to_inv(obj_id, inventory_owner_id, count:int=1, _connection=None):
    obj_to_create = services.object_manager().get(obj_id)
    target_object = services.object_manager().get(inventory_owner_id)
    if obj_to_create is None or target_object is None:
        sims4.commands.output('{} or {} not found in object manager'.format(obj_id, inventory_owner_id), _connection)
        return
    inventory = target_object.inventory_component
    if inventory is None:
        sims4.commands.output("{} doesn't have an inventory".format(str(target_object)), _connection)
        return
    for _ in range(count):
        obj_instance = objects.system.create_object(obj_to_create.definition)
        while obj_instance:
            inventory.player_try_add_object(obj_instance)

