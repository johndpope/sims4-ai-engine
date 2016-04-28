from contextlib import contextmanager
from sims4.callback_utils import CallableList
from event_testing.results import TestResult
from interactions.base.picker_interaction import PickerSuperInteraction
from relationships.global_relationship_tuning import RelationshipGlobalTuning
from relationships.relationship import Relationship
from relationships.relationship_tracker_tuning import DefaultGenealogyLink, DefaultRelationshipInHousehold
from sims4.tuning.tunable import Tunable
from sims4.utils import flexmethod
from singletons import DEFAULT
from ui.ui_dialog_picker import ObjectPickerRow
import caches
import event_testing
import services
import sims4.log
logger = sims4.log.Logger('Relationship', default_owner='rez')
relationship_setup_logger = sims4.log.Logger('DefaultRelSetup', default_owner='manus')

class RelationshipTracker:
    __qualname__ = 'RelationshipTracker'

    def __init__(self, sim_info):
        super().__init__()
        self._sim_info = sim_info
        self._relationships = {}
        self._suppress_client_updates = False
        self.spouse_sim_id = None
        self._relationship_multipliers = {}
        self._create_relationship_callbacks = CallableList()

    def __iter__(self):
        return self._relationships.values().__iter__()

    def __len__(self):
        return len(self._relationships)

    @property
    def suppress_client_updates(self):
        return self._suppress_client_updates

    @contextmanager
    def suppress_client_updates_context_manager(self):
        self._suppress_client_updates = True
        try:
            yield None
        finally:
            self._suppress_client_updates = False

    def create_relationship(self, target_sim_id):
        return self._find_relationship(target_sim_id, True)

    def destroy_relationship(self, target_sim_id, notify_client=True):
        if target_sim_id in self._relationships:
            relationship = self._relationships[target_sim_id]
            relationship.destroy(notify_client=notify_client)
            del self._relationships[target_sim_id]

    def _clear_relationships(self):
        for sim_id in tuple(self._relationships.keys()):
            self.destroy_relationship(sim_id)

    def destroy_all_relationships(self):
        sim_id = self._sim_info.id
        keys = tuple(self._relationships.keys())
        for target_sim_id in keys:
            relationship = self._relationships[target_sim_id]
            target_sim_info = relationship.find_target_sim_info()
            if target_sim_info is not None:
                target_sim_info.relationship_tracker.destroy_relationship(sim_id)
            self.destroy_relationship(target_sim_id)

    def save(self):
        save_list = [relationship.get_persistance_protocol_buffer() for relationship in self._relationships.values()]
        return save_list

    def load(self, relationship_save_data):
        with self.suppress_client_updates_context_manager():
            self._clear_relationships()
            while relationship_save_data:
                for rel_save in relationship_save_data:
                    relationship = self.create_relationship(rel_save.target_id)
                    relationship.load(self._sim_info, rel_save)

    def send_relationship_info(self, target_sim_id=None):
        if target_sim_id is None:
            for relationship in self._relationships.values():
                relationship.send_relationship_info()
        else:
            relationship = self._find_relationship(target_sim_id)
            if relationship is not None:
                relationship.send_relationship_info()

    def clean_and_send_remaining_relationship_info(self):
        sim_info_manager = services.sim_info_manager()
        for (target_sim_info_id, relationship) in tuple(self._relationships.items()):
            if target_sim_info_id in sim_info_manager:
                relationship.send_relationship_info()
            else:
                self.destroy_relationship(target_sim_info_id, notify_client=False)

    def add_create_relationship_listener(self, callback):
        if callback not in self._create_relationship_callbacks:
            self._create_relationship_callbacks.append(callback)

    def remove_create_relationship_listener(self, callback):
        self._create_relationship_callbacks.remove(callback)

    @caches.cached
    def get_relationship_score(self, target_sim_id, track=DEFAULT):
        if track is DEFAULT:
            track = RelationshipGlobalTuning.REL_INSPECTOR_TRACK
        relationship = self._find_relationship(target_sim_id)
        if relationship:
            return relationship.get_track_score(track)
        return Relationship.DEFAULT_RELATIONSHIP_VALUE

    def add_relationship_score(self, target_sim_id, increment, track=DEFAULT, threshold=None):
        if track is DEFAULT:
            track = RelationshipGlobalTuning.REL_INSPECTOR_TRACK
        if target_sim_id == self._sim_info.sim_id:
            return
        relationship = self._find_relationship(target_sim_id, True)
        if relationship:
            if threshold is None or threshold.compare(relationship.get_track_score(track)):
                relationship.add_track_score(increment, track)
                logger.debug('Adding to score to track {} for {}: += {}; new score = {}', track, relationship, increment, relationship.get_track_score(track))
            else:
                logger.debug('Attempting to add to track {} for {} but {} not within threshold {}', track, relationship, relationship.get_track_score(track), threshold)
        else:
            logger.error('Attempting to add to the relationship score with myself: Sim = {}', self._sim_info)

    def set_relationship_score(self, target_sim_id, value, track=DEFAULT, threshold=None):
        if track is DEFAULT:
            track = RelationshipGlobalTuning.REL_INSPECTOR_TRACK
        if target_sim_id == self._sim_info.sim_id:
            return
        relationship = self._find_relationship(target_sim_id, True)
        if relationship:
            if threshold is None or threshold.compare(relationship.get_track_score(track)):
                relationship.set_track_score(value, track)
                logger.debug('Setting score on track {} for {}: = {}; new score = {}', track, relationship, value, relationship.get_track_score(track))
            else:
                logger.debug('Attempting to set score on track {} for {} but {} not within threshold {}', track, relationship, relationship.get_track_score(track), threshold)
        else:
            logger.error('Attempting to set the relationship score with myself: Sim = {}', self._sim_info)

    def enable_selectable_sim_track_decay(self, to_enable=True):
        logger.debug('Enabling ({}) decay for selectable sim: {}'.format(to_enable, self._sim_info))
        for relationship in self._relationships.values():
            relationship.enable_selectable_sim_track_decay(to_enable)

    def get_relationship_track_utility_score(self, target_sim_id, track=DEFAULT):
        if track is DEFAULT:
            track = RelationshipGlobalTuning.REL_INSPECTOR_TRACK
        relationship = self._find_relationship(target_sim_id)
        if relationship is not None:
            return relationship.get_track_utility_score(track)
        return track.autonomous_desire

    def get_relationship_prevailing_short_term_context_track(self, target_sim_id):
        relationship = self._find_relationship(target_sim_id)
        if relationship is not None:
            return relationship.get_prevailing_short_term_context_track()

    def get_default_short_term_context_bit(self):
        track = Relationship.DEFAULT_SHORT_TERM_CONTEXT_TRACK
        return track.get_bit_at_relationship_value(track.initial_value)

    def get_relationship_track_tracker(self, target_sim_id, add=False):
        relationship = self._find_relationship(target_sim_id, add)
        if relationship:
            return relationship.bit_track_tracker
        return

    def get_relationship_track(self, target_sim_id, track=DEFAULT, add=False):
        with self.suppress_client_updates_context_manager():
            if track is DEFAULT:
                track = RelationshipGlobalTuning.REL_INSPECTOR_TRACK
            relationship = self._find_relationship(target_sim_id, add)
            if relationship:
                return relationship.get_track(track, add)
            return

    def relationship_tracks_gen(self, target_sim_id):
        with self.suppress_client_updates_context_manager():
            relationship = self._find_relationship(target_sim_id)
            while relationship:
                for track in relationship.bit_track_tracker:
                    yield track

    def add_relationship_multipliers(self, handle, relationship_multipliers):
        if relationship_multipliers:
            for relationship in self:
                self._apply_relationship_multiplier_to_relationship(relationship, relationship_multipliers)
            self._relationship_multipliers[handle] = relationship_multipliers

    def _apply_relationship_multiplier_to_relationship(self, relationship, relationship_multipliers):
        for (track_type, multiplier) in relationship_multipliers.items():
            relationship_track = relationship.get_track(track_type, add=track_type.add_if_not_in_tracker)
            while relationship_track is not None:
                relationship_track.add_statistic_multiplier(multiplier)

    def remove_relationship_multipliers(self, handle):
        relationship_multipliers = self._relationship_multipliers.pop(handle, None)
        if relationship_multipliers is None:
            return
        for relationship in self:
            for (track_type, multiplier) in relationship_multipliers.items():
                relationship_track = relationship.get_track(track_type, add=False)
                while relationship_track is not None:
                    relationship_track.remove_statistic_multiplier(multiplier)

    def on_added_to_social_group(self, target_sim_id):
        relationship = self._find_relationship(target_sim_id)
        if relationship is not None:
            relationship.apply_social_group_decay()

    def on_removed_from_social_group(self, target_sim_id):
        relationship = self._find_relationship(target_sim_id)
        if relationship is not None:
            relationship.remove_social_group_decay()

    def set_default_tracks(self, target_sim, update_romance=True, family_member=False):
        if target_sim is None or target_sim.sim_id == self._sim_info.sim_id:
            return
        with self.suppress_client_updates_context_manager():
            target_sim_id = target_sim.sim_id
            key = DefaultGenealogyLink.Roommate
            if family_member:
                key = DefaultGenealogyLink.FamilyMember
            default_relationship = DefaultRelationshipInHousehold.RelationshipSetupMap.get(key)
            default_relationship.apply(self, target_sim)
            if update_romance and self.spouse_sim_id == target_sim_id:
                key = DefaultGenealogyLink.Spouse
                default_relationship = DefaultRelationshipInHousehold.RelationshipSetupMap.get(key)
                default_relationship.apply(self, target_sim)
                for (gender, gender_preference_statistic) in self._sim_info.get_gender_preferences_gen():
                    while gender == target_sim.gender:
                        gender_preference_statistic.set_value(gender_preference_statistic.max_value)
            relationship_setup_logger.info('Set default tracks {:25} -> {:25} as {}', self._sim_info.full_name, target_sim.full_name, key)

    def add_relationship_bit(self, target_sim_id, bit_to_add, force_add=False):
        if bit_to_add is None:
            logger.error('Attempting to add None bit to relationship for {}', self._sim_info)
            return
        if bit_to_add.trait_replacement_bits is not None:
            trait_tracker = self._sim_info.trait_tracker
            for (trait, replacement_bit) in bit_to_add.trait_replacement_bits.items():
                while trait_tracker.has_trait(trait):
                    self.add_relationship_bit(target_sim_id, replacement_bit, force_add)
                    return
        relationship = self._find_relationship(target_sim_id, True)
        if not relationship:
            logger.error('Failed to find relationship for {} and {}', self._sim_info, services.sim_info_manager().get(target_sim_id))
            return
        for requirement in bit_to_add.permission_requirements:
            while self._sim_info.sim_permissions.is_permission_enabled(requirement.permission) != requirement.required_enabled:
                return
        if force_add:
            if bit_to_add.is_track_bit and bit_to_add.triggered_track is not None:
                track = bit_to_add.triggered_track
                mean_list = track.bit_data.get_track_mean_list_for_bit(bit_to_add)
                for mean_tuple in mean_list:
                    self.set_relationship_score(target_sim_id, mean_tuple.mean, mean_tuple.track)
            for required_bit in bit_to_add.required_bits:
                self.add_relationship_bit(target_sim_id, required_bit, force_add=True)
        self._send_relationship_prechange_event(target_sim_id)
        if not bit_to_add.is_track_bit:
            relationship.add_bit(bit_to_add)
        self._send_relationship_changed_event(target_sim_id)
        services.social_service.post_relationship_message(self._sim_info, bit_to_add, target_sim_id, added=True)

    def remove_relationship_bit(self, target_sim_id, bit):
        relationship = self._find_relationship(target_sim_id)
        if relationship:
            self._send_relationship_prechange_event(target_sim_id)
            relationship.remove_bit(bit)
            self._send_relationship_changed_event(target_sim_id)
            services.social_service.post_relationship_message(self._sim_info, bit, target_sim_id, added=False)

    def _check_for_living_status(self, sim_id, allow_dead_targets, allow_living_targets):
        sim_info = services.sim_info_manager().get(sim_id)
        if sim_info is None:
            logger.error('_check_for_living_status() could not find SimInfo for sim_id {} with requesting sim {}', sim_id, self._sim_info, owner='ayarger')
            return False
        is_sim_dead = sim_info.is_dead
        return allow_dead_targets and is_sim_dead or allow_living_targets and not is_sim_dead

    def get_all_bits(self, target_sim_id:int=None, allow_dead_targets=True, allow_living_targets=True):
        bits = []
        if target_sim_id is None:
            for relationship in self._relationships.values():
                if not self._check_for_living_status(relationship.target_sim_id, allow_dead_targets, allow_living_targets):
                    pass
                bits.extend(relationship.get_bits())
        else:
            relationship = self._find_relationship(target_sim_id)
            if relationship:
                if not self._check_for_living_status(relationship.target_sim_id, allow_dead_targets, allow_living_targets):
                    return bits
                bits.extend(relationship.get_bits())
        return bits

    def get_relationship_depth(self, target_sim_id):
        relationship = self._find_relationship(target_sim_id)
        if relationship:
            return relationship.depth
        return 0

    def has_bit(self, target_sim_id, bit):
        relationship = self._find_relationship(target_sim_id)
        if relationship is not None:
            return relationship.has_bit(bit)
        return False

    def get_highest_priority_track_bit(self, target_sim_id):
        relationship = self._find_relationship(target_sim_id)
        if relationship is not None:
            return relationship.get_highest_priority_track_bit()
        return

    def get_highest_priority_bit(self, target_sim_id):
        relationship = self._find_relationship(target_sim_id)
        if relationship is not None:
            return relationship.get_highest_priority_bit()
        return

    def update_bits_on_age_up(self, current_age):
        for relationship in self._relationships.values():
            relationship.add_historical_bits_on_age_up(current_age)

    def target_sim_gen(self):
        for target_sim_id in self._relationships.keys():
            yield target_sim_id

    def add_relationship_appropriateness_buffs(self, target_sim_id):
        relationship = self._find_relationship(target_sim_id)
        if relationship is not None:
            relationship.add_relationship_appropriateness_buffs()

    def add_neighbor_bit_if_necessary(self):
        for relationship in self._relationships.values():
            relationship.add_neighbor_bit_if_necessary(self._sim_info)

    def get_knowledge(self, target_sim_id, initialize=False):
        relationship = self._find_relationship(target_sim_id, create=initialize)
        if relationship is not None:
            return relationship.get_knowledge(initialize=initialize)

    def add_known_trait(self, trait, target_sim_id, num_traits=None, notify_client=True):
        relationship = self._find_relationship(target_sim_id, True)
        knowledge = relationship.get_knowledge(initialize=True)
        knowledge.add_known_trait(trait, num_traits=num_traits, notify_client=notify_client)

    def print_relationship_info(self, target_sim_id, _connection):
        relationship = self._find_relationship(target_sim_id)
        if relationship is not None:
            sims4.commands.output('{}:\n\tTotal Depth: {}\n\tBits:\n{}\n\tTracks:\n{}'.format(relationship, relationship.depth, relationship.build_printable_string_of_bits(), relationship.build_printable_string_of_tracks()), _connection)
        else:
            sims4.commands.output('Relationship not found between {} and {}:\n\tTotal Depth: {}\n\tBits:\n{}\n\tTracks:\n{}'.format(self._sim_info, target_sim_id, self.get_relationship_depth(target_sim_id), self._build_printable_string_of_bits(target_sim_id), self._build_printable_string_of_tracks(target_sim_id)), _connection)

    def _find_relationship(self, target_sim_id, create=False):
        if self._sim_info.sim_id == target_sim_id:
            return
        if target_sim_id in self._relationships:
            return self._relationships[target_sim_id]
        if create:
            logger.debug('Creating relationship for {0} and {1}', self._sim_info, target_sim_id)
            relationship = Relationship(self, self._sim_info.sim_id, target_sim_id)
            self._relationships[target_sim_id] = relationship
            relationship.add_neighbor_bit_if_necessary(self._sim_info)
            for multiplier in self._relationship_multipliers.values():
                self._apply_relationship_multiplier_to_relationship(relationship, multiplier)
            self._create_relationship_callbacks(relationship)
            return relationship

    def _build_printable_string_of_bits(self, target_sim_id):
        relationship = self._find_relationship(target_sim_id)
        if relationship:
            return relationship.build_printable_string_of_bits()
        return ''

    def _build_printable_string_of_tracks(self, target_sim_id):
        relationship = self._find_relationship(target_sim_id)
        if relationship:
            return relationship.build_printable_string_of_tracks()
        return ''

    def _send_relationship_prechange_event(self, target_sim_id):
        services.get_event_manager().process_event(event_testing.test_events.TestEvent.PrerelationshipChanged, self._sim_info, sim_id=self._sim_info.id, target_sim_id=target_sim_id)

    def _send_relationship_changed_event(self, target_sim_id):
        services.get_event_manager().process_event(event_testing.test_events.TestEvent.RelationshipChanged, sim_info=self._sim_info, sim_id=self._sim_info.id, target_sim_id=target_sim_id)

