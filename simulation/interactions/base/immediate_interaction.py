from types import SimpleNamespace
from interactions.base.basic import TunableBasicContentSet
from interactions.base.interaction import InteractionIntensity
from interactions.base.super_interaction import SuperInteraction
from interactions.utils.creation import ObjectCreationElement
from interactions.utils.destruction import ObjectDestructionElement
from interactions.utils.notification import NotificationElement
from interactions.utils.payment import PaymentElement
from interactions.utils.visual_effect import PlayVisualEffectElement
from objects.components.state import TunableStateChange
from sims.sim_outfits import TunableOutfitChange
from sims4 import commands
from sims4.tuning.instances import lock_instance_tunables
from sims4.tuning.tunable import TunableList, TunableVariant, Tunable
from sims4.utils import classproperty
from situations.tunable import CreateSituationElement
from tag import Tag

class ImmediateSuperInteraction(SuperInteraction):
    __qualname__ = 'ImmediateSuperInteraction'
    INSTANCE_TUNABLES = {'basic_content': TunableBasicContentSet(no_content=True, default='no_content'), 'basic_extras': TunableList(description='Additional elements to run around the basic content of the interaction.', tunable=TunableVariant(state_change=TunableStateChange(), create_situation=CreateSituationElement.TunableFactory(), create_object=ObjectCreationElement.TunableFactory(), notification=NotificationElement.TunableFactory(), payment=PaymentElement.TunableFactory(), destroy_object=ObjectDestructionElement.TunableFactory(), vfx=PlayVisualEffectElement.TunableFactory()))}

    @classproperty
    def immediate(cls):
        return True

lock_instance_tunables(ImmediateSuperInteraction, allow_autonomous=False, _cancelable_by_user=False, _must_run=True, visible=False, _constraints=[], basic_reserve_object=None, basic_focus=None, intensity=InteractionIntensity.Default, interaction_category_tags=frozenset([Tag.INVALID]), super_affordance_compatibility=None, animation_stat=None, _provided_posture_type=None, supported_posture_type_filter=[], force_autonomy_on_inertia=False, force_exit_on_inertia=False, pre_add_autonomy_commodities=[], pre_run_autonomy_commodities=[], post_guaranteed_autonomy_commodities=[], post_run_autonomy_commodities=SimpleNamespace(requests=[], fallback_notification=None), opportunity_cost_multiplier=1, autonomy_can_overwrite_similar_affordance=False, subaction_selection_weight=1, relationship_scoring=False, _party_size_weight_tuning=[], joinable=[], rallyable=None, autonomy_preference=None, outfit_priority=None, outfit_change=None, object_reservation_tests=[], cancel_replacement_affordances=None, privacy=None, provided_affordances=[], canonical_animation=None, ignore_group_socials=False)

class CommandSuperInteraction(ImmediateSuperInteraction):
    __qualname__ = 'CommandSuperInteraction'
    INSTANCE_TUNABLES = {'command': Tunable(str, None, description='The command to run.')}

    def _run_gen(self, timeline):
        if self.context.client is not None:
            if self.context.target_sim_id is not None:
                commands.execute('{} {}'.format(self.command, self.context.target_sim_id), self.context.client.id)
            else:
                commands.execute('{} {}'.format(self.command, self.target.id), self.context.client.id)
        else:
            commands.execute('{} {}'.format(self.command, self.target.id), None)
        return True
        yield None

class DebugRaiseExceptionImmediateSuperInteraction(ImmediateSuperInteraction):
    __qualname__ = 'DebugRaiseExceptionImmediateSuperInteraction'

    def _run_interaction_gen(self, timeline):
        raise RuntimeError('This is a forced error from DebugRaiseExceptionImmediateSuperInteraction')

class DebugTestExitBehaviorSuperInteraction(ImmediateSuperInteraction):
    __qualname__ = 'DebugTestExitBehaviorSuperInteraction'

    def _run_interaction_gen(self, timeline):

        def return_val(val):

            def f():
                return val

            return f

        def raise_exc(exc_type):

            def f():
                raise exc_type()

            return f

        self.add_exit_function(return_val(True))
        self.add_exit_function(return_val(False))
        self.add_exit_function(return_val(True))
        self.add_exit_function(return_val(False))
        self.add_exit_function(raise_exc(Exception))
        self.add_exit_function(raise_exc(BaseException))
        self.add_exit_function(raise_exc(Exception))
        self.add_exit_function(raise_exc(BaseException))
        self.add_exit_function(raise_exc(Exception))
        self.add_exit_function(raise_exc(BaseException))
        self.add_exit_function(raise_exc(Exception))
        self.add_exit_function(return_val(True))
        self.add_exit_function(return_val(False))
        self.add_exit_function(return_val(True))
        self.add_exit_function(return_val(False))
        return True

