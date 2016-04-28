from protocolbuffers.Sparse_pb2 import SparseMessageData
from distributor.fields import Field
from distributor.system import Distributor
from singletons import DEFAULT
import sims4.log
logger = sims4.log.Logger('Sparse')
SPARSE_MESSAGE_DATA_FIELD_NUMBERS = []
for item in SparseMessageData.DESCRIPTOR.enum_types_by_name['FieldNumbers'].values:
    SPARSE_MESSAGE_DATA_FIELD_NUMBERS.append(item.number)
_message_type_to_sparse_data_attribute = {}
_message_type_to_repeated_attributes = {}

def get_sparse_data_attribute_for_message(message_or_type):
    if not isinstance(message_or_type, type):
        message_or_type = type(message_or_type)
    if message_or_type in _message_type_to_sparse_data_attribute:
        return _message_type_to_sparse_data_attribute[message_or_type]
    fields_by_number = message_or_type.DESCRIPTOR.fields_by_number
    sparse_data_attr = None
    for field_number in SPARSE_MESSAGE_DATA_FIELD_NUMBERS:
        while field_number in fields_by_number:
            field = fields_by_number[field_number]
            if field.message_type == SparseMessageData.DESCRIPTOR:
                sparse_data_attr = field.name
                break
    return sparse_data_attr

def get_repeated_attributes_for_message(message_or_type):
    if not isinstance(message_or_type, type):
        message_or_type = type(message_or_type)
    if message_or_type in _message_type_to_repeated_attributes:
        return _message_type_to_repeated_attributes[message_or_type]
    fields_by_name = message_or_type.DESCRIPTOR.fields_by_name
    repeated_attributes = {}
    for (name, field) in fields_by_name.items():
        while field.label == field.LABEL_REPEATED:
            repeated_attributes[name] = field.number
    _message_type_to_repeated_attributes[message_or_type] = repeated_attributes
    return repeated_attributes

class RepeatedFieldWrapper:
    __qualname__ = 'RepeatedFieldWrapper'
    ATTRS_TO_WRAP = ['__delitem__', '__setitem__', 'append', 'extend', 'insert', 'remove', 'sort']

    def __init__(self, sparse_message, field_number, container):
        self._sparse_message = sparse_message
        self._field_number = field_number
        self._container = container

    def __len__(self):
        return len(self._container)

    def __getitem__(self, key):
        return self._container[key]

    def __getattr__(self, name):
        return getattr(self._container, name)

def _make_wrapper(name):

    def f(self, *args, **kwargs):
        ret = getattr(self._container, name)(*args, **kwargs)
        if self._field_number not in self._sparse_message._set_fields:
            self._sparse_message._set_fields.append(self._field_number)
        return ret

    return f

for _name in RepeatedFieldWrapper.ATTRS_TO_WRAP:
    setattr(RepeatedFieldWrapper, _name, _make_wrapper(_name))
del _name
del _make_wrapper

