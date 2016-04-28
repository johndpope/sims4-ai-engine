import time
from interactions import ParticipantType
from performance.test_profiling import TestProfileRecord, ProfileMetrics
from singletons import DEFAULT
import event_testing.test_events
import services
import sims4.log
import sims4.reload
logger = sims4.log.Logger('Resolver')
with sims4.reload.protected(globals()):
    RESOLVER_PARTICIPANT = 'resolver'
    test_profile = None

class Resolver:
    __qualname__ = 'Resolver'

    def __init__(self, skip_safe_tests=False, search_for_tooltip=False):
        self._skip_safe_tests = skip_safe_tests
        self._search_for_tooltip = search_for_tooltip

    @property
    def skip_safe_tests(self):
        return self._skip_safe_tests

    @property
    def search_for_tooltip(self):
        return self._search_for_tooltip

    @property
    def interaction(self):
        pass

    def get_resolved_args(self, expected):
        if expected is None:
            raise ValueError('Expected arguments from test instance get_expected_args are undefined: {}'.format(expected))
        single_types = {ParticipantType.Affordance, ParticipantType.InteractionContext, event_testing.test_events.FROM_DATA_OBJECT, event_testing.test_events.OBJECTIVE_GUID64, event_testing.test_events.FROM_EVENT_DATA}
        ret = {}
        for (event_key, participant_type) in expected.items():
            if participant_type in single_types:
                value = self.get_participant(participant_type, event_key=event_key)
            else:
                value = self.get_participants(participant_type, event_key=event_key)
            ret[event_key] = value
        return ret

    @property
    def profile_metric_key(self):
        pass

    def __call__(self, test):
        if test_profile is not None:
            start_time = time.time()
        expected_args = test.get_expected_args()
        resolved_args = self.get_resolved_args(expected_args)
        result = test(**resolved_args)
        if test_profile is not None:
            self._record_test_profile_metrics(test, start_time)
        return result

    def _record_test_profile_metrics(self, test, start_time):
        global test_profile
        try:
            delta = time.time() - start_time
            test_name = test.__class__.__name__
            record = test_profile.get(test_name)
            if record is None:
                record = TestProfileRecord()
                test_profile[test_name] = record
            record.metrics.update(delta)
            resolver_name = type(self).__name__
            resolver_dict = record.resolvers.get(resolver_name)
            if resolver_dict is None:
                resolver_dict = dict()
                record.resolvers[resolver_name] = resolver_dict
            key_name = self.profile_metric_key
            if key_name is None:
                key_name = 'Key'
            metrics = resolver_dict.get(key_name)
            if metrics is None:
                metrics = ProfileMetrics()
                resolver_dict[key_name] = metrics
            metrics.update(delta)
        except Exception as e:
            logger.exception('Resetting test_profile due to an exception {}.', e, owner='manus')
            test_profile = None

    def can_make_pass(self, test):
        expected_args = test.get_expected_args()
        resolved_args = self.get_resolved_args(expected_args)
        return test.can_make_pass(**resolved_args)

    def make_pass(self, test):
        expected_args = test.get_expected_args()
        resolved_args = self.get_resolved_args(expected_args)
        return test.make_pass(**resolved_args)

    def get_participant(self, participant_type, **kwargs):
        participants = self.get_participants(participant_type, **kwargs)
        if not participants:
            return
        if len(participants) > 1:
            raise ValueError('Too many participants returned for {}!'.format(participant_type))
        return next(iter(participants))

    def get_participants(self, participant_type, **kwargs):
        raise NotImplementedError('Attempting to use the Resolver base class, use sub-classes instead.')

    def _get_participants_base(self, participant_type, **kwargs):
        if participant_type == RESOLVER_PARTICIPANT:
            return self
        result = Resolver.get_particpants_shared(participant_type)
        if result:
            return result
        return ()

    def get_target_id(self, test, id_type=None):
        expected_args = test.get_expected_args()
        resolved_args = self.get_resolved_args(expected_args)
        resolved_args['id_type'] = id_type
        return test.get_target_id(**resolved_args)

    def get_posture_id(self, test):
        expected_args = test.get_expected_args()
        resolved_args = self.get_resolved_args(expected_args)
        return test.get_posture_id(**resolved_args)

    def get_tags(self, test):
        expected_args = test.get_expected_args()
        resolved_args = self.get_resolved_args(expected_args)
        return test.get_tags(**resolved_args)

    def get_localization_tokens(self, *args, **kwargs):
        return ()

    @staticmethod
    def get_particpants_shared(participant_type):
        if participant_type == ParticipantType.Lot:
            return (services.active_lot(),)
        if participant_type == ParticipantType.LotOwners:
            owning_household = services.owning_household_of_active_lot()
            if owning_household is not None:
                return tuple(sim_info for sim_info in owning_household.sim_info_gen())
        return ()

