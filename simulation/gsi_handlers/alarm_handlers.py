from sims4.gsi.dispatcher import GsiHandler
from sims4.gsi.schema import GsiGridSchema, GsiFieldVisualizers
import alarms
alarm_schema = GsiGridSchema(label='Alarms')
alarm_schema.add_field('time', label='Absolute Time', width=2)
alarm_schema.add_field('time_left', label='Time Left', width=1)
alarm_schema.add_field('ticks', label='Ticks Left', type=GsiFieldVisualizers.INT)
alarm_schema.add_field('handle', label='Handle', width=1, unique_field=True, hidden=True)
alarm_schema.add_field('owner', label='Owner', width=3)
alarm_schema.add_field('callback', label='Callback', width=3)

@GsiHandler('alarms', alarm_schema)
def generate_alarm_data(*args, zone_id:int=None, **kwargs):
    return alarms.get_alarm_data_for_gsi()

