from collections import Counter
import time
from gsi_handlers.gameplay_archiver import GameplayArchiver
from objects import ALL_HIDDEN_REASONS
from sims4.gsi.schema import GsiGridSchema, GsiFieldVisualizers
from sims4.tuning.tunable import TunableSet, TunableEnumEntry
from tag import Tag
import alarms
import clock
import services
import sims4
performance_archive_schema = GsiGridSchema(label='Performance Metrics Log')
performance_archive_schema.add_field('autonomy_queue_time', label='Autonomy Q Time', type=GsiFieldVisualizers.INT, width=2)
performance_archive_schema.add_field('autonomy_queue_length', label='Autonomy Q Len', type=GsiFieldVisualizers.INT, width=2)
performance_archive_schema.add_field('ticks_per_sec', label='Ticks Per Sec', type=GsiFieldVisualizers.FLOAT, width=2)
performance_archive_schema.add_field('num_sims', label='#Sims', type=GsiFieldVisualizers.INT)
performance_archive_schema.add_field('num_sim_infos', label='#SimInfos', type=GsiFieldVisualizers.INT)
performance_archive_schema.add_field('num_objects_active_lot', label='#Obj(ActiveLot)', type=GsiFieldVisualizers.INT, width=3)
performance_archive_schema.add_field('num_objects_open_street', label='#Objects(OpenStreet)', type=GsiFieldVisualizers.INT, width=3)
performance_archive_schema.add_field('num_props', label='#Props', type=GsiFieldVisualizers.INT)
performance_archive_schema.add_field('total_objects_props', label='Total Objs&Props', type=GsiFieldVisualizers.INT, width=2)
with performance_archive_schema.add_has_many('AdditionalMetrics', GsiGridSchema) as sub_schema:
    sub_schema.add_field('metric', label='Metric')
    sub_schema.add_field('count', label='Count', type=GsiFieldVisualizers.INT)
OBJECT_CLASSIFICATIONS = ['ActiveLot(Interactive)', 'ActiveLot(Decorative)', 'OpenStreet(Interactive)', 'OpenStreet(Decorative)']
for name in OBJECT_CLASSIFICATIONS:
    with performance_archive_schema.add_has_many(name, GsiGridSchema) as sub_schema:
        sub_schema.add_field('object_name', label='Object Name')
        sub_schema.add_field('frequency', label='Frequency', type=GsiFieldVisualizers.INT)
with sims4.reload.protected(globals()):
    performance_log_alarm = None
    previous_log_time_stamp = 0
    previous_log_time_ticks = 0
SECONDS_BETWEEN_LOGGING = 600
performance_metrics = []
archive_data = {'autonomy_queue_time': 0, 'autonomy_queue_length': 0, 'ticks_per_sec': 0, 'num_sims': 0, 'num_sim_infos': 0, 'num_objects_active_lot': 0, 'num_objects_open_street': 0, 'num_props': 0, 'total_objects_props': 0}

def enable_performance_logging(*args, enableLog=False, **kwargs):
    global previous_log_time_stamp, previous_log_time_ticks, performance_log_alarm
    if enableLog:
        if performance_log_alarm is not None:
            return

        def alarm_callback(_):
            global previous_log_time_stamp, previous_log_time_ticks
            generate_statistics()
            _log_performance_metrics()
            previous_log_time_stamp = time.time()
            previous_log_time_ticks = services.server_clock_service().now().absolute_ticks()

        previous_log_time_stamp = time.time()
        previous_log_time_ticks = services.server_clock_service().now().absolute_ticks()
        set_gsi_performance_metric('ticks_per_sec', 'N/A')
        _log_performance_metrics()
        current_zone = services.current_zone()
        if performance_log_alarm is not None:
            alarms.cancel_alarm(performance_log_alarm)
        performance_log_alarm = alarms.add_alarm_real_time(current_zone, clock.interval_in_real_seconds(SECONDS_BETWEEN_LOGGING), alarm_callback, repeating=True, use_sleep_time=False)
    elif performance_log_alarm is not None:
        alarms.cancel_alarm(performance_log_alarm)
        performance_log_alarm = None
        previous_log_time_stamp = 0
        set_gsi_performance_metric('ticks_per_sec', 'N/A')

