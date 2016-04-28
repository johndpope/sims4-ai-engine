import sys
import xml.sax.handler
import sims4.resources
import sims4.tuning.instance_manager
import sims4.tuning.serialization

class _EarlyExit(Exception):
    __qualname__ = '_EarlyExit'

class _ParseHandler(xml.sax.handler.ContentHandler):
    __qualname__ = '_ParseHandler'

    def __init__(self):
        self.module_name = None

    def startElement(self, name, attrs):
        if name == 'TuningRoot':
            return
        if name == sims4.tuning.tunable.LoadingTags.Instance:
            raise RuntimeError('Instance tuning can not be reloaded as module tuning')
        elif name == sims4.tuning.tunable.LoadingTags.Module:
            self.module_name = attrs[sims4.tuning.tunable.LoadingAttributes.Name]
            raise _EarlyExit
        raise RuntimeError('All tuning must start with either instance or module tuning')

def get_module_name_from_tuning(key):
    loader = sims4.resources.ResourceLoader(key)
    tuning_file = loader.load()
    parse_handler = _ParseHandler()
    try:
        xml.sax.parse(tuning_file, parse_handler)
    except _EarlyExit:
        return parse_handler.module_name

class ModuleTuningManager(sims4.tuning.instance_manager.InstanceManager):
    __qualname__ = 'ModuleTuningManager'

    def reload_by_key(self, key):
        if not __debug__:
            raise RuntimeError('[manus] Reloading tuning is not supported for optimized python builds.')
        module_name = get_module_name_from_tuning(key)
        module = sys.modules[module_name]
        sims4.tuning.serialization.load_module_tuning(module, key)

