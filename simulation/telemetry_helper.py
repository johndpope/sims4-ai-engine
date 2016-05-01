import collections
from date_and_time import create_time_span
from objects import ALL_HIDDEN_REASONS
from sims4.telemetry import RuleAction
from sims4.tuning.tunable import Tunable, TunableRange, TunableList, TunableTuple, TunableEnumEntry
import alarms
import services
import sims4.telemetry
import sims4.zone_utils
TELEMETRY_GROUP_REPORT = 'REPO'
TELEMETRY_HOOK_BUFF_REPORT = 'BUFF'
TELEMETRY_HOOK_EMOTION_REPORT = 'EMOT'
TELEMETRY_HOOK_FUNDS_REPORT = 'FUND'
TELEMETRY_HOOK_RELATIONSHIP_REPORT = 'RELA'
TELEMETRY_TARGET_SIM_ID = 'tsim'
TELEMETRY_BUFF_ID = 'bfid'
TELEMETRY_BUFF_REASON = 'reas'
TELEMETRY_REL_BIT_ID = 'biid'
TELEMETRY_REL_BIT_COUNT = 'cico'
TELEMETRY_EMOTION_ID = 'emot'
TELEMETRY_EMOTION_INTENSITY = 'inte'
TELEMETRY_HOUSEHOLD_FUNDS = 'fund'
report_telemetry_writer = sims4.telemetry.TelemetryWriter(
    TELEMETRY_GROUP_REPORT)


def _classify_sim(sim, household):
    if household.is_persistent_npc:
        return 4
    if household.is_npc_household:
        return 3
    client = services.client_manager().get_client_by_household_id(household.id)
    if sim == client.active_sim:
        return 1
    return 2


def _write_common_data(hook, sim=None, household=None, session_id=None):
    if sim is not None:
        if not hook.valid_for_npc and sim.is_npc:
            hook.disabled_hook = True
        sim_id = sim.id
        if household is None:
            household = sim.household
        mood = sim.get_mood()
        if mood is not None:
            sim_mood = mood.guid64
        else:
            sim_mood = 0
    else:
        sim_id = 0
        sim_mood = 0
    sim_classification = 0
    if household is not None:
        household_id = household.id
        account = household.account
        if sim is not None:
            sim_classification = _classify_sim(sim, household)
        if session_id is None:
            zone_id = sims4.zone_utils.get_zone_id(can_be_none=True)
            if zone_id is not None:
                client = account.get_client(zone_id)
                if client is not None:
                    session_id = client.id
    else:
        household_id = 0
    if session_id is None:
        session_id = 0
    time_service = services.time_service()
    sim_time = int(time_service.sim_now.absolute_seconds())
    sims4.telemetry._write_common_data(hook, sim_id, household_id, session_id,
                                       sim_time, sim_mood, sim_classification)


def begin_hook(writer, hook_tag, valid_for_npc=False, **kwargs):
    hook = writer.begin_hook(hook_tag, valid_for_npc=valid_for_npc)
    _write_common_data(hook, **kwargs)
    return hook


class TelemetryTuning:
    __qualname__ = 'TelemetryTuning'
    BUFF_ALARM_TIME = TunableRange(
        description=
        "\n        Integer value in sim minutes in which the buff alarm will trigger to \n        send a telemetry report of current active buff's on the household sims.\n        ",
        tunable_type=int,
        minimum=1,
        default=60)
    EMOTION_REL_ALARM_TIME = TunableRange(
        description=
        '\n        Integer value in sim minutes in which the emotion and relationship \n        alarm will trigger to send a telemetry report of the emotion and \n        relationship status of the household sims.\n        ',
        tunable_type=int,
        minimum=1,
        default=60)
    HOOK_ACTIONS = TunableList(
        description=
        '\n        List of hook actions that we want to drop or collect to create rules \n        to disable them from triggering.\n        ',
        tunable=TunableTuple(
            description='\n            Hook actions.\n            ',
            module_tag=Tunable(
                description=
                "\n                Module identifier of the hook where the action should be \n                applied.\n                Can be empty if we want to apply an action by only group or \n                hook tag. \n                e.g. 'GAME'.  \n                ",
                tunable_type=str,
                default=''),
            group_tag=Tunable(
                description=
                "\n                Group identifier of the hook where the action should be \n                applied.\n                Can be empty if we want to apply an action by only module or \n                hook tag.\n                e.g. 'WHIM'\n                ",
                tunable_type=str,
                default=''),
            hook_tag=Tunable(
                description=
                "\n                Tag identifier of the hook where the action should be \n                applied.\n                Can be empty if we want to apply an action by only module or \n                group tag.\n                e.g. 'WADD'\n                ",
                tunable_type=str,
                default=''),
            priority=Tunable(
                description=
                "\n                Priority for this rule to apply.  The rules are sorted in \n                priority order (lowest priority first).  The the first rule \n                that matches a hook causes the hook to be blocked or collected, \n                depending on the value of action. \n                e.g. We can have an action to COLLECT hook {GAME, WHIM, WADD} \n                with priority 0, and an action to DROP hooks with module 'GAME'\n                {GAME, '', ''} with priority 1, this means the collected hook\n                action will have more importance than the rule to drop all \n                GAME hooks.                \n                ",
                tunable_type=int,
                default=0),
            action=TunableEnumEntry(
                description=
                '\n                Action to take for the specified tags. \n                COLLECT to enable the hook.\n                DROP to disable the hook.\n                ',
                tunable_type=RuleAction,
                default=RuleAction.DROP)))

    @classmethod
    def filter_tunable_hooks(cls):
        for hook in TelemetryTuning.HOOK_ACTIONS:
            module_tag = hook.module_tag
            group_tag = hook.group_tag
            hook_tag = hook.hook_tag
            if module_tag == '':
                module_tag = None
            if group_tag == '':
                group_tag = None
            if hook_tag == '':
                hook_tag = None
            sims4.telemetry.add_filter_rule(hook.priority, module_tag,
                                            group_tag, hook_tag, None,
                                            hook.action)


