try:
    import _cas
except:

    class _cas:
        __qualname__ = '_cas'
        SimInfo = None

        @staticmethod
        def age_up_sim(*_, **__):
            pass

        @staticmethod
        def get_buffs_from_part_ids(*_, **__):
            return []

        @staticmethod
        def generate_offspring(*_, **__):
            pass

        @staticmethod
        def generate_household(*_, **__):
            pass

BaseSimInfo = _cas.SimInfo
age_up_sim = _cas.age_up_sim
get_buff_from_part_ids = _cas.get_buffs_from_part_ids
generate_offspring = _cas.generate_offspring
generate_household = _cas.generate_household