class InteractionResolver(Resolver):
    __qualname__ = 'InteractionResolver'
    VALID_INTERACTION_PARTICIPANTS = ParticipantType.All | ParticipantType.AllSims | ParticipantType.Actor | ParticipantType.Object | ParticipantType.CarriedObject | ParticipantType.TargetSim | ParticipantType.JoinTarget | ParticipantType.Listeners | ParticipantType.CraftingProcess | ParticipantType.ActorSurface | ParticipantType.StoredSim | ParticipantType.Lot | ParticipantType.SocialGroup | ParticipantType.OtherSimsInteractingWithTarget | ParticipantType.CraftingObject | ParticipantType.ObjectParent | ParticipantType.PickedObject | ParticipantType.OwnerSim | ParticipantType.PickedSim | ParticipantType.SignificantOtherActor | ParticipantType.SignificantOtherTargetSim | ParticipantType.StoredSimOnActor | ParticipantType.ObjectChildren | ParticipantType.PickedZoneId | ParticipantType.CreatedObject | ParticipantType.PickedItemId | ParticipantType.Unlockable | ParticipantType.LotOwners | ParticipantType.PregnancyPartnerActor | ParticipantType.PregnancyPartnerTargetSim

    def __init__(self, affordance, interaction, target=DEFAULT, context=DEFAULT, custom_sim=None, super_interaction=None, skip_safe_tests=False, search_for_tooltip=False, **interaction_parameters):
        super().__init__(skip_safe_tests, search_for_tooltip)
        self.affordance = affordance
        self._interaction = interaction
        self.target = interaction.target if target is DEFAULT else target
        self.context = interaction.context if context is DEFAULT else context
        self.custom_sim = custom_sim
        self.super_interaction = super_interaction
        self.interaction_parameters = interaction_parameters

    def __repr__(self):
        return 'InteractionResolver: affordance: {}, interaction:{}, target: {}, context: {}, si: {}'.format(self.affordance, self.interaction, self.target, self.context, self.super_interaction)

    @property
    def interaction(self):
        return self._interaction

    @property
    def profile_metric_key(self):
        if self.affordance is None:
            return 'NoAffordance'
        return self.affordance.__name__

    def get_participants(self, participant_type, **kwargs):
        if participant_type == event_testing.test_events.SIM_INSTANCE:
            participant_type = ParticipantType.Actor
        if participant_type == ParticipantType.Actor:
            sim = self.context.sim
            if sim is not None:
                result = _to_sim_info(sim)
                if result is not None:
                    return (result,)
                return ()
        else:
            if participant_type == ParticipantType.Object:
                if self.target is not None:
                    result = _to_sim_info(self.target)
                    if result is not None:
                        return (result,)
                return ()
            if participant_type == ParticipantType.TargetSim:
                if self.target is not None and self.target.is_sim:
                    result = _to_sim_info(self.target)
                    if result is not None:
                        return (result,)
                return ()
        if participant_type == 0:
            logger.error('Calling get_participants with no flags on {}.', self)
            return ()
        result = self._get_participants_base(participant_type, **kwargs)
        if result:
            return result
        if participant_type == event_testing.test_events.FROM_DATA_OBJECT:
            return ()
        if participant_type == event_testing.test_events.OBJECTIVE_GUID64:
            return ()
        if participant_type == event_testing.test_events.FROM_EVENT_DATA:
            return ()
        if participant_type == ParticipantType.Affordance:
            return (self.affordance,)
        if participant_type == ParticipantType.InteractionContext:
            return (self.context,)
        if participant_type == ParticipantType.CustomSim:
            if self.custom_sim is not None:
                return (self.custom_sim.sim_info,)
            ValueError('Trying to use CustomSim without passing a custom_sim in InteractionResolver.')
        else:
            if participant_type == ParticipantType.AllRelationships:
                return (ParticipantType.AllRelationships,)
            if participant_type & InteractionResolver.VALID_INTERACTION_PARTICIPANTS:
                if self.interaction is not None:
                    participants = self.interaction.get_participants(participant_type=participant_type, sim=self.context.sim, target=self.target, listener_filtering_enabled=False, **self.interaction_parameters)
                elif self.super_interaction is not None:
                    participants = self.super_interaction.get_participants(participant_type=participant_type, sim=self.context.sim, target=self.target, listener_filtering_enabled=False, target_type=self.affordance.target_type, **self.interaction_parameters)
                else:
                    participants = self.affordance.get_participants(participant_type=participant_type, sim=self.context.sim, target=self.target, carry_target=self.context.carry_target, listener_filtering_enabled=False, target_type=self.affordance.target_type, **self.interaction_parameters)
                resolved_participants = set()
                for participant in participants:
                    resolved_participants.add(_to_sim_info(participant))
                return tuple(resolved_participants)
        raise ValueError('Trying to use InteractionResolver without a valid type: {}'.format(participant_type))

    def get_localization_tokens(self, *args, **kwargs):
        return self.interaction.get_localization_tokens(*args, **kwargs)

