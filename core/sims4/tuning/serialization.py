from _pyio import StringIO
from xml.sax.saxutils import XMLGenerator, escape
from xml.sax.xmlreader import AttributesImpl
import collections
import inspect
import os
import pydoc
from sims4.resources import ResourceLoader
from sims4.tuning.instance_manager import TuningCallbackHelper, increment_tunable_callback_count, increment_verify_tunable_callback_count
from sims4.tuning.merged_tuning_manager import MergedTuningAttr, get_manager
from sims4.tuning.tunable_base import Tags, Attributes, TunableBase, TunableAliasError, TunableFileReadOnlyError, DELETEDMARKER, LoadingAttributes, LoadingTags
import enum
import paths
import sims4.core_services
import sims4.log
import sims4.reload
import sims4.resources
import sims4.service_manager
import sims4.tuning.instances
import sims4.utils
import xml.etree.ElementTree as ET
logger = sims4.log.Logger('Tuning', default_owner='cjiang')
with sims4.reload.protected(globals()):
    _deferred_tuning_loaders = []
MODULE_TUNABLES = 'MODULE_TUNABLES'
ENUM_ENTRIES = 'ENUM_ENTRIES'
XML_ENTITIES = {'\n': '&#xA;', '\r': '&#xD;', '\t': '&#x9;'}
TUNING_LOADING_CALLBACK = '_tuning_loading_callback'
LOAD_MODULE_FOR_EXPORTING = False

def quoteattr(data):
    data = escape(data, XML_ENTITIES)
    if '"' in data:
        if "'" in data:
            data = '"%s"' % data.replace('"', '&quot;')
        else:
            data = "'%s'" % data
    else:
        data = '"%s"' % data
    return data

def process_tuning(module):
    if paths.TUNING_ROOTS is None:
        return False
    load_filename = get_file_name(module)
    module_tuning_root = paths.TUNING_ROOTS.get(sims4.resources.Types.TUNING)
    if module_tuning_root:
        save_filename = os.path.join(module_tuning_root, load_filename)
    else:
        save_filename = None
    result = load_module_tuning(module, save_filename)
    return result

def get_file_name(module):
    return '{0}.{1}'.format(module.__name__.replace('.', '-'), sims4.resources.extensions[sims4.resources.Types.TUNING])

def get_desc_file_name(module):
    return '{0}.{1}'.format(module.__name__.replace('.', '-'), sims4.resources.extensions[sims4.resources.Types.TUNING_DESCRIPTION])

def get_tdesc_frag_name(cls):
    return '{0}.{1}'.format(cls.__name__.replace('.', '-'), Attributes.TdescFragType)

def _enumerate_members(module, predicate, skip_private=True):
    items = module.__dict__.items()
    if hasattr(module, '__qualname__'):
        qual_path = module.__qualname__ + '.'
    else:
        qual_path = ''
    for (key, value) in items:
        if skip_private and key.startswith('__') and key.endswith('__'):
            pass
        while predicate(qual_path + key, value):
            yield (key, value)

def _tunable_check(_, obj):
    return isinstance(obj, TunableBase)

def _process_module_tunables(module, tunables):
    module.MODULE_TUNABLES = tunables
    for (key, tunable) in tunables.items():
        delattr(module, key)
        while tunable.needs_deferring:
            tunable.deferred = True

def _replace_tunables(scan, module):
    if MODULE_TUNABLES in vars(module):
        return True
    tunables = dict(_enumerate_members(module, _tunable_check))
    if tunables:
        reload_context = getattr(module, '__reload_context__', None)
        if reload_context:
            with reload_context(module, module):
                _process_module_tunables(module, tunables)
        else:
            _process_module_tunables(module, tunables)
        return True
    return False

def _scan_tunables(scan, module):
    if MODULE_TUNABLES in vars(module):
        scan.update(module.MODULE_TUNABLES)
        return bool(module.MODULE_TUNABLES)
    return False

