from clock import ClockSpeedMode
from date_and_time import create_time_span
from element_utils import build_critical_section_with_finally
from gsi_handlers import clock_handlers
from interactions import ParticipantType
from interactions.interaction_finisher import FinishingType
from interactions.liability import Liability
from interactions.utils.balloon import TunableBalloon
from interactions.utils.interaction_elements import XevtTriggeredElement
from interactions.utils.notification import NotificationElement
from sims4 import commands
from sims4.localization import TunableLocalizedStringFactory
from sims4.tuning.tunable import TunableList, TunableReference, TunableFactory, Tunable, TunableEnumEntry, TunableMapping, TunableTuple, TunableVariant, HasTunableFactory, TunableSimMinute, OptionalTunable
from snippets import TunableAffordanceListReference
from statistics.statistic import Statistic
from statistics.statistic_ops import TunableStatisticChange
from ui.ui_dialog_notification import TunableUiDialogNotificationSnippet
import alarms
import clock
import services
import sims4.log
import sims4.resources
logger = sims4.log.Logger('Super Interactions')

class TunableAffordanceLinkList(TunableList):
    __qualname__ = 'TunableAffordanceLinkList'

    def __init__(self, class_restrictions=(), **kwargs):
        super().__init__(TunableReference(services.get_instance_manager(sims4.resources.Types.INTERACTION), checks=[('check_posture_compatability', 'asm')], category='asm', description='Linked Affordance', class_restrictions=class_restrictions), **kwargs)

class ContentSet(HasTunableFactory):
    __qualname__ = 'ContentSet'
    FACTORY_TUNABLES = {'description': ' \n           This is where you tune any sub actions of this interaction.\n           \n           The interactions here can be tuned as reference to individual\n           affordances, lists of affordances, or phase affordances.\n           \n           Sub actions are affordances that can be run anytime this \n           interaction is active. Autonomy will choose which interaction\n           runs.\n           \n           Using phase affordances you can also tune Quick Time or \n           optional affordances that can appear.\n           ', 'affordance_links': TunableAffordanceLinkList(class_restrictions=('MixerInteraction',)), 'affordance_lists': TunableList(TunableAffordanceListReference()), 'phase_affordances': TunableMapping(description='\n            A mapping of phase names to affordance links and affordance lists. \n                      \n            This is also where you can specify an affordance is Quick Time (or\n            an optional affordance) and how many steps are required before an\n            option affordance is made available.\n            ', value_type=TunableList(TunableTuple(affordance_links=TunableAffordanceLinkList(class_restrictions=('MixerInteraction',)), affordance_lists=TunableList(TunableAffordanceListReference())))), 'phase_tuning': OptionalTunable(TunableTuple(description='\n            When enabled, statistic will be added to target and is used to\n            determine the phase index to determine which affordance group to use\n            in the phase affordance.\n            ', turn_statistic=Statistic.TunableReference(description='\n                The statistic used to track turns during interaction.\n                Value will be reset to 0 at the start of each phase.\n                '), target=TunableEnumEntry(description='\n                The participant the affordance will target.\n                ', tunable_type=ParticipantType, default=ParticipantType.Actor)))}
    EMPTY_LINKS = None

    def __init__(self, affordance_links, affordance_lists, phase_affordances, phase_tuning):
        self._affordance_links = affordance_links
        self._affordance_lists = affordance_lists
        self.phase_tuning = phase_tuning
        self._phase_affordance_links = []
        for key in sorted(phase_affordances.keys()):
            self._phase_affordance_links.append(phase_affordances[key])

    def _get_all_affordance_for_phase_gen(self, phase_affordances):
        for affordance in phase_affordances.affordance_links:
            yield affordance
        for affordance_list in phase_affordances.affordance_lists:
            for affordance in affordance_list:
                yield affordance

    def all_affordances_gen(self, phase_index=None):
        if phase_index is not None and self._phase_affordance_links:
            phase_index = min(phase_index, len(self._phase_affordance_links) - 1)
            phase = self._phase_affordance_links[phase_index]
            for phase_affordances in phase:
                for affordance in self._get_all_affordance_for_phase_gen(phase_affordances):
                    yield affordance
        else:
            for phase in self._phase_affordance_links:
                for phase_affordances in phase:
                    for affordance in self._get_all_affordance_for_phase_gen(phase_affordances):
                        yield affordance
            for link in self._affordance_links:
                yield link
            for l in self._affordance_lists:
                for link in l:
                    yield link

    @property
    def num_phases(self):
        return len(self._phase_affordance_links)

    def has_affordances(self):
        return bool(self._affordance_links) or (bool(self._affordance_lists) or bool(self._phase_affordance_links))