class HouseholdTelemetryTracker:
    __qualname__ = 'HouseholdTelemetryTracker'

    def __init__(self, household):
        self._buff_alarm = None
        self._emotion_relationship_alarm = None
        self._household = household

    def initialize_alarms(self):
        if self._buff_alarm is not None:
            alarms.cancel_alarm(self._buff_alarm)
        self._buff_alarm = alarms.add_alarm(
            self,
            create_time_span(minutes=TelemetryTuning.BUFF_ALARM_TIME),
            self.buff_telemetry_report,
            True)
        if self._emotion_relationship_alarm is not None:
            alarms.cancel_alarm(self._emotion_relationship_alarm)
        self._emotion_relationship_alarm = alarms.add_alarm(
            self,
            create_time_span(minutes=TelemetryTuning.EMOTION_REL_ALARM_TIME),
            self.emotion_relation_telemetry_report,
            True)

    def buff_telemetry_report(self, handle):
        for sim in self._household.instanced_sims_gen(
                allow_hidden_flags=ALL_HIDDEN_REASONS):
            with begin_hook(report_telemetry_writer,
                            TELEMETRY_HOOK_EMOTION_REPORT,
                            sim=sim) as hook:
                hook.write_guid(TELEMETRY_EMOTION_ID, sim.get_mood().guid64)
                hook.write_int(TELEMETRY_EMOTION_INTENSITY,
                               sim.get_mood_intensity())
            for buff in sim.Buffs:
                if buff.visible == False:
                    pass
                with begin_hook(report_telemetry_writer,
                                TELEMETRY_HOOK_BUFF_REPORT,
                                sim=sim) as hook:
                    hook.write_guid(TELEMETRY_BUFF_ID, buff.guid64)
                    if buff.buff_reason is not None:
                        hook.write_localized_string(TELEMETRY_BUFF_REASON,
                                                    buff.buff_reason)
                    else:
                        hook.write_guid(TELEMETRY_BUFF_REASON, 0)

    def emotion_relation_telemetry_report(self, handle):
        household_bit_dict = collections.defaultdict(lambda: 0)
        for sim in self._household.instanced_sims_gen(
                allow_hidden_flags=ALL_HIDDEN_REASONS):
            for bit in sim.sim_info.relationship_tracker.get_all_bits(
                    allow_dead_targets=False):
                household_bit_dict[bit.guid64] += 1
        for (bit_id, bit_count) in household_bit_dict.items():
            with begin_hook(report_telemetry_writer,
                            TELEMETRY_HOOK_RELATIONSHIP_REPORT,
                            household=self._household) as hook:
                hook.write_guid(TELEMETRY_REL_BIT_ID, bit_id)
                hook.write_int(TELEMETRY_REL_BIT_COUNT, bit_count)
        with begin_hook(report_telemetry_writer,
                        TELEMETRY_HOOK_FUNDS_REPORT,
                        household=self._household) as hook:
            hook.write_int(TELEMETRY_HOUSEHOLD_FUNDS,
                           self._household.funds.money)

    def on_client_disconnect(self):
        if self._buff_alarm is not None:
            alarms.cancel_alarm(self._buff_alarm)
            self._buff_alarm = None
        if self._emotion_relationship_alarm is not None:
            alarms.cancel_alarm(self._emotion_relationship_alarm)
            self._emotion_relationship_alarm = None
