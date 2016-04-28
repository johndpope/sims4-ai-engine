import itertools
from build_buy import get_object_slotset, get_object_decosize
from interactions import ParticipantType
from interactions.constraints import GLOBAL_STUB_ACTOR, GLOBAL_STUB_TARGET
from interactions.utils.animation import InteractionAsmType
from interactions.utils.animation_reference import get_animation_reference_usage
from objects.components.slot_component import SlotComponent
from objects.slots import get_slot_type_set_from_key, DecorativeSlotTuning
from sims4.gsi.dispatcher import GsiHandler
from sims4.gsi.schema import GsiGridSchema, GsiFieldVisualizers
from sims4.repr_utils import callable_repr
import native.animation
import services
import sims4.resources
slot_type_schema = GsiGridSchema(label='Tuning/Slot Types')
slot_type_schema.add_field('slot_type_name', label='Name', unique_field=True)
slot_type_schema.add_field('slot_type_name_hash', label='Hash', type=GsiFieldVisualizers.INT)
slot_type_schema.add_field('slot_type_name_hashx', label='Hex Hash')
slot_type_schema.add_field('bone_name', label='Bone Name')
slot_type_schema.add_field('bone_name_hash', label='Bone Name Hash', type=GsiFieldVisualizers.INT)
slot_type_schema.add_field('bone_name_hashx', label='Bone Name Hex Hash')
with slot_type_schema.add_has_many('objects', GsiGridSchema, label='Objects that go in this type of slot') as sub_schema:
    sub_schema.add_field('id', label='Definition ID', unique_field=True)
    sub_schema.add_field('name', label='Definition Tuning')
    sub_schema.add_field('object_name', label='Object Tuning')
with slot_type_schema.add_has_many('slot_type_sets', GsiGridSchema, label='Part of these slot type sets') as sub_schema:
    sub_schema.add_field('name', label='Name', unique_field=True)
with slot_type_schema.add_has_many('object_slots', GsiGridSchema, label='Objects with this type of slot') as sub_schema:
    sub_schema.add_field('id', label='Catalog ID', width=0.25, unique_field=True)
    sub_schema.add_field('tuning_id', label='Tuning ID')
    sub_schema.add_field('object_name', label='Object Tuning')
    sub_schema.add_field('bone_name', label='Bone Names')
    sub_schema.add_field('bone_name_hash', label='Bone Name Hashes')
    sub_schema.add_field('bone_name_hashx', label='Bone Name Hex Hashes')

@GsiHandler('slot_types', slot_type_schema)
def generate_slot_type_data(*args, zone_id:int=None, **kwargs):
    slot_type_data = []
    for (key, slot_type) in services.get_instance_manager(sims4.resources.Types.SLOT_TYPE).types.items():
        data = {}
        data['slot_type_name'] = slot_type.__name__
        data['slot_type_name_hash'] = key.instance
        data['slot_type_name_hashx'] = hex(key.instance)
        if slot_type._bone_name is not None:
            data['bone_name'] = slot_type._bone_name
            data['bone_name_hash'] = slot_type.bone_name_hash
            data['bone_name_hashx'] = hex(slot_type.bone_name_hash)
        data['slot_type_sets'] = []
        for (key, slot_type_set) in services.get_instance_manager(sims4.resources.Types.SLOT_TYPE_SET).types.items():
            while slot_type in slot_type_set.slot_types:
                sub_data = {}
                sub_data['name'] = slot_type_set.__name__
                data['slot_type_sets'].append(sub_data)
        data['objects'] = []
        data['object_slots'] = []
        for ((def_id, obj_state), definition) in services.definition_manager()._definitions_cache.items():
            slot_types = set()
            slot_types.update(DecorativeSlotTuning.get_slot_types_for_object(get_object_decosize(definition.id)))
            try:
                def_slot_type_set_key = get_object_slotset(def_id)
                def_slot_type_set = get_slot_type_set_from_key(def_slot_type_set_key)
                while def_slot_type_set is not None:
                    slot_types.update(def_slot_type_set.slot_types)
            except:
                pass
            if slot_type in slot_types:
                sub_data = {}
                sub_data['id'] = '{}[{}]'.format(def_id, obj_state)
                sub_data['tuning_id'] = definition.tuning_file_id
                if definition.cls is not None:
                    sub_data['object_name'] = definition.cls.__name__
                data['objects'].append(sub_data)
            slots_resource = definition.get_slots_resource(obj_state)
            while slots_resource is not None:
                slot_infos = []
                for (slot_name_hash, slot_types) in SlotComponent.get_containment_slot_infos_static(slots_resource, definition.get_rig(obj_state), None):
                    while slot_type in slot_types:
                        try:
                            slot_infos.append((native.animation.get_joint_name_for_hash_from_rig(definition.get_rig(obj_state), slot_name_hash), slot_name_hash, hex(slot_name_hash)))
                        except:
                            pass
                if slot_infos:
                    slot_infos.sort()

                    def info_list(i):
                        return ', '.join(str(e[i]) for e in slot_infos)

                    sub_data = {}
                    sub_data['id'] = '{}[{}]'.format(def_id, obj_state)
                    sub_data['tuning_id'] = definition.tuning_file_id
                    if definition.cls is not None:
                        sub_data['object_name'] = definition.cls.__name__
                    sub_data['bone_name'] = info_list(0)
                    sub_data['bone_name_hash'] = info_list(1)
                    sub_data['bone_name_hashx'] = info_list(2)
                    data['object_slots'].append(sub_data)
        slot_type_data.append(data)
    return slot_type_data

