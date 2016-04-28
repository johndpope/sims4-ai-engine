from protocolbuffers import Consts_pb2, InteractionOps_pb2
from types import SimpleNamespace
from animation.posture_manifest_constants import STAND_NO_CARRY_NO_SURFACE_POSTURE_MANIFEST
from clock import ClockSpeedMode
from element_utils import build_critical_section
from event_testing.results import TestResult
from interactions import ParticipantType
from interactions.aop import AffordanceObjectPair
from interactions.base.immediate_interaction import ImmediateSuperInteraction
from interactions.base.interaction import InteractionIntensity
from interactions.base.super_interaction import SuperInteraction
from interactions.base.tuningless_interaction import create_tuningless_superinteraction
from interactions.constraints import TunableWelcomeConstraint, TunableSpawnPoint
from interactions.context import InteractionContext
from interactions.utils.animation import flush_all_animations
from interactions.utils.tunable import SetGoodbyeNotificationElement
from objects import ALL_HIDDEN_REASONS
from sims.sim_outfits import OutfitCategory, SimOutfits
from sims4.localization import TunableLocalizedStringFactory
from sims4.tuning.instances import lock_instance_tunables
from sims4.tuning.tunable import TunableEnumEntry, TunableMapping, TunableReference, OptionalTunable, Tunable, TunableLotDescription
from sims4.tuning.tunable_base import GroupNames
from sims4.utils import flexmethod
from singletons import DEFAULT
from statistics import skill
from world import travel_service
from world.lot import get_lot_id_from_instance_id
from world.travel_tuning import TravelMixin, TRAVEL_SIM_LIABILITY, TravelSimLiability
import distributor
import services
import sims4.log
logger = sims4.log.Logger('Travel')

class TravelInteraction(SuperInteraction):
    __qualname__ = 'TravelInteraction'
    INSTANCE_TUNABLES = {'travel_xevt': OptionalTunable(description='\n            If enabled, specify an xevent at which the Sim will disappear from\n            the world.\n            ', tunable=Tunable(description='\n                The xevent at which the Sim will disappear from the world.\n                ', tunable_type=int, needs_tuning=False, default=100))}

    @classmethod
    def _define_supported_postures(cls):
        return STAND_NO_CARRY_NO_SURFACE_POSTURE_MANIFEST

    def __init__(self, aop, context, **kwargs):
        super().__init__(aop, context, **kwargs)
        self.from_zone_id = kwargs['from_zone_id']
        self.to_zone_id = kwargs['to_zone_id']
        self.on_complete_callback = kwargs['on_complete_callback']
        self.on_complete_context = kwargs['on_complete_context']
        self.force_save_and_destroy_sim = True

    def _setup_gen(self, timeline):
        if self.travel_xevt is not None:

            def on_travel_visuals(*_, **__):
                self.sim.remove_from_client()
                event_handler.release()

            event_handler = self.animation_context.register_event_handler(on_travel_visuals, handler_id=self.travel_xevt)
        result = yield super()._setup_gen(timeline)
        return result

    def run_pre_transition_behavior(self, *args, **kwargs):
        result = super().run_pre_transition_behavior(*args, **kwargs)
        if result:
            self.sim.set_allow_route_instantly_when_hitting_marks(False)
        return result

    def _run_interaction_gen(self, timeline):
        self.save_and_destroy_sim(False, self.sim.sim_info)

    def save_and_destroy_sim(self, on_reset, sim_info):
        if services.current_zone().is_zone_shutting_down:
            return
        from_zone_id = self.from_zone_id
        to_zone_id = self.to_zone_id
        callback = self.on_complete_callback
        context = self.on_complete_context

        def notify_travel_service():
            if services.travel_service().has_pending_travel(sim_info.account):
                travel_service.on_travel_interaction_succeeded(sim_info, from_zone_id, to_zone_id, callback, context)
            if not sim_info.is_npc:
                services.client_manager().get_first_client().send_selectable_sims_update()

        try:
            logger.debug('Saving sim during TravelInteraction for {}', sim_info)
            sim_info.inject_into_inactive_zone(self.to_zone_id)
            save_success = sim_info.save_sim()
            while not save_success:
                logger.error('Failure saving during TravelInteraction for {}', sim_info)
        finally:
            logger.debug('Destroying sim {}', sim_info)
            self.force_save_and_destroy_sim = False
            if on_reset:
                if self.sim is not None:
                    services.object_manager().remove(self.sim)
                notify_travel_service()
            elif self.sim is not None:
                self.sim.schedule_destroy_asap(source=self, cause='Destroying sim on travel.')

