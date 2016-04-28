import random
from date_and_time import create_time_span
from distributor.ops import Op
from distributor.system import Distributor
from event_testing.resolver import SingleSimResolver
from event_testing.tests import TunableTestSet
from interactions import ParticipantType
from interactions.utils.tunable_icon import TunableIconVariant
from protocolbuffers import DistributorOps_pb2 as protocols, Sims_pb2
from sims4.tuning.instances import HashedTunedInstanceMetaclass
from sims4.tuning.tunable import Tunable, TunableVariant, TunableList, TunableEnumEntry, TunableResourceKey, TunableEnumFlags, TunableFactory, TunableRange, TunablePercent, AutoFactoryInit, HasTunableFactory, HasTunableReference, TunableReference, TunableTuple, HasTunableSingletonFactory
from sims4.tuning.tunable_base import FilterTag
from singletons import DEFAULT
import assertions
import elements
import enum
import gsi_handlers
import services
import sims4.log
import sims4.random
import sims4.resources
logger = sims4.log.Logger('Balloons')

class BalloonTypeEnum(enum.Int):
    __qualname__ = 'BalloonTypeEnum'
    THOUGHT = 0
    SPEECH = 1
    DISTRESS = 2

class BalloonIcon(HasTunableFactory, AutoFactoryInit):
    __qualname__ = 'BalloonIcon'
    FACTORY_TUNABLES = {'weight': TunableRange(description='\n            The weight to assign to this balloon.\n            ', tunable_type=float, default=1, minimum=1), 'balloon_type': TunableEnumEntry(description='\n            The visual style of the balloon background. For example if it is a\n            speech balloon or a thought balloon.\n            ', tunable_type=BalloonTypeEnum, needs_tuning=True, default=BalloonTypeEnum.THOUGHT), 'icon': TunableIconVariant(description='\n            The Icon that will be showed within the balloon.\n            '), 'overlay': TunableResourceKey(description='\n            The overlay for the balloon, if present.\n            ', default=None, resource_types=sims4.resources.CompoundTypes.IMAGE), 'debug_overlay_override': TunableResourceKey(description='\n            The overlay for the balloon in debug, if present. This overlay will\n            be placed on the balloon instead of overlay in debug only.\n            ', default=None, tuning_filter=FilterTag.EXPERT_MODE, resource_types=sims4.resources.CompoundTypes.IMAGE)}

    def get_balloon_icons(self, resolver, balloon_type=DEFAULT, gsi_entries=None, gsi_category=None, gsi_interaction=None, gsi_balloon_target_override=None, gsi_test_result=None):
        if balloon_type is not DEFAULT:
            self.balloon_type = balloon_type
        if gsi_entries is not None:
            setattr(self, 'gsi_category', gsi_category)
            gsi_entries.append({'test_result': str(gsi_test_result), 'balloon_type': str(self.balloon_type), 'weight': self.weight, 'icon': str(self.icon(gsi_interaction, balloon_target_override=gsi_balloon_target_override)), 'balloon_category': self.gsi_category})
        if gsi_test_result is None or gsi_test_result:
            return [(self.weight, self)]
        return ()

