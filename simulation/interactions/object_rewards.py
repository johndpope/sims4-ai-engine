from collections import Counter
from interactions import ParticipantType
from interactions.utils.loot_basic_op import BaseLootOperation
from objects import ALL_HIDDEN_REASONS
from objects.components import types
from objects.system import create_object
from sims4.localization import LocalizationHelperTuning
from sims4.random import weighted_random_item
from sims4.tuning.tunable import TunableRange, TunableTuple, TunableReference, TunableList, TunableVariant, HasTunableSingletonFactory, HasTunableReference, TunableEnumFlags, Tunable, OptionalTunable, TunableEnumEntry
from ui.ui_dialog_notification import TunableUiDialogNotificationSnippet
import build_buy
import services

class ObjectRewardsTuning(HasTunableReference, HasTunableSingletonFactory):
    __qualname__ = 'ObjectRewardsTuning'
    TUNABLE_REWARD = 1
    SPAWNER_REWARD = 2
    FACTORY_TUNABLES = {'quantity': TunableRange(description='\n            Quantity of objects to create when loot action gets triggered.\n            The result of this loot will do a quantity number of random checks\n            to see which reward objects it will give.\n            e.g. quantity 2 will do 2 random checks using the weights tuned \n            to see which items it will give each time.\n            ', tunable_type=int, default=10, minimum=0, maximum=None), 'reward_objects': TunableList(description='\n            List of pair of object reference-weight for the random calculation\n            e.g. Pair1[3,obj1] Pair2[7,obj2] means obj1 has a 30% chance of \n            being picked and obj2 has 70% chance of being picked\n            ', tunable=TunableTuple(reward=TunableList(description='\n                    List of objects to reward.  When the random check picks \n                    this value from the weight calculation it will give all\n                    the items tuned on this list.\n                    ', tunable=TunableReference(description='\n                        Object reference of the type of game object needed.\n                        Reference can be None.  We will allow this to have the \n                        probability to receive no rewards from the interaction\n                        ', manager=services.definition_manager())), weight=TunableRange(description='\n                    Weight that object will have on the probability calculation \n                    of which objects will be created.\n                    ', tunable_type=int, default=1, minimum=0))), 'locked_args': {'spawn_type': TUNABLE_REWARD}}

    def __init__(self, quantity, reward_objects, spawn_type, **kwargs):
        super().__init__()
        self.spawn_type = spawn_type
        self.quantity = quantity
        self.reward_objects = reward_objects

class SpawnerInteractionTuning(HasTunableSingletonFactory):
    __qualname__ = 'SpawnerInteractionTuning'
    FACTORY_TUNABLES = {'spawner_participant': TunableEnumFlags(description='\n        Subject containing the spawner component the object reward data will \n        be read from.\n        ', enum_type=ParticipantType, default=ParticipantType.Object), 'locked_args': {'spawn_type': ObjectRewardsTuning.SPAWNER_REWARD}}

    def __init__(self, spawner_participant, spawn_type, **kwargs):
        super().__init__()
        self.spawner_participant = spawner_participant
        self.spawn_type = spawn_type