def _to_sim_info(participant):
    sim_info = getattr(participant, 'sim_info', None)
    if sim_info is None or sim_info.is_baby:
        return participant
    return sim_info

class AwayActionResolver(Resolver):
    __qualname__ = 'AwayActionResolver'
    VALID_AWAY_ACTION_PARTICIPANTS = ParticipantType.Actor | ParticipantType.TargetSim | ParticipantType.Lot

    def __init__(self, away_action, skip_safe_tests=False, search_for_tooltip=False, **away_action_parameters):
        super().__init__(skip_safe_tests, search_for_tooltip)
        self.away_action = away_action
        self.away_action_parameters = away_action_parameters

    def __repr__(self):
        return 'AwayActionResolver: away_action: {}'.format(self.away_action)

    @property
    def sim(self):
        return self.get_participant(ParticipantType.Actor)

    def get_participants(self, participant_type, **kwargs):
        if participant_type == 0:
            logger.error('Calling get_participants with no flags on {}.', self)
            return ()
        if participant_type == event_testing.test_events.FROM_DATA_OBJECT:
            return ()
        if participant_type == event_testing.test_events.OBJECTIVE_GUID64:
            return ()
        if participant_type == event_testing.test_events.FROM_EVENT_DATA:
            return ()
        if participant_type & AwayActionResolver.VALID_AWAY_ACTION_PARTICIPANTS:
            return self.away_action.get_participants(participant_type=participant_type, **self.away_action_parameters)
        raise ValueError('Trying to use AwayActionResolver without a valid type: {}'.format(participant_type))

    def get_localization_tokens(self, *args, **kwargs):
        return self.interaction.get_localization_tokens(*args, **kwargs)

class SingleSimResolver(Resolver):
    __qualname__ = 'SingleSimResolver'

    def __init__(self, sim_info_to_test):
        super().__init__()
        self.sim_info_to_test = sim_info_to_test

    def __repr__(self):
        return 'SingleSimResolver: sim_to_test: {}'.format(self.sim_info_to_test)

    def _get_participants_base(self, participant_type, **kwargs):
        result = super()._get_participants_base(participant_type, **kwargs)
        if result:
            return result
        if participant_type == ParticipantType.Actor or participant_type == ParticipantType.CustomSim or participant_type == event_testing.test_events.SIM_INSTANCE:
            return (self.sim_info_to_test,)
        if participant_type == ParticipantType.SignificantOtherActor:
            return (self.sim_info_to_test.get_spouse_sim_info(),)
        if participant_type == ParticipantType.PregnancyPartnerActor:
            return (self.sim_info.pregnancy_tracker.get_partner(),)
        if participant_type == ParticipantType.AllRelationships:
            return ParticipantType.AllRelationships
        return ()

    def get_participants(self, participant_type, **kwargs):
        result = self._get_participants_base(participant_type, **kwargs)
        if result:
            return result
        if participant_type == event_testing.test_events.FROM_EVENT_DATA:
            return ()
        raise ValueError('Trying to use SingleSimResolver with something that is not an Actor: {}'.format(participant_type))

    def get_localization_tokens(self, *args, **kwargs):
        return (self.sim_info_to_test,)