def _scan_module_rec(scan, module, key_name, root_name, visited=None, for_export=False):
    if visited is None:
        visited = set()
    if for_export:
        module_scan = {}
    else:
        module_scan = collections.OrderedDict()
    attr_name = Attributes.Name if for_export else LoadingAttributes.Name
    if attr_name not in module_scan and hasattr(module, '__name__'):
        module_name = module.__name__
        if key_name in scan:
            for class_dict in scan[key_name]:
                while class_dict.get(attr_name) == module_name:
                    return False
        module_scan[attr_name] = module_name
    if inspect.isclass(module):
        if for_export:
            has_tunables = _scan_tunables(module_scan, module)
            module_scan[ENUM_ENTRIES] = module
            module_scan[Attributes.EnumBitFlag] = module.flags
            module_scan[Attributes.EnumLocked] = module.locked
            if module.display_sorted:
                module_scan[Attributes.DisplaySorted] = module.display_sorted
            if module.partitioned:
                module_scan[Attributes.Partitioned] = module.partitioned
            has_tunables = True
        else:
            has_tunables = _replace_tunables(module_scan, module)
    else:
        has_tunables = False

    def _is_visible_class(name, obj):
        if inspect.isclass(obj) and obj.__module__ == root_name:
            if name == obj.__qualname__:
                return True
        return False

    def _sort_key(enumerate_tuple):
        if for_export:
            try:
                return inspect.getsourcelines(enumerate_tuple[1])[1]
            except IOError:
                return 0
        else:
            return enumerate_tuple[0]

    class_tag = Tags.Class if for_export else LoadingTags.Class
    for (_cls_name, cls) in sorted(_enumerate_members(module, _is_visible_class), key=_sort_key):
        while cls not in visited:
            visited.add(cls)
            has_tunables |= _scan_module_rec(module_scan, cls, class_tag, root_name, visited=visited, for_export=for_export)
    if has_tunables:
        if key_name not in scan:
            scan[key_name] = []
        scan[key_name].append(module_scan)
    return has_tunables

def export_tuning(module, export_path):
    if not hasattr(module, '__file__'):
        return True
    writer = None
    try:
        schema_dict = {}
        has_tunables = _scan_module_rec(schema_dict, module, Tags.Module, module.__name__, for_export=True)
        while has_tunables:
            writer = TuningDescFileWriter(module, export_path, whitespace_depth=2)
            writer.open()
            _export_module(writer, schema_dict)
    except TunableFileReadOnlyError as exc:
        logger.error(str(exc))
        return False
    except:
        logger.exception('Error during export of module {0}', module)
        return False
    finally:
        if writer is not None:
            writer.close()
    return True

ATTRIBUTES_RESERVED_KEYS = [Attributes.InstancePath, Attributes.InstanceType, Attributes.InstanceClass, Attributes.InstanceModule, Attributes.InstanceSubclassesOnly, Attributes.InstanceParents, Attributes.Description]

def export_class(cls, export_path, instance_type):
    writer = None
    try:
        logger.debug(' Exporting: {}', cls.__name__)
        schema_dict = cls.get_tunables(ignore_tuned_instance_metaclass_subclasses=True)
        for reserved_key in ATTRIBUTES_RESERVED_KEYS:
            while reserved_key in schema_dict:
                raise KeyError("{} use reserved key '{}' in instance tunables. Please rename the tunable.".format(cls.__name__, reserved_key))
        removed_tuning = cls.get_removed_tunable_names()
        for tuning_to_remove in removed_tuning:
            schema_dict[tuning_to_remove] = DELETEDMARKER
        relative_path = os.path.relpath(export_path, paths.DATA_ROOT)
        schema_dict[Attributes.InstancePath] = relative_path
        schema_dict[Attributes.InstanceType] = sims4.resources.extensions[instance_type]
        schema_dict[Attributes.InstanceClass] = cls.__name__
        schema_dict[Attributes.InstanceModule] = cls.__module__
        schema_dict[Attributes.InstanceSubclassesOnly] = sims4.tuning.instances.prohibits_instantiation(cls)
        if cls.tuning_manager.use_guid_for_ref:
            schema_dict[Attributes.InstanceUseGuidForRef] = True
        parent_names = []
        for parent in cls.__mro__[1:]:
            while isinstance(parent, sims4.tuning.instances.TunedInstanceMetaclass):
                parent_names.append(parent.__name__)
        if parent_names:
            schema_dict[Attributes.InstanceParents] = ', '.join(parent_names)
        if cls.__doc__:
            schema_dict[Attributes.Description] = pydoc.getdoc(cls)
        full_schema_dict = {Tags.Instance: schema_dict}
        writer = TuningDescFileWriter(cls, export_path=export_path, whitespace_depth=1)
        writer.open()
        _export_module(writer, full_schema_dict)
    except TunableFileReadOnlyError as exc:
        logger.error(str(exc))
        return False
    except:
        logger.exception('Error during export of class {0}', cls)
        return False
    finally:
        if writer is not None:
            writer.close()
    return True