class ObjectRewardsOperation(BaseLootOperation):
    __qualname__ = 'ObjectRewardsOperation'
    FACTORY_TUNABLES = {'object_rewards': TunableVariant(description='\n            Object rewards when running the loot.  Rewards objects will be created\n            and sent to the tuned inventory.\n            Spawnerdata reference will load the reward data from the interaction \n            spawner tuning inside the spawner component of the participant selected\n            Rewardsdata tuning will allow you to tune the object rewards directly  \n            ', spawnerdata_reference=SpawnerInteractionTuning.TunableFactory(), rewardsdata_tuning=ObjectRewardsTuning.TunableFactory()), 'notification': OptionalTunable(description='\n            If enabled, a notification will be displayed when this object reward\n            is granted to a Sim.\n            ', tunable=TunableUiDialogNotificationSnippet(description='\n                The notification to display when this object reward is granted\n                to the Sim. There is one additional token provided: a string\n                representing a bulleted list of all individual rewards granted.\n                ')), 'force_family_inventory': Tunable(description='\n            If Enabled, the rewards object(s) will be put in the family \n            inventory no matter what.  If not enabled, the object will try to\n            be added to the sim inventory, if that is not possible it will be\n            added to the family inventory as an automatic fallback.', tunable_type=bool, default=False), 'transfer_stored_sim_info_to_reward': OptionalTunable(description="\n            If enabled, the tuned participant will transfer its stored sim info\n            into the rewards created. This is mostly used for the cow plant\n            life essence, which will store the sim info of the sim from which\n            the life essence was drained.\n            \n            Ex: For cow plant's milk life essence, we want to transfer the dead\n            sim's sim info from the cow plant to the created essence drink.\n            ", tunable=TunableEnumEntry(description='\n                The participant of this interaction which has a \n                StoredSimInfoComponent. The stored sim info will be transferred\n                to the created rewards and will then be removed from the source.\n                ', tunable_type=ParticipantType, default=ParticipantType.Object))}

    def __init__(self, object_rewards, notification, force_family_inventory, transfer_stored_sim_info_to_reward, subject=None, **kwargs):
        super().__init__(**kwargs)
        self._object_rewards = object_rewards
        self._notification = notification
        self._force_family_inventory = force_family_inventory
        self._transfer_stored_sim_info_to_reward = transfer_stored_sim_info_to_reward

    def _create_object_rewards(self, obj_weight_pair, obj_counter, resolver):
        obj_result = weighted_random_item(obj_weight_pair)
        for obj_reward in obj_result:
            created_obj = create_object(obj_reward, init=None, post_add=lambda *args: self._place_object(resolver=resolver, *args))
            while created_obj is not None:
                obj_counter[obj_reward] += 1

    def _apply_to_subject_and_target(self, subject, target, resolver):
        if subject.is_npc:
            return
        obj_counter = Counter()
        if self._object_rewards.spawn_type == ObjectRewardsTuning.SPAWNER_REWARD:
            participant = resolver.get_participant(self._object_rewards.spawner_participant)
            if participant is not None:
                weighted_data = participant.interaction_spawner_data()
                if weighted_data is not None:
                    self._create_object_rewards(weighted_data, obj_counter, resolver)
        elif self._object_rewards.spawn_type == ObjectRewardsTuning.TUNABLE_REWARD:
            for _ in range(self._object_rewards.quantity):
                weight_pairs = [(data.weight, data.reward) for data in self._object_rewards.reward_objects]
                self._create_object_rewards(weight_pairs, obj_counter, resolver)
        if obj_counter and self._notification is not None:
            obj_names = [LocalizationHelperTuning.get_object_count(count, obj) for (obj, count) in obj_counter.items()]
            dialog = self._notification(subject, resolver=resolver)
            dialog.show_dialog(additional_tokens=(LocalizationHelperTuning.get_bulleted_list(None, *obj_names),))
        return True

    def _place_object(self, created_object, resolver=None):
        actor = resolver.get_participant(ParticipantType.Actor).get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)
        created_object.update_ownership(actor, make_sim_owner=False)
        if self._transfer_stored_sim_info_to_reward is not None:
            stored_sim_source = resolver.get_participant(self._transfer_stored_sim_info_to_reward)
            sim_id = stored_sim_source.get_stored_sim_id()
            if sim_id is not None:
                created_object.add_dynamic_component(types.STORED_SIM_INFO_COMPONENT.instance_attr, sim_id=sim_id)
                stored_sim_source.remove_component(types.STORED_SIM_INFO_COMPONENT.instance_attr)
                created_object.update_object_tooltip()
        if self._force_family_inventory or actor.inventory_component.can_add(created_object):
            if actor.inventory_component.player_try_add_object(created_object):
                return
        build_buy.move_object_to_household_inventory(created_object)

