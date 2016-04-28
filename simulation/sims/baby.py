from protocolbuffers import Commodities_pb2
from protocolbuffers.Consts_pb2 import MSG_SIM_MOOD_UPDATE
from buffs.tunable import TunableBuffReference
from event_testing.resolver import SingleSimResolver
from event_testing.results import TestResult
from interactions.aop import AffordanceObjectPair
from interactions.base.interaction import RESERVATION_LIABILITY
from interactions.base.super_interaction import SuperInteraction
from interactions.context import InteractionContext, InteractionSource, QueueInsertStrategy
from objects import VisibilityState, HiddenReasonFlag
from objects.components.state import TunableStateValueReference, ObjectState
from objects.game_object import GameObject
from objects.system import create_object
from sims.aging import AGING_LIABILITY, AgingLiability
from sims.genealogy_tracker import genealogy_caching
from sims.sim_info_types import Age, Gender
from sims.sim_spawner import SimSpawner, SimCreator
from sims4.tuning.tunable import TunableReference, TunableList, TunableMapping, TunableEnumEntry, TunableTuple, TunableSkinTone, Tunable
from sims4.tuning.tunable_base import ExportModes
from singletons import DEFAULT
from statistics.mood import Mood
from ui.ui_dialog_notification import UiDialogNotification, TunableUiDialogNotificationSnippet
import build_buy
import camera
import distributor
import enum
import interactions
import placement
import services
import sims4
import tag
import vfx
logger = sims4.log.Logger('Baby')

class BabySkinTone(enum.Int):
    __qualname__ = 'BabySkinTone'
    LIGHT = 0
    MEDIUM = 1
    DARK = 2
    BLUE = 3
    GREEN = 4
    ADULT_SIM = 5