def export_fragment(cls, export_path):
    writer = None
    try:
        logger.debug(' Exporting: {}', cls.__name__)
        writer = TuningDescFileWriter(cls, export_path=export_path, whitespace_depth=1)
        writer.open()
        writer.write_frag(cls())
    except Exception as exc:
        logger.error(str(exc))
        return False
    except:
        logger.exception('Error during export of fragment {0}', cls)
        return False
    finally:
        if writer is not None:
            writer.close()
    return True

def _export_module(writer, scan):
    for (name, value) in sorted(scan.items()):
        if isinstance(value, TunableBase):
            if value.name is None:
                value.name = name
            elif value.name != name:
                raise TunableAliasError(value.name)
            writer.write_tunable(value)
        elif isinstance(value, enum.Metaclass) and value.export:
            writer.write_enum_items(value)
        elif isinstance(value, dict):
            writer.start_namespace(name, value)
            _export_module(writer, value)
            writer.end_namespace(name)
        elif isinstance(value, list):
            while True:
                for sub_dict in value:
                    writer.start_namespace(name, sub_dict)
                    _export_module(writer, sub_dict)
                    writer.end_namespace(name)
                while value is DELETEDMARKER:
                    writer.write_deleted_tunable(name)
        else:
            while value is DELETEDMARKER:
                writer.write_deleted_tunable(name)

def _find_tunables_gen(name, tree, parent):
    for (category, sub_list) in tree.items():
        if category == LoadingAttributes.Name and MODULE_TUNABLES in vars(parent):
            for (tunable_name, tunable) in parent.MODULE_TUNABLES.items():
                yield (tunable_name, tunable, parent)
        while category in (LoadingTags.Class, LoadingTags.Instance, LoadingTags.Module):
            while True:
                for sub_tree in sub_list:
                    child_name = sub_tree.get(LoadingAttributes.Name, None)
                    if name:
                        child = vars(parent).get(child_name)
                    else:
                        child = parent
                    for t in _find_tunables_gen(child_name, sub_tree, child):
                        yield t

def load_module_tuning(module, tuning_filename_or_key):
    schema_dict = {}
    has_tunables = _scan_module_rec(schema_dict, module, LoadingTags.Module, module.__name__, for_export=False)
    if not has_tunables:
        return True
    if not LOAD_MODULE_FOR_EXPORTING:
        tuning_loader = ETreeTuningLoader(module, tuning_filename_or_key)
        mtg = get_manager()
        if isinstance(tuning_filename_or_key, str):
            full_name = os.path.basename(tuning_filename_or_key)
            res_name = os.path.splitext(full_name)[0]
            res_key = sims4.resources.get_resource_key(res_name, sims4.resources.Types.TUNING)
        else:
            res_key = tuning_filename_or_key
        if mtg.local_key_exists(res_key):
            loader = ResourceLoader(res_key, sims4.resources.Types.TUNING)
            tuning_file = loader.load()
            tuning_loader.feed(tuning_file)
        else:
            root_node = mtg.get_tuning_res(res_key, silent_fail=True)
            if root_node is not None:
                tuning_loader.feed_node(root_node)
    for (name, tunable, parent) in _find_tunables_gen(None, schema_dict, module):
        if name in vars(parent):
            while not tunable.deferred:
                tuned_value = getattr(parent, name)
                tunable.invoke_callback(None, name, tuning_filename_or_key, tuned_value)
                value = tunable.default
                reload_context = getattr(parent, '__reload_context__', None)
                if reload_context:
                    with reload_context(parent, parent):
                        setattr(parent, name, value)
                else:
                    setattr(parent, name, value)
        value = tunable.default
        reload_context = getattr(parent, '__reload_context__', None)
        if reload_context:
            with reload_context(parent, parent):
                setattr(parent, name, value)
        else:
            setattr(parent, name, value)
    return True

