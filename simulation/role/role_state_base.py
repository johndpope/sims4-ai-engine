from objects.components.welcome_component import FrontDoorTuning
from sims4.utils import classproperty
import services
import sims4.log
logger = sims4.log.Logger('Roles')

class RoleStateBase:
    __qualname__ = 'RoleStateBase'

    @classproperty
    def role_priority(cls):
        raise NotImplementedError

    @classproperty
    def buffs(cls):
        raise NotImplementedError

    @classproperty
    def off_lot_autonomy_buff(cls):
        raise NotImplementedError

    @classproperty
    def role_specific_affordances(cls):
        raise NotImplementedError

    @classproperty
    def on_activate(cls):
        raise NotImplementedError

    @classproperty
    def portal_disallowance_tags(self):
        return set()

    @classproperty
    def allow_npc_routing_on_active_lot(cls):
        raise NotImplementedError

    @classproperty
    def only_allow_sub_action_autonomy(cls):
        raise NotImplementedError

    def __init__(self, sim):
        self._sim_ref = sim.ref()
        self._buff_handles = []
        self._off_lot_autonomy_buff_handle = None

    @property
    def sim(self):
        if self._sim_ref is not None:
            return self._sim_ref()

    def can_run_super_affordance(self, super_affordance):
        if self.super_affordance_compatibility is None:
            return True
        if self.super_affordance_compatibility(super_affordance):
            return True
        return False

    def on_role_removed_from_sim(self):
        self.on_role_deactivated()

    def _add_disallowed_portal(self, portal):
        if portal.portal_disallowance_tags & self.portal_disallowance_tags:
            portal.add_disallowed_sim(self.sim, self)

    def _remove_disallowed_portal(self, portal):
        if portal.portal_disallowance_tags & self.portal_disallowance_tags:
            portal.remove_disallowed_sim(self.sim, self)

    def _on_front_door_candidates_changed(self):
        object_manager = services.object_manager()
        for portal in object_manager.portal_cache_gen():
            if not portal.state_component:
                pass
            if portal.get_state(FrontDoorTuning.FRONT_DOOR_ENABLED_STATE.state) == FrontDoorTuning.FRONT_DOOR_ENABLED_STATE:
                self._add_disallowed_portal(portal)
            else:
                self._remove_disallowed_portal(portal)

    def on_role_activate(self, role_affordance_target=None):
        if self.portal_disallowance_tags:
            object_manager = services.object_manager()
            for portal in object_manager.portal_cache_gen():
                while portal.state_component and portal.get_state(FrontDoorTuning.FRONT_DOOR_ENABLED_STATE.state) == FrontDoorTuning.FRONT_DOOR_ENABLED_STATE:
                    self._add_disallowed_portal(portal)
            object_manager.register_portal_added_callback(self._add_disallowed_portal)
            object_manager.register_front_door_candidates_changed_callback(self._on_front_door_candidates_changed)
        for buff_ref in self.buffs:
            if buff_ref is None:
                logger.warn('{} has empty buff in buff list. Please fix tuning.', self)
            if buff_ref.buff_type is None:
                logger.warn('{} has an buff type not set. Please fix tuning.', self)
            self._buff_handles.append(self.sim.add_buff(buff_ref.buff_type, buff_reason=buff_ref.buff_reason))
        if self.off_lot_autonomy_buff is not None and self.off_lot_autonomy_buff.buff_type is not None:
            self._off_lot_autonomy_buff_handle = self.sim.add_buff(self.off_lot_autonomy_buff.buff_type, buff_reason=self.off_lot_autonomy_buff.buff_reason)
        flags = set()
        for affordance in self.role_specific_affordances:
            flags |= affordance.commodity_flags
        if flags:
            self.sim.add_dynamic_commodity_flags(self, flags)
        if self.on_activate is not None:
            self.on_activate(self, role_affordance_target)
        if not self.allow_npc_routing_on_active_lot:
            self.sim.inc_lot_routing_restriction_ref_count()

    def _get_target_for_push_affordance(self, target_type):
        raise NotImplementedError

    def on_role_deactivated(self):
        sim = self.sim
        if sim is None:
            return
        if self.portal_disallowance_tags:
            object_manager = services.object_manager()
            object_manager.unregister_portal_added_callback(self._add_disallowed_portal)
            object_manager.unregister_front_door_candidates_changed_callback(self._on_front_door_candidates_changed)
            for portal in object_manager.portal_cache_gen():
                self._remove_disallowed_portal(portal)
        for buff_handle in self._buff_handles:
            sim.remove_buff(buff_handle)
        self._buff_handles = []
        if self._off_lot_autonomy_buff_handle is not None:
            sim.remove_buff(self._off_lot_autonomy_buff_handle)
            self._off_lot_autonomy_buff_handle = None
        if self.role_specific_affordances:
            self.sim.remove_dynamic_commodity_flags(self)
        if not self.allow_npc_routing_on_active_lot:
            self.sim.dec_lot_routing_restriction_ref_count()