class Baby(GameObject):
    __qualname__ = 'Baby'
    MAX_PLACEMENT_ATTEMPTS = 8
    BABY_BASSINET_DEFINITION_MAP = TunableMapping(description='\n        The corresponding mapping for each definition pair of empty bassinet\n        and bassinet with baby inside. The reason we need to have two of\n        definitions is one is deletable and the other one is not.\n        ', key_name='Baby', key_type=TunableReference(description='\n            Bassinet with Baby object definition id.\n            ', manager=services.definition_manager()), value_name='EmptyBassinet', value_type=TunableReference(description='\n            Bassinet with Baby object definition id.\n            ', manager=services.definition_manager()))
    BASSINET_EMPTY_STATE = TunableStateValueReference(description='\n        The state value for an empty bassinet.\n        ')
    BASSINET_BABY_STATE = TunableStateValueReference(description='\n        The state value for a non-empty bassinet.\n        ')
    STATUS_STATE = ObjectState.TunableReference(description='\n        The state defining the overall status of the baby (e.g. happy, crying,\n        sleeping). We use this because we need to reapply this state to restart\n        animations after a load.\n        ')
    BABY_SKIN_TONE_STATE_MAPPING = TunableMapping(description='\n        From baby skin tone enum to skin tone state mapping.\n        ', key_type=TunableEnumEntry(tunable_type=BabySkinTone, default=BabySkinTone.MEDIUM), value_type=TunableTuple(boy=TunableStateValueReference(), girl=TunableStateValueReference()))
    BABY_MOOD_MAPPING = TunableMapping(description='\n        From baby state (happy, crying, sleep) to in game mood.\n        ', key_type=TunableStateValueReference(), value_type=Mood.TunableReference())
    BABY_SKIN_TONE_TO_CAS_SKIN_TONE = TunableMapping(description='\n        From baby skin tone enum to cas skin tone id mapping.\n        ', key_type=TunableEnumEntry(tunable_type=BabySkinTone, default=BabySkinTone.MEDIUM), value_type=TunableList(description='\n            The Skin Tones CAS reference under Catalog/InGame/CAS/Skintones.\n            ', tunable=TunableSkinTone()), export_modes=ExportModes.All, tuple_name='BabySkinToneToCasTuple')
    SEND_BABY_TO_DAYCARE_NOTIFICATION_SINGLE_BABY = TunableUiDialogNotificationSnippet(description='\n        The message appearing when a single baby is sent to daycare. You can\n        reference this single baby by name.\n        ')
    SEND_BABY_TO_DAYCARE_NOTIFICATION_MULTIPLE_BABIES = TunableUiDialogNotificationSnippet(description='\n        The message appearing when multiple babies are sent to daycare. You can\n        not reference any of these babies by name.\n        ')
    BRING_BABY_BACK_FROM_DAYCARE_NOTIFICATION_SINGLE_BABY = TunableUiDialogNotificationSnippet(description='\n        The message appearing when a single baby is brought back from daycare.\n        You can reference this single baby by name.\n        ')
    BRING_BABY_BACK_FROM_DAYCARE_NOTIFICATION_MULTIPLE_BABIES = TunableUiDialogNotificationSnippet(description='\n        The message appearing when multiple babies are brought back from\n        daycare. You can not reference any of these babies by name.\n        ')
    BABY_AGE_UP = TunableTuple(description='\n        Multiple settings for baby age up moment.\n        ', age_up_affordance=TunableReference(description='\n            The affordance to run when baby age up to kid.\n            ', manager=services.affordance_manager(), class_restrictions='SuperInteraction'), copy_states=TunableList(description='\n            The list of the state we want to copy from the original baby\n            bassinet to the new bassinet to play idle.\n            ', tunable=TunableReference(manager=services.object_state_manager(), class_restrictions='ObjectState')), idle_state_value=TunableReference(description='\n            The state value to apply on the new baby bassinet with the age up\n            special idle animation/vfx linked.\n            ', manager=services.object_state_manager(), class_restrictions='ObjectStateValue'))
    BABY_PLACEMENT_TAGS = TunableList(TunableEnumEntry(tag.Tag, tag.Tag.INVALID, description='\n            Attempt to place the baby near objects with this tag set.\n            '), description='\n        When trying to place a baby bassinet on the lot, we attempt to place it\n        near other objects on the lot. Those objects are determined in priority\n        order by this tuned list. It will try to place next to all objects of the\n        matching types, before trying to place the baby in the middle of the lot,\n        and then finally trying the mailbox. If all FGL placements fail, we put\n        the baby into the household inventory.\n        ')
    BABY_THUMBNAIL_DEFINITION = TunableReference(description='\n        The thumbnail definition for client use only.\n        ', manager=services.definition_manager(), export_modes=(ExportModes.ClientBinary,))
    NEGLECTED_STATES = TunableList(description='\n        If the baby enters any of these states, the neglected moment will begin.\n        ', tunable=TunableStateValueReference(description='\n            The state to listen for in order to push the neglected moment on the baby.\n            '))
    NEGLECT_ANIMATION = TunableReference(description='\n        The animation to play on the baby for the neglect moment.\n        ', manager=services.get_instance_manager(sims4.resources.Types.ANIMATION), class_restrictions='ObjectAnimationElement')
    NEGLECT_NOTIFICATION = UiDialogNotification.TunableFactory(description='\n        The notification to show when the baby neglect moment happens.\n        ')
    NEGLECT_EFFECT = Tunable(description='\n        The VFX to play during the neglect moment.\n        ', tunable_type=str, default='s40_Sims_neglected')
    NEGLECT_EMPTY_BASSINET_STATE = TunableStateValueReference(description='\n        The state that will be set on the bassinet when it is emptied due to\n        neglect. This should control any reaction broadcasters that we want to\n        happen when the baby is taken away. This MUST be tuned.\n        ')
    NEGLECT_BUFF_IMMEDIATE_FAMILY = TunableBuffReference(description="\n        The buff to be applied to the baby's immediate family during the \n        neglect moment.\n        ")
    FAILED_PLACEMENT_NOTIFICATION = UiDialogNotification.TunableFactory(description='\n        The notification to show if a baby could not be spawned into the world\n        because FGL failed. This is usually due to the player cluttering their\n        lot with objects. Token 0 is the baby.\n        ')

    @classmethod
    def get_baby_skin_tone_enum(cls, sim_info):
        if sim_info.is_baby:
            skin_tone_id = sim_info.skin_tone
            for (skin_enum, tone_ids) in cls.BABY_SKIN_TONE_TO_CAS_SKIN_TONE.items():
                while skin_tone_id in tone_ids:
                    return skin_enum
            logger.error('Baby with skin tone id {} not in BABY_SKIN_TONE_TO_CAS_SKIN_TONE. Setting light skin tone instead.', skin_tone_id, owner='jjacobson')
            return BabySkinTone.LIGHT
        return BabySkinTone.ADULT_SIM

    @classmethod
    def get_baby_skin_tone_state(cls, sim_info):
        skin_tone_state_value = None
        baby_skin_enum = cls.get_baby_skin_tone_enum(sim_info)
        if baby_skin_enum is not None and baby_skin_enum in cls.BABY_SKIN_TONE_STATE_MAPPING:
            skin_state_tuple = cls.BABY_SKIN_TONE_STATE_MAPPING[baby_skin_enum]
            if sim_info.gender == Gender.FEMALE:
                skin_tone_state_value = skin_state_tuple.girl
            elif sim_info.gender == Gender.MALE:
                skin_tone_state_value = skin_state_tuple.boy
        return skin_tone_state_value

    @classmethod
    def get_corresponding_definition(cls, definition):
        if definition in cls.BABY_BASSINET_DEFINITION_MAP:
            return cls.BABY_BASSINET_DEFINITION_MAP[definition]
        for (baby_def, bassinet_def) in cls.BABY_BASSINET_DEFINITION_MAP.items():
            while bassinet_def is definition:
                return baby_def

    @classmethod
    def get_default_baby_def(cls):
        return next(iter(cls.BABY_BASSINET_DEFINITION_MAP), None)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._sim_info = None
        self.state_component.state_trigger_enabled = False
        self._started_neglect_moment = False
        self._ignore_daycare = False

    def set_sim_info(self, sim_info, ignore_daycare=False):
        self._sim_info = sim_info
        self._ignore_daycare = ignore_daycare
        if self._sim_info is not None:
            self.state_component.state_trigger_enabled = True
            self.enable_baby_state()

    @property
    def sim_info(self):
        return self._sim_info

    @property
    def is_selectable(self):
        return self.sim_info.is_selectable

    @property
    def sim_id(self):
        if self._sim_info is not None:
            return self._sim_info.sim_id
        return self.id

    @property
    def household_id(self):
        if self._sim_info is not None:
            return self._sim_info.household.id
        return 0

    def populate_localization_token(self, *args, **kwargs):
        if self.sim_info is not None:
            return self.sim_info.populate_localization_token(*args, **kwargs)
        logger.warn('self.sim_info is None in baby.populate_localization_token', owner='epanero', trigger_breakpoint=True)
        return super().populate_localization_token(*args, **kwargs)

    def enable_baby_state(self):
        if self._sim_info is None:
            return
        self.set_state(self.BASSINET_BABY_STATE.state, self.BASSINET_BABY_STATE)
        status_state = self.get_state(self.STATUS_STATE)
        self.set_state(status_state.state, status_state, force_update=True)
        skin_tone_state = self.get_baby_skin_tone_state(self._sim_info)
        if skin_tone_state is not None:
            self.set_state(skin_tone_state.state, skin_tone_state)

    def empty_baby_state(self):
        self.set_state(self.BASSINET_EMPTY_STATE.state, self.BASSINET_EMPTY_STATE)

    def on_state_changed(self, state, old_value, new_value):
        super().on_state_changed(state, old_value, new_value)
        if new_value in self.NEGLECTED_STATES and not self._started_neglect_moment:
            start_baby_neglect(self)
        elif self.manager is not None and new_value in self.BABY_MOOD_MAPPING:
            mood = self.BABY_MOOD_MAPPING[new_value]
            mood_msg = Commodities_pb2.MoodUpdate()
            mood_msg.sim_id = self.id
            mood_msg.mood_key = mood.guid64
            mood_msg.mood_intensity = 1
            distributor.shared_messages.add_object_message(self, MSG_SIM_MOOD_UPDATE, mood_msg, False)

    def load_object(self, object_data):
        super().load_object(object_data)
        self._sim_info = services.sim_info_manager().get(self.sim_id)

    def on_finalize_load(self):
        sim_info = services.sim_info_manager().get(self.sim_id)
        if sim_info is None or sim_info.household is not services.active_lot().get_household():
            _replace_bassinet(sim_info, bassinet=self)
        else:
            self.set_sim_info(sim_info)

