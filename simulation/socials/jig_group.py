from interactions import ParticipantType
from interactions.constraints import Constraint, Anywhere, create_constraint_set, Nowhere
from interactions.interaction_finisher import FinishingType
from interactions.utils.routing import get_two_person_transforms_for_jig, fgl_and_get_two_person_transforms_for_jig
from sims4.tuning.instances import lock_instance_tunables
from sims4.tuning.tunable import TunableReference, TunableMapping, TunableEnumEntry, Tunable, TunableSimMinute
from socials.side_group import SideGroup
import interactions.constraints
import placement
import services
import sims4.log
import socials.group
logger = sims4.log.Logger('Social Group')

class JigGroup(SideGroup):
    __qualname__ = 'JigGroup'
    INSTANCE_TUNABLES = {'jig': TunableReference(description='\n            The jig to use for finding a place to do the social.', manager=services.definition_manager()), 'participant_slot_map': TunableMapping(description='\n            The slot index mapping on the jig keyed by participant type', key_type=TunableEnumEntry(ParticipantType, ParticipantType.Actor), value_type=Tunable(description='The slot index for the participant type', tunable_type=int, default=0)), 'cancel_delay': TunableSimMinute(description='\n        Amount of time a jig group must be inactive before it will shut down.\n        ', default=15)}
    DEFAULT_SLOT_INDEX_ACTOR = 1
    DEFAULT_SLOT_INDEX_TARGET = 0

    @classmethod
    def _get_jig_transforms(cls, initiating_sim, target_sim, picked_object=None, participant_slot_overrides=None):
        slot_map = cls.participant_slot_map if participant_slot_overrides is None else participant_slot_overrides
        actor_slot_index = slot_map.get(ParticipantType.Actor, cls.DEFAULT_SLOT_INDEX_ACTOR)
        target_slot_index = slot_map.get(ParticipantType.TargetSim, cls.DEFAULT_SLOT_INDEX_TARGET)
        if picked_object is not None and picked_object.carryable_component is None:
            try:
                return get_two_person_transforms_for_jig(picked_object.definition, picked_object.transform, picked_object.routing_surface, actor_slot_index, target_slot_index)
            except RuntimeError:
                pass
        return fgl_and_get_two_person_transforms_for_jig(cls.jig, initiating_sim, actor_slot_index, target_sim, target_slot_index)

    def __init__(self, *args, si=None, target_sim=None, participant_slot_overrides=None, **kwargs):
        super().__init__(si=si, target_sim=target_sim, *args, **kwargs)
        self._sim_transform_map = {}
        self.geometry = None
        initiating_sim = si.sim
        if initiating_sim is None or target_sim is None:
            logger.error('JigGroup {} cannot init with initial sim {()} or target sim {()}', self.__name__, initiating_sim, target_sim)
            return
        picked_object = si.picked_object
        self.participant_slot_overrides = participant_slot_overrides
        (sim_transform, target_transform, routing_surface) = self._get_jig_transforms(initiating_sim, target_sim, picked_object=picked_object, participant_slot_overrides=self.participant_slot_overrides)
        self._jig_transform = target_transform
        if target_transform is not None:
            self._jig_polygon = placement.get_placement_footprint_polygon(target_transform.translation, target_transform.orientation, routing_surface, self.jig.get_footprint(0))
        else:
            self._jig_polygon = None
        self._sim_transform_map[initiating_sim] = sim_transform
        self._sim_transform_map[target_sim] = target_transform
        if target_transform is None:
            self._constraint = Nowhere()
            return
        target_forward = target_transform.transform_vector(sims4.math.FORWARD_AXIS)
        self._set_focus(target_transform.translation, target_forward, routing_surface)
        self._initialize_constraint(notify=True)

    @classmethod
    def _verify_tuning_callback(cls):
        if cls.jig is None:
            logger.error('JigGroup {} must have a jig tuned.', cls.__name__)

    @classmethod
    def make_constraint_default(cls, actor, target_sim, position, routing_surface, participant_type=ParticipantType.Actor, picked_object=None, participant_slot_overrides=None):
        (actor_transform, target_transform, routing_surface) = cls._get_jig_transforms(actor, target_sim, picked_object=picked_object, participant_slot_overrides=participant_slot_overrides)
        if actor_transform is None or target_transform is None:
            return Nowhere()
        if participant_type == ParticipantType.Actor:
            constraint_transform = actor_transform
        elif participant_type == ParticipantType.TargetSim:
            constraint_transform = target_transform
        else:
            return Anywhere()
        return interactions.constraints.Transform(constraint_transform, routing_surface=routing_surface, debug_name='JigGroupConstraint')

    def _relocate_group_around_focus(self, *args, **kwargs):
        return False

    @property
    def group_radius(self):
        if self._jig_polygon is not None:
            return self._jig_polygon.radius()
        return 0

    @property
    def jig_polygon(self):
        return self._jig_polygon

    @property
    def jig_transform(self):
        return self._jig_transform

    def get_constraint(self, sim):
        transform = self._sim_transform_map.get(sim, None)
        if transform is not None:
            return interactions.constraints.Transform(transform, routing_surface=self.routing_surface)
        if sim in self._sim_transform_map:
            return Nowhere()
        return Anywhere()

    def _make_constraint(self, *args, **kwargs):
        if self._constraint is None:
            constraints = [interactions.constraints.Transform(t, routing_surface=self.routing_surface) for t in self._sim_transform_map.values()]
            self._constraint = create_constraint_set(constraints) if constraints else Anywhere()
        return self._constraint

    _create_adjustment_alarm = socials.group.SocialGroup._create_adjustment_alarm

    def _consider_adjusting_sim(self, sim=None, initial=False):
        if not initial:
            for sim in self:
                for _ in self.queued_mixers_gen(sim):
                    pass
            if self.time_since_interaction().in_minutes() < self.cancel_delay:
                return
            self.shutdown(FinishingType.NATURAL)

lock_instance_tunables(JigGroup, social_anchor_object=None)
