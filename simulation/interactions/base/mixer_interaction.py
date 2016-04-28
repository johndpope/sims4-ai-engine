#ERROR: jaddr is None
#ERROR: jaddr is None
from protocolbuffers import Sims_pb2 as protocols
import weakref
from animation import posture_manifest
from element_utils import build_critical_section_with_finally
from event_testing.results import TestResult
from interactions import ParticipantType
from interactions.aop import AffordanceObjectPair
from interactions.base.interaction import Interaction, TargetType, LockGuaranteedOnSIWhileRunning, LOCK_GUARANTEED_ON_SI_WHILE_RUNNING, InteractionQueuePreparationStatus
from interactions.constraints import RequiredSlotSingle
from interactions.context import InteractionContext, QueueInsertStrategy
from interactions.interaction_finisher import FinishingType
from interactions.utils.common import SCRIPT_EVENT_ID_PLUMBBOB_SHEEN
from interactions.utils.outcome import TunableOutcome
from sims4.localization import TunableLocalizedStringFactory
from sims4.tuning.instances import lock_instance_tunables
from sims4.tuning.tunable import Tunable, TunableTuple, TunableReference, OptionalTunable, TunableSet, TunableInterval, TunableSimMinute, TunableMapping, TunableList, TunableRange, TunableEnumEntry
from sims4.tuning.tunable_base import GroupNames, FilterTag
from sims4.utils import flexmethod, classproperty, flexproperty
from singletons import DEFAULT
import gsi_handlers.interaction_archive_handlers
import gsi_handlers.sim_timeline_handlers
import interactions.constraints
import performance.counters
import services
import sims4.log
import sims4.resources
logger = sims4.log.Logger('MixerInteraction')

