from interactions.context import InteractionContext, InteractionSource
from interactions.priority import Priority
from sims4.tuning.instances import HashedTunedInstanceMetaclass
from sims4.tuning.tunable import TunableList, TunableReference, TunableEnumEntry, TunableSet, TunableVariant, AutoFactoryInit, HasTunableSingletonFactory, TunableEnumWithFilter, Tunable, HasDependentTunableReference
from sims4.tuning.tunable_base import FilterTag
from sims4.utils import classproperty
from tag import Tag
import buffs.tunable
import enum
import role.role_state_base
import services
import sims4.log
import sims4.resources
import tag
logger = sims4.log.Logger('Roles')

class RolePriority(enum.Int):
    __qualname__ = 'RolePriority'
    NORMAL = 0
    HIGH = 1

class SituationAffordanceTarget(enum.Int):
    __qualname__ = 'SituationAffordanceTarget'
    NO_TARGET = 0
    CRAFTED_OBJECT = 1

class PushAffordanceFromRole(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'PushAffordanceFromRole'
    FACTORY_TUNABLES = {'description': '\n                        Push the specific affordance onto the sim.\n                        ', 'affordance': TunableReference(services.affordance_manager()), 'source': TunableEnumEntry(tunable_type=InteractionSource, default=InteractionSource.SCRIPT), 'priority': TunableEnumEntry(tunable_type=Priority, default=Priority.High, description='Priority to push the interaction'), 'run_priority': TunableEnumEntry(tunable_type=Priority, default=None, description='Priority to run the interaction. None means use the (push) priority'), 'target': TunableEnumEntry(description='\n                            The target of the affordance. We will try to get\n                            the target from the situation the role sim is\n                            running.\n                            ', tunable_type=SituationAffordanceTarget, default=SituationAffordanceTarget.NO_TARGET)}

    def __call__(self, role_state, role_affordance_target):
        sim = role_state.sim
        affordance = self.affordance
        source = self.source
        priority = self.priority
        run_priority = self.run_priority
        if run_priority is None:
            run_priority = priority
        interaction_context = InteractionContext(sim, source, priority, run_priority=run_priority)
        target = role_state._get_target_for_push_affordance(self.target, role_affordance_target=role_affordance_target)
        sim.push_super_affordance(affordance, target, interaction_context)

class DoAutonomyPingFromRole(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'DoAutonomyPingFromRole'

    def __call__(self, role_state, role_affordance_target):
        role_state.sim.run_full_autonomy_next_ping()

class RoleState(HasDependentTunableReference, role.role_state_base.RoleStateBase, metaclass=HashedTunedInstanceMetaclass, manager=services.get_instance_manager(sims4.resources.Types.ROLE_STATE)):
    __qualname__ = 'RoleState'
    INSTANCE_TUNABLES = {'_role_priority': TunableEnumEntry(RolePriority, RolePriority.NORMAL, description='\n                The priority of this role state.  All the role states with the\n                same priority will all be applied together.  The highest group\n                of priorities is considered the active ones.\n                '), '_buffs': TunableList(buffs.tunable.TunableBuffReference(), description='\n                Buffs that will be added to sim when role is active.\n                '), '_off_lot_autonomy_buff': buffs.tunable.TunableBuffReference(description='\n                A buff that prevents autonomy from considering some objects based\n                on the location of the object (e.g. on lot, off lot, within a\n                radius of the sim). \n                In the buff set: Game Effect Modifiers->Autonomy Modifier->Off Lot Autonomy Rule.\n                '), 'tags': TunableSet(TunableEnumEntry(Tag, Tag.INVALID), description='\n                Tags for the role state for checking role states against a set\n                of tags rather than against a list of role states.\n                '), 'role_affordances': TunableList(TunableReference(services.affordance_manager()), description="\n                A list of affordances that are available on the sim in this\n                role state. EX: when a Maid is in the maid_role_start\n                role_state, she will have the 'dismiss' and 'fire' affordances\n                when you click on her.\n                "), '_on_activate': TunableVariant(description='\n                Select the autonomy behavior when this role state becomes active on the sim.\n                disabled: Take no action.\n                autonomy_ping: We explicitly force an autonomy ping on the sim.\n                push_affordance: Push the specific affordance on the sim.\n                ', locked_args={'disabled': None}, autonomy_ping=DoAutonomyPingFromRole.TunableFactory(), push_affordance=PushAffordanceFromRole.TunableFactory(), default='disabled'), '_portal_disallowance_tags': TunableSet(description='\n                A set of tags that define what the portal disallowance tags of\n                this role state are.  Portals that include any of these\n                disallowance tags are considered locked for sims that have this\n                role state.\n                ', tunable=TunableEnumWithFilter(description='\n                    A single portal disallowance tag.\n                    ', tunable_type=tag.Tag, default=tag.Tag.INVALID, filter_prefixes=tag.PORTAL_DISALLOWANCE_PREFIX)), '_allow_npc_routing_on_active_lot': Tunable(description='\n                If True, then npc in this role will be allowed to route on the\n                active lot.\n                If False, then npc in this role will not be allowed to route on the\n                active lot, unless they are already on the lot when the role\n                state is activated.\n                \n                This flag is ignored for player sims and npcs who live on the\n                active lot.\n                \n                e.g. ambient walkby sims should not be routing on the active lot\n                because that is rude.\n                ', tunable_type=bool, needs_tuning=True, default=True), '_only_allow_sub_action_autonomy': Tunable(description='\n                If True, then the sim in this role will only run sub action\n                autonomy. Full autonomy will not be run.\n                \n                This has very limited uses and can totally hose a sim. Please\n                check with Rez or Sscholl before using it.                \n                ', tunable_type=bool, needs_tuning=False, default=False, tuning_filter=FilterTag.EXPERT_MODE)}

    @classmethod
    def _verify_tuning_callback(cls):
        for buff_ref in cls.buffs:
            if buff_ref is None:
                logger.error('{} has empty buff in buff list. Please fix tuning.', cls)
            while buff_ref.buff_type is None:
                logger.error('{} has a buff type not set. Please fix tuning.', cls)

    @classproperty
    def role_priority(cls):
        return cls._role_priority

    @classproperty
    def buffs(cls):
        return cls._buffs

    @classproperty
    def off_lot_autonomy_buff(cls):
        return cls._off_lot_autonomy_buff

    @classproperty
    def role_specific_affordances(cls):
        return cls.role_affordances

    @classproperty
    def allow_npc_routing_on_active_lot(cls):
        return cls._allow_npc_routing_on_active_lot

    @classproperty
    def only_allow_sub_action_autonomy(cls):
        return cls._only_allow_sub_action_autonomy

    @classproperty
    def on_activate(cls):
        return cls._on_activate

    @classproperty
    def portal_disallowance_tags(cls):
        return cls._portal_disallowance_tags

    @classproperty
    def has_full_permissions(cls):
        current_venue = services.get_current_venue()
        if current_venue and current_venue.allow_rolestate_routing_on_navmesh:
            return True
        return not cls._portal_disallowance_tags and cls._allow_npc_routing_on_active_lot

    def _get_target_for_push_affordance(self, situation_target, role_affordance_target=None):
        if situation_target == SituationAffordanceTarget.NO_TARGET:
            return
        if situation_target == SituationAffordanceTarget.CRAFTED_OBJECT:
            return role_affordance_target
        logger.error('Unable to resolve target when trying to push affordance on role state {} activate. requested target type was {}', self, self._on_activate.target)

