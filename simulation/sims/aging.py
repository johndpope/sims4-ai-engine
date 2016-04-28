import random
import sys
from protocolbuffers import DistributorOps_pb2
from clock import interval_in_sim_days
from date_and_time import create_time_span, TimeSpan
from element_utils import build_element
from event_testing.resolver import SingleSimResolver
from event_testing.test_events import TestEvent
from event_testing.tests import TunableTestSet
from interactions.context import InteractionContext
from interactions.liability import Liability
from interactions.priority import Priority
from objects import ALL_HIDDEN_REASONS
from relationships.relationship import Relationship
from sims.sim_dialogs import SimPersonalityAssignmentDialog
from sims.sim_info_types import Age
from sims4.localization import TunableLocalizedString
from sims4.tuning.tunable import Tunable, TunableReference, TunableFactory, TunableTuple, TunableList, TunableMapping, TunableEnumEntry, TunableSimMinute
from sims4.tuning.tunable_base import ExportModes
from sims4.utils import classproperty
from statistics.continuous_statistic import ContinuousStatistic
from ui.ui_dialog import PhoneRingType
from ui.ui_dialog_notification import UiDialogNotification
import alarms
import date_and_time
import enum
import services
import sims4.log
import sims4.resources
import telemetry_helper
logger = sims4.log.Logger('Aging')
TELEMETRY_CHANGE_AGE = 'AGES'
writer_age = sims4.telemetry.TelemetryWriter(TELEMETRY_CHANGE_AGE)
AGING_LIABILITY = 'AgingLiability'

class AgingLiability(Liability):
    __qualname__ = 'AgingLiability'
    AGING_SAVELOCK_TOOLTIP = TunableLocalizedString(description='\n        The tooltip that is used as the reason why the game is save locked\n        while the age up dialog is visible.\n        ')

    def __init__(self, sim_info, starting_age):
        self._sim_info = sim_info
        self._starting_age = starting_age

    def get_lock_save_reason(self):
        return AgingLiability.AGING_SAVELOCK_TOOLTIP

    def release(self):
        if self._sim_info.age != self._starting_age and not self._sim_info.is_npc:
            services.get_persistence_service().lock_save(self)
            dialog = AgeTransitions.AGE_TRANSITION_INFO[self._sim_info.age].age_transition_dialog(self._sim_info, assignment_sim_info=self._sim_info, resolver=SingleSimResolver(self._sim_info))
            dialog.show_dialog(on_response=lambda _: services.get_persistence_service().unlock_save(self))

class AgeProgressContinuousStatistic(ContinuousStatistic):
    __qualname__ = 'AgeProgressContinuousStatistic'
    _default_convergence_value = sims4.math.POS_INFINITY
    decay_modifier = 1

    @classproperty
    def max_value(cls):
        return cls.default_value

    @classproperty
    def min_value(cls):
        return 0.0

    @classproperty
    def persisted(cls):
        return True

    @classmethod
    def set_modifier(cls, modifier):
        cls.decay_modifier = modifier

    @property
    def base_decay_rate(self):
        return self.decay_modifier/(date_and_time.HOURS_PER_DAY*date_and_time.MINUTES_PER_HOUR)

class AgeSpeeds(enum.Int):
    __qualname__ = 'AgeSpeeds'
    FAST = 0
    NORMAL = 1
    SLOW = 2

class TraitDaysFactory(TunableFactory):
    __qualname__ = 'TraitDaysFactory'

    @staticmethod
    def factory(tuned_trait, percent_days_award, trait_in_question):
        if trait_in_question == tuned_trait.guid64:
            return percent_days_award
        return 0

    FACTORY_TYPE = factory

    def __init__(self, **kwargs):
        super().__init__(tuned_trait=TunableReference(description='\n                             The trait we want to test ownership of\n                             ', manager=services.get_instance_manager(sims4.resources.Types.TRAIT)), percent_days_award=Tunable(description='\n                             Percent lifespan is extended as bonus life span for possessing this trait. \n                             (This is the bonus time, so .1 is 10% more.)\n                             ', tunable_type=float, default=0))