lock_instance_tunables(TravelInteraction, basic_reserve_object=None, basic_focus=None, allow_from_object_inventory=False, allow_from_sim_inventory=False, intensity=InteractionIntensity.Default, basic_liabilities=[], animation_stat=None, _provided_posture_type=None, supported_posture_type_filter=[], force_autonomy_on_inertia=False, force_exit_on_inertia=False, pre_add_autonomy_commodities=[], pre_run_autonomy_commodities=[], post_guaranteed_autonomy_commodities=[], post_run_autonomy_commodities=SimpleNamespace(requests=[], fallback_notification=None), opportunity_cost_multiplier=1, autonomy_can_overwrite_similar_affordance=False, subaction_selection_weight=1, relationship_scoring=False, _party_size_weight_tuning=[], joinable=[], rallyable=None, autonomy_preference=None, outfit_change=None, outfit_priority=None, object_reservation_tests=[], cancel_replacement_affordances=None, privacy=None, provided_affordances=[], canonical_animation=None, ignore_group_socials=False, utility_info=None, skill_loot_data=skill.EMPTY_SKILL_LOOT_DATA)

class GoToSpecificLotTravelInteraction(TravelInteraction):
    __qualname__ = 'GoToSpecificLotTravelInteraction'
    INSTANCE_TUNABLES = {'destination_lot': OptionalTunable(description="\n            If enabled, tune a specific lot description to be the destination\n            of the interaction.  Otherwise, the interaction will assume the\n            destination lot is the Sim's home lot.\n            ", tunable=TunableLotDescription(description='\n                The lot description of the destination lot.\n                '))}

    def __init__(self, aop, context, **kwargs):
        if self.destination_lot is None:
            zone_id = context.sim.household.home_zone_id
        else:
            lot_id = get_lot_id_from_instance_id(self.destination_lot)
            zone_id = services.get_persistence_service().resolve_lot_id_into_zone_id(lot_id, ignore_neighborhood_id=True)
        super().__init__(aop, context, from_zone_id=context.sim.zone_id, to_zone_id=zone_id, on_complete_callback=None, on_complete_context=None, **kwargs)

    def _run_interaction_gen(self, timeline):
        travel_info = InteractionOps_pb2.TravelSimsToZone()
        travel_info.zone_id = self.to_zone_id
        travel_info.sim_ids.append(self.sim.id)
        distributor.system.Distributor.instance().add_event(Consts_pb2.MSG_TRAVEL_SIMS_TO_ZONE, travel_info)
        services.game_clock_service().set_clock_speed(ClockSpeedMode.PAUSED)

class GoHomeTravelInteraction(TravelMixin, TravelInteraction):
    __qualname__ = 'GoHomeTravelInteraction'
    INSTANCE_TUNABLES = {'front_door_constraint': TunableWelcomeConstraint(description="\n            The Front Door Constraint for when the active lot is the Sim's home\n            lot.\n            ", radius=5.0, tuning_group=GroupNames.TRAVEL), 'home_spawn_point_constraint': TunableSpawnPoint(description="\n            This is the Spawn Point Constraint for when the Sim's home lot is\n            on the current street, but is not active. We should be tuning the\n            Arrival Spawner Tag(s) here.\n            ", tuning_group=GroupNames.TRAVEL), 'street_spawn_point_constraint': TunableSpawnPoint(description="\n            This is the Spawn Point Constraint for when the Sim's home lot is\n            not on the current street. We should likely be tuning Walkby\n            Spawner Tags here.\n            ", tuning_group=GroupNames.TRAVEL), 'attend_career': Tunable(description='\n            If set, Sim will automatically go to work after going home.\n            ', tunable_type=bool, default=False)}

    def __init__(self, aop, context, **kwargs):
        household = context.sim.household
        to_zone_id = household.home_zone_id if household is not None else 0
        super().__init__(aop, context, from_zone_id=context.sim.zone_id, to_zone_id=to_zone_id, on_complete_callback=None, on_complete_context=None, **kwargs)

    def should_fade_sim_out(self):
        home_zone_id = self.sim.household.home_zone_id
        if home_zone_id == services.current_zone_id():
            return False
        return True

    @classmethod
    def _test(cls, target, context, **kwargs):
        sim = context.sim
        test_result = super()._test(target, context, **kwargs)
        if not test_result:
            return test_result
        if target is not None and target is not sim:
            return TestResult(False, 'Self Interactions cannot target other Sims.')
        if sim.sim_info.is_npc or context.source == InteractionContext.SOURCE_AUTONOMY:
            return TestResult(False, 'Selectable Sims cannot go home autonomously.')
        test_result = cls.travel_test(context)
        if not test_result:
            return test_result
        zone = services.current_zone()
        home_zone_id = sim.household.home_zone_id
        if zone.id == home_zone_id and sim.intended_position_on_active_lot:
            return TestResult(False, 'Selectable Sims cannot go home if they are already at home.')
        return TestResult.TRUE

    @flexmethod
    def _constraint_gen(cls, inst, sim, target, *args, **kwargs):
        yield super()._constraint_gen(sim, target, *args, **kwargs)
        yield services.current_zone().get_spawn_point_ignore_constraint()
        inst_or_cls = inst if inst is not None else cls
        home_zone_id = sim.household.home_zone_id
        if home_zone_id == services.current_zone_id():
            active_lot = services.current_zone().lot
            if active_lot.front_door_id is not None:
                yield inst_or_cls.front_door_constraint.create_constraint(sim)
            else:
                yield inst_or_cls.home_spawn_point_constraint.create_constraint(sim, lot_id=active_lot.lot_id)
        else:
            persistence_service = services.get_persistence_service()
            zone_data = persistence_service.get_zone_proto_buff(home_zone_id)
            if zone_data.world_id == services.current_zone().world_id:
                home_lot_id = zone_data.lot_id
                yield inst_or_cls.home_spawn_point_constraint.create_constraint(sim, lot_id=home_lot_id)
            else:
                yield inst_or_cls.street_spawn_point_constraint.create_constraint(sim)

    def _run_interaction_gen(self, timeline):
        home_zone_id = self.sim.household.home_zone_id
        if home_zone_id == services.current_zone_id():
            return
        client = services.client_manager().get_first_client()
        expect_response = True
        for next_sim_info in client.selectable_sims:
            next_sim = next_sim_info.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)
            while next_sim is not self.sim and next_sim is not None:
                expect_response = False
        travel_liability = TravelSimLiability(self, self.sim.sim_info, self.to_zone_id, is_attend_career=self.attend_career)
        if expect_response:
            travel_liability.travel_player()
        else:
            self.add_liability(TRAVEL_SIM_LIABILITY, travel_liability)

    def on_reset(self):
        self.sim.fade_in()
        super().on_reset()

