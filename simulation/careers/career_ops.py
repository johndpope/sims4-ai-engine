from interactions import ParticipantType
from interactions.utils import LootType
from interactions.utils.loot_basic_op import BaseLootOperation
from protocolbuffers import Consts_pb2
from sims4.tuning.tunable import TunableReference, TunableEnumEntry, TunableEnumFlags, TunableVariant, TunableTuple, TunableList, Tunable
import enum
import services
import sims4.log
from objects import ALL_HIDDEN_REASONS
logger = sims4.log.Logger('Career')

class CareerOps(enum.Int):
    __qualname__ = 'CareerOps'
    JOIN_CAREER = 0
    QUIT_CAREER = 1
    CALLED_IN_SICK = 2

class CareerLevelOps(enum.Int):
    __qualname__ = 'CareerLevelOps'
    PROMOTE = 0
    DEMOTE = 1

class CareerLevelOp(BaseLootOperation):
    __qualname__ = 'CareerLevelOp'
    FACTORY_TUNABLES = {'career': TunableReference(description="\n            The career upon which we'll be promoting/demoting the Sim.\n            If the Sim doesn't have this career or there's a reason the career\n            can't be promoted/demoted, nothing will happen.\n            ", manager=services.get_instance_manager(sims4.resources.Types.CAREER)), 'operation': TunableEnumEntry(description='\n            The operation to perform on the career.\n            ', tunable_type=CareerLevelOps, default=CareerLevelOps.PROMOTE)}

    def __init__(self, career, operation, **kwargs):
        super().__init__(**kwargs)
        self._career = career
        self._operation = operation

    def _apply_to_subject_and_target(self, subject, target, resolver):
        career = subject.career_tracker.careers.get(self._career.guid64)
        demote = self._operation == CareerLevelOps.DEMOTE
        if career is None or not career.can_change_level(demote=demote):
            return
        if demote:
            career.demote()
        else:
            career.promote()

class CareerLootOp(BaseLootOperation):
    __qualname__ = 'CareerLootOp'
    REFERENCE = 0
    PARTICIPANT = 1
    OP_PERFORMANCE = 0
    OP_MONEY = 1
    OP_RETIRE = 2
    FACTORY_TUNABLES = {'career': TunableVariant(description='\n            The career to apply loot to.\n            ', career_reference=TunableTuple(description='\n                Reference to the career.\n                ', reference=TunableReference(manager=services.get_instance_manager(sims4.resources.Types.CAREER)), locked_args={'id_type': REFERENCE}), participant_type=TunableTuple(description='\n                The id of the career upon which the op will be applied to. Sim\n                Participant must have the career. Typically should be PickedItemId\n                if this loot is being applied by the continuation of a\n                CareerPickerSuperInteraction.\n                ', participant=TunableEnumFlags(enum_type=ParticipantType, default=ParticipantType.PickedItemId), locked_args={'id_type': PARTICIPANT}), default='career_reference'), 'operations': TunableList(description='\n            A list of career loot ops.\n            ', tunable=TunableVariant(description='\n                What the Sim will get with this op.\n                ', performance=TunableTuple(description="\n                    The tuned amount will be applied to the relevant career's\n                    performance statistic.\n                    ", amount=Tunable(description="\n                        The amount to apply to the career's performance statistic.\n                        Can be negative.\n                        ", tunable_type=float, default=0), locked_args={'operation_type': OP_PERFORMANCE}), money=TunableTuple(description="\n                    A tuned amount of money, as a multiple of the current\n                    career's simoleons per hour, for the Sim to get.\n                    ", hour_multiplier=Tunable(description="\n                        The multiplier on the career's simoleons per hour.\n                        ", tunable_type=float, default=0), locked_args={'operation_type': OP_MONEY}), retire=TunableTuple(description='\n                    Retire the Sim from the career. The career will provide a\n                    daily pension until death. All other careers will be quit.\n                    ', locked_args={'operation_type': OP_RETIRE}), default='performance'))}

    def __init__(self, career, operations, **kwargs):
        super().__init__(**kwargs)
        self.career = career
        self.operations = operations

    def _apply_to_subject_and_target(self, subject, target, resolver):
        if subject is None:
            return
        career = self._get_career(subject, resolver)
        if career is None:
            return
        self._apply_to_career(subject, career, resolver)

    def _apply_to_career(self, sim_info, career, resolver):
        for op in self.operations:
            if op.operation_type == CareerLootOp.OP_PERFORMANCE:
                stat = career.work_performance_stat
                stat.add_value(op.amount, interaction=resolver.interaction)
                career.resend_career_data()
            elif op.operation_type == CareerLootOp.OP_MONEY:
                money = op.hour_multiplier*career.get_hourly_pay()
                sim = sim_info.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)
                sim_info.household.funds.add(money, Consts_pb2.TELEMETRY_MONEY_CAREER, sim)
            else:
                while op.operation_type == CareerLootOp.OP_RETIRE:
                    sim_info.career_tracker.retire_career(career.guid64)

    def _get_career_id(self, interaction):
        if self.career.id_type == CareerLootOp.REFERENCE:
            return self.career.reference.guid64
        if self.career.id_type == CareerLootOp.PARTICIPANT:
            for career_id in interaction.get_participants(self.career.participant):
                pass
        logger.warn('CareerLootOp: No career found {}', self.career, owner='tingyul')
        return 0

    def _get_career(self, sim_info, interaction):
        career_id = self._get_career_id(interaction)
        if career_id:
            career = sim_info.career_tracker.careers.get(career_id)
            return career
        logger.warn('CareerLootOp: Sim {} does not have career {}'.format(sim_info, career_id), owner='tingyul')

