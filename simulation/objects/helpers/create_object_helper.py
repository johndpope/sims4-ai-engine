from objects.system import create_object
from element_utils import build_critical_section_with_finally

class CreateObjectHelper:
    __qualname__ = 'CreateObjectHelper'
    __slots__ = ('_object', '_claimed', '_reserver', 'sim', 'def_id', 'tag', 'create_kwargs')

    def __init__(self, sim, definition, reserver, tag='(no tag)', **create_kwargs):
        self._object = None
        self._claimed = False
        self._reserver = reserver
        self.sim = sim
        self.def_id = definition
        self.tag = tag
        self.create_kwargs = create_kwargs

    def __call__(self):
        return self.object

    def create(self, *args):

        def _create(_):
            self._object = create_object(self.def_id, **self.create_kwargs)
            if self._object is None:
                return False
            if self.sim is not None and self._reserver is not None:
                self.object.reserve(self.sim, self._reserver)
            return True

        def _cleanup(_):
            if self.sim is not None and self._reserver is not None:
                self._object.release(self.sim, self._reserver)
            if not (self._object is not None and self._claimed):
                self._object.destroy(source=self.sim, cause="Created object wasn't claimed.")
                self._object = None

        return build_critical_section_with_finally(_create, args, _cleanup)

    def claim(self, *_, **__):
        if self._object is None:
            raise RuntimeError('CreateObjectHelper: Attempt to claim object before it was created: {}'.format(self.tag))
        if self._claimed:
            raise RuntimeError('CreateObjectHelper: Attempt to claim object multiple times: {}'.format(self.tag))
        self._claimed = True

    @property
    def object(self):
        if self._object is None:
            raise RuntimeError('CreateObjectHelper: Attempt to get object before it was created: {}'.format(self.tag))
        return self._object

    @property
    def is_object_none(self):
        return self._object is None

    @property
    def claimed(self):
        return self._claimed

