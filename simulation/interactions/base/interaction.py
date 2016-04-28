from collections import OrderedDict, namedtuple, defaultdict
from contextlib import contextmanager
from sims4.utils import setdefault_callable
from weakref import WeakKeyDictionary, WeakSet
import collections
import weakref
from protocolbuffers import Sims_pb2
from animation.posture_manifest import PostureManifest, MATCH_ANY, MATCH_NONE, PostureManifestEntry, AnimationParticipant
from date_and_time import TimeSpan, create_time_span
from distributor.system import Distributor
from element_utils import build_critical_section, build_critical_section_with_finally, build_element
from event_testing.tests import TestList
from interactions import ParticipantType, PipelineProgress, TargetType
from interactions.base.basic import TunableBasicContentSet, TunableBasicExtras, AFFORDANCE_LOADED_CALLBACK_STR
from interactions.constraints import ANYWHERE, NOWHERE
from interactions.context import InteractionContext, QueueInsertStrategy
from interactions.interaction_finisher import FinishingType, InteractionFinisher
from interactions.item_consume import ItemCost
from interactions.liability import Liability, ReplaceableLiability
from interactions.utils import sim_focus, payment
from interactions.utils.animation import InteractionAsmType, flush_all_animations, with_event_handlers, ArbElement, StubActor, TunableAnimationOverrides
from interactions.utils.autonomy_op_list import AutonomyAdList
from interactions.utils.balloon import TunableBalloon
from interactions.utils.display_name import TunableDisplayNameVariant
from interactions.utils.localization_tokens import LocalizationTokens
from interactions.utils.outcome import TunableOutcome
from interactions.utils.outcome_enums import OutcomeResult
from interactions.utils.payment import PaymentLiability
from interactions.utils.reserve import TunableReserveObject
from interactions.utils.sim_focus import TunableFocusElement, with_sim_focus, SimFocus
from interactions.utils.statistic_element import ExitCondition, ConditionalInteractionAction
from interactions.utils.teleport_liability import TeleportLiability
from interactions.utils.tunable import TimeoutLiability, TunableStatisticAdvertisements, SaveLockLiability
from interactions.utils.tunable_icon import TunableIconVariant, TunableIcon
from postures import ALL_POSTURES, PostureEvent
from postures.posture_specs import PostureSpecVariable
from sims.bills_enums import Utilities
from sims4.callback_utils import consume_exceptions, CallableList
from sims4.collections import frozendict
from sims4.localization import TunableLocalizedStringFactory
from sims4.math import MAX_UINT64
from sims4.sim_irq_service import yield_to_irq
from sims4.tuning.dynamic_enum import DynamicEnum
from sims4.tuning.instances import HashedTunedInstanceMetaclass
from sims4.tuning.tunable import OptionalTunable, TunableTuple, TunableSimMinute, TunableSet, HasTunableReference, Tunable, TunableList, TunableVariant, TunableResourceKey, TunableEnumEntry, TunableReference, TunableRange, TunableMapping, TunableThreshold
from sims4.tuning.tunable_base import GroupNames, FilterTag
from sims4.utils import classproperty, flexproperty, flexmethod
from singletons import DEFAULT, EMPTY_SET
from statistics.skill import TunableSkillLootData
from tag import Tag
from ui.ui_dialog import UiDialogOkCancel
from ui.ui_dialog_element import UiDialogElement
from uid import unique_id
import alarms
import animation
import animation.asm
import caches
import carry
import clock
import distributor
import element_utils
import enum
import event_testing.resolver
import event_testing.results
import event_testing.test_events as test_events
import event_testing.tests
import gsi_handlers
import interactions.constraints
import interactions.si_state
import interactions.utils.exit_condition_manager
import objects
import services
import sims
import sims4.log
import sims4.resources
import snippets
logger = sims4.log.Logger('Interactions')
SIM_YIELD_INTERACTION_GET_PARTICIPANTS_MOD = 1000
interaction_get_particpants_call_count = 0

class InteractionIntensity(DynamicEnum):
    __qualname__ = 'InteractionIntensity'
    Default = 0

class InteractionQueueVisualType(enum.Int):
    __qualname__ = 'InteractionQueueVisualType'
    SIMPLE = 0
    PARENT = 1
    MIXER = 2
    POSTURE = 3

    @staticmethod
    def get_interaction_visual_type(visual_type):
        if visual_type == InteractionQueueVisualType.PARENT:
            return Sims_pb2.Interaction.PARENT
        if visual_type == InteractionQueueVisualType.MIXER:
            return Sims_pb2.Interaction.MIXER
        if visual_type == InteractionQueueVisualType.POSTURE:
            return Sims_pb2.Interaction.POSTURE
        return Sims_pb2.Interaction.SIMPLE

class InteractionQueuePreparationStatus(enum.Int, export=False):
    __qualname__ = 'InteractionQueuePreparationStatus'
    FAILURE = 0
    SUCCESS = 1
    NEEDS_DERAIL = 2

ANIMATION_CONTEXT_LIABILITY = 'AnimationContext'

class AnimationContextLiability(Liability):
    __qualname__ = 'AnimationContextLiability'

    def __init__(self, animation_context):
        self._animation_context = animation_context
        self._animation_context.add_ref(ANIMATION_CONTEXT_LIABILITY)
        self._event_handle = None
        self._interaction = None
        self.cached_asm_keys = defaultdict(set)

    @property
    def animation_context(self):
        return self._animation_context

    def unregister_handles(self, interaction):
        if self._event_handle is not None:
            self._event_handle.release()
            self._event_handle = None

    def setup_props(self, interaction):
        previous_interaction = self._interaction
        self._interaction = interaction
        if self._interaction is None:
            if self._event_handle is not None:
                self._event_handle.release()
                self._event_handle = None
            return
        if previous_interaction != interaction:
            if self._event_handle is not None:
                self._event_handle.release()
            self._event_handle = self._animation_context.register_custom_event_handler(self._hide_other_held_props, interaction.sim, 0, allow_stub_creation=True, optional=True)

    def _hide_other_held_props(self, _):
        self._event_handle = None
        for sim in self._interaction.required_sims():
            for si in sim.si_state:
                while si is not self._interaction.super_interaction and not si.super_affordance_should_persist_held_props:
                    si.animation_context.set_all_prop_visibility(False, held_only=True)

    def transfer(self, interaction):
        if self._animation_context is not None:
            logger.debug('TRANSFER: {} -> {}', self.animation_context, interaction)
            self.animation_context.reset_for_new_interaction()

    def release(self):
        if self._animation_context is not None:
            self._animation_context.release_ref(ANIMATION_CONTEXT_LIABILITY)
            logger.debug('RELEASE : {}', self.animation_context)
            self._animation_context = None

PRIVACY_LIABILITY = 'PrivacyLiability'

class PrivacyLiability(Liability):
    __qualname__ = 'PrivacyLiability'

    def __init__(self, interaction, target=None):
        self._privacy = interaction.privacy(interaction)
        try:
            self._privacy.build_privacy(target=target)
        except:
            if self._privacy:
                self._privacy.remove_privacy()
            raise

    @property
    def privacy(self):
        return self._privacy

    @property
    def should_transfer(self):
        return False

    def release(self):
        self._privacy.remove_privacy()

    def on_reset(self):
        self._privacy.remove_privacy()

FITNESS_LIABILITY = 'FitnessLiability'

class FitnessLiability(Liability):
    __qualname__ = 'FitnessLiability'

    def __init__(self, sim):
        self.sim = sim

    def release(self):
        self.sim.sim_info.update_fitness_state()

OWNS_POSTURE_LIABILITY = 'OwnsPostureLiability'

class OwnsPostureLiability(ReplaceableLiability):
    __qualname__ = 'OwnsPostureLiability'

    def __init__(self, interaction, posture):
        self._interaction_ref = None
        self._posture_ref = weakref.ref(posture)

    def on_add(self, interaction):
        super().on_add(interaction)
        if self._posture is not None:
            self._interaction_ref = weakref.ref(interaction)
            self._posture.add_owning_interaction(self._interaction)

    def transfer(self, interaction):
        if self._posture is not None:
            self._posture.remove_owning_interaction(self._interaction)

    def release(self):
        if self._posture is not None:
            self._posture.remove_owning_interaction(self._interaction)

    @property
    def _posture(self):
        return self._posture_ref()

    @property
    def _interaction(self):
        return self._interaction_ref()

CANCEL_AOP_LIABILITY = 'CancelAOPLiability'

class CancelAOPLiability(Liability):
    __qualname__ = 'CancelAOPLiability'

    def __init__(self, sim, interaction_cancel_replacement, interaction_to_cancel, release_callback, posture):
        self._sim_ref = weakref.ref(sim)
        self._interaction_cancel_replacement_ref = weakref.ref(interaction_cancel_replacement)
        self._interaction_to_cancel_ref = weakref.ref(interaction_to_cancel)
        self._release_callback = release_callback
        self._posture = posture
        if posture is not None:
            self._posture.add_cancel_aop(interaction_cancel_replacement)
        sim.on_posture_event.append(self._on_posture_changed)

    @property
    def interaction_to_cancel(self):
        return self._interaction_to_cancel_ref()

    def release(self):
        self._sim_ref().on_posture_event.remove(self._on_posture_changed)
        if self._release_callback is not None:
            self._release_callback(self._posture)
        sim = self._sim_ref()
        if sim is not None and (sim.posture is self._posture and sim.posture.ownable) and (not self._posture.owning_interactions or len(self._posture.owning_interactions) == 1 and self._interaction_cancel_replacement_ref() in self._posture.owning_interactions):
            sim.schedule_reset_asap(source=self._posture.target, cause="CancelAOPLiability released without changing the Sim's posture away from {}".format(self._posture))

    def _on_posture_changed(self, change, dest_state, track, old_value, new_value):
        if self._posture.track == track and change == PostureEvent.POSTURE_CHANGED:
            interaction = self._interaction_cancel_replacement_ref()
            sim = self._sim_ref()
            if interaction is not None and (interaction is not new_value.source_interaction and (interaction not in new_value.owning_interactions and (sim is not None and sim.queue.transition_controller is not None))) and sim.queue.transition_controller.interaction is not interaction:
                interaction.cancel(FinishingType.LIABILITY, cancel_reason_msg='CancelAOPLiability. Posture changed before cancel_replacement completed.')

CANCEL_INTERACTION_ON_EXIT_LIABILITY = 'CancelInteractionsOnExitLiability'

class CancelInteractionsOnExitLiability(Liability):
    __qualname__ = 'CancelInteractionsOnExitLiability'

    def __init__(self):
        self._to_cancel_for_sim = WeakKeyDictionary()

    def merge(self, interaction, key, new_liability):
        if not isinstance(new_liability, CancelInteractionsOnExitLiability):
            raise TypeError('Cannot merge a CancelInteractionsOnExitLiability with a ' + type(new_liability).__name__)
        if key != CANCEL_INTERACTION_ON_EXIT_LIABILITY:
            raise ValueError('Mysterious and unexpected key: {} instead of {}'.format(key, CANCEL_INTERACTION_ON_EXIT_LIABILITY))
        old_keys = set(self._to_cancel_for_sim.keys())
        new_keys = set(new_liability._to_cancel_for_sim.keys())
        for key in old_keys & new_keys:
            new_liability._to_cancel_for_sim[key] |= self._to_cancel_for_sim[key]
        for key in old_keys - new_keys:
            new_liability._to_cancel_for_sim[key] = self._to_cancel_for_sim[key]

    def release(self):
        for (sim, affordances_or_interactions) in tuple(self._to_cancel_for_sim.items()):
            for affordance_or_interaction in tuple(affordances_or_interactions):
                if isinstance(affordance_or_interaction, Interaction):
                    interaction = affordance_or_interaction
                else:
                    interaction = sim.si_state.get_si_by_affordance(affordance_or_interaction)
                while interaction is not None:
                    interaction.cancel(FinishingType.LIABILITY, cancel_reason_msg='CancelInteractionsOnExitLiability released')

    def add_cancel_entry(self, sim, affordance_or_interaction):
        if sim not in self._to_cancel_for_sim:
            self._to_cancel_for_sim[sim] = WeakSet()
        self._to_cancel_for_sim[sim].add(affordance_or_interaction)

    def remove_cancel_entry(self, sim, affordance_or_interaction):
        self._to_cancel_for_sim[sim].remove(affordance_or_interaction)
        if len(self._to_cancel_for_sim[sim]) == 0:
            del self._to_cancel_for_sim[sim]

LOCK_GUARANTEED_ON_SI_WHILE_RUNNING = 'LockGuaranteedOnSIWhileRunning'

class LockGuaranteedOnSIWhileRunning(Liability):
    __qualname__ = 'LockGuaranteedOnSIWhileRunning'

    def __init__(self, si_to_lock):
        self._si_to_lock = si_to_lock
        with si_to_lock.guaranteed_watcher:
            si_to_lock.guaranteed_locks[self] = True

    def release(self):
        if self not in self._si_to_lock.guaranteed_locks:
            return
        with self._si_to_lock.guaranteed_watcher:
            del self._si_to_lock.guaranteed_locks[self]

STAND_SLOT_LIABILITY = 'StandSlotReservationLiability'

class StandSlotReservationLiability(ReplaceableLiability):
    __qualname__ = 'StandSlotReservationLiability'

    def __init__(self, sim, interaction):
        self._sim_ref = weakref.ref(sim)
        self._interaction_ref = weakref.ref(interaction)

    @property
    def should_transfer(self):
        return False

    @property
    def sim(self):
        return self._sim_ref()

    @property
    def interaction(self):
        return self._interaction_ref()

    def release(self):
        self.sim.remove_stand_slot_reservation(self.interaction)

RESERVATION_LIABILITY = 'ReservationLiability'

class ReservationLiability(ReplaceableLiability):
    __qualname__ = 'ReservationLiability'

    def __init__(self, reservation_handlers):
        self._reservation_handlers = reservation_handlers

    def on_reset(self):
        self.release_reservations()

    def release(self):
        self.release_reservations()

    @property
    def should_transfer(self):
        return False

    def release_reservations(self):
        for handler in self._reservation_handlers:
            handler.end()

AUTONOMY_MODIFIER_LIABILITY = 'AutonomyModifierLiability'

class AutonomyModifierLiability(Liability):
    __qualname__ = 'AutonomyModifierLiability'

    def __init__(self, interaction):
        self._sim = interaction.sim
        self._autonomy_modifier_handles = weakref.WeakKeyDictionary()
        autonomy_modifiers = interaction.target.autonomy_modifiers
        for modifier in autonomy_modifiers:
            subject = self._sim
            if modifier.subject:
                subject = interaction.get_participant(modifier.subject)
            while subject is not None:
                handle = subject.add_statistic_modifier(modifier, interaction_modifier=True)
                setdefault_callable(self._autonomy_modifier_handles, subject, list).append(handle)

    def release(self, *args, **kwargs):
        for (subject, handles) in self._autonomy_modifier_handles.items():
            for handle in handles:
                subject.remove_statistic_modifier(handle)

ROUTING_POSTURE_INTERACTION_ID = MAX_UINT64 - 1

class InteractionFailureOptions:
    __qualname__ = 'InteractionFailureOptions'
    FAILURE_REASON_TESTS = TunableList(description='\n        A List in the format of (TunableTestSet, TunableAnimOverrides). When an interaction\n        fails because of its tests, we execute these tests and the first one that passes\n        determines the AnimOverrides that will be used to show failure to the player.\n        ', tunable=TunableTuple(test_set=event_testing.tests.TunableTestSet(), anim_override=TunableAnimationOverrides()))
    ROUTE_FAILURE_AFFORDANCE = TunableReference(description="\n        A Tunable Reference to the Interaction that's pushed on a Sim when their\n        tests fail and they need to display failure to the user.\n        ", manager=services.affordance_manager())

