from animation.arb_accumulator import with_skippable_animation_time
from broadcasters.broadcaster_request import BroadcasterRequest
from buffs.tunable import TunableBuffElement
from carry import TunableExitCarryWhileHolding, TunableEnterCarryWhileHolding
from interactions import ParticipantType
from interactions.utils.adventure import Adventure
from interactions.utils.animation_reference import TunableAnimationReference
from interactions.utils.audio import TunableAudioModificationElement, TunableAudioSting
from interactions.utils.balloon import TunableBalloon
from interactions.utils.camera import CameraFocusElement
from interactions.utils.creation import ObjectCreationElement, SimCreationElement
from interactions.utils.destruction import ObjectDestructionElement
from interactions.utils.filter_elements import InviteSimElement
from interactions.utils.interaction_elements import ParentObjectElement, FadeChildrenElement, SetVisibilityStateElement, UpdatePhysique
from interactions.utils.life_event import TunableLifeEventElement
from interactions.utils.notification import NotificationElement
from interactions.utils.payment import PaymentElement
from interactions.utils.plumbbob import TunableReslotPlumbbob
from interactions.utils.pregnancy import PregnancyElement
from interactions.utils.reaction_trigger import ReactionTriggerElement
from interactions.utils.sim_focus import TunableFocusElement
from interactions.utils.state import TunableConditionalAnimationElement
from interactions.utils.statistic_element import PeriodicStatisticChangeElement, TunableProgressiveStatisticChangeElement, TunableStatisticIncrementDecrement, TunableStatisticDecayByCategory, TunableStatisticTransferRemove, TunableExitConditionSnippet, ConditionalActionRestriction, ConditionalInteractionAction
from interactions.utils.tunable import TunableSetClockSpeed, ServiceNpcRequest, TunableSetSimSleeping, ContentSetWithOverrides, ContentSet, DoCommand, SetGoodbyeNotificationElement
from interactions.utils.visual_effect import PlayVisualEffectElement
from objects.components.autonomy import TunableParameterizedAutonomy
from objects.components.footprint_component import TunableFootprintToggleElement
from objects.components.game_component import TunableJoinGame, TunableSetGameTarget
from objects.components.gardening_components import SlotItemHarvest
from objects.components.inventory import InventoryTransfer, PutObjectInMail, DeliverBill, DestroySpecifiedObjectsFromTargetInventory
from objects.components.name_component import NameTransfer
from objects.components.state import TunableStateChange, TunableTransienceChange
from objects.components.stored_sim_info_component import StoreSimElement
from objects.household_inventory_management import SendToInventory
from relationships.relationship_bit_change import TunableRelationshipBitElement
from sims.royalty_tracker import TunableRoyaltyPayment
from sims.sim_outfits import ChangeOutfitElement
from sims4.tuning.tunable import OptionalTunable, TunableVariant, TunableList, AutoFactoryInit, HasTunableSingletonFactory, TunableFactory, TunableReference, TunableTuple, Tunable, TunableEnumEntry
from sims4.tuning.tunable_base import FilterTag
from singletons import DEFAULT
from situations.tunable import CreateSituationElement, TunableUserAskNPCToLeave, TunableMakeNPCLeaveMustRun, TunableSummonNpc
from world.spawn_point import DynamicSpawnPointElement
import careers.career_tuning
import interactions
import services
import sims4.log
logger = sims4.log.Logger('Basic')
AFFORDANCE_LOADED_CALLBACK_STR = 'on_affordance_loaded_callback'

