from postures.posture_specs import PostureSpecVariable, BODY_POSTURE_TYPE_INDEX, BODY_INDEX, BODY_TARGET_INDEX, SURFACE_INDEX, SURFACE_TARGET_INDEX
from sims4.tuning.dynamic_enum import DynamicEnum
from sims4.tuning.geometric import TunableCurve
from sims4.tuning.tunable import Tunable, TunableFactory, TunableVariant, TunableTuple, TunableList, TunableEnumEntry
import accumulator
import gsi_handlers
import interactions.constraints
import postures
import primitives.routing_utils
import services
import sims4.callback_utils
import sims4.reload
import socials.geometry
with sims4.reload.protected(globals()):

    def final_destinations_gen():
        pass

    on_transition_destinations_changed = sims4.callback_utils.CallableList()

def set_final_destinations_gen(new_final_destinations_gen):
    global final_destinations_gen
    final_destinations_gen = new_final_destinations_gen

def set_transition_destinations(sim, source_dest_set, preserve=False, draw_both_sets=False):
    if __debug__ and on_transition_destinations_changed:
        transition_destinations = []
        possible_sources = []
        max_dest_cost = 0
        for (source_handles, destination_handles, _, _, _, _) in source_dest_set.values():
            for (_, _, _, _, slot_goals, _, _) in source_handles.values():
                for slot_goal in slot_goals:
                    slot_transform = sims4.math.Transform(slot_goal.location.position, slot_goal.location.orientation)
                    slot_constraint = interactions.constraints.Transform(slot_transform, routing_surface=slot_goal.routing_surface_id)
                    possible_sources.append(slot_constraint)
            if not draw_both_sets:
                pass
            for (_, _, _, _, slot_goals, _, _) in destination_handles.values():
                for slot_goal in slot_goals:
                    if slot_goal.cost > max_dest_cost:
                        max_dest_cost = slot_goal.cost
                    slot_transform = sims4.math.Transform(slot_goal.location.position, slot_goal.location.orientation)
                    slot_constraint = interactions.constraints.Transform(slot_transform, routing_surface=slot_goal.routing_surface_id)
                    transition_destinations.append((slot_goal.path_id, slot_constraint, slot_goal.cost))
        on_transition_destinations_changed(sim, transition_destinations, possible_sources, max_dest_cost, preserve=preserve)

class AttractSimAffinityStrategy(TunableFactory):
    __qualname__ = 'AttractSimAffinityStrategy'
    ATTRACTION_BONUS = Tunable(description='\n        The distance, in meters, the Sim will go out of their way to choose objects near other\n        Sims. This bonus will drop off as distance from other Sims increases.\n        ', tunable_type=float, default=50)

    @staticmethod
    def _get_affinity(sim, other_sim):
        return (-AttractSimAffinityStrategy.ATTRACTION_BONUS, 'Sim Affinity: basic attract bonus: {}')

    FACTORY_TYPE = _get_affinity

class AvoidSimAffinityStrategy(TunableFactory):
    __qualname__ = 'AvoidSimAffinityStrategy'
    AVOID_PENALTY = Tunable(description='\n        The effective increased distance, in meters, the Sim will consider objects\n        nearby other Sims. This penalty will drop off as distance from other Sims increases.\n        ', tunable_type=float, default=50)

    @staticmethod
    def _get_affinity(sim, other_sim):
        return (AvoidSimAffinityStrategy.AVOID_PENALTY, 'Sim Affinity: basic avoid penalty: {}')

    FACTORY_TYPE = _get_affinity

class RelationshipSimAffinityStrategy(TunableFactory):
    __qualname__ = 'RelationshipSimAffinityStrategy'
    RELATIONSHIP_TO_ATTRACTION_BONUS_CURVE = TunableCurve(description='\n        Tunable curve where the X-axis defines the relationship level between \n        two sims while the Y-axis defines the attraction bonus.\n        Note: Negative numbers are a penalty.\n        ', x_axis_name='Relationship', y_axis_name='Attraction Bonus')

    @staticmethod
    def _get_affinity(sim, other_sim):
        aggregate_track_value = [track.get_value() for track in sim.relationship_tracker.relationship_tracks_gen(other_sim.id) if track.is_scored]
        average_track_value = sum(aggregate_track_value)/len(aggregate_track_value) if aggregate_track_value else 0
        sim_affinity = RelationshipSimAffinityStrategy.RELATIONSHIP_TO_ATTRACTION_BONUS_CURVE.get(average_track_value)
        return (-sim_affinity, 'Sim Affinity: basic nearby Sim with relationship bonus: {}')

    FACTORY_TYPE = _get_affinity

