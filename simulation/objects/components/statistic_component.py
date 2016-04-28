import itertools
import weakref
from protocolbuffers import SimObjectAttributes_pb2 as persistence_protocols
from interactions.interaction_finisher import FinishingType
from objects.components import Component, componentmethod, types, componentmethod_with_fallback
from objects.components.statistic_types import StatisticComponentGlobalTuning
from element_utils import build_critical_section_with_finally
from protocolbuffers import SimObjectAttributes_pb2 as persistence_protocols
import autonomy.autonomy_modifier
import interactions.context
import services.reset_and_delete_service
import sims4.log
import statistics.base_statistic_tracker
import statistics.commodity_tracker
import statistics.static_commodity
import statistics.statistic
import statistics.statistic_tracker
import uid
logger = sims4.log.Logger('StatisticComponent')

class HasStatisticComponent:
    __qualname__ = 'HasStatisticComponent'

    def add_statistic_component(self):
        statcomp = self.get_component(types.STATISTIC_COMPONENT)
        if not statcomp:
            self.add_dynamic_component(types.STATISTIC_COMPONENT.instance_attr)
            statcomp = self.get_component(types.STATISTIC_COMPONENT)
        statcomp.get_statistic_tracker()
        statcomp.get_commodity_tracker()
        statcomp.get_static_commodity_tracker()

    def get_tracker(self, stat):
        statcomp = self.get_component(types.STATISTIC_COMPONENT)
        if not statcomp:
            self.add_dynamic_component(types.STATISTIC_COMPONENT.instance_attr)
            statcomp = self.get_component(types.STATISTIC_COMPONENT)
        return statcomp.get_tracker(stat)

    @property
    def statistic_tracker(self):
        statcomp = self.get_component(types.STATISTIC_COMPONENT)
        if not statcomp:
            self.add_dynamic_component(types.STATISTIC_COMPONENT.instance_attr)
            statcomp = self.get_component(types.STATISTIC_COMPONENT)
        return statcomp.get_statistic_tracker()

    @property
    def commodity_tracker(self):
        statcomp = self.get_component(types.STATISTIC_COMPONENT)
        if not statcomp:
            self.add_dynamic_component(types.STATISTIC_COMPONENT.instance_attr)
            statcomp = self.get_component(types.STATISTIC_COMPONENT)
        return statcomp.get_commodity_tracker()

    @property
    def static_commodity_tracker(self):
        statcomp = self.get_component(types.STATISTIC_COMPONENT)
        if not statcomp:
            self.add_dynamic_component(types.STATISTIC_COMPONENT.instance_attr)
            statcomp = self.get_component(types.STATISTIC_COMPONENT)
        return statcomp.get_static_commodity_tracker()

class AutonomyModifierEntry:
    __qualname__ = 'AutonomyModifierEntry'

    def __init__(self, autonomy_modifier):
        self._autonomy_modifier = autonomy_modifier
        self.statistic_modifiers = []
        self.statistic_multipliers = []

    @property
    def autonomy_modifier(self):
        return self._autonomy_modifier