class DoubleSimResolver(SingleSimResolver):
    __qualname__ = 'DoubleSimResolver'

    def __init__(self, sim_info, target_sim_info):
        super().__init__(sim_info)
        self.target_sim_info = target_sim_info

    def __repr__(self):
        return 'DoubleSimResolver: sim: {} target_sim: {}'.format(self.sim_info_to_test, self.target_sim_info)

    def get_participants(self, participant_type, **kwargs):
        result = super()._get_participants_base(participant_type, **kwargs)
        if result:
            return result
        if participant_type == ParticipantType.TargetSim:
            return (self.target_sim_info,)
        if participant_type == ParticipantType.SignificantOtherTargetSim:
            return (self.target_sim_info.get_significant_other_sim_info(),)
        if participant_type == event_testing.test_events.FROM_EVENT_DATA:
            return ()
        raise ValueError('Trying to use DoubleSimResolver with something that is not an Actor or target_sim: {}'.format(participant_type))

    def get_localization_tokens(self, *args, **kwargs):
        return (self.sim_info_to_test, self.target_sim_info)

class DataResolver(Resolver):
    __qualname__ = 'DataResolver'

    def __init__(self, sim_info, event_kwargs=None):
        super().__init__()
        self.sim_info = sim_info
        if event_kwargs is not None:
            self._interaction = event_kwargs.get('interaction', None)
            self.on_zone_load = event_kwargs.get('init', False)
        else:
            self._interaction = None
            self.on_zone_load = False
        self.event_kwargs = event_kwargs
        self.data_object = None
        self.objective_guid64 = None

    def __repr__(self):
        return 'DataResolver: participant: {}'.format(self.sim_info)

    def __call__(self, test, data_object=None, objective_guid64=None):
        if data_object is not None:
            self.data_object = data_object
            self.objective_guid64 = objective_guid64
        return super().__call__(test)

    @property
    def interaction(self):
        return self._interaction

    @property
    def profile_metric_key(self):
        interaction_name = None
        if self._interaction is not None:
            interaction_name = self._interaction.aop.affordance.__name__
        objective_name = 'Invalid'
        if self.objective_guid64 is not None:
            objective_manager = services.objective_manager()
            objective = objective_manager.get(self.objective_guid64)
            objective_name = objective.__name__
        return 'objective:{} (interaction:{})'.format(objective_name, interaction_name)

    def get_resolved_arg(self, key):
        return self.event_kwargs.get(key, None)

    def get_participants(self, participant_type, event_key=None):
        result = self._get_participants_base(participant_type, event_key=event_key)
        if result:
            return result
        if participant_type == event_testing.test_events.SIM_INSTANCE:
            return (self.sim_info,)
        if participant_type == event_testing.test_events.FROM_DATA_OBJECT:
            return (self.data_object,)
        if participant_type == event_testing.test_events.OBJECTIVE_GUID64:
            return (self.objective_guid64,)
        if participant_type == event_testing.test_events.FROM_EVENT_DATA:
            if not self.event_kwargs:
                return ()
            return (self.event_kwargs.get(event_key),)
        if self._interaction is not None:
            return tuple(getattr(participant, 'sim_info', participant) for participant in self._interaction.get_participants(participant_type))
        if participant_type == ParticipantType.Actor:
            return (self.sim_info,)
        if participant_type == ParticipantType.AllRelationships:
            sim_mgr = services.sim_info_manager()
            relations = set(sim_mgr.get(relations.relationship_id) for relations in self.sim_info.relationship_tracker)
            return tuple(relations)
        if participant_type == ParticipantType.TargetSim:
            if not self.event_kwargs:
                return ()
            target_sim_id = self.event_kwargs.get(event_testing.test_events.TARGET_SIM_ID)
            if target_sim_id is None:
                return ()
            return (services.sim_info_manager().get(target_sim_id),)
        if self.on_zone_load:
            return ()
        raise ValueError('Trying to use DataResolver with type that is not supported by DataResolver: {}'.format(participant_type))