class SparseMessage:
    __qualname__ = 'SparseMessage'
    _value = None

    def __init__(self, message):
        sparse_data_attr = get_sparse_data_attribute_for_message(message)
        if sparse_data_attr is None:
            raise ValueError('{} does not have a SparseMessageData field at one of the acceptable IDs: {}'.format(message, SPARSE_MESSAGE_DATA_FIELD_NUMBERS))
        self._sparse_data_attr = sparse_data_attr
        self._repeated_attrs = get_repeated_attributes_for_message(message).copy()
        self._value = message

    def get_non_sparse_value(self):
        result = type(self._value)()
        result.MergeFrom(self._value)
        self._clear_field(self._sparse_data_attr, result)
        return result

    def _is_self_attr(self, name):
        value = self._value
        if value is None:
            return True
        if name not in value.DESCRIPTOR.fields_by_name:
            return True
        return False

    def _clear_field(self, name, value=None):
        value = value if value is not None else self._value
        return value.ClearField(name)

    @property
    def _sparse_data(self):
        return getattr(self._value, self._sparse_data_attr)

    @property
    def _set_fields(self):
        return self._sparse_data.set_fields

    def _touch(self, field_number):
        if field_number not in self._set_fields:
            self._set_fields.append(field_number)

    def __getattr__(self, name):
        if name not in self._repeated_attrs:
            return getattr(self._value, name)
        repeated_attr = self._repeated_attrs[name]
        if not isinstance(repeated_attr, RepeatedFieldWrapper):
            container = getattr(self._value, name)
            repeated_attr = RepeatedFieldWrapper(self, repeated_attr, container)
            self._repeated_attrs[name] = repeated_attr
        return repeated_attr

    def __setattr__(self, name, value):
        if self._is_self_attr(name):
            return super().__setattr__(name, value)
        if name in self._repeated_attrs:
            repeated_field = getattr(self, name)
            self._clear_field(name)
            for i in value:
                repeated_field.append(i)
            self._touch(repeated_field._field_number)
            return
        field = self._value.DESCRIPTOR.fields_by_name[name]
        if value == field.default_value:
            ret = self._clear_field(name)
        else:
            ret = setattr(self._value, name, value)
        self._touch(field.number)
        return ret

    def __delattr__(self, name):
        if self._is_self_attr(name):
            return super().__delattr__(name)
        field = self._value.DESCRIPTOR.fields_by_name[name]
        ret = self._clear_field(name)
        field_number = field.number
        if field_number in self._set_fields:
            self._set_fields.remove(field_number)
        if not self._set_fields:
            ret = self._clear_field(self._sparse_data_attr)
        return ret

    def set_to_default(self, name):
        ret = self._clear_field(name)
        field = self._value.DESCRIPTOR.fields_by_name[name]
        self._touch(field.number)
        return ret

    @property
    def set_field_names(self):
        names = set()
        for field_number in self._set_fields:
            field = self._value.DESCRIPTOR.fields_by_number[field_number]
            name = field.name
            names.add(name)
        return names

class SparseField(Field):
    __qualname__ = 'SparseField'

    def __init__(self, message_type, op, field_name=None):
        super().__init__(op=op, getter=self._get_message, setter=self._set_message)
        self._message_type = message_type
        self._field_name = field_name or '_{}_sparse_value'.format(message_type.__name__)

    def _get_message(self, inst):
        try:
            value = getattr(inst, self._field_name)
        except AttributeError:
            value = SparseMessage(self._message_type())
            setattr(inst, self._field_name, value)
        return value

    def _set_message(self, inst, value):
        if not isinstance(value, SparseMessage):
            value = SparseMessage(value)
        setattr(inst, self._field_name, value)

    def __get__(self, *args, for_create=False, **kwargs):
        value = super().__get__(for_create=for_create, *args, **kwargs)
        if for_create:
            value = value.get_non_sparse_value()
        return value

    def getter(self, field_name):

        def getter_dec(getter):

            def _getter(inst):
                message = self._get_message(inst)
                return getter(inst, message)

            return _getter

        return getter_dec

    def setter(self, field_name):

        def setter_dec(setter):

            def _setter(inst, value):
                message = self._get_message(inst)
                ret = setter(inst, message, value, True)
                if inst.valid_for_distribution:
                    op_message = SparseMessage(self._message_type())
                    setter(inst, op_message, value, False)
                    op = self.get_op(inst, value=op_message._value)
                    if op is not None:
                        Distributor.instance().add_op(inst, op)
                return ret

            return _setter

        return setter_dec

    def deleter(self, field_name):

        def deleter_dec(deleter):

            def _deleter(inst):
                message = self._get_message(inst)
                return deleter(inst, message)

            return _deleter

        return deleter_dec

    def generic_getter(self, field_name):

        def generic_getter(inst, message):
            return getattr(message, field_name)

        return self.getter(field_name)(generic_getter)

    def generic_setter(self, field_name, auto_reset=DEFAULT):
        if auto_reset is DEFAULT:
            if field_name in self._message_type.DESCRIPTOR.fields_by_name:
                field = self._message_type.DESCRIPTOR.fields_by_name[field_name]
                auto_reset = field.type == field.TYPE_MESSAGE
            else:
                logger.error('Field missing from message type, are your protobufs out of sync? ({}.{})', self._message_type.__name__, field_name)
                auto_reset = False

        def generic_setter(inst, message, value, update_inst):
            if value is None and auto_reset:
                return message.set_to_default(field_name)
            return setattr(message, field_name, value)

        return self.setter(field_name)(generic_setter)

    def generic_deleter(self, field_name):

        def generic_deleter(inst, message):
            return delattr(message, field_name)

        return self.deleter(field_name)(generic_deleter)

    def generic_property(self, field_name, auto_reset=DEFAULT):
        return property(self.generic_getter(field_name), self.generic_setter(field_name, auto_reset=auto_reset))