class MixerInteraction(Interaction):
    __qualname__ = 'MixerInteraction'
    INSTANCE_TUNABLES = {'display_name_target': TunableLocalizedStringFactory(description="\n            Display text of target of mixer interaction. Example: Sim A queues\n            'Tell Joke', Sim B will see in their queue 'Be Told Joke'\n            ", tuning_group=GroupNames.UI), 'sub_action': TunableTuple(description='\n            Sub-Action scoring: The base_weight tuned here is used to determine\n            the autonomy score for choosing this mixer interaction.\n                                   \n            Example: If you like to see this mixer to be chosen more by\n            autonomous sims tune this value higher.  If you want the mixer to\n            chosen less likely keep the value small.\n                                   \n            Formula being used to determine the autonomy score is Score =\n            Avg(Uc, Ucs) * W * SW, Where Uc is the commodity score, Ucs is the\n            content set score, W is the weight tuned the on mixer, and SW is the\n            weight tuned on the super interaction.\n            ', tuning_group=GroupNames.AUTONOMY, base_weight=TunableRange(description='\n                The base weight of the subaction (0 means this action is not\n                considered for subaction autonomy)\n                ', tunable_type=int, minimum=0, default=1), mixer_group=TunableEnumEntry(description='\n                            The group this mixer belongs to.  This will directly affect the scoring \n                            of subaction autonomy.  When subaction autonomy runs and chooses the \n                            mixer provider for the sim to express, the sim will gather all mixers \n                            for that provider.  She will then choose one of the categories based on \n                            a weighted random, then score the mixers only in that group.  The weights\n                            are tuned in autonomy_modes with the SUBACTION_GROUP_WEIGHTING tunable\n                            mapping.\n                            \n                            Example: Say you have two groups: DEFAULT and IDLES.  You could set up \n                            the SUBACTION_GROUP_WEIGHTING mapping such that DEFAULT has a weight of 3 \n                            and IDLES has a weight of 7.  When a sim needs to decide which set of mixers \n                            to pull from, 70% of the time she will choose mixers tagged with IDLES and \n                            30% of the time she will choose mixers tagged with DEFAULT.\n                            ', tunable_type=interactions.MixerInteractionGroup, needs_tuning=True, default=interactions.MixerInteractionGroup.DEFAULT)), 'topic_preferences': TunableSet(description=' \n            A set of topics that will increase the content score for this mixer\n            interaction.  If a sim has a topic that exist in this set, a value\n            tuned in that topic will increase the content score.  This is used\n            conjunction with base_score.\n                                \n            Formula being used to determine the autonomy score is Score =\n            Avg(Uc, Ucs) * W * SW, Where Uc is the commodity score, Ucs is the\n            content set score, W is the weight tuned the on mixer, and SW is the\n            weight tuned on the super interaction.\n            ', tuning_group=GroupNames.AUTONOMY, tunable=TunableReference(description='\n                The Topic this interaction gets bonus score for. Amount of score\n                is tuned on the Topic.\n                ', manager=services.get_instance_manager(sims4.resources.Types.TOPIC))), 'mood_preference': TunableMapping(description="\n            A mapping of moods that will adjust the content score for this mixer\n            interaction.  If sim's mood exist in this mapping, the value mapped\n            to mood will add to the content score.  This is used conjunction\n            with base_score.\n            ", tuning_group=GroupNames.AUTONOMY, key_type=TunableReference(manager=services.get_instance_manager(sims4.resources.Types.MOOD)), value_type=Tunable(tunable_type=float, default=0)), 'optional': Tunable(description="\n            Most mixers are expected to always be valid.  Thus this should be\n            False. When setting to True, we will test this mixer for\n            compatibility with the current SIs the sim is in. This can be used\n            to ensure general tuning for things like socials can all always be\n            there, but a couple socials that won't work with the treadmill will\n            be tested out such that the player cannot choose them.\n            ", tuning_group=GroupNames.AVAILABILITY, tunable_type=bool, default=False), 'lock_out_time': OptionalTunable(description='\n            Enable to prevent this mixer from being run repeatedly.\n            ', tuning_group=GroupNames.AVAILABILITY, tunable=TunableTuple(interval=TunableInterval(description='\n                    Time in sim minutes in which this affordance will not be valid for.\n                    ', tunable_type=TunableSimMinute, default_lower=1, default_upper=1, minimum=0), target_based_lock_out=Tunable(bool, False, description='\n                    If True, this lock out time will be enabled on a per Sim basis. i.e.\n                    locking it out on Sim A will leave it available to Sim B.\n                    '))), 'lock_out_time_initial': OptionalTunable(description='\n            Enable to prevent this mixer from being run immediately.\n            ', tunable=TunableInterval(description='\n                Time in sim minutes to delay before running this mixer for the\n                first time.\n                ', tunable_type=TunableSimMinute, default_lower=1, default_upper=1, minimum=0), tuning_group=GroupNames.AVAILABILITY), 'lock_out_affordances': OptionalTunable(TunableList(description='\n            Additional affordances that will be locked out if lock out time has\n            been set.\n            ', tunable=TunableReference(manager=services.get_instance_manager(sims4.resources.Types.INTERACTION), class_restrictions=('MixerInteraction',))), tuning_group=GroupNames.AVAILABILITY), 'front_page_cooldown': OptionalTunable(description='\n            If Enabled, when you run this mixer is will get a penalty applied to\n            the front page score of this mixer for a tunable amount of time. If\n            The mixer is run more than once, the cooldown will be re-applied, and\n            the penalty will stack making the mixer less likely to be on the front\n            page as you execute it more.\n            ', tuning_group=GroupNames.AVAILABILITY, tunable=TunableTuple(interval=TunableInterval(description='\n                    Time in minutes until the penatly on the front page score\n                    expires.\n                    ', tunable_type=TunableSimMinute, default_lower=1, default_upper=1, minimum=0), penalty=Tunable(int, 0, description='\n                    Stuff\n                    '))), '_interruptible': OptionalTunable(description='\n            If disabled, this Mixer Interaction will be interruptible if the\n            content is looping, and not if the content is one shot.  To override\n            this behavior, enable this tunable and set the bool.\n            ', tunable=Tunable(description='\n                This interaction represents idle-style behavior and can\n                immediately be interrupted by more important interactions. Set\n                this to True for passive, invisible mixer interactions like\n                stand_Passive.\n                ', tunable_type=bool, default=False), tuning_filter=FilterTag.EXPERT_MODE), 'outcome': TunableOutcome()}

    def __init__(self, target, context, *args, push_super_on_prepare=False, **kwargs):
        super().__init__(target, context, *args, **kwargs)
        self._plumbbob_sheen_event_handle = None
        self._target_sim_refs_to_remove_interaction = None
        self._push_super_on_prepare = push_super_on_prepare
        self.duration = None

    def get_animation_context_liability(self):
        if self.super_interaction is not None:
            animation_liability = self.super_interaction.get_animation_context_liability()
            return animation_liability
        raise RuntimeError('Mixer Interaction {} has no associated Super Interaction. [tastle]'.format(self))

    @property
    def animation_context(self):
        animation_liability = self.get_animation_context_liability()
        return animation_liability.animation_context

    @property
    def carry_target(self):
        carry_target = super().carry_target
        if carry_target is None and self.super_interaction is not None:
            carry_target = self.super_interaction.carry_target
        return carry_target

    def enable_on_all_parts_by_default(self):
        if self.super_interaction is not None:
            return self.super_interaction.enable_on_all_parts_by_default
        return False

    @flexmethod
    def skip_test_on_execute(cls, inst):
        return True

    @flexproperty
    def stat_from_skill_loot_data(cls, inst):
        if inst is None or cls.skill_loot_data.stat is not None:
            return cls.skill_loot_data.stat
        if inst.super_interaction is not None:
            return inst.super_interaction.stat_from_skill_loot_data

    @flexproperty
    def skill_effectiveness_from_skill_loot_data(cls, inst):
        if inst is None or cls.skill_loot_data.effectiveness is not None:
            return cls.skill_loot_data.effectiveness
        if inst.super_interaction is not None:
            return inst.super_interaction.skill_effectiveness_from_skill_loot_data

    @flexproperty
    def level_range_from_skill_loot_data(cls, inst):
        if inst is None or cls.skill_loot_data.level_range is not None:
            return cls.skill_loot_data.level_range
        if inst.super_interaction is not None:
            return inst.super_interaction.level_range_from_skill_loot_data

    @classmethod
    def _test(cls, target, context, **kwargs):
        if cls.optional and not cls.is_mixer_compatible(context.sim, target, participant_type=ParticipantType.Actor):
            return TestResult(False, 'Optional MixerInteraction ({}) was not compatible with current posture ({})', cls, context.sim.posture_state)
        return super()._test(target, context, **kwargs)

    @classmethod
    def potential_interactions(cls, target, sa, si, **kwargs):
        yield AffordanceObjectPair(cls, target, sa, si, **kwargs)

    @classmethod
    def get_base_content_set_score(cls):
        return 0

    @classmethod
    def filter_mixer_targets(cls, potential_targets, actor, affordance=None):
        if cls.target_type & TargetType.ACTOR:
            targets = (None,)
        elif cls.target_type & TargetType.TARGET or cls.target_type & TargetType.OBJECT:
            targets = [x for x in potential_targets if not actor.is_sub_action_locked_out(affordance, target=x)]
        elif cls.target_type & TargetType.GROUP:
            targets = [x for x in potential_targets if not x.is_sim]
            targets = (None,)
        else:
            targets = (None,)
        return targets

    @classmethod
    def get_score_modifier(cls, sim, target):
        return cls.mood_preference.get(sim.get_mood(), 0)

    @classmethod
    def calculate_autonomy_weight(cls, sim):
        final_weight = cls.sub_action.base_weight
        for static_commodity_data in cls.static_commodities_data:
            while sim.get_stat_instance(static_commodity_data.static_commodity):
                final_weight *= static_commodity_data.desire
        return final_weight

    @classproperty
    def interruptible(cls):
        if cls._interruptible is not None:
            return cls._interruptible
        return False

    def should_insert_in_queue_on_append(self):
        if self.super_interaction is not None:
            return True
        return False

    def _must_push_super_interaction(self):
        if not self._push_super_on_prepare or self.super_interaction is not None:
            return False
        for interaction in self.sim.running_interactions_gen(self.super_affordance):
            if interaction.is_finishing:
                pass
            while self.target is interaction.target or self.target in interaction.get_potential_mixer_targets():
                self.super_interaction = interaction
                self.sim.ui_manager.set_interaction_super_interaction(self, self.super_interaction.id)
                return False
        return True

    def notify_queue_head(self):
        super().notify_queue_head()
        if self._must_push_super_interaction():
            self._push_super_on_prepare = False
            context = InteractionContext(self.sim, self.source, self.priority, insert_strategy=QueueInsertStrategy.FIRST, preferred_objects=self.context.preferred_objects)
            result = self.sim.push_super_affordance(self.super_affordance, self.target, context)
            if result:
                self.super_interaction = result.interaction
                guaranteed_lock_liability = LockGuaranteedOnSIWhileRunning(self.super_interaction)
                self.add_liability(LOCK_GUARANTEED_ON_SI_WHILE_RUNNING, guaranteed_lock_liability)
                self.sim.ui_manager.set_interaction_super_interaction(self, self.super_interaction.id)
            else:
                self.cancel(FinishingType.KILLED, 'Failed to push the SI associated with this mixer!')

    def prepare_gen(self, timeline):
        return InteractionQueuePreparationStatus.SUCCESS
        yield None

    def _get_required_sims(self, *args, **kwargs):
        sims = set()
        if self.target_type & TargetType.GROUP:
            sims.update(self.get_participants(ParticipantType.AllSims, listener_filtering_enabled=True))
        elif self.target_type & TargetType.TARGET:
            sims.update(self.get_participants(ParticipantType.Actor))
            sims.update(self.get_participants(ParticipantType.TargetSim))
        elif self.target_type & TargetType.ACTOR or self.target_type & TargetType.OBJECT:
            sims.update(self.get_participants(ParticipantType.Actor))
        return sims

    def get_asm(self, *args, **kwargs):
        if self.super_interaction is not None:
            return self.super_interaction.get_asm(*args, **kwargs)
        return super().get_asm(*args, **kwargs)

    def on_added_to_queue(self, *args, **kwargs):
        super().on_added_to_queue(*args, **kwargs)
        if self._aop:
            self._aop.lifetime_in_steps = 0

    def build_basic_elements(self, sequence=()):
        sequence = super().build_basic_elements(sequence=sequence)
        for sim in self.required_sims():
            for social_group in sim.get_groups_for_sim_gen():
                sequence = social_group.with_social_focus(self.sim, social_group._group_leader, (sim,), sequence)
        suspended_modifiers_dict = self._generate_suspended_modifiers_dict()
        if gsi_handlers.interaction_archive_handlers.is_archive_enabled(self):
            start_time = services.time_service().sim_now
        else:
            start_time = None

        def interaction_start(_):
            self._suspend_modifiers(suspended_modifiers_dict)
            self.apply_interaction_cost()
            performance.counters.add_counter('PerfNumSubInteractions', 1)
            self._add_interaction_to_targets()
            if gsi_handlers.interaction_archive_handlers.is_archive_enabled(self):
                gsi_handlers.interaction_archive_handlers.archive_interaction(self.sim, self, 'Start')

        def interaction_end(_):
            if start_time is not None:
                game_clock_service = services.game_clock_service()
                if game_clock_service is not None:
                    self.duration = (game_clock_service.now() - start_time).in_minutes()
            self._remove_interaction_from_targets()
            self.sim.update_last_used_mixer(self)
            if self._plumbbob_sheen_event_handle is not None:
                self._plumbbob_sheen_event_handle.release()
                self._plumbbob_sheen_event_handle = None
            self._resume_modifiers(suspended_modifiers_dict)

        self._plumbbob_sheen_event_handle = self.animation_context.register_event_handler(self._outcome_xevt_callback, handler_id=SCRIPT_EVENT_ID_PLUMBBOB_SHEEN)
        return build_critical_section_with_finally(interaction_start, sequence, interaction_end)

    def _generate_suspended_modifiers_dict(self):
        suspended_modifiers_dict = {}
        for sim in self.required_sims():
            for (handle, autonomy_modifier_entry) in sim.sim_info.get_statistic_modifiers_gen():
                autonomy_modifier = autonomy_modifier_entry.autonomy_modifier
                while autonomy_modifier.exclusive_si and autonomy_modifier.exclusive_si is not self.super_interaction:
                    if sim.sim_info not in suspended_modifiers_dict:
                        suspended_modifiers_dict[sim.sim_info] = []
                    suspended_modifiers_dict[sim.sim_info].append(handle)
        return suspended_modifiers_dict

    def _suspend_modifiers(self, modifiers_dict):
        for (sim_info, handle_list) in modifiers_dict.items():
            for handle in handle_list:
                sim_info.suspend_statistic_modifier(handle)

    def _resume_modifiers(self, modifiers_dict):
        for (sim_info, handle_list) in modifiers_dict.items():
            for handle in handle_list:
                sim_info.resume_statistic_modifier(handle)

    def apply_interaction_cost(self):
        pass

    def listen_for_availability_change(self, target, context, callback):
        raise RuntimeError('[bhill] This function is believed to be dead code and is scheduled for pruning. If this exception has been raised, the code is not dead and this exception should be removed.')

    def cancel(self, finishing_type, cancel_reason_msg, **kwargs):
        if hasattr(self.super_interaction, 'context_handle'):
            context_handle = self.super_interaction.context_handle
            ret = super().cancel(finishing_type, cancel_reason_msg, **kwargs)
            if ret:
                from server_commands import interaction_commands
                interaction_commands.send_reject_response(self.sim.client, self.sim, context_handle, protocols.ServerResponseFailed.REJECT_CLIENT_SELECT_MIXERINTERACTION)
            return ret
        return super().cancel(finishing_type, cancel_reason_msg, **kwargs)

    def cancel_parent_si_for_participant(self, participant_type, finishing_type, cancel_reason_msg, **kwargs):
        self.super_interaction.cancel(finishing_type, cancel_reason_msg, **kwargs)

    def apply_posture_state(self, *args, **kwargs):
        pass

    def _pre_perform(self):
        result = super()._pre_perform()
        if self.is_user_directed:
            self._update_autonomy_timer()
        return result

    @flexmethod
    def is_mixer_compatible(cls, inst, sim, target, error_on_fail=False, participant_type=DEFAULT):
        posture_state = sim.posture_state
        inst_or_cls = inst if inst is not None else cls
        si = inst.super_interaction if inst is not None else None
        mixer_constraint_tentative = inst_or_cls.constraint_intersection(sim=sim, target=target, posture_state=None, participant_type=participant_type)
        with posture_manifest.ignoring_carry():
            mixer_constraint = mixer_constraint_tentative.apply_posture_state(posture_state, inst_or_cls.get_constraint_resolver(posture_state))
            posture_state_constraint = posture_state.constraint_intersection
            no_geometry_posture_state = posture_state_constraint.generate_alternate_geometry_constraint(None)
            no_geometry_mixer_state = mixer_constraint.generate_alternate_geometry_constraint(None)
            test_intersection = no_geometry_posture_state.intersect(no_geometry_mixer_state)
            ret = test_intersection.valid
        if not ret and error_on_fail:
            si_constraint_list = ''.join('\n        ' + str(c) for c in posture_state_constraint)
            mi_constraint_list = ''.join('\n        ' + str(c) for c in mixer_constraint_tentative)
            mx_constraint_list = ''.join('\n        ' + str(c) for c in mixer_constraint)
            to_constraint_list = ''.join('\n        ' + str(c) for c in test_intersection)
            logger.error("Mixer Interaction Constraint Error:\n    Mixer interaction's constraint is more restrictive than its Super \n    Interaction. Since this mixer is not tuned to be optional, this is a tuning \n    or animation error as the interaction's animation may not play correctly or \n    at all. If it is okay for this mixer to only be available part of the time, \n    set Optional to True.    \n    Mixer: {}\n    SI: {}\n    SI constraints:{}\n    Original Mixer constraints:{}\n    Effective Mixer constraints:{}\n    Total constraints:{}\n                ".format(inst_or_cls, si, si_constraint_list, mi_constraint_list, mx_constraint_list, to_constraint_list), owner='Maxr', trigger_breakpoint=True)
        return ret

    def _validate_posture_state(self):
        for sim in self.required_sims():
            participant_type = self.get_participant_type(sim)
            if participant_type is None:
                pass
            constraint_tentative = self.constraint_intersection(sim=sim, participant_type=participant_type)
            constraint = constraint_tentative.apply_posture_state(sim.posture_state, self.get_constraint_resolver(sim.posture_state, participant_type=participant_type))
            sim_transform_constraint = interactions.constraints.Transform(sim.transform, routing_surface=sim.routing_surface)
            geometry_intersection = constraint.intersect(sim_transform_constraint)
            while not geometry_intersection.valid:
                containment_transform = None
                if isinstance(constraint, RequiredSlotSingle):
                    containment_transform = constraint.containment_transform.translation
                    if sims4.math.vector3_almost_equal_2d(sim.transform.translation, containment_transform, epsilon=0.001):
                        return True
                logger.error("Interaction Constraint Error: Interaction's constraint is incompatible with the Sim's current position \n                    Interaction: {}\n                    Sim: {}, \n                    Constraint: {}\n                    Sim Position: {}\n                    Interaction Target Position: {},\n                    Target Containment Transform: {}", self, sim, constraint, sim.position, self.target.position if self.target is not None else None, containment_transform, owner='MaxR', trigger_breakpoint=True)
                return False
        return True

    def pre_process_interaction(self):
        self.sim.ui_manager.transferred_to_si_state(self)

    def post_process_interaction(self):
        self.sim.ui_manager.remove_from_si_state(self)

    def perform_gen(self, timeline):
        with gsi_handlers.sim_timeline_handlers.archive_sim_timeline_context_manager(self.sim, 'Mixer', 'Perform', self):
            result = yield super().perform_gen(timeline)
            return result

    def _add_interaction_to_targets(self):
        if not self.visible_as_interaction:
            return
        social_group = self.social_group
        if social_group is not None:
            icon_info = self.get_icon_info()
            if icon_info[0] is None:
                icon_info = (None, self.sim)
            for target_sim in self.required_sims():
                if target_sim == self.sim:
                    pass
                target_si = social_group.get_si_registered_for_sim(target_sim)
                if target_si is None:
                    pass
                name = self.display_name_target(target_sim, self.sim)
                target_sim.ui_manager.add_running_mixer_interaction(target_si.id, self, icon_info, name)
                if gsi_handlers.interaction_archive_handlers.is_archive_enabled(self):
                    gsi_handlers.interaction_archive_handlers.archive_interaction(target_sim, self, 'Start')
                if self._target_sim_refs_to_remove_interaction is None:
                    self._target_sim_refs_to_remove_interaction = weakref.WeakSet()
                self._target_sim_refs_to_remove_interaction.add(target_sim)

    def _remove_interaction_from_targets(self):
        if self._target_sim_refs_to_remove_interaction:
            for target_sim in self._target_sim_refs_to_remove_interaction:
                target_sim.ui_manager.remove_from_si_state(self)
                while gsi_handlers.interaction_archive_handlers.is_archive_enabled(self):
                    gsi_handlers.interaction_archive_handlers.archive_interaction(target_sim, self, 'Complete')

lock_instance_tunables(MixerInteraction, basic_reserve_object=None)
