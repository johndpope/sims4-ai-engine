from autonomy.autonomy_modifier import AutonomyModifier
from event_testing.tests import TunableTestSet
from interactions import ParticipantType
from interactions.context import InteractionContext
from interactions.priority import Priority
from sims4.tuning.tunable import AutoFactoryInit, HasTunableSingletonFactory, TunableReference, TunableVariant, OptionalTunable, TunableEnumEntry, Tunable, TunablePercent, TunableList
from sims4.utils import classproperty
import buffs.tunable
import random
import services
import sims4.resources

class TunableBroadcasterEffectVariant(TunableVariant):
    __qualname__ = 'TunableBroadcasterEffectVariant'

    def __init__(self, **kwargs):
        super().__init__(affordance=BroadcasterEffectAffordance.TunableFactory(), buff=BroadcasterEffectBuff.TunableFactory(), statistic_modifier=BroadcasterEffectStatisticModifier.TunableFactory(), self_state_change=BroadcasterEffectSelfStateChange.TunableFactory(), start_fire=BroadcasterEffectStartFire.TunableFactory(), loot=BroadcasterEffectLoot.TunableFactory(), **kwargs)

class _BroadcasterEffect(AutoFactoryInit, HasTunableSingletonFactory):
    __qualname__ = '_BroadcasterEffect'

    @classproperty
    def apply_when_linked(cls):
        return False

    def register_static_callbacks(self, broadcaster_request_owner):
        pass

    def apply_broadcaster_effect(self, broadcaster, affected_object):
        pass

    def remove_broadcaster_effect(self, broadcaster, affected_object):
        pass

class _BroadcasterEffectTested(_BroadcasterEffect):
    __qualname__ = '_BroadcasterEffectTested'
    FACTORY_TUNABLES = {'tests': TunableTestSet(description='\n            Tests that must pass in order for the broadcaster effect to be\n            applied.\n            ')}

    def apply_broadcaster_effect(self, broadcaster, affected_object):
        resolver = broadcaster.get_resolver(affected_object)
        if self.tests.run_tests(resolver):
            return self._apply_broadcaster_effect(broadcaster, affected_object)

    def _apply_broadcaster_effect(self, broadcaster, affected_object):
        raise NotImplementedError

class BroadcasterEffectBuff(_BroadcasterEffectTested):
    __qualname__ = 'BroadcasterEffectBuff'
    FACTORY_TUNABLES = {'buff': buffs.tunable.TunableBuffReference(description='\n            The buff to apply while the broadcaster actively affects the Sim.\n            ')}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._buff_handles = {}

    @classproperty
    def apply_when_linked(cls):
        return True

    def _apply_broadcaster_effect(self, broadcaster, affected_object):
        if not affected_object.is_sim:
            return
        key = (affected_object.id, broadcaster.broadcaster_id)
        if key not in self._buff_handles:
            handle_id = affected_object.add_buff(self.buff.buff_type, buff_reason=self.buff.buff_reason)
            if handle_id:
                self._buff_handles[key] = handle_id

    def remove_broadcaster_effect(self, broadcaster, affected_object):
        if not affected_object.is_sim:
            return
        key = (affected_object.id, broadcaster.broadcaster_id)
        if key in self._buff_handles:
            affected_object.remove_buff(self._buff_handles[key])
            del self._buff_handles[key]

class BroadcasterEffectAffordance(_BroadcasterEffectTested):
    __qualname__ = 'BroadcasterEffectAffordance'
    FACTORY_TUNABLES = {'affordance': TunableReference(description='\n            The affordance to push on Sims affected by the broadcaster.\n            ', manager=services.affordance_manager()), 'affordance_target': OptionalTunable(description='\n            If enabled, the pushed interaction will target a specified\n            participant.\n            ', tunable=TunableEnumEntry(description='\n                The participant to be targeted by the pushed interaction.\n                ', tunable_type=ParticipantType, default=ParticipantType.Object), enabled_by_default=True), 'affordance_priority': TunableEnumEntry(description='\n            The priority at which the specified affordance is to be pushed.\n            ', tunable_type=Priority, default=Priority.Low), 'affordance_run_priority': OptionalTunable(description="\n            If enabled, specify the priority at which the affordance runs. This\n            may be different than 'affordance_priority'. For example. you might\n            want an affordance to push at high priority such that it cancels\n            existing interactions, but it runs at a lower priority such that it\n            can be more easily canceled.\n            ", tunable=TunableEnumEntry(description='\n                The run priority for the specified affordance.\n                ', tunable_type=Priority, default=Priority.Low)), 'affordance_must_run_next': Tunable(description="\n            If set, the affordance will be inserted at the beginning of the\n            Sim's queue.\n            ", tunable_type=bool, default=False)}

    def register_static_callbacks(self, broadcaster_request_owner):
        register_privacy_callback = getattr(broadcaster_request_owner, 'register_sim_can_violate_privacy_callback', None)
        if register_privacy_callback is not None:
            register_privacy_callback(self._on_privacy_violation)

    def _on_privacy_violation(self, interaction, sim):
        (affordance_target, context) = self._get_target_and_context(interaction.get_resolver(), sim)
        return sim.test_super_affordance(self.affordance, affordance_target, context)

    def _get_target_and_context(self, resolver, affected_object):
        affordance_target = resolver.get_participant(self.affordance_target) if self.affordance_target is not None else None
        if affordance_target is not None and affordance_target.is_sim:
            affordance_target = affordance_target.get_sim_instance()
        context = InteractionContext(affected_object, InteractionContext.SOURCE_SCRIPT, self.affordance_priority, run_priority=self.affordance_run_priority, must_run_next=self.affordance_must_run_next)
        return (affordance_target, context)

    def _apply_broadcaster_effect(self, broadcaster, affected_object):
        if not affected_object.is_sim:
            return
        if broadcaster.interaction is not None:
            participants = broadcaster.interaction.get_participants(ParticipantType.AllSims)
            if affected_object in participants:
                return
        (affordance_target, context) = self._get_target_and_context(broadcaster.get_resolver(affected_object), affected_object)
        affected_object.push_super_affordance(self.affordance, affordance_target, context)