def create_class_instance(resource_key, resource_type):
    tuning_loader = ETreeClassCreator('Instance: {0}, Type: {1}'.format(resource_key, resource_type))
    mtg = get_manager()
    if mtg.deleted_local_key_exists(resource_key):
        return
    if mtg.local_key_exists(resource_key):
        loader = ResourceLoader(resource_key, resource_type)
        tuning_file = loader.load()
        tuning_loader.feed(tuning_file)
    else:
        root_node = mtg.get_tuning_res(resource_key)
        if root_node is not None:
            tuning_loader.feed_node(root_node)
    return tuning_loader.module

def load_from_xml(resource_key, resource_type, inst, from_reload=False):
    mtg = get_manager()
    tuning_loader = ETreeTuningLoader(inst, 'Instance: {0}, Type: {1}'.format(resource_key, resource_type), loading_tag=LoadingTags.Instance)
    if mtg.deleted_local_key_exists(resource_key):
        tuning_loader.module = None
    else:
        if from_reload or mtg.local_key_exists(resource_key):
            loader = ResourceLoader(resource_key, resource_type)
            tuning_file = loader.load()
            if tuning_file is not None:
                return tuning_loader.feed(tuning_file)
        if mtg.has_combined_tuning_loaded:
            root_node = mtg.get_tuning_res(resource_key)
            if root_node is not None:
                return tuning_loader.feed_node(root_node)

def restore_class_instance(inst):
    tunables = inst.get_tunables()
    for name in tunables:
        while name in vars(inst):
            delattr(inst, name)
    if hasattr(inst, TUNING_LOADING_CALLBACK):
        inst._tuning_loading_callback()

