from sims4.gsi.schema import GsiGridSchema
from gsi_handlers.gameplay_archiver import GameplayArchiver
mc_archive_schema = GsiGridSchema(label='Master Controller Log')
mc_archive_schema.add_field('sims_with_active_work', label='Sims With Active Work Start', width=2)
mc_archive_schema.add_field('sims_with_active_work_after', label='Sims With Work After', width=2)
mc_archive_schema.add_field('last_time_stamp', label='Time Stamp At Start', width=2)
mc_archive_schema.add_field('last_time_stamp_end', label='Time Stamp At End', width=2)
with mc_archive_schema.add_has_many('Log', GsiGridSchema) as sub_schema:
    sub_schema.add_field('tag', label='Tag', width=0.25)
    sub_schema.add_field('sim', label='Sim', width=0.15)
    sub_schema.add_field('log', label='log')
with mc_archive_schema.add_has_many('active_work_start', GsiGridSchema) as sub_schema:
    sub_schema.add_field('sim', label='ID', width=0.2)
    sub_schema.add_field('work_entry', label='Work')
with mc_archive_schema.add_has_many('active_work_end', GsiGridSchema) as sub_schema:
    sub_schema.add_field('sim', label='ID', width=0.2)
    sub_schema.add_field('work_entry', label='Work')
archiver = GameplayArchiver('master_controller', mc_archive_schema, add_to_archive_enable_functions=False)

def archive_master_controller_entry(entry):
    archiver.archive(data=entry)

