
class IBouncerClient:
    __qualname__ = 'IBouncerClient'

    def on_sim_assigned_to_request(self, sim, request):
        raise NotImplementedError

    def on_sim_unassigned_from_request(self, sim, request):
        raise NotImplementedError

    def on_sim_replaced_in_request(self, old_sim, new_sim, request):
        raise NotImplementedError

    def on_failed_to_spawn_sim_for_request(self, request):
        raise NotImplementedError

    def on_tardy_request(self, request):
        raise NotImplementedError

    def on_first_assignment_pass_completed(self):
        raise NotImplementedError