class SingleObjectResolver(Resolver):
    __qualname__ = 'SingleObjectResolver'

    def __init__(self, obj):
        super().__init__()
        self._obj = obj

    def __repr__(self):
        return 'SingleObjectResolver: object: {}'.format(self._obj)

    def get_participants(self, participant_type, **kwargs):
        result = self._get_participants_base(participant_type, **kwargs)
        if result:
            return result
        if participant_type == ParticipantType.Object:
            return (self._obj,)
        if participant_type == ParticipantType.StoredSim:
            stored_sim_info = self._obj.get_stored_sim_info()
            return (stored_sim_info,)
        if participant_type == ParticipantType.OwnerSim:
            owner_sim_info_id = self._obj.get_sim_owner_id()
            owner_sim_info = services.sim_info_manager().get(owner_sim_info_id)
            return (owner_sim_info,)
        raise ValueError('Trying to use SingleObjectResolver with something that is not an Object: {}'.format(participant_type))

    def get_localization_tokens(self, *args, **kwargs):
        return (self._obj,)

class DoubleObjectResolver(Resolver):
    __qualname__ = 'DoubleObjectResolver'

    def __init__(self, source_obj, target_obj):
        super().__init__()
        self._source_obj = source_obj
        self._target_obj = target_obj

    def __repr__(self):
        return 'DoubleObjectResolver: actor_object: {}, target_object:{}'.format(self._source_obj, self._target_obj)

    def get_participants(self, participant_type, **kwargs):
        result = self._get_participants_base(participant_type, **kwargs)
        if result:
            return result
        if participant_type == ParticipantType.Actor or (participant_type == ParticipantType.PickedObject or participant_type == ParticipantType.CarriedObject) or participant_type == ParticipantType.LiveDragActor:
            if self._source_obj.is_sim:
                return (self._source_obj.sim_info,)
            return (self._source_obj,)
        if participant_type == ParticipantType.Listeners or (participant_type == ParticipantType.Object or participant_type == ParticipantType.TargetSim) or participant_type == ParticipantType.LiveDragTarget:
            if self._target_obj.is_sim:
                return (self._target_obj.sim_info,)
            return (self._target_obj,)
        if participant_type == event_testing.test_events.FROM_EVENT_DATA:
            return ()
        raise ValueError('Trying to use DoubleObjectResolver with something that is not supported: {}'.format(participant_type))

        def get_localization_tokens(self, *args, **kwargs):
            return (self._source_obj, self._target_obj)

class SingleActorAndObjectResolver(Resolver):
    __qualname__ = 'SingleActorAndObjectResolver'

    def __init__(self, actor_sim_info, obj):
        super().__init__()
        self._sim_info = actor_sim_info
        self._obj = obj

    def __repr__(self):
        return 'SingleActorAndObjectResolver: sim_info: {}, object: {}'.format(self._sim_info, self._obj)

    def get_participants(self, participant_type, **kwargs):
        result = self._get_participants_base(participant_type, **kwargs)
        if result:
            return result
        if participant_type == ParticipantType.Actor or participant_type == ParticipantType.CustomSim or participant_type == event_testing.test_events.SIM_INSTANCE:
            return (self._sim_info,)
        if participant_type == ParticipantType.Object:
            return (self._obj,)
        if participant_type == ParticipantType.ObjectParent:
            if self._obj is None or self._obj.parent is None:
                return ()
            return (self._obj.parent,)
        if participant_type == ParticipantType.StoredSim:
            stored_sim_info = self._obj.get_stored_sim_info()
            return (stored_sim_info,)
        if participant_type == ParticipantType.OwnerSim:
            owner_sim_info_id = self._obj.get_sim_owner_id()
            owner_sim_info = services.sim_info_manager().get(owner_sim_info_id)
            return (owner_sim_info,)
        if participant_type == event_testing.test_events.FROM_EVENT_DATA:
            return ()
        raise ValueError('Trying to use SingleActorAndObjectResolver with something that is not supported: {}'.format(participant_type))

    def get_localization_tokens(self, *args, **kwargs):
        return (self._sim_info, self._obj)

