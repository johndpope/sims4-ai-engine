import operator
from event_testing.results import TestResult
from interactions import ParticipantType
from interactions.aop import AffordanceObjectPair
from interactions.base.immediate_interaction import ImmediateSuperInteraction
from interactions.base.super_interaction import SuperInteraction
from interactions.context import InteractionContext, QueueInsertStrategy
from interactions.interaction_finisher import FinishingType
from interactions.join_liability import JOIN_INTERACTION_LIABILITY, JoinInteractionLiability
from sims4.localization import TunableLocalizedStringFactory, LocalizationHelperTuning
from sims4.tuning.tunable import TunableReference, Tunable, TunableList, TunableTuple, OptionalTunable, TunableEnumEntry, TunableVariant
from sims4.utils import flexmethod, classproperty
from singletons import DEFAULT
from ui.ui_dialog_generic import UiDialogTextInputOkCancel, UiDialogTextInputOk
import element_utils
import services
import sims4.resources

class BaseInteractionTuning:
    __qualname__ = 'BaseInteractionTuning'
    GLOBAL_AFFORDANCES = TunableList(TunableReference(services.get_instance_manager(sims4.resources.Types.INTERACTION)), description='Super affordances on all objects.')

class ProxyInteraction(SuperInteraction):
    __qualname__ = 'ProxyInteraction'
    INSTANCE_SUBCLASSES_ONLY = True

    @classproperty
    def proxy_name(cls):
        return '[Proxy]'

    @classmethod
    def generate(cls, proxied_affordance):

        class ProxyInstance(cls, proxied_affordance):
            __qualname__ = 'ProxyInteraction.generate.<locals>.ProxyInstance'
            INSTANCE_SUBCLASSES_ONLY = True

            @classproperty
            def proxied_affordance(cls):
                return proxied_affordance

            @classmethod
            def get_interaction_type(cls):
                return proxied_affordance.get_interaction_type()

        ProxyInstance.__name__ = cls.proxy_name + proxied_affordance.__name__
        return ProxyInstance

    @classmethod
    def potential_pie_menu_sub_interactions_gen(cls, target, context, **kwargs):
        pass

class JoinInteraction(ProxyInteraction):
    __qualname__ = 'JoinInteraction'
    create_join_solo_solo = TunableLocalizedStringFactory(default=3134556480, description='Interaction name wrapper for when a solo Sim joins another solo Sim.')
    INSTANCE_SUBCLASSES_ONLY = True

    @classmethod
    def generate(cls, proxied_affordance, join_interaction, joinable_info):
        result = super().generate(proxied_affordance)
        result.join_interaction = join_interaction
        result.joinable_info = joinable_info
        return result

    @classproperty
    def proxy_name(cls):
        return '[Join]'

    @classproperty
    def allow_user_directed(cls):
        return True

    @classmethod
    def _can_rally(cls, *args, **kwargs):
        return False

    @classmethod
    def _test(cls, *args, **kwargs):
        return super()._test(join=True, *args, **kwargs)

    @flexmethod
    def get_name(cls, inst, target=DEFAULT, context=DEFAULT, **kwargs):
        if inst is not None:
            return super(JoinInteraction, inst).get_name(target=target, context=context, **kwargs)
        join_target = cls.get_participant(participant_type=ParticipantType.JoinTarget, sim=context.sim, target=target, **kwargs)
        original_name = super(JoinInteraction, cls).get_name(target=target, context=context, **kwargs)
        localization_args = (original_name, join_target)
        if cls.joinable_info.join_available and cls.joinable_info.join_available.loc_custom_join_name is not None:
            return cls.joinable_info.join_available.loc_custom_join_name(*localization_args)
        return cls.create_join_solo_solo(*localization_args)

    def run_pre_transition_behavior(self, *args, **kwargs):
        if self.join_interaction.has_been_canceled:
            self.cancel(FinishingType.INTERACTION_INCOMPATIBILITY, cancel_reason_msg='The joined interaction has been canceled.')
        return super().run_pre_transition_behavior(*args, **kwargs)

    def on_added_to_queue(self, *args, **kwargs):
        super().on_added_to_queue(*args, **kwargs)
        if self.joinable_info.link_joinable:
            self.join_interaction.add_liability(JOIN_INTERACTION_LIABILITY, JoinInteractionLiability(self))

