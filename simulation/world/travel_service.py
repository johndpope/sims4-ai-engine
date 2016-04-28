from interactions.aop import AffordanceObjectPair
from interactions.context import InteractionContext
from interactions.priority import Priority
from sims4.service_manager import Service
from sims4.tuning.tunable import TunableReference
import services
import sims4.log
logger = sims4.log.Logger('Travel')

class TravelService(Service):
    __qualname__ = 'TravelService'
    TRAVEL_AFFORDANCE = TunableReference(manager=services.get_instance_manager(sims4.resources.Types.INTERACTION), description='The affordance used to make a Sim travel.')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pending_travel_request = []

    def add_pending_travel(self, sim):
        self.pending_travel_request.append(sim.account)

    def has_pending_travel(self, account):
        return account in self.pending_travel_request

    def remove_pending_travel(self, sim):
        self.pending_travel_request.remove(sim.account)

def push_travel_interaction(sim, from_zone_id, to_zone_id, callback, context):
    travel_affordance = TravelService.TRAVEL_AFFORDANCE
    travel_aop = AffordanceObjectPair(travel_affordance, None, travel_affordance, None, from_zone_id=from_zone_id, to_zone_id=to_zone_id, on_complete_callback=callback, on_complete_context=context)
    interaction_context = InteractionContext(sim, InteractionContext.SOURCE_PIE_MENU, Priority.High)
    if not travel_aop.test_and_execute(interaction_context):
        logger.error('Critical Failure: Failed to push travel affordance: {0} on sim: {1}', travel_affordance, sim, owner='mduke')
        callback(from_zone_id, sim.sim_info.sim_id, 0, context)
    else:
        services.travel_service().add_pending_travel(sim)

def on_travel_interaction_succeeded(sim_info, from_zone_id, to_zone_id, callback, context):
    callback(from_zone_id, sim_info.sim_id, 1, context)
    services.travel_service().remove_pending_travel(sim_info)
    services.social_service.post_travel_message(sim_info, to_zone_id)