def generate_statistics():
    now_ticks = services.server_clock_service().now().absolute_ticks()
    ticks_elapsed = now_ticks - previous_log_time_ticks
    now_time = time.time()
    time_elapsed = now_time - previous_log_time_stamp
    ticks_per_sec = 0
    if time_elapsed != 0:
        ticks_per_sec = ticks_elapsed/time_elapsed
    else:
        ticks_per_sec = 'Zero time elapsed. ticks elapsed = {}'.format(ticks_elapsed)
    num_sim_infos = 0
    num_sims = 0
    for sim_info in services.sim_info_manager().objects:
        num_sim_infos += 1
        while sim_info.is_instanced(allow_hidden_flags=ALL_HIDDEN_REASONS):
            num_sims += 1
    all_props = []
    if services.prop_manager():
        all_props = list(services.prop_manager().objects)
    all_objects = list(services.object_manager().objects)
    all_inventory_objects = list(services.current_zone().inventory_manager.objects)
    objects_active_lot_interactive = []
    objects_active_lot_decorative = []
    objects_open_street_interactive = []
    objects_open_street_decorative = []
    for obj in all_objects:
        tags = obj.definition.build_buy_tags
        if obj.is_on_active_lot():
            if PerformanceHandlerTuning.DECORATIVE_OBJECT_TAGS_ACTIVE_LOT & tags:
                objects_active_lot_decorative.append(obj)
            else:
                objects_active_lot_interactive.append(obj)
                if PerformanceHandlerTuning.DECORATIVE_OBJECT_TAGS_OPEN_STREET & tags:
                    objects_open_street_decorative.append(obj)
                else:
                    objects_open_street_interactive.append(obj)
        elif PerformanceHandlerTuning.DECORATIVE_OBJECT_TAGS_OPEN_STREET & tags:
            objects_open_street_decorative.append(obj)
        else:
            objects_open_street_interactive.append(obj)
    performance_metrics.clear()
    set_gsi_performance_metric('num_sims', num_sims)
    set_gsi_performance_metric('num_sim_infos', num_sim_infos)
    set_gsi_performance_metric('num_objects_active_lot', len(objects_active_lot_interactive) + len(objects_active_lot_decorative))
    set_gsi_performance_metric('num_objects_open_street', len(objects_open_street_interactive) + len(objects_open_street_decorative))
    set_gsi_performance_metric('num_props', len(all_props))
    set_gsi_performance_metric('total_objects_props', len(all_props) + len(all_objects))
    set_gsi_performance_metric('ticks_per_sec', ticks_per_sec)
    metrics = [('#Objects (Active Lot) Interactive', lambda : len(objects_active_lot_interactive)), ('#Objects (Active Lot) Decorative', lambda : len(objects_active_lot_decorative)), ('#Objects (OpenStreet) Interactive', lambda : len(objects_open_street_interactive)), ('#Objects (OpenStreet) Decorative', lambda : len(objects_open_street_decorative)), ('Total Objects', lambda : len(all_objects)), ('Total Props', lambda : len(all_props)), ('Total Inventory Objects', lambda : len(all_inventory_objects)), ('Grand Total (Objs,Props,InventoryObjs)', lambda : len(all_props) + len(all_objects) + len(all_inventory_objects))]
    details = list()
    for (name, func) in metrics:
        entry = {'metric': name, 'count': func()}
        details.append(entry)
    set_gsi_performance_metric('AdditionalMetrics', details)

    def generate_histogram(name, objects):
        histogram_counter = Counter([obj.definition.name for obj in objects])
        histogram = list()
        for (obj_name, freq) in histogram_counter.most_common():
            entry = {'object_name': obj_name, 'frequency': freq}
            histogram.append(entry)
        set_gsi_performance_metric(name, histogram)

    generate_histogram(OBJECT_CLASSIFICATIONS[0], objects_active_lot_interactive)
    generate_histogram(OBJECT_CLASSIFICATIONS[1], objects_active_lot_decorative)
    generate_histogram(OBJECT_CLASSIFICATIONS[2], objects_open_street_interactive)
    generate_histogram(OBJECT_CLASSIFICATIONS[3], objects_open_street_decorative)
    return performance_metrics

archiver = GameplayArchiver('performance_metrics', performance_archive_schema, custom_enable_fn=enable_performance_logging, add_to_archive_enable_functions=False)

def set_gsi_performance_metric(performance_metric_id, value):
    if performance_metric_id == 'AdditionalMetrics':
        for v in value:
            performance_metrics.append((str(v['metric']), str(v['count'])))
    else:
        performance_metrics.append((performance_metric_id, str(value)))
    archive_data[performance_metric_id] = value

def _log_performance_metrics():
    archiver.archive(data=archive_data)

class PerformanceHandlerTuning:
    __qualname__ = 'PerformanceHandlerTuning'
    DECORATIVE_OBJECT_TAGS_ACTIVE_LOT = TunableSet(description="\n                                            Tags that will be used by GSI's performance metric view \n                                            to classify active lot objects as decorative.\n                                            ", tunable=TunableEnumEntry(tunable_type=Tag, default=Tag.INVALID))
    DECORATIVE_OBJECT_TAGS_OPEN_STREET = TunableSet(description="\n                                            Tags that will be used by GSI's performance metric view \n                                            to classify open street objects as decorative.\n                                            ", tunable=TunableEnumEntry(tunable_type=Tag, default=Tag.INVALID))