def start_baby_neglect(baby):
    baby._started_neglect_moment = True
    sim_info = baby.sim_info
    dialog = Baby.NEGLECT_NOTIFICATION(sim_info, SingleSimResolver(sim_info))
    dialog.show_dialog()
    neglect_effect = vfx.PlayEffect(sim_info, 's40_Sims_neglected', sims4.hash_util.hash32('_FX_'))
    neglect_effect.start()
    camera.focus_on_sim(sim_info, follow=False)
    sim_info_manager = services.sim_info_manager()
    with genealogy_caching():
        for member_id in sim_info.genealogy.get_immediate_family_sim_ids_gen():
            member_info = sim_info_manager.get(member_id)
            member_info.add_buff_from_op(Baby.NEGLECT_BUFF_IMMEDIATE_FAMILY.buff_type, Baby.NEGLECT_BUFF_IMMEDIATE_FAMILY.buff_reason)
    empty_bassinet = _replace_bassinet(sim_info)
    empty_bassinet.set_state(Baby.NEGLECT_EMPTY_BASSINET_STATE.state, Baby.NEGLECT_EMPTY_BASSINET_STATE)
    services.client_manager().get_first_client().selectable_sims.remove_selectable_sim_info(sim_info)
    services.get_persistence_service().del_sim_proto_buff(sim_info.id)
    sim_info_manager.remove_permanently(sim_info)

