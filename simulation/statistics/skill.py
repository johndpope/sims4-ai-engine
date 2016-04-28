from protocolbuffers import Commodities_pb2
import collections
import operator
from event_testing import test_events
from event_testing.resolver import SingleSimResolver
from sims import sim_info_types
from sims4.localization import TunableLocalizedString
from sims4.math import Threshold
from sims4.tuning.dynamic_enum import DynamicEnum
from sims4.tuning.geometric import TunableVector2, TunableCurve
from sims4.tuning.instances import HashedTunedInstanceMetaclass
from sims4.tuning.tunable import Tunable, TunableList, TunableEnumEntry, TunableMapping, TunableEntitlement, TunableSet, TunableResourceKey, TunableTuple, OptionalTunable, TunableInterval, TunableReference, TunableRange, HasTunableReference
from sims4.tuning.tunable_base import ExportModes, GroupNames
from sims4.utils import classproperty
from singletons import DEFAULT
from statistics.base_statistic import StatisticChangeDirection
from statistics.tunable import TunableStatAsmParam
from ui.ui_dialog import UiDialogResponse
from ui.ui_dialog_notification import UiDialogNotification
import caches
import enum
import gsi_handlers.sim_handlers_log
import mtx
import services.social_service
import sims4.log
import statistics.continuous_statistic_tuning
import tag
import telemetry_helper
import ui.screen_slam
logger = sims4.log.Logger('Skills')
TELEMETRY_GROUP_SKILLS = 'SKIL'
TELEMETRY_HOOK_SKILL_LEVEL_UP = 'SKLU'
TELEMETRY_HOOK_SKILL_INTERACTION = 'SKIA'
TELEMETRY_HOOK_SKILL_INTERACTION_FIRST_TIME = 'SKIF'
TELEMETRY_FIELD_SKILL_ID = 'skid'
TELEMETRY_FIELD_SKILL_LEVEL = 'sklv'
TELEMETRY_FIELD_SKILL_AFFORDANCE = 'skaf'
TELEMETRY_FIELD_SKILL_AFFORDANCE_SUCCESS = 'safs'
TELEMETRY_FIELD_SKILL_AFFORDANCE_VALUE_ADD = 'safv'
TELEMETRY_INTERACTION_NOT_AVAILABLE = 'not_available'
skill_telemetry_writer = sims4.telemetry.TelemetryWriter(TELEMETRY_GROUP_SKILLS)

class SkillLevelType(enum.Int):
    __qualname__ = 'SkillLevelType'
    MAJOR = 0
    MINOR = 1
    CHILD = 2
    TEEN = 3

class SkillEffectiveness(DynamicEnum):
    __qualname__ = 'SkillEffectiveness'
    STANDARD = 0

class TunableSkillMultiplier(TunableTuple):
    __qualname__ = 'TunableSkillMultiplier'

    def __init__(self, **kwargs):
        super().__init__(affordance_list=TunableList(description='\n                List of affordances this multiplier will effect.\n                ', tunable=TunableReference(manager=services.affordance_manager(), reload_dependent=True)), curve=TunableCurve(description='\n                Tunable curve where the X-axis defines the skill level, and\n                the Y-axis defines the associated multiplier.\n                ', x_axis_name='Skill Level', y_axis_name='Multiplier'), use_effective_skill=Tunable(description='\n                If checked, this modifier will look at the current\n                effective skill value.  If unchecked, this modifier will\n                look at the actual skill value.\n                ', tunable_type=bool, needs_tuning=True, default=True), **kwargs)