class MoodDaysFactory(TunableFactory):
    __qualname__ = 'MoodDaysFactory'

    @staticmethod
    def factory(tuned_mood, tuned_days_held, days_award, mood_in_question, days_mood_held):
        if mood_in_question is tuned_mood and days_mood_held > tuned_days_held:
            return days_award
        return 0

    FACTORY_TYPE = factory

    def __init__(self, **kwargs):
        super().__init__(tuned_mood=TunableReference(description='\n                            The mood we want to test ownership of\n                            ', manager=services.get_instance_manager(sims4.resources.Types.MOOD)), tuned_days_held=Tunable(description='\n                            Number of Sim days this mood was held during lifetime.\n                            ', tunable_type=float, default=1), days_award=Tunable(description='\n                             Number of Sim days awarded as bonus life span for possessing this mood.\n                             ', tunable_type=float, default=1))

class AgeTransitionInfo(TunableTuple):
    __qualname__ = 'AgeTransitionInfo'

    def __init__(self, **kwargs):
        super().__init__(age_up_warning_notification=UiDialogNotification.TunableFactory(description='\n                Message sent to client to warn of impending age up.\n                '), age_up_available_notification=UiDialogNotification.TunableFactory(description='\n                Message sent to client to alert age up is ready.\n                '), age_transition_threshold=Tunable(description='\n                Number of Sim days required to be eligible to transition from\n                the mapping key age to the next one."\n                ', tunable_type=float, default=1), age_transition_warning=Tunable(description='\n                Number of Sim days prior to the transition a Sim will get a\n                warning of impending new age.\n                ', tunable_type=float, default=1), age_transition_delay=Tunable(description='\n                Number of Sim days after transition time elapsed before auto-\n                aging occurs.\n                ', tunable_type=float, default=1), auto_aging_actions=TunableTuple(buff=TunableReference(description='\n                    Buff that will be applied to the Sim when aging up to the\n                    current age.  This buff will be applied if the Sim\n                    auto-ages rather than if they age up with the birthday\n                    cake.\n                    ', manager=services.buff_manager()), buff_tests=TunableTestSet(description='\n                    Tests that will be run to determine if to apply the buff on\n                    the Sim.  This should be used to not apply the auto-aging\n                    under certain circumstances, example auto-aging while a\n                    birthday party is being thrown for the sim.\n                    '), description='\n                Tuning related to actions that will be applied on auto-aging\n                rather than aging up normally through the birday cake.\n                '), age_trait_awards=TunableList(description='\n                Traits available for selection to the Sim upon completing the\n                current age. They traits are presented in a menu for the player\n                to choose from.\n                ', tunable=TunableReference(services.trait_manager())), age_trait=TunableReference(description="\n                The age trait that corresponds to this Sim's age\n                ", manager=services.trait_manager()), age_transition_dialog=SimPersonalityAssignmentDialog.TunableFactory(description='\n                Dialog displayed to the player when their sim ages up.\n                ', locked_args={'phone_ring_type': PhoneRingType.NO_RING}))