def set_baby_sim_info_with_switch_id(bassinet, sim_info):
    if bassinet.id != sim_info.sim_id:
        new_bassinet = None
        try:
            save_data = bassinet.get_attribute_save_data()
            empty_bassinet_def = bassinet.definition
            baby_in_bassinet_def = Baby.get_corresponding_definition(empty_bassinet_def)
            new_bassinet = create_object(baby_in_bassinet_def, obj_id=sim_info.sim_id)
            new_bassinet.load(save_data)
            new_bassinet.location = bassinet.location
        except:
            logger.error('{} fail to set sim_info {}', bassinet, sim_info)
            if new_bassinet is not None:
                new_bassinet.destroy(source=sim_info, cause='Failed to set sim_info on bassinet')
        finally:
            new_bassinet.set_sim_info(sim_info)
            sim_info.supress_aging()
            bassinet.hide(HiddenReasonFlag.REPLACEMENT)
        return new_bassinet

def on_sim_spawn(sim_info):
    sim_info.set_zone_on_spawn()
    if sim_info.is_baby:
        _assign_to_bassinet(sim_info)
    else:
        _replace_bassinet(sim_info)
    return True

def assign_bassinet_for_baby(sim_info):
    object_manager = services.object_manager()
    for bassinet in object_manager.get_objects_of_type_gen(*Baby.BABY_BASSINET_DEFINITION_MAP.values()):
        while not bassinet.transient:
            set_baby_sim_info_with_switch_id(bassinet, sim_info)
            bassinet.destroy(source=sim_info, cause='Assigned bassinet for baby.')
            return True
    return False

def create_and_place_baby(sim_info, **kwargs):
    bassinet = create_object(Baby.get_default_baby_def(), obj_id=sim_info.sim_id)
    bassinet.set_sim_info(sim_info, **kwargs)

    def try_to_place_bassinet(position, **kwargs):
        fgl_context = placement.FindGoodLocationContext(starting_position=position, object_id=sim_info.sim_id, search_flags=placement.FGLSearchFlagsDefault | placement.FGLSearchFlag.SHOULD_TEST_BUILDBUY, object_footprints=(bassinet.get_footprint(),), **kwargs)
        (translation, orientation) = placement.find_good_location(fgl_context)
        if translation is not None and orientation is not None:
            bassinet.move_to(translation=translation, orientation=orientation)
            return True
        return False

    lot = services.active_lot()
    for tag in Baby.BABY_PLACEMENT_TAGS:
        for (attempt, obj) in enumerate(services.object_manager().get_objects_with_tag_gen(tag)):
            position = obj.position
            if lot.is_position_on_lot(position) and try_to_place_bassinet(position, max_distance=10):
                return
            while attempt >= Baby.MAX_PLACEMENT_ATTEMPTS:
                break
    position = lot.get_default_position()
    if not try_to_place_bassinet(position):
        bassinet.update_ownership(sim_info, make_sim_owner=False)
        build_buy.move_object_to_household_inventory(bassinet)
        if sim_info.is_selectable:
            failed_placement_notification = Baby.FAILED_PLACEMENT_NOTIFICATION(sim_info, SingleSimResolver(sim_info))
            failed_placement_notification.show_dialog()

def _assign_to_bassinet(sim_info):
    object_manager = services.object_manager()
    bassinet = object_manager.get(sim_info.sim_id)
    if assign_bassinet_for_baby(sim_info):
        return
    if not (bassinet is None and build_buy.object_exists_in_household_inventory(sim_info.id, sim_info.household_id)):
        create_and_place_baby(sim_info)