class ETreeTuningLoader:
    __qualname__ = 'ETreeTuningLoader'

    def __init__(self, module, source, loading_tag=LoadingTags.Module):
        self.module = module
        self.source = source
        self.root = None
        self._invoke_names = []
        self._loading_tag = loading_tag

    def feed(self, tuning_file):
        tree = ET.parse(tuning_file)
        self.root = tree.getroot()
        return self._load_node(self.root, self.module)

    def feed_node(self, node):
        return self._load_node(node, self.module)

    def _load_node(self, node, tunable_class):
        callback_infos = []
        verify_callback_infos = []
        mtg = get_manager()
        if node.tag == LoadingTags.Module:
            for child_node in node:
                name = child_node.get(LoadingAttributes.Name)
                child_class = self._inner_module(tunable_class, name)
                node_to_load = child_node
                if child_node.tag == MergedTuningAttr.Reference:
                    ref_index = child_node.get(MergedTuningAttr.Index)
                    node_to_load = mtg.get_tunable_node(ref_index)
                self._load_node(node_to_load, child_class)
        else:
            if node.tag == LoadingTags.Class:
                tunable_datas = self._get_module_tunables_from_class(tunable_class)
            else:
                tunable_datas = tunable_class.get_tunables()
            for child_node in node:
                tunable_name = child_node.get(LoadingAttributes.Name, '')
                if tunable_datas is not None and tunable_name in tunable_datas:
                    tunable = tunable_datas.get(tunable_name)
                    if tunable is None or not isinstance(tunable, TunableBase):
                        logger.error('Attempt to load a value from {0} that is no longer tunable: {1}'.format(self.source, tunable_name))
                    else:
                        self._load_tunable(tunable_class, tunable_name, tunable, child_node, mtg)
                        sub_child_class = self._inner_module(tunable_class, tunable_name)
                        if sub_child_class is not None:
                            node_to_load = child_node
                            if child_node.tag == MergedTuningAttr.Reference:
                                ref_index = child_node.get(MergedTuningAttr.Index)
                                node_to_load = mtg.get_tunable_node(ref_index)
                            self._load_node(node_to_load, sub_child_class)
                        else:
                            logger.error('Attempt to load a value from {0} that is no longer tunable: {1}'.format(self.source, tunable_name))
                else:
                    sub_child_class = self._inner_module(tunable_class, tunable_name)
                    if sub_child_class is not None:
                        node_to_load = child_node
                        if child_node.tag == MergedTuningAttr.Reference:
                            ref_index = child_node.get(MergedTuningAttr.Index)
                            node_to_load = mtg.get_tunable_node(ref_index)
                        self._load_node(node_to_load, sub_child_class)
                    else:
                        logger.error('Attempt to load a value from {0} that is no longer tunable: {1}'.format(self.source, tunable_name))
            if self._loading_tag == LoadingTags.Instance:
                tunable_data = self.module.get_tunables()
                if tunable_data is not None:
                    while True:
                        for name in self._invoke_names:
                            template = tunable_data.get(name)
                            while template is not None:
                                tuned_value = getattr(self.module, name)
                                if template.has_callback:
                                    callback_infos.append(TuningCallbackHelper(template, name, self.source, tuned_value))
                                if template.has_verify_tunable_callback:
                                    verify_callback_infos.append(TuningCallbackHelper(template, name, self.source, tuned_value))
        increment_tunable_callback_count(len(callback_infos))
        increment_verify_tunable_callback_count(len(verify_callback_infos))
        return (callback_infos, verify_callback_infos)

    def _load_tunable(self, tunable_class, tunable_name, tunable, cur_node, mtg):
        if cur_node.tag != MergedTuningAttr.Reference:
            current_tunable_tag = tunable.LOADING_TAG_NAME
            if current_tunable_tag == Tags.TdescFragTag:
                current_tunable_tag = tunable.FRAG_TAG_NAME
            if current_tunable_tag != cur_node.tag:
                logger.error("Incorrectly matched tuning types found in tuning for {0} in {1}. Expected '{2}', got '{3}'".format(tunable_name, self.source, current_tunable_tag, cur_node.tag))
                logger.error('ATTRS: {}'.format(cur_node.items()))
        try:
            deferred = False
            if tunable.deferred and sims4.core_services.defer_tuning_references:
                value = _DeferredEtreeTunableLoader(tunable, node=cur_node, source=self.source)
                _deferred_tuning_loaders.append(value)
                deferred = True
            elif cur_node.tag == MergedTuningAttr.Reference:
                ref_index = cur_node.get(MergedTuningAttr.Index)
                value = mtg.get_tunable(ref_index, tunable, source=self.source)
            else:
                value = tunable.load_etree_node(node=cur_node, source=self.source)
            reload_context = getattr(tunable_class, '__reload_context__', None)
            if reload_context:
                with reload_context(tunable_class, tunable_class):
                    setattr(tunable_class, tunable_name, value)
            else:
                setattr(tunable_class, tunable_name, value)
            while not deferred:
                self._invoke_names.append(tunable_name)
        except Exception:
            logger.exception("Error occurred within the tag named '{}' (value: {})", cur_node.get(LoadingAttributes.Name), cur_node.tag)
            raise

    def _inner_module(self, cursor, name):
        if name == self._loading_tag:
            return cursor
        return vars(cursor).get(name)

    def _get_module_tunables_from_class(self, cls):
        if MODULE_TUNABLES in vars(cls):
            return cls.MODULE_TUNABLES

class ETreeClassCreator:
    __qualname__ = 'ETreeClassCreator'

    def __init__(self, source):
        self.source = source
        self.module = None

    def feed(self, tuning_file):
        tree = ET.parse(tuning_file)
        self.root = tree.getroot()
        self._load_node(self.root, self.module)

    def feed_node(self, node):
        self._load_node(node, self.module)

    def _load_node(self, node, tunable_class):
        if node.tag == LoadingTags.Instance:
            module_name = node.get(LoadingAttributes.InstanceModule)
            cls_name = node.get(LoadingAttributes.InstanceClass)
            inst_name = node.get(LoadingAttributes.Name)
            cls = sims4.utils.find_class(module_name, cls_name)
            self.module = cls.generate_tuned_type(inst_name)