class AgeTransitions:
    __qualname__ = 'AgeTransitions'
    AGE_TRANSITION_INFO = TunableMapping(description='\n        A mapping between age and the tuning that details the transition into\n        and out of that age.\n        ', key_type=TunableEnumEntry(description='\n            The age that this set of age transition info will correspond to.\n            ', tunable_type=Age, default=Age.ADULT), value_type=AgeTransitionInfo())
    AGE_SPEED_SETTING_MULTIPLIER = TunableMapping(description='\n        A mapping between age speeds and the multiplier that those speeds\n        correspond to.\n        ', key_type=TunableEnumEntry(description='\n            The age speed that will be mapped to its multiplier.\n            ', tunable_type=AgeSpeeds, default=AgeSpeeds.NORMAL), value_type=Tunable(description="\n            The multiplier by which to adjust the lifespan based on user age\n            speed settings. Setting this to 2 for 'Slow' speed will double the\n            Sim's age play time in that setting.\n            ", tunable_type=float, default=1))
    BONUS_TRAIT_DAYS = TunableList(description='\n        Extra days of life to be awarded to the Sim for possessing this trait.\n        ', tunable=TraitDaysFactory())
    BONUS_MOOD_DAYS = TunableList(description='\n        Extra days of life to be awarded to the Sim for spending a tuned number\n        of days in this mood.\n        ', tunable=MoodDaysFactory())

    @classmethod
    def get_warning_notification(cls, age):
        if age in cls.AGE_TRANSITION_INFO.keys():
            return cls.AGE_TRANSITION_INFO[age].age_up_warning_notification

    @classmethod
    def get_available_notification(cls, age):
        if age in cls.AGE_TRANSITION_INFO.keys():
            return cls.AGE_TRANSITION_INFO[age].age_up_available_notification

    @classmethod
    def get_duration(cls, age) -> float:
        if age in cls.AGE_TRANSITION_INFO.keys():
            return cls.AGE_TRANSITION_INFO[age].age_transition_threshold
        return 0

    @classmethod
    def get_total_lifetime(cls) -> float:
        total_lifetime = 0
        for age_transition in cls.AGE_TRANSITION_INFO.values():
            total_lifetime += age_transition.age_transition_threshold
        age_service = services.get_age_service()
        total_lifetime /= cls.get_speed_multiple(age_service.aging_speed)
        return total_lifetime

    @classmethod
    def get_warning(cls, age) -> float:
        if age in cls.AGE_TRANSITION_INFO.keys():
            return cls.AGE_TRANSITION_INFO[age].age_transition_warning
        return 0

    @classmethod
    def get_delay(cls, age) -> float:
        if age in cls.AGE_TRANSITION_INFO.keys():
            return cls.AGE_TRANSITION_INFO[age].age_transition_delay
        return 0

    @classmethod
    def get_speed_multiple(cls, ageSpeed) -> float:
        if ageSpeed in cls.AGE_SPEED_SETTING_MULTIPLIER.keys():
            return cls.AGE_SPEED_SETTING_MULTIPLIER[ageSpeed]
        return 0

    @classmethod
    def get_auto_aging_buff(cls, sim_info):
        age = sim_info.age
        if age not in cls.AGE_TRANSITION_INFO.keys():
            return
        auto_aging_actions = cls.AGE_TRANSITION_INFO[age].auto_aging_actions
        if auto_aging_actions.buff is None:
            return
        resolver = SingleSimResolver(sim_info)
        if not auto_aging_actions.buff_tests.run_tests(resolver):
            return
        return auto_aging_actions.buff

    @classmethod
    def get_trait_list(cls, age):
        if age in cls.AGE_TRANSITION_INFO.keys():
            return cls.AGE_TRANSITION_INFO[age].age_trait_awards
        return []

    @classmethod
    def get_bonus_for_trait(cls, trait_inst_id) -> float:
        return sum(trait_to_check(trait_in_question=trait_inst_id) for trait_to_check in cls.BONUS_TRAIT_DAYS)

    @classmethod
    def get_bonus_for_mood(cls, mood, days_held) -> float:
        return sum(mood_to_check(mood_in_question=mood, days_mood_held=days_held) for mood_to_check in cls.BONUS_MOOD_DAYS)

    @classmethod
    def get_age_trait(cls, age):
        if age in cls.AGE_TRANSITION_INFO.keys():
            trait = cls.AGE_TRANSITION_INFO[age].age_trait
            if trait is None:
                logger.warn('get_age_trait() was unable to find a tuned trait in the age transition tuning for age: {}', age)
            return trait

class AgingTuning:
    __qualname__ = 'AgingTuning'
    AGE_PROGRESS_UPDATE_TIME = Tunable(description='\n        The update rate, in Sim Days, of age progression in the UI.\n        ', tunable_type=float, default=0.2)
    AGE_UP_MOMENT = TunableReference(description='\n        Interaction to age up a Sim\n        ', manager=services.get_instance_manager(sims4.resources.Types.INTERACTION), class_restrictions='AgeUpSuperInteraction')
    OLD_AGE_DEATH = TunableReference(description="\n        Interaction of a Sim's demise for old age\n        ", manager=services.get_instance_manager(sims4.resources.Types.INTERACTION), class_restrictions='DeathSuperInteraction')
    AGE_SUPPRESSION_ALARM_TIME = TunableSimMinute(description='\n        Amount of time in sim seconds to suppress aging.\n        ', default=5, minimum=1)

