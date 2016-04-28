import itertools
import math
import random
from interactions.social.social_super_interaction import SocialSuperInteraction
from situations.ambient.walkby_ambient_situation import WalkbyAmbientSituation
import alarms
import clock
import gsi_handlers
import services
import sims4.log
import sims4.service_manager
import sims4.tuning.tunable
import situations.situation_guest_list
import terrain
import world.lot_tuning
logger = sims4.log.Logger('Ambient')
with sims4.reload.protected(globals()):
    gsi_logging_enabled = False

class _AmbientSource:
    __qualname__ = '_AmbientSource'

    def __init__(self, priority_multiplier):
        self._running_situation_ids = []
        self._priority_multipler = priority_multiplier

    def is_valid(self):
        raise NotImplemented

    def get_priority(self):
        imbalance = self.get_desired_number_of_sims() - self.get_current_number_of_sims()
        return imbalance*self._priority_multipler

    def get_desired_number_of_sims(self):
        raise NotImplemented

    def get_current_number_of_sims(self):
        self._cleanup_running_situations()
        return len(self._running_situation_ids)

    def start_appropriate_situation(self, time_of_day=None):
        raise NotImplemented

    def create_standard_ambient_guest_list(self, situation_type):
        client = services.client_manager().get_first_client()
        if client is None:
            logger.warn('No clients found when trying to get the active sim for ambient autonomy.', owner='sscholl')
            return
        active_sim = client.active_sim
        if active_sim is None:
            return
        guest_list = situations.situation_guest_list.SituationGuestList(invite_only=True, host_sim_id=active_sim.id)
        if situation_type.default_job() is not None:
            guest_info = situations.situation_guest_list.SituationGuestInfo.construct_from_purpose(0, situation_type.default_job(), situations.situation_guest_list.SituationInvitationPurpose.WALKBY)
            guest_list.add_guest_info(guest_info)
        return guest_list

    def get_running_situations(self):
        situations = []
        situation_manager = services.current_zone().situation_manager
        for situation_id in self._running_situation_ids:
            situation = situation_manager.get(situation_id)
            while situation is not None:
                situations.append(situation)
        return situations

    def _start_specific_situation(self, situation_type):
        situation_manager = services.current_zone().situation_manager
        guest_list = self.create_standard_ambient_guest_list(situation_type)
        situation_id = situation_manager.create_situation(situation_type, guest_list=guest_list, user_facing=False)
        if situation_id is not None:
            self._running_situation_ids.append(situation_id)
        return situation_id

    def _cleanup_running_situations(self):
        situation_manager = services.current_zone().situation_manager
        to_delete_ids = []
        for situation_id in self._running_situation_ids:
            while situation_id not in situation_manager:
                to_delete_ids.append(situation_id)
        for delete_id in to_delete_ids:
            self._running_situation_ids.remove(delete_id)

    def get_gsi_description(self):
        return 'Unknown, {0}, {1}'.format(self.get_desired_number_of_sims(), self.get_current_number_of_sims())

class _AmbientSourceStreet(_AmbientSource):
    __qualname__ = '_AmbientSourceStreet'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        lot_tuning = world.lot_tuning.LotTuningMaps.get_lot_tuning()
        if lot_tuning:
            self._walkby_tuning = lot_tuning.walkby
        else:
            self._walkby_tuning = None

    def is_valid(self):
        return self._walkby_tuning is not None

    def get_desired_number_of_sims(self):
        if not self._walkby_tuning:
            return 0
        return self._walkby_tuning.get_desired_sim_count()

    def start_appropriate_situation(self, time_of_day=None):
        if not self._walkby_tuning:
            return
        situation_type = self._walkby_tuning.get_ambient_walkby_situation()
        if situation_type is None:
            return
        return self._start_specific_situation(situation_type)

    def get_gsi_description(self):
        if self._walkby_tuning is None:
            street = 'Unknown Street'
        else:
            street = self._walkby_tuning.__name__
        return '({0}, {1}, {2})'.format(street, self.get_desired_number_of_sims(), self.get_current_number_of_sims())

