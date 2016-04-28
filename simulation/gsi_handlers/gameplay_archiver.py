import weakref
import services
import sims4.gsi.archive
with sims4.reload.protected(globals()):
    tracked_objects_dict = {}
    deleted_objs = []
logger = sims4.log.Logger('GameplayArchiver')
MAX_DELETED_SIM_RECORDS = 10

def logged_gsi_object_deleted(obj):
    deleted_id = tracked_objects_dict[obj]
    del tracked_objects_dict[obj]
    deleted_objs.append(deleted_id)
    if len(deleted_objs) > MAX_DELETED_SIM_RECORDS:
        obj_to_cleanup = deleted_objs.pop(0)
        for archive_entries in sims4.gsi.archive.archive_data.values():
            while isinstance(archive_entries, dict):
                if obj_to_cleanup in archive_entries:
                    del archive_entries[obj_to_cleanup]

def print_num_archive_records():
    logger.warn('---------- Start GSI Archive Dump ----------')
    for (archive_type, archive_entries) in sims4.gsi.archive.archive_data.items():
        if isinstance(archive_entries, list):
            logger.warn('Type: {}, Entries: {}', archive_type, len(archive_entries))
        elif isinstance(archive_entries, dict):
            logger.warn('Type: {}', archive_type)
            for (sim_id, sim_data_entries) in archive_entries.items():
                logger.warn('    Sim Id: {}, Num Entries: {}', sim_id, len(sim_data_entries))
        else:
            logger.error('I have no idea what this entry is....')
    logger.warn('---------- End GSI Archive Dump ----------')

class GameplayArchiver(sims4.gsi.archive.Archiver):
    __qualname__ = 'GameplayArchiver'

    def archive(self, *args, object_id=None, **kwargs):
        if self._sim_specific:
            cur_sim = services.object_manager().get(object_id)
            if cur_sim is not None and not cur_sim.is_selectable:
                cur_sim_ref = weakref.ref(cur_sim, logged_gsi_object_deleted)
                if cur_sim_ref not in tracked_objects_dict:
                    tracked_objects_dict[cur_sim_ref] = object_id
                    if object_id in deleted_objs:
                        deleted_objs.remove(object_id)
        super().archive(object_id=object_id, *args, **kwargs)