buff_schema = GsiGridSchema(label='Tuning/Buffs')
buff_schema.add_field('buff_name', label='Name', unique_field=True)
buff_schema.add_field('guid', label='Guid')
buff_schema.add_field('visible', label='Visible')
buff_schema.add_field('sim_has_buff', label='Buff Exists on Current Sim')
with buff_schema.add_has_many('sims_with_buff', GsiGridSchema, label='Sims with Buff') as sub_schema:
    sub_schema.add_field('id', label='Sim ID')
    sub_schema.add_field('name', label='Sim Name')
with buff_schema.add_view_cheat('sims.add_buff', label='Add Selected Buff to Current Sim') as cheat:
    cheat.add_token_param('buff_name')
with buff_schema.add_view_cheat('sims.remove_buff', label='Remove Selected Buff from Current Sim') as cheat:
    cheat.add_token_param('buff_name')
with buff_schema.add_view_cheat('sims.remove_buff_from_all', label='Remove Selected Buff from All Sims') as cheat:
    cheat.add_token_param('buff_name')

@GsiHandler('buff_handler', buff_schema)
def generate_buff_data(*args, zone_id:int=None, sim_id:int=None, **kwargs):
    buff_data = []
    buff_manager = services.get_instance_manager(sims4.resources.Types.BUFF)
    for buff_type in buff_manager.types.values():
        data = {'buff_name': buff_type.__name__, 'guid': buff_type.guid64, 'visible': buff_type.visible}
        sim_list = []
        buff_is_on_sim = False
        for sim_info in services.sim_info_manager(zone_id).values():
            sim = sim_info.get_sim_instance()
            while sim is not None:
                if sim.has_buff(buff_type):
                    sim_data = {'id': str(sim.id), 'name': sim.full_name}
                    sim_list.append(sim_data)
                    if sim.id != sim_id:
                        buff_is_on_sim = str(True)
        data['sims_with_buff'] = sim_list
        data['sim_has_buff'] = str(buff_is_on_sim)
        buff_data.append(data)
    return buff_data

_PARTICIPANT_TYPES_THAT_GET_CONSTRAINTS = (ParticipantType.Actor, ParticipantType.TargetSim, ParticipantType.Listeners)
interactions_schema = GsiGridSchema(label='Tuning/Super Interactions', auto_refresh=False)
interactions_schema.add_field('name', label='Name', width=1, unique_field=True)
interactions_schema.add_field('postures', width=1, label='Postures')
interactions_schema.add_field('slots', width=1, label='Slots')
interactions_schema.add_field('canonical_animation', width=1, label='Canonical Animation')
interactions_schema.add_field('has_callbacks', width=1, label='Has Procedural Behavior')
with interactions_schema.add_has_many('constraints', GsiGridSchema, label='Constraints') as sub_schema:
    sub_schema.add_field('participant_type', label='Participant', width=1)
    sub_schema.add_field('constraint_type', label='Type of Constraint', width=1)
    sub_schema.add_field('constraint_postures', label='Postures', width=1)
    sub_schema.add_field('constraint_slots', label='Slots', width=3)
    sub_schema.add_field('constraint_info', label='Constraint Information', width=9)
