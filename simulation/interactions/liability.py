
class Liability:
    __qualname__ = 'Liability'

    def release(self):
        pass

    def merge(self, interaction, key, new_liability):
        return new_liability

    @property
    def should_transfer(self):
        return True

    def transfer(self, interaction):
        pass

    def on_reset(self):
        self.release()

    def on_add(self, interaction):
        pass

    def on_run(self):
        pass

    @classmethod
    def on_affordance_loaded_callback(cls, affordance, liability_tuning):
        pass

class ReplaceableLiability(Liability):
    __qualname__ = 'ReplaceableLiability'

    def merge(self, interaction, key, new_liability):
        interaction.remove_liability(key)
        return new_liability

