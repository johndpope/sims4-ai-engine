import weakref
from broadcasters.broadcaster_effect import TunableBroadcasterEffectVariant
from event_testing.resolver import DoubleObjectResolver
from interactions.constraints import TunableGeometricConstraintVariant, Anywhere
from sims4.tuning.instances import HashedTunedInstanceMetaclass
from sims4.tuning.tunable import HasTunableReference, TunableList, TunableVariant, TunableTuple, Tunable, TunableSimMinute, OptionalTunable
from socials.clustering import ObjectClusterRequest
from uid import unique_id
import services
import sims4.log
import sims4.resources
logger = sims4.log.Logger('Broadcaster', default_owner='epanero')

class _BroadcasterLosComponent:
    __qualname__ = '_BroadcasterLosComponent'

    def __init__(self, broadcaster):
        self.broadcaster = broadcaster

    @property
    def constraint(self):
        return self.broadcaster.get_constraint()

    @property
    def default_position(self):
        broadcasting_object = self.broadcaster.broadcasting_object
        return broadcasting_object.intended_position + broadcasting_object.intended_forward*0.1

@unique_id('broadcaster_id')
class Broadcaster(HasTunableReference, metaclass=HashedTunedInstanceMetaclass, manager=services.get_instance_manager(sims4.resources.Types.BROADCASTER)):
    __qualname__ = 'Broadcaster'
    FREQUENCY_ENTER = 0
    FREQUENCY_PULSE = 1
    INSTANCE_TUNABLES = {'constraints': TunableList(description='\n            A list of constraints that define the area of influence of this\n            broadcaster. It is required that at least one constraint be defined.\n            ', tunable=TunableGeometricConstraintVariant()), 'effects': TunableList(description='\n            A list of effects that are applied to Sims and objects affected by\n            this broadcaster.\n            ', tunable=TunableBroadcasterEffectVariant()), 'frequency': TunableVariant(description='\n            Define in what instances and how often this broadcaster affects Sims\n            and objects in its area of influence.\n            ', on_enter=TunableTuple(description='\n                Sims and objects are affected by this broadcaster when they\n                enter in its area of influence, or when the broadcaster is\n                created.\n                ', locked_args={'frequency_type': FREQUENCY_ENTER}, allow_multiple=Tunable(description="\n                    If checked, then Sims may react multiple times if they re-\n                    enter the broadcaster's area of influence. If unchecked,\n                    then Sims will only react to the broadcaster once.\n                    ", tunable_type=bool, needs_tuning=True, default=False)), on_pulse=TunableTuple(description='\n                Sims and objects are constantly affected by this broadcaster\n                while they are in its area of influence.\n                ', locked_args={'frequency_type': FREQUENCY_PULSE}, cooldown_time=TunableSimMinute(description='\n                    The time interval between broadcaster pulses. Sims would not\n                    react to the broadcaster for at least this amount of time\n                    while in its area of influence.\n                    ', default=8)), default='on_pulse'), 'clustering': OptionalTunable(description='\n            If set, then similar broadcasters, i.e. broadcasters of the same\n            instance, will be clustered together if their broadcasting objects\n            are close by. This improves performance and avoids having Sims react\n            multiple times to similar broadcasters. When broadcasters are\n            clustered together, there is no guarantee as to what object will be\n            used for testing purposes.\n            \n            e.g. Stinky food reactions are clustered together. A test on the\n            broadcaster should not, for example, differentiate between a stinky\n            lobster and a stinky steak, because the broadcasting object is\n            arbitrary and undefined.\n            \n            e.g. Jealousy reactions are not clustered together. A test on the\n            broadcaster considers the relationship between two Sims. Therefore,\n            it would be unwise to consider an arbitrary Sim if two jealousy\n            broadcasters are close to each other.\n            ', tunable=ObjectClusterRequest.TunableFactory(description='\n                Specify how clusters for this particular broadcaster are formed.\n                ', locked_args={'minimum_size': 1}), enabled_by_default=True), 'allow_objects': Tunable(description='\n            If checked, then in addition to all instantiated Sims, all objects\n            will be affected by this broadcaster. Some tuned effects might still\n            only apply to Sims (e.g. affordance pushing).\n            \n            Checking this tuning field has performance repercussions, as it\n            means we have to process a lot more data during broadcaster pings.\n            Please use this sporadically.\n            ', tunable_type=bool, default=False)}

    @classmethod
    def _verify_tuning_callback(cls):
        if not cls.constraints:
            logger.error('Broadcaster {} does not define any constraints.', cls)

    @classmethod
    def register_static_callbacks(cls, *args, **kwargs):
        for broadcaster_effect in cls.effects:
            broadcaster_effect.register_static_callbacks(*args, **kwargs)

    def __init__(self, *args, broadcasting_object, interaction=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._broadcasting_object_ref = weakref.ref(broadcasting_object, self._on_broadcasting_object_deleted)
        self._interaction = interaction
        self._constraint = None
        self._affected_objects = weakref.WeakKeyDictionary()
        self._current_objects = weakref.WeakSet()
        self._linked_broadcasters = weakref.WeakSet()
        broadcasting_object.register_on_location_changed(self._on_broadcasting_object_moved)
        self._quadtree = None
        self._cluster_request = None

    @property
    def broadcasting_object(self):
        if self._broadcasting_object_ref is not None:
            return self._broadcasting_object_ref()

    @property
    def interaction(self):
        return self._interaction

    @property
    def quadtree(self):
        return self._quadtree

    @property
    def cluster_request(self):
        return self._cluster_request

    def _on_broadcasting_object_deleted(self, _):
        current_zone = services.current_zone()
        if current_zone is not None:
            broadcaster_service = current_zone.broadcaster_service
            if broadcaster_service is not None:
                broadcaster_service.remove_broadcaster(self)

    def _on_broadcasting_object_moved(self, *_, **__):
        self.regenerate_constraint()
        current_zone = services.current_zone()
        if current_zone is not None:
            broadcaster_service = current_zone.broadcaster_service
            if broadcaster_service is not None:
                broadcaster_service.update_cluster_request(self)

    def on_processed(self):
        for affected_object in self._affected_objects:
            while affected_object not in self._current_objects:
                self.remove_broadcaster_effect(affected_object)
        self._current_objects.clear()

    def on_removed(self):
        for affected_object in self._affected_objects:
            self.remove_broadcaster_effect(affected_object)
        broadcasting_object = self.broadcasting_object
        if broadcasting_object is not None:
            broadcasting_object.unregister_on_location_changed(self._on_broadcasting_object_moved)

    def on_added_to_quadtree_and_cluster_request(self, quadtree, cluster_request):
        self._quadtree = quadtree
        self._cluster_request = cluster_request

    def can_affect(self, obj):
        if not self.allow_objects and not obj.is_sim:
            return False
        broadcasting_object = self.broadcasting_object
        if broadcasting_object is None:
            return False
        routing_surface = broadcasting_object.routing_surface
        if routing_surface is None or obj.routing_surface != routing_surface:
            return False
        if obj is broadcasting_object:
            return False
        linked_broadcasters = list(self._linked_broadcasters)
        if any(obj is linked_broadcaster.broadcasting_object for linked_broadcaster in linked_broadcasters):
            return False
        return True

    def apply_broadcaster_effect(self, affected_object):
        self._current_objects.add(affected_object)
        if self._should_apply_broadcaster_effect(affected_object):
            self._affected_objects[affected_object] = (services.time_service().sim_now, True)
            for broadcaster_effect in self.effects:
                broadcaster_effect.apply_broadcaster_effect(self, affected_object)
        for linked_broadcaster in self._linked_broadcasters:
            linked_broadcaster._apply_linked_broadcaster_effect(affected_object, self._affected_objects[affected_object])

    def _apply_linked_broadcaster_effect(self, affected_object, data):
        self._apply_linked_broadcaster_data(affected_object, data)
        for broadcaster_effect in self.effects:
            while broadcaster_effect.apply_when_linked:
                broadcaster_effect.apply_broadcaster_effect(self, affected_object)

    def _apply_linked_broadcaster_data(self, affected_object, data):
        if affected_object in self._affected_objects:
            was_in_area = self._affected_objects[affected_object][1]
            is_in_area = data[1]
            if was_in_area and not is_in_area:
                self.remove_broadcaster_effect(affected_object)
        self._affected_objects[affected_object] = data

    def remove_broadcaster_effect(self, affected_object, is_linked=False):
        if not self._affected_objects[affected_object][1]:
            return
        self._affected_objects[affected_object] = (self._affected_objects[affected_object][0], False)
        for broadcaster_effect in self.effects:
            while broadcaster_effect.apply_when_linked or not is_linked:
                broadcaster_effect.remove_broadcaster_effect(self, affected_object)
        if not is_linked:
            for linked_broadcaster in self._linked_broadcasters:
                linked_broadcaster.remove_broadcaster_effect(affected_object, is_linked=True)

    def _should_apply_broadcaster_effect(self, affected_object):
        if self.frequency.frequency_type == self.FREQUENCY_ENTER:
            if affected_object not in self._affected_objects:
                return True
            if self.frequency.allow_multiple and not self._affected_objects[affected_object][1]:
                return True
            return False
        if self.frequency.frequency_type == self.FREQUENCY_PULSE:
            last_reaction = self._affected_objects.get(affected_object, None)
            if last_reaction is None:
                return True
            time_since_last_reaction = services.time_service().sim_now - last_reaction[0]
            if time_since_last_reaction.in_minutes() > self.frequency.cooldown_time:
                return True
            return False

    def clear_linked_broadcasters(self):
        self._linked_broadcasters.clear()

    def set_linked_broadcasters(self, broadcasters):
        self.clear_linked_broadcasters()
        self._linked_broadcasters.update(broadcasters)
        for linked_broadcaster in self._linked_broadcasters:
            linked_broadcaster.clear_linked_broadcasters()
            for (obj, data) in self._affected_objects.items():
                linked_broadcaster._apply_linked_broadcaster_data(obj, data)

    @property
    def has_linked_broadcasters(self):
        if self._linked_broadcasters:
            return True
        return False

    def get_linked_broadcasters_gen(self):
        yield self._linked_broadcasters

    def regenerate_constraint(self, *_, **__):
        self._constraint = None

    def get_constraint(self):
        if self._constraint is None or not self._constraint.valid:
            self._constraint = Anywhere()
            for tuned_constraint in self.constraints:
                self._constraint = self._constraint.intersect(tuned_constraint.create_constraint(None, target=self.broadcasting_object, target_position=self.broadcasting_object.position))
        return self._constraint

    def get_resolver(self, affected_object):
        return DoubleObjectResolver(affected_object, self.broadcasting_object)

    def get_clustering(self):
        broadcasting_object = self.broadcasting_object
        if broadcasting_object is None:
            return
        if broadcasting_object.is_sim:
            return
        if broadcasting_object.is_in_inventory():
            return
        if broadcasting_object.routing_surface is None:
            return
        return self.clustering

    def should_cluster(self):
        return self.get_clustering() is not None

    def get_affected_object_count(self):
        return sum(1 for data in self._affected_objects.values() if data[1])

    @property
    def id(self):
        return self.broadcaster_id

    @property
    def lineofsight_component(self):
        return _BroadcasterLosComponent(self)

    @property
    def position(self):
        return self.broadcasting_object.position

    @property
    def routing_surface(self):
        return self.broadcasting_object.routing_surface

    @property
    def parts(self):
        return self.broadcasting_object.parts