with interactions_schema.add_has_many('callbacks', GsiGridSchema, label='Procedural Behavior') as sub_schema:
    sub_schema.add_field('callback_type', label='Type')
    sub_schema.add_field('callback_value', label='Value')

@GsiHandler('interactions_tuning', interactions_schema)
def generate_interaction_tuning_data(*args, zone_id:int=None, **kwargs):
    interaction_tuning_data = []
    for affordance in services.get_instance_manager(sims4.resources.Types.INTERACTION).types.values():
        if not affordance.is_super:
            pass
        data = {}
        data['name'] = affordance.__name__
        canonical_animation = affordance.canonical_animation
        if canonical_animation is not None:
            data['canonical_animation'] = str(canonical_animation).replace('TunableAnimationReferenceWrapper.', '')
        else:
            data['canonical_animation'] = None
        constraint_list = []
        all_postures = set()
        all_slots = set()
        for participant_type in _PARTICIPANT_TYPES_THAT_GET_CONSTRAINTS:
            try:
                for constraints in affordance.constraint_gen(GLOBAL_STUB_ACTOR, GLOBAL_STUB_TARGET, participant_type):
                    for constraint in constraints:
                        constraint_data = {}
                        constraint_data['participant_type'] = participant_type.name
                        constraint_data['constraint_type'] = type(constraint).__name__
                        if constraint.posture_state_spec:
                            postures = set(p.name for p in itertools.chain(*[e.posture_types for e in constraint.posture_state_spec.posture_manifest]))
                            all_postures.update(postures)
                            postures = ', '.join(sorted(postures))
                            if postures:
                                data['has_posture_constraints'] = True
                                constraint_data['constraint_postures'] = postures
                            slots = set(str(e) for e in constraint.posture_state_spec.slot_manifest)
                            all_slots.update(slots)
                            slots = ', '.join(sorted(slots))
                            if slots:
                                data['has_slot_constraints'] = True
                                constraint_data['constraint_slots'] = slots
                        constraint_data['constraint_info'] = str(constraint)
                        constraint_list.append(constraint_data)
            except Exception as exc:
                constraint_data = {}
                constraint_data['participant_type'] = participant_type.name
                constraint_data['constraint_type'] = 'ERROR'
                constraint_data['constraint_info'] = str(exc)
                constraint_list.append(constraint_data)
        data['constraints'] = constraint_list
        data['postures'] = ', '.join(sorted(all_postures))
        data['slots'] = ', '.join(sorted(all_slots))
        callback_list = []
        if affordance._simoleon_delta_callbacks:
            for callback in affordance._simoleon_delta_callbacks:
                callback_data = {}
                callback_data['callback_type'] = 'Simoleon'
                callback_data['callback_value'] = callable_repr(callback)
                callback_list.append(callback_data)
        if affordance._sim_can_violate_privacy_callbacks:
            for callback in affordance._sim_can_violate_privacy_callbacks:
                callback_data = {}
                callback_data['callback_type'] = 'Privacy'
                callback_data['callback_value'] = callable_repr(callback)
                callback_list.append(callback_data)
        if affordance._additional_conditional_actions:
            for callback in affordance._additional_conditional_actions:
                callback_data = {}
                callback_data['callback_type'] = 'Exit Condition'
                callback_data['callback_value'] = str(callback)
                callback_list.append(callback_data)
        if affordance._additional_tests:
            for callback in affordance._additional_tests:
                callback_data = {}
                callback_data['callback_type'] = 'Test'
                callback_data['callback_value'] = str(callback)
                callback_list.append(callback_data)
        data['callbacks'] = callback_list
        data['has_callbacks'] = ', '.join(sorted(set(e['callback_type'] for e in callback_list))) or ''
        interaction_tuning_data.append(data)
    return interaction_tuning_data

