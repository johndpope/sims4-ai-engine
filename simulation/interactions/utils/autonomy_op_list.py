
class AutonomyAdList:
    __qualname__ = 'AutonomyAdList'

    def __init__(self, stat_type):
        self._stat_type = stat_type
        self._op_list = []

    def __iter__(self):
        return iter(self._op_list)

    @property
    def stat(self):
        return self._stat_type

    def add_op(self, op):
        self._op_list.append(op)

    def remove_op(self, op):
        if op in self._op_list:
            self._op_list.remove(op)
            return True
        return False

    def get_fulfillment_rate(self, interaction):
        return sum(op.get_fulfillment_rate(interaction) for op in self)

    def get_value(self):
        return sum(op.get_value() for op in self)

