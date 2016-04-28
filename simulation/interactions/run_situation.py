from situations.situation_guest_list import SituationGuestList, SituationGuestInfo, SituationInvitationPurpose
import event_testing.results
import interactions.base.super_interaction
import services
import sims4.log
import sims4.resources
import sims4.tuning
logger = sims4.log.Logger('Interactions')

class RunSituationSuperInteraction(interactions.base.super_interaction.SuperInteraction):
    __qualname__ = 'RunSituationSuperInteraction'
    INSTANCE_TUNABLES = {'situation': sims4.tuning.tunable.TunableReference(description='The situation to launch upon execution of this interaction.', manager=services.get_instance_manager(sims4.resources.Types.SITUATION), tuning_group=sims4.tuning.tunable_base.GroupNames.SITUATION), 'job_mapping': sims4.tuning.tunable.TunableMapping(description='\n                                This is a mapping of participant type to situation job.  These must match up with \n                                the jobs in the actual situation.\n                            ', key_type=sims4.tuning.tunable.TunableEnumEntry(interactions.ParticipantType, interactions.ParticipantType.Actor, description='\n                                    The participant type that will be given this job.'), value_type=sims4.tuning.tunable.TunableReference(description='\n                                    The situation job applied to this participant type.  This MUST be a valid \n                                    job for the situation.', manager=services.get_instance_manager(sims4.resources.Types.SITUATION_JOB)), tuning_group=sims4.tuning.tunable_base.GroupNames.SITUATION), 'host_sim': sims4.tuning.tunable.TunableEnumFlags(interactions.ParticipantType, interactions.ParticipantType.Actor, description='\n                            The participant type that will be made the host.')}

    @classmethod
    def _test(cls, target, context, **kwargs):
        return super()._test(target, context, **kwargs)

    def _run_interaction_gen(self, timeline):
        logger.assert_raise(self.situation is not None, 'No situation tuned on RunSituationSuperInteraction: {}'.format(self), owner='rez')
        situation_manager = services.get_zone_situation_manager()
        host_sim_id = 0
        host_sim = self.get_participant(self.host_sim)
        if host_sim is not None:
            host_sim_id = host_sim.sim_id
        guest_list = SituationGuestList(host_sim_id=host_sim_id)
        if self.job_mapping:
            for (participant_type, job) in self.job_mapping.items():
                sim = self.get_participant(participant_type)
                while sim is not None and sim.is_sim:
                    guest_info = SituationGuestInfo.construct_from_purpose(sim.sim_id, job, SituationInvitationPurpose.INVITED)
                    guest_list.add_guest_info(guest_info)
        situation_manager.create_situation(self.situation, guest_list=guest_list, user_facing=False)
        return event_testing.results.ExecuteResult.NONE

