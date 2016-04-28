from distributor.rollback import ProtocolBufferRollback
from sims4.log import LEVEL_EXCEPTION
import distributor.system
import enum
__unittest__ = 'test.distributor.fields_test'

class Field:
    __qualname__ = 'Field'
    _distributed_fields = {}
    _OBJECT_DIR = set(dir(object))
    _NO_DEFAULT = object()

    class Priority(enum.Int, export=False):
        __qualname__ = 'Field.Priority'
        LOW = -1
        NORMAL = 0
        HIGH = 1

    def __init__(self, getter=None, setter=None, op=None, priority:Priority=Priority.NORMAL, default=_NO_DEFAULT, direct_attribute_name=None, should_distribute_fn=None):
        self._get = getter
        self._set = setter
        self._op = op
        self._priority = priority
        self._default = default
        self._direct_attribute_name = direct_attribute_name
        self._should_distribute_fn = should_distribute_fn

    def __call__(self, getter):
        if self._get is not None:
            raise Exception('getter has already been set')
        return self.getter(getter)

    def get_op(self, inst, for_create=False, value=_NO_DEFAULT):
        op = self._op
        if op is None:
            return
        try:
            if value is Field._NO_DEFAULT:
                if not self._direct_attribute_name:
                    value = self.__get__(inst, for_create=False)
                else:
                    value = getattr(inst, self._direct_attribute_name)
            if for_create and value == self._default:
                return
            return op(value)
        except:
            msg = 'Error while attempting to create op {} for {}:'.format(op, inst)
            distributor.system.logger.callstack(msg, level=LEVEL_EXCEPTION)
            distributor.system.logger.exception(msg)
            return

    def __get__(self, inst, owner=None, *, for_create=False):
        if inst is None:
            return self
        return self._get(inst)

    def __set__(self, inst, value):
        if self._set is None:
            raise AttributeError("can't set read-only field")
        ret = self._set(inst, value)
        if self._should_distribute(inst):
            op = self.get_op(inst)
            if op is not None:
                distributor.system.Distributor.instance().add_op(inst, op)
        return ret

    def getter(self, getter):
        return type(self)(getter, self._set, self._op, self._priority, self._default, self._direct_attribute_name, self._should_distribute_fn)

    def setter(self, setter):
        return type(self)(self._get, setter, self._op, self._priority, self._default, self._direct_attribute_name, self._should_distribute_fn)

    def get_resend(self):

        def _resend(inst):
            if self._should_distribute(inst):
                op = self.get_op(inst)
                if op is not None:
                    distributor.system.Distributor.instance().add_op(inst, op)

        return _resend

    @staticmethod
    def _get_distributed_fields(obj):
        object_type = type(obj)
        component_types = getattr(obj, 'component_types', None)
        key = (object_type, component_types)
        distributed_fields = Field._distributed_fields.get(key)
        if distributed_fields is None:
            distributed_fields = []
            for name in set(dir(object_type)) - Field._OBJECT_DIR:
                field = getattr(object_type, name, None)
                while isinstance(field, Field):
                    distributed_fields.append((None, field))
            if component_types:
                for component in obj.components:
                    for (_, field) in Field._get_distributed_fields(component):
                        distributed_fields.append((component.INAME, field))
            distributed_fields.sort(reverse=True, key=lambda t: t[1]._priority)
            Field._distributed_fields[key] = distributed_fields
        return distributed_fields

    @staticmethod
    def fill_in_operation_list(obj, operations, for_create=False):
        for op in Field.get_operations_gen(obj, for_create=for_create):
            with ProtocolBufferRollback(operations) as op_msg:
                op.write(op_msg)

    @staticmethod
    def get_operations_gen(obj, for_create=False):
        distributed_fields = Field._get_distributed_fields(obj)
        for (component_name, field) in distributed_fields:
            field_owner = obj
            if component_name is not None:
                field_owner = getattr(obj, component_name)
            op = field.get_op(field_owner, for_create=for_create)
            while op is not None:
                yield op

    def _should_distribute(self, inst):
        if inst.valid_for_distribution and (self._should_distribute_fn is None or self._should_distribute_fn(inst)):
            return True
        return False

class ComponentField(Field):
    __qualname__ = 'ComponentField'

    def __set__(self, inst, value):
        if self._set is None:
            raise AttributeError("can't set read-only field")
        ret = self._set(inst, value)
        if self._should_distribute(inst.owner):
            op = self.get_op(inst)
            if op is not None:
                distributor.system.Distributor.instance().add_op(inst.owner, op)
        return ret

    def get_resend(self):

        def _resend(component):
            if self._should_distribute(component.owner):
                op = self.get_op(component)
                if op is not None:
                    distributor.system.Distributor.instance().add_op(component.owner, op)

        return _resend

class ChildField:
    __qualname__ = 'ChildField'

    def __init__(self, getter=None, setter=None, parent=None):
        self._get = getter
        self._set = setter
        self._parent = parent

    def __call__(self, getter):
        if self._get is not None:
            raise Exception('getter has already been set')
        return type(self)(getter, self._set, self._parent)

    def __get__(self, inst, owner=None):
        if inst is None:
            return self
        return self._get(inst)

    def __set__(self, inst, value):
        if self._set is None:
            raise AttributeError("can't set read-only child field")
        ret = self._set(inst, value)
        self._parent.__set__(inst, self._parent.__get__(inst))
        return ret

    def getter(self, method):
        return type(self)(method, self._set, self._parent)

    def setter(self, method):
        return type(self)(self._get, method, self._parent)