@unique_id('id', 1, MAX_UINT64 - 2)
class Interaction(HasTunableReference, metaclass=HashedTunedInstanceMetaclass, manager=services.get_instance_manager(sims4.resources.Types.INTERACTION)):
    __qualname__ = 'Interaction'
    DEBUG_NAME_FACTORY = OptionalTunable(TunableLocalizedStringFactory(display_name='Debug Interaction Name Pattern', description='Format for displaying interaction names for interactions that are debug interactions.'))
    SIMOLEON_DELTA_MODIFIES_AFFORDANCE_NAME = Tunable(bool, True, description='Enables the display of Simoleon delta information in the choices menu.')
    SIMOLEON_DELTA_MODIFIES_INTERACTION_NAME = Tunable(bool, True, description='Enables the display of Simoleon delta information on running interactions.')
    SIMOLEON_COST_NAME_FACTORY = OptionalTunable(TunableLocalizedStringFactory(display_name='Simoleon Cost Interaction Name Pattern', description='Format for displaying interaction names on interactions that have Simoleon costs.'))
    SIMOLEON_GAIN_NAME_FACTORY = OptionalTunable(TunableLocalizedStringFactory(display_name='Simoleon Gain Interaction Name Pattern', description='Format for displaying interaction names on interactions that have Simoleon gains.'))
    ITEM_COST_NAME_FACTORY = OptionalTunable(TunableLocalizedStringFactory(display_name='Item Cost Interaction Name Pattern', description='Format for displaying item cost on the interaction name so player is aware what the interaction will consume'))
    INSTANCE_SUBCLASSES_ONLY = True
    INSTANCE_TUNABLES = {'display_name': TunableLocalizedStringFactory(description='\n            The localized name of this interaction.  It takes two tokens, the\n            actor (0) and target object (1) of the interaction.', tuning_group=GroupNames.UI), 'display_tooltip': OptionalTunable(description='\n            The tooltip to show on the pie menu option if this interaction passes\n            its tests.\n            ', tunable=sims4.localization.TunableLocalizedStringFactory(), tuning_group=GroupNames.UI), 'display_name_text_tokens': LocalizationTokens.TunableFactory(description="\n            Localization tokens to be passed into 'display_name'.\n            For example, you could use a participant or you could also pass in \n            statistic and commodity values\n            ", tuning_group=GroupNames.UI), 'display_name_overrides': TunableDisplayNameVariant(description='\n            Set name modifiers or random names.\n            ', tuning_group=GroupNames.UI), '_icon': TunableIconVariant(description='\n            The icon to be displayed in the interaction queue.\n            ', tuning_group=GroupNames.UI), 'pie_menu_icon': TunableResourceKey(description='\n            The icon to display in the pie menu.\n            ', default=None, resource_types=sims4.resources.CompoundTypes.IMAGE, tuning_group=GroupNames.UI), 'pie_menu_priority': TunableRange(description="\n            Higher priority interactions will show up first on the pie menu.\n            Interactions with the same priority will be alphabetical. This will \n            not override the content_score for socials. Socials with a high score\n            will still show on the top-most page of the pie menu. It's \n            suggested that you start with lower numbers instead of automatically \n            tuning something to a 10 just to make it show up on the first page.\n            ", tunable_type=int, default=0, minimum=0, maximum=10), 'allow_autonomous': Tunable(description='\n            If checked, this interaction may be chosen by autonomy for Sims to\n            run autonomously.\n            ', tunable_type=bool, default=True, needs_tuning=True, tuning_group=GroupNames.AVAILABILITY), 'allow_user_directed': Tunable(description='\n            If checked, this interaction may appear in the pie menu and be\n            chosen by the player.\n            ', tunable_type=bool, default=True, needs_tuning=True, tuning_group=GroupNames.AVAILABILITY), 'allow_from_world': Tunable(description='\n            If checked, this interaction may be started while the object is in\n            the world (as opposed to being in an inventory).\n            ', tunable_type=bool, default=True, tuning_group=GroupNames.AVAILABILITY), 'allow_from_sim_inventory': Tunable(description="\n            If checked, this interaction may be started while the object is in a\n            Sim's inventory.\n            ", tunable_type=bool, default=False, tuning_group=GroupNames.AVAILABILITY), 'allow_from_object_inventory': Tunable(description="\n            If checked, this interaction may be started while the object is in\n            another object's inventory.\n            ", tunable_type=bool, default=False, tuning_group=GroupNames.AVAILABILITY), 'allow_forward': Tunable(description='\n            If checked, this interaction will be available by clicking on the\n            parent of this object (for example, on an oven containing a backing\n            pan) or by clicking on a Sim using this object (for example, "order\n            drink" is available both on a bar and the Sim tending the bar).\n            ', tunable_type=bool, default=False, tuning_group=GroupNames.AVAILABILITY), 'allow_from_portrait': Tunable(description='\n            If checked, this interaction may be surfaced from the portrait icon of a Sim in the \n            Relationship panel.\n            ', tunable_type=bool, default=False, tuning_group=GroupNames.AVAILABILITY), 'allow_while_save_locked': Tunable(description='\n            If checked, this interaction is allowed to run while saving is\n            currently blocked. Example:Saving is locked when a Sim is in the\n            process of dying and is waiting to be reaped by the grim reaper.\n            While this is happening we do not want you to be able to travel, so\n            all travel interactions have this tunable unchecked.\n            ', tunable_type=bool, default=True, tuning_group=GroupNames.AVAILABILITY, tuning_filter=FilterTag.EXPERT_MODE), '_cancelable_by_user': TunableVariant(description='\n            Define the ability for the player to cancel this interaction.            \n            ', require_confirmation=UiDialogOkCancel.TunableFactory(description='\n                A dialog prompting the player for confirmation as to whether or\n                not they want to cancel this interaction. The interaction will\n                cancel only if the player responds affirmatively. \n                '), locked_args={'allow_cancelation': True, 'prohibit_cancelation': False}, default='allow_cancelation', tuning_group=GroupNames.UI), '_must_run': Tunable(description='\n            If checked, nothing may cancel this interaction.  Not to be used\n            lightly.', tunable_type=bool, default=False, tuning_group=GroupNames.UI), 'time_overhead': TunableSimMinute(description="\n            Amount of time, in sim minutes, that autonomy believes that this\n            interaction will take to run. This value does not represent an\n            actual value of how long the interaction should run, but rather an\n            estimation of how long it will run for autonomy calculate the\n            efficiency of the interaction. Efficiency is used to model distance\n            attenuation.  If this value is high, the sim won't care as much how\n            far away it is.\n            ", default=10, minimum=1, tuning_group=GroupNames.AUTONOMY), 'visible': Tunable(description='\n            If checked, this interaction will be visible in the UI when queued\n            or running.\n            ', tunable_type=bool, default=True, needs_tuning=True, tuning_group=GroupNames.UI), 'simless': Tunable(description='\n            If unchecked, there must be an active Sim to run it. If checked, no\n            Sim will be available to the interaction when it runs. Debug\n            interactions are often Simless.\n            ', tunable_type=bool, default=False, tuning_group=GroupNames.AVAILABILITY), 'target_type': TunableEnumEntry(description='\n            Indicates the type of target this interaction has: a specific Sim, a\n            group, or no one.\n                                        \n            Setting this value here will determine the animation resource\n            required for interaction to run.\n                                        \n            Examples:\n             * If sim "told a joke" and you want all sims in the group to react,\n             this should be set to GROUP.\n                                        \n             * If sim poke fun at another sim, you want to set this to TARGET.\n            ', tunable_type=TargetType, default=TargetType.GROUP), 'debug': Tunable(description='\n            If checked, this interaction will only be available from the debug\n            pie menu.  The debug pie menu is not available in release builds and\n            only appears when shift-clicking to bring up the pie menu.\n            ', tunable_type=bool, default=False, tuning_group=GroupNames.AVAILABILITY, tuning_filter=FilterTag.EXPERT_MODE), 'cheat': Tunable(description='\n            If checked, this interaction will only be available from the cheat\n            pie menu. The cheat pie menu is available in all builds when cheats\n            are enabled, and only appears when shift-clicking to bring up the\n            pie menu.\n            ', tunable_type=bool, default=False, tuning_group=GroupNames.AVAILABILITY, tuning_filter=FilterTag.EXPERT_MODE), 'automation': Tunable(description='\n            If checked, this interaction will only be available from the\n            automation mode of the game. Note that this is ignored if the\n            cheat is marked as debug while the game is non-optimized.\n            ', tunable_type=bool, default=False, tuning_group=GroupNames.AVAILABILITY, tuning_filter=FilterTag.EXPERT_MODE), '_static_commodities': TunableList(description='\n            The list of static commodities to which this affordance will\n            advertise.\n            ', tunable=TunableTuple(description='\n                A single chunk of static commodity scoring data.\n                ', static_commodity=TunableReference(description='\n                    The type of static commodity offered by this affordance.\n                    ', manager=services.get_instance_manager(sims4.resources.Types.STATIC_COMMODITY), reload_dependent=True), desire=Tunable(description='\n                    The autonomous desire to fulfill this static commodity.  This is how much \n                    of the static commodity the Sim thinks they will get.  This is, of course, \n                    a blatant lie.\n                    ', tunable_type=float, default=1)), tuning_group=GroupNames.AUTONOMY), '_affordance_key_override_for_autonomy': Tunable(description='\n                                                        If set, this string will take the place of the affordance as the key used \n                                                        in autonomy scoring.  This will cause autonomy to see two affordances as \n                                                        the same for the purposes of grouping.  For example, if you have \n                                                        bed_sleep_single and bed_sleep_double, you can override them to both be  \n                                                        "bed_sleep".  Autonomy will see them as the same affordance and will \n                                                        only choose one to consider when throwing the weighted random at the end.\n                                                        It will also apply object preference, treating them as the same affordance.\n                                                        ', tunable_type=str, default=None, tuning_group=GroupNames.AUTONOMY), 'outcome': TunableOutcome(outcome_locked_args={'cancel_si': None}), 'skill_loot_data': TunableSkillLootData(description='\n            Loot Data for DynamicSkillLootOp. This will only be used if in the\n            loot list of the outcome there is a dynamic loot op.\n            '), '_false_advertisements': TunableStatisticAdvertisements(description='\n            Fake advertisements make the interaction more enticing to autonomy\n            by promising things it will not deliver.\n            ', tuning_group=GroupNames.AUTONOMY), '_hidden_false_advertisements': TunableStatisticAdvertisements(description="\n            Fake advertisements that are hidden from the Sim.  These ads will not\n            be used when determining which interactions solve for a commodity, but\n            it will be used to calculate the final score.\n            \n            For example: You can tune the bubble bath to provide hygiene as normal, \n            but to also have a hidden ad for fun.  Sims will prefer a bubble bath\n            when they want to solve hygiene and their fun is low, but they won't\n            choose to take a bubble bath just to solve for fun.\n            ", tuning_group=GroupNames.AUTONOMY), '_constraints': TunableList(description='\n            A list of constraints that must be fulfilled in order to interact\n            with this object.\n            ', tunable=interactions.constraints.TunableConstraintVariant(description='\n                A constraint that must be fulfilled in order to interact with\n                this object.\n                ')), '_constraints_actor': TunableEnumEntry(ParticipantType, ParticipantType.Object, description='\n        The Actor used to generate _constraints relative to.\n        '), 'fade_sim_out': Tunable(bool, False, description='\n        If set to True, this interaction will fade the Sim out as they approach\n        the destination constraint for this interaction.\n        '), 'tests': event_testing.tests.TunableTestSet(tuning_group=GroupNames.AVAILABILITY), 'test_globals': event_testing.tests.TunableGlobalTestSet(description='\n            A set of global tests that are always run before other tests. All\n            tests must pass in order for the interaction to run.\n            ', tuning_group=GroupNames.AVAILABILITY), 'test_autonomous': event_testing.tests.TunableTestSet(description='\n            A set of tests that are only run for interactions being considered \n            by autonomy.\n            ', tuning_group=GroupNames.AVAILABILITY), 'basic_reserve_object': OptionalTunable(TunableReserveObject(), True), 'basic_focus': TunableVariant(description='\n            Control the focus (gaze) of the actor while running this\n            interaction.\n            ', locked_args={'do_not_change_focus': None, 'disable_focus': False}, default='do_not_change_focus', tunable_focus=TunableFocusElement()), 'basic_liabilities': TunableList(description="\n            Use basic_liablities to tune a list of tunable liabilities.                     \n            \n            A liability is a construct that is associated to an interaction the moment it is added\n            to the queue. This is different from basic_content and basic_extras, which only affect\n            interactions that have started running. \n            \n            e.g. The 'timeout' tunable is a liability, because its behavior is triggered\n            the moment the SI is enqueued - by keeping track of how long it takes for it\n            to start running and canceling if the timeout is hit.\n            ", tunable=TunableVariant(timeout=TimeoutLiability.TunableFactory(), save_lock=SaveLockLiability.TunableFactory(), payment=PaymentLiability.TunableFactory(), teleport=TeleportLiability.TunableFactory())), 'basic_extras': TunableBasicExtras(), 'basic_content': TunableBasicContentSet(description='\n            Use basic_content to define the nature of this interaction. Any\n            looping animation, autonomy, statistic gain, and any other periodic change\n            is tuned in. Also, exit conditions will be specified here.                                        \n            \n            Depending on the type of basic_content you select, some options\n            may or may not be available.\n            \n            Please see the variant elements descriptions to determine how\n            each specific option affects the behavior of this interaction.\n            ', one_shot=True, looping_animation=True, no_content=True, default='no_content'), 'confirmation_dialog': OptionalTunable(UiDialogElement.TunableFactory(description='\n                Prompts the user with an Ok Cancel Dialog. This will stop the\n                interaction from running if the user chooses the cancel option.\n                ')), 'intensity': TunableEnumEntry(description='\n            The intensity of response animations for this interaction.\n            ', tunable_type=InteractionIntensity, needs_tuning=True, default=InteractionIntensity.Default), 'category': TunableReference(description='\n            Pie menu category.\n            ', manager=services.get_instance_manager(sims4.resources.Types.PIE_MENU_CATEGORY), tuning_group=GroupNames.UI), 'posture_preferences': TunableTuple(description='\n            Options relating to posture preferences for this interaction.\n            ', prefer_surface=Tunable(description='\n                If checked, a Sim will prefer to perform this interaction at a\n                surface.\n                ', tunable_type=bool, needs_tuning=True, default=False), apply_penalties=Tunable(description='\n                If checked, posture penalties will be applied when selecting a\n                posture in which to perform this interaction.\n                ', tunable_type=bool, needs_tuning=True, default=False), find_best_posture=Tunable(description='"\n                If checked, the Sim will always find the find best (most\n                preferred) posture even if the Sim\'s current posture is already\n                compatible.  Example: if a Sim grabs a serving of food, the Sim\n                will standing, but we still want the Sim to go find a chair at a\n                table even though they could eat the food standing up.\n                ', tunable_type=bool, needs_tuning=True, default=False), prefer_clicked_part=Tunable(description='\n                If True, this interaction will prefer to take the Sim to the part\n                near where you clicked in world.\n                ', tunable_type=bool, default=True), require_current_constraint=Tunable(description='\n                If checked, a Sim will never violate its current geometric\n                constraints in order to find a place to run the interaction.\n                ', tunable_type=bool, default=False), posture_cost_overrides=TunableMapping(description='\n                For any posture in this mapping, its cost is overriden by the\n                specified value for the purpose of transitioning for this\n                interaction.\n                \n                For example, Sit is a generally cheap posture. However, some\n                interactions (such as Nap), would want to penalize Sit in favor\n                of something more targeted (such as the two-seated version of\n                nap).\n                ', key_type=TunableReference(manager=services.posture_manager()), value_type=Tunable(description='\n                    The cost override for the specified posture.\n                    ', tunable_type=int, default=0))), 'interaction_category_tags': TunableSet(description='\n            This attribute is used to tag an interaction to allow for searching,\n            testing, and categorization. An example would be using a tag to\n            selectively test certain interactions. On each of the interactions\n            you want to test together you would add the same tag, then the test\n            routine would only test interactions with that tag. Interactions can\n            have multiple tags.\n            \n            This attribute has no effect on gameplay.\n            ', tunable=TunableEnumEntry(description='\n                These tag values are used for searching, testing, and\n                categorizing interactions.\n                ', tunable_type=Tag, default=Tag.INVALID)), 'utility_info': OptionalTunable(TunableList(description='\n            Tuning that specifies which utilities this interaction requires to\n            be run.\n            ', tunable=TunableEnumEntry(Utilities, None)), needs_tuning=True, tuning_group=GroupNames.AVAILABILITY), 'test_incest': Tunable(description='\n            If checked, an incest check must pass for this interaction to be\n            available. This test is only valid for interactions that involve two\n            Sims.\n            ', tunable_type=bool, default=False, tuning_group=GroupNames.AVAILABILITY), 'visual_type_override': TunableEnumEntry(description='\n            Specify visual type if you want to override how this interaction\n            will appear in the interaction queue.\n            \n            Example: sitting by default will appear as posture interaction set\n            to simple if you want to make this appear as a normal interaction.\n            ', tunable_type=InteractionQueueVisualType, default=None, tuning_group=GroupNames.UI, tuning_filter=FilterTag.EXPERT_MODE), 'visual_type_override_data': TunableTuple(description="\n            Overrides this interaction's icon and name if interaction is going\n            into the posture slot of the interaction queue.\n            ", icon=TunableIcon(), tooltip_text=TunableLocalizedStringFactory(description='\n                The localized name of this interaction when it appear in the\n                running section of the interaction queue.\n                ', default=None), group_tag=TunableEnumEntry(description='\n                This tag is used for Grouping interactions in the\n                running section of the interaction queue.\n                \n                Example:  Sim is running chat then queues up be_affectionate.\n                Once be_affectionate moves into the running of the section of\n                the queue be_affection will disappear since it is grouped\n                together with sim chat\n                ', tunable_type=Tag, default=Tag.INVALID), group_priority=TunableRange(description='\n                When interactions are grouped into one item in the queue, this\n                is the priority of which interaction will be the top item.\n                ', tunable_type=int, default=1, minimum=1), tuning_group=GroupNames.UI), 'item_cost': ItemCost.TunableFactory(), 'progress_bar_enabled': TunableTuple(description='\n            Set of tuning to display the progress bar when the interaction runs\n            ', bar_enabled=Tunable(description='\n                If checked, interaction will try to show a progress bar when \n                running.\n                Progress bar functionality also depends on the interaction being\n                tuned with proper exit condition and extras that will lead it to \n                that exit condition.\n                e.g.  An interaction with an exit condition for a statistic that \n                reaches a threshold and a tunable extra that increases that \n                statistic as the interaction runs. \n                e.g.  Interaction with tunable time of execution.\n                ', tunable_type=bool, needs_tuning=True, default=True), remember_progress=Tunable(description="\n                If checked, interaction will use the current progress of the \n                statistic from the exit conditions to display where the bar\n                should start.  \n                This is used for interactions that we don't always want to \n                start the progress bar from zero but to display they had been \n                started previously.\n                ", tunable_type=bool, needs_tuning=True, default=False), force_listen_statistic=OptionalTunable(TunableTuple(description="\n                If this is enabled, the progress bar will listen to a specific\n                statistic on a subject of this interaction instead of \n                looking at the interaction's exit conditions.  This means, \n                instead of sending the UI a rate of change during the \n                interaction we will send a message whenever that statistic \n                changes.\n                ", statistic=TunableReference(description='\n                    Statistic to listen to display on the progress bar.\n                    This should not be a commodity with a decay value.\n                    The reason for this is because we will send a message to \n                    the UI for every update on this commodity and decaying \n                    commodities decay every tick, so that will just overload \n                    the number of messages we send.\n                    ', manager=services.get_instance_manager(sims4.resources.Types.STATISTIC)), subject=TunableEnumEntry(description='\n                    Subject of interaction that the progress bar will listen \n                    for this statistic change.\n                    ', tunable_type=ParticipantType, default=ParticipantType.Actor), target_value=TunableThreshold(description='\n                    Target value of where the progress bar should lead to.\n                    '))), override_min_max_values=OptionalTunable(TunableTuple(description='\n                If this is enabled, we can override the minimum and maximum \n                value of a statistic.  \n                For example, the build rocketship \n                uses a statistic that goes from -100 to 100, but the build \n                interaction only works from 0 to 100.  So for this interaction\n                we want to override the min value to 0 so the progress bar \n                shows properly.  \n                ', statistic=TunableReference(description='\n                    Statistic to look for to override its min or max values \n                    when calculating the progress bar generation.\n                    ', manager=services.statistic_manager()), min_value=OptionalTunable(description='\n                    Override min value\n                    ', tunable=Tunable(description='\n                        Value to use as the new minimum of the specified \n                        statistic \n                        ', tunable_type=float, default=0), enabled_name='specified_min', disabled_name='use_stat_min'), max_value=OptionalTunable(description='\n                    Override max value\n                    ', tunable=Tunable(description='\n                        Value to use as the new maximum of the specified \n                        statistic \n                        ', tunable_type=float, default=0), enabled_name='specified_max', disabled_name='use_stat_max'))), blacklist_statistics=OptionalTunable(description='\n                Set statistics that should be ignored by the progress bar\n                ', tunable=TunableList(description='\n                    List of commodities the progress bar will ignore when \n                    calculating the exit condition that will cause the \n                    interaction to exit.\n                    ', tunable=TunableReference(description='\n                        Statistic to be ignored by the progress bar\n                        ', manager=services.statistic_manager())), enabled_name='specify_blacklist_statistics', disabled_name='consider_all'), interaction_exceptions=TunableTuple(description='\n                Possible exceptions to the normal progress bar rules.\n                For example, music interactions will listen to a tunable \n                time which is hand tuned to match the audio tracks, \n                ', is_music_interaction=Tunable(description='\n                    If checked, interaction will read the tunable track time of \n                    music tracks and use that time to display the progress bar. \n                    e.g.  Piano and violin interactions.\n                    ', tunable_type=bool, default=False)), tuning_group=GroupNames.AVAILABILITY), 'appropriateness_tags': TunableSet(description='\n            A set of tags that define appropriateness for this interaction.  If\n            an appropriateness or inappropriateness test is used for this\n            interaction then it will check the tuned appropriateness tags\n            against the ones that the role state has applied to the actor.\n            ', tunable=TunableEnumEntry(tunable_type=Tag, default=Tag.INVALID)), 'route_start_balloon': OptionalTunable(TunableTuple(description='\n            Allows for a balloon to be played over the actor at the start  \n            of this interaction transition when run autonomously.', balloon=TunableBalloon(locked_args={'balloon_delay': 0, 'balloon_delay_random_offset': 0}), also_show_user_directed=Tunable(description='\n                If checked, this balloon also can be shown for this interaction \n                when it is user-directed.', tunable_type=bool, needs_tuning=True, default=False))), 'allowed_to_combine': Tunable(description="\n        If checked, this interaction will be allowed to combine with other\n        interactions we deem are compatible. If unchecked, it will never be\n        allowed to combine.\n        \n        If we combine multiple interactions, we attempt to solve for all their\n        constraints at once. For example, we tell the Sim to eat and they\n        decide to sit in a chair to do so. While they're routing to that chair,\n        we queue up a go-here. Because the Sim can go to that new location and\n        eat at the same time, we derail their current transition and tell them\n        to do both at once.\n        \n        By default this is set to True, but certain interactions might have\n        deceptive or abnormal constraints that could cause them to be combined in\n        unexpected ways.\n        \n        Please consult a GPE if you think you need to tune this to False.\n        ", tunable_type=bool, default=True), 'mood_list': TunableList(description='\n        A list of possible moods this interaction may associate with.\n        ', tunable=TunableReference(description='\n        A mood associated with this interaction.\n        ', manager=services.mood_manager())), 'ignore_animation_context_liability': Tunable(bool, False, description='\n        This interaction will discard any AnimationContextLiabilities from its\n        source (if a continuation). Use this for interactions that are continuations\n        but share no ASMs or props with their continuation source.')}
    _commodity_flags = EMPTY_SET
    _supported_postures = None
    _autonomy_ads = None
    _simoleon_delta_callbacks = None
    _sim_can_violate_privacy_callbacks = None
    _auto_constraints = None
    _auto_constraints_history = None
    _additional_conditional_actions = None
    _additional_tests = None
    _static_commodities_set = None
    _actor_role_asm_info_map = None
    _provided_posture_type = None
    _progress_bar_goal = None
    Multiplier = namedtuple('Multiplier', ['curve', 'use_effective_skill'])
    _success_chance_multipliers = {}
    _monetary_payout_multipliers = {}
    _expressed = True
    _animation_data_actors = defaultdict(lambda : InteractionAsmType.Unknown)
    disable_transitions = False
    disable_distance_estimation_and_posture_checks = False

    @classmethod
    def is_none_outcome(cls):
        return not cls.outcome.has_content

    @classproperty
    def is_putdown(cls):
        return False

    @classmethod
    def _tuning_loading_callback(cls):
        cls._commodity_flags = EMPTY_SET
        cls._supported_postures = None
        cls._autonomy_ads = None
        cls._simoleon_delta_callbacks = None
        cls._sim_can_violate_privacy_callbacks = None
        cls._auto_constraints = None
        cls._auto_constraints_history = None
        cls._additional_conditional_actions = None
        cls._static_commodities_set = None

    @classmethod
    def register_tuned_animation(cls, interaction_asm_type, asm_key, actor_name, target_name, carry_target_name, create_target_name, overrides, participant_type_actor, participant_type_target):
        if cls._actor_role_asm_info_map is None:
            cls._actor_role_asm_info_map = defaultdict(list)
        data = cls._animation_data_actors[participant_type_actor]
        data |= interaction_asm_type
        cls._animation_data_actors[participant_type_actor] = data
        if participant_type_target is not None and participant_type_target & ParticipantType.AllSims:
            data_target = cls._animation_data_actors[participant_type_target]
            data_target |= interaction_asm_type
            cls._animation_data_actors[participant_type_target] = data_target
        if target_name == 'y':
            data = cls._animation_data_actors[ParticipantType.TargetSim]
            data |= interaction_asm_type
            cls._animation_data_actors[ParticipantType.TargetSim] = data
        list_key = (asm_key, overrides, target_name, carry_target_name, create_target_name)
        if interaction_asm_type == InteractionAsmType.Interaction or interaction_asm_type == InteractionAsmType.Outcome or interaction_asm_type == InteractionAsmType.Response:
            actor_list = cls._actor_role_asm_info_map[ParticipantType.Actor]
            actor_list.append((list_key, 'x'))
            target_list = cls._actor_role_asm_info_map[ParticipantType.TargetSim]
            target_list.append((list_key, 'y'))
        elif interaction_asm_type == InteractionAsmType.Reactionlet:
            target_list = cls._actor_role_asm_info_map[ParticipantType.TargetSim]
            target_list.append((list_key, 'x'))
            listener_list = cls._actor_role_asm_info_map[ParticipantType.Listeners]
            listener_list.append((list_key, 'x'))

    @classmethod
    def add_auto_constraint(cls, participant_type, tuned_constraint, is_canonical=False):
        for ptype in ParticipantType:
            while ptype == participant_type:
                participant_type = ptype
        if cls._auto_constraints is None:
            cls._auto_constraints = {}
        if participant_type in cls._auto_constraints and not is_canonical:
            intersection = cls._auto_constraints[participant_type].intersect(tuned_constraint)
        else:
            intersection = tuned_constraint
        if not intersection.valid:
            logger.error('{}: Interaction is incompatible with itself: {} and {} have no intersection.', cls.__name__, cls._auto_constraints, tuned_constraint)
        cls._auto_constraints[participant_type] = intersection

    @classmethod
    def _add_autonomy_ad(cls, operation, overwrite=False):
        if operation.stat is None:
            logger.error('stat is None in statistic operation {} for {}.', operation, cls, owner='rez')
            return
        if cls._autonomy_ads is None:
            cls._autonomy_ads = {}
        ad_list = cls._autonomy_ads.get(operation.stat)
        if ad_list is None or overwrite:
            ad_list = AutonomyAdList(operation.stat)
            cls._autonomy_ads[operation.stat] = ad_list
        ad_list.add_op(operation)

    @classmethod
    def _remove_autonomy_ad(cls, operation):
        ad_list = cls._autonomy_ads.get(operation.stat)
        if ad_list is None:
            return False
        return ad_list.remove_op(operation)

    def instance_statistic_operations_gen(self):
        for op in self.aditional_instance_ops:
            yield op
        stat_op_list = self._statistic_operations_gen()
        for op in stat_op_list:
            yield op

    @classmethod
    def _statistic_operations_gen(cls):
        if cls.basic_content is None:
            return
        if cls.basic_content.periodic_stat_change is not None:
            for op in cls.basic_content.periodic_stat_change.operations:
                yield op
            for operation_list in cls.basic_content.periodic_stat_change.operation_actions.actions:
                for (op, _) in operation_list.get_loot_ops_gen():
                    yield op
        if cls.basic_content.progressive_stat_change is not None:
            for op in cls.basic_content.progressive_stat_change.additional_operations:
                yield op

    @classmethod
    def get_affordance_key_for_autonomy(cls):
        if cls._affordance_key_override_for_autonomy is not None:
            return cls._affordance_key_override_for_autonomy
        return cls.__qualname__

    @classmethod
    def register_simoleon_delta_callback(cls, callback):
        if cls._simoleon_delta_callbacks:
            cls._simoleon_delta_callbacks.append(callback)
        else:
            cls._simoleon_delta_callbacks = [callback]

    @classmethod
    def register_sim_can_violate_privacy_callback(cls, callback):
        if cls._sim_can_violate_privacy_callbacks:
            cls._sim_can_violate_privacy_callbacks.append(callback)
        else:
            cls._sim_can_violate_privacy_callbacks = [callback]

    @classmethod
    def add_exit_condition(cls, condition_factory_list):
        action = ExitCondition(conditions=condition_factory_list, interaction_action=ConditionalInteractionAction.EXIT_NATURALLY)
        if cls._additional_conditional_actions:
            cls._additional_conditional_actions.append(action)
        else:
            cls._additional_conditional_actions = [action]

    @classmethod
    def add_additional_test(cls, test):
        if cls._additional_tests:
            cls._additional_tests.append(test)
        else:
            cls._additional_tests = [test]

    @classmethod
    def _tuning_loaded_callback(cls):
        for op in cls._statistic_operations_gen():
            while op.advertise and op.subject == ParticipantType.Actor:
                cls._add_autonomy_ad(op)
        for op in cls._false_advertisements_gen():
            cls._add_autonomy_ad(op, overwrite=True)
        cls._update_commodity_flags()
        if not cls._supported_postures:
            supported_postures = cls._define_supported_postures()
            if supported_postures is not None and not isinstance(supported_postures, dict):
                supported_postures = {ParticipantType.Actor: supported_postures}
            cls._supported_postures = supported_postures
        for liability in cls.basic_liabilities:
            liability.factory.on_affordance_loaded_callback(cls, liability)
        for basic_extra in cls.basic_extras:
            while hasattr(basic_extra.factory, AFFORDANCE_LOADED_CALLBACK_STR):
                basic_extra.factory.on_affordance_loaded_callback(cls, basic_extra)
        if cls.outcome is not None:
            for basic_extra in cls.outcome.get_basic_extras_gen():
                while hasattr(basic_extra.factory, AFFORDANCE_LOADED_CALLBACK_STR):
                    basic_extra.factory.on_affordance_loaded_callback(cls, basic_extra)
        progress_bar_tuning = cls.progress_bar_enabled.force_listen_statistic
        if progress_bar_tuning is not None and progress_bar_tuning.statistic is None:
            logger.error('Progress bar forced commodity is none for interaction {}.', cls, owner='camilogarcia')

    @classmethod
    def _verify_tuning_callback(cls):
        if cls.immediate and cls.staging:
            logger.error('{} is tuned to be staging but is marked immediate, this is not allowed.  Suggestion: set basic_content to one-shot or uncheck immediate.', cls.__name__)
        if cls.outcome is not None:
            cls.outcome.interaction_cls_name = cls.__name__
        if cls.visible and cls.display_name is not None and not cls.display_name:
            logger.error('Interaction {} is visible but has no display name', cls.__name__)
        if cls.basic_content:
            cls.basic_content.validate_tuning()

    @classmethod
    def _update_commodity_flags(cls):
        commodity_flags = set()
        if cls._autonomy_ads:
            for stat in cls._autonomy_ads:
                commodity_flags.add(stat)
        static_commodities = cls.static_commodities
        if static_commodities:
            commodity_flags.update(static_commodities)
        if commodity_flags:
            cls._commodity_flags = frozenset(commodity_flags)

    @classmethod
    def contains_stat(cls, stat):
        if stat is None:
            logger.warn('Pass in None stat to ask whether {} contains it.', cls.__name__)
            return False
        for op in cls._statistic_operations_gen():
            while stat is op.stat:
                return True
        return False

    def is_adjustment_interaction(self):
        return False

    @classmethod
    def add_skill_multiplier(cls, multiplier_dict, skill_type, curve, use_effective_skill):
        if cls not in multiplier_dict:
            multiplier_dict[cls] = {}
        multiplier_dict[cls][skill_type] = cls.Multiplier(curve, use_effective_skill)

    @classmethod
    def get_skill_multiplier(cls, multiplier_dict, target):
        multiplier = 1
        if cls in multiplier_dict:
            for skill_type in multiplier_dict[cls]:
                skill = target.get_stat_instance(skill_type)
                while skill is not None:
                    modifier = multiplier_dict[cls][skill_type]
                    if modifier.use_effective_skill:
                        value = target.Buffs.get_effective_skill_level(skill)
                    else:
                        value = skill.get_user_value()
                    multiplier *= modifier.curve.get(value)
        return multiplier

    def should_fade_sim_out(self):
        return self.fade_sim_out

    @classproperty
    def success_chance_multipliers(cls):
        return cls._success_chance_multipliers

    @classproperty
    def monetary_payout_multipliers(cls):
        return cls._monetary_payout_multipliers

    def _get_conditional_actions_for_content(self, basic_content):
        conditional_actions = []
        if basic_content.conditional_actions:
            actions = snippets.flatten_snippet_list(basic_content.conditional_actions)
            conditional_actions.extend(actions)
        if basic_content is not None and self._additional_conditional_actions:
            actions = snippets.flatten_snippet_list(self._additional_conditional_actions)
            conditional_actions.extend(actions)
        return conditional_actions

    def get_conditional_actions(self):
        actions = self._get_conditional_actions_for_content(self.basic_content)
        if self.target is not None:
            target_basic_content = self.target.get_affordance_basic_content(self)
            if target_basic_content is not None:
                target_actions = self._get_conditional_actions_for_content(target_basic_content)
                actions.extend(target_actions)
        return actions

    def _get_start_as_guaranteed_for_content(self, basic_content):
        if basic_content is not None:
            if self.is_user_directed:
                return not self.basic_content.start_user_directed_inertial
            return not self.basic_content.start_autonomous_inertial
        return False

    def get_start_as_guaranteed(self):
        if self._get_start_as_guaranteed_for_content(self.basic_content):
            return True
        if self.target is not None:
            target_basic_content = self.target.get_affordance_basic_content(self)
            if self._get_start_as_guaranteed_for_content(target_basic_content):
                return True
        return False

    def __str__(self):
        return 'Interaction {} on {}; id:{}, sim:{}'.format(self.affordance, self.target, self.id, self.sim)

    def __repr__(self):
        return '<Interaction {} id:{} sim:{}>'.format(self.affordance.__name__, self.id, self.sim)

    @classproperty
    def autonomy_preference(cls):
        pass

    @classproperty
    def interaction(cls):
        return cls

    @classproperty
    def requires_target_support(cls):
        return True

    @classmethod
    def get_interaction_type(cls):
        return cls

    def get_linked_interaction_type(self):
        pass

    @classmethod
    def generate_continuation_affordance(cls, affordance):
        return affordance

    def get_target_si(self):
        return (None, True)

    @staticmethod
    def _tunable_tests_enabled():
        return True

    @flexmethod
    def get_display_tooltip(cls, inst, override=None, context=DEFAULT, **kwargs):
        inst_or_cls = inst if inst is not None else cls
        context = inst.context if context is DEFAULT else context
        sim = inst.sim if inst is not None else context.sim
        tooltip = inst_or_cls.display_tooltip
        if override is not None and override.new_display_tooltip is not None:
            tooltip = override.new_display_tooltip
        if tooltip is not None:
            tooltip = inst_or_cls.create_localized_string(tooltip, context=context, **kwargs)
        if inst_or_cls.item_cost is not None:
            tooltip = inst_or_cls.item_cost.get_interaction_tooltip(tooltip=tooltip, sim=sim)
        return tooltip

    @flexmethod
    def skip_test_on_execute(cls, inst):
        if inst is not None:
            return inst.aop.skip_test_on_execute
        return False

    @classmethod
    def _test(cls, target, context, **interaction_parameters):
        return event_testing.results.TestResult.TRUE

    @flexmethod
    def test(cls, inst, target=DEFAULT, context=DEFAULT, super_interaction=None, skip_safe_tests=False, test_list_method_name='run_tests', **interaction_parameters):
        inst_or_cls = inst if inst is not None else cls
        target = target if target is not DEFAULT else inst.target
        context = context if context is not DEFAULT else inst.context
        if inst_or_cls.is_super:
            for obj in inst_or_cls.get_participants(ParticipantType.All, sim=context.sim, target=target, **interaction_parameters):
                if obj.build_buy_lockout:
                    return event_testing.results.TestResult(False, 'Target object has been locked out and cannot be interacted with.')
                while not obj.visible_to_client:
                    return event_testing.results.TestResult(False, 'The object {} in this interaction has been removed from the client and is no longer expected to be accessible [tastle/jpollak]', obj)
        if inst.interaction_parameters and interaction_parameters:
            interaction_parameters = frozendict(inst.interaction_parameters, interaction_parameters)
        else:
            interaction_parameters = inst.interaction_parameters or interaction_parameters
        if inst is not None and super_interaction is None:
            super_interaction = inst.super_interaction
        result = event_testing.results.TestResult.TRUE
        try:
            if cls.is_super and (cls.visible and target is None) and cls._icon is None:
                return event_testing.results.TestResult(False, 'Visible interaction has no target, which is invalid for displaying icons.')
            if context.sim is None:
                if not cls.simless:
                    return event_testing.results.TestResult(False, 'No Sim specified in context.')
            elif not (context.source == context.SOURCE_AUTONOMY and context.sim.test_interaction_for_distress_compatability(cls)):
                return event_testing.results.TestResult(False, 'Interaction is not compatible with current distress.')
            if target.is_in_inventory():
                if target.is_in_sim_inventory():
                    if not cls.allow_from_sim_inventory:
                        return event_testing.results.TestResult(False, 'Interaction is not valid from sim inventory.')
                        if not cls.allow_from_object_inventory:
                            return event_testing.results.TestResult(False, 'Interaction is not valid from object inventory.')
                elif not cls.allow_from_object_inventory:
                    return event_testing.results.TestResult(False, 'Interaction is not valid from object inventory.')
            else:
                is_starting = interaction_parameters.get('interaction_starting', False)
                if not is_starting and not cls.allow_from_world:
                    return event_testing.results.TestResult(False, 'Interaction is not valid from the world.')
            if not (target is not None and cls.simless):
                if target.parent is not None and target.parent.is_sim:
                    if target.parent is not context.sim and not target.is_set_as_head:
                        return event_testing.results.TestResult(False, 'Target is being held by another Sim.')
            if inst_or_cls is not None and inst_or_cls.test_incest and target is not None:
                if not context.sim.sim_info.incest_prevention_test(target):
                    return event_testing.results.TestResult(False, 'Not available because it violates the incest rules.')
            if inst_or_cls is not None and not inst_or_cls.debug:
                fire_service = services.get_fire_service()
                if fire_service is not None:
                    fire_interaction_test_result = fire_service.fire_interaction_test(inst_or_cls.affordance, context)
                    if not fire_interaction_test_result:
                        return fire_interaction_test_result
            instance_result = inst_or_cls._test(target, context, skip_safe_tests=skip_safe_tests, **interaction_parameters)
            if not (instance_result or instance_result.tooltip):
                return instance_result
            if inst_or_cls._tunable_tests_enabled():
                search_for_tooltip = context.source == context.SOURCE_PIE_MENU
                resolver = inst_or_cls.get_resolver(target=target, context=context, super_interaction=super_interaction, search_for_tooltip=search_for_tooltip, **interaction_parameters)
                global_test_set_method = getattr(cls.test_globals, test_list_method_name)
                global_result = global_test_set_method(resolver, skip_safe_tests, search_for_tooltip)
                local_result = event_testing.results.TestResult.TRUE
                autonomous_result = event_testing.results.TestResult.TRUE
                target_result = event_testing.results.TestResult.TRUE
                if global_result or search_for_tooltip and global_result.tooltip is not None:
                    local_test_set_method = getattr(cls.tests, test_list_method_name)
                    local_result = local_test_set_method(resolver, skip_safe_tests, search_for_tooltip)
                    if (local_result or search_for_tooltip) and local_result.tooltip is not None and inst_or_cls._additional_tests:
                        additional_tests = TestList(inst_or_cls._additional_tests)
                        additional_local_test_set_method = getattr(additional_tests, test_list_method_name)
                        local_result = additional_local_test_set_method(resolver, skip_safe_tests, search_for_tooltip)
                    if (local_result or search_for_tooltip) and local_result.tooltip is not None and target is not None:
                        tests = target.get_affordance_tests(inst_or_cls)
                        if tests is not None:
                            object_test_set_method = getattr(tests, test_list_method_name)
                            target_result = object_test_set_method(resolver, skip_safe_tests, search_for_tooltip)
                    if local_result and context.source == InteractionContext.SOURCE_AUTONOMY:
                        if inst_or_cls.test_autonomous:
                            autonomous_test_set_method = getattr(cls.test_autonomous, test_list_method_name)
                            autonomous_result = autonomous_test_set_method(resolver, skip_safe_tests, False)
                if not target_result:
                    result = target_result
                elif not local_result:
                    result = local_result
                elif not global_result:
                    result = global_result
                else:
                    result = autonomous_result
            if not result:
                return result
            result = target_result & local_result & global_result & autonomous_result
            result &= instance_result
            if result:
                household = services.active_household()
                if household is not None:
                    result &= household.bills_manager.test_utility_info(cls.utility_info)
                    if result:
                        cost = inst_or_cls.get_simoleon_cost(target=target, context=context)
                        if household.funds.money < cost:
                            result &= event_testing.results.TestResult(False, 'Household does not have enough money to perform this interaction.', tooltip=payment.PaymentElement.CANNOT_AFFORD_TOOLTIP)
            if result:
                result &= inst_or_cls.item_cost.get_test_result(context.sim, inst_or_cls)
            if result and not cls.allow_while_save_locked:
                fail_reason = services.get_persistence_service().get_save_lock_tooltip()
                if fail_reason is not None:
                    error_tooltip = lambda *_, **__: fail_reason
                    return event_testing.results.TestResult(False, 'Interaction is not allowed to run while save is locked.', tooltip=error_tooltip)
            if not result:
                return result
        except Exception as e:
            logger.exception('Exception during call to test method on {0}', cls)
            return event_testing.results.TestResult(False, 'Exception: {}', e)
        if not isinstance(result, event_testing.results.TestResult):
            logger.warn("Interaction test didn't return a TestResult: {}: {}", result, cls.__name__, result)
            return event_testing.results.TestResult(result)
        return result

    @classmethod
    def can_make_test_pass(cls, *args, **kwargs):
        return cls.test(test_list_method_name='can_make_pass', *args, **kwargs)

    @classmethod
    def make_test_pass(cls, *args, **kwargs):
        return cls.test(test_list_method_name='make_pass', *args, **kwargs)

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
    def get_participants(cls, inst, participant_type, sim=DEFAULT, target=DEFAULT, carry_target=DEFAULT, listener_filtering_enabled=False, target_type=None, **interaction_parameters) -> set:
        global interaction_get_particpants_call_count
        interaction_get_particpants_call_count += 1
        if interaction_get_particpants_call_count % SIM_YIELD_INTERACTION_GET_PARTICIPANTS_MOD == 0:
            yield_to_irq()
        participant_type = int(participant_type)
        if inst is not None:
            if inst.interaction_parameters and interaction_parameters:
                interaction_parameters = frozendict(inst.interaction_parameters, interaction_parameters)
            else:
                interaction_parameters = inst.interaction_parameters or interaction_parameters
        inst_or_cls = inst if inst is not None else cls
        if inst_or_cls.simless:
            sim = None
        else:
            sim = inst.sim if sim is DEFAULT else sim
        target = inst.target if target is DEFAULT else target
        if participant_type == ParticipantType.Actor:
            if sim is not None:
                return (sim,)
            return ()
        if participant_type == ParticipantType.Object:
            if target is not None:
                return (target,)
            return ()
        if participant_type == ParticipantType.TargetSim:
            if target is not None and target.is_sim:
                return (target,)
            return ()
        if inst is not None:
            carry_target = inst.carry_target if carry_target is DEFAULT else carry_target
        is_all = participant_type & ParticipantType.All
        all_sims = participant_type & ParticipantType.AllSims
        if target_type is None:
            target_type = inst_or_cls.target_type
        result = set()
        if is_all:
            all_sims = True
        target_is_sim = target is not DEFAULT and (target is not None and target.is_sim)
        if (all_sims or participant_type & ParticipantType.Actor) and sim is not None:
            result.add(sim)
        if (is_all or participant_type & ParticipantType.Object) and target is not None:
            result.add(target)
        if (is_all or participant_type & ParticipantType.ObjectParent) and (target is not None and not target.is_sim) and target.parent is not None:
            result.add(target.parent)
        if participant_type & ParticipantType.ObjectChildren and target is not None:
            result.update(target.children_recursive_gen())
        if is_all or participant_type & ParticipantType.CarriedObject:
            if carry_target is not None and carry_target is not DEFAULT:
                result.add(carry_target)
            elif 'carry_target' in interaction_parameters and target is not None:
                result.add(target)
        if (all_sims or participant_type & ParticipantType.TargetSim) and target_is_sim:
            result.add(target)
        if all_sims or participant_type & ParticipantType.JoinTarget:
            join_target_ref = interaction_parameters.get('join_target_ref')
            if join_target_ref is not None:
                result.add(join_target_ref())
        social_group = inst.social_group if inst is not None else None
        if target_type & TargetType.TARGET and (target is not None and target_is_sim) and (not target.ignore_group_socials(excluded_group=social_group) or not listener_filtering_enabled):
            result.add(target)
        if (all_sims or participant_type & ParticipantType.Listeners) and inst is not None and target_type & TargetType.GROUP:
            if social_group is not None:
                while True:
                    for other_sim in social_group:
                        if other_sim is sim:
                            pass
                        while True:
                            for si in social_group.get_sis_registered_for_sim(other_sim):
                                while si.pipeline_progress >= PipelineProgress.RUNNING and not si.is_finishing:
                                    break
                        if inst.acquire_listeners_as_resource or other_sim.ignore_group_socials(excluded_group=social_group) and listener_filtering_enabled:
                            pass
                        if inst._required_sims is not None and listener_filtering_enabled and other_sim not in inst._required_sims:
                            pass
                        result.add(other_sim)
        if participant_type & ParticipantType.SocialGroup and (inst is not None and inst.is_social) and inst.social_group is not None:
            result.add(inst.social_group)
        if participant_type & ParticipantType.SocialGroupSims and target_is_sim:
            result.add(target)
            while True:
                for social_group in target.get_groups_for_sim_gen():
                    for group_sim in social_group:
                        result.add(group_sim)
        if sim is not None and sim.posture_state is not None and (is_all or participant_type & ParticipantType.ActorSurface):
            if sim.posture_state.surface_target is not None:
                result.add(sim.posture_state.surface_target)
        if participant_type & ParticipantType.CreatedObject and inst is not None and inst.created_target is not None:
            result.add(inst.created_target)
        if participant_type & ParticipantType.PickedItemId:
            picked_item_ids = interaction_parameters.get('picked_item_ids')
            if picked_item_ids is not None:
                result.update(picked_item_ids)
        if participant_type & ParticipantType.Unlockable:
            unlockable_name = interaction_parameters.get('unlockable_name')
            if unlockable_name is not None:
                result.add(unlockable_name)
        if participant_type & ParticipantType.PickedObject:
            picked_item_ids = interaction_parameters.get('picked_item_ids')
            if picked_item_ids is not None:
                object_manager = services.object_manager()
                inventory_manager = services.current_zone().inventory_manager
                while True:
                    for picked_item_id in picked_item_ids:
                        obj = object_manager.get(picked_item_id)
                        if obj is None:
                            obj = inventory_manager.get(picked_item_id)
                        while obj is not None:
                            result.add(obj)
        if participant_type & ParticipantType.PickedSim:
            picked_item_ids = interaction_parameters.get('picked_item_ids')
            if picked_item_ids is not None:
                while True:
                    for picked_item_id in picked_item_ids:
                        sim_info = services.sim_info_manager().get(picked_item_id)
                        while sim_info is not None:
                            result.add(sim_info.get_sim_instance() or sim_info)
        if participant_type & ParticipantType.StoredSim and target is not None:
            stored_sim_info = target.get_stored_sim_info()
            if stored_sim_info is not None:
                result.add(stored_sim_info.get_sim_instance() or stored_sim_info)
        if participant_type & ParticipantType.StoredSimOnActor and sim is not None:
            stored_sim_info = sim.get_stored_sim_info()
            if stored_sim_info is not None:
                result.add(stored_sim_info.get_sim_instance() or stored_sim_info)
        if participant_type & ParticipantType.OwnerSim and target is not None:
            owner_sim_info_id = target.get_sim_owner_id()
            owner_sim_info = services.sim_info_manager().get(owner_sim_info_id)
            if owner_sim_info is not None:
                result.add(owner_sim_info.get_sim_instance() or owner_sim_info)
        if participant_type & ParticipantType.SignificantOtherActor and sim is not None:
            spouse = sim.get_significant_other_sim_info()
            if spouse is not None:
                result.add(spouse.get_sim_instance() or spouse)
        if participant_type & ParticipantType.SignificantOtherTargetSim and target is not None and target.is_sim:
            spouse = target.get_significant_other_sim_info()
            if spouse is not None:
                result.add(spouse.get_sim_instance() or spouse)
        if participant_type & ParticipantType.PregnancyPartnerActor and sim is not None:
            partner = sim.sim_info.pregnancy_tracker.get_partner()
            if partner is not None:
                result.add(partner.get_sim_instance() or partner)
        if participant_type & ParticipantType.PregnancyPartnerTargetSim and target is not None and target.is_sim:
            partner = target.sim_info.pregnancy_tracker.get_partner()
            if partner is not None:
                result.add(partner.get_sim_instance() or partner)
        if participant_type & ParticipantType.Lot:
            result.update(event_testing.resolver.Resolver.get_particpants_shared(ParticipantType.Lot))
        if participant_type & ParticipantType.PickedZoneId:
            picked_zone_ids = interaction_parameters.get('picked_zone_ids')
            if picked_zone_ids is not None:
                result.update(picked_zone_ids)
        if target.is_part:
            users_target = target.part_owner
        else:
            users_target = target
        if participant_type & ParticipantType.OtherSimsInteractingWithTarget and target is not None and hasattr(users_target, 'get_users'):
            other_sims = users_target.get_users(sims_only=True)
            all_sims_for_removal = inst_or_cls.get_participants(ParticipantType.AllSims, sim=sim, target=target, carry_target=carry_target, **interaction_parameters)
            result.update(other_sims - set(all_sims_for_removal))
        if participant_type & ParticipantType.LotOwners:
            owners = event_testing.resolver.Resolver.get_particpants_shared(ParticipantType.LotOwners)
            if owners is not None:
                result.update(owners)
        if participant_type & ParticipantType.SocialGroupAnchor and inst is not None:
            group = inst.social_group
            if group is not None and group.anchor is not None:
                result.add(group.anchor)
        if None in result:
            logger.error('Get Participants {} for interaction {} on target {} gave a results list that contains None. None should never be in the result list. Removing.', participant_type, inst_or_cls, target, owner='yshan')
            result.discard(None)
        return tuple(result)

    PRIORITY_PARTICIPANT_TYPES = (ParticipantType.Actor, ParticipantType.TargetSim, ParticipantType.Listeners)
    AGGREGATE_PARTICIPANT_TYPES = (ParticipantType.All, ParticipantType.AllSims)

    @flexmethod
    def get_participant_type(cls, inst, participant, restrict_to_participant_types=None, exclude_participant_types=(), **kwargs) -> ParticipantType:
        inst_or_cls = inst if inst is not None else cls
        priority_participant_types = inst_or_cls.PRIORITY_PARTICIPANT_TYPES
        exclude_participant_types = inst_or_cls.AGGREGATE_PARTICIPANT_TYPES + exclude_participant_types
        for participant_type in priority_participant_types:
            if restrict_to_participant_types is not None and participant_type not in restrict_to_participant_types:
                pass
            if participant_type in exclude_participant_types:
                pass
            while participant in inst_or_cls.get_participants(participant_type, **kwargs):
                return participant_type
        for (_, participant_type) in ParticipantType.items():
            if participant_type in priority_participant_types:
                pass
            if restrict_to_participant_types is not None and participant_type not in restrict_to_participant_types:
                pass
            if participant_type in exclude_participant_types:
                pass
            while participant in inst_or_cls.get_participants(participant_type, **kwargs):
                return participant_type

    def can_sim_violate_privacy(self, sim):
        if self._sim_can_violate_privacy_callbacks:
            for callback in self._sim_can_violate_privacy_callbacks:
                while callback(self, sim):
                    return True
        return False

    @flexmethod
    def get_simoleon_deltas_gen(cls, inst, target=DEFAULT, context=DEFAULT):
        inst_or_cls = inst if inst is not None else cls
        if inst_or_cls._simoleon_delta_callbacks:
            for callback in inst_or_cls._simoleon_delta_callbacks:
                yield callback(inst_or_cls, target, context)

    @flexmethod
    def get_simoleon_cost(cls, inst, target=DEFAULT, context=DEFAULT):
        inst_or_cls = inst if inst is not None else cls
        return -sum(amount for amount in inst_or_cls.get_simoleon_deltas_gen(target, context) if amount < 0)

    @flexmethod
    def get_simoleon_payout(cls, inst, target=DEFAULT, context=DEFAULT):
        inst_or_cls = inst if inst is not None else cls
        return sum(amount for amount in inst_or_cls.get_simoleon_deltas_gen(target, context) if amount > 0)

    @classmethod
    def get_category_tags(cls):
        return cls.interaction_category_tags

    @flexmethod
    def get_pie_menu_category(cls, inst, **interaction_parameters):
        inst_or_cls = inst if inst is not None else cls
        return inst_or_cls.category

    @flexmethod
    def get_name_override_and_test_result(cls, inst, **kwargs):
        inst_or_cls = inst if inst is not None else cls
        if inst_or_cls.display_name_overrides is not None:
            return inst_or_cls.display_name_overrides.get_display_name_and_result(inst_or_cls, **kwargs)
        return (None, event_testing.results.TestResult.NONE)

    @flexmethod
    def get_name_override_tunable_and_result(cls, inst, **kwargs):
        inst_or_cls = inst if inst is not None else cls
        (override_tunable, test_result) = inst_or_cls.get_name_override_and_test_result(**kwargs)
        if override_tunable is not None:
            return (override_tunable, test_result)
        return (None, test_result)

    @flexmethod
    def get_name(cls, inst, target=DEFAULT, context=DEFAULT, apply_name_modifiers=True, **interaction_parameters):
        inst_or_cls = inst if inst is not None else cls
        display_name = inst_or_cls._get_name(target=target, context=context, **interaction_parameters)
        if inst is None and cls.SIMOLEON_DELTA_MODIFIES_AFFORDANCE_NAME or inst.SIMOLEON_DELTA_MODIFIES_INTERACTION_NAME:
            simoleon_cost = inst_or_cls.get_simoleon_cost(target=target, context=context)
            if simoleon_cost > 0 and inst_or_cls.SIMOLEON_COST_NAME_FACTORY is not None:
                display_name = inst_or_cls.SIMOLEON_COST_NAME_FACTORY(display_name, simoleon_cost)
            elif inst_or_cls.SIMOLEON_GAIN_NAME_FACTORY is not None:
                simoleon_payout = inst_or_cls.get_simoleon_payout(target=target, context=context)
                if simoleon_payout > 0:
                    display_name = inst_or_cls.SIMOLEON_GAIN_NAME_FACTORY(display_name, simoleon_payout)
        if inst is None and cls.ITEM_COST_NAME_FACTORY:
            display_name = cls.item_cost.get_interaction_name(cls, display_name)
        if apply_name_modifiers and inst_or_cls.debug and inst_or_cls.DEBUG_NAME_FACTORY is not None:
            display_name = inst_or_cls.DEBUG_NAME_FACTORY(display_name)
        return display_name

    @flexmethod
    def _get_name(cls, inst, target=DEFAULT, context=DEFAULT, **interaction_parameters):
        inst_or_cls = inst if inst is not None else cls
        display_name = inst_or_cls.display_name
        (override_tunable, _) = inst_or_cls.get_name_override_and_test_result(target=target, context=context)
        if override_tunable is not None:
            display_name = override_tunable.new_display_name
        display_name = inst_or_cls.create_localized_string(display_name, target=target, context=context, **interaction_parameters)
        return display_name

    @flexmethod
    def create_localized_string(cls, inst, localized_string_factory, *tokens, **kwargs):
        inst_or_cls = inst if inst is not None else cls
        interaction_tokens = inst_or_cls.get_localization_tokens(**kwargs)
        return localized_string_factory(*interaction_tokens + tokens)

    @flexmethod
    def get_localization_tokens(cls, inst, **interaction_parameters):
        inst_or_cls = inst if inst is not None else cls
        tokens = inst_or_cls.display_name_text_tokens.get_tokens(inst_or_cls.get_resolver(**interaction_parameters))
        return tokens

    @classmethod
    def visual_targets_gen(cls, target, context, **kwargs):
        yield target

    @classmethod
    def has_pie_menu_sub_interactions(cls, target, context, **kwargs):
        return False

    @classmethod
    def potential_pie_menu_sub_interactions_gen(cls, target, context, **kwargs):
        pass

    @classproperty
    def is_super(cls):
        return False

    @classmethod
    def _false_advertisements_gen(cls):
        for false_add in cls._false_advertisements:
            yield false_add

    @classproperty
    def commodity_flags(cls):
        return cls._commodity_flags

    @classmethod
    def autonomy_ads_gen(cls, target=None, include_hidden_false_ads=False):
        if target is not None:
            for ad in target.get_affordance_false_ads(cls):
                cls._add_autonomy_ad(ad, overwrite=False)
        if include_hidden_false_ads:
            for ad in cls._hidden_false_advertisements:
                cls._add_autonomy_ad(ad, overwrite=False)
        if cls._autonomy_ads:
            for ad_list in cls._autonomy_ads.values():
                yield ad_list
        if include_hidden_false_ads:
            for ad in cls._hidden_false_advertisements:
                cls._remove_autonomy_ad(ad)
        if target is not None:
            for ad in target.get_affordance_false_ads(cls):
                cls._remove_autonomy_ad(ad)

    @classproperty
    def static_commodities(cls):
        static_commodities_frozen_set = frozenset([data.static_commodity for data in cls.static_commodities_data])
        return static_commodities_frozen_set

    @classproperty
    def static_commodities_data(cls):
        if cls._static_commodities_set is None:
            cls._refresh_static_commodity_cache()
        return cls._static_commodities_set

    @classmethod
    def _refresh_static_commodity_cache(cls):
        if cls._static_commodities:
            static_commodities_set = set(cls._static_commodities)
        else:
            static_commodities_set = set()
        cls._static_commodities_set = frozenset(static_commodities_set)

    @classproperty
    def provided_posture_type(cls):
        pass

    @flexmethod
    def get_associated_skill(cls, inst):
        skill = None
        if inst is not None:
            skill = inst.stat_from_skill_loot_data
        elif cls.outcome is not None:
            skill = cls.outcome.associated_skill
        return skill

    @flexmethod
    def _get_skill_loot_data(cls, inst):
        if inst is not None and inst.target is not None:
            target_skill_loot_data = inst.target.get_affordance_skill_loot_data(inst)
            if target_skill_loot_data is not None:
                return target_skill_loot_data
        return cls.skill_loot_data

    @flexproperty
    def stat_from_skill_loot_data(cls, inst):
        inst_or_cls = inst if inst is not None else cls
        skill_loot_data = inst_or_cls._get_skill_loot_data()
        return skill_loot_data.stat or inst_or_cls.skill_loot_data.stat

    @flexproperty
    def skill_effectiveness_from_skill_loot_data(cls, inst):
        inst_or_cls = inst if inst is not None else cls
        skill_loot_data = inst_or_cls._get_skill_loot_data()
        return skill_loot_data.effectiveness or inst_or_cls.skill_loot_data.effectiveness

    @flexproperty
    def level_range_from_skill_loot_data(cls, inst):
        inst_or_cls = inst if inst is not None else cls
        skill_loot_data = inst_or_cls._get_skill_loot_data()
        return skill_loot_data.level_range or inst_or_cls.skill_loot_data.level_range

    @classproperty
    def approximate_duration(cls):
        return cls.time_overhead

    @classmethod
    def get_supported_postures(cls, participant_type=ParticipantType.Actor):
        default_support = None if participant_type == ParticipantType.Actor else ALL_POSTURES
        if cls._supported_postures:
            return cls._supported_postures.get(participant_type, default_support)
        return default_support

    @classmethod
    def _define_supported_postures(cls):
        if not cls._actor_role_asm_info_map:
            return
        posture_support_map = None
        for (actor_role, asm_info) in cls._actor_role_asm_info_map.items():
            supported_postures = None
            for ((asm_key, overrides, target_name, carry_target_name, create_target_name), actor_name) in asm_info:
                posture_manifest_overrides = None
                if overrides is not None:
                    posture_manifest_overrides = overrides.manifests
                asm = animation.asm.Asm(asm_key, None, posture_manifest_overrides)
                supported_postures_asm = asm.get_supported_postures_for_actor(actor_name)
                while supported_postures_asm is not None:
                    for posture_manifest_entry in supported_postures_asm:
                        manifest_carry_target = posture_manifest_entry.carry_target
                        while manifest_carry_target:
                            if manifest_carry_target != target_name and manifest_carry_target != carry_target_name and manifest_carry_target != create_target_name:
                                logger.error("{}: The ASM {}'s posture manifest references a carried object ({}) that isn't the target, carry_target, or create_target of the animation tuning.", cls.__name__, asm.name, manifest_carry_target)
                    if supported_postures is None:
                        supported_postures = PostureManifest()
                    supported_postures.update(supported_postures_asm)
            while supported_postures is not None:
                if posture_support_map is None:
                    posture_support_map = {}
                posture_support_map[actor_role] = supported_postures
        return posture_support_map

    @classmethod
    def filter_supported_postures(cls, supported_postures_from_asm, filter_posture_name=None, force_carry_state=None):
        if supported_postures_from_asm is ALL_POSTURES:
            return ALL_POSTURES
        if force_carry_state is None:
            force_carry_state = (None, None)
        filter_entry = PostureManifestEntry(None, filter_posture_name, filter_posture_name, MATCH_ANY, force_carry_state[0], force_carry_state[1], None)
        supported_postures = supported_postures_from_asm.intersection_single(filter_entry)
        return supported_postures

    @flexmethod
    def constraint_gen(cls, inst, sim, target, participant_type=ParticipantType.Actor):
        inst_or_cls = cls if inst is None else inst
        if inst_or_cls.basic_reserve_object is None or cls.basic_reserve_object._tuned_values.reserve_type(None, sim, None).is_multi:
            for constraint in inst_or_cls._constraint_gen(sim, target, participant_type):
                yield constraint.generate_forbid_small_intersections_constraint()
        else:
            yield inst_or_cls._constraint_gen(sim, target, participant_type)

    @classmethod
    def _constraint_gen(cls, sim, target, participant_type=ParticipantType.Actor):
        if participant_type == ParticipantType.Actor and cls._constraints:
            while True:
                for tuned_constraint in cls._constraints:
                    yield tuned_constraint.create_constraint(sim, target)
        if cls._auto_constraints is not None and participant_type in cls._auto_constraints:
            yield cls._auto_constraints[participant_type]

    @flexmethod
    def get_constraint_target(cls, inst, target):
        constraint_target = target
        if inst is not None:
            constraint_target = inst.get_participant(participant_type=cls._constraints_actor)
        return constraint_target

    @flexmethod
    def constraint_intersection(cls, inst, sim=DEFAULT, target=DEFAULT, participant_type=DEFAULT, *, posture_state=DEFAULT, force_concrete=True, allow_holster=DEFAULT, invalid_expected=False):
        inst_or_cls = inst if inst is not None else cls
        target = inst.target if target is DEFAULT else target
        if sim is DEFAULT and participant_type is DEFAULT:
            participant_type = ParticipantType.Actor
        sim = inst_or_cls.get_participant(participant_type, target=target) if sim is DEFAULT else sim
        if sim is None:
            return ANYWHERE
        if posture_state is DEFAULT:
            posture_state = sim.posture_state
        if inst is not None and posture_state is not None and posture_state.body.source_interaction is inst:
            return posture_state.body_posture_state_constraint
        participant_type = inst_or_cls.get_participant_type(sim, target=target) if participant_type is DEFAULT else participant_type
        if participant_type is None:
            return NOWHERE
        if inst is None or allow_holster is not DEFAULT:
            intersection = None
        elif __debug__ and not caches.use_constraints_cache:
            intersection = None
        else:
            if posture_state is not None:
                cached_constraint = inst._constraint_cache_final.get(posture_state)
                if cached_constraint:
                    return cached_constraint
            intersection = inst._constraint_cache.get(sim)
        inst_or_cls = inst if inst is not None else cls
        if intersection is None:
            intersection = ANYWHERE
            constraints = list(inst_or_cls.constraint_gen(sim, inst_or_cls.get_constraint_target(target), participant_type=participant_type))
            for constraint in constraints:
                if inst is not None:
                    if force_concrete:
                        constraint = constraint.create_concrete_version(inst)
                    constraint_resolver = inst.get_constraint_resolver(None, participant_type=participant_type, force_actor=sim)
                    constraint = constraint.apply_posture_state(None, constraint_resolver, affordance=inst_or_cls.affordance)
                    constraint = constraint.add_slot_constraints_if_possible(sim)
                test_intersection = constraint.intersect(intersection)
                intersection = test_intersection
                while not intersection.valid:
                    break
            if inst is not None and intersection.valid and allow_holster is DEFAULT:
                inst._constraint_cache[sim] = intersection
        if not intersection.valid:
            return intersection
        final_intersection = inst_or_cls.apply_posture_state_and_interaction_to_constraint(posture_state, intersection, sim=sim, target=target, participant_type=participant_type, allow_holster=allow_holster, invalid_expected=invalid_expected)
        if inst is not None and posture_state is not None and allow_holster is DEFAULT:
            inst._constraint_cache_final[posture_state] = final_intersection
        return final_intersection

    def is_guaranteed(self):
        return not self.has_active_cancel_replacement

    @classmethod
    def consumes_object(cls):
        return cls.outcome.consumes_object

    @classproperty
    def interruptible(cls):
        return False

    def __init__(self, aop, context, aop_id=None, super_affordance=None, must_run=False, posture_target=None, liabilities=None, find_best_posture=DEFAULT, route_fail_on_transition_fail=True, name_override=None, load_data=None, depended_on_si=None, anim_overrides=None, set_work_timestamp=True, **kwargs):
        self._kwargs = kwargs
        self._aop = aop
        self.context = context
        self.anim_overrides = anim_overrides
        if name_override is not None:
            self.name_override = name_override
        self._pipeline_progress = PipelineProgress.NONE
        self._constraint_cache = WeakKeyDictionary()
        self._constraint_cache_final = WeakKeyDictionary()
        self._target = None
        self.set_target(aop.target)
        self.carry_track = None
        self.slot_manifest = None
        self.motive_handles = []
        self.aditional_instance_ops = []
        self._super_interaction = None
        self._run_interaction_element = None
        self._asm_states = {}
        self.locked_params = frozendict()
        if context is not None:
            self._priority = context.priority
            self._run_priority = context.run_priority if context.run_priority else context.priority
        else:
            self._priority = context.priority if context else interactions.priority.Priority.Low
            self._run_priority = context.priority
        self._active = False
        self._satisfied = not self.get_start_as_guaranteed()
        self._delay_behavior = None
        conditional_actions = self.get_conditional_actions()
        if conditional_actions:
            self._conditional_action_manager = interactions.utils.exit_condition_manager.ConditionalActionManager()
        else:
            self._conditional_action_manager = None
        self._performing = False
        self._start_time = None
        self._loaded_start_time = None
        if load_data is not None and load_data.start_time is not None:
            self._loaded_start_time = load_data.start_time
        self._finisher = InteractionFinisher(self)
        self.on_pipeline_change_callbacks = CallableList()
        self._must_run_instance = must_run
        self._outcome_result = None
        self.outcome_display_message = None
        self._posture_target_ref = None
        self._find_best_posture = find_best_posture
        self.reserved_funds = None
        self._interaction_event_update_alarm = None
        self._liabilities = OrderedDict()
        if liabilities is not None:
            for liability in liabilities:
                self.add_liability(*liability)
        self.route_fail_on_transition_fail = route_fail_on_transition_fail
        self._required_sims = None
        self._required_sims_threading = None
        self._on_cancelled_callbacks = CallableList()
        if depended_on_si is None and self.context.continuation_id:
            parent = self.sim.find_interaction_by_id(self.context.continuation_id)
            if parent is not None:
                depended_on_si = parent.depended_on_si
        if depended_on_si is not None:
            depended_on_si.attach_interaction(self)
        self.depended_on_si = depended_on_si
        self._progress_bar_commodity_callback = None
        self._progress_bar_displayed = False
        self.set_work_timestamp = set_work_timestamp

    def on_asm_state_changed(self, asm, state):
        if state == 'exit':
            state = 'entry'
        self._asm_states[asm] = state

    @property
    def aop(self):
        return self._aop

    @property
    def aop_id(self):
        return self.aop.aop_id

    @property
    def sim(self):
        return self.context.sim

    @property
    def source(self):
        return self.context.source

    @property
    def is_user_directed(self):
        return self.source == InteractionContext.SOURCE_PIE_MENU or self.source == InteractionContext.SOURCE_SCRIPT_WITH_USER_INTENT

    @property
    def is_autonomous(self):
        return self.source == InteractionContext.SOURCE_AUTONOMY

    @property
    def object_with_inventory(self):
        return self._kwargs.get('object_with_inventory')

    @classproperty
    def staging(cls):
        if cls.basic_content is not None:
            return cls.basic_content.staging
        return False

    @classproperty
    def one_shot(cls):
        basic_content = cls.basic_content
        if basic_content.staging:
            return False
        if basic_content is not None and basic_content.sleeping:
            return False
        return True

    @classproperty
    def is_basic_content_one_shot(cls):
        basic_content = cls.basic_content
        if basic_content is not None and (basic_content.staging or basic_content.sleeping):
            return False
        return True

    @property
    def consecutive_running_hours(self):
        if self._start_time is None:
            return 0
        hours = services.time_service().sim_now.absolute_hours() - self._start_time.absolute_hours()
        return hours

    @property
    def consecutive_running_time_span(self):
        if self._start_time is None:
            return TimeSpan.ZERO
        return services.time_service().sim_now - self._start_time

    @property
    def target(self):
        return self._target

    @property
    def user_facing_target(self):
        return self.target

    @property
    def category_tag(self):
        raise RuntimeError('[bhill] This function is believed to be dead code and is scheduled for pruning. If this exception has been raised, the code is not dead and this exception should be removed.')
        return self.get_category_tag()

    @classproperty
    def immediate(cls):
        return False

    @contextmanager
    def override_var_map(self, sim, var_map):
        original_target = self.target
        original_carry_track = self.carry_track
        original_slot_manifest = self.slot_manifest
        self._apply_vars(*self._get_vars_from_var_map(sim, var_map))
        yield None
        self._apply_vars(original_target, original_carry_track, original_slot_manifest)

    def apply_var_map(self, sim, var_map):
        self._apply_vars(*self._get_vars_from_var_map(sim, var_map))

    def _get_vars_from_var_map(self, sim, var_map):
        target = var_map.get(PostureSpecVariable.INTERACTION_TARGET)
        hand = var_map.get(PostureSpecVariable.HAND)
        if hand is None:
            carry_track = None
        else:
            carry_track = self.sim.posture_state.hand_to_track(hand)
        slot_manifest = var_map.get(PostureSpecVariable.SLOT)
        return (target, carry_track, slot_manifest)

    def _apply_vars(self, target, carry_track, slot_manifest):
        self.set_target(target)
        self.carry_track = carry_track
        self.slot_manifest = slot_manifest

    def set_target(self, target):
        if self.target is target:
            return
        if self.queued and self.target is not None:
            self.target.remove_interaction_reference(self)
            if self.sim.transition_controller is not None:
                self.sim.transition_controller.remove_relevant_object(self.target)
        if self.target_type & TargetType.ACTOR:
            if target is not self.sim and target is not None:
                logger.error('Interaction {} has target type ACTOR, but got an unexpected target {}', self, target)
            target = None
        elif not (target is self.sim and self.immediate):
            logger.error('Setting the target of an {} interaction to the running Sim. This can cause errors if the Sim is reset or deleted.', self)
        if self.queued and target is not None:
            target.add_interaction_reference(self)
        self._target = target
        self.refresh_constraints()

    @property
    def interaction_parameters(self):
        return self._kwargs

    @property
    def continuation_id(self):
        return self.context.continuation_id

    @property
    def visual_continuation_id(self):
        return self.context.continuation_id or self.context.visual_continuation_id

    def is_continuation_by_id(self, source_id):
        return source_id is not None and self.continuation_id == source_id

    def is_continuation_of(self, source):
        raise RuntimeError('[bhill] This function is believed to be dead code and is scheduled for pruning. If this exception has been raised, the code is not dead and this exception should be removed.')
        if source is None:
            return False
        return self.is_continuation_by_id(source.id)

    @property
    def group_id(self):
        return self.context.group_id or self.id

    def is_related_to(self, interaction):
        return self.group_id == interaction.group_id

    @classproperty
    def affordance(cls):
        return cls

    @property
    def super_affordance(self):
        return self._aop.super_affordance

    @property
    def si_state(self):
        if self.sim is not None:
            return self.sim.si_state

    @property
    def queue(self):
        if self.sim is not None:
            return self.sim.queue

    @property
    def visible_as_interaction(self):
        return self.visible

    @property
    def transition(self):
        pass

    @property
    def carry_target(self):
        return self.context.carry_target

    @property
    def create_target(self):
        pass

    @property
    def created_target(self):
        pass

    @property
    def disable_carry_interaction_mask(self):
        return False

    @flexmethod
    def get_icon_info(cls, inst, target=DEFAULT, context=DEFAULT):
        inst_or_cls = inst if inst is not None else cls
        resolver = inst_or_cls.get_resolver(target=target, context=context)
        icon_info = inst_or_cls._get_icon(resolver)
        if icon_info is not None:
            return icon_info
        target = inst.target if inst is not None else target
        if target is not DEFAULT and target is not None:
            return (target.icon, None)
        return (None, None)

    @classmethod
    def _get_icon(cls, interaction):
        (icon, icon_object) = cls._icon(interaction)
        if icon is not None:
            return (icon, None)
        if icon_object is not None:
            return (None, icon_object)

    @property
    def user_cancelable(self, **kwargs):
        if self.must_run:
            return False
        return self._cancelable_by_user != False

    @property
    def must_run(self):
        if self._must_run or self._must_run_instance:
            return True
        return False

    @property
    def super_interaction(self):
        return self._super_interaction

    @super_interaction.setter
    def super_interaction(self, si):
        if si is self._super_interaction:
            return
        if self._super_interaction is not None:
            self._super_interaction.detach_interaction(self)
        self._super_interaction = si
        if si is not None:
            si.attach_interaction(self)

    @property
    def queued(self):
        return self.pipeline_progress >= PipelineProgress.QUEUED

    @property
    def prepared(self):
        return self.pipeline_progress >= PipelineProgress.PREPARED

    @property
    def running(self):
        return self._run_interaction_element is not None and self._run_interaction_element._child_handle is not None

    @property
    def performing(self):
        return self._performing

    @property
    def active(self):
        return self._active

    def _set_pipeline_progress(self, value):
        self._pipeline_progress = value

    @property
    def pipeline_progress(self):
        return self._pipeline_progress

    @pipeline_progress.setter
    def pipeline_progress(self, value):
        if value is not self._pipeline_progress:
            self._set_pipeline_progress(value)
            self.on_pipeline_change_callbacks(self)

    @property
    def should_reset_based_on_pipeline_progress(self):
        return self._pipeline_progress >= PipelineProgress.PRE_TRANSITIONING

    def _set_satisfied(self, value):
        self._satisfied = value

    @property
    def satisfied(self):
        return self._satisfied

    @satisfied.setter
    def satisfied(self, value):
        self._set_satisfied(value)

    def get_animation_context_liability(self):
        animation_liability = self.get_liability(ANIMATION_CONTEXT_LIABILITY)
        if animation_liability is None:
            animation_context = animation.AnimationContext()
            animation_liability = AnimationContextLiability(animation_context)
            self.add_liability(ANIMATION_CONTEXT_LIABILITY, animation_liability)
        return animation_liability

    @property
    def animation_context(self):
        animation_liability = self.get_animation_context_liability()
        return animation_liability.animation_context

    @property
    def priority(self):
        return self._priority

    @property
    def run_priority(self):
        return self._run_priority

    @priority.setter
    def priority(self, value):
        if self._priority == value:
            return
        self._priority = value
        if self.queue is not None:
            self.queue.on_element_priority_changed(self)

    @classproperty
    def is_social(cls):
        return False

    @property
    def social_group(self):
        pass

    @property
    def liabilities(self):
        return reversed(tuple(self._liabilities.values()))

    @property
    def start_time(self):
        if self._loaded_start_time is not None:
            return self._loaded_start_time
        return self._start_time

    def disable_displace(self, other):
        return False

    def add_liability(self, key, liability):
        old_liability = self.get_liability(key)
        if old_liability is not None:
            liability = old_liability.merge(self, key, liability)
        liability.on_add(self)
        self._liabilities[key] = liability

    def remove_liability(self, key):
        liability = self.get_liability(key)
        if liability is not None:
            liability.release()
            del self._liabilities[key]

    def get_liability(self, key):
        if key in self._liabilities:
            return self._liabilities[key]

    def _acquire_liabilities(self):
        if self.context.continuation_id:
            parent = self.sim.find_interaction_by_id(self.context.continuation_id)
            if parent is None:
                return
            if self.is_super != parent.is_super:
                return
            parent.release_liabilities(continuation=self)

    def release_liabilities(self, continuation=None, liabilities_to_release=()):
        exception = None
        for (key, liability) in list(self._liabilities.items()):
            while not liabilities_to_release or key in liabilities_to_release:
                if continuation is not None and liability.should_transfer and (key != ANIMATION_CONTEXT_LIABILITY or not continuation.ignore_animation_context_liability):
                    liability.transfer(continuation)
                    continuation.add_liability(key, liability)
                    del self._liabilities[key]
                elif continuation is None:
                    try:
                        liability.release()
                        del self._liabilities[key]
                    except BaseException as ex:
                        logger.exception('Liability {} threw exception {}', liability, ex)
                        while exception is None:
                            exception = ex
        if exception is not None:
            raise exception

    @classproperty
    def can_holster_incompatible_carries(cls):
        return True

    @classproperty
    def allow_holstering_of_owned_carries(cls):
        return False

    @property
    def combined_posture_preferences(self):
        return self.posture_preferences

    @property
    def combined_posture_target_preference(self):
        return self.posture_target_preferences

    def should_find_best_posture(self):
        if self._find_best_posture is not DEFAULT:
            return self._find_best_posture
        return self.combined_posture_preferences.find_best_posture

    @flexmethod
    def get_constraint_resolver(cls, inst, posture_state, *args, participant_type=ParticipantType.Actor, force_actor=None, **kwargs):
        if inst is not None and posture_state is not None:
            posture_sim = posture_state.sim
            participant_sims = inst.get_participants(participant_type)
        inst_or_cls = inst if inst is not None else cls

        def resolver(constraint_participant, default=None):
            result = default
            if constraint_participant == AnimationParticipant.ACTOR:
                if force_actor is not None:
                    result = force_actor
                else:
                    result = inst_or_cls.get_participant(participant_type, *args, **kwargs)
            elif constraint_participant == AnimationParticipant.TARGET or constraint_participant == PostureSpecVariable.INTERACTION_TARGET:
                result = inst_or_cls.get_participant(ParticipantType.Object, *args, **kwargs)
            elif constraint_participant == AnimationParticipant.CARRY_TARGET or constraint_participant == PostureSpecVariable.CARRY_TARGET:
                result = inst_or_cls.get_participant(ParticipantType.CarriedObject, *args, **kwargs)
            elif constraint_participant == AnimationParticipant.CREATE_TARGET:
                if inst is not None:
                    result = inst.create_target
            elif constraint_participant == AnimationParticipant.CONTAINER or constraint_participant == PostureSpecVariable.CONTAINER_TARGET:
                if posture_state is not None:
                    result = posture_state.body.target
                else:
                    result = PostureSpecVariable.CONTAINER_TARGET
            elif constraint_participant in (AnimationParticipant.SURFACE, PostureSpecVariable.SURFACE_TARGET):
                if posture_state is not None:
                    result = posture_state.surface_target
                    if result is None:
                        result = MATCH_NONE
                        if constraint_participant == AnimationParticipant.SURFACE and default == AnimationParticipant.SURFACE:
                            result = PostureSpecVariable.SURFACE_TARGET
                elif constraint_participant == AnimationParticipant.SURFACE and default == AnimationParticipant.SURFACE:
                    result = PostureSpecVariable.SURFACE_TARGET
            return result

        return resolver

    @flexmethod
    def apply_posture_state_and_interaction_to_constraint(cls, inst, posture_state, constraint, *args, participant_type=ParticipantType.Actor, sim=DEFAULT, allow_holster=DEFAULT, invalid_expected=False, **kwargs):
        inst_or_cls = inst if inst is not None else cls
        sim = sim if sim is not DEFAULT else posture_state.sim
        if posture_state is not None:
            body_target = posture_state.body_target
            if body_target is not None and body_target.is_part:
                if not body_target.supports_posture_spec(posture_state.get_posture_spec({}), inst_or_cls):
                    return NOWHERE
        allow_holster = inst_or_cls.can_holster_incompatible_carries if allow_holster is DEFAULT else allow_holster
        if allow_holster:
            constraint = constraint.get_holster_version()
        constraint_resolver = inst_or_cls.get_constraint_resolver(posture_state, participant_type=participant_type, sim=sim, *args, **kwargs)
        result = constraint.apply_posture_state(posture_state, constraint_resolver, invalid_expected=invalid_expected)
        return result

    def log_participants_to_gsi(self):
        if gsi_handlers.interaction_archive_handlers.is_archive_enabled(self):
            for participant in self.get_participants(ParticipantType.All):
                ptype = self.get_participant_type(participant)
                gsi_handlers.interaction_archive_handlers.add_participant(self, ptype, participant)

    def get_asm(self, asm_key, actor_name, target_name, carry_target_name, setup_asm_override=DEFAULT, animation_context=DEFAULT, posture=None, cache_key=DEFAULT, use_cache=True, posture_manifest_overrides=None, **kwargs):
        if posture is None:
            posture = self.sim.posture
        if setup_asm_override is DEFAULT:
            setup_asm_override = lambda asm: self.setup_asm_default(asm, actor_name, target_name, carry_target_name, posture=posture, **kwargs)
        if animation_context is DEFAULT:
            animation_context = self.animation_context
        if cache_key is DEFAULT:
            cache_key = self.continuation_id or self.id
        animation_liability = self.get_animation_context_liability()
        cached_keys = animation_liability.cached_asm_keys[posture]
        cached_keys.add(cache_key)
        asm = posture.get_asm(animation_context, asm_key, setup_asm_override, use_cache=use_cache, cache_key=cache_key, interaction=self, posture_manifest_overrides=posture_manifest_overrides)
        if asm is None:
            return
        current_state = self._asm_states.get(asm)
        if current_state is not None:
            asm.set_current_state(current_state)
        return asm

    def setup_asm_default(self, asm, actor_name, target_name, carry_target_name, posture=None, create_target_name=None):
        if posture is None:
            posture = self.sim.posture
        carry_track = self.carry_track if self.carry_track is not None else DEFAULT
        if not posture.setup_asm_interaction(asm, self.sim, self.target, actor_name, target_name, carry_target=self.carry_target, carry_target_name=carry_target_name, create_target_name=create_target_name, carry_track=carry_track):
            return False
        self.super_interaction.set_stat_asm_parameter(asm, actor_name, self.sim)
        self.sim.set_mood_asm_parameter(asm, actor_name)
        self.sim.set_trait_asm_parameters(asm, actor_name)
        if target_name is not None and self.target is not None and self.target.is_sim:
            self.target.set_mood_asm_parameter(asm, target_name)
            self.target.set_trait_asm_parameters(asm, target_name)
        if create_target_name is not None and asm.get_actor_definition(create_target_name) is not None and self.created_target is not None:
            if not asm.add_potentially_virtual_actor(actor_name, self.sim, create_target_name, self.created_target, target_participant=AnimationParticipant.CREATE_TARGET):
                return False
            carry.set_carry_track_param_if_needed(asm, self.sim, create_target_name, self.created_target, carry_track)
        if self.locked_params:
            virtual_actor_map = {target_name: self.target} if target_name is not None else None
            asm.update_locked_params(self.locked_params, virtual_actor_map)
        return True

    def with_listeners(self, sims, sequence):
        listeners = WeakSet(sims)

        def event_handler_reactionlet(event_data):
            asm_name_default = event_data.event_data['reaction_name']
            public_state_name = event_data.event_data['public_state']
            self._trigger_reactionlets(listeners, asm_name_default, public_state_name)

        sequence = with_event_handlers(self.animation_context, event_handler_reactionlet, animation.ClipEventType.Reaction, sequence=sequence, tag='reactionlets')
        for listener in sims:
            sequence = with_sim_focus(self.sim, listener, self.sim, SimFocus.LAYER_INTERACTION, sequence, score=0.999)
        return sequence

    def _trigger_reactionlets(self, listeners, asm_name_default, public_state_name):
        if self.super_interaction is None:
            return
        for listener in listeners:

            def setup_asm_listener(asm):
                return listener.posture.setup_asm_interaction(asm, listener, None, 'x', None)

            reactionlet = self.outcome.get_reactionlet(self, setup_asm_override=setup_asm_listener, sim=listener)
            if reactionlet is not None:
                asm = reactionlet.get_asm()
                arb = animation.arb.Arb()
                reactionlet.append_to_arb(asm, arb)
                arb_element = ArbElement(arb)
                arb_element.distribute()
            else:
                asm = listener.posture.get_asm(self.animation_context, asm_name_default, setup_asm_listener, interaction=self, use_cache=False)
                while asm is not None:
                    reaction_arb = animation.arb.Arb()
                    if public_state_name is None:
                        asm.request('exit', reaction_arb)
                    else:
                        asm.request(public_state_name, reaction_arb)
                    arb_element = ArbElement(reaction_arb)
                    arb_element.distribute()

    def refresh_constraints(self):
        self._constraint_cache.clear()
        self._constraint_cache_final.clear()

    def apply_posture_state(self, posture_state, participant_type=ParticipantType.Actor, sim=DEFAULT):
        if posture_state in self._constraint_cache_final:
            return
        intersection = self.constraint_intersection(sim=sim, participant_type=participant_type, posture_state=posture_state, force_concrete=True)
        if posture_state is not None:
            posture_state.add_constraint(self, intersection)

    def _setup_gen(self, timeline):
        if self.super_interaction is None:
            return False
        if not self.super_interaction.can_run_subinteraction(self):
            return False
        yield self.si_state.process_gen(timeline)
        self._active = True
        return True

    def setup_gen(self, timeline):
        interaction_parameters = {}
        interaction_parameters['interaction_starting'] = True
        test_result = self.test(skip_safe_tests=self.skip_test_on_execute(), **interaction_parameters)
        if not test_result:
            return (test_result.result, test_result.reason)
        result = yield self._setup_gen(timeline)
        return (result, None)

    @property
    def should_rally(self):
        return False

    def maybe_bring_group_along(self, **kwargs):
        pass

    def pre_process_interaction(self):
        pass

    def post_process_interaction(self):
        pass

    def _validate_posture_state(self):
        return True

    def perform_gen(self, timeline):
        constraint = self.constraint_intersection()
        constraint.apply_posture_state(self.sim.posture_state, self.get_constraint_resolver(self.sim.posture_state))
        (single_point, _) = constraint.single_point()
        if single_point is None:
            self.remove_liability(STAND_SLOT_LIABILITY)
        if self.disable_transitions or self.constraint_intersection().tentative:
            raise AssertionError("Interaction's constraints are still tentative in perform(): {}.".format(self))
        (result, reason) = yield self.setup_gen(timeline)
        if not result:
            self.cancel(FinishingType.FAILED_TESTS, cancel_reason_msg='Interaction failed setup on perform. {}'.format(result))
            return (result, reason)
        if self.is_finishing or not self._active:
            return (False, 'is_finishing or not active')
        if self._run_priority is not None:
            self._priority = self._run_priority
        completed = True
        consumed_exc = None
        try:
            self._performing = True
            self._start_time = services.time_service().sim_now
            if not self._pre_perform():
                return (False, 'pre_perform failed')
            self._trigger_interaction_start_event()
            for liability in self._liabilities.values():
                liability.on_run()
            completed = False
            yield self._do_perform_trigger_gen(timeline)
            completed = True
            if self.provided_posture_type is None:
                for required_sim in self.required_sims():
                    required_sim.last_affordance = self.affordance
            self._post_perform()
        except Exception as exc:
            for posture in self.sim.posture_state.aspects:
                while posture.source_interaction is self:
                    raise
            logger.exception('Exception while running interaction {0}', self)
            consumed_exc = exc
        finally:
            if not completed:
                with consume_exceptions('Interactions', 'Exception thrown while tearing down an interaction:'):
                    self.detach_conditional_actions()
                    self.kill()
            self._delay_behavior = None
            self._performing = False
            if not self.is_super:
                self.remove_liability(AUTONOMY_MODIFIER_LIABILITY)
        return (True, None)

    def _pre_perform(self):
        if self.basic_content is not None and self.basic_content.sleeping:
            self._delay_behavior = element_utils.soft_sleep_forever()
        return True

    def _stop_delay_behavior(self):
        if self._delay_behavior is not None:
            self._delay_behavior.trigger_soft_stop()
            self._delay_behavior = None

    def _conditional_action_satisfied_callback(self, condition_group):
        conditional_action = condition_group.conditional_action
        action = conditional_action.interaction_action
        if action == ConditionalInteractionAction.GO_INERTIAL:
            self.satisfied = True
            self._stop_delay_behavior()
        elif action == ConditionalInteractionAction.EXIT_NATURALLY:
            if not self.is_finishing:
                self._finisher.on_pending_finishing_move(FinishingType.NATURAL)
            self.satisfied = True
            if self.staging:
                self.cancel(FinishingType.NATURAL, cancel_reason_msg='Conditional Action: Exit Naturally')
            self._stop_delay_behavior()
        elif action == ConditionalInteractionAction.EXIT_CANCEL:
            self.cancel(FinishingType.CONDITIONAL_EXIT, cancel_reason_msg='Conditional Action: Exit Cancel')
            self._stop_delay_behavior()
        elif action == ConditionalInteractionAction.LOWER_PRIORITY:
            self.priority = interactions.priority.Priority.Low
        if gsi_handlers.interaction_archive_handlers.is_archive_enabled(self):
            gsi_handlers.interaction_archive_handlers.add_exit_reason(self, action, condition_group)
        loot_actions = conditional_action.loot_actions
        if loot_actions:
            resolver = self.get_resolver()
            for actions in loot_actions:
                actions.apply_to_resolver(resolver)

    def refresh_conditional_actions(self):
        if self._conditional_action_manager:
            self.detach_conditional_actions()
            self.attach_conditional_actions()

    def attach_conditional_actions(self):
        if self.staging:
            self._satisfied = not self.get_start_as_guaranteed()
        conditional_actions = self.get_conditional_actions()
        if conditional_actions:
            self._conditional_action_manager.attach_conditions(self, conditional_actions, self._conditional_action_satisfied_callback, interaction=self)

    def detach_conditional_actions(self):
        if self._conditional_action_manager is not None:
            self._conditional_action_manager.detach_conditions(self, exiting=True)

    def _run_gen(self, timeline):
        result = yield self._do_perform_gen(timeline)
        return result

    def _do_perform_trigger_gen(self, timeline):
        result = yield self._do_perform_gen(timeline)
        return result

    def _get_behavior(self):
        self._run_interaction_element = self.build_basic_elements(sequence=self._run_interaction_gen)
        return self._run_interaction_element

    def _do_perform_gen(self, timeline):
        interaction_element = self._get_behavior()
        result = yield element_utils.run_child(timeline, interaction_element)
        return result

    def build_basic_content(self, sequence=(), **kwargs):
        if self.basic_content is not None:
            sequence = self.basic_content(self, sequence=sequence, **kwargs)
        if self.target is not None:
            target_basic_content = self.target.get_affordance_basic_content(self)
            if target_basic_content is not None:
                sequence = target_basic_content(self, sequence=sequence, **kwargs)
        return sequence

    def _build_outcome_sequence(self):
        sequence = self.outcome.build_elements(self)
        if self.target is not None:
            target_outcome = self.target.get_affordance_outcome(self)
            if target_outcome is not None:
                sequence = (sequence, target_outcome.build_elements(self))
        return sequence

    def build_outcome(self):
        return self._build_outcome_sequence()

    def build_basic_extras(self, sequence=()):
        for factory in reversed(self.basic_extras):
            sequence = factory(self, sequence=sequence)
        if self.target is not None:
            target_basic_extras = self.target.get_affordance_basic_extras(self)
            for factory in reversed(target_basic_extras):
                sequence = factory(self, sequence=sequence)
        if self.confirmation_dialog is not None:
            sequence = (self.confirmation_dialog(self.sim, self.get_resolver()), sequence)
        return sequence

    def get_item_cost_content(self):
        if self.item_cost.ingredients:
            return self.item_cost.consume_interaction_cost(self)

    def _outcome_xevt_callback(self, event_data):
        success = self.outcome_result == OutcomeResult.SUCCESS
        self.sim.ui_manager.set_interaction_outcome(success, self.outcome_display_message)

    def _decay_topics(self, e):
        if self.sim is not None:
            self.sim.decay_topics()

    def get_keys_to_process_events(self):
        custom_keys = set(self.get_category_tags())
        custom_keys.add(self.affordance.get_interaction_type())
        return custom_keys

    def _trigger_interaction_complete_test_event(self):
        custom_keys = self.get_keys_to_process_events()
        for participant in self.get_participants(ParticipantType.AllSims):
            while participant is not None:
                services.get_event_manager().process_event(test_events.TestEvent.InteractionComplete, sim_info=participant.sim_info, interaction=self, custom_keys=custom_keys)
        self.remove_event_auto_update()

    def _trigger_interaction_exited_pipeline_test_event(self):
        custom_keys = self.get_keys_to_process_events()
        actor = self.sim
        if actor is not None:
            services.get_event_manager().process_event(test_events.TestEvent.InteractionExitedPipeline, sim_info=actor.sim_info, interaction=self, custom_keys=custom_keys)

    def _build_pre_elements(self):
        pass

    def build_basic_elements(self, sequence=(), **kwargs):
        sequence = (lambda _: self.send_current_progress(), sequence)
        sequence = self.build_basic_content(sequence=sequence, **kwargs)
        if not self.is_basic_content_one_shot:
            sequence = build_critical_section_with_finally(lambda _: self.attach_conditional_actions(), sequence, lambda _: self.detach_conditional_actions())
        listeners = list(self.get_participants(ParticipantType.Listeners, listener_filtering_enabled=True))
        sequence = self.with_listeners(listeners, sequence)
        sequence = build_critical_section(self.get_item_cost_content(), sequence, self._decay_topics, self.build_outcome())
        sequence = self.build_basic_extras(sequence=sequence)
        if not self.immediate and not self.disable_transitions:
            create_target_track = self.carry_track if self.create_target is not None else None
            sequence = carry.interact_with_carried_object(self.sim, self.carry_target or self.target, interaction=self, create_target_track=create_target_track, sequence=sequence)
            sequence = carry.holster_carried_object(self.sim, self, self.should_unholster_carried_object, sequence=sequence)
        if self.basic_focus is not None and self.provided_posture_type is None:
            if self.basic_focus is False:
                sequence = sim_focus.without_sim_focus(self.sim, self.sim, sequence)
            else:
                sequence = self.basic_focus(self, sequence=sequence)
        if self.autonomy_preference is not None:
            should_set = self.autonomy_preference.preference.should_set
            if should_set and self.is_user_directed or should_set.autonomous:

                def set_preference(_):
                    self.sim.set_autonomy_preference(self.autonomy_preference.preference, self.target)
                    return True

                sequence = (set_preference, sequence)
        if self.target is not None and (self._provided_posture_type is None and isinstance(self.target, objects.game_object.GameObject)) and self.target.autonomy_modifiers:
            self.add_liability(AUTONOMY_MODIFIER_LIABILITY, AutonomyModifierLiability(self))
        for participant in self.get_participants(ParticipantType.All):
            sequence = participant.add_modifiers_for_interaction(self, sequence=sequence)
        if not (self.basic_reserve_object is not None and self.get_liability(RESERVATION_LIABILITY)):
            reserver = self.basic_reserve_object(self.sim, self, interaction=self)
            sequence = reserver.do_reserve(sequence=sequence)
        if not self.immediate:
            sequence = build_critical_section(sequence, flush_all_animations)
        animation_liability = self.get_animation_context_liability()
        sequence = build_critical_section_with_finally(lambda _: animation_liability.setup_props(self), sequence, lambda _: animation_liability.unregister_handles(self))

        def sync_element(_):
            try:
                if self.sim is None or self.immediate:
                    return
                noop = distributor.ops.SetLocation(self.sim.location)
                added_additional_channel = False
                for additional_sim in self.required_sims():
                    if additional_sim is self.sim:
                        pass
                    added_additional_channel = True
                    noop.add_additional_channel(additional_sim.manager.id, additional_sim.id)
                while added_additional_channel:
                    distributor.ops.record(self.sim, noop)
            except Exception:
                logger.exception('Exception when trying to create the Sync Element at the end of {}', self, owner='maxr')

        return build_element((self._build_pre_elements(), sequence, sync_element))

    def _run_interaction_gen(self, timeline):
        if self._delay_behavior:
            result = yield element_utils.run_child(timeline, self._delay_behavior)
            return result
        return True

    def push_tunable_continuation(self, tunable_continuation, multi_push=True, insert_strategy=QueueInsertStrategy.NEXT, actor=DEFAULT, affordance_override=None, **kwargs):
        num_pushed = collections.defaultdict(int)
        num_required = collections.defaultdict(int)
        continuations = tunable_continuation
        if multi_push and insert_strategy == QueueInsertStrategy.NEXT:
            continuations = reversed(tunable_continuation)
        for continuation in continuations:
            if actor is DEFAULT:
                local_actors = self.get_participants(continuation.actor)
            else:
                local_actors = (actor,)
            for local_actor in local_actors:
                if isinstance(local_actor, sims.sim_info.SimInfo):
                    pass
                if multi_push:
                    num_required[local_actor.id] += 1
                else:
                    num_required[local_actor.id] = 1
                    if num_pushed[local_actor.id] > 0:
                        pass
                group_id = self.super_interaction.group_id if self.super_interaction is not None else None
                if local_actor is self.sim:
                    if self.immediate:
                        context = self.context.clone_from_immediate_context(self, insert_strategy=insert_strategy)
                    else:
                        context = self.context.clone_for_continuation(self, insert_strategy=insert_strategy)
                else:
                    context = self.context.clone_for_sim(local_actor, group_id=group_id)
                if continuation.carry_target is not None:
                    context.carry_target = self.get_participant(continuation.carry_target)
                if continuation.target != ParticipantType.Invalid:
                    targets = self.get_participants(continuation.target)
                    target = next(iter(targets), None)
                else:
                    target = None
                if target is not None:
                    if target.is_sim:
                        if isinstance(target, sims.sim_info.SimInfo):
                            target = target.get_sim_instance()
                            if target.is_part:
                                target = target.part_owner
                    elif target.is_part:
                        target = target.part_owner
                affordance = continuation.affordance if affordance_override is None else affordance_override
                kwargs_copy = kwargs.copy()
                join_target_ref = self.interaction_parameters.get('join_target_ref')
                if join_target_ref is not None:
                    kwargs_copy['join_target_ref'] = join_target_ref
                if 'picked_item_ids' not in kwargs_copy:
                    picked_items = self.get_participants(ParticipantType.PickedItemId)
                    if picked_items:
                        kwargs_copy['picked_item_ids'] = picked_items
                if 'picked_zone_ids' not in kwargs_copy:
                    picked_zones = self.get_participants(ParticipantType.PickedZoneId)
                    if picked_zones:
                        kwargs_copy['picked_zone_ids'] = picked_zones
                if affordance.is_super:
                    result = local_actor.push_super_affordance(affordance, target, context, picked_object=self.target, **kwargs_copy)
                else:
                    if continuation.si_affordance_override is not None:
                        super_affordance = continuation.si_affordance_override
                        super_interaction = None
                        push_super_on_prepare = True
                    else:
                        super_affordance = self.super_affordance
                        super_interaction = self.super_interaction
                        push_super_on_prepare = False
                    aop = interactions.aop.AffordanceObjectPair(affordance, target, super_affordance, super_interaction, picked_object=self.target, push_super_on_prepare=push_super_on_prepare, **kwargs_copy)
                    result = aop.test_and_execute(context)
                while result:
                    num_pushed[local_actor.id] += 1
        return num_pushed == num_required

    def _post_perform(self):
        if not self.is_finishing:
            self._finisher.on_finishing_move(FinishingType.NATURAL)
        self._active = False

    def required_sims(self, *args, for_threading=False, **kwargs):
        cached_required_sims = self._required_sims if not for_threading else self._required_sims_threading
        if cached_required_sims is not None:
            return cached_required_sims
        return self._get_required_sims(for_threading=for_threading, *args, **kwargs)

    def has_sim_in_required_sim_cache(self, sim_in_question):
        if self._required_sims is None:
            return False
        return sim_in_question in self._required_sims

    def required_resources(self):
        return set()

    def is_required_sims_locked(self):
        return isinstance(self._required_sims, frozenset)

    def refresh_and_lock_required_sims(self):
        self._required_sims = frozenset(self._get_required_sims())
        self._required_sims_threading = frozenset(self._get_required_sims(for_threading=True))

    def remove_required_sim(self, sim):
        if self._required_sims is None:
            logger.error('Trying to remove a Sim {} even though we have not yet reserved a list of required Sims.', sim)
            return
        if sim in self._required_sims:
            sim.queue.transition_controller = None

    def unlock_required_sims(self):
        self._required_sims = None

    def _get_required_sims(self, *args, **kwargs):
        return {self.sim}

    def notify_queue_head(self):
        pass

    def on_incompatible_in_queue(self):
        if self.context.cancel_if_incompatible_in_queue:
            self.cancel(FinishingType.INTERACTION_INCOMPATIBILITY, 'Canceled because cancel_if_incompatible_in_queue == True')

    def _trigger_interaction_start_event(self):
        if self.sim is not None:
            services.get_event_manager().process_event(test_events.TestEvent.InteractionStart, sim_info=self.sim.sim_info, interaction=self, custom_keys=self.get_keys_to_process_events())
            self.register_event_auto_update()

    def register_event_auto_update(self):
        if self._interaction_event_update_alarm is not None:
            self.remove_event_auto_update()
        self._interaction_event_update_alarm = alarms.add_alarm(self, create_time_span(minutes=15), lambda _, sim_info=self.sim.sim_info, interaction=self, custom_keys=self.get_keys_to_process_events(): services.get_event_manager().process_event(test_events.TestEvent.InteractionUpdate, sim_info=sim_info, interaction=interaction, custom_keys=custom_keys), True)

    def remove_event_auto_update(self):
        if self._interaction_event_update_alarm is not None:
            alarms.cancel_alarm(self._interaction_event_update_alarm)
            self._interaction_event_update_alarm = None

    def _interrupt_active_work(self, kill=False, finishing_type=None):
        element = self._run_interaction_element
        if element is not None:
            if kill:
                element.trigger_hard_stop()
            else:
                element.trigger_soft_stop()
        return True

    def invalidate(self):
        if self.pipeline_progress == PipelineProgress.NONE:
            if self.transition is not None:
                self.transition.shutdown()
            self._finisher.on_finishing_move(FinishingType.KILLED)
            self.release_liabilities()

    def kill(self):
        if self.has_been_killed:
            return False
        self._finisher.on_finishing_move(FinishingType.KILLED)
        self._interrupt_active_work(kill=True, finishing_type=FinishingType.KILLED)
        self._active = False
        if self.queue is not None:
            self.queue.on_interaction_canceled(self)
        return True

    def cancel(self, finishing_type, cancel_reason_msg, ignore_must_run=False, **kwargs):
        if self.is_finishing or self.must_run and not ignore_must_run:
            return False
        self._finisher.on_finishing_move(finishing_type)
        self._interrupt_active_work(finishing_type=finishing_type)
        self._active = False
        if self.queue is not None:
            self.queue.on_interaction_canceled(self)
        self._on_cancelled_callbacks(self)
        self._on_cancelled_callbacks.clear()
        return True

    def displace(self, displaced_by, **kwargs):
        return self.cancel(FinishingType.DISPLACED, **kwargs)

    def on_reset(self):
        if self._finisher.has_been_reset:
            return
        self._finisher.on_finishing_move(FinishingType.RESET)
        self._active = False
        for liability in list(self.liabilities):
            liability.on_reset()
        self._liabilities.clear()
        self.remove_event_auto_update()

    def cancel_user(self, cancel_reason_msg):
        if not self._cancelable_by_user:
            return False
        if self._cancelable_by_user == True or not self.prepared:
            return self.cancel(FinishingType.USER_CANCEL, cancel_reason_msg=cancel_reason_msg)

        def on_cancel_dialog_response(dialog):
            if dialog.accepted:
                return self.cancel(FinishingType.USER_CANCEL, cancel_reason_msg=cancel_reason_msg)
            self.sim.ui_manager.refresh_ui_data()
            return False

        dialog = self._cancelable_by_user(self.sim, self.get_resolver())
        dialog.show_dialog(on_response=on_cancel_dialog_response)
        return True

    def should_visualize_interaction_for_sim(self, participant_type):
        return participant_type == ParticipantType.Actor

    @classproperty
    def has_visible_content_sets(cls):
        return False

    def get_interaction_queue_visual_type(self):
        if self.visual_type_override is not None:
            return (InteractionQueueVisualType.get_interaction_visual_type(self.visual_type_override), self.visual_type_override_data)
        if not self.is_super:
            return (Sims_pb2.Interaction.MIXER, self.visual_type_override_data)
        if self.has_visible_content_sets:
            return (Sims_pb2.Interaction.PARENT, self.visual_type_override_data)
        sim_posture = self.sim.posture
        if sim_posture.source_interaction is self:
            return (Sims_pb2.Interaction.POSTURE, self.visual_type_override_data)
        return (Sims_pb2.Interaction.SIMPLE, self.visual_type_override_data)

    def on_added_to_queue(self, interaction_id_to_insert_after=None, notify_client=True):
        self.pipeline_progress = PipelineProgress.QUEUED
        self._entered_pipeline()
        self.sim.ui_manager.add_queued_interaction(self, interaction_id_to_insert_after=interaction_id_to_insert_after, notify_client=notify_client)
        if self.should_visualize_interaction_for_sim(ParticipantType.TargetSim):
            target_sim = self.get_participant(ParticipantType.TargetSim)
            if target_sim is not None and target_sim is not self.sim:
                target_sim.ui_manager.add_queued_interaction(self, notify_client=notify_client)
        for liability in self.basic_liabilities:
            liability = liability(self)
            self.add_liability(liability.LIABILITY_TOKEN, liability)

    def on_removed_from_queue(self):
        if self.pipeline_progress < PipelineProgress.RUNNING or not self.is_super and self.pipeline_progress < PipelineProgress.EXITED:
            self.sim.ui_manager.remove_queued_interaction(self)
            if self.should_visualize_interaction_for_sim(ParticipantType.TargetSim):
                target_sim = self.get_participant(ParticipantType.TargetSim)
                if target_sim is not None and target_sim is not self.sim:
                    target_sim.ui_manager.remove_queued_interaction(self)
            if not self.is_finishing:
                self.cancel(FinishingType.INTERACTION_QUEUE, 'Being removed from queue without successfully running.', ignore_must_run=True, immediate=True)
            self._exited_pipeline()

    def _entered_pipeline(self):
        self._acquire_liabilities()
        if self.target is not None:
            self.target.add_interaction_reference(self)

    def _exited_pipeline(self):
        if not self.is_finishing:
            logger.callstack('Exiting pipeline without having canceled an interaction: {}', self, level=sims4.log.LEVEL_WARN, owner='bhill')
            self.cancel(FinishingType.UNKNOWN, 'Exiting pipeline without canceling.', ignore_must_run=True, immediate=True)
        if self.target is not None:
            self.target.remove_interaction_reference(self)
        if gsi_handlers.interaction_archive_handlers.is_archive_enabled(self):
            gsi_handlers.interaction_archive_handlers.archive_interaction(self.sim, self, 'Complete')
        if self.pipeline_progress >= PipelineProgress.EXITED:
            logger.callstack('_exited_pipeline called twice on {}', self, level=sims4.log.LEVEL_ERROR)
            return
        completed = self.pipeline_progress >= PipelineProgress.RUNNING
        self.pipeline_progress = PipelineProgress.EXITED
        if self.is_super:
            animation_liability = self.get_animation_context_liability()
            for (posture, key_list) in animation_liability.cached_asm_keys.items():
                for key in key_list:
                    posture.remove_from_cache(key)
            animation_liability.cached_asm_keys.clear()
        self.release_liabilities()
        for asm in self._asm_states:
            while self.on_asm_state_changed in asm.on_state_changed_events:
                asm.on_state_changed_events.remove(self.on_asm_state_changed)
        if completed:
            self._trigger_interaction_complete_test_event()
        self._target = None
        if self.sim is not None:
            self.sim.skip_autonomy(self, False)
        self._trigger_interaction_exited_pipeline_test_event()

    def _do(self, *args):
        raise RuntimeError('Calling _do on interaction is not supported')

    def disallows_full_autonomy(self, disable_full_autonomy=DEFAULT):
        return False

    def _update_autonomy_timer(self, force_user_directed=False):
        self.sim.skip_autonomy(self, False)
        if force_user_directed or self.is_user_directed:
            self.sim.set_last_user_directed_action_time()
            if self.is_social and self.target is not None and self.target.is_sim:
                self.target.set_last_user_directed_action_time()
        elif self.source == InteractionContext.SOURCE_AUTONOMY:
            self.sim.set_last_autonomous_action_time()

    def register_on_finishing_callback(self, callback):
        self._finisher.register_callback(callback)

    def unregister_on_finishing_callback(self, callback):
        self._finisher.unregister_callback(callback)

    @property
    def allow_outcomes(self):
        if not self.is_super:
            return True
        if self.immediate:
            return True
        if self.is_basic_content_one_shot:
            return True
        if self.is_finishing or self._finisher.has_pending_natural_finisher:
            return True
        if self.is_finishing_naturally:
            return True
        return False

    @property
    def is_finishing(self):
        return self._finisher.is_finishing

    @property
    def user_canceled(self):
        return self._finisher.has_been_user_canceled

    @property
    def is_finishing_naturally(self):
        return self._finisher.is_finishing_naturally

    @property
    def transition_failed(self):
        return self._finisher.transition_failed

    @property
    def will_exit(self):
        return self.is_finishing

    @property
    def was_initially_displaced(self):
        return self._finisher.was_initially_displaced

    @property
    def uncanceled(self):
        if not self._finisher.is_finishing:
            return True
        if self._finisher.is_finishing_naturally:
            return True
        return False

    @property
    def has_active_cancel_replacement(self):
        return self.sim.queue.cancel_aop_exists_for_si(self)

    @property
    def is_cancel_aop(self):
        return self.context.is_cancel_aop

    @property
    def has_been_killed(self):
        return self._finisher.has_been_killed

    @property
    def has_been_canceled(self):
        return self._finisher.has_been_canceled

    @property
    def has_been_user_canceled(self):
        return self._finisher.has_been_user_canceled

    @property
    def has_been_reset(self):
        return self._finisher.has_been_reset

    def finisher_repr(self):
        return self._finisher.__repr__()

    @property
    def outcome_result(self):
        return self._outcome_result

    @outcome_result.setter
    def outcome_result(self, outcome_result):
        self._outcome_result = outcome_result

    def is_equivalent(self, interaction, target=DEFAULT):
        if target is DEFAULT:
            target = interaction.target
        return self.get_interaction_type() is interaction.get_interaction_type() and self.target is target

    def merge(self, other):
        if self.context.priority < other.context.priority:
            self.context.priority = interactions.priority.Priority(other.context.priority)
            self.context.source = other.context.source
        self.refresh_conditional_actions()

    def should_unholster_carried_object(self, obj):
        if obj.carryable_component.unholster_on_long_route_only:
            return obj is self.target or obj is self.carry_target
        return not self.is_super

    def get_uncarriable_objects_gen(self, posture_state=DEFAULT, allow_holster=DEFAULT, use_holster_compatibility=False):
        carry_target = self.carry_target or self.super_interaction.carry_target
        interaction_target = self.target
        for sim in self.required_sims():
            participant_type = self.get_participant_type(sim)
            if participant_type is None:
                pass
            for (_, carry_posture, carry_object) in carry.get_carried_objects_gen(sim):
                while carry_object is not carry_target and carry_object is not interaction_target:
                    while True:
                        for owning_interaction in carry_posture.owning_interactions:
                            while not owning_interaction.allow_holstering_of_owned_carries:
                                allow_holster = False
                                break
            current_interaction_constraint = self.constraint_intersection(sim=sim, participant_type=participant_type, posture_state=posture_state, allow_holster=allow_holster)
            forced_tentative_interaction_constraint = None if posture_state is not None else current_interaction_constraint
            for (_, carry_posture, carry_object) in carry.get_carried_objects_gen(sim):
                while carry_object is not carry_target and carry_object is not interaction_target:
                    while True:
                        for owning_interaction in list(carry_posture.owning_interactions):
                            if not (use_holster_compatibility and carry_object.carryable_component.holster_compatibility(self.super_affordance)):
                                yield (owning_interaction, carry_posture)
                            if not (self.is_super and interactions.si_state.SIState.test_non_constraint_compatibility(self, owning_interaction)):
                                yield (owning_interaction, carry_posture)
                            if owning_interaction.running:
                                other_constraint = owning_interaction.constraint_intersection(posture_state=posture_state)
                                interaction_constraint = current_interaction_constraint
                            else:
                                other_constraint = owning_interaction.constraint_intersection(posture_state=None)
                                if forced_tentative_interaction_constraint is None:
                                    forced_tentative_interaction_constraint = self.constraint_intersection(sim=sim, participant_type=participant_type, posture_state=None, allow_holster=allow_holster)
                                interaction_constraint = forced_tentative_interaction_constraint
                            constraint_resolver = self.get_constraint_resolver(None, participant_type=participant_type)
                            other_constraint = other_constraint.apply_posture_state(None, constraint_resolver)
                            intersection = interaction_constraint.intersect(other_constraint)
                            if not intersection.valid:
                                yield (owning_interaction, carry_posture)
                            while True:
                                for sub_constraint in intersection:
                                    if sub_constraint.posture_state_spec is None:
                                        break
                                    body_target = sub_constraint.posture_state_spec.body_target
                                    if body_target is not None and not isinstance(body_target, PostureSpecVariable):
                                        surface = body_target.parent
                                    else:
                                        surface = None
                                    if surface is None:
                                        break
                                    while True:
                                        for manifest_entry in sub_constraint.posture_state_spec.posture_manifest:
                                            if manifest_entry.surface_target is MATCH_NONE:
                                                pass
                                            break
                                    if not sub_constraint.posture_state_spec.slot_manifest:
                                        break
                                    while True:
                                        for runtime_slot in surface.get_runtime_slots_gen():
                                            if not runtime_slot.is_valid_for_placement(obj=carry_object, objects_to_ignore=[carry_object]):
                                                pass
                                            break
                                    break
                                yield (owning_interaction, carry_posture)

    def register_on_cancelled_callback(self, callback):
        self._on_cancelled_callbacks.append(callback)

    def send_current_progress(self, new_interaction=True):
        self.send_progress_bar_message(new_interaction=new_interaction)

    def send_progress_bar_message(self, new_interaction=True):
        if self.progress_bar_enabled.bar_enabled and (self.display_name and self.sim.is_selectable) and self.sim.valid_for_distribution:
            if self.progress_bar_enabled.force_listen_statistic:
                progress_tuning = self.progress_bar_enabled.force_listen_statistic
                progress_target = self.get_participant(progress_tuning.subject)
                tracker = progress_target.get_tracker(progress_tuning.statistic)
                if tracker is not None and self._progress_bar_goal is None:
                    self._progress_bar_commodity_callback = tracker.add_watcher(self._progress_bar_update_statistic_callback)
                    if self.progress_bar_enabled.interaction_exceptions.is_music_interaction:
                        track_time = clock.interval_in_real_seconds(self._track.length).in_minutes()
                        if track_time == 0:
                            logger.error('Progress bar: Tuned track time is 0 for interaction {}.', self, owner='camilogarcia')
                            return
                        rate_change = 1/track_time
                        self._send_progress_bar_update_msg(0, rate_change, start_msg=True)
                    elif self._conditional_action_manager:
                        (percent, rate_change) = self._conditional_action_manager.get_percent_rate_for_best_exit_conditions(self)
                        if percent is not None:
                            if not self.progress_bar_enabled.remember_progress and new_interaction and percent < 1:
                                rate_change = rate_change/(1 - percent)
                                percent = 0
                            self._send_progress_bar_update_msg(percent, rate_change, start_msg=True)
            elif self.progress_bar_enabled.interaction_exceptions.is_music_interaction:
                track_time = clock.interval_in_real_seconds(self._track.length).in_minutes()
                if track_time == 0:
                    logger.error('Progress bar: Tuned track time is 0 for interaction {}.', self, owner='camilogarcia')
                    return
                rate_change = 1/track_time
                self._send_progress_bar_update_msg(0, rate_change, start_msg=True)
            elif self._conditional_action_manager:
                (percent, rate_change) = self._conditional_action_manager.get_percent_rate_for_best_exit_conditions(self)
                if percent is not None:
                    if not self.progress_bar_enabled.remember_progress and new_interaction and percent < 1:
                        rate_change = rate_change/(1 - percent)
                        percent = 0
                    self._send_progress_bar_update_msg(percent, rate_change, start_msg=True)

    def _progress_bar_update_statistic_callback(self, stat_type, old_value, new_value):
        if stat_type is not self.progress_bar_enabled.force_listen_statistic.statistic:
            return
        target_value = self.progress_bar_enabled.force_listen_statistic.target_value.value
        current_value = new_value
        if target_value < current_value:
            if self._progress_bar_goal is None:
                self._progress_bar_goal = current_value - target_value
            current_value = self._progress_bar_goal - new_value
        else:
            self._progress_bar_goal = target_value
        if self._progress_bar_goal == 0:
            return
        percent = current_value/self._progress_bar_goal
        self._send_progress_bar_update_msg(percent, 0, start_msg=True)

    def send_end_progress(self):
        if self.user_canceled:
            return
        if self._progress_bar_commodity_callback is not None:
            progress_tuning = self.progress_bar_enabled.force_listen_statistic
            progress_target = self.get_participant(progress_tuning.subject)
            if progress_target is not None:
                tracker = progress_target.get_tracker(progress_tuning.statistic)
                tracker.remove_watcher(self._progress_bar_commodity_callback)
            self._progress_bar_commodity_callback = None
        if self._progress_bar_displayed and self.sim.valid_for_distribution:
            self._send_progress_bar_update_msg(1, 0)

    def _send_progress_bar_update_msg(self, percent, rate_change, start_msg=False):
        if start_msg:
            self._progress_bar_displayed = True
        op = distributor.ops.InteractionProgressUpdate(self.sim.sim_id, percent, rate_change, self.id)
        Distributor.instance().add_op(self.sim, op)

    @property
    def acquire_listeners_as_resource(self):
        return False

    @flexmethod
    def get_resolver(cls, inst, target=DEFAULT, context=DEFAULT, super_interaction=None, **interaction_parameters):
        inst_or_cls = inst if inst is not None else cls
        if target == DEFAULT:
            target = inst_or_cls.target
        if context == DEFAULT:
            context = inst_or_cls.context
        return event_testing.resolver.InteractionResolver(cls, inst, target=target, context=context, super_interaction=super_interaction, **interaction_parameters)

    @property
    def finishing_type(self):
        if self._finisher is not None:
            return self._finisher.finishing_type

