from autonomy.settings import AutonomyRandomization
from event_testing.results import TestResult
from sims4.tuning.tunable import TunableReference, TunableSingletonFactory, TunableSet, TunableEnumEntry, TunableList, AutoFactoryInit
from situations.situation import Situation
from tag import Tag
import autonomy.autonomy_modes
import autonomy.autonomy_request
import event_testing
import interactions.context
import interactions.priority
import objects.components.autonomy
import services
import sims4.log
import situations
logger = sims4.log.Logger('Situations')

class SituationComplex(Situation):
    __qualname__ = 'SituationComplex'

    def test_interaction_complete_by_job_holder(self, sim_info, resolver, job_type, test):
        sim = sim_info.get_sim_instance()
        if sim is None:
            return False
        if not self.sim_has_job(sim, job_type):
            return False
        return resolver(test)

    def _choose_role_interaction(self, sim, push_priority=interactions.priority.Priority.High, run_priority=interactions.priority.Priority.High, allow_failed_path_plans=False):
        context = interactions.context.InteractionContext(sim, interactions.context.InteractionSource.SCRIPT, push_priority, run_priority=run_priority)
        distance_estimation_behavior = autonomy.autonomy_request.AutonomyDistanceEstimationBehavior.FULL
        if allow_failed_path_plans:
            distance_estimation_behavior = autonomy.autonomy_request.AutonomyDistanceEstimationBehavior.ALLOW_UNREACHABLE_LOCATIONS
        autonomy_request = autonomy.autonomy_request.AutonomyRequest(sim, autonomy_mode=autonomy.autonomy_modes.FullAutonomy, skipped_static_commodities=objects.components.autonomy.AutonomyComponent.STANDARD_STATIC_COMMODITY_SKIP_SET, limited_autonomy_allowed=False, context=context, distance_estimation_behavior=distance_estimation_behavior, autonomy_mode_label_override='ChooseRoleInteraction')
        best_interaction = services.autonomy_service().find_best_action(autonomy_request, randomization_override=AutonomyRandomization.DISABLED)
        return best_interaction

class SituationState:
    __qualname__ = 'SituationState'

    def __init__(self):
        self._active = False
        self.owner = None
        self._registered_test_events = set()

    def on_pre_activate(self, reader=None):
        pass

    def on_activate(self, reader=None):
        self._active = True

    def on_deactivate(self):
        self._unregister_for_all_test_events()
        self.owner = None
        self._active = False

    def save_state(self, writer):
        pass

    def _change_state(self, new_state):
        self.owner._change_state(new_state)

    def _test_event_register(self, test_event):
        if test_event in self._registered_test_events:
            return
        self._registered_test_events.add(test_event)
        services.get_event_manager().register_single_event(self, test_event)

    def _test_event_unregister(self, test_event):
        if test_event in self._registered_test_events:
            self._registered_test_events.remove(test_event)
            services.get_event_manager().unregister_single_event(self, test_event)

    def _unregister_for_all_test_events(self):
        services.get_event_manager().unregister(self, self._registered_test_events)
        self._registered_test_events = set()

    def _on_set_sim_role_state(self, sim, job_type, role_state_type, role_affordance_target):
        pass

    def _get_role_state_overrides(self, sim, job_type, role_state_type, role_affordance_target):
        return (role_state_type, role_affordance_target)

class SituationJobAndRoleState:
    __qualname__ = 'SituationJobAndRoleState'
    FACTORY_TUNABLES = {'situation_job': TunableReference(services.situation_job_manager(), description='A reference to a SituationJob that can be performed at this Situation.'), 'role_state': TunableReference(services.get_instance_manager(sims4.resources.Types.ROLE_STATE), description='A role state the sim assigned to the job will perform')}

    def __init__(self, situation_job, role_state):
        self.job = situation_job
        self.role_state = role_state

    def add_to_situation_jobs(self, situation):
        situation._add_job_type(self.job, self.role_state)

TunableSituationJobAndRoleState = TunableSingletonFactory.create_auto_factory(SituationJobAndRoleState)

class InteractionOfInterest(AutoFactoryInit):
    __qualname__ = 'InteractionOfInterest'
    FACTORY_TUNABLES = {'affordances': TunableList(TunableReference(services.affordance_manager()), description="The Sim must have started either any affordance in this list or an interaction matching one of the tags in this tunable's Tags field."), 'tags': TunableSet(TunableEnumEntry(Tag, Tag.INVALID), description='The Sim must have run either an interaction matching one of these Tags or an affordance from the list of Affordances in this tunable.')}

    def get_expected_args(self):
        return {'interaction': event_testing.test_events.FROM_EVENT_DATA}

    def __call__(self, interaction=None):
        if interaction is not None and self.tags & interaction.get_category_tags():
            tag_match = True
        else:
            tag_match = False
        if not tag_match and interaction.affordance not in self.affordances:
            return TestResult(False, 'Failed affordance check: {} not in {}', interaction.affordance, self.affordances)
        return TestResult.TRUE