class BalloonVariant(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'BalloonVariant'
    FACTORY_TUNABLES = {'tests': TunableTestSet(description='\n            A set of tests that are run when selecting the balloon icon.  If the\n            tests do not pass then this balloon icon will not be selected.\n            ')}

    @TunableFactory.factory_option
    def balloon_type(balloon_type=DEFAULT):
        return {'item': TunableVariant(balloon_icon=BalloonIcon.TunableFactory(locked_args={} if balloon_type is DEFAULT else {'balloon_type': balloon_type}), balloon_category=TunableReference(services.get_instance_manager(sims4.resources.Types.BALLOON)), default='balloon_icon')}

    def get_balloon_icons(self, resolver, gsi_test_result=None, **kwargs):
        if gsi_test_result is None or gsi_test_result:
            test_result = self.tests.run_tests(resolver)
        else:
            test_result = gsi_test_result
        if test_result or gsi_handlers.balloon_handlers.archiver.enabled:
            return self.item().get_balloon_icons(resolver, gsi_test_result=test_result, **kwargs)
        return []

class BalloonCategory(HasTunableReference, metaclass=HashedTunedInstanceMetaclass, manager=services.get_instance_manager(sims4.resources.Types.BALLOON)):
    __qualname__ = 'BalloonCategory'
    INSTANCE_TUNABLES = {'balloon_type': TunableEnumEntry(description='\n             The visual style of the balloon background.\n             ', tunable_type=BalloonTypeEnum, needs_tuning=True, default=BalloonTypeEnum.THOUGHT), 'balloon_chance': TunablePercent(description='\n             The chance that a balloon from the list is actually shown.\n             ', default=100), 'balloons': TunableList(description='\n             The list of possible balloons.\n             ', tunable=BalloonVariant.TunableFactory(balloon_type=None))}

    @classmethod
    def get_balloon_icons(cls, resolver, balloon_type=DEFAULT, gsi_category=None, **kwargs):
        if gsi_category is None:
            gsi_category = cls.__name__
        else:
            gsi_category = '{}/{}'.format(gsi_category, cls.__name__)
        possible_balloons = []
        if random.random() <= cls.balloon_chance:
            for balloon in cls.balloons:
                for balloon_icon in balloon.get_balloon_icons(resolver, balloon_type=cls.balloon_type, gsi_category=gsi_category, **kwargs):
                    while balloon_icon:
                        possible_balloons.append(balloon_icon)
        return possible_balloons

class BalloonRequest(elements.Element):
    __qualname__ = 'BalloonRequest'
    __slots__ = ['_sim_ref', 'icon', 'icon_object', 'overlay', 'balloon_type', 'priority', 'duration', 'delay', 'delay_randomization']

    def __init__(self, sim, icon, icon_object, overlay, balloon_type, priority, duration, delay, delay_randomization):
        super().__init__()
        self._sim_ref = sim.ref()
        self.icon = icon
        self.icon_object = icon_object
        self.overlay = overlay
        self.balloon_type = balloon_type
        self.priority = priority
        self.duration = duration
        self.delay = delay
        self.delay_randomization = delay_randomization

    @property
    def _sim(self):
        if self._sim_ref is not None:
            return self._sim_ref()

    def _run(self, timeline):
        return self.distribute()

    def distribute(self):
        sim = self._sim
        if sim is not None and not sim.is_hidden():
            balloon_op = AddBalloon(self, sim)
            distributor = Distributor.instance()
            distributor.add_op(sim, balloon_op)
            return True
        return False

BALLOON_TYPE_LOOKUP = {BalloonTypeEnum.THOUGHT: (Sims_pb2.AddBalloon.THOUGHT_TYPE, Sims_pb2.AddBalloon.THOUGHT_PRIORITY), BalloonTypeEnum.SPEECH: (Sims_pb2.AddBalloon.SPEECH_TYPE, Sims_pb2.AddBalloon.SPEECH_PRIORITY), BalloonTypeEnum.DISTRESS: (Sims_pb2.AddBalloon.DISTRESS_TYPE, Sims_pb2.AddBalloon.MOTIVE_FAILURE_PRIORITY)}

class TunableBalloon(TunableFactory):
    __qualname__ = 'TunableBalloon'
    X_ACTOR_EVENT = 710
    Y_ACTOR_EVENT = 711
    BALLOON_DURATION = Tunable(float, 3.0, description='The duration, in seconds, that a balloon should last.')

    @staticmethod
    def factory(interaction, balloon_target, balloon_choices, balloon_delay, balloon_delay_random_offset, balloon_chance, used_sim_set=None, balloon_target_override=None, sequence=None, **kwargs):
        balloon_requests = []
        if interaction is None:
            return balloon_requests
        roll = random.uniform(0, 1)
        if roll > balloon_chance:
            return balloon_requests
        if used_sim_set is None:
            used_sim_set = set()
        resolver = interaction.get_resolver()
        if balloon_target == ParticipantType.Invalid:
            logger.error('Balloon Request has no Balloon Target, interaction: {}.', interaction)
            return []
        balloon_sims = interaction.get_participants(balloon_target)
        for sim in balloon_sims:
            if sim in used_sim_set:
                logger.error('A sim has multiple balloons tuned for this interaction. This is not supported. Interaction: {}.', interaction)
            else:
                if gsi_handlers.balloon_handlers.archiver.enabled:
                    gsi_entries = []
                else:
                    gsi_entries = None
                balloon_icon = TunableBalloon.select_balloon_icon(balloon_choices, resolver, gsi_entries=gsi_entries, gsi_interaction=interaction, gsi_balloon_target_override=balloon_target_override)
                if balloon_icon is not None:
                    icon_info = balloon_icon.icon(interaction, balloon_target_override=balloon_target_override)
                else:
                    icon_info = None
                if gsi_handlers.balloon_handlers.archiver.enabled:
                    gsi_handlers.balloon_handlers.archive_balloon_data(sim, interaction, balloon_icon, icon_info, gsi_entries)
                while balloon_icon is not None:
                    used_sim_set.add(sim)
                    if icon_info[0] is None and icon_info[1] is None:
                        pass
                    (balloon_type, priority) = BALLOON_TYPE_LOOKUP[balloon_icon.balloon_type]
                    balloon_overlay = balloon_icon.overlay
                    request = BalloonRequest(sim, icon_info[0], icon_info[1], balloon_overlay, balloon_type, priority, TunableBalloon.BALLOON_DURATION, balloon_delay, balloon_delay_random_offset)
                    balloon_requests.append(request)
        if sequence is not None:
            return (balloon_requests, sequence)
        return balloon_requests

    FACTORY_TYPE = factory

    def __init__(self, *args, **kwargs):
        super().__init__(balloon_target=TunableEnumFlags(ParticipantType, ParticipantType.Invalid, description='\n                                                             Who to play balloons over relative to the interaction. \n                                                             Generally, balloon tuning will use either balloon_animation_target \n                                                             or balloon_target.'), balloon_choices=TunableList(description='\n                             A list of the balloons and balloon categories\n                             ', tunable=BalloonVariant.TunableFactory()), balloon_delay=Tunable(float, None, description='\n                             If set, the number of seconds after the start of the animation to \n                             trigger the balloon. A negative number will count backwards from the \n                             end of the animation.'), balloon_delay_random_offset=TunableRange(float, 0, minimum=0, description='\n                             The amount of randomization that is added to balloon requests. \n                             Will always offset the delay time later, and requires the delay \n                             time to be set to a number. A value of 0 has no randomization.'), balloon_chance=TunablePercent(100, description='\n                             The chance that the balloon will play.'), **kwargs)

    @staticmethod
    def get_balloon_requests(interaction, overrides):
        balloon_requests = []
        used_sim_set = set()
        for balloon in overrides.balloons:
            new_balloon_requests = balloon(interaction, used_sim_set=used_sim_set, balloon_target_override=overrides.balloon_target_override)
            balloon_requests.extend(new_balloon_requests)
        return balloon_requests

    @staticmethod
    def _get_balloon_icons(balloon_choices, resolver, **kwargs):
        possible_balloons = []
        for balloon in balloon_choices:
            balloons = balloon.get_balloon_icons(resolver, **kwargs)
            possible_balloons.extend(balloons)
        return possible_balloons

    @staticmethod
    def select_balloon_icon(balloon_choices, resolver, **kwargs):
        possible_balloons = TunableBalloon._get_balloon_icons(balloon_choices, resolver, **kwargs)
        chosen_balloon = sims4.random.weighted_random_item(possible_balloons)
        return chosen_balloon

class AddBalloon(Op):
    __qualname__ = 'AddBalloon'

    def __init__(self, balloon_request, sim):
        super().__init__()
        self.balloon_request = balloon_request
        self.sim_id = sim.id

    def write(self, msg):
        balloon_msg = Sims_pb2.AddBalloon()
        balloon_msg.sim_id = self.sim_id
        if self.balloon_request.icon is not None:
            balloon_msg.icon.type = self.balloon_request.icon.type
            balloon_msg.icon.group = self.balloon_request.icon.group
            balloon_msg.icon.instance = self.balloon_request.icon.instance
        if self.balloon_request.icon_object is None:
            balloon_msg.icon_object.manager_id = 0
            balloon_msg.icon_object.object_id = 0
        else:
            (balloon_msg.icon_object.object_id, balloon_msg.icon_object.manager_id) = self.balloon_request.icon_object.icon_info
        if self.balloon_request.overlay is not None:
            balloon_msg.overlay.type = self.balloon_request.overlay.type
            balloon_msg.overlay.group = self.balloon_request.overlay.group
            balloon_msg.overlay.instance = self.balloon_request.overlay.instance
        balloon_msg.type = self.balloon_request.balloon_type
        balloon_msg.priority = self.balloon_request.priority
        balloon_msg.duration = self.balloon_request.duration
        msg.type = protocols.Operation.ADD_BALLOON
        msg.data = balloon_msg.SerializeToString()

class PassiveBalloons:
    __qualname__ = 'PassiveBalloons'

    @staticmethod
    def _validate_tuning(instance_class, tunable_name, source, value):
        if PassiveBalloons.BALLOON_LOCKOUT + PassiveBalloons.BALLOON_RANDOM >= PassiveBalloons.BALLOON_LONG_LOCKOUT:
            logger.error('PassiveBalloons tuning value error! BALLOON_LONG_LOCKOUT must be tuned to be greater than BALLOON_LOCKOUT + BALLOON_RANDOM')

    BALLOON_LOCKOUT = Tunable(int, 10, description='The duration, in minutes, for the lockout time between displaying passive balloons.')
    BALLOON_RANDOM = Tunable(int, 20, description='The duration, in minutes, for a random amount to be added to the lockout time between displaying passive balloons.')
    BALLOON_LONG_LOCKOUT = Tunable(int, 120, callback=_validate_tuning, description='The duration, in minutes, to indicate that a long enough time has passed since the                                     last balloon, to trigger a delay of the next balloon by the random amount of time from BALLOON_RANDOM. The reason for this is so that                                     newly spawned walkby sims that begin routing do not display their first routing balloon immediately. Make sure that this is always                                     higher than the tuned values in BALLOON_LOCKOUT + BALLOON_RANDOM, or it will not work as intended.')
    MAX_NUM_BALLOONS = Tunable(int, 25, description='The maximum number of passive balloon tuning data entries to process per balloon display attempt')
    ROUTING_BALLOONS = TunableList(description='\n        A weighted list of passive routing balloons.\n        ', tunable=TunableTuple(balloon=TunableBalloon(locked_args={'balloon_delay': 0, 'balloon_delay_random_offset': 0, 'balloon_chance': 100, 'balloon_target': None}), weight=Tunable(tunable_type=int, default=1)))

    @staticmethod
    def request_routing_to_object_balloon(sim, interaction):
        balloon_tuning = interaction.route_start_balloon
        if balloon_tuning is None:
            return
        if interaction.is_user_directed and not balloon_tuning.also_show_user_directed:
            return
        balloon_requests = balloon_tuning.balloon(interaction)
        if balloon_requests:
            choosen_balloon = random.choice(balloon_requests)
            if choosen_balloon is not None:
                choosen_balloon.distribute()

    @staticmethod
    def create_passive_ballon_request(sim, balloon_data):
        if gsi_handlers.balloon_handlers.archiver.enabled:
            gsi_entries = []
        else:
            gsi_entries = None
        resolver = SingleSimResolver(sim.sim_info)
        balloon_icon = TunableBalloon.select_balloon_icon(balloon_data.balloon_choices, resolver, gsi_entries=gsi_entries, gsi_interaction=None, gsi_balloon_target_override=None)
        if balloon_icon is not None:
            icon_info = balloon_icon.icon(resolver, balloon_target_override=None)
        else:
            icon_info = None
        if gsi_handlers.balloon_handlers.archiver.enabled:
            gsi_handlers.balloon_handlers.archive_balloon_data(sim, None, balloon_icon, icon_info, gsi_entries)
        if balloon_icon is not None and (icon_info[0] is not None or icon_info[1] is not None):
            (balloon_type, priority) = BALLOON_TYPE_LOOKUP[balloon_icon.balloon_type]
            balloon_overlay = balloon_icon.overlay
            request = BalloonRequest(sim, icon_info[0], icon_info[1], balloon_overlay, balloon_type, priority, TunableBalloon.BALLOON_DURATION, balloon_data.balloon_delay, balloon_data.balloon_delay_random_offset)
            return request

    @staticmethod
    def request_passive_balloon(sim, time_now):
        if time_now - sim.next_passive_balloon_unlock_time > create_time_span(minutes=PassiveBalloons.BALLOON_LONG_LOCKOUT):
            lockout_time = random.randint(0, PassiveBalloons.BALLOON_RANDOM)
            sim.next_passive_balloon_unlock_time = services.time_service().sim_now + create_time_span(minutes=lockout_time)
            return
        balloon_requests = []
        if len(PassiveBalloons.ROUTING_BALLOONS) > PassiveBalloons.MAX_NUM_BALLOONS:
            sampled_balloon_tuning = random.sample(PassiveBalloons.ROUTING_BALLOONS, PassiveBalloons.MAX_NUM_BALLOONS)
        else:
            sampled_balloon_tuning = PassiveBalloons.ROUTING_BALLOONS
        for balloon_weight_pair in sampled_balloon_tuning:
            balloon_request = PassiveBalloons.create_passive_ballon_request(sim, balloon_weight_pair.balloon)
            while balloon_request is not None:
                balloon_requests.append((balloon_weight_pair.weight, balloon_request))
        if len(balloon_requests) > 0:
            choosen_balloon = sims4.random.weighted_random_item(balloon_requests)
            if choosen_balloon is not None:
                choosen_balloon.distribute()
        lockout_time = PassiveBalloons.BALLOON_LOCKOUT + random.randint(0, PassiveBalloons.BALLOON_RANDOM)
        sim.next_passive_balloon_unlock_time = time_now + create_time_span(minutes=lockout_time)