class _DeferredEtreeTunableLoader:
    __qualname__ = '_DeferredEtreeTunableLoader'

    def __init__(self, template, node, source):
        self.template = template
        self.node = node
        self.source = source
        self.tunable_name = None
        self.value = None

    def load_value(self):
        if self.node is None:
            return
        try:
            self.tunable_name = self.node.get(LoadingAttributes.Name)
            if self.node.tag == MergedTuningAttr.Reference:
                ref_index = self.node.get(MergedTuningAttr.Index)
                mtg = get_manager()
                self.value = mtg.get_tunable(ref_index, self.template, source=self.source)
            else:
                self.value = self.template.load_etree_node(node=self.node, source=self.source)
        except Exception:
            logger.exception("Error parsing deferred tuning within the tag named '{}' (source: {})".format(self.tunable_name, self.source))
            raise
        self.node = None

    def __get__(self, instance, owner):
        self.load_value()
        reload_context = getattr(owner, '__reload_context__', None)
        if reload_context:
            with reload_context(owner, owner):
                setattr(owner, self.tunable_name, self.value)
        else:
            setattr(owner, self.tunable_name, self.value)
        self.template.invoke_callback(None, self.tunable_name, self.source, self.value)
        return self.value

class FinalizeTuningService(sims4.service_manager.Service):
    __qualname__ = 'FinalizeTuningService'

    def start(self):
        self.finalize_deferred_loads()
        if not sims4.core_services.SUPPORT_RELOADING_RESOURCES:
            merged_tuning_manager = get_manager()
            merged_tuning_manager.clear()

    def finalize_deferred_loads(self):
        for deferred_loader in _deferred_tuning_loaders:
            deferred_loader.load_value()
        _deferred_tuning_loaders.clear()