ContentSet.EMPTY_LINKS = ContentSet((), (), {}, None)

class ContentSetWithOverrides(ContentSet):
    __qualname__ = 'ContentSetWithOverrides'
    FACTORY_TUNABLES = {'balloon_overrides': OptionalTunable(TunableList(description='\n            Balloon Overrides lets you override the mixer balloons.\n            EX: Each of the comedy routine performances have a set of balloons.\n            However, the animation/mixer content is the same. We want to play\n            the same mixer content, but just have the balloons be different.\n            ', tunable=TunableBalloon()))}

    def __init__(self, balloon_overrides, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.balloon_overrides = balloon_overrides

class TunableStatisticAdvertisements(TunableList):
    __qualname__ = 'TunableStatisticAdvertisements'

    def __init__(self, **kwargs):
        super().__init__(TunableStatisticChange(locked_args={'subject': ParticipantType.Actor, 'advertise': True}), **kwargs)

class TunableContinuation(TunableList):
    __qualname__ = 'TunableContinuation'

    def __init__(self, target_default=ParticipantType.Object, locked_args={}, carry_target_default=ParticipantType.Object, **kwargs):
        super().__init__(TunableTuple(affordance=TunableReference(services.affordance_manager(), description='The affordance to push as a continuation on the actor for this SI.'), si_affordance_override=TunableReference(services.affordance_manager(), description="When the tuned affordance is a mixer for a different SI, use this to specify the mixer's appropriate SI. This is useful for pushing socials."), actor=TunableEnumEntry(ParticipantType, ParticipantType.Actor, description='The Sim on which the affordance is pushed.'), target=TunableEnumEntry(ParticipantType, target_default, description='The participant the affordance will target.'), carry_target=OptionalTunable(TunableEnumEntry(ParticipantType, carry_target_default, description='The participant the affordance will set as a carry target.')), locked_args=locked_args), **kwargs)

class TimeoutLiability(Liability, HasTunableFactory):
    __qualname__ = 'TimeoutLiability'
    LIABILITY_TOKEN = 'TimeoutLiability'
    FACTORY_TUNABLES = {'description': 'Establish a timeout for this affordance. If it has not run when the timeout hits, cancel and push timeout_affordance, if set.', 'timeout': TunableSimMinute(4, minimum=0, description='The time, in Sim minutes, after which the interaction is canceled and time_toute affordance is pushed, if set.'), 'timeout_affordance': TunableReference(services.affordance_manager(), description='The affordance to push when the timeout expires. Can be unset, in which case the interaction will just be canceled.')}

    def __init__(self, interaction, *, timeout, timeout_affordance):

        def on_alarm(*_, **__):
            if interaction.running:
                return
            if interaction.transition is not None and interaction.transition.running:
                return
            if timeout_affordance is not None:
                context = interaction.context.clone_for_continuation(interaction)
                interaction.sim.push_super_affordance(timeout_affordance, interaction.target, context)
            interaction.cancel(FinishingType.LIABILITY, cancel_reason_msg='Timeout after {} sim minutes.'.format(timeout))

        time_span = clock.interval_in_sim_minutes(timeout)
        self._handle = alarms.add_alarm(self, time_span, on_alarm)

    def release(self):
        alarms.cancel_alarm(self._handle)

class SaveLockLiability(Liability, HasTunableFactory):
    __qualname__ = 'SaveLockLiability'
    LIABILITY_TOKEN = 'SaveLockLiability'
    FACTORY_TUNABLES = {'description': '\n            Prevent the user from saving or traveling while this interaction is\n            in the queue or running.\n            ', 'save_lock_tooltip': TunableLocalizedStringFactory(description='\n                The tooltip/message to show when the player tries to save the\n                game or return to the neighborhood view while the interaction\n                is running or in the queue.\n                '), 'should_transfer': Tunable(description='\n                If this liability should transfer to continuations.\n                ', tunable_type=bool, default=True)}

    def __init__(self, interaction, *, save_lock_tooltip, should_transfer):
        self._save_lock_tooltip = save_lock_tooltip
        self._should_transfer = should_transfer
        self._interaction = interaction
        self._is_save_locked = False

    def on_add(self, interaction):
        self._interaction = interaction
        if not self._is_save_locked:
            services.get_persistence_service().lock_save(self)
            self._is_save_locked = True

    @property
    def should_transfer(self):
        return self._should_transfer

    def release(self):
        services.get_persistence_service().unlock_save(self)

    def get_lock_save_reason(self):
        return self._interaction.create_localized_string(self._save_lock_tooltip)

def set_sim_sleeping(interaction, sequence=None):
    sim = interaction.sim

    def set_sleeping(_):
        sim.sleeping = True

    def set_awake(_):
        sim.sleeping = False

    return build_critical_section_with_finally(set_sleeping, sequence, set_awake)

class TunableSetSimSleeping(TunableFactory):
    __qualname__ = 'TunableSetSimSleeping'
    FACTORY_TYPE = staticmethod(set_sim_sleeping)

class TunableSetClockSpeed(XevtTriggeredElement):
    __qualname__ = 'TunableSetClockSpeed'
    SET_DIRECTLY = 1
    REQUEST_SPEED = 2
    UNREQUEST_SS3 = 3
    FACTORY_TUNABLES = {'description': 'Change the game clock speed as part of an interaction.', 'game_speed_change': TunableVariant(default='set_speed_directly', set_speed_directly=TunableTuple(description='\n                When the interaction runs, the clock speed is set directly at\n                the specified time.\n                ', locked_args={'set_speed_type': SET_DIRECTLY}, game_speed=TunableEnumEntry(description='\n                    The speed to set the game.\n                    ', tunable_type=ClockSpeedMode, default=ClockSpeedMode.NORMAL)), try_request_speed=TunableTuple(description='\n                Request a change in game speed. When all user sims on the lot\n                have requested the speed, the speed will occur.\n                ', locked_args={'set_speed_type': REQUEST_SPEED}, game_speed=TunableEnumEntry(description='\n                    The clock speed is requested, and when all user sims on the\n                    lot have requested the speed, the speed will occur.\n                    ', tunable_type=ClockSpeedMode, default=ClockSpeedMode.SPEED3), allow_super_speed_three=OptionalTunable(description='\n                    If enabled, when this interaction is run, the actor sim is\n                    marked as okay to be sped up to super speed 3. When all\n                    instantiated sims are okay to be sped up to super speed 3,\n                    if the game is in speed 3, the game will go into super\n                    speed 3.\n                    ', tunable=TunableTuple(unrequest_speed=OptionalTunable(description='\n                            If enabled and if the game is still in super speed\n                            3 when the interaction is canceled or ends, this\n                            speed will be requested.\n                            ', tunable=TunableEnumEntry(tunable_type=ClockSpeedMode, default=ClockSpeedMode.NORMAL), enabled_by_default=True)), needs_tuning=True)), unrequest_super_speed_three=TunableTuple(description='\n                This will directly set the game speed only if super speed three\n                is active. Otherwise, nothing happens.\n                ', locked_args={'set_speed_type': UNREQUEST_SS3}, game_speed=TunableEnumEntry(description='\n                    This is the speed the game will enter if it was in Super Speed\n                    Three.\n                    ', tunable_type=ClockSpeedMode, default=ClockSpeedMode.NORMAL)))}

    def __init__(self, interaction, *args, game_speed_change, sequence=(), **kwargs):
        super().__init__(interaction, sequence=sequence, game_speed_change=game_speed_change, *args, **kwargs)
        self._game_speed_change = game_speed_change
        self._sim_id = None

    def _do_behavior(self):
        if clock.GameClock.ignore_game_speed_requests:
            return
        set_speed_type = self._game_speed_change.set_speed_type
        game_speed = self._game_speed_change.game_speed
        if set_speed_type == self.SET_DIRECTLY:
            services.game_clock_service().set_clock_speed(game_speed)
        elif set_speed_type == self.REQUEST_SPEED:
            allow_ss3 = self._game_speed_change.allow_super_speed_three
            game_speed_params = (game_speed, allow_ss3 is not None)
            if allow_ss3 is not None and allow_ss3.unrequest_speed is not None:
                self.interaction.register_on_cancelled_callback(lambda _: self._unrequest_super_speed_three_mode(allow_ss3.unrequest_speed))
            self._sim_id = self.interaction.sim.id
            services.game_clock_service().register_game_speed_change_request(self.interaction.sim, game_speed_params)
        elif set_speed_type == self.UNREQUEST_SS3:
            self._unrequest_super_speed_three_mode(game_speed)
        if clock_handlers.speed_change_archiver.enabled:
            clock_handlers.archive_speed_change(self.interaction, set_speed_type, game_speed, True)

    def _unrequest_super_speed_three_mode(self, game_speed):
        if services.get_super_speed_three_service().in_super_speed_three_mode():
            services.game_clock_service().set_clock_speed(game_speed)

    def _unrequest_speed(self, *_, **__):
        if self._sim_id is not None:
            services.game_clock_service().unregister_game_speed_change_request(self._sim_id)
            if clock_handlers.speed_change_archiver.enabled:
                clock_handlers.archive_speed_change(self.interaction, None, None, False)

    def _build_outer_elements(self, sequence):
        if self._game_speed_change.set_speed_type == self.REQUEST_SPEED:
            return build_critical_section_with_finally(sequence, self._unrequest_speed)
        return sequence

class ServiceNpcRequest(XevtTriggeredElement):
    __qualname__ = 'ServiceNpcRequest'
    MINUTES_ADD_TO_SERVICE_ARRIVAL = 5
    HIRE = 1
    CANCEL = 2
    FACTORY_TUNABLES = {'description': '\n        Request a service NPC as part of an interaction. Note for timing field:\n        Only beginning and end will work because xevents will trigger\n        immediately on the server for service requests\n        ', 'request_type': TunableVariant(description='\n                Specify the type of service NPC Request. You can hire, dismiss,\n                fire, or cancel a service npc.', hire=TunableTuple(description='\n                A reference to the tuned service npc instance that will be\n                requested at the specified time.', locked_args={'request_type': HIRE}, service=TunableReference(services.service_npc_manager())), cancel=TunableTuple(locked_args={'request_type': CANCEL}, service=TunableReference(services.service_npc_manager()), description='A reference to the tuned service that will be cancelled. This only really applies to recurring services where a cancelled service will never have any service npcs show up again until re-requested.'), default='hire'), 'notification': OptionalTunable(description='\n                When enabled, display a notification when the service npc is \n                successfully hired/cancelled.\n                If hired, last token is DateAndTime when service npc will\n                arrive. (usually this is 1)\n                ', tunable=NotificationElement.TunableFactory(locked_args={'timing': XevtTriggeredElement.LOCKED_AT_BEGINNING}))}

    def __init__(self, interaction, *args, request_type, notification, sequence=(), **kwargs):
        super().__init__(interaction, request_type=request_type, notification=notification, sequence=sequence, *args, **kwargs)
        self._request_type = request_type
        self.notification = notification
        self._household = interaction.sim.household
        self._service_npc_user_specified_data_id = None
        self._recurring = False
        self._read_interaction_parameters(**interaction.interaction_parameters)

    def _read_interaction_parameters(self, service_npc_user_specified_data_id=None, service_npc_recurring_request=False, **kwargs):
        self._service_npc_user_specified_data_id = service_npc_user_specified_data_id
        self._recurring = service_npc_recurring_request

    def _do_behavior(self):
        request_type = self._request_type.request_type
        service_npc = self._request_type.service
        if service_npc is None:
            return
        service_npc_service = services.current_zone().service_npc_service
        if request_type == self.HIRE:
            finishing_time = service_npc_service.request_service(self._household, service_npc, user_specified_data_id=self._service_npc_user_specified_data_id, is_recurring=self._recurring)
            if self.notification is not None and finishing_time is not None:
                finishing_time = finishing_time + create_time_span(minutes=self.MINUTES_ADD_TO_SERVICE_ARRIVAL)
                notification_element = self.notification(self.interaction)
                notification_element.show_notification(additional_tokens=(finishing_time,))
        elif request_type == self.CANCEL:
            service_npc_service.cancel_service(self._household, service_npc)
            if self.notification is not None:
                notification_element = self.notification(self.interaction)
                notification_element._do_behavior()

class DoCommand(XevtTriggeredElement, HasTunableFactory):
    __qualname__ = 'DoCommand'
    FACTORY_TUNABLES = {'description': "\n            Run a server command, providing its target's id as an argument.\n            ", 'command': Tunable(description='The command to run.', tunable_type=str, default=None)}

    def _do_behavior(self):
        if self.interaction.context.client is not None:
            if self.interaction.context.target_sim_id is not None:
                commands.execute('{} {}'.format(self.command, self.interaction.context.target_sim_id), self.interaction.context.client.id)
            else:
                commands.execute('{} {}'.format(self.command, self.interaction.target.id), self.interaction.context.client.id)
        else:
            commands.execute('{} {}'.format(self.command, self.interaction.target.id), None)
        return True

class SetGoodbyeNotificationElement(XevtTriggeredElement):
    __qualname__ = 'SetGoodbyeNotificationElement'
    NEVER_USE_NOTIFICATION_NO_MATTER_WHAT = 'never_use_notification_no_matter_what'
    FACTORY_TUNABLES = {'description': 'Set the notification that a Sim will display when they leave.', 'participant': TunableEnumEntry(description='\n            The participant of the interaction who will have their "goodbye"\n            notification set.\n            ', tunable_type=ParticipantType, default=ParticipantType.Actor), 'goodbye_notification': TunableVariant(description='\n                The "goodbye" notification that will be set on this Sim. This\n                notification will be displayed when this Sim leaves the lot\n                (unless it gets overridden later).\n                ', notification=TunableUiDialogNotificationSnippet(), locked_args={'no_notification': None, 'never_use_notification_no_matter_what': NEVER_USE_NOTIFICATION_NO_MATTER_WHAT}, default='no_notification'), 'only_set_if_notification_already_set': Tunable(description="\n                If the Sim doesn't have a goodbye notification already set and\n                this checkbox is checked, leave the goodbye notification unset.\n                ", tunable_type=bool, default=True)}

    def _do_behavior(self):
        participants = self.interaction.get_participants(self.participant)
        for participant in participants:
            if participant.sim_info.goodbye_notification == self.NEVER_USE_NOTIFICATION_NO_MATTER_WHAT:
                pass
            if participant.sim_info.goodbye_notification is None and self.only_set_if_notification_already_set:
                pass
            participant.sim_info.goodbye_notification = self.goodbye_notification