class RelbitPickerSuperInteraction(PickerSuperInteraction):
    __qualname__ = 'RelbitPickerSuperInteraction'
    INSTANCE_TUNABLES = {'is_add': Tunable(description='\n                If this interaction is trying to add a relbit to the\n                sim->target or to remove a relbit from the sim->target.', tunable_type=bool, default=True)}

    @flexmethod
    def _test(cls, inst, target, context, **kwargs):
        if target is context.sim:
            return TestResult(False, 'Cannot run rel picker as a self interaction.')
        inst_or_cls = inst if inst is not None else cls
        return super(PickerSuperInteraction, inst_or_cls)._test(target, context, **kwargs)

    def _run_interaction_gen(self, timeline):
        self._show_picker_dialog(self.sim, target_sim=self.target)
        return True

    @classmethod
    def _bit_selection_gen(cls, target, context):
        bit_manager = services.get_instance_manager(sims4.resources.Types.RELATIONSHIP_BIT)
        rel_tracker = context.sim.sim_info.relationship_tracker
        target_sim_id = target.sim_id
        if cls.is_add:
            for bit in bit_manager.types.values():
                while bit.is_rel_bit and not rel_tracker.has_bit(target_sim_id, bit):
                    yield bit
        else:
            for bit in rel_tracker.get_all_bits(target_sim_id=target_sim_id):
                yield bit

    @flexmethod
    def picker_rows_gen(cls, inst, target, context, **kwargs):
        for bit in cls._bit_selection_gen(target, context):
            row = ObjectPickerRow(name=bit.display_name, icon=bit.icon, row_description=bit.bit_description, tag=bit)
            yield row

    def on_choice_selected(self, choice_tag, **kwargs):
        bit = choice_tag
        rel_tracker = self.sim.sim_info.relationship_tracker
        target_sim_id = self.target.sim_id
        if bit is not None:
            if self.is_add:
                rel_tracker.add_relationship_bit(target_sim_id, bit, force_add=True)
            else:
                rel_tracker.remove_relationship_bit(target_sim_id, bit)