class StatisticComponent(Component, component_name=types.STATISTIC_COMPONENT, allow_dynamic=True, persistence_key=persistence_protocols.PersistenceMaster.PersistableData.StatisticComponent, persistence_priority=10):
    __qualname__ = 'StatisticComponent'

    def __init__(self, owner):
        super().__init__(owner)
        self._get_next_statistic_handle = uid.UniqueIdGenerator(1)
        self._statistic_modifiers = {}
        self._locked_commodities = {}
        self._relationship_score_multiplier_with_buff_on_target = None
        self._commodity_tracker = None
        self._static_commodity_tracker = None
        self._statistic_tracker = None
        self._commodity_distress_refs = []
        self._commodities_added = {}
        self._interaction_modifiers = {}
        self._suspended_modifiers = {}

    def get_statistic_tracker(self):
        if self._statistic_tracker is None:
            self.create_statistic_tracker()
        return self._statistic_tracker

    def get_commodity_tracker(self):
        if self._commodity_tracker is None:
            self._commodity_tracker = statistics.commodity_tracker.CommodityTracker(self.owner)
        return self._commodity_tracker

    def get_static_commodity_tracker(self):
        if self._static_commodity_tracker is None:
            self._static_commodity_tracker = statistics.base_statistic_tracker.BaseStatisticTracker()
        return self._static_commodity_tracker

    @componentmethod_with_fallback(lambda : ())
    def get_all_stats_gen(self):
        if self._statistic_tracker is not None:
            yield self._statistic_tracker
        if self._commodity_tracker is not None:
            yield self._commodity_tracker
        if self._static_commodity_tracker is not None:
            yield self._static_commodity_tracker

    @componentmethod_with_fallback(lambda _: False)
    def is_statistic_type_added_by_modifier(self, statistic_type):
        return statistic_type in self._commodities_added

    @componentmethod
    def create_statistic_tracker(self):
        self._statistic_tracker = statistics.statistic_tracker.StatisticTracker(self.owner)

    @componentmethod
    def get_tracker(self, stat):
        if stat is None:
            return
        stat = stat.stat_type
        if issubclass(stat, statistics.static_commodity.StaticCommodity):
            return self.get_static_commodity_tracker()
        if issubclass(stat, statistics.statistic.Statistic):
            return self.get_statistic_tracker()
        if stat.continuous:
            return self.get_commodity_tracker()

    @componentmethod
    def get_stat_instance(self, stat_type, **kwargs):
        tracker = self.get_tracker(stat_type)
        if tracker is not None:
            return tracker.get_statistic(stat_type, **kwargs)

    @componentmethod
    def get_stat_value(self, stat_type):
        tracker = self.get_tracker(stat_type)
        if tracker is not None:
            return tracker.get_value(stat_type)

    @componentmethod
    def set_stat_value(self, stat_type, *args, **kwargs):
        tracker = self.get_tracker(stat_type)
        if tracker is not None:
            tracker.set_value(stat_type, *args, **kwargs)

    @componentmethod_with_fallback(lambda : False)
    def update_all_commodities(self):
        if self._commodity_tracker is not None:
            self._commodity_tracker.update_all_commodities()

    def _build_stat_sequence(self, participant, modifier, sequence):
        handle = None
        participant_ref = weakref.ref(participant)

        def _begin(_):
            nonlocal handle
            handle = participant.add_statistic_modifier(modifier, True)

        def _end(_):
            if handle:
                participant_deref = participant_ref()
                if participant_deref is not None:
                    return participant_deref.remove_statistic_modifier(handle)

        return build_critical_section_with_finally(_begin, sequence, _end)

    @componentmethod_with_fallback(lambda _, sequence: sequence)
    def add_modifiers_for_interaction(self, interaction, sequence):
        for modifier in self._interaction_modifiers:
            participants = interaction.get_participants(self._interaction_modifiers[modifier]._subject)
            for participant in participants:
                sequence = self._build_stat_sequence(participant, self._interaction_modifiers[modifier], sequence)
        return sequence

    @componentmethod_with_fallback(lambda *_, **__: None)
    def add_statistic_modifier(self, modifier, interaction_modifier=False, requested_handle=None):
        is_interaction_modifier = modifier._subject and not interaction_modifier
        if requested_handle and (is_interaction_modifier and requested_handle in self._interaction_modifiers or requested_handle in self._statistic_modifiers):
            logger.warn('Trying to add a modifier with a requested handle that already exists. Generating a new handle. - trevorlindsey')
            requested_handle = None
        handle = self._get_next_statistic_handle() if requested_handle is None else requested_handle
        if is_interaction_modifier:
            self._interaction_modifiers[handle] = modifier
            return handle
        if interaction_modifier and any(modifier is autonomy_modifier_entry.autonomy_modifier for autonomy_modifier_entry in self._statistic_modifiers.values()):
            return
        autonomy_modifier_entry = AutonomyModifierEntry(modifier)
        self._statistic_modifiers[handle] = autonomy_modifier_entry
        for commodity_type in modifier.commodities_to_add:
            if commodity_type is None:
                logger.warn('{} has empty stat in commodities add list. Please fix tuning.', modifier)
            tracker = self.get_tracker(commodity_type)
            if not tracker.has_statistic(commodity_type):
                tracker.add_statistic(commodity_type)
            if commodity_type not in self._commodities_added:
                self._commodities_added[commodity_type] = 1
            else:
                self._commodities_added[commodity_type] += 1
        if modifier.override_convergence is not None:
            for (commodity_to_override, convergence_value) in modifier.override_convergence.items():
                tracker = self.get_tracker(commodity_to_override)
                tracker.set_convergence(commodity_to_override, convergence_value)
        for stat_type in modifier.locked_stats_gen():
            if stat_type in self._locked_commodities:
                self._locked_commodities[stat_type] += 1
            else:
                stat = self._commodity_tracker.get_statistic(stat_type, stat_type.add_if_not_in_tracker)
                if stat is not None:
                    stat.decay_enabled = False
                    if not interaction_modifier:
                        stat.set_value(stat.max_value)
                    stat.send_commodity_progress_msg()
                    self._locked_commodities[stat_type] = 1
                else:
                    logger.error("Attempting to lock commodity {} that doesn't exist on object: {}", stat_type, self)
        if modifier.decay_modifiers:
            for (stat_type, decay_modifiers) in modifier.decay_modifiers.items():
                stat = self._commodity_tracker.get_statistic(stat_type, stat_type.add_if_not_in_tracker)
                if stat is not None:
                    stat.add_decay_rate_modifier(decay_modifiers)
                    stat.send_commodity_progress_msg()
                elif self.owner.is_sim:
                    self.owner.log_sim_info(logger.error, additional_msg="Attempting to add a decay rate modifier for a commodity {} that doesn't exist on object: {}".format(stat_type, self.owner))
                else:
                    logger.error("Attempting to add a decay rate modifier for a commodity {} that doesn't exist on object: {}", stat_type, self.owner)
        if modifier.statistic_modifiers:
            for (stat_type, statistic_modifier) in modifier.statistic_modifiers.items():
                tracker = self.get_tracker(stat_type)
                stat = tracker.get_statistic(stat_type, stat_type.add_if_not_in_tracker)
                while stat is not None and stat_type not in self._locked_commodities:
                    stat.add_statistic_modifier(statistic_modifier)
                    autonomy_modifier_entry.statistic_modifiers.append(stat_type)
        self._relationship_score_multiplier_with_buff_on_target = modifier.relationship_score_multiplier_with_buff_on_target
        if modifier.statistic_multipliers:
            for (stat_type, statistic_multiplier) in modifier.statistic_multipliers.items():
                tracker = self.get_tracker(stat_type)
                stat = tracker.get_statistic(stat_type, stat_type.add_if_not_in_tracker)
                while stat is not None:
                    stat.add_statistic_multiplier(statistic_multiplier)
                    autonomy_modifier_entry.statistic_multipliers.append(stat_type)
        if self.owner.is_sim:
            if modifier.super_affordance_suppress_on_add:
                sim_instance = self.owner.get_sim_instance()
                if sim_instance is not None:
                    while True:
                        for interaction in itertools.chain(sim_instance.si_state, sim_instance.queue):
                            while modifier.affordance_suppressed(sim_instance, interaction):
                                interaction.cancel(FinishingType.INTERACTION_INCOMPATIBILITY, cancel_reason_msg='Modifier suppression')
            sim_skill_list = list(self.owner.skills_gen())

            def skill_with_tag_gen(tag):
                for skill in sim_skill_list:
                    while tag in skill.tags:
                        yield skill

            for (skill_tag, skill_modifier) in modifier.skill_tag_modifiers.items():
                for found_skill in skill_with_tag_gen(skill_tag):
                    found_skill.add_statistic_multiplier(skill_modifier)
            self.owner.relationship_tracker.add_relationship_multipliers(handle, modifier.relationship_multipliers)
        return handle

    def add_statistic_multiplier(self, modifier, subject):
        if modifier.statistic_multipliers:
            for (stat_type, statistic_multiplier) in modifier.statistic_multipliers.items():
                if subject is not None and subject != statistic_multiplier.subject:
                    pass
                tracker = self.get_tracker(stat_type)
                stat = tracker.get_statistic(stat_type, stat_type.add_if_not_in_tracker)
                while stat is not None:
                    stat.add_statistic_multiplier(statistic_multiplier)

    @componentmethod
    def remove_statistic_modifier(self, handle):
        if handle in self._interaction_modifiers:
            del self._interaction_modifiers[handle]
            return True
        if handle in self._suspended_modifiers:
            del self._suspended_modifiers[handle]
            return True
        if handle in self._statistic_modifiers:
            if self.owner.id == 0:
                return True
            autonomy_modifier_entry = self._statistic_modifiers[handle]
            modifier = autonomy_modifier_entry.autonomy_modifier
            for stat_type in modifier.locked_stats_gen():
                if stat_type in self._locked_commodities:
                    if self._locked_commodities[stat_type] <= 1:
                        stat = self._commodity_tracker.get_statistic(stat_type)
                        if stat is not None:
                            stat.decay_enabled = True
                            stat.send_commodity_progress_msg()
                        else:
                            logger.error("Attempting to unlock commodity that doesn't exist on object {}: {}", self.owner, stat_type)
                        del self._locked_commodities[stat_type]
                    else:
                        self._locked_commodities[stat_type] -= 1
                        logger.error("Locked commodity doesn't exist in the _locked_commodities dict: object {}, stat {}", self.owner, stat_type)
                else:
                    logger.error("Locked commodity doesn't exist in the _locked_commodities dict: object {}, stat {}", self.owner, stat_type)
            if modifier.decay_modifiers:
                for (stat_type, decay_modifier) in modifier.decay_modifiers.items():
                    stat = self._commodity_tracker.get_statistic(stat_type)
                    if stat is not None:
                        stat.remove_decay_rate_modifier(decay_modifier)
                        stat.send_commodity_progress_msg()
                    else:
                        while not stat_type.remove_on_convergence:
                            logger.error("Attempting to remove a decay rate modifier for a commodity that doesn't exist on object {}: {}", self.owner, stat_type)
            if modifier.statistic_modifiers:
                for (stat_type, statistic_modifier) in modifier.statistic_modifiers.items():
                    if stat_type not in autonomy_modifier_entry.statistic_modifiers:
                        pass
                    tracker = self.get_tracker(stat_type)
                    stat = tracker.get_statistic(stat_type)
                    if stat is not None:
                        stat.remove_statistic_modifier(statistic_modifier)
                    else:
                        while stat_type.add_if_not_in_tracker and not stat_type.remove_on_convergence:
                            logger.error("Attempting to remove a statistic modifier for a commodity that doesn't exist on object {}: {}", self.owner, stat_type)
            autonomy_modifier_entry.statistic_modifiers.clear()
            if modifier.statistic_multipliers:
                for (stat_type, statistic_multiplier) in modifier.statistic_multipliers.items():
                    if stat_type not in autonomy_modifier_entry.statistic_multipliers:
                        pass
                    tracker = self.get_tracker(stat_type)
                    stat = tracker.get_statistic(stat_type)
                    if stat is not None:
                        stat.remove_statistic_multiplier(statistic_multiplier)
                    else:
                        while stat_type.add_if_not_in_tracker:
                            logger.warn("Attempting to remove a statistic multiplier for a commodity that doesn't exist on object {}: {}", self.owner, stat_type)
            autonomy_modifier_entry.statistic_multipliers.clear()
            if self.owner.is_sim:
                self.owner.relationship_tracker.remove_relationship_multipliers(handle)
                sim_skill_list = list(self.owner.skills_gen())

                def skill_with_tag_gen(tag):
                    for skill in sim_skill_list:
                        while tag in skill.tags:
                            yield skill

                for (skill_tag, skill_modifier) in modifier.skill_tag_modifiers.items():
                    for found_skill in skill_with_tag_gen(skill_tag):
                        found_skill.remove_statistic_multiplier(skill_modifier)
            for commodity_type in modifier.commodities_to_add:
                while commodity_type in self._commodities_added:
                    if self._commodities_added[commodity_type] > 1:
                        self._commodities_added[commodity_type] -= 1
                    else:
                        del self._commodities_added[commodity_type]
                        tracker = self.get_tracker(commodity_type)
                        tracker.remove_statistic(commodity_type)
            if modifier.override_convergence is not None:
                for commodity_to_override in modifier.override_convergence.keys():
                    tracker = self.get_tracker(commodity_to_override)
                    tracker.reset_convergence(commodity_to_override)
            del self._statistic_modifiers[handle]
            return True
        return False

    @componentmethod
    def get_statistic_modifier(self, handle):
        bad_id = self.owner.id == 0
        if handle in self._statistic_modifiers:
            if bad_id:
                return
            return self._statistic_modifiers[handle].autonomy_modifier
        if handle in self._suspended_modifiers:
            if bad_id:
                return
            return self._suspended_modifiers[handle]

    @componentmethod
    def get_statistic_modifiers_gen(self):
        yield self._statistic_modifiers.items()

    @componentmethod
    def suspend_statistic_modifier(self, handle):
        autonomy_modifier = self._statistic_modifiers[handle].autonomy_modifier
        self.remove_statistic_modifier(handle)
        self._suspended_modifiers[handle] = autonomy_modifier

    @componentmethod
    def resume_statistic_modifier(self, handle):
        if handle in self._suspended_modifiers:
            self.add_statistic_modifier(modifier=self._suspended_modifiers[handle], requested_handle=handle)
            del self._suspended_modifiers[handle]

    @componentmethod
    def get_score_multiplier(self, stat_type):
        score_multiplier = 1
        for autonomy_modifier_entry in self._statistic_modifiers.values():
            score_multiplier *= autonomy_modifier_entry.autonomy_modifier.get_score_multiplier(stat_type)
        return score_multiplier

    @componentmethod_with_fallback(lambda *_, **__: 1)
    def get_stat_multiplier(self, stat_type, participant_type):
        score_multiplier = 1
        for autonomy_modifier_entry in self._statistic_modifiers.values():
            score_multiplier *= autonomy_modifier_entry.autonomy_modifier.get_stat_multiplier(stat_type, participant_type)
        for modifier in self._interaction_modifiers.values():
            score_multiplier *= modifier.get_stat_multiplier(stat_type, participant_type)
        return score_multiplier

    @componentmethod_with_fallback(lambda *_, **__: False)
    def check_affordance_for_suppression(self, sim, aop, user_directed):
        for autonomy_modifier_entry in self._statistic_modifiers.values():
            while autonomy_modifier_entry.autonomy_modifier.affordance_suppressed(sim, aop, user_directed):
                return True
        for autonomy_modifier in self._suspended_modifiers.values():
            while autonomy_modifier.affordance_suppressed(sim, aop, user_directed):
                return True
        return False

    @componentmethod_with_fallback(lambda _: False)
    def is_locked(self, stat):
        for autonomy_modifier_entry in self._statistic_modifiers.values():
            while autonomy_modifier_entry.autonomy_modifier.is_locked(type(stat)):
                return True
        for modifier in self._suspended_modifiers.values():
            while modifier.is_locked(type(stat)):
                return True
        return False

    @componentmethod_with_fallback(lambda _: None)
    def get_relationship_score_multiplier_for_buff_on_target(self):
        return self._relationship_score_multiplier_with_buff_on_target

    @componentmethod
    def is_scorable(self, stat_type):
        for autonomy_modifier_entry in self._statistic_modifiers.values():
            while not autonomy_modifier_entry.autonomy_modifier.is_scored(stat_type):
                return False
        return True

    @componentmethod
    def get_off_lot_autonomy_rule_type(self):
        current_rule = None
        for autonomy_modifier_entry in self._statistic_modifiers.values():
            rule = autonomy_modifier_entry.autonomy_modifier.off_lot_autonomy_rule
            if rule is None:
                pass
            while current_rule is None or rule.rule > current_rule.rule:
                current_rule = rule
        if current_rule is not None:
            return current_rule.rule
        return autonomy.autonomy_modifier.OffLotAutonomyRules.DEFAULT

    @componentmethod
    def get_off_lot_autonomy_tolerance(self):
        current_rule = None
        for autonomy_modifier_entry in self._statistic_modifiers.values():
            rule = autonomy_modifier_entry.autonomy_modifier.off_lot_autonomy_rule
            if rule is None:
                pass
            while current_rule is None or rule.tolerance > current_rule.tolerance:
                current_rule = rule
        if current_rule is not None:
            return current_rule.tolerance
        return StatisticComponentGlobalTuning.DEFAULT_OFF_LOT_TOLERANCE

    @componentmethod
    def get_off_lot_autonomy_radius(self):
        current_rule = None
        for autonomy_modifier_entry in self._statistic_modifiers.values():
            rule = autonomy_modifier_entry.autonomy_modifier.off_lot_autonomy_rule
            if rule is None:
                pass
            while current_rule is None or rule.radius > current_rule.radius:
                current_rule = rule
        if current_rule is not None:
            return current_rule.radius
        return StatisticComponentGlobalTuning.DEFAULT_RADIUS_TO_CONSIDER_OFF_LOT_OBJECTS

    def _get_off_lot_autonomy_rule(self):
        current_rule = None
        for autonomy_modifier_entry in self._statistic_modifiers.values():
            rule = autonomy_modifier_entry.autonomy_modifier.off_lot_autonomy_rule
            while rule is not None:
                if current_rule is None:
                    current_rule = rule
                else:
                    return
        return current_rule

    def on_initial_startup(self):
        if self._commodity_tracker is not None:
            self._commodity_tracker.on_initial_startup()
        if self._statistic_tracker is not None:
            self._statistic_tracker.on_initial_startup()
        if self._static_commodity_tracker is not None:
            self._static_commodity_tracker.on_initial_startup()

    def on_remove(self):
        if self._commodity_tracker is not None:
            self._commodity_tracker.destroy()
        if self._statistic_tracker is not None:
            self._statistic_tracker.destroy()
        if self._static_commodity_tracker is not None:
            self._static_commodity_tracker.destroy()

    def save(self, persistence_master_message):
        persistable_data = persistence_protocols.PersistenceMaster.PersistableData()
        persistable_data.type = persistence_protocols.PersistenceMaster.PersistableData.StatisticComponent
        saved_any_data = False
        if self._statistic_tracker is not None:
            statistic_data = persistable_data.Extensions[persistence_protocols.PersistableStatisticsTracker.persistable_data]
            regular_statistics = self._statistic_tracker.save()
            statistic_data.statistics.extend(regular_statistics)
            if regular_statistics:
                saved_any_data = True
        if self._commodity_tracker is not None:
            commodity_data = persistable_data.Extensions[persistence_protocols.PersistableCommodityTracker.persistable_data]
            skill_data = persistable_data.Extensions[persistence_protocols.PersistableSkillTracker.persistable_data]
            (commodities, skill_statistics) = self._commodity_tracker.save()
            commodity_data.commodities.extend(commodities)
            skill_data.skills.extend(skill_statistics)
            if commodities or skill_statistics:
                saved_any_data = True
        if saved_any_data:
            persistence_master_message.data.extend([persistable_data])

    def load(self, statistic_component_message):
        if self._statistic_tracker is not None:
            statistic_component_data = statistic_component_message.Extensions[persistence_protocols.PersistableStatisticsTracker.persistable_data]
            self._statistic_tracker.load(statistic_component_data.statistics)
        if self._commodity_tracker is not None:
            commodity_data = statistic_component_message.Extensions[persistence_protocols.PersistableCommodityTracker.persistable_data]
            self._commodity_tracker.load(commodity_data.commodities)
            skill_component_data = statistic_component_message.Extensions[persistence_protocols.PersistableSkillTracker.persistable_data]
            self._commodity_tracker.load(skill_component_data.skills)

    @componentmethod
    def is_in_distress(self):
        return len(self._commodity_distress_refs) > 0

    @componentmethod
    def enter_distress(self, commodity):
        index = 0
        for commodity_ref in self._commodity_distress_refs:
            if commodity == commodity_ref:
                return
            if commodity.commodity_distress.priority < commodity_ref.commodity_distress.priority:
                self._commodity_distress_refs.insert(index, commodity)
                return
            index += 1
        self._commodity_distress_refs.append(commodity)

    @componentmethod
    def exit_distress(self, commodity):
        if commodity in self._commodity_distress_refs:
            self._commodity_distress_refs.remove(commodity)

    @componentmethod
    def test_interaction_for_distress_compatability(self, interaction):
        return self._get_commodity_incompatible_with_interaction(interaction) is None

    def _get_commodity_incompatible_with_interaction(self, interaction):
        for commodity in self._commodity_distress_refs:
            while commodity.commodity_distress.incompatible_interactions(interaction):
                return commodity

    @componentmethod
    def test_for_distress_compatibility_and_run_replacement(self, interaction, sim):
        incompatible_distress_commodity = self._get_commodity_incompatible_with_interaction(interaction)
        if incompatible_distress_commodity is None:
            return True
        context = interactions.context.InteractionContext(sim, interactions.context.InteractionContext.SOURCE_AUTONOMY, interactions.priority.Priority.Critical)
        sim.push_super_affordance(incompatible_distress_commodity.commodity_distress.replacement_affordance, None, context)
        return False

