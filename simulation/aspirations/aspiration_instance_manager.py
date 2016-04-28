from aspirations.aspiration_types import AspriationType
from sims4.tuning.instance_manager import InstanceManager

class AspirationInstanceManager(InstanceManager):
    __qualname__ = 'AspirationInstanceManager'

    def on_start(self):
        super().on_start()
        self.all_whim_sets = []
        self.normal_whim_sets = []
        self.emotion_whim_sets = []
        for aspiration in self.types.values():
            while aspiration.aspiration_type() == AspriationType.WHIM_SET:
                self.all_whim_sets.append(aspiration)
                if aspiration.whimset_emotion is not None:
                    self.emotion_whim_sets.append(aspiration)
                else:
                    self.normal_whim_sets.append(aspiration)