TunableInteractionOfInterest = TunableSingletonFactory.create_auto_factory(InteractionOfInterest)

class SituationComplexCommon(SituationComplex):
    __qualname__ = 'SituationComplexCommon'
    INSTANCE_SUBCLASSES_ONLY = True
    REMOVE_INSTANCE_TUNABLES = ('_default_job',)
    INVALID_STATE_UID = -1
    STATE_ID_KEY = 'state_id'

    def __init__(self, *arg, **kwargs):
        super().__init__(*arg, **kwargs)
        self._cur_state = None

    def _destroy(self):
        if self._cur_state is not None:
            old_state = self._cur_state
            self._cur_state = None
            old_state.on_deactivate()
        super()._destroy()

    @classmethod
    def _state_type_to_uid(cls, state_type_to_find):
        for (uid, state_type) in cls._states():
            while state_type_to_find is state_type:
                return uid
        return cls.INVALID_STATE_UID

    @classmethod
    def _uid_to_state_type(cls, uid_to_find):
        for (uid, state_type) in cls._states():
            while uid_to_find == uid:
                return state_type

    @staticmethod
    def _states():
        raise NotImplementedError

    @classmethod
    def _tuning_loaded_callback(cls):
        job_and_state = cls._get_tuned_job_and_default_role_state_tuples()
        job_set = set()
        for (job, _) in job_and_state:
            if job in job_set:
                logger.error('Job {} appears more than once in tuning for situation {}', job, cls)
            else:
                job_set.add(job)
        cls._jobs = job_set
        super()._tuning_loaded_callback()

    @classmethod
    def _get_tuned_job_and_default_role_state_tuples(cls):
        raise NotImplementedError

    @classmethod
    def get_tuned_jobs(cls):
        return cls._jobs

    def _initialize_situation_jobs(self):
        super()._initialize_situation_jobs()
        for (job, role_state) in self._get_tuned_job_and_default_role_state_tuples():
            self._add_job_type(job, role_state)

    def _load_situation_states_and_phases(self):
        super()._load_situation_states_and_phases()
        complex_seedling = self._seed.situation_complex_seedling
        if complex_seedling.state_custom_reader is not None:
            self._load_custom_state(complex_seedling.state_custom_reader)

    def _save_custom(self, seed):
        super()._save_custom(seed)
        seedling = seed.setup_for_complex_save()
        self._save_custom_situation(seedling.situation_custom_writer)
        self._save_custom_state(seedling.state_custom_writer)

    def _save_custom_situation(self, writer):
        pass

    def _save_custom_state(self, writer):
        uid = self._state_type_to_uid(type(self._cur_state))
        if uid == SituationComplexCommon.INVALID_STATE_UID:
            raise AssertionError('SituationState: {} in Situation: {} has no unique id'.format(self._cur_state, self))
        writer.write_uint32(SituationComplexCommon.STATE_ID_KEY, uid)
        self._cur_state.save_state(writer)

    def _load_custom_state(self, reader):
        uid = reader.read_uint32(SituationComplexCommon.STATE_ID_KEY, SituationComplexCommon.INVALID_STATE_UID)
        state_type = self._uid_to_state_type(uid)
        if state_type is None:
            raise KeyError
        new_state = state_type()
        self._change_state(new_state, reader)

    @classmethod
    def default_job(cls):
        raise NotImplementedError

    def _change_state(self, new_state, reader=None):
        if __debug__ and self.situation_serialization_option != situations.situation_types.SituationSerializationOption.DONT and self._state_type_to_uid(type(new_state)) == self.INVALID_STATE_UID:
            logger.error('Situation State: {} is not in states() list for Situation: {}. This will prevent it from serializing when in this state.', new_state, self)
        old_state = self._cur_state
        self._cur_state = new_state
        try:
            while self._cur_state is not None:
                self._cur_state.owner = self
                self._cur_state.on_pre_activate(reader)
        finally:
            if old_state is not None:
                old_state.on_deactivate()
        if self._cur_state is not None:
            self._cur_state.on_activate(reader)

    def get_phase_state_name_for_gsi(self):
        if self._cur_state is None:
            return 'None'
        return self._cur_state.__class__.__name__

    def _on_set_sim_role_state(self, sim, job_type, role_state_type, role_affordance_target):
        if self._cur_state is not None:
            self._cur_state._on_set_sim_role_state(sim, job_type, role_state_type, role_affordance_target)

    def _get_role_state_overrides(self, sim, job_type, role_state_type, role_affordance_target):
        if self._cur_state is None:
            return (role_state_type, role_affordance_target)
        return self._cur_state._get_role_state_overrides(sim, job_type, role_state_type, role_affordance_target)