class BroadcasterEffectStatisticModifier(_BroadcasterEffectTested):
    __qualname__ = 'BroadcasterEffectStatisticModifier'
    FACTORY_TUNABLES = {'statistic': TunableReference(description='\n            The statistic to be affected by the modifier.\n            ', manager=services.statistic_manager()), 'modifier': Tunable(description='\n            The modifier to apply to the tuned statistic.\n            ', tunable_type=float, default=0)}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._modifier_handles = {}

    @classproperty
    def apply_when_linked(cls):
        return True

    def _apply_broadcaster_effect(self, broadcaster, affected_object):
        key = (affected_object.id, broadcaster.broadcaster_id)
        if key not in self._modifier_handles:
            autonomy_modifier = AutonomyModifier(statistic_modifiers={self.statistic: self.modifier})
            handle_id = affected_object.add_statistic_modifier(autonomy_modifier)
            if handle_id:
                self._modifier_handles[key] = handle_id

    def remove_broadcaster_effect(self, broadcaster, affected_object):
        key = (affected_object.id, broadcaster.broadcaster_id)
        if key in self._modifier_handles:
            affected_object.remove_statistic_modifier(self._modifier_handles[key])
            del self._modifier_handles[key]

class BroadcasterEffectSelfStateChange(_BroadcasterEffectTested):
    __qualname__ = 'BroadcasterEffectSelfStateChange'
    FACTORY_TUNABLES = {'enter_state_value': TunableReference(description='\n                                    The state value to enter when first object gets close\n                                    ', manager=services.get_instance_manager(sims4.resources.Types.OBJECT_STATE), class_restrictions='ObjectStateValue'), 'exit_state_value': TunableReference(description='\n                                    The state value to enter when last object leaves\n                                    ', manager=services.get_instance_manager(sims4.resources.Types.OBJECT_STATE), class_restrictions='ObjectStateValue')}

    @classproperty
    def apply_when_linked(cls):
        return True

    def _apply_broadcaster_effect(self, broadcaster, affected_object):
        if broadcaster.get_affected_object_count() == 1:
            broadcasting_object = broadcaster.broadcasting_object
            if broadcasting_object is not None:
                state_value = self.enter_state_value
                broadcasting_object.set_state(state_value.state, state_value)

    def remove_broadcaster_effect(self, broadcaster, affected_object):
        if broadcaster.get_affected_object_count() == 0:
            broadcasting_object = broadcaster.broadcasting_object
            if broadcasting_object is not None:
                state_value = self.exit_state_value
                broadcasting_object.set_state(state_value.state, state_value)

class BroadcasterEffectStartFire(_BroadcasterEffectTested):
    __qualname__ = 'BroadcasterEffectStartFire'
    FACTORY_TUNABLES = {'percent_chance': TunablePercent(description='\n            A value between 0 - 100 which represents the percent chance to \n            start a fire when reacting to the broadcaster.\n            ', default=50)}

    def _apply_broadcaster_effect(self, broadcaster, affected_object):
        if random.random() <= self.percent_chance:
            fire_service = services.get_fire_service()
            fire_service.spawn_fire_at_object(affected_object)

class BroadcasterEffectLoot(_BroadcasterEffectTested):
    __qualname__ = 'BroadcasterEffectLoot'
    FACTORY_TUNABLES = {'loot_list': TunableList(description='\n            A list of loot operations.\n            ', tunable=TunableReference(manager=services.get_instance_manager(sims4.resources.Types.ACTION), class_restrictions=('LootActions',)))}

    def _apply_broadcaster_effect(self, broadcaster, affected_object):
        resolver = broadcaster.get_resolver(affected_object)
        for loot_action in self.loot_list:
            loot_action.apply_to_resolver(resolver)

