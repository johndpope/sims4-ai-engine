from autonomy.autonomy_modes import FullAutonomy
from autonomy.autonomy_request import AutonomyRequest
from interactions.aop import AffordanceObjectPair
from interactions.context import QueueInsertStrategy, InteractionContext
from interactions.priority import Priority
from objects.base_interactions import ProxyInteraction
from sims.party import Party
from sims4.utils import classproperty, flexmethod
from singletons import DEFAULT
import services

class RallyInteraction(ProxyInteraction):
    __qualname__ = 'RallyInteraction'
    INSTANCE_SUBCLASSES_ONLY = True

    @classproperty
    def proxy_name(cls):
        return '[Rally]'

    def __init__(self, *args, from_rally_interaction=None, push_social=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._rally_targets = None
        self._from_rally_interaction = from_rally_interaction
        self._push_social = push_social

    @classmethod
    def generate(cls, proxied_affordance, rally_tag, rally_level, rally_data, rally_push_social=None, rally_constraint=None):
        rally_affordance = proxied_affordance
        result = super().generate(rally_affordance)
        result.rally_tag = rally_tag
        result.rally_level = rally_level
        result.rally_data = rally_data
        result.rally_push_social = rally_push_social
        result.rally_constraint = rally_constraint
        return result

    @classmethod
    def potential_interactions(cls, target, context, **kwargs):
        yield AffordanceObjectPair(cls, target, cls, None, **kwargs)

    @classmethod
    def generate_continuation_affordance(cls, affordance, **kwargs):
        return RallyInteraction.generate(affordance, rally_tag=cls.rally_tag, rally_level=cls.rally_level + 1, rally_data=None, **kwargs)

    @flexmethod
    def _get_name(cls, inst, target=DEFAULT, context=DEFAULT, **kwargs):
        if inst is not None or cls.rally_data is None:
            return super(ProxyInteraction, inst)._get_name(target=target, context=context, **kwargs)
        original_name = super(ProxyInteraction, cls)._get_name(target=target, context=context, **kwargs)
        return cls.rally_data.loc_display_name(original_name)

    @classmethod
    def autonomy_ads_gen(cls, *args, **kwargs):
        for op in Party.RALLY_FALSE_ADS:
            cls._add_autonomy_ad(op, overwrite=False)
        for ad in super().autonomy_ads_gen(*args, **kwargs):
            yield ad
        for op in Party.RALLY_FALSE_ADS:
            cls._remove_autonomy_ad(op)

    @classmethod
    def _constraint_gen(cls, *args, **kwargs):
        for constraint in super()._constraint_gen(*args, **kwargs):
            yield constraint
        if cls.rally_constraint is not None:
            yield cls.rally_constraint

    def _run_interaction_gen(self, timeline):
        main_group = self.sim.get_visible_group()
        if self._push_social is not None and main_group is None:
            context = InteractionContext(self.sim, InteractionContext.SOURCE_SCRIPT, self.context.priority)
            self.sim.push_super_affordance(self._push_social, self._from_rally_interaction.sim, context)
        yield super()._run_interaction_gen(timeline)

    def disable_displace(self, other):
        if isinstance(other, RallyInteraction):
            return self._from_rally_interaction is other or other._from_rally_interaction is self
        return False

    def excluded_posture_destination_objects(self):
        excluded = set()
        if self._from_rally_interaction is None or self._from_rally_interaction.transition is None:
            return excluded
        for dest in self._from_rally_interaction.transition.final_destinations_gen():
            while dest.body_target is not None:
                excluded.add(dest.body_target)
        return excluded

    def _get_rally_affordance(self):
        affordance = self.rally_data.affordance
        if affordance is None:
            return self.proxied_affordance
        return affordance or None

    def _get_rally_affordance_target(self):
        affordance_target_type = self.rally_data.affordance_target
        if affordance_target_type is not None:
            return self.get_participant(affordance_target_type)
        return affordance_target_type

    def _get_rally_static_commodity(self):
        return self.rally_data.static_commodity

    def _do_rally_behavior(self, sim, constraint):
        if self.rally_data is not None:
            target = None
            if self.rally_constraint is not None:
                constraint = self.rally_constraint
            context = self.context.clone_for_sim(sim, insert_strategy=QueueInsertStrategy.NEXT)
            affordance = self._get_rally_affordance()
            context.run_priority = Priority.Low
            if affordance is None:
                static_commodity = self._get_rally_static_commodity()
                if static_commodity is not None:
                    request = AutonomyRequest(sim, static_commodity_list=(static_commodity,), skipped_static_commodities=None, object_list=self._rally_targets, constraint=constraint, context=context, autonomy_mode=FullAutonomy, autonomy_mode_label_override='RallyBehavior')
                    autonomy_result = services.autonomy_service().score_all_interactions(request)
                    if self._rally_targets is None:
                        self._rally_targets = {}
                        for scored_interaction_data in autonomy_result:
                            num_possible_parts = 0
                            possible_target = scored_interaction_data.interaction.target
                            if possible_target is not None and possible_target.parts is not None:
                                for part in possible_target.parts:
                                    while not part.in_use or part.in_use_by(sim):
                                        if part.supports_affordance(scored_interaction_data.interaction.affordance):
                                            num_possible_parts = num_possible_parts + 1
                            else:
                                num_possible_parts = 1
                            if self.target == possible_target:
                                num_possible_parts = num_possible_parts - 1
                            while num_possible_parts > 0:
                                self._rally_targets[possible_target] = num_possible_parts
                    appropriate_scored_interactons = tuple([scored_interaction_data for scored_interaction_data in autonomy_result if scored_interaction_data.interaction.target in self._rally_targets])
                    chosen_interaction = services.autonomy_service().choose_best_interaction(appropriate_scored_interactons, request)
                    request.invalidate_created_interactions(excluded_si=chosen_interaction)
                    affordance = chosen_interaction.affordance
                    target = chosen_interaction.target
                    if target is not None:
                        num_parts_remaining = self._rally_targets.get(target, 1) - 1
                        if num_parts_remaining <= 0:
                            del self._rally_targets[target]
                        else:
                            self._rally_targets[target] = num_parts_remaining
                        return False
                else:
                    return False
            else:
                target = self._get_rally_affordance_target()
                if target is not None and target.is_part:
                    for adjacent_part in target.adjacent_parts_gen():
                        while adjacent_part.may_reserve(sim, affordance=self, context=self.context) and adjacent_part.supports_posture_type(affordance.provided_posture_type, interaction=affordance):
                            target = adjacent_part
                            break
                    target = target.part_owner
            if affordance is not None:
                affordance = self.generate_continuation_affordance(affordance, rally_constraint=constraint)
                return sim.push_super_affordance(affordance, target, context, from_rally_interaction=self, push_social=self.rally_push_social, **self.interaction_parameters)
        return False

    def maybe_bring_group_along(self, **kwargs):
        if not self.should_rally:
            return
        anchor_object = self.target
        if anchor_object is not None and anchor_object.is_part:
            anchor_object = anchor_object.part_owner
        main_group = self.sim.get_visible_group()
        if main_group:
            if not main_group.try_relocate_around_focus(self.sim, priority=self.priority):
                return
            for sim in list(main_group):
                while sim is not self.sim:
                    self._do_rally_behavior(sim, main_group.get_constraint(sim))

    @property
    def should_rally(self):
        main_group = self.sim.get_visible_group()
        if self._from_rally_interaction is None and main_group is not None and not main_group.is_solo:
            return True
        return False