class InteractionPostureAffinityTag(DynamicEnum):
    __qualname__ = 'InteractionPostureAffinityTag'
    ALL = Ellipsis

class TunableSimAffinityStrategy(TunableTuple):
    __qualname__ = 'TunableSimAffinityStrategy'

    def __init__(self):
        return super().__init__(negate_tag=Tunable(bool, default=False, description='\n                        Negate the tag below, meaning the affinity will apply for Sims running interactions that\n                        DO NOT have the given tag. Note: has no effect when paired with ALL.'), running_interaction_tag=TunableEnumEntry(InteractionPostureAffinityTag, default=InteractionPostureAffinityTag.ALL, description='\n                                                                    A list of tags of interactions where if a Sim is running\n                                                                    any interaction that matches any of these tags, they will\n                                                                    get the attached affinity scoring'), affinity_strategy=TunableVariant(description='\n                                        The type of strategy to use when scoring other Sims.\n                                        ', relationship_based=RelationshipSimAffinityStrategy(description='\n                                                        Score objects near Sims based on their relationship. This\n                                                        strategy will make Sims more likely to be near their\n                                                        family members and lovers, etc.'), attract=AttractSimAffinityStrategy(description='\n                                                        Score objects near other Sims more highly. This will make\n                                                        Sims more likely to be nearby other Sims.'), avoid=AvoidSimAffinityStrategy(description='\n                                                        Apply penalties to objects near other Sims. This will make\n                                                        Sims avoid other Sims.')), multiplier=Tunable(float, default=1, description='\n                                        A scalar multiplier on the final score for each other Sim.'))

class TunableSimAffinityPostureScoringData(TunableTuple):
    __qualname__ = 'TunableSimAffinityPostureScoringData'

    def __init__(self):
        return super().__init__(my_tags=TunableList(TunableEnumEntry(InteractionPostureAffinityTag, default=InteractionPostureAffinityTag.ALL), description='\n                                                        The tags that apply to this interaction.'), my_scoring=TunableList(TunableSimAffinityStrategy(), description='\n                                                           The scoring strategies that will be applied\n                                                           to objects when doing posture graph solutions\n                                                           for this interaction.'))

