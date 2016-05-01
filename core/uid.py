import sims4.math


class UniqueIdGenerator:
    __qualname__ = 'UniqueIdGenerator'
    __slots__ = ('next_uid', 'min_uid', 'max_uid')

    def __init__(self, min_uid=0, max_uid=sims4.math.MAX_UINT32):
        try:
            min_uid = int(min_uid)
            max_uid = int(max_uid)
        except:
            raise TypeError('min_uid and max_uid must be ints')
        if min_uid >= max_uid:
            raise ValueError('({}, {}) is not a valid unique id range.'.format(
                min_uid, max_uid))
        self.min_uid = min_uid
        self.max_uid = max_uid
        self.next_uid = min_uid

    def __call__(self):
        uid = self.next_uid
        if uid < self.max_uid:
            self.next_uid = uid + 1
        else:
            self.next_uid = self.min_uid
        return uid

    def __reload_update__(self, oldobj, newobj, _update):
        uid = oldobj.next_uid
        if newobj.min_uid <= uid <= newobj.max_uid:
            newobj.next_uid = uid
        else:
            newobj.next_uid = newobj.min_uid
        return newobj


class UniqueId(UniqueIdGenerator):
    __qualname__ = 'UniqueId'
    __slots__ = ('uid_attr', )

    def __init__(self, uid_attr, *args, **kwargs):
        if not isinstance(uid_attr, str):
            raise TypeError('uid_attr must be a string, not {}'.format(type(
                uid_attr)))
        super().__init__(*args, **kwargs)
        self.uid_attr = uid_attr

    def __get__(self, instance, owner):
        if instance is None:
            return self
        uid = self()
        setattr(instance, self.uid_attr, uid)
        return uid


def unique_id(uid_attr, *args, **kwargs):
    def dec(cls):
        setattr(cls, uid_attr, UniqueId(uid_attr, *args, **kwargs))
        return cls

    return dec