class _BasicContent(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = '_BasicContent'
    animation_ref = None
    periodic_stat_change = None
    progressive_stat_change = None
    statistic_reduction_by_category = None
    conditional_actions = None
    start_autonomous_inertial = False
    start_user_directed_inertial = False
    staging = False
    sleeping = False
    content_set = None
    FACTORY_TUNABLES = {'allow_holster': OptionalTunable(description='\n            If enabled, specify an override as to whether or not this\n            interaction allows holstering. If left unspecified, then only\n            staging interactions will allow holstering.\n            \n            For example: a one-shot interaction where the Grim Reaper dooms a\n            Sim disallows carry. Normally, the Grim Reaper would be unable to\n            holster his scythe. We override holstering to be allowed such that\n            the scythe can indeed be holstered.\n            ', tunable=Tunable(description='\n                Whether or not holstering is explicitly allowed or not.\n                ', tunable_type=bool, default=True), disabled_name='use_default', enabled_name='override')}

    def __call__(self, interaction, sequence=(), **kwargs):
        actor_or_object_target = interaction.target_type & interactions.TargetType.ACTOR or interaction.target_type & interactions.TargetType.OBJECT
        last_affordance_is_affordance = not interaction.simless and interaction.sim.last_affordance is interaction.affordance
        if self.animation_ref is not None:
            animation_sequence = self.animation_ref(interaction, sequence=sequence, **kwargs)
        if actor_or_object_target and (last_affordance_is_affordance and (not interaction.is_super and (self.sleeping == True and self.animation_ref is not None))) and not animation_sequence.repeat:
            skip_animation = interaction.sim.asm_auto_exit.asm is not None
        else:
            skip_animation = False
        if self.animation_ref is not None and not skip_animation:
            sequence = animation_sequence
        if self.periodic_stat_change is not None:
            sequence = self.periodic_stat_change(interaction, sequence=sequence)
        if self.progressive_stat_change is not None:
            sequence = self.progressive_stat_change(interaction, sequence=sequence)
        if self.statistic_reduction_by_category is not None:
            sequence = self.statistic_reduction_by_category(interaction, sequence=sequence)
        if self.sleeping and self.animation_ref is not None and not animation_sequence.repeat:
            sequence = with_skippable_animation_time((interaction.sim,), sequence=sequence)
        return sequence

    def validate_tuning(self):
        pass

class NoContent(_BasicContent):
    __qualname__ = 'NoContent'
    start_autonomous_inertial = True
    start_user_directed_inertial = True

class OneShotContent(_BasicContent):
    __qualname__ = 'OneShotContent'

    @TunableFactory.factory_option
    def animation_callback(callback=DEFAULT):
        return {'animation_ref': TunableAnimationReference(description=' \n                A non-looping animation reference.\n                ', callback=callback), 'periodic_stat_change': OptionalTunable(description='\n                Statistic changes tuned to occur every specified interval.\n                ', tunable=PeriodicStatisticChangeElement.TunableFactory())}

class _FlexibleLengthContent(_BasicContent):
    __qualname__ = '_FlexibleLengthContent'
    FACTORY_TUNABLES = {'progressive_stat_change': OptionalTunable(description='\n            Statistic changes tuned to change a certain amount over the course\n            of an interaction.\n            ', tunable=TunableProgressiveStatisticChangeElement()), 'periodic_stat_change': OptionalTunable(description='\n            Statistic changes tuned to occur every specified interval.\n            ', tunable=PeriodicStatisticChangeElement.TunableFactory()), 'statistic_reduction_by_category': OptionalTunable(description='\n            Increase the decay of some commodities over time.\n            Useful for removing a category of buffs from a Sim.', tunable=TunableStatisticDecayByCategory()), 'conditional_actions': TunableList(description='\n            A list of conditional actions for this interaction. Conditional\n            actions are behavior, such as giving loot and canceling interaction,\n            that trigger based upon a condition or list of conditions, e.g. \n            time or a commodity hitting a set number.\n            \n            Example behavior that can be accomplished with this:\n            - Guarantee a Sim will play with a doll for 30 minutes.\n            - Stop the interaction when the object breaks.\n            ', tunable=TunableExitConditionSnippet()), 'start_autonomous_inertial': Tunable(bool, True, needs_tuning=True, description='\n            Inertial interactions will run only for as long autonomy fails to\n            find another interaction that outscores it. As soon as a higher-\n            scoring interaction is found, the inertial interaction is canceled\n            and the other interaction runs.\n            \n            The opposite of inertial is guaranteed. A guaranteed interaction\n            will never be displaced by autonomy, even if there are higher\n            scoring interactions available to the Sim.\n\n            This option controls which mode the interaction starts in if\n            autonomy starts it. If started guaranteed, this interaction can be\n            set back to inertial with a conditional action.\n            \n            Please use this with care. If an interaction starts guaranteed but\n            nothing ever sets the interaction back to inertial or otherwise end\n            the interaction, this interaction will never end without direct\n            user intervention.\n            '), 'start_user_directed_inertial': Tunable(bool, False, needs_tuning=True, description='\n            Inertial interactions will run only for as long autonomy fails to\n            find another interaction that outscores it. As soon as a higher-\n            scoring interaction is found, the inertial interaction is canceled\n            and the other interaction runs.\n            \n            The opposite of inertial is guaranteed. A guaranteed interaction\n            will never be displaced by autonomy, even if there are higher\n            scoring interactions available to the Sim.\n\n            This option controls which mode the interaction starts in if the\n            user starts it. If started guaranteed, this interaction can be\n            set back to inertial with a conditional action.\n            \n            Please use this with care. If an interaction starts guaranteed but\n            nothing ever sets the interaction back to inertial or otherwise end\n            the interaction, this interaction will never end without direct\n            user intervention.\n            ')}

class _LoopingContentBase(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = '_LoopingContentBase'
    sleeping = True

    @TunableFactory.factory_option
    def animation_callback(callback=DEFAULT):
        return {'animation_ref': TunableAnimationReference(description=' \n                A looping animation reference.\n                ', callback=callback, reload_dependent=True)}

class LoopingContent(_LoopingContentBase, _FlexibleLengthContent):
    __qualname__ = 'LoopingContent'

    def validate_tuning(self):
        if not self.start_autonomous_inertial:
            for conditional_action in self.conditional_actions:
                while conditional_action.restrictions != ConditionalActionRestriction.USER_DIRECTED_ONLY and conditional_action.interaction_action != ConditionalInteractionAction.NO_ACTION:
                    break
            logger.error("Looping content that doesn't start inertial that has no conditional action that causes the interaction to end.", owner='jjacobson.')
        if not self.start_user_directed_inertial:
            for conditional_action in self.conditional_actions:
                while conditional_action.restrictions != ConditionalActionRestriction.AUTONOMOUS_ONLY and conditional_action.interaction_action != ConditionalInteractionAction.NO_ACTION:
                    break
            logger.error("Looping content that doesn't start inertial that has no conditional action that causes the interaction to end.", owner='jjacobson.')

class _StagingContentBase(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = '_StagingContentBase'
    staging = True

    @TunableFactory.factory_option
    def animation_callback(callback=DEFAULT):
        return {'animation_ref': OptionalTunable(TunableAnimationReference(description=' \n                A non-looping animation reference.\n                ', callback=callback, reload_dependent=True))}

    FACTORY_TUNABLES = {'content_set': lambda : ContentSetWithOverrides.TunableFactory(), 'push_affordance_on_run': OptionalTunable(TunableTuple(actor=TunableEnumEntry(description='\n                        The participant of this interaction that is going to have\n                        the specified affordance pushed upon them.\n                        ', tunable_type=ParticipantType, default=ParticipantType.Actor), target=OptionalTunable(description="\n                        If enabled, specify a participant to be used as the\n                        interaction's target.\n                        ", tunable=TunableEnumEntry(description="\n                            The participant to be used as the interaction's\n                            target.\n                            ", tunable_type=ParticipantType, default=ParticipantType.Object), enabled_by_default=True), affordance=TunableReference(description='\n                        When this interaction is run, the tuned affordance will be\n                        pushed if possible. \n                        \n                        e.g: when Stereo dance is run, we also push the listen to\n                        music interaction\n                        ', manager=services.get_instance_manager(sims4.resources.Types.INTERACTION)), link_cancelling_to_affordance=Tunable(description='\n                        If True, when the above tuned affordance is cancelled, This\n                        interaction will cancel too. \n                        \n                        e.g.: When sim is dancing and listening to music, if the\n                        listen to music interaction is cancelled, the dance will\n                        cancel too.\n                        ', tunable_type=bool, default=True))), 'post_stage_autonomy_commodities': TunableList(description='\n                An ordered list of parameterized autonomy requests to run when\n                this interaction has staged.\n                ', tunable=TunableParameterizedAutonomy())}

class StagingContent(_StagingContentBase, _FlexibleLengthContent):
    __qualname__ = 'StagingContent'
    EMPTY = _StagingContentBase(animation_ref=None, content_set=ContentSet.EMPTY_LINKS, push_affordance_on_run=None, post_stage_autonomy_commodities=())

class FlexibleLengthContent(_FlexibleLengthContent):
    __qualname__ = 'FlexibleLengthContent'

    @TunableFactory.factory_option
    def animation_callback(callback=DEFAULT):
        return {'content': TunableVariant(staging_content=_StagingContentBase.TunableFactory(animation_callback=callback), looping_content=_LoopingContentBase.TunableFactory(animation_callback=callback), default='staging_content')}

    CONTENT_OVERRIDES = ('animation_ref', 'push_affordance_on_run', 'post_stage_autonomy_commodities', 'staging', 'sleeping', 'content_set')

    def __getattribute__(self, name):
        if name in FlexibleLengthContent.CONTENT_OVERRIDES:
            content = object.__getattribute__(self, 'content')
            try:
                return object.__getattribute__(content, name)
            except AttributeError:
                return object.__getattribute__(self, name)
        return object.__getattribute__(self, name)

class TunableBasicContentSet(TunableVariant):
    __qualname__ = 'TunableBasicContentSet'

    def __init__(self, default=None, no_content=False, one_shot=False, looping_animation=False, flexible_length=False, animation_callback=DEFAULT, description=None, **kwargs):
        options = {}
        if one_shot is True:
            options['one_shot'] = OneShotContent.TunableFactory(animation_callback=(animation_callback,))
        if looping_animation is True:
            options['looping_animation'] = LoopingContent.TunableFactory(animation_callback=(animation_callback,), locked_args={'start_autonomous_inertial': False, 'start_user_directed_inertial': False}, tuning_filter=FilterTag.EXPERT_MODE)
        if flexible_length is True:
            options['flexible_length'] = FlexibleLengthContent.TunableFactory(animation_callback=(animation_callback,))
        if no_content is True:
            options['no_content'] = NoContent.TunableFactory()
        if default is not None:
            options['default'] = default
        kwargs.update(options)
        super().__init__(description=description, **kwargs)

class BasicExtraVariantCore(TunableVariant):
    __qualname__ = 'BasicExtraVariantCore'

    def __init__(self, **kwargs):
        super().__init__(audio_modification=TunableAudioModificationElement(), audio_sting=TunableAudioSting.TunableFactory(), balloon=TunableBalloon(), broadcaster=BroadcasterRequest.TunableFactory(), buff=TunableBuffElement(), camera_focus=CameraFocusElement.TunableFactory(), career_selection=careers.career_tuning.CareerSelectElement.TunableFactory(), change_outfit=ChangeOutfitElement.TunableFactory(), create_object=ObjectCreationElement.TunableFactory(), create_sim=SimCreationElement.TunableFactory(), create_situation=CreateSituationElement.TunableFactory(), deliver_bill=DeliverBill.TunableFactory(), destroy_object=ObjectDestructionElement.TunableFactory(), destroy_specified_objects_from_target_inventory=DestroySpecifiedObjectsFromTargetInventory.TunableFactory(), do_command=DoCommand.TunableFactory(), dynamic_spawn_point=DynamicSpawnPointElement.TunableFactory(), exit_carry_while_holding=TunableExitCarryWhileHolding(), enter_carry_while_holding=TunableEnterCarryWhileHolding(), fade_children=FadeChildrenElement.TunableFactory(), inventory_transfer=InventoryTransfer.TunableFactory(), invite=InviteSimElement.TunableFactory(), life_event=TunableLifeEventElement(), notification=NotificationElement.TunableFactory(), npc_summon=TunableSummonNpc(), focus=TunableFocusElement(), parent_object=ParentObjectElement.TunableFactory(), payment=PaymentElement.TunableFactory(), pregnancy=PregnancyElement.TunableFactory(), put_object_in_mail=PutObjectInMail.TunableFactory(), royalty_payment=TunableRoyaltyPayment.TunableFactory(), send_to_inventory=SendToInventory.TunableFactory(), service_npc_request=ServiceNpcRequest.TunableFactory(), set_game_speed=TunableSetClockSpeed.TunableFactory(), set_goodbye_notification=SetGoodbyeNotificationElement.TunableFactory(), set_visibility_state=SetVisibilityStateElement.TunableFactory(), slot_item_harvest=SlotItemHarvest.TunableFactory(), stat_transfer_remove=TunableStatisticTransferRemove(), state_change=TunableStateChange(), store_sim=StoreSimElement.TunableFactory(), transfer_name=NameTransfer.TunableFactory(), transience_change=TunableTransienceChange(), trigger_reaction=ReactionTriggerElement.TunableFactory(), update_physique=UpdatePhysique.TunableFactory(), vfx=PlayVisualEffectElement.TunableFactory(), **kwargs)

class BasicExtraVariant(BasicExtraVariantCore):
    __qualname__ = 'BasicExtraVariant'

    def __init__(self, **kwargs):
        super().__init__(adventure=Adventure.TunableFactory(), conditional_animation=TunableConditionalAnimationElement(), footprint_toggle=TunableFootprintToggleElement(), join_game=TunableJoinGame(), make_npc_leave_now_must_run=TunableMakeNPCLeaveMustRun(), relationship_bit=TunableRelationshipBitElement(), reslot_plumbbob=TunableReslotPlumbbob(), set_game_target=TunableSetGameTarget(), set_sim_sleeping=TunableSetSimSleeping(), stat_increment_decrement=TunableStatisticIncrementDecrement(), user_ask_npc_to_leave=TunableUserAskNPCToLeave(), **kwargs)

BASIC_EXTRA_DESCRIPTION = "\n    Basic extras add additional non-periodic behavior to an interaction.\n    Elements in this list come in two kinds: ones that act once and ones\n    that do something at the beginning and end of an interaction.\n    \n    The first kind generally causes a discrete change in the world at a\n    specified moment. Most of these tunables give you the option of\n    specifying the moment in time when the behavior should trigger,\n    usually at the beginning of the interaction, the end of the\n    interaction, or on an xevent.\n    \n    The other kind of element is one that starts some modifying behavior\n    which ends at the end of the interaction.  These do things like\n    modify the Sim's focus or modify audio properties.\n    \n    The order of the elements you add to this list does matter: the\n    elements that come earlier in the list surround the behavior of\n    elements that come later.  In most cases this order isn't\n    significant, but it is possible that one element could depend on the\n    behavior of another having already occurred.  Consult a GPE if you\n    aren't sure.\n    \n    e.g. You want a sound modifier to be in effect while running this\n    interaction, and while the sound is playing, you want the Sim's\n    focus to be affected:\n     * add an 'audio_modification' element\n     * add a 'focus' element\n     \n    In this case, the audio_modification element will start before the\n    focus one, and it will end after the focus one.  (This example is\n    somewhat contrived since both the beginning and ending of both\n    elements will happen on the same frame so the order doesn't actually\n    matter.)\n         \n    e.g. You want an object state to change at a particular xevent, such\n    as a toilet becoming flushed when the Sim touches the handle:\n     * add a 'state' element, using the xevent id agreed on in the DR or\n       IR to fill in the timing.\n    "

class TunableBasicExtrasCore(TunableList):
    __qualname__ = 'TunableBasicExtrasCore'

    def __init__(self, **kwargs):
        super().__init__(description=BASIC_EXTRA_DESCRIPTION, tunable=BasicExtraVariantCore(), **kwargs)

class TunableBasicExtras(TunableList):
    __qualname__ = 'TunableBasicExtras'

    def __init__(self, description=BASIC_EXTRA_DESCRIPTION, **kwargs):
        super().__init__(description=description, tunable=BasicExtraVariant(), **kwargs)

