
class ProfileMetrics:
    __qualname__ = 'ProfileMetrics'

    def __init__(self):
        self.count = 0
        self.total_time = 0

    @property
    def average_time(self):
        if self.total_time == 0 or self.count == 0:
            return 0
        return self.total_time/self.count

    def update(self, delta_time):
        pass

class TestProfileRecord:
    __qualname__ = 'TestProfileRecord'

    def __init__(self):
        self.metrics = ProfileMetrics()
        self.resolvers = dict()

