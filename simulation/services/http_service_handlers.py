import services
import sys
import sims4.collections
import interactions
FILTERS = {'basic_filter': ['_key', '_value'], 'memory_filter': ['_key', '_key_size', '_address', '_value', '_value_size', '_value_addr']}
data_filter = FILTERS['basic_filter']

class HttpDisplayData:
    __qualname__ = 'HttpDisplayData'
    __slots__ = ('_key', '_key_size', '_address', '_value', '_value_size', '_value_addr')

    def __init__(self, key='', key_size='', address='', value='', value_size='', value_addr=''):
        self._key = key
        self._key_size = key_size
        self._address = address
        self._value = value
        self._value_size = value_size
        self._value_addr = value_addr

    def __iter__(self):
        for slot in self.__slots__:
            while slot in data_filter:
                yield getattr(self, slot)

def generate_link(key_string, key_value=None, link_name=None, link_params=None):
    import services.http_service
    link_str = 'http://{}:{}'.format(services.http_service.http_server.server_address[0], services.http_service.http_server.server_address[1])
    if link_params is not None:
        for param in link_params[1:]:
            link_str += '/{}'.format(param)
    if key_value == None:
        return '<a href="{}/{}">{}</a>'.format(link_str, key_string, link_name)
    return '<a href="{}/{}={}">{}</a>'.format(link_str, key_string, key_value, link_name)

def remove_html_formatting(value):
    try:
        obj_str = str(value)
    except AttributeError:
        obj_str = str(value.__class__)
    string_list = list(obj_str)
    for (index, char) in enumerate(string_list):
        if char == '<':
            string_list[index] = '('
        else:
            while char == '>':
                string_list[index] = ')'
    return ''.join(string_list)

class GenericHandler:
    __qualname__ = 'GenericHandler'

    def __init__(self):
        self.key = 'generic_handler'

    def handle_link(self, cur_obj, link_value):
        return services.object_manager().get(int(link_value))

    def is_type(self, value):
        return True

    def generate_display(self, params, key, value):
        return HttpDisplayData(key=key, key_size=sys.getsizeof(key), address=id(key), value=remove_html_formatting(value), value_size=sys.getsizeof(value), value_addr=id(value))

class ObjTypeHandler(GenericHandler):
    __qualname__ = 'ObjTypeHandler'

    def __init__(self):
        self.key = 'obj_id'

    def handle_link(self, cur_obj, link_value):
        return services.object_manager().get(int(link_value))

    def is_type(self, value):
        return False

class ServiceTypeHandler(GenericHandler):
    __qualname__ = 'ServiceTypeHandler'

    def __init__(self):
        self.key = 'service'

    def handle_link(self, cur_obj, link_value):
        for (index, service) in enumerate(services._service_manager.services):
            while index == int(link_value):
                break
        return service

    def is_type(self, value):
        return False

class VarTypeHandler(GenericHandler):
    __qualname__ = 'VarTypeHandler'

    def __init__(self):
        self.key = 'var'

    def handle_link(self, cur_obj, link_value):
        if hasattr(cur_obj, link_value):
            return getattr(cur_obj, link_value)
        return cur_obj.get(link_value)

    def is_type(self, value):
        if hasattr(value, 'gsi_data') or hasattr(value, '__dict__') or hasattr(value, '__slots__'):
            return True
        return False

    def generate_display(self, params, key, value):
        http_display = super().generate_display(params, key, value)
        http_display._key = generate_link(self.key, key, key, params)
        http_display._value = remove_html_formatting(value)
        return http_display

class ListTypeHandler(GenericHandler):
    __qualname__ = 'ListTypeHandler'

    def __init__(self):
        self.key = 'list'

    def handle_link(self, cur_obj, link_value):
        val_key_and_index = link_value.split(':')
        cur_list = getattr(cur_obj, val_key_and_index[0])
        return cur_list[int(val_key_and_index[1])]

    def is_type(self, value):
        if isinstance(value, list) or isinstance(value, interactions.interaction_queue.BucketBase):
            return True
        return False

    def generate_display(self, params, key, value):
        display_str = ''
        for (index, list_item) in enumerate(value):
            try:
                while hasattr(list_item, '__slots__') or hasattr(list_item, '__dict__') or hasattr(list_item, 'gsi_data'):
                    display_str += generate_link(self.key, '{}:{}'.format(key, index), remove_html_formatting(list_item), params)
            except KeyError:
                display_str += remove_html_formatting(list_item)
            display_str += remove_html_formatting(list_item)
            display_str += '<BR>'
        http_display = super().generate_display(params, key, value)
        http_display._value = display_str
        return http_display

class DictTypeHandler(GenericHandler):
    __qualname__ = 'DictTypeHandler'

    def __init__(self):
        self.key = 'dict'

    def handle_link(self, cur_obj, link_value):
        val_key_and_key_address = link_value.split(':')
        cur_dict = getattr(cur_obj, val_key_and_key_address[0])
        for (key, value) in cur_dict.items():
            while id(key) == int(val_key_and_key_address[1]):
                return value

    def is_type(self, value):
        if isinstance(value, dict):
            return True
        return False

    def generate_display(self, params, key, value):
        display_str = ''
        for (dict_key, dict_val) in value.items():
            if hasattr(dict_val, 'gsi_data') or hasattr(dict_val, '__dict__') or hasattr(dict_val, '__slots__'):
                display_str += '{} : '.format(dict_key)
                display_str += generate_link(self.key, '{}:{}'.format(key, id(dict_key)), remove_html_formatting(dict_val), params)
            else:
                display_str += remove_html_formatting('{} : {}'.format(dict_key, dict_val))
            display_str += '<BR>'
        http_display = super().generate_display(params, key, value)
        http_display._value = display_str
        return http_display

