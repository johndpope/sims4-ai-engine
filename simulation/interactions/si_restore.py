from clock import ClockSpeedMode
from objects import ALL_HIDDEN_REASONS
from sims4.tuning.tunable import Tunable
import alarms
import autonomy.settings
import clock
import interactions
import services
import sims4
logger = sims4.log.Logger('SuperInteractionRestore')

class SuperInteractionRestorer:
    __qualname__ = 'SuperInteractionRestorer'
    INTERACTION_SPINUP_TIMETIMEOUT_TIME = Tunable(description="\n        The maximum number of ticks that the server takes trying to restore\n        SI's to restore staged interactions or run preroll autonomy.\n        ", tunable_type=int, default=10)
    INTERACTION_SPINUP_TRANSITIONING_TIME = Tunable(description='\n        The number of ticks that we take waiting for sims to get in\n        transitioning interactions.\n        ', tunable_type=int, default=10)
    RESTORE_STAGED_INTERACTIONS = 0
    RESTORE_TRANSITIONING_INTERACTION = 1
    RESTORE_QUEUED_INTERACTIONS = 2
    NUM_RESTORE_STEPS = 3

    def __init__(self):
        self._sims_to_restore = []
        self._si_state_restore_liabilities = []
        self._current_restore_state = self.RESTORE_STAGED_INTERACTIONS

    def _run_startup_interactions(self):
        try:
            for restore_step in range(self.NUM_RESTORE_STEPS):
                self._current_restore_state = restore_step
                if restore_step == self.RESTORE_STAGED_INTERACTIONS:
                    self._load_staged_interactions()
                elif restore_step == self.RESTORE_TRANSITIONING_INTERACTION:
                    self._load_transitioning_interactions()
                else:
                    while restore_step == self.RESTORE_QUEUED_INTERACTIONS:
                        self._load_queued_interactions()
        except Exception as e:
            logger.exception('Exception raised while trying to startup interactions.', exc=e)

    def restore_sim_si_state(self):
        sim_info_manager = services.sim_info_manager()
        for sim_id in sim_info_manager.startup_sim_set_gen():
            sim_info = sim_info_manager.get(sim_id)
            if sim_info is None:
                pass
            sim = sim_info.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)
            if sim is None:
                pass
            self._sims_to_restore.append(sim.ref())
            sim.set_allow_route_instantly_when_hitting_marks(True)
        if not self._sims_to_restore:
            return
        self._sims_to_restore.sort(key=lambda sim_ref: sim_ref().id)
        autonomy_disabled_sim_infos = set()
        for sim in sim_info_manager.instanced_sims_gen():
            old_setting = sim.autonomy_settings.get_state_setting()
            sim.autonomy_settings.set_state_setting(autonomy.settings.AutonomyState.DISABLED)
            autonomy_disabled_sim_infos.add((sim.sim_info, old_setting))
        self._run_startup_interactions()
        for (sim_info, setting) in autonomy_disabled_sim_infos:
            sim = sim_info.get_sim_instance(allow_hidden_flags=ALL_HIDDEN_REASONS)
            if sim is not None:
                sim.autonomy_settings.set_state_setting(setting)
            else:
                logger.error('{} was uninstantiated during si restore. si_state: {}', sim_info, sim_info.si_state, owner='tingyul')

    def _load_staged_interactions(self):
        for sim_ref in self._sims_to_restore:
            sim = sim_ref()
            while sim is not None:
                sim.load_staged_interactions()

    def _load_transitioning_interactions(self):
        for sim_ref in self._sims_to_restore:
            sim = sim_ref()
            while sim is not None:
                sim.load_transitioning_interaction()

    def _load_queued_interactions(self):
        for sim_ref in self._sims_to_restore:
            sim = sim_ref()
            while sim is not None:
                sim.load_queued_interactions()