def _replace_bassinet(sim_info, bassinet=None):
    bassinet = bassinet if bassinet is not None else services.object_manager().get(sim_info.sim_id)
    if bassinet is not None:
        empty_bassinet = create_object(Baby.get_corresponding_definition(bassinet.definition))
        empty_bassinet.location = bassinet.location
        bassinet.destroy(source=sim_info, cause='Replaced bassinet with empty version')
        return empty_bassinet

def _replace_bassinet_for_age_up(sim_info):
    bassinet = services.object_manager().get(sim_info.sim_id)
    if bassinet is not None:
        new_bassinet = create_object(bassinet.definition)
        new_bassinet.location = bassinet.location
        new_bassinet.set_sim_info(bassinet.sim_info)
        new_bassinet.copy_state_values(bassinet, state_list=Baby.BABY_AGE_UP.copy_states)
        bassinet.destroy(source=sim_info, cause='Replacing bassinet for age up.')
        return new_bassinet

def baby_age_up(sim_info, client=DEFAULT):
    middle_bassinet = _replace_bassinet_for_age_up(sim_info)
    if middle_bassinet is not None:
        try:

            def run_age_up(kid):

                def age_up_exit_behavior():
                    new_bassinet = create_object(Baby.get_corresponding_definition(middle_bassinet.definition))
                    new_bassinet.location = middle_bassinet.location
                    middle_bassinet.make_transient()

                kid.fade_opacity(1, 0)
                kid.visibility = VisibilityState(False)
                affordance = Baby.BABY_AGE_UP.age_up_affordance
                aop = AffordanceObjectPair(affordance, middle_bassinet, affordance, None, exit_functions=(age_up_exit_behavior,))
                context = InteractionContext(kid, InteractionSource.SCRIPT, interactions.priority.Priority.Critical, insert_strategy=QueueInsertStrategy.NEXT)
                result = aop.test_and_execute(context)
                if result:
                    result.interaction.add_liability(AGING_LIABILITY, AgingLiability(sim_info, Age.BABY))
                else:
                    logger.error('Failed to run baby age up interaction.', owner='jjacobson')
                return True

            if not SimSpawner.spawn_sim(sim_info, middle_bassinet.position, spawn_action=run_age_up):
                logger.error('Failed to spawn sim in process of baby age up.  We are in an unrecoverable situation if this occurs.', owner='jjacobson')
            if client is DEFAULT:
                client = services.client_manager().get_client_by_household_id(sim_info.household_id)
            while client is not None:
                if sim_info not in client.selectable_sims:
                    client.selectable_sims.add_selectable_sim_info(sim_info)
                else:
                    client.on_sim_added_to_skewer(sim_info)
                    client.selectable_sims.notify_dirty()
        except Exception as e:
            logger.exception('{} fail to age up with sim_info {}', middle_bassinet, sim_info, exc=e)

class BabyManualAgeUpInteraction(SuperInteraction):
    __qualname__ = 'BabyManualAgeUpInteraction'

    @classmethod
    def _test(cls, target, context, **interaction_parameters):
        result = super()._test(target, context, **interaction_parameters)
        if not result:
            return result
        if target.sim_info is None:
            return TestResult(False, 'Bassinet({}) does not have sim info.', target)
        if not target.sim_info.can_age_up():
            return TestResult(False, 'Baby {} cannot age up now.', target.sim_info)
        return TestResult.TRUE

    def _run_interaction_gen(self, timeline):

        def age_up_baby():
            sim_info = self.target.sim_info
            self.set_target(None)
            self.remove_liability(RESERVATION_LIABILITY)
            sim_info.advance_age()
            baby_age_up(sim_info)

        self.add_exit_function(age_up_baby)

def _check_send_baby_to_day_care(household, travel_sim_infos, from_zone_id):
    if household.is_npc_household:
        return
    if not household.number_of_babies:
        return
    message_owner_info = None
    curent_zone = services.current_zone()
    for sim_info in household.teen_or_older_info_gen():
        while sim_info.zone_id == household.home_zone_id:
            if sim_info.zone_id != curent_zone.id:
                if not sim_info.career_tracker.currently_at_work:
                    return
                    sim = sim_info.get_sim_instance()
                    if sim is not None and not sim.is_hidden():
                        return
            else:
                sim = sim_info.get_sim_instance()
                if sim is not None and not sim.is_hidden():
                    return
    if curent_zone.id == from_zone_id:
        client = services.client_manager().get_client_by_household(household)
        if client is not None:
            message_owner_info = client.active_sim.sim_info
        obj_mgr = services.object_manager(curent_zone.id)
        for baby_info in household.baby_info_gen():
            bassinet = obj_mgr.get(baby_info.sim_id)
            while bassinet is not None:
                bassinet.empty_baby_state()
    else:
        message_owner_info = sim_info
    if message_owner_info is None:
        return
    if household.number_of_babies == 1:
        dialog = Baby.SEND_BABY_TO_DAYCARE_NOTIFICATION_SINGLE_BABY(message_owner_info, SingleSimResolver(next(household.baby_info_gen())))
    else:
        dialog = Baby.SEND_BABY_TO_DAYCARE_NOTIFICATION_MULTIPLE_BABIES(message_owner_info, SingleSimResolver(message_owner_info))
    dialog.show_dialog()

