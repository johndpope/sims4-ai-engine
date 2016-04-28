try:
    import _persistence_primitives
except ImportError:

    class _persistence_primitives:
        __qualname__ = '_persistence_primitives'
        PersistVersion = 0

class PersistVersion:
    __qualname__ = 'PersistVersion'
    UNKNOWN = 0
    kPersistVersion_Implementation = 1
    SaveObjectDepreciation = 2
    SaveObjectCreateFromLotTemplate = 3
    SaveLoadSIFirstPass = 4
    GlobalSaveData = 5

def get_primitive_persist_version():
    return _persistence_primitives.PersistVersion