class AgingMixin:
    __qualname__ = 'AgingMixin'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._age_progress = AgeProgressContinuousStatistic(None, 0.0)
        self._age_progress.decay_enabled = True
        self._auto_aging_enabled = True
        self._age_speed_setting = AgeSpeeds.NORMAL
        self._almost_can_age_handle = None
        self._can_age_handle = None
        self._auto_age_handle = None
        self._walk_on_lot_handle = None
        self._age_time = 1
        self._time_alive = TimeSpan.ZERO
        self._last_time_time_alive_updated = None
        self._age_suppression_alarm_handle = None

    @property
    def is_baby(self):
        return self._base.age == Age.BABY

    @property
    def is_child(self):
        return self._base.age == Age.CHILD

    @property
    def is_teen(self):
        return self._base.age == Age.TEEN

    @property
    def is_teen_or_older(self):
        return self._base.age >= Age.TEEN

    @property
    def is_young_adult(self):
        return self._base.age == Age.YOUNGADULT

    @property
    def is_adult(self):
        return self._base.age == Age.ADULT

    @property
    def is_elder(self):
        return self._base.age == Age.ELDER

    def _create_fake_total_time_alive(self):
        age = Age.BABY
        time_alive = TimeSpan.ZERO
        while age != self.age:
            age_time = interval_in_sim_days(AgeTransitions.get_duration(Age(self._base.age)))
            time_alive += age_time
            age = Age.next_age(age)
        setting_multiplier = AgeTransitions.get_speed_multiple(self._age_speed_setting)
        time_alive /= setting_multiplier
        return time_alive

    def load_time_alive(self, loaded_time):
        if loaded_time is None:
            loaded_time = self._create_fake_total_time_alive()
        self._time_alive = loaded_time
        self._last_time_time_alive_updated = services.time_service().sim_now

    def update_time_alive(self):
        if self._last_time_time_alive_updated is None:
            logger.error('Trying to update time live before initial value has been set.', owner='jjacobson')
            return
        current_time = services.time_service().sim_now
        time_since_last_update = current_time - self._last_time_time_alive_updated
        self._last_time_time_alive_updated = current_time

    def advance_age_phase(self):
        if self._base.age == Age.ELDER:
            bonus_days = self._get_bonus_days()
        else:
            bonus_days = 0
        age_time = AgeTransitions.get_duration(Age(self._base.age))
        warn_time = age_time - AgeTransitions.get_warning(Age(self._base.age))
        auto_age_time = age_time + AgeTransitions.get_delay(Age(self._base.age)) + bonus_days
        age_progress = self._age_progress.get_value()
        if age_progress <= warn_time:
            age_progress = warn_time
        elif age_progress <= age_time:
            age_progress = age_time
        else:
            age_progress = auto_age_time
        self._age_progress.set_value(age_progress - 0.0001)
        self.update_age_callbacks()

    def reset_age_progress(self):
        self._age_progress.set_value(self._age_progress.min_value)
        self.send_age_progress_bar_update()
        self.resend_age()
        self.update_age_callbacks()

    def _days_until_ready_to_age(self):
        setting_multiplier = AgeTransitions.get_speed_multiple(self._age_speed_setting)
        return (self._age_time - self._age_progress.get_value())/setting_multiplier

    def update_age_callbacks(self):
        self._update_age_trait(self._base.age)
        self._age_time = AgeTransitions.get_duration(Age(self._base.age))
        if not self._auto_aging_enabled:
            self._age_progress.decay_enabled = False
            if self._almost_can_age_handle is not None:
                alarms.cancel_alarm(self._almost_can_age_handle)
                self._almost_can_age_handle = None
            if self._can_age_handle is not None:
                alarms.cancel_alarm(self._can_age_handle)
                self._can_age_handle = None
            if self._auto_age_handle is not None:
                alarms.cancel_alarm(self._auto_age_handle)
                self._auto_age_handle = None
            if self._walk_on_lot_handle is not None:
                alarms.cancel_alarm(self._walk_on_lot_handle)
                self._walk_on_lot_handle = None
            return
        self._age_progress.decay_enabled = True
        if self.is_elder:
            bonus_days = self._get_bonus_days()
        else:
            bonus_days = 0
        setting_multiplier = AgeTransitions.get_speed_multiple(self._age_speed_setting)
        self._age_progress.set_modifier(setting_multiplier)
        age_time = self._days_until_ready_to_age()
        warn_time = age_time - AgeTransitions.get_warning(Age(self._base.age))/setting_multiplier
        auto_age_time = age_time + (AgeTransitions.get_delay(Age(self._base.age)) + bonus_days)/setting_multiplier
        if self._almost_can_age_handle is not None:
            alarms.cancel_alarm(self._almost_can_age_handle)
        if warn_time >= 0:
            self._almost_can_age_handle = alarms.add_alarm(self, create_time_span(days=warn_time), self.callback_almost_ready_to_age, False)
        if self._can_age_handle is not None:
            alarms.cancel_alarm(self._can_age_handle)
        if age_time >= 0:
            self._can_age_handle = alarms.add_alarm(self, create_time_span(days=age_time), self.callback_ready_to_age, False)
        self._create_auto_age_callback(delay=max(0, auto_age_time))
        self.send_age_progress()

    def send_age_progress(self):
        if self.is_selectable:
            self.send_age_progress_bar_update()

    def _create_auto_age_callback(self, delay=1):
        if self._auto_age_handle is not None:
            alarms.cancel_alarm(self._auto_age_handle)
        time_span_until_age_up = create_time_span(days=delay)
        if time_span_until_age_up.in_ticks() <= 0:
            time_span_until_age_up = create_time_span(minutes=1)
        self._auto_age_handle = alarms.add_alarm(self, time_span_until_age_up, self.callback_auto_age, False)

    def add_bonus_days(self, number_of_days):
        pass

    def _get_bonus_days(self):
        bonus_days = 0
        bonus_days_percent = 0.0
        for trait_inst_id in self._trait_tracker.trait_ids:
            bonus_days_percent = AgeTransitions.get_bonus_for_trait(trait_inst_id)
            bonus_days += bonus_days_percent*AgeTransitions.get_total_lifetime()
        mood_manager = services.get_instance_manager(sims4.resources.Types.MOOD)
        for mood_id in mood_manager.types:
            mood = mood_manager.get(mood_id)
            days_in_mood = 0
            for buff in mood.buffs:
                while buff.buff_type is not None:
                    days_in_mood += self.aspiration_tracker.data_object.get_total_buff_data(buff.buff_type).in_days()
            while days_in_mood > 0:
                bonus_days += AgeTransitions.get_bonus_for_mood(mood, days_in_mood)
        bonus_days += self._additional_bonus_days
        return bonus_days

    def _apply_auto_aging_buff(self):
        buff = AgeTransitions.get_auto_aging_buff(self)
        if buff is not None:
            self.add_buff_from_op(buff, buff.buff_name)

    def _select_age_trait(self):
        traits_choices = AgeTransitions.get_trait_list(Age(self._base.age))
        for trait in traits_choices:
            logger.info('AGE UP TRAIT CHOICES: {}', trait.display_name)

    def _update_age_trait(self, next_age, current_age=None):
        trait_tracker = self.trait_tracker
        if current_age is not None:
            trait_to_remove = AgeTransitions.get_age_trait(current_age)
            if trait_tracker.has_trait(trait_to_remove):
                trait_tracker.remove_trait(trait_to_remove)
        trait_to_add = AgeTransitions.get_age_trait(next_age)
        if trait_to_add is None:
            return
        if not trait_tracker.has_trait(trait_to_add):
            trait_tracker.add_trait(trait_to_add)

    def _show_age_notification(self, notification_name):
        if not self.is_npc and not self._is_aging_disabled():
            notification = AgeTransitions.AGE_TRANSITION_INFO[self.age][notification_name]
            dialog = notification(self, SingleSimResolver(self))
            dialog.show_dialog(additional_tokens=(self,))

    def callback_ready_to_age(self, *_, **__):
        logger.info('READY TO AGE: {}', self.full_name)
        services.social_service.post_aging_message(self)
        self._show_age_notification('age_up_available_notification')
        services.get_event_manager().process_event(TestEvent.ReadyToAge, sim_info=self)

    def callback_almost_ready_to_age(self, *_, **__):
        logger.info('ALMOST READY TO AGE: {}', self.full_name)
        services.social_service.post_aging_message(self, ready_to_age=False)
        self._show_age_notification('age_up_warning_notification')

    def callback_auto_age(self, *_, **__):
        if self._is_aging_disabled():
            self._create_auto_age_callback()
        else:
            walk_on_lot_delay = create_time_span(0.001*random.randrange(1, 10, 1))
            self._walk_on_lot_handle = alarms.add_alarm(self, walk_on_lot_delay, self.age_moment, False)

    def age_moment(self, walk_on_lot_handle):
        logger.info('AGE UP COMPLETE BY AUTOAGING: {}', self.full_name)
        if self.is_baby:
            self._age_up_baby()
        elif self.is_elder:
            self._age_up_elder()
        else:
            self._age_up_pctya()
        alarms.cancel_alarm(walk_on_lot_handle)
        self._walk_on_lot_handle = None

    def _age_up_baby(self):
        baby = services.object_manager().get(self.sim_id)
        if baby is not None:
            from sims.baby import baby_age_up
            client = services.client_manager().get_client_by_account(self._account.id)
            self.advance_age()
            baby_age_up(self, client)
        elif self.is_npc:
            self.advance_age()

    def _age_up_pctya(self):
        sim_instance = self.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)
        if sim_instance is not None:
            client = services.client_manager().get_client_by_account(self._account.id)
            context = InteractionContext(sim_instance, InteractionContext.SOURCE_SCRIPT, Priority.Critical, client=client, pick=None)
            result = sim_instance.push_super_affordance(AgingTuning.AGE_UP_MOMENT, None, context)
            if not result:
                self._create_auto_age_callback()
                return
        elif self.is_npc:
            self.advance_age()
        self._apply_auto_aging_buff()

    def _age_up_elder(self):
        sim_instance = self.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)
        if sim_instance is not None:
            client = services.client_manager().get_client_by_account(self._account.id)
            context = InteractionContext(sim_instance, InteractionContext.SOURCE_SCRIPT, Priority.Critical, client=client, pick=None)
            if not sim_instance.push_super_affordance(AgingTuning.OLD_AGE_DEATH, None, context):
                self._create_auto_age_callback()
        elif self.is_npc:
            household = self.household
            household_zone_id = household.home_zone_id
            if self.spouse_sim_id is not None:
                spouse_sim_id = self.spouse_sim_id
                self.relationship_tracker.remove_relationship_bit(spouse_sim_id, Relationship.MARRIAGE_RELATIONSHIP_BIT)
                spouse_sim_info = services.sim_info_manager().get(spouse_sim_id)
                if spouse_sim_info is not None:
                    spouse_sim_info.relationship_tracker.remove_relationship_bit(self.id, Relationship.MARRIAGE_RELATIONSHIP_BIT)
            self.death_tracker.set_death_type(AgingTuning.OLD_AGE_DEATH.death_type)
            if not any(sim_info is not self for sim_info in household.teen_or_older_info_gen()) and household_zone_id != 0:
                household.clear_household_lot_ownership(household_zone_id)

    def callback_update_ui_age_progress(self, *_, **__):
        self.send_age_progress_bar_update()

    def set_aging_speed(self, speed):
        if speed is None or speed < 0 or speed > 2:
            logger.warn('Trying to set aging speed on a sim with an invalid speed: {}. Speed can only be 0, 1, or 2.', speed)
        self._age_speed_setting = AgeSpeeds(speed)
        self.update_age_callbacks()

    def set_aging_enabled(self, enabled):
        self._auto_aging_enabled = enabled
        self.update_age_callbacks()

    def advance_age_progress(self, days) -> None:
        self._age_progress.set_value(self._age_progress.get_value() + days)

    def _is_aging_disabled(self):
        if any(not trait.can_age_up for trait in self.trait_tracker):
            return True
        if self.is_elder and self.is_death_disabled():
            return True
        if self._age_suppression_alarm_handle is not None:
            return True
        return False

    def is_death_disabled(self):
        return any(not trait.can_die for trait in self.trait_tracker)

    def can_age_up(self) -> bool:
        return not self.is_elder and not self._is_aging_disabled()

    @property
    def time_until_age_up(self):
        return self._age_time - self._age_progress.get_value()

    def advance_age(self, force_age=None) -> None:
        current_age = Age(self._base.age)
        next_age = Age(force_age) if force_age is not None else Age.next_age(current_age)
        self._relationship_tracker.update_bits_on_age_up(current_age)
        self.age_progress = 0
        self._dirty_flags = sys.maxsize
        self._base.update_for_age(next_age)
        getOutfitsPB = DistributorOps_pb2.SetSimOutfits()
        getOutfitsPB.ParseFromString(self._base.outfits)
        self._outfits.load_sim_outfits_from_cas_proto(getOutfitsPB)
        self.resend_physical_attributes()
        self._update_age_trait(next_age, current_age)
        self._select_age_trait()
        self.age = next_age
        self.init_child_skills()
        if self.is_teen:
            self.remove_child_only_features()
        sim_instance = self.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)
        if sim_instance is not None:
            with telemetry_helper.begin_hook(writer_age, TELEMETRY_CHANGE_AGE, sim=sim_instance) as hook:
                hook.write_enum('agef', current_age)
                hook.write_enum('aget', next_age)
                sim_instance.schedule_element(services.time_service().sim_timeline, build_element(sim_instance._update_face_and_posture_gen))
                sim_instance._update_multi_motive_buff_trackers()
            if current_age != Age.BABY:
                self.verify_school(from_age_up=True)
                self.remove_invalid_age_based_careers(current_age)
        self.reset_age_progress()
        if self.is_npc:
            if self.is_child or self.is_teen:
                available_aspirations = []
                aspiration_track_manager = services.get_instance_manager(sims4.resources.Types.ASPIRATION_TRACK)
                for aspiration_track in aspiration_track_manager.types.values():
                    if aspiration_track.is_child_aspiration_track:
                        if self.is_child:
                            available_aspirations.append(aspiration_track.guid64)
                            while self.is_teen:
                                available_aspirations.append(aspiration_track.guid64)
                    else:
                        while self.is_teen:
                            available_aspirations.append(aspiration_track.guid64)
                self.primary_aspiration = random.choice(available_aspirations)
            trait_tracker = self.trait_tracker
            empty_trait_slots = trait_tracker.empty_slot_number
            available_traits = [trait for trait in services.trait_manager().types.values() if trait.is_personality_trait]
            while True:
                while empty_trait_slots > 0 and available_traits:
                    trait = random.choice(available_traits)
                    available_traits.remove(trait)
                    if not trait_tracker.can_add_trait(trait, display_warn=False):
                        continue
                    #ERROR: Unexpected statement:   770 POP_BLOCK  |   771 JUMP_ABSOLUTE 812

                    if trait_tracker.add_trait(trait):
                        empty_trait_slots -= 1
                        continue
                        continue
                    continue
        else:
            self.whim_tracker.validate_goals()
            services.social_service.post_aging_message(self, ready_to_age=False)
        client = services.client_manager().get_client_by_household_id(self._household_id)
        if client is None:
            return
        client.selectable_sims.notify_dirty()

    def _suppress_aging_callback(self, _):
        self._age_suppression_alarm_handle = None

    def supress_aging(self):
        if self._age_suppression_alarm_handle is not None:
            logger.warn("Trying to suppress aging when aging is already suppressed. You probably don't want to do be doing this.", owner='jjacobson')
        self._age_suppression_alarm_handle = alarms.add_alarm(self, create_time_span(minutes=AgingTuning.AGE_SUPPRESSION_ALARM_TIME), self._suppress_aging_callback)