def _check_bring_baby_back_from_daycare(household, travel_sim_infos, current_zone):
    if household.is_npc_household:
        return
    if not household.number_of_babies:
        return
    for sim_info in household.teen_or_older_info_gen():
        while sim_info not in travel_sim_infos and sim_info.zone_id == household.home_zone_id:
            sim = sim_info.get_sim_instance()
            if sim is not None and not sim.is_hidden():
                return
    returned_babies = []
    obj_mgr = services.object_manager()
    for baby_info in household.baby_info_gen():
        bassinet = obj_mgr.get(baby_info.sim_id)
        while bassinet is not None:
            if not bassinet._ignore_daycare:
                bassinet.enable_baby_state()
                returned_babies.append(bassinet)
            else:
                bassinet._ignore_daycare = False
    if returned_babies:
        if len(returned_babies) == 1:
            dialog = Baby.BRING_BABY_BACK_FROM_DAYCARE_NOTIFICATION_SINGLE_BABY(sim_info, SingleSimResolver(returned_babies[0]))
        else:
            dialog = Baby.BRING_BABY_BACK_FROM_DAYCARE_NOTIFICATION_MULTIPLE_BABIES(sim_info, SingleSimResolver(sim_info))
        dialog.show_dialog()

def on_sim_removed_baby_handle(travel_sim, from_zone_id):
    if travel_sim is None:
        return
    _check_send_baby_to_day_care(travel_sim.household, (travel_sim,), from_zone_id)

def on_sim_spawned_baby_handle(travel_sim_infos):
    if travel_sim_infos is None:
        return
    zone = services.current_zone()
    travel_households = {sim_info.household for sim_info in travel_sim_infos}
    for travel_household in travel_households:
        if travel_household.home_zone_id != zone.id:
            _check_send_baby_to_day_care(travel_household, travel_sim_infos, travel_household.home_zone_id)
        else:
            _check_bring_baby_back_from_daycare(travel_household, travel_sim_infos, zone)

def debug_create_baby(actor_sim, position, gender, routing_surface=None):
    baby = None
    try:
        actor_sim_info = actor_sim.sim_info
        account = actor_sim.sim_info.account
        sim_creator = SimCreator(gender=gender, age=Age.BABY, first_name=SimSpawner.get_random_first_name(account, gender == Gender.FEMALE), last_name=SimSpawner.get_family_name_for_gender(account, actor_sim.last_name, gender == Gender.FEMALE))
        (sim_info_list, _) = SimSpawner.create_sim_infos((sim_creator,), household=actor_sim_info.household, account=account, zone_id=actor_sim_info.zone_id, creation_source='cheat: debug_create_baby')
        sim_info = sim_info_list[0]
        baby_def = Baby.get_default_baby_def()
        baby = create_object(baby_def, sim_info.sim_id)
        baby.set_sim_info(sim_info)
        fgl_context = placement.FindGoodLocationContext(starting_position=position, object_id=baby.id, search_flags=placement.FGLSearchFlagsDefault, object_footprints=(baby.get_footprint(),))
        (trans, orient) = placement.find_good_location(fgl_context)
        if trans is not None:
            baby.location = sims4.math.Location(sims4.math.Transform(trans, orient), routing_surface)
        client = services.client_manager().get_client_by_household_id(sim_info.household_id)
        while client is not None:
            client.selectable_sims.add_selectable_sim_info(sim_info)
    except Exception as e:
        logger.exception('Create baby fail', e)
        if actor_sim_info.household.sim_in_household(sim_info.sim_id):
            actor_sim_info.household.remove_sim_info(sim_info)
        client = services.client_manager().get_client_by_household_id(sim_info.household_id)
        if client is not None:
            client.selectable_sims.remove_selectable_sim_info(sim_info)
        while baby is not None:
            baby.destroy(source=actor_sim, cause='Create baby fail')

