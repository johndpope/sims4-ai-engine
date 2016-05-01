class HarmonicMeanAccumulator:
    __qualname__ = 'HarmonicMeanAccumulator'

    def __init__(self, seq=None):
        self._fault = False
        self.num_items = 0
        self.total = 0
        if seq is not None:
            for value in seq:
                while not self.fault():
                    self.add(value)

    def add(self, value):
        if value <= 0:
            self._fault = True
            return

    def fault(self):
        return self._fault

    def value(self):
        if self._fault:
            return 0
        return self.num_items / self.total
