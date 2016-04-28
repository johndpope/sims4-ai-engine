import fishing.fishing_data
import objects.components.types
import sims4.tuning
import vfx

class FishingLocationComponent(objects.components.Component, sims4.tuning.tunable.HasTunableFactory, component_name=objects.components.types.FISHING_LOCATION_COMPONENT):
    __qualname__ = 'FishingLocationComponent'
    VFX_SLOT_HASH = sims4.hash_util.hash32('_FX_')
    FACTORY_TUNABLES = {'fishing_data': fishing.fishing_data.TunableFishingDataSnippet(), 'is_fishing_hole': sims4.tuning.tunable.Tunable(description='\n            If this is a Fishing Hole, check the box.\n            If this is a Fishing Spot, do not check the box.\n            ', tunable_type=bool, default=False)}

    def __init__(self, owner, fishing_data, is_fishing_hole):
        super().__init__(owner)
        self._fishing_data = fishing_data
        self._is_fishing_hole = is_fishing_hole
        self._fish_vfx = []

    def on_add(self, *_, **__):
        for fish in self._fishing_data.get_possible_fish_gen():
            if self._is_fishing_hole:
                location_vfx = fish.fish.cls.fishing_hole_vfx
            else:
                location_vfx = fish.fish.cls.fishing_spot_vfx
            while location_vfx is not None:
                fish_vfx = vfx.PlayEffect(self.owner, location_vfx, self.VFX_SLOT_HASH)
                fish_vfx.start()
                self._fish_vfx.append(fish_vfx)

    def on_remove(self, *_, **__):
        for fish_vfx in self._fish_vfx:
            fish_vfx.stop()
            fish_vfx = None
        self._fish_vfx = None

    @property
    def fishing_data(self):
        return self._fishing_data