class AskToJoinInteraction(ProxyInteraction, ImmediateSuperInteraction):
    __qualname__ = 'AskToJoinInteraction'
    create_invite_solo_any = TunableLocalizedStringFactory(default=974662056, description='Interaction name wrapper for inviting a solo Sim.')
    INSTANCE_SUBCLASSES_ONLY = True

    @classproperty
    def proxy_name(cls):
        return '[AskToJoin]'

    def __init__(self, *args, **kwargs):
        ImmediateSuperInteraction.__init__(self, *args, **kwargs)

    def _trigger_interaction_start_event(self):
        pass

    def _trigger_interaction_complete_test_event(self):
        pass

    @classmethod
    def generate(cls, proxied_affordance, join_sim, join_interaction, joinable_info):
        result = super().generate(proxied_affordance)
        result.join_sim = join_sim
        result.join_interaction = join_interaction
        result.joinable_info = joinable_info
        return result

    @classproperty
    def allow_autonomous(cls):
        return False

    @classproperty
    def allow_user_directed(cls):
        return True

    @classmethod
    def test(cls, target, context, **kwargs):
        join_context = context.clone_for_sim(cls.join_sim)
        return cls.proxied_affordance.test(target, join_context, join=True, **kwargs)

    @flexmethod
    def _get_name(cls, inst, target=DEFAULT, context=DEFAULT, **kwargs):
        inst_or_cls = inst if inst is not None else cls
        original_name = super(ProxyInteraction, inst_or_cls)._get_name(target=target, context=context, **kwargs)
        localization_args = (original_name, inst_or_cls.join_sim)
        if cls.joinable_info.invite_available and cls.joinable_info.invite_available.loc_custom_invite_name is not None:
            return cls.joinable_info.invite_available.loc_custom_invite_name(*localization_args)
        return inst_or_cls.create_invite_solo_any(*localization_args)

    def _push_join_interaction(self, join_sim):
        join_interaction = JoinInteraction.generate(self.proxied_affordance, join_interaction=self.join_interaction, joinable_info=self.joinable_info)
        join_context = InteractionContext(join_sim, self.context.source, self.priority, insert_strategy=QueueInsertStrategy.NEXT)
        join_sim.push_super_affordance(join_interaction, self.target, join_context, **self.interaction_parameters)

    def _do_perform_gen(self, timeline):
        self._push_join_interaction(self.join_sim)
        return True
        yield None

    @flexmethod
    def create_localized_string(cls, inst, localized_string_factory, *tokens, **kwargs):
        inst_or_cls = inst if inst is not None else cls
        interaction_tokens = (inst_or_cls.join_sim, inst_or_cls.join_interaction.sim)
        return localized_string_factory(*interaction_tokens + tokens)

class AggregateSuperInteraction(SuperInteraction):
    __qualname__ = 'AggregateSuperInteraction'
    INSTANCE_TUNABLES = {'aggregated_affordances': TunableList(TunableTuple(priority=Tunable(int, 0, description='The relative priority of this affordance compared to other affordances in this aggregate.'), affordance=TunableReference(services.affordance_manager(), description='The aggregated affordance.')), description='A list of affordances composing this aggregate.  Distance estimation will be used to break ties if there are multiple valid interactions at the same priority level.'), 'sim_to_push_affordance_on': TunableEnumEntry(ParticipantType, ParticipantType.Actor, description='The Sim to push the affordance on.  If this is Actor, the affordance will be pushed as a continuation of this.')}
    _allow_user_directed = True

    @classmethod
    def _aops_sorted_gen(cls, target, **interaction_parameters):
        affordances = []
        for aggregated_affordance in cls.aggregated_affordances:
            aop = AffordanceObjectPair(aggregated_affordance.affordance, target, aggregated_affordance.affordance, None, **interaction_parameters)
            affordances.append((aggregated_affordance.priority, aop))
        return sorted(affordances, key=operator.itemgetter(0), reverse=True)

    @classmethod
    def _test(cls, target, context, **interaction_parameters):
        result = super()._test(target, context, **interaction_parameters)
        if not result:
            return result
        cls._allow_user_directed = False
        context = context.clone_for_sim(cls.get_participant(participant_type=cls.sim_to_push_affordance_on, sim=context.sim, target=target))
        for (_, aop) in cls._aops_sorted_gen(target, **interaction_parameters):
            result = aop.test(context)
            while result:
                if aop.affordance.allow_user_directed:
                    cls._allow_user_directed = True
                return result
        return TestResult(False, 'No sub-affordances passed their tests.')

    @classmethod
    def consumes_object(cls):
        for aggregated_affordance in cls.aggregated_affordances:
            while aggregated_affordance.affordance.consumes_object():
                return True
        return False

    @classproperty
    def allow_user_directed(cls):
        return cls._allow_user_directed

    def _do_perform_gen(self, timeline):
        sim = self.get_participant(self.sim_to_push_affordance_on)
        if sim == self.context.sim:
            context = self.context.clone_for_continuation(self)
        else:
            context = context.clone_for_sim(sim)
        max_priority = None
        aops_valid = []
        for (priority, aop) in self._aops_sorted_gen(self.target, **self.interaction_parameters):
            if max_priority is not None and priority < max_priority:
                break
            if aop.test(context):
                aops_valid.append(aop)
                max_priority = priority
        if not aops_valid:
            raise RuntimeError('Failed to find valid super affordance in AggregateSuperInteraction, did we not run its test immediately before executing it? [jpollak]')
        interactions_by_distance = []
        for aop in aops_valid:
            interaction_result = aop.interaction_factory(context)
            if not interaction_result:
                raise RuntimeError('Failed to generate interaction from aop {}. {} [maxr/tastle]'.format(aop, interaction_result))
            interaction = interaction_result.interaction
            if len(aops_valid) == 1:
                distance = 0
            else:
                (distance, _, _) = interaction.estimate_distance()
            if distance is not None:
                interactions_by_distance.append((distance, interaction))
        (_, interaction) = max(interactions_by_distance, key=operator.itemgetter(0))
        return AffordanceObjectPair.execute_interaction(interaction)
        yield None

