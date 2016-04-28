import random
from event_testing.tests import TunableTestSet
from interactions.utils.display_name import HasDisplayTextMixin
from objects import ALL_HIDDEN_REASONS
from sims4.tuning.tunable import HasTunableSingletonFactory, TunableEnumEntry, TunablePercent, TunableFactory, OptionalTunable, TunableEnumFlags
import interactions
import interactions.utils
import singletons

class BaseLootOperation(HasTunableSingletonFactory, HasDisplayTextMixin):
    __qualname__ = 'BaseLootOperation'
    FACTORY_TUNABLES = {'tests': TunableTestSet(description='\n            The test to decide whether the loot action can be applied.\n            '), 'chance': TunablePercent(description='\n            Percent chance that buff will be added to Sim.\n            ', default=100)}

    @staticmethod
    def get_participant_tunable(tunable_name, optional=False, use_flags_enum=False, description='', default_participant=interactions.ParticipantType.Actor):
        if use_flags_enum:
            enum_tunable = TunableEnumFlags(description=description, enum_type=interactions.ParticipantType, default=default_participant)
        else:
            enum_tunable = TunableEnumEntry(description=description, tunable_type=interactions.ParticipantType, default=default_participant)
        if optional:
            return {tunable_name: OptionalTunable(description=description, tunable=enum_tunable)}
        return {tunable_name: enum_tunable}

    @TunableFactory.factory_option
    def subject_participant_type_options(description=singletons.DEFAULT, **kwargs):
        if description is singletons.DEFAULT:
            description = 'The sim(s) the operation is applied to.'
        return BaseLootOperation.get_participant_tunable('subject', description=description, **kwargs)

    def __init__(self, *args, subject=interactions.ParticipantType.Actor, target_participant_type=None, advertise=False, tests=None, chance=1, **kwargs):
        super().__init__(*args, **kwargs)
        self._advertise = advertise
        self._subject = subject
        self._target_participant_type = target_participant_type
        self._tests = tests
        self._chance = chance

    def __repr__(self):
        return '<{} {}>'.format(type(self).__name__, self.subject)

    @property
    def advertise(self):
        return self._advertise

    @property
    def stat(self):
        pass

    def get_stat(self, interaction):
        return self.stat

    @property
    def subject(self):
        return self._subject

    @property
    def target_participant_type(self):
        return self._target_participant_type

    @property
    def chance(self):
        return self._chance

    @property
    def loot_type(self):
        return interactions.utils.LootType.GENERIC

    def test_resolver(self, resolver):
        if random.random() > self._chance:
            return False
        if not self._tests:
            return True
        test_result = self._tests.run_tests(resolver)
        return test_result

    def apply_to_resolver(self, resolver, skip_test=False):
        if not skip_test and not self.test_resolver(resolver):
            return (False, None)
        if self.subject is not None:
            for recipient in resolver.get_participants(self.subject):
                if self.target_participant_type is not None:
                    for target_recipient in resolver.get_participants(self.target_participant_type):
                        self._apply_to_subject_and_target(recipient, target_recipient, resolver)
                else:
                    self._apply_to_subject_and_target(recipient, None, resolver)
        elif self.target_participant_type is not None:
            for target_recipient in resolver.get_participants(self.target_participant_type):
                self._apply_to_subject_and_target(None, target_recipient, resolver)
        else:
            self._apply_to_subject_and_target(None, None, resolver)
        return (True, self._on_apply_completed())

    def _apply_to_subject_and_target(self, subject, target, resolver):
        raise NotImplemented

    def _get_object_from_recipient(self, recipient):
        if recipient is None:
            return
        if recipient.is_sim:
            return recipient.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)
        return recipient

    def _on_apply_completed(self):
        pass

    def apply_to_interaction_statistic_change_element(self, resolver):
        self.apply_to_resolver(resolver, skip_test=True)

class BaseTargetedLootOperation(BaseLootOperation):
    __qualname__ = 'BaseTargetedLootOperation'

    @TunableFactory.factory_option
    def target_participant_type_options(description=singletons.DEFAULT, default_participant=interactions.ParticipantType.Invalid, **kwargs):
        if description is singletons.DEFAULT:
            description = 'Participant(s) that subject will apply operations on.'
        return BaseLootOperation.get_participant_tunable('target_participant_type', description=description, default_participant=default_participant, **kwargs)

