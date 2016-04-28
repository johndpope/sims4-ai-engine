import objects.game_object

class FireSprinklerHead(objects.game_object.GameObject):
    __qualname__ = 'FireSprinklerHead'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.vfx = None

    def on_remove(self):
        if self.vfx is not None:
            self.vfx.stop()
        super().on_remove()

