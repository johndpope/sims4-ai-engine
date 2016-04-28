import itertools
from audio.primitive import TunablePlayAudio, play_tunable_audio
import distributor
import enum
import protocolbuffers
import sims4.localization
import sims4.tuning
from sims4.tuning.tunable import OptionalTunable, Tunable, TunableEnumEntry, AutoFactoryInit, HasTunableSingletonFactory
from snippets import define_snippet, SCREEN_SLAM

class ScreenSlamSizeEnum(enum.Int):
    __qualname__ = 'ScreenSlamSizeEnum'
    SMALL = 0
    MEDIUM = 1
    LARGE = 2
    EXTRA_LARGE = 3

class ScreenSlam(HasTunableSingletonFactory, AutoFactoryInit):
    __qualname__ = 'ScreenSlam'
    FACTORY_TUNABLES = {'screen_slam_size': TunableEnumEntry(description='\n            Screen slam type.\n            ', tunable_type=ScreenSlamSizeEnum, default=ScreenSlamSizeEnum.MEDIUM), 'title': OptionalTunable(description='\n            Title of the screen slam.\n            ', tunable=sims4.localization.TunableLocalizedStringFactory()), 'text': sims4.localization.TunableLocalizedStringFactory(description='"\n            Text of the screen slam.\n            ', export_modes=sims4.tuning.tunable_base.ExportModes.All), 'icon': sims4.tuning.tunable.TunableResourceKey(description=',\n            Icon to be displayed for the screen Slam.\n            ', default=None, resource_types=sims4.resources.CompoundTypes.IMAGE), 'audio_sting': OptionalTunable(description='\n            A sting to play at the same time as the screen slam.\n            ***Some screen slams may appear to play a sting, but the audio is\n            actually tuned on something else.  Example: On CareerLevel tuning\n            there already is a tunable, Promotion Audio Sting, to trigger a\n            sting, so one is not necessary on the screen slam.  Make sure to\n            avoid having to stings play simultaneously.***\n            ', tunable=TunablePlayAudio()), 'active_sim_only': Tunable(description='\n            If true, the screen slam will be only be shown if the active Sim\n            triggers it.\n            ', tunable_type=bool, default=True)}

    def send_screen_slam_message(self, sim_info, *localization_tokens):
        msg = protocolbuffers.UI_pb2.UiScreenSlam()
        msg.type = self.screen_slam_size
        msg.size = self.screen_slam_size
        msg.name = self.text(*(token for token in itertools.chain(localization_tokens)))
        if sim_info is not None:
            msg.sim_id = sim_info.sim_id
        if self.icon is not None:
            msg.icon.group = self.icon.group
            msg.icon.instance = self.icon.instance
            msg.icon.type = self.icon.type
        if self.title is not None:
            msg.title = self.title(*(token for token in itertools.chain(localization_tokens)))
        if self.active_sim_only and sim_info is not None and sim_info.is_selected or not self.active_sim_only:
            distributor.shared_messages.add_message_if_player_controlled_sim(sim_info, protocolbuffers.Consts_pb2.MSG_UI_SCREEN_SLAM, msg, False)
            if self.audio_sting is not None:
                play_tunable_audio(self.audio_sting)

(TunableScreenSlamReference, TunableScreenSlamSnippet) = define_snippet(SCREEN_SLAM, ScreenSlam.TunableFactory())