class RenameImmediateInteraction(ImmediateSuperInteraction):
    __qualname__ = 'RenameImmediateInteraction'
    TEXT_INPUT_NEW_NAME = 'new_name'
    TEXT_INPUT_NEW_DESCRIPTION = 'new_description'
    INSTANCE_TUNABLES = {'display_name_rename': OptionalTunable(TunableLocalizedStringFactory(description="If set, this localized string will be used as the interaction's display name if the object has been previously renamed.")), 'rename_dialog': TunableVariant(description='\n            The rename dialog to show when running this interaction.\n            ', ok_dialog=UiDialogTextInputOk.TunableFactory(text_inputs=(TEXT_INPUT_NEW_NAME, TEXT_INPUT_NEW_DESCRIPTION)), ok_cancel_dialog=UiDialogTextInputOkCancel.TunableFactory(text_inputs=(TEXT_INPUT_NEW_NAME, TEXT_INPUT_NEW_DESCRIPTION)))}

    @flexmethod
    def _get_name(cls, inst, target=DEFAULT, context=DEFAULT, **kwargs):
        inst_or_cls = inst if inst is not None else cls
        target = inst.target if inst is not None else target
        if inst_or_cls.display_name_rename is not None and target.has_custom_name():
            display_name = inst_or_cls.display_name_rename
        else:
            display_name = inst_or_cls.display_name
        return inst_or_cls.create_localized_string(display_name, target=target, context=context, **kwargs)

    def _run_interaction_gen(self, timeline):
        target_name_component = self.target.name_component

        def on_response(dialog):
            if not dialog.accepted:
                return
            name = dialog.text_input_responses.get(self.TEXT_INPUT_NEW_NAME)
            description = dialog.text_input_responses.get(self.TEXT_INPUT_NEW_DESCRIPTION)
            target = self.target
            if target is not None:
                if name is not None:
                    target.set_custom_name(name)
                if description is not None:
                    target.set_custom_description(description)
                self._update_ui_metadata(target)
            sequence = self._build_outcome_sequence()
            services.time_service().sim_timeline.schedule(element_utils.build_element(sequence))

        text_input_overrides = {}
        (template_name, template_description) = target_name_component.get_template_name_and_description()
        if target_name_component.allow_name:
            text_input_overrides[self.TEXT_INPUT_NEW_NAME] = None
            if self.target.has_custom_name():
                text_input_overrides[self.TEXT_INPUT_NEW_NAME] = lambda *_, **__: LocalizationHelperTuning.get_object_name(self.target)
            elif template_name is not None:
                text_input_overrides[self.TEXT_INPUT_NEW_NAME] = template_name
        if target_name_component.allow_description:
            text_input_overrides[self.TEXT_INPUT_NEW_DESCRIPTION] = None
            if self.target.has_custom_description():
                text_input_overrides[self.TEXT_INPUT_NEW_DESCRIPTION] = lambda *_, **__: LocalizationHelperTuning.get_object_description(self.target)
            elif template_description is not None:
                text_input_overrides[self.TEXT_INPUT_NEW_DESCRIPTION] = template_description
        dialog = self.rename_dialog(self.sim, self.get_resolver())
        dialog.show_dialog(on_response=on_response, text_input_overrides=text_input_overrides)
        return True

    def build_outcome(self):
        pass

    def _update_ui_metadata(self, updated_object):
        updated_object.update_ui_metadata()
        current_inventory = updated_object.get_inventory()
        if current_inventory is not None:
            current_inventory.push_inventory_item_update_msg(updated_object)

class ImposterSuperInteraction(SuperInteraction):
    __qualname__ = 'ImposterSuperInteraction'

    def __init__(self, *args, interaction_name=None, interaction_icon_info=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._old_interaction_name = interaction_name
        self._old_icon_info = interaction_icon_info

    @flexmethod
    def get_name(cls, inst, *args, **kwargs):
        if inst is not None:
            return inst._old_interaction_name
        return super().get_name(*args, **kwargs)

    @flexmethod
    def get_icon_info(cls, inst, *args, **kwargs):
        if inst is not None:
            return inst._old_icon_info
        return super().get_icon_info(*args, **kwargs)

    def _exited_pipeline(self):
        try:
            super()._exited_pipeline()
        finally:
            self._old_interaction_name = None
            self._old_icon_info = None