lock_instance_tunables(GoHomeTravelInteraction, fade_sim_out=True)

class NPCLeaveLotInteraction(TravelInteraction):
    __qualname__ = 'NPCLeaveLotInteraction'

    def __init__(self, aop, context, **kwargs):
        household = context.sim.household
        to_zone_id = household.home_zone_id if household is not None else 0
        super().__init__(aop, context, from_zone_id=context.sim.zone_id, to_zone_id=to_zone_id, on_complete_callback=None, on_complete_context=None, **kwargs)
        self.register_on_finishing_callback(self._on_finishing_callback)

    def run_pre_transition_behavior(self):
        actor = self.get_participant(ParticipantType.Actor)
        lot_owners = self.get_participants(ParticipantType.LotOwners)
        notification = actor.sim_info.goodbye_notification
        if notification not in (None, SetGoodbyeNotificationElement.NEVER_USE_NOTIFICATION_NO_MATTER_WHAT):
            for lot_owner in lot_owners:
                if not lot_owner.is_selectable:
                    pass
                resolver = self.get_resolver()
                dialog = notification(lot_owner, resolver=resolver)
                if dialog is not None:
                    dialog.show_dialog()
                break
            actor.sim_info.goodbye_notification = None
        return super().run_pre_transition_behavior()

    @classmethod
    def generate_aop(cls, target, context, **kwargs):
        return AffordanceObjectPair(cls, None, cls, None, **kwargs)

    @classmethod
    def _test(cls, target, context, **kwargs):
        if not context.sim.sim_info.is_npc:
            return TestResult(False, 'Only for NPCs.')
        return TestResult.TRUE

    def _on_finishing_callback(self, interaction):
        if self.transition_failed:
            services.get_zone_situation_manager().make_sim_leave_now_must_run(self.sim)
        self.unregister_on_finishing_callback(self._on_finishing_callback)

    @flexmethod
    def constraint_gen(cls, inst, sim, target, participant_type=ParticipantType.Actor):
        inst_or_cls = cls if inst is None else inst
        yield inst_or_cls._constraint_gen(sim, target, participant_type)