state_schema = GsiGridSchema(label='Tuning/Object States')
state_schema.add_field('state_name', label='Name', unique_field=True)
with state_schema.add_has_many('state_values', GsiGridSchema, label='State Values') as sub_schema:
    sub_schema.add_field('state_value_name', label='Name')
state_value_schema = GsiGridSchema(label='Tuning/Object State Values')
state_value_schema.add_field('state_value_name', label='Name', unique_field=True)
state_value_schema.add_field('state_name', label='State Name')

def get_states_and_values():
    all_states = []
    all_state_values = []
    from objects.components.state import ObjectState, ObjectStateValue
    for (_, obj) in services.get_instance_manager(sims4.resources.Types.OBJECT_STATE).types.items():
        if issubclass(obj, ObjectState):
            all_states.append(obj)
        while issubclass(obj, ObjectStateValue):
            all_state_values.append(obj)
    return (all_states, all_state_values)

@GsiHandler('states', state_schema)
def generate_state_data(*args, zone_id:int=None, **kwargs):
    (all_states, _) = get_states_and_values()
    state_data = []
    for state in all_states:
        data = {}
        data['state_name'] = state.__name__
        state_values = []
        for state_value in state.values:
            sub_data = {}
            sub_data['state_value_name'] = state_value.__name__
            state_values.append(sub_data)
        data['state_values'] = state_values
        state_data.append(data)
    return state_data

@GsiHandler('state_values', state_value_schema)
def generate_state_value_data(*args, zone_id:int=None, **kwargs):
    (_, all_state_values) = get_states_and_values()
    state_value_data = []
    for state_value in all_state_values:
        data = {}
        data['state_value_name'] = state_value.__name__
        data['state_name'] = repr(state_value.state)
        state_value_data.append(data)
    return state_value_data

animation_element_schema = GsiGridSchema(label='Tuning/Animation Elements', auto_refresh=False)
animation_element_schema.add_field('animation_element_name', label='Name', unique_field=True)
animation_element_schema.add_field('count_interaction', label='Interaction', type=GsiFieldVisualizers.INT)
animation_element_schema.add_field('count_outcome', label='Outcome', type=GsiFieldVisualizers.INT)
animation_element_schema.add_field('count_response', label='Response', type=GsiFieldVisualizers.INT)
animation_element_schema.add_field('count_reactionlet', label='Reactionlet', type=GsiFieldVisualizers.INT)
animation_element_schema.add_field('count_total', label='Total', type=GsiFieldVisualizers.INT)

@GsiHandler('animation_elements', animation_element_schema)
def generate_animation_element_data(*args, zone_id:int=None, **kwargs):
    affordance_manager = services.affordance_manager()
    animation_element_data = []
    for (animation_element, usage) in get_animation_reference_usage().items():
        animation_element_data.append({'animation_element_name': animation_element.__name__, 'count_interaction': usage[InteractionAsmType.Interaction], 'count_outcome': usage[InteractionAsmType.Outcome], 'count_response': usage[InteractionAsmType.Response], 'count_reactionlet': usage[InteractionAsmType.Reactionlet], 'count_total': sum(count for count in usage.values())})
    return animation_element_data

trait_tuning_schema = GsiGridSchema(label='Tuning/Traits', auto_refresh=False)
trait_tuning_schema.add_field('trait_name', label='Name', width=2)
trait_tuning_schema.add_field('guid', label='Guid', unique_field=True)
with trait_tuning_schema.add_view_cheat('traits.equip_trait', label='Add Trait to Current Sim', dbl_click=True) as cheat:
    cheat.add_token_param('guid')
with trait_tuning_schema.add_view_cheat('traits.remove_trait', label='Remove Trait from Current Sim') as cheat:
    cheat.add_token_param('guid')

@GsiHandler('trait_definitions', trait_tuning_schema)
def generate_trait_instances_data(*args, zone_id:int=None, **kwargs):
    trait_data = []
    for trait_type in sorted(services.get_instance_manager(sims4.resources.Types.TRAIT).types.values(), key=lambda trait_type: trait_type.__name__):
        trait_data.append({'trait_name': trait_type.__name__, 'guid': trait_type.guid64})
    return trait_data