class TuningDescFileWriter:
    __qualname__ = 'TuningDescFileWriter'
    SORT_OVERRIDE = collections.defaultdict(lambda : 0, {'name': 100, 'class': 99, 'type': 98, 'default': 97, 'min': -1, 'max': -2, 'description': -100})

    def __init__(self, module, export_path, whitespace_depth=0):
        if export_path is None:
            export_path = paths.TUNING_ROOTS[sims4.resources.Types.TUNING]
        tuning_file = self.get_file_name(module)
        self._filename = os.path.join(export_path, tuning_file)
        self._writer = None
        self._whitespace_depth = whitespace_depth

    def get_file_name(self, module):
        is_fragment = getattr(module, 'is_fragment', False)
        if is_fragment:
            return get_tdesc_frag_name(module)
        return get_desc_file_name(module)

    def open(self):
        self._open()

    @staticmethod
    def list_key(value):
        if isinstance(value, dict):
            return value.get(Attributes.Name, '')
        return ''

    @staticmethod
    def sort_tags_recursive(attr_vals, sort_override=None):
        if not sort_override:
            sort_key = None
        else:

            def sort_key(value):
                return (-sort_override[value], value)

        if isinstance(attr_vals, dict) and not isinstance(attr_vals, collections.OrderedDict):
            new_vals = collections.OrderedDict()
            for key in sorted(attr_vals, key=sort_key):
                new_vals[key] = TuningDescFileWriter.sort_tags_recursive(attr_vals[key], sort_override)
            return new_vals
        if isinstance(attr_vals, list):
            new_vals = []
            for value in sorted(attr_vals, key=TuningDescFileWriter.list_key):
                new_vals.append(TuningDescFileWriter.sort_tags_recursive(value, sort_override))
            return new_vals
        return attr_vals

    def write_tunable(self, tunable):
        desc_tag = tunable.TAGNAME
        attr_vals = tunable.export_desc()
        sorted_vals = TuningDescFileWriter.sort_tags_recursive(attr_vals, sort_override=TuningDescFileWriter.SORT_OVERRIDE)
        self._writer.startElement(desc_tag, AttributesImpl(sorted_vals), can_close=True)
        self._writer.endElement(desc_tag)

    def write_frag(self, tunable):
        desc_tag = Attributes.TdescFragClass
        tunable_vals = {}
        attr_vals = tunable.frag_desc()
        tunable_vals[tunable.FRAG_TAG_NAME] = attr_vals
        sorted_vals = TuningDescFileWriter.sort_tags_recursive(tunable_vals, sort_override=TuningDescFileWriter.SORT_OVERRIDE)
        self._writer.startElement(desc_tag, AttributesImpl(sorted_vals), can_close=True)
        self._writer.endElement(desc_tag)

    def write_enum_items(self, enum_class):
        if hasattr(enum_class, '_static_index'):
            last_static_index = enum_class._static_index + 1
        else:
            last_static_index = len(enum_class.names)
        for i in range(last_static_index):
            enum_name = enum_class.names[i]
            enum_value = int(enum_class[enum_name])
            attr_vals = {Attributes.Name: enum_name, Attributes.EnumValue: enum_value}
            self._writer.startElement(Tags.EnumItem, AttributesImpl(attr_vals), can_close=True)
            self._writer.endElement(Tags.EnumItem)

    def write_deleted_tunable(self, deleted_tunable_name):
        attr_vals = {Attributes.Name: deleted_tunable_name}
        self._writer.startElement(Tags.Deleted, AttributesImpl(attr_vals), can_close=True)
        self._writer.endElement(Tags.Deleted)

    def _open(self):

        class Writer(XMLGenerator):
            __qualname__ = 'TuningDescFileWriter._open.<locals>.Writer'
            SPACES_PER_INDENT = 4

            def __init__(self, *args, whitespace_depth=0, **kwargs):
                super().__init__(*args, **kwargs)
                self._whitespace_depth = whitespace_depth
                self._indent = 0
                self._already_closed = None
                self._last_indent = -1

            def startElement(self, name, attrs, can_close=False):
                sub_elements = {}
                if self._indent == self._last_indent and self._indent <= self.SPACES_PER_INDENT*self._whitespace_depth:
                    self.add_new_line()
                self._last_indent = self._indent
                self._write('{0}<{1}'.format(' '*self._indent, name))
                for (attr_name, value) in attrs.items():
                    if isinstance(value, dict) or isinstance(value, list):
                        sub_elements[attr_name] = value
                    else:
                        while value is not None:
                            self._write(' %s=%s' % (attr_name, quoteattr(str(value))))
                if not sub_elements and can_close:
                    self._write(' />\n'.format(name))
                    self._already_closed = name
                else:
                    self._write('>\n')
                    for (name, value) in sub_elements.items():
                        if isinstance(value, dict):
                            self.startElement(name, value, can_close=True)
                            self.endElement(name)
                        else:
                            for sub_item in value:
                                self.startElement(name, sub_item, can_close=True)
                                self.endElement(name)

            def endElement(self, name):
                if self._already_closed is not None:
                    self._already_closed = None
                else:
                    self._write(' '*self._indent)
                    super().endElement(name)
                    self.add_new_line()
                    self._last_indent = self._indent

            def add_new_line(self):
                self._write('\n')

        self._string = StringIO()
        self._writer = Writer(self._string, whitespace_depth=self._whitespace_depth)
        self._writer.startDocument()
        self._writer.add_new_line()

    def start_namespace(self, namespace, contents):
        attribute_dict = {}
        for (attribute, value) in contents.items():
            while not isinstance(value, TunableBase) and (not isinstance(value, dict) and (not isinstance(value, list) and not isinstance(value, enum.Metaclass))) and value is not DELETEDMARKER:
                attribute_dict[attribute] = value
        self._writer.startElement(namespace, attribute_dict)

    def end_namespace(self, namespace):
        self._writer.endElement(namespace)

    def close(self):
        self._writer.endDocument()
        serialized_data = self._string.getvalue()
        self._string.close()
        path = os.path.split(self._filename)[0]
        if path and not os.path.exists(path):
            os.makedirs(path)
        do_compare = True
        tuning_file = None
        created = True
        if os.path.exists(self._filename):
            created = False
            if not do_compare:
                try:
                    with open(self._filename, 'w'):
                        pass
                except IOError:
                    do_compare = True
            if do_compare:
                with open(self._filename, 'r') as old_tuning_file:
                    old_serialized_data = old_tuning_file.read()
                if serialized_data == old_serialized_data:
                    logger.debug('Skipped tuning file: {}', self._filename)
                    return
        try:
            tuning_file = open(self._filename, 'w')
        except IOError:
            raise TunableFileReadOnlyError(self._filename)
        with tuning_file:
            tuning_file.write(serialized_data)
            if created:
                logger.warn('CREATED tuning file: {}', self._filename)
            elif do_compare:
                logger.info('Updated tuning file: {}', self._filename)
            else:
                logger.info('Wrote   tuning file: {}', self._filename)

def _test():
    import doctest
    doctest.testmod()

if __name__ == '__main__':
    _test()
