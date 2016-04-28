from sims4.tuning.instances import TunedInstanceMetaclass
import sims

def format_object_name(obj):
    if not isinstance(type(obj), TunedInstanceMetaclass):
        return str(obj)
    if isinstance(obj, sims.sim.Sim):
        return obj.full_name
    name = type(obj).__name__
    obj_str = str(obj)
    if name in obj_str:
        return name
    return '{0} ({1})'.format(name, obj_str)

def format_object_list_names(items):
    return ', '.join(format_object_name(item) for item in items)