class PostureScoring:
    __qualname__ = 'PostureScoring'
    INNER_NON_MOBILE_TO_NON_MOBILE_COST = Tunable(description='\n        Default Cost to transition between parts when already in an object.\n        ', tunable_type=float, default=3)
    ENTER_EXIT_OBJECT_COST = Tunable(description='\n        Cost for entering or exiting an object.\n        ', tunable_type=float, default=0.5)
    OBJECT_RESERVED_PENALTY = Tunable(description='\n        The Penalty, in meters, to apply if another Sim has already started \n        a transition to use an object a Sim is considering.\n        ', tunable_type=float, default=100)
    IN_USE_PENALTY = Tunable(description='\n        The Penalty, in meters, to apply if the part is already in use. Keep this\n        greater than Not Best Part Penalty so sims will still try a new part if\n        the best part fails.\n        ', tunable_type=float, default=20)
    BEST_PART_BONUS = Tunable(description='\n        Sims will go this many meters out of their way to get to the part\n        picked when choosing the interaction. This should be slightly larger\n        than the radius of our largest multi-part object. This bonus is applied\n        in addition to the best object bonus.\n        ', tunable_type=float, default=75)
    BEST_OBJECT_BONUS = Tunable(description='\n        On the first route, we prefer parts on the object that contains\n        the part that you clicked over other objects or parts. Sims will\n        go this many meters out of their way to get to that object.\n        ', tunable_type=float, default=100)
    SURFACE_BONUS = Tunable(description='\n        Add this bonus, in meters, to surface nodes if we prefer surface for the\n        interaction.\n        ', tunable_type=float, default=7)
    DEST_ALREADY_SELECTED_PENALTY = Tunable(description='\n        Add this penalty, in meters, if a transition sequence already picked this\n        destination.\n        ', tunable_type=float, default=10)
    IN_PARTY_CONSTRAINT_BONUS = Tunable(description="\n        Add this bonus, in meters, if the object is within the Sim's party's\n        constraint.\n        ", tunable_type=float, default=100)
    ADJACENT_TO_GROUP_MEMBER_BONUS = Tunable(description='\n        Add this bonus, in meters, if the object is a part and there is an adjacent\n        part in use by a group member.\n        ', tunable_type=float, default=15)
    AUTONOMOUSLY_PREFERRED_BONUS = Tunable(description='\n        Add this bonus, in meters, if the interaction prefers that this target is \n        selected. This uses autonomy preferences to help figure out\n        where a Sim should go to.\n        \n        Example: When sims choose to use a bed they prefer to use their own bed.\n        When Sims do a posture transition to do WooHoo, they should also use\n        their bed. This value determines how far out of the way the Sim will go\n        to meet that preference. \n        ', tunable_type=float, default=100)
    SAME_CLUSTER_SIM_MULTIPLIER = Tunable(description='\n        This multiplier is applied to the bonus for Sims in the same cluster\n        as the object being considered by the Sim.  Raising this will\n        encourage Sims to join/avoid clusters with people they like/dislike.\n        ', tunable_type=float, default=1.2)
    MOBILE_TO_MOBILE_COST = 0
    CANCEL_EXISTING_CARRY_OR_SLOT_COST = 10
    _DISTANCE_MULT = 2

    @staticmethod
    def build_destination_costs(goal_costs, destination_nodes, sim, interaction, var_map, preferences, included_sis, additional_template_list, relationship_bonuses, spec_constraint, group_constraint):
        for dest_node in destination_nodes:
            if dest_node in goal_costs:
                pass
            node_cost = PostureScoring.get_goal_node_cost(dest_node, sim, interaction, var_map, preferences, included_sis, additional_template_list, relationship_bonuses, spec_constraint, group_constraint)
            goal_costs[dest_node] = node_cost

    @staticmethod
    def get_preferred_object_cost(goal_targets, preferred_objects, cost_str_list=None):
        if not preferred_objects:
            return 0
        for goal_target in goal_targets:
            while goal_target is not None:
                break
        return 0
        cost = 0
        goal_ancestry = set()
        for goal_target in goal_targets:
            goal_ancestry.update(goal_target.ancestry_gen())
        preferred_objects = set().union(*(obj.ancestry_gen() for obj in preferred_objects if obj.carryable_component is None))
        preferred_parts = {obj for obj in preferred_objects if obj.is_part}
        is_preferred_part = True if goal_ancestry & preferred_parts else False
        is_preferred_object = is_preferred_part or (True if goal_ancestry & preferred_objects else False)
        if is_preferred_part:
            cost -= PostureScoring.BEST_PART_BONUS
            if cost_str_list is not None:
                cost_str_list.append('BEST_PART_BONUS: {}'.format(-PostureScoring.BEST_PART_BONUS))
        if is_preferred_object:
            cost -= PostureScoring.BEST_OBJECT_BONUS
            if cost_str_list is not None:
                cost_str_list.append('BEST_OBJECT_BONUS: {}'.format(-PostureScoring.BEST_OBJECT_BONUS))
            if preferred_parts:
                estimate_distance = primitives.routing_utils.estimate_distance
                distance_to_preferred_part = min(min(estimate_distance(goal_target, part) for part in preferred_parts) for goal_target in goal_targets)
                preferred_part_dist_cost = distance_to_preferred_part*PostureScoring._DISTANCE_MULT
                cost += preferred_part_dist_cost
                if cost_str_list is not None:
                    cost_str_list.append('distance to preferred part * _DISTANCE_MULT: {}'.format(preferred_part_dist_cost))
        return cost

    @staticmethod
    def build_relationship_bonuses(sim, sim_affinity_posture_scoring_data, sims_to_consider=None):
        if sim_affinity_posture_scoring_data is None:
            return
        bonuses = {}
        posture_graph = services.current_zone().posture_graph_service
        if not sims_to_consider:
            sims_to_consider = (other_sim_info.get_sim_instance() for other_sim_info in services.sim_info_manager().objects if other_sim_info.is_instanced())
        obj_to_cluster = {}
        clusters = list(services.social_group_cluster_service().get_clusters_gen())
        for cluster in clusters:
            for obj in cluster.objects_gen():
                obj_to_cluster[obj] = cluster
        for other_sim in sims_to_consider:
            if other_sim is sim:
                pass
            if other_sim.posture.unconstrained:
                pass
            if other_sim.is_moving:
                pass
            if not other_sim.posture.allow_affinity:
                pass
            scores = []
            other_sim_cluster = None
            other_sim_body_target = other_sim.posture_state.body_target
            if other_sim_body_target.is_part:
                other_sim_body_target = other_sim_body_target.part_owner
            other_sim_cluster = obj_to_cluster.get(other_sim_body_target)
            for scoring_strategy in sim_affinity_posture_scoring_data.my_scoring:
                match_tag = scoring_strategy.running_interaction_tag
                if match_tag == InteractionPostureAffinityTag.ALL:
                    match = True
                else:
                    match = False
                    for si in other_sim.si_state:
                        while si.sim_affinity_posture_scoring_data is not None and match_tag in si.sim_affinity_posture_scoring_data.my_tags:
                            if not scoring_strategy.negate_tag:
                                match = True
                            break
                    if scoring_strategy.negate_tag:
                        match = True
                if not match:
                    pass
                (affinity, message) = scoring_strategy.affinity_strategy(sim, other_sim)
                if not affinity:
                    pass
                scores.append((affinity, message))
            if not (other_sim_body_target is not None and scores):
                pass
            other_sim_facing = sims4.math.yaw_quaternion_to_angle(other_sim.transform.orientation)
            distances = {}
            nodes_in_sight = posture_graph.nodes_matching_constraint_geometry(other_sim.los_constraint)
            for goal_node in nodes_in_sight:
                goal_body = goal_node[BODY_INDEX]
                goal_body_target = goal_body[BODY_TARGET_INDEX]
                goal_posture_type = goal_body[BODY_POSTURE_TYPE_INDEX]
                while not goal_body_target is None:
                    if goal_posture_type.mobile:
                        pass
                    distance = distances.get(goal_body_target)
                    if distance is None:
                        sim_facing = sims4.math.yaw_quaternion_to_angle(goal_body_target.transform.orientation)
                        accum = accumulator.HarmonicMeanAccumulator()
                        delta = other_sim.transform.translation - goal_body_target.transform.translation
                        socials.geometry.score_facing(accum, sim_facing, other_sim_facing, delta)
                        facing_score = accum.value()
                        if facing_score <= 0:
                            pass
                        distance = (goal_body_target.position - other_sim.position).magnitude_2d()
                        distance = max(distance, 1)
                        distance /= facing_score
                        distances[goal_body_target] = distance
                    bonus = 0
                    all_messages = []
                    for (affinity, message) in scores:
                        affinity_weighted = affinity/distance
                        bonus += affinity_weighted
                    if not bonus:
                        pass
                    if goal_body_target.is_part:
                        goal_object = goal_body_target.part_owner
                    else:
                        goal_object = goal_body_target
                    if goal_object in obj_to_cluster:
                        same_cluster = obj_to_cluster[goal_object] is other_sim_cluster
                    else:
                        same_cluster = False
                    if same_cluster:
                        bonus *= PostureScoring.SAME_CLUSTER_SIM_MULTIPLIER
                    current_bonus_info = bonuses.get(goal_body_target)
                    while current_bonus_info is None or bonus < current_bonus_info[0]:
                        formatted_message = ''
                        bonuses[goal_body_target] = (bonus, formatted_message)
        obj_to_cluster.clear()
        return bonuses

    @staticmethod
    def get_goal_node_cost(goal_node, sim, interaction, var_map, preferences, included_sis, additional_template_dict, relationship_bonuses, spec_constraint, group_constraint):
        cost = 0
        body_index = BODY_INDEX
        body_target_index = BODY_TARGET_INDEX
        body_posture_type_index = BODY_POSTURE_TYPE_INDEX
        goal_body = goal_node[body_index]
        goal_body_target = goal_body[body_target_index]
        goal_surface_target = goal_node[SURFACE_INDEX][SURFACE_TARGET_INDEX]
        if gsi_handlers.posture_graph_handlers.archiver.enabled:
            cost_str_list = []
        else:
            cost_str_list = None
        if goal_body_target is not None and not goal_body_target.may_reserve(sim):
            cost += PostureScoring.IN_USE_PENALTY
            if gsi_handlers.posture_graph_handlers.archiver.enabled:
                cost_str_list.append('IN_USE_PENALTY: {}'.format(PostureScoring.IN_USE_PENALTY))
        elif goal_surface_target is not None and PostureSpecVariable.SLOT in var_map:
            slot_manifest_entry = var_map[PostureSpecVariable.SLOT].with_overrides(target=goal_surface_target)
            objects_to_ignore = []
            if hasattr(interaction, 'process') and interaction.process is not None and interaction.process.current_ico is not None:
                objects_to_ignore.append(interaction.process.current_ico)
            runtime_slots = slot_manifest_entry.get_runtime_slots_gen()
            for runtime_slot in runtime_slots:
                while runtime_slot is not None:
                    if slot_manifest_entry.actor in runtime_slot.children:
                        break
                    result = runtime_slot.is_valid_for_placement(obj=slot_manifest_entry.actor, objects_to_ignore=objects_to_ignore)
                    if result:
                        break
            cost += PostureScoring.IN_USE_PENALTY
            if gsi_handlers.posture_graph_handlers.archiver.enabled:
                cost_str_list.append('IN_USE_PENALTY: {}(Slot In Use)'.format(PostureScoring.IN_USE_PENALTY))
        if interaction.autonomy_preference is not None and goal_body_target is not None and sim.is_object_use_preferred(interaction.autonomy_preference.preference.tag, goal_body_target):
            cost -= PostureScoring.AUTONOMOUSLY_PREFERRED_BONUS
            if gsi_handlers.posture_graph_handlers.archiver.enabled:
                cost_str_list.append('AUTONOMOUSLY_PREFERRED_BONUS: {}'.format(-1*PostureScoring.AUTONOMOUSLY_PREFERRED_BONUS))
        goal_targets = set()
        if goal_body_target is not None:
            goal_targets.add(goal_body_target)
        if goal_surface_target is not None:
            goal_targets.add(goal_surface_target)
        if goal_targets:
            body_target_cost = PostureScoring.get_preferred_object_cost(goal_targets, interaction.preferred_objects, cost_str_list=cost_str_list)
            cost += body_target_cost
        if group_constraint is not None:
            for sub_constraint in group_constraint:
                while sub_constraint.geometry is None or goal_body_target is None or sub_constraint.geometry.contains_point(goal_body_target.position):
                    cost -= PostureScoring.IN_PARTY_CONSTRAINT_BONUS
                    if gsi_handlers.posture_graph_handlers.archiver.enabled:
                        cost_str_list.append('IN_PARTY_CONSTRAINT_BONUS: {}'.format(PostureScoring.IN_PARTY_CONSTRAINT_BONUS))
                    break
        if group_constraint is not None and goal_body_target is not None and goal_body_target.is_part:
            main_group = sim.get_main_group()
            if main_group is not None:
                group_sims = tuple(group_sim for group_sim in main_group if group_sim is not sim)
            else:
                group_sims = ()
            adjacent_parts = list(goal_body_target.adjacent_parts_gen())
            while True:
                for adjacent_part in adjacent_parts:
                    while any(adjacent_part.in_use_by(group_sim) for group_sim in group_sims):
                        cost -= PostureScoring.ADJACENT_TO_GROUP_MEMBER_BONUS
                        if gsi_handlers.posture_graph_handlers.archiver.enabled:
                            cost_str_list.append('ADJACENT_TO_GROUP_MEMBER_BONUS: {}'.format(PostureScoring.ADJACENT_TO_GROUP_MEMBER_BONUS))
                        break
        if goal_body_target is not None:
            for destination in final_destinations_gen():
                destination_body_target = destination[body_index][body_target_index]
                while destination_body_target is not None and destination_body_target is goal_body_target:
                    cost += PostureScoring.DEST_ALREADY_SELECTED_PENALTY
                    if gsi_handlers.posture_graph_handlers.archiver.enabled:
                        cost_str_list.append('DEST_ALREADY_SELECTED_PENALTY: {}'.format(PostureScoring.DEST_ALREADY_SELECTED_PENALTY))
        if additional_template_dict and not interaction.is_putdown:
            posture_graph = services.current_zone().posture_graph_service
            for (carry_si, additional_templates) in additional_template_dict.items():
                if posture_graph.any_template_passes_destination_test(additional_templates, carry_si, sim, goal_node):
                    pass
                cost += PostureScoring.CANCEL_EXISTING_CARRY_OR_SLOT_COST
                while gsi_handlers.posture_graph_handlers.archiver.enabled:
                    cost_str_list.append('CANCEL_EXISTING_CARRY_OR_SLOT_COST: {}'.format(PostureScoring.CANCEL_EXISTING_CARRY_OR_SLOT_COST))
        if goal_body_target is not None and interaction.combined_posture_target_preference is not None:
            posture_target_preferences = interaction.combined_posture_target_preference.copy()
            for si in included_sis:
                si_target_preferences = si.combined_posture_target_preference
                if si_target_preferences is None:
                    pass
                if si.has_active_cancel_replacement:
                    pass
                for (posture_tag, weight) in si_target_preferences.items():
                    posture_target_preferences[posture_tag] = weight + posture_target_preferences.get(posture_tag, 0)
            if goal_surface_target is not None and goal_surface_target.posture_transition_target_tag != postures.PostureTransitionTargetPreferenceTag.INVALID:
                preference_score = posture_target_preferences.get(goal_surface_target.posture_transition_target_tag, 0)
            elif goal_body_target is not None and goal_body_target.posture_transition_target_tag != postures.PostureTransitionTargetPreferenceTag.INVALID:
                preference_score = posture_target_preferences.get(goal_body_target.posture_transition_target_tag, 0)
            else:
                preference_score = 0
            cost -= preference_score
            if gsi_handlers.posture_graph_handlers.archiver.enabled:
                cost_str_list.append('goal_body_target preference bonus: {}'.format(-preference_score))
        if preferences is None:
            posture_cost = goal_body[body_posture_type_index].cost
            cost += posture_cost
            if gsi_handlers.posture_graph_handlers.archiver.enabled:
                cost_str_list.append('posture_cost: {}'.format(posture_cost))
        elif preferences.apply_penalties:
            posture_cost = preferences.posture_cost_overrides.get(goal_body[body_posture_type_index].posture_type, goal_body[body_posture_type_index].cost)
            if posture_cost < 0 and goal_body_target is not None and not goal_body[body_posture_type_index].posture_type.mobile:
                posture_cost *= spec_constraint.get_posture_cost_attenuation(goal_body_target)
            cost += posture_cost
            if gsi_handlers.posture_graph_handlers.archiver.enabled:
                cost_str_list.append('posture_cost: {}'.format(posture_cost))
            if preferences.prefer_surface and goal_surface_target is not None:
                cost -= PostureScoring.SURFACE_BONUS
                if gsi_handlers.posture_graph_handlers.archiver.enabled:
                    cost_str_list.append('SURFACE_BONUS: {}'.format(-1*PostureScoring.SURFACE_BONUS))
        if relationship_bonuses is not None:
            relationship_bonus_info = relationship_bonuses.get(goal_body_target)
            if relationship_bonus_info is not None:
                (relationship_bonus, message) = relationship_bonus_info
                cost += relationship_bonus
                if gsi_handlers.posture_graph_handlers.archiver.enabled:
                    cost_str_list.append(message)
        if gsi_handlers.posture_graph_handlers.archiver.enabled:
            gsi_handlers.posture_graph_handlers.log_goal_cost(sim, goal_node, cost, cost_str_list)
        return cost

