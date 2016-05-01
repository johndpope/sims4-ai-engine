try:
    import _persistence_module
except ImportError as err:

    class _persistence_module:
        __qualname__ = '_persistence_module'

        @staticmethod
        def run_persistence_operation(persistence_op_type, protocol_buffer,
                                      save_slot_id, callback):
            callback(save_slot_id, False)
            return False


class PersistenceOpType:
    __qualname__ = 'PersistenceOpType'
    kPersistenceOpInvalid = 0
    kPersistenceOpLoad = 1
    kPersistenceOpSave = 2
    kPersistenceOpLoadZoneObjects = 3
    kPersistenceOpSaveZoneObjects = 4
    kPersistenceOpSaveGameplayGlobalData = 5
    kPersistenceOpLoadGameplayGlobalData = 6
    kPersistenceOpSaveHousehold = 1000


run_persistence_operation = _persistence_module.run_persistence_operation