class OutfitMixin:
    __qualname__ = 'OutfitMixin'
    INSTANCE_TUNABLES = {'outfit_category_map': TunableMapping(key_type=TunableEnumEntry(OutfitCategory, OutfitCategory.EVERYDAY, description='The outfit category to pull outfit indexes from'), value_type=TunableReference(services.get_instance_manager(sims4.resources.Types.PIE_MENU_CATEGORY), description='Pie menu category so we can display a submenu for each outfit category')), 'current_outfit_tooltip': TunableLocalizedStringFactory(description='Greyed out tooltip that displays if the sim is currently wearing the selected outfit'), 'outfit_and_index_interaction_name': TunableLocalizedStringFactory(description='A string that concatenates the outfit category localized string and the number of the outfit category index')}

    def __init__(self, aop, context, pie_menu_category=None, outfit_category=None, outfit_index=None, **kwargs):
        super().__init__(aop, context, **kwargs)
        self.pie_menu_category = pie_menu_category
        self.outfit_category = outfit_category
        self.outfit_index = outfit_index

    @flexmethod
    def get_pie_menu_category(cls, inst, pie_menu_category=None, **interaction_parameters):
        if inst is not None:
            return inst.pie_menu_category
        return pie_menu_category

    @staticmethod
    def _get_interaction_name(cls, outfit_category, outfit_index):
        localized_string = SimOutfits.OUTFIT_CATEGORY_TUNING.get(outfit_category).localized_category
        if localized_string is not None:
            return cls.outfit_and_index_interaction_name(localized_string(), outfit_index + 1)

    @flexmethod
    def _get_name(cls, inst, target=DEFAULT, context=DEFAULT, outfit_category=None, outfit_index=None, **interaction_parameters):
        if inst is not None:
            return cls._get_interaction_name(cls, inst.outfit_category, inst.outfit_index)
        return cls._get_interaction_name(cls, outfit_category, outfit_index)

    @classmethod
    def _shared_test(cls, sim, outfit_category, outfit_index):
        requested_outfit = (outfit_category, outfit_index)
        if sim.sim_info.get_current_outfit() == requested_outfit:
            return TestResult(False, 'Already in requested outfit', tooltip=cls.current_outfit_tooltip)
        return TestResult.TRUE

    @classmethod
    def _shared_potential_interactions(cls, sim, target, **kwargs):
        if sim is None:
            return
        outfit_category_map = cls.outfit_category_map
        for outfit_category in outfit_category_map:
            pie_menu_category = outfit_category_map[outfit_category]
            outfits = sim.sim_info.sim_outfits.outfits_in_category(outfit_category)
            index = 0
            while outfits is not None:
                while True:
                    for _ in outfits:
                        yield AffordanceObjectPair(cls, target, cls, None, pie_menu_category=pie_menu_category, outfit_category=outfit_category, outfit_index=index, **kwargs)
                        index += 1

class ChangeOutfitInteraction(OutfitMixin, SuperInteraction):
    __qualname__ = 'ChangeOutfitInteraction'

    def build_basic_elements(self, sequence=()):
        sequence = super().build_basic_elements(sequence=sequence)
        outfit_category_and_index = (self.outfit_category, self.outfit_index)
        exit_change = build_critical_section(sequence, self.sim.sim_info.sim_outfits.get_change_outfit_element(outfit_category_and_index, do_spin=True), flush_all_animations)
        return exit_change

    @classmethod
    def _test(cls, target, context, outfit_category=None, outfit_index=None, **kwargs):
        test_result = super()._test(target, context, **kwargs)
        if not test_result:
            return test_result
        return cls._shared_test(context.sim, outfit_category, outfit_index)

    @classmethod
    def potential_interactions(cls, target, context, **kwargs):
        change_outfit_target = None if context.sim is target else target
        return cls._shared_potential_interactions(context.sim, change_outfit_target)

    def add_preload_outfit_changes(self, final_preload_outfit_set):
        super().add_preload_outfit_changes(final_preload_outfit_set)
        final_preload_outfit_set.add((self.outfit_category, self.outfit_index))

class ChangeOtherSimsOutfitInteraction(OutfitMixin, ImmediateSuperInteraction):
    __qualname__ = 'ChangeOtherSimsOutfitInteraction'

    @classmethod
    def _test(cls, target, context, outfit_category=None, outfit_index=None, **kwargs):
        test_result = super()._test(target, context, **kwargs)
        if not test_result:
            return test_result
        return cls._shared_test(target, outfit_category, outfit_index)

    @classmethod
    def potential_interactions(cls, target, context, **kwargs):
        return cls._shared_potential_interactions(target, target)

    def _run_interaction_gen(self, timeline):
        target = self.target
        target.sim_info.set_current_outfit((self.outfit_category, self.outfit_index))

class AnimationInteraction(SuperInteraction):
    __qualname__ = 'AnimationInteraction'
    INSTANCE_SUBCLASSES_ONLY = True

    def __init__(self, *args, hide_unrelated_held_props=True, **kwargs):
        super().__init__(*args, **kwargs)
        self._hide_unrelated_held_props = hide_unrelated_held_props

    @property
    def animation_context(self):
        animation_liability = self.get_animation_context_liability()
        return animation_liability.animation_context

create_tuningless_superinteraction(AnimationInteraction)
