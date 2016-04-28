from away_actions.away_actions_util import PeriodicStatisticChange, TunableAwayActionCondition
from event_testing.results import TestResult
from event_testing.tests import TunableTestSet
from interactions import ParticipantType
from interactions.utils.exit_condition_manager import ConditionalActionManager
from interactions.utils.localization_tokens import LocalizationTokens
from sims4.localization import TunableLocalizedString, TunableLocalizedStringFactory
from sims4.tuning.instances import HashedTunedInstanceMetaclass
from sims4.tuning.tunable import TunableList, TunableResourceKey, HasTunableReference, Tunable, TunableTuple, TunableSet, TunableEnumEntry, TunableReference, OptionalTunable
from sims4.tuning.tunable_base import GroupNames
from sims4.utils import flexmethod, classproperty
from singletons import DEFAULT
from statistics.static_commodity import StaticCommodity
import enum
import event_testing
import services
import sims4
import tag
logger = sims4.log.Logger('AwayAction')

class AwayActionState(enum.Int, export=False):
    __qualname__ = 'AwayActionState'
    INITIALIZED = 0
    RUNNING = 1
    STOPPED = 2

class AwayAction(HasTunableReference, metaclass=HashedTunedInstanceMetaclass, manager=services.get_instance_manager(sims4.resources.Types.AWAY_ACTION)):
    __qualname__ = 'AwayAction'
    INSTANCE_TUNABLES = {'_exit_conditions': TunableList(description='\n                A list of exit conditions for this away action. When exit\n                conditions are met then the away action ends and the default\n                away action is reapplied.\n                ', tunable=TunableTuple(conditions=TunableList(description='\n                        A list of conditions that all must be satisfied for the\n                        group to be considered satisfied.\n                        ', tunable=TunableAwayActionCondition(description='\n                            A condition for an away action.\n                            ')))), '_periodic_stat_changes': PeriodicStatisticChange.TunableFactory(description='\n                Periodic stat changes that this away action applies while it\n                is active.\n                '), 'icon': TunableResourceKey(description='\n                Icon that represents the away action in on the sim skewer.\n                ', default=None, resource_types=sims4.resources.CompoundTypes.IMAGE, tuning_group=GroupNames.UI), 'tooltip': TunableLocalizedStringFactory(description='\n                The tooltip shown on the icon that represents the away action.\n                ', tuning_group=GroupNames.UI), 'pie_menu_tooltip': TunableLocalizedStringFactory(description='\n                The tooltip shown in the pie menu for this away action.\n                ', tuning_group=GroupNames.UI), '_tests': TunableTestSet(description='\n                Tests that determine if this away action is applicable.  These\n                tests do not ensure that the conditions are still met\n                throughout the duration that the away action is applied.\n                '), '_display_name': TunableLocalizedStringFactory(description='\n                The name given to the away action when the user sees it in the\n                pie menu.\n                ', tuning_group=GroupNames.UI), '_display_name_text_tokens': LocalizationTokens.TunableFactory(description="\n                Localization tokens to be passed into 'display_name'.\n                For example, you could use a participant or you could also pass\n                in statistic and commodity values\n                ", tuning_group=GroupNames.UI), '_available_when_instanced': Tunable(description="\n                If this away action is able to be applied when the sim is still\n                instanced.  If the sim becomes instanced while the away action\n                is running we will not stop running it.\n                \n                This should only be true in special cases such as with careers.\n                \n                PLEASE ASK A GPE ABOUT MAKING THIS TRUE BEFORE DOING SO.  YOU\n                PROBABLY DON'T WANT THIS.\n                ", tunable_type=bool, default=False), '_preroll_commodities': TunableList(description='\n                A list of commodities that will be used to run preroll\n                if the sim loaded with this away action.\n                ', tunable=TunableReference(description='\n                    The commodity that is used to solve for preroll if the\n                    sim had this away action on them when they are being loaded.\n                    \n                    This is used to help preserve the fiction of what that sim was\n                    doing when the player returns to the lot.  EX: make the sim\n                    garden if they were using the gardening away action. \n                    ', manager=services.get_instance_manager(sims4.resources.Types.STATISTIC))), '_preroll_static_commodities': TunableList(description='\n                A list of static commodities that will be used to run preroll\n                if the sim loaded with this away action.\n                ', tunable=StaticCommodity.TunableReference(description='\n                    The static commodity that is used to solve for preroll if the\n                    sim had this away action on them when they are being loaded.\n                    \n                    This is used to help preserve the fiction of what that sim was\n                    doing when the player returns to the lot.  EX: make the sim\n                    garden if they were using the gardening away action. \n                    ')), '_apply_on_load_tags': TunableSet(description='\n                A set of tags that are are compared to interaction tags that\n                the sim was running when they became uninstantiated.  If there\n                are any matching tags then this away action will be applied\n                automatically to that sim rather than the default away action.\n                ', tunable=TunableEnumEntry(description='\n                    A single tag that will be compared to the interaction tags.\n                    ', tunable_type=tag.Tag, default=tag.Tag.INVALID)), '_disabled_when_running': OptionalTunable(description='\n                The availability of this away action when it is already the\n                active away action on the sim.\n                ', tunable=TunableLocalizedStringFactory(description='\n                    The text that displays in the tooltip string when this\n                    away action is not available because it is already the\n                    active away action.\n                    '), disabled_name='available_when_running', enabled_name='disabled_when_running'), 'mood_list': TunableList(description='\n                A list of possible moods this AwayAction may associate with.\n                ', tunable=TunableReference(description='\n                    A mood associated with this AwayAction.\n                    ', manager=services.mood_manager()))}

    def __init__(self, tracker, target=None):
        self._tracker = tracker
        self._target = target
        self._conditional_actions_manager = ConditionalActionManager()
        self._periodic_stat_changes_instance = self._periodic_stat_changes(self)
        self._state = AwayActionState.INITIALIZED

    @classmethod
    def should_run_on_load(cls, sim_info):
        for interaction_data in sim_info.si_state.interactions:
            interaction = services.get_instance_manager(sims4.resources.Types.INTERACTION).get(interaction_data.interaction)
            if interaction is None:
                pass
            while len(interaction.get_category_tags() & cls._apply_on_load_tags) > 0:
                return True
        return False

    @classmethod
    def get_commodity_preroll_list(cls):
        if cls._preroll_commodities:
            return cls._preroll_commodities

    @classmethod
    def get_static_commodity_preroll_list(cls):
        if cls._preroll_static_commodities:
            return cls._preroll_static_commodities

    @property
    def sim_info(self):
        return self._tracker.sim_info

    @property
    def sim(self):
        return self.sim_info

    @property
    def target(self):
        return self._target

    @classproperty
    def available_when_instanced(cls):
        return cls._available_when_instanced

    @property
    def is_running(self):
        return self._state == AwayActionState.RUNNING

    def run(self, callback):
        if self._state == AwayActionState.RUNNING:
            logger.callstack('Attempting to start away action that is already running.', owner='jjacobson')
            return
        self._periodic_stat_changes_instance.run()
        if self._exit_conditions:
            self._conditional_actions_manager.attach_conditions(self, self._exit_conditions, callback)
        self._state = AwayActionState.RUNNING

    def stop(self):
        if self._state == AwayActionState.STOPPED:
            logger.callstack('Attempting to stop away action that is already stopped.', owner='jjacobson')
            return
        self._periodic_stat_changes_instance.stop()
        if self._exit_conditions:
            self._conditional_actions_manager.detach_conditions(self)
        self._state = AwayActionState.STOPPED

    @flexmethod
    def get_participant(cls, inst, participant_type=ParticipantType.Actor, **kwargs):
        inst_or_cl = inst if inst is not None else cls
        participants = inst_or_cl.get_participants(participant_type=participant_type, **kwargs)
        if not participants:
            return
        if len(participants) > 1:
            raise ValueError('Too many participants returned for {}!'.format(participant_type))
        return next(iter(participants))

    @flexmethod
    def get_participants(cls, inst, participant_type, sim_info=DEFAULT, target=DEFAULT) -> set:
        inst_or_cls = inst if inst is not None else cls
        sim_info = inst.sim_info if sim_info is DEFAULT else sim_info
        target = inst.target if target is DEFAULT else target
        if sim_info is None:
            logger.error('Sim info is None when trying to get participants for Away Action {}.', inst_or_cls, owner='jjacobson')
            return ()
        results = set()
        participant_type = int(participant_type)
        if participant_type & ParticipantType.Actor:
            results.add(sim_info)
        if participant_type & ParticipantType.Lot:
            zone = services.get_zone(sim_info.zone_id, allow_uninstantiated_zones=True)
            results.add(zone.lot)
        if participant_type & ParticipantType.TargetSim and target is not None:
            results.add(target)
        return tuple(results)

    @flexmethod
    def get_resolver(cls, inst, **away_action_parameters):
        inst_or_cls = inst if inst is not None else cls
        return event_testing.resolver.AwayActionResolver(inst_or_cls, **away_action_parameters)

    @flexmethod
    def get_localization_tokens(cls, inst, **away_action_parameters):
        inst_or_cls = inst if inst is not None else cls
        tokens = inst_or_cls._display_name_text_tokens.get_tokens(inst_or_cls.get_resolver(**away_action_parameters))
        return tokens

    @flexmethod
    def test(cls, inst, sim_info=DEFAULT, **away_action_parameters):
        inst_or_cls = inst if inst is not None else cls
        sim_info = inst.sim_info if sim_info is DEFAULT else sim_info
        current_away_action = sim_info.current_away_action
        if inst_or_cls._disabled_when_running and current_away_action is not None and isinstance(current_away_action, cls):
            return TestResult(False, 'Cannot run away action when it is already running', tooltip=inst_or_cls._disabled_when_running)
        resolver = inst_or_cls.get_resolver(sim_info=sim_info, **away_action_parameters)
        if inst is None:
            condition_actions_manager = ConditionalActionManager()
        else:
            condition_actions_manager = inst._conditional_actions_manager
        if inst_or_cls._exit_conditions and condition_actions_manager.callback_will_trigger_immediately(resolver, inst_or_cls._exit_conditions):
            return TestResult(False, 'Away Action cannot run since exit conditions will satisfy immediately.')
        return inst_or_cls._tests.run_tests(resolver)

    @flexmethod
    def get_display_name(cls, inst, *tokens, **away_action_parameters):
        inst_or_cls = inst if inst is not None else cls
        localization_tokens = inst_or_cls.get_localization_tokens(**away_action_parameters)
        return inst_or_cls._display_name(*localization_tokens + tokens)