class _AmbientSourceActiveLotVenueType(_AmbientSource):
    __qualname__ = '_AmbientSourceActiveLotVenueType'

    def is_valid(self):
        return True

    def get_desired_number_of_sims(self):
        return 0

    def start_appropriate_situation(self, time_of_day=None):
        ambient_service = services.current_zone().ambient_service
        situation_type = ambient_service.TEST_WALKBY_SITUATION
        if situation_type is None:
            return
        return self._start_specific_situation(situation_type)

    def get_gsi_description(self):
        return '(Active Venue, {0}, {1})'.format(self.get_desired_number_of_sims(), self.get_current_number_of_sims())

class AmbientService(sims4.service_manager.Service):
    __qualname__ = 'AmbientService'
    TEST_WALKBY_SITUATION = sims4.tuning.tunable.TunableReference(description='\n                                            A walkby situation for testing.\n                                            ', manager=services.get_instance_manager(sims4.resources.Types.SITUATION))
    SOCIAL_AFFORDANCES = sims4.tuning.tunable.TunableList(description='\n        When selected for a walkby social the sim runs one of the social\n        affordances in this list.\n        ', tunable=SocialSuperInteraction.TunableReference())
    SOCIAL_COOLDOWN = sims4.tuning.tunable.TunableSimMinute(description='\n            The minimum amount of time from the end of one social\n            until the walkby sim can perform another social. If it is too small\n            sims may socialize, stop, then start socializing again.\n            ', default=60, minimum=30, maximum=480)
    SOCIAL_MAX_DURATION = sims4.tuning.tunable.TunableSimMinute(description='\n            The maximum amount of time the sims can socialize.\n            ', default=60, minimum=1, maximum=180)
    SOCIAL_MAX_START_DISTANCE = sims4.tuning.geometric.TunableDistanceSquared(description='\n            Walkby Sims must be less than this distance apart for a social\n            to be started.\n            ', default=10)
    SOCIAL_VIEW_CONE_ANGLE = sims4.tuning.tunable.TunableAngle(description='\n            For 2 sims to be able to socialize at least one sim must be in the\n            view cone of the other. This tunable defines the view cone as an angle\n            in degrees centered straight out in front of the sim. 0 degrees would \n            make the sim blind, 360 degrees means the sim can see in all directions.\n            ', default=sims4.math.PI)
    SOCIAL_CHANCE_TO_START = sims4.tuning.tunable.TunablePercent(description='\n            This is the percentage chance, per pair of properly positioned sims,\n            that a social will be started on an ambient service ping.\n\n            The number of pairs of sims is multiplied by this tunable to get the overall\n            chance of a social starting.\n            \n            For the purposes of these examples, we assume that the tuned value is 25%\n            \n            1 pair of sims -> 25%.\n            2 pairs of sims -> 50%\n            4 pairs of sims -> 100%.\n\n            ', default=100)

    def __init__(self):
        self._update_alarm_handle = None
        self._flavor_alarm_handle = None
        self._sources = []

    def stop(self):
        if self._update_alarm_handle is not None:
            alarms.cancel_alarm(self._update_alarm_handle)
            self._update_alarm_handle = None
        if self._flavor_alarm_handle is not None:
            alarms.cancel_alarm(self._flavor_alarm_handle)
            self._flavor_alarm_handle = None

    def begin_walkbys(self):
        self._sources.append(_AmbientSourceStreet(2.1))
        self._update_alarm_handle = alarms.add_alarm(self, clock.interval_in_sim_minutes(5), self._update_alarm_callback, repeating=True, use_sleep_time=False)
        self._flavor_alarm_handle = alarms.add_alarm(self, clock.interval_in_sim_minutes(1), self._flavor_alarm_callback, repeating=True, use_sleep_time=False)

    def debug_update(self):
        return self._update(force_create=True)

    def _update_alarm_callback(self, alarm_handle=None):
        client = services.client_manager().get_first_client()
        if client is None:
            return
        self._update()

    def _update(self, force_create=False):
        if services.get_super_speed_three_service().in_or_has_requested_super_speed_three():
            gsi_handlers.ambient_handlers.archive_ambient_data('In super speed 3 mode')
            return
        if not self._sources:
            return
        if gsi_handlers.ambient_handlers.archiver.enabled:
            gsi_description = self.get_gsi_description()
        else:
            gsi_description = None
        sources_and_priorities = [(source, source.get_priority()) for source in self._sources]
        sources_and_priorities.sort(key=lambda source: source[1], reverse=True)
        situation_id = None
        source = sources_and_priorities[0][0]
        priority = sources_and_priorities[0][1]
        if priority > 0:
            situation_id = source.start_appropriate_situation()
        elif force_create:
            for (source, _) in sources_and_priorities:
                situation_id = source.start_appropriate_situation()
                while situation_id is not None:
                    break
        if gsi_handlers.ambient_handlers.archiver.enabled:
            if situation_id is not None:
                situation = services.current_zone().situation_manager.get(situation_id)
                gsi_description += '    Created {}'.format(situation)
            gsi_handlers.ambient_handlers.archive_ambient_data(gsi_description)
        return situation_id

    def _flavor_alarm_callback(self, _):
        if not self._sources:
            return
        social_available_sim_to_situation = {}
        flavor_available_sim_to_situation = {}
        for source in self._sources:
            for situation in source.get_running_situations():
                while isinstance(situation, WalkbyAmbientSituation):
                    sim = situation.get_sim_available_for_social()
                    if sim is not None:
                        social_available_sim_to_situation[sim] = situation
                    sim = situation.get_sim_available_for_walkby_flavor()
                    if sim is not None:
                        flavor_available_sim_to_situation[sim] = situation
        social_available_sims = list(social_available_sim_to_situation.keys())
        available_social_pairs = []
        for (actor_sim, target_sim) in itertools.combinations(social_available_sims, 2):
            while self._can_sims_start_social(actor_sim, target_sim):
                available_social_pairs.append((actor_sim, target_sim))
        if available_social_pairs and sims4.random.random_chance(len(available_social_pairs)*self.SOCIAL_CHANCE_TO_START*100):
            (actor_sim, target_sim) = available_social_pairs[random.randint(0, len(available_social_pairs) - 1)]
            social_available_sim_to_situation[actor_sim].start_social(social_available_sim_to_situation[target_sim])
            flavor_available_sim_to_situation.pop(actor_sim, None)
            flavor_available_sim_to_situation.pop(target_sim, None)
        for situation in flavor_available_sim_to_situation.values():
            while situation.random_chance_to_start_flavor_interaction():
                situation.start_flavor_interaction()
                break

    def _sim_forward_to_sim_dot(self, sim_one, sim_two):
        one_to_two = sim_two.position - sim_one.position
        one_to_two.y = 0
        if sims4.math.vector3_almost_equal(one_to_two, sims4.math.Vector3.ZERO()):
            return 1
        one_to_two = sims4.math.vector_normalize(one_to_two)
        one_to_two_dot = sims4.math.vector_dot_2d(sims4.math.vector_flatten(sim_one.forward), one_to_two)
        return one_to_two_dot

    def _can_sims_start_social(self, actor_sim, target_sim):
        distance_squared = (actor_sim.position - target_sim.position).magnitude_squared()
        if distance_squared > self.SOCIAL_MAX_START_DISTANCE:
            return False
        cone_dot = math.cos(self.SOCIAL_VIEW_CONE_ANGLE*0.5)
        actor_to_target_dot = self._sim_forward_to_sim_dot(actor_sim, target_sim)
        if actor_to_target_dot <= cone_dot:
            target_to_actor_dot = self._sim_forward_to_sim_dot(target_sim, actor_sim)
            if target_to_actor_dot <= cone_dot:
                return False
        if terrain.is_position_in_street(actor_sim.position):
            return False
        if terrain.is_position_in_street(target_sim.position):
            return False
        middle_position = (actor_sim.position + target_sim.position)*0.5
        if terrain.is_position_in_street(middle_position):
            return False
        return True

    def get_gsi_description(self):
        if not self._sources:
            return ''
        description = self._sources[0].get_gsi_description()
        for source in self._sources[1:]:
            description = description + '   ' + source.get_gsi_description()
        return description

