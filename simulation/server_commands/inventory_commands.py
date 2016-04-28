from objects.system import create_object
from protocolbuffers import Consts_pb2
from server_commands.argument_helpers import OptionalTargetParam, get_optional_target, RequiredTargetParam
import services
import sims4.commands

@sims4.commands.Command('inventory.create_in_hidden')
def create_object_in_hidden_inventory(definition_id, _connection=None):
    lot = services.active_lot()
    if lot is not None:
        return lot.create_object_in_hidden_inventory(definition_id) is not None
    return False

@sims4.commands.Command('inventory.list_hidden')
def list_objects_in_hidden_inventory(_connection=None):
    lot = services.active_lot()
    if lot is not None:
        hidden_inventory = lot.get_hidden_inventory()
        if hidden_inventory is not None:
            for obj in hidden_inventory:
                sims4.commands.output(str(obj), _connection)
            return True
    return False

@sims4.commands.Command('qa.objects.inventory.list', command_type=sims4.commands.CommandType.Automation)
def automation_list_active_situations(inventory_obj_id:int=None, _connection=None):
    manager = services.object_manager()
    if inventory_obj_id not in manager:
        sims4.commands.automation_output('ObjectInventory; Status:NoObject, ObjectId:{}'.format(inventory_obj_id), _connection)
        return
    inventory_obj = manager.get(inventory_obj_id)
    if inventory_obj.inventory_component != None:
        sims4.commands.automation_output('ObjectInventory; Status:Begin, ObjectId:{}'.format(inventory_obj_id), _connection)
        for obj in inventory_obj.inventory_component:
            sims4.commands.automation_output('ObjectInventory; Status:Data, Id:{}, DefId:{}'.format(obj.id, obj.definition.id), _connection)
        sims4.commands.automation_output('ObjectInventory; Status:End', _connection)
    else:
        sims4.commands.automation_output('ObjectInventory; Status:NoInventory, ObjectId:{}'.format(inventory_obj_id), _connection)

@sims4.commands.Command('inventory.purge')
def purge_sim_inventory(opt_target:OptionalTargetParam=None, _connection=None):
    target = get_optional_target(opt_target, _connection)
    if target is not None:
        target.inventory_component.purge_inventory()
    return False

@sims4.commands.Command('inventory.purchase', command_type=sims4.commands.CommandType.Live)
def purchase_to_inventory(inventory_obj, def_id:str=None, mailman_purchase:bool=False, _connection=None):
    definition_manager = services.definition_manager()
    definition = definition_manager.get(def_id)
    if definition is None:
        return False
    client = services.client_manager().get(_connection)
    if client is None:
        return False
    household = client.household
    price = definition.price
    if household.funds.money < price:
        return False
    if mailman_purchase:
        obj = services.active_lot().create_object_in_hidden_inventory(definition)
    else:
        inventory = inventory_obj.get_target().inventory_component
        if inventory is None:
            return False
        obj = create_object(definition)
        if obj is None:
            return False
        if not inventory.player_try_add_object(obj):
            obj.destroy(source=inventory, cause='Failed to purchase object into inventory')
            return False
    obj.set_household_owner_id(household.id)
    obj.try_post_bb_fixup(force_fixup=True, active_household_id=services.active_household_id())
    household.funds.remove(price, Consts_pb2.TELEMETRY_OBJECT_BUY)
    return True

@sims4.commands.Command('inventory.purchase_picker_response', command_type=sims4.commands.CommandType.Live)
def purchase_picker_response(inventory_target, mailman_purchase:bool=False, *def_ids_and_amounts, _connection=None):
    total_price = 0
    current_purchased = 0
    objects_to_buy = []
    definition_manager = services.definition_manager()
    for (def_id, amount) in zip(def_ids_and_amounts[::2], def_ids_and_amounts[1::2]):
        definition = definition_manager.get(def_id)
        if definition is None:
            sims4.commands.output('inventory.purchase_picker_response: Definition not found with id {}'.format(def_id), _connection)
            return False
        purchase_price = definition.price*amount
        total_price += purchase_price
        objects_to_buy.append((definition, amount))
    client = services.client_manager().get(_connection)
    if client is None:
        sims4.commands.output('inventory.purchase_picker_response: No client found to make purchase.', _connection)
        return False
    household = client.household
    if household.funds.money < total_price:
        sims4.commands.output('inventory.purchase_picker_response: Insufficient funds for household to purchase items.', _connection)
        return False
    if mailman_purchase:
        inventory = services.active_lot().get_hidden_inventory()
    else:
        inventory_owner = inventory_target.get_target()
        inventory = inventory_owner.inventory_component
    if inventory is None:
        sims4.commands.output('inventory.purchase_picker_response: Inventory not found for items to be purchased into.', _connection)
        return False
    for (definition, amount) in objects_to_buy:
        obj = create_object(definition)
        if obj is None:
            sims4.commands.output('inventory.purchase_picker_response: Failed to create object with definition {}.'.format(definition), _connection)
        obj.set_stack_count(amount)
        if not inventory.player_try_add_object(obj):
            sims4.commands.output('inventory.purchase_picker_response: Failed to add object into inventory: {}'.format(obj), _connection)
            obj.destroy(source=inventory, cause='inventory.purchase_picker_response: Failed to add object into inventory.')
        obj.set_household_owner_id(household.id)
        obj.try_post_bb_fixup(force_fixup=True, active_household_id=services.active_household_id())
        purchase_price = definition.price*amount
        current_purchased += purchase_price
    household.funds.remove(current_purchased, Consts_pb2.TELEMETRY_OBJECT_BUY)
    return True

@sims4.commands.Command('inventory.open_ui', command_type=sims4.commands.CommandType.Live)
def open_inventory_ui(inventory_obj, _connection=None):
    obj = inventory_obj.get_target()
    if obj is None:
        sims4.commands.output('Failed to get inventory_obj: {}.'.format(inventory_obj), _connection)
        return False
    comp = obj.inventory_component
    if comp is None:
        sims4.commands.output('inventory_obj does not have an inventory component: {}.'.format(inventory_obj), _connection)
        return False
    comp.open_ui_panel()
    return True

@sims4.commands.Command('inventory.view_update', command_type=sims4.commands.CommandType.Live)
def inventory_view_update(obj_id:int=0, _connection=None):
    obj = services.current_zone().find_object(obj_id)
    if obj is not None:
        obj.inventory_view_update()
        return True
    return False