class Skill(HasTunableReference, statistics.continuous_statistic_tuning.TunedContinuousStatistic, metaclass=HashedTunedInstanceMetaclass, manager=services.get_instance_manager(sims4.resources.Types.STATISTIC)):
    __qualname__ = 'Skill'
    SKILL_LEVEL_LIST = TunableMapping(key_type=TunableEnumEntry(SkillLevelType, SkillLevelType.MAJOR), value_type=TunableList(Tunable(int, 0), description='The level boundaries for skill type, specified as a delta from the previous value'), export_modes=ExportModes.All)
    SKILL_EFFECTIVENESS_GAIN = TunableMapping(key_type=TunableEnumEntry(SkillEffectiveness, SkillEffectiveness.STANDARD), value_type=TunableCurve(), description='Skill gain points based on skill effectiveness.')
    DYNAMIC_SKILL_INTERVAL = TunableRange(description='\n        Interval used when dynamic loot is used in a\n        PeriodicStatisticChangeElement.\n        ', tunable_type=float, default=1, minimum=1)
    INSTANCE_TUNABLES = {'stat_name': TunableLocalizedString(description='\n            Localized name of this Statistic\n            ', export_modes=ExportModes.All), 'ad_data': TunableList(description='\n            A list of Vector2 points that define the desire curve for this\n            commodity.\n            ', tunable=TunableVector2(description='\n                Point on a Curve\n                ', default=sims4.math.Vector2(0, 0))), 'weight': Tunable(description="\n            The weight of the Skill with regards to autonomy.  It's ignored \n            for the purposes of sorting stats, but it's applied when scoring \n            the actual statistic operation for the SI.\n            ", tunable_type=float, default=0.5), 'skill_level_type': TunableEnumEntry(description='\n            Skill level list to use.\n            ', tunable_type=SkillLevelType, default=SkillLevelType.MAJOR, export_modes=ExportModes.All), 'locked_description': TunableLocalizedString(description="\n            The skill description when it's locked.\n            ", export_modes=ExportModes.All), 'skill_description': TunableLocalizedString(description="\n            The skill's normal description.\n            ", export_modes=ExportModes.All), 'is_default': Tunable(description='\n            Whether Sim will default has this skill.\n            ', tunable_type=bool, default=False), 'genders': TunableSet(description='\n            Skill allowed gender, empty set means not specified\n            ', tunable=TunableEnumEntry(tunable_type=sim_info_types.Gender, default=None, export_modes=ExportModes.All)), 'ages': TunableSet(description='\n            Skill allowed ages, empty set means not specified\n            ', tunable=TunableEnumEntry(tunable_type=sim_info_types.Age, default=None, export_modes=ExportModes.All)), 'entitlement': TunableEntitlement(description='\n            Entitlement required to use this skill.\n            '), 'icon': TunableResourceKey(description='\n            Icon to be displayed for the Skill.\n            ', default='PNG:missing_image', resource_types=sims4.resources.CompoundTypes.IMAGE, export_modes=ExportModes.All), 'tags': TunableList(description='\n            The associated categories of the skill\n            ', tunable=TunableEnumEntry(tunable_type=tag.Tag, default=tag.Tag.INVALID)), 'priority': Tunable(description='\n            Skill priority.  Higher priority skill will trump other skills when\n            being displayed on the UI side. When a sim gains multiple skills at\n            the same time only the highest priority one will display a progress\n            bar over its head.\n            ', tunable_type=int, default=1, export_modes=ExportModes.All), 'statistic_multipliers': TunableMapping(description='\n            Multipliers this skill applies to other statistics based on its\n            value.\n            ', key_type=TunableReference(description='\n                The statistic this multiplier will be applied to.\n                ', manager=services.statistic_manager(), reload_dependent=True), value_type=TunableTuple(curve=TunableCurve(description='\n                    Tunable curve where the X-axis defines the skill level, and\n                    the Y-axis defines the associated multiplier.\n                    ', x_axis_name='Skill Level', y_axis_name='Multiplier'), direction=TunableEnumEntry(description="\n                    Direction where the multiplier should work on the\n                    statistic.  For example, a tuned decrease for an object's\n                    brokenness rate will not also increase the time it takes to\n                    repair it.\n                    ", tunable_type=StatisticChangeDirection, default=StatisticChangeDirection.INCREASE), use_effective_skill=Tunable(description='\n                    If checked, this modifier will look at the current\n                    effective skill value.  If unchecked, this modifier will\n                    look at the actual skill value.\n                    ', tunable_type=bool, needs_tuning=True, default=True)), tuning_group=GroupNames.MULTIPLIERS), 'success_chance_multipliers': TunableList(description='\n            Multipliers this skill applies to the success chance of\n            affordances.\n            ', tunable=TunableSkillMultiplier(), tuning_group=GroupNames.MULTIPLIERS), 'monetary_payout_multipliers': TunableList(description='\n            Multipliers this skill applies to the monetary payout amount of\n            affordances.\n            ', tunable=TunableSkillMultiplier(), tuning_group=GroupNames.MULTIPLIERS), 'next_level_teaser': TunableList(description='\n            Tooltip which describes what the next level entails.\n            ', tunable=TunableLocalizedString(), export_modes=(ExportModes.ClientBinary,)), 'level_data': TunableMapping(description='\n            Level-specific information, such as notifications to be displayed to\n            level up.\n            ', key_type=int, value_type=TunableTuple(level_up_notification=UiDialogNotification.TunableFactory(description='\n                    The notification to display when the Sim obtains this level.\n                    The text will be provided two tokens: the Sim owning the\n                    skill and a number representing the 1-based skill level\n                    ', locked_args={'text_tokens': DEFAULT, 'icon': None, 'primary_icon_response': UiDialogResponse(text=None, ui_request=UiDialogResponse.UiDialogUiRequest.SHOW_SKILL_PANEL), 'secondary_icon': None}), level_up_screen_slam=OptionalTunable(description='\n                    Screen slam to show when reaches this skill level.\n                    Localization Tokens: Sim - {0.SimFirstName}, Skill Name - \n                    {1.String}, Skill Number - {2.Number}\n                    ', tunable=ui.screen_slam.TunableScreenSlamSnippet(), tuning_group=GroupNames.UI))), 'mood_id': TunableReference(description='\n            When this mood is set and active sim matches mood, the UI will \n            display a special effect on the skill bar to represent that this \n            skill is getting a bonus because of the mood.\n            ', manager=services.mood_manager(), export_modes=ExportModes.All), 'stat_asm_param': TunableStatAsmParam.TunableFactory(), 'tutorial': TunableReference(description='\n            Tutorial instance for this skill. This will be used to bring up the \n            skill lesson from the first notification for Sim to know this skill.\n            ', manager=services.get_instance_manager(sims4.resources.Types.TUTORIAL), class_restrictions=('Tutorial',)), 'skill_unlocks_on_max': TunableList(description='\n            A list of skills that become unlocked when this skill is maxed.\n            ', tunable=TunableReference(description='\n                A skill to unlock.\n                ', manager=services.get_instance_manager(sims4.resources.Types.STATISTIC), class_restrictions=('Skill',)))}
    REMOVE_INSTANCE_TUNABLES = ('min_value_tuning', 'max_value_tuning', 'decay_rate', '_default_convergence_value')

    def __init__(self, tracker):
        super().__init__(tracker, self.initial_value)
        self._delta_enabled = True
        self._callback_handle = None
        if self.tracker.owner.is_simulating:
            self.on_initial_startup()
        self._max_level_update_sent = False

    def on_initial_startup(self):
        if self.tracker.owner.is_selectable:
            self.refresh_level_up_callback()

    def on_remove(self, on_destroy=False):
        super().on_remove(on_destroy=on_destroy)
        self._destory_callback_handle()

    def _apply_multipliers_to_continuous_statistics(self):
        for stat in self.statistic_multipliers:
            while stat.continuous:
                owner_stat = self.tracker.get_statistic(stat)
                if owner_stat is not None:
                    owner_stat._recalculate_modified_decay_rate()

    @caches.cached
    def get_user_value(self):
        return super(Skill, self).get_user_value()

    def set_value(self, value, *args, from_load=False, interaction=None, **kwargs):
        old_value = self.get_value()
        super().set_value(value, *args, **kwargs)
        self.get_user_value.cache.clear()
        if not from_load:
            new_value = self.get_value()
            new_level = self.convert_to_user_value(value)
            if old_value == self.initial_value and old_value != new_value:
                sim_info = self._tracker._owner
                services.get_event_manager().process_event(test_events.TestEvent.SkillLevelChange, sim_info=sim_info, statistic=self.stat_type)
            old_level = self.convert_to_user_value(old_value)
            if old_level < new_level:
                self._apply_multipliers_to_continuous_statistics()

    def add_value(self, add_amount, interaction=None, **kwargs):
        old_value = self.get_value()
        if old_value == self.initial_value:
            telemhook = TELEMETRY_HOOK_SKILL_INTERACTION_FIRST_TIME
        else:
            telemhook = TELEMETRY_HOOK_SKILL_INTERACTION
        super().add_value(add_amount, interaction=interaction)
        self.get_user_value.cache.clear()
        if interaction is not None:
            self.on_skill_updated(telemhook, old_value, self.get_value(), interaction.affordance.__name__)

    def _update_value(self):
        old_value = self._value
        if gsi_handlers.sim_handlers_log.skill_change_archiver.enabled:
            last_update = self._last_update
        time_delta = super()._update_value()
        self.get_user_value.cache.clear()
        new_value = self._value
        if old_value == self.initial_value:
            telemhook = TELEMETRY_HOOK_SKILL_INTERACTION_FIRST_TIME
            self.on_skill_updated(telemhook, old_value, new_value, TELEMETRY_INTERACTION_NOT_AVAILABLE)
            sim_info = self._tracker._owner
            services.get_event_manager().process_event(test_events.TestEvent.SkillLevelChange, sim_info=sim_info, statistic=self.stat_type)
        old_level = self.convert_to_user_value(old_value)
        new_level = self.convert_to_user_value(new_value)
        if gsi_handlers.sim_handlers_log.skill_change_archiver.enabled and self.tracker.owner.is_sim:
            gsi_handlers.sim_handlers_log.archive_skill_change(self.tracker.owner, self, time_delta, old_value, new_value, new_level, last_update)
        if old_value < new_value and old_level < new_level:
            if self._tracker is not None:
                self._tracker.notify_watchers(self.stat_type, self._value, self._value)

    def on_skill_updated(self, telemhook, old_value, new_value, affordance_name):
        owner_sim = self._tracker._owner
        if owner_sim.is_selectable:
            with telemetry_helper.begin_hook(skill_telemetry_writer, telemhook, sim=owner_sim) as hook:
                hook.write_guid(TELEMETRY_FIELD_SKILL_ID, self.guid64)
                hook.write_string(TELEMETRY_FIELD_SKILL_AFFORDANCE, affordance_name)
                hook.write_bool(TELEMETRY_FIELD_SKILL_AFFORDANCE_SUCCESS, True)
                hook.write_int(TELEMETRY_FIELD_SKILL_AFFORDANCE_VALUE_ADD, new_value - old_value)
        if old_value == self.initial_value:
            skill_level = self.convert_to_user_value(old_value)
            self._show_level_notification(skill_level)

    def _destory_callback_handle(self):
        if self._callback_handle is not None:
            self.remove_callback(self._callback_handle)
            self._callback_handle = None

    def refresh_level_up_callback(self):
        self._destory_callback_handle()

        def _on_level_up_callback(stat_inst):
            new_level = stat_inst.get_user_value()
            old_level = new_level - 1
            stat_inst.on_skill_level_up(old_level, new_level)
            stat_inst.refresh_level_up_callback()

        self._callback_handle = self.add_callback(Threshold(self._get_next_level_bound(), operator.ge), _on_level_up_callback)

    def on_skill_level_up(self, old_level, new_level):
        tracker = self.tracker
        sim_info = tracker._owner
        if self.reached_max_level:
            for skill in self.skill_unlocks_on_max:
                skill_instance = tracker.add_statistic(skill, force_add=True)
                skill_instance.set_value(skill.initial_value)
        with telemetry_helper.begin_hook(skill_telemetry_writer, TELEMETRY_HOOK_SKILL_LEVEL_UP, sim=sim_info) as hook:
            hook.write_guid(TELEMETRY_FIELD_SKILL_ID, self.guid64)
            hook.write_int(TELEMETRY_FIELD_SKILL_LEVEL, new_level)
        if sim_info.account is not None:
            services.social_service.post_skill_message(sim_info, self, old_level, new_level)
        self._show_level_notification(new_level)
        services.get_event_manager().process_event(test_events.TestEvent.SkillLevelChange, sim_info=sim_info, statistic=self.stat_type)

    def _show_level_notification(self, skill_level):
        sim_info = self._tracker._owner
        if not sim_info.is_npc:
            level_data = self.level_data.get(skill_level)
            if level_data is not None:
                tutorial_id = None
                if self.tutorial is not None and skill_level == 1:
                    tutorial_id = self.tutorial.guid64
                notification = level_data.level_up_notification(sim_info, resolver=SingleSimResolver(sim_info))
                notification.show_dialog(icon_override=(self.icon, None), secondary_icon_override=(None, sim_info), additional_tokens=(skill_level,), tutorial_id=tutorial_id)
                if level_data.level_up_screen_slam is not None:
                    level_data.level_up_screen_slam.send_screen_slam_message(sim_info, sim_info, self.stat_name, skill_level)

    @classproperty
    def skill_type(cls):
        return cls

    @classproperty
    def remove_on_convergence(cls):
        return False

    @classmethod
    def can_add(cls, owner, force_add=False, **kwargs):
        if force_add:
            return True
        if cls.genders and owner.gender not in cls.genders:
            return False
        if cls.ages and owner.age not in cls.ages:
            return False
        if cls.entitlement is None:
            return True
        if owner.is_npc:
            return False
        return mtx.has_entitlement(cls.entitlement)

    @classmethod
    def get_level_list(cls):
        return cls.SKILL_LEVEL_LIST.get(cls.skill_level_type)

    @classmethod
    def get_max_skill_value(cls):
        level_list = cls.get_level_list()
        return sum(level_list)

    @classmethod
    def get_skill_value_for_level(cls, level):
        level_list = cls.get_level_list()
        if level > len(level_list):
            logger.error('Level {} out of bounds', level)
            return 0
        return sum(level_list[:level])

    @classmethod
    def get_skill_effectiveness_points_gain(cls, effectiveness_level, level):
        skill_gain_curve = cls.SKILL_EFFECTIVENESS_GAIN.get(effectiveness_level)
        if skill_gain_curve is not None:
            return skill_gain_curve.get(level)
        logger.error('{} does not exist in SKILL_EFFECTIVENESS_GAIN mapping', effectiveness_level)
        return 0

    @classmethod
    def _tuning_loaded_callback(cls):
        super()._tuning_loaded_callback()
        level_list = cls.get_level_list()
        cls.max_level = len(level_list)
        cls.min_value_tuning = 0
        cls.max_value_tuning = sum(level_list)
        cls._default_convergence_value = cls.min_value_tuning
        cls._build_utility_curve_from_tuning_data(cls.ad_data)
        for stat in cls.statistic_multipliers:
            multiplier = cls.statistic_multipliers[stat]
            curve = multiplier.curve
            direction = multiplier.direction
            use_effective_skill = multiplier.use_effective_skill
            stat.add_skill_based_statistic_multiplier(cls, curve, direction, use_effective_skill)
        for multiplier in cls.success_chance_multipliers:
            curve = multiplier.curve
            use_effective_skill = multiplier.use_effective_skill
            for affordance in multiplier.affordance_list:
                affordance.add_skill_multiplier(affordance.success_chance_multipliers, cls, curve, use_effective_skill)
        for multiplier in cls.monetary_payout_multipliers:
            curve = multiplier.curve
            use_effective_skill = multiplier.use_effective_skill
            for affordance in multiplier.affordance_list:
                affordance.add_skill_multiplier(affordance.monetary_payout_multipliers, cls, curve, use_effective_skill)

    @classmethod
    def _verify_tuning_callback(cls):
        success_multiplier_affordances = []
        for multiplier in cls.success_chance_multipliers:
            success_multiplier_affordances.extend(multiplier.affordance_list)
        if len(success_multiplier_affordances) != len(set(success_multiplier_affordances)):
            logger.error("The same affordance has been tuned more than once under {}'s success multipliers, and they will overwrite each other. Please fix in tuning.", cls, owner='tastle')
        monetary_payout_multiplier_affordances = []
        for multiplier in cls.monetary_payout_multipliers:
            monetary_payout_multiplier_affordances.extend(multiplier.affordance_list)
        if len(monetary_payout_multiplier_affordances) != len(set(monetary_payout_multiplier_affordances)):
            logger.error("The same affordance has been tuned more than once under {}'s monetary payout multipliers, and they will overwrite each other. Please fix in tuning.", cls, owner='tastle')

    @classmethod
    def convert_to_user_value(cls, value):
        if not cls.get_level_list():
            return 0
        current_value = value
        for (level, level_threshold) in enumerate(cls.get_level_list()):
            current_value -= level_threshold
            while current_value < 0:
                return level
        return level + 1

    @classmethod
    def convert_from_user_value(cls, user_value):
        (level_min, _) = cls._get_level_bounds(user_value)
        return level_min

    @classmethod
    def _get_level_bounds(cls, level):
        level_list = cls.get_level_list()
        level_min = sum(level_list[:level])
        if level < cls.max_level:
            level_max = sum(level_list[:level + 1])
        else:
            level_max = sum(level_list)
        return (level_min, level_max)

    def _get_next_level_bound(self):
        level = self.convert_to_user_value(self._value)
        (_, level_max) = self._get_level_bounds(level)
        return level_max

    @property
    def reached_max_level(self):
        max_value = self.get_max_skill_value()
        if self.get_value() >= max_value:
            return True
        return False

    @property
    def should_send_update(self):
        if not self.reached_max_level:
            return True
        if not self._max_level_update_sent:
            self._max_level_update_sent = True
            return True
        return False

    @classproperty
    def is_skill(cls):
        return True

    @classproperty
    def autonomy_weight(cls):
        return cls.weight

    @classmethod
    def create_skill_update_msg(cls, sim_id, stat_value):
        if not cls.convert_to_user_value(stat_value) > 0:
            return
        skill_msg = Commodities_pb2.Skill_Update()
        skill_msg.skill_id = cls.guid64
        skill_msg.curr_points = int(stat_value)
        skill_msg.sim_id = sim_id
        return skill_msg

    @property
    def is_initial_value(self):
        return self.initial_value == self.get_value()

    @classproperty
    def valid_for_stat_testing(cls):
        return True

_SkillLootData = collections.namedtuple('_SkillLootData', ['level_range', 'stat', 'effectiveness'])
EMPTY_SKILL_LOOT_DATA = _SkillLootData(None, None, None)

class TunableSkillLootData(TunableTuple):
    __qualname__ = 'TunableSkillLootData'

    def __init__(self, **kwargs):
        super().__init__(level_range=OptionalTunable(TunableInterval(description="\n                            Interval is used to clamp the sim's user facing\n                            skill level to determine how many point to give. If\n                            disabled, level passed to the dynamic skill loot\n                            will always be the current user facing skill level\n                            of sim. \n                            Example: if sim is level 7 in fitness but\n                            interaction skill level is only for 1 to 5 give the\n                            dynamic skill amount as if sim is level 5.\n                            ", tunable_type=int, default_lower=0, default_upper=1, minimum=0)), stat=TunableReference(description='\n                             The statistic we are operating on.\n                             ', manager=services.get_instance_manager(sims4.resources.Types.STATISTIC), class_restrictions=Skill), effectiveness=TunableEnumEntry(description='\n                             Enum to determine which curve to use when giving\n                             points to sim.\n                             ', tunable_type=SkillEffectiveness, needs_tuning=True, default=None), **kwargs)

