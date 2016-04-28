from objects.components import types, componentmethod
from objects.components.types import NativeComponent
from protocolbuffers import DistributorOps_pb2 as protocols, ResourceKey_pb2
from sims4.tuning.tunable import TunableFactory
import sims4.hash_util
RESOURCE_TYPE_VP6 = 929579223
RESOURCE_GROUP_PLAYLIST = 12535179

class VideoPlaylist:
    __qualname__ = 'VideoPlaylist'

    def __init__(self, version_id, clip_names, loop_last):
        self.version_id = version_id
        self.clip_keys = VideoPlaylist._encode_clip_names(clip_names)
        self.loop_last = loop_last

    def __repr__(self):
        return 'version({}): {} clips, loop={}'.format(self.version_id, len(self.clip_keys), self.loop_last)

    def append_clips(self, clip_names, loop_last):
        if clip_names:
            self.loop_last = loop_last

    def get_protocol_msg(self):
        msg = protocols.VideoSetPlaylist()
        msg.version_id = self.version_id
        msg.clip_keys.extend(self.clip_keys)
        msg.final_loop = self.loop_last
        return msg

    @staticmethod
    def _encode_clip_names(clip_names):
        return [VideoPlaylist._encode_clip_name(clip_name) for clip_name in clip_names]

    @staticmethod
    def _encode_clip_name(clip_name):
        key = ResourceKey_pb2.ResourceKey()
        if type(clip_name) is sims4.resources.Key:
            key.type = clip_name.type
            key.group = clip_name.group
            key.instance = clip_name.instance
            if key.type == sims4.resources.Types.PLAYLIST:
                key.group = RESOURCE_GROUP_PLAYLIST
        else:
            split_index = clip_name.find('.')
            key.type = RESOURCE_TYPE_VP6
            key.group = 0
            if split_index < 0:
                key.instance = sims4.hash_util.hash64(clip_name)
            else:
                key.instance = sims4.hash_util.hash64(clip_name[:split_index])
                ext = clip_name[split_index + 1:]
                if ext == 'playlist':
                    key.group = RESOURCE_GROUP_PLAYLIST
                elif ext != 'vp6':
                    raise ValueError('Unknown clip name extension: ' + ext)
        return key

class VideoComponent(NativeComponent, component_name=types.VIDEO_COMPONENT, key=2982943478):
    __qualname__ = 'VideoComponent'

    def __repr__(self):
        if self.owner.video_playlist is None:
            return 'No clips queued'
        return repr(self.owner.video_playlist)

    @property
    def video_playlist_looping(self):
        return self.owner.video_playlist

    @video_playlist_looping.setter
    def video_playlist_looping(self, value):
        if value is None:
            self.set_video_clips()
        else:
            self.set_video_clips([value], True)

    @property
    def video_playlist(self):
        return self.owner.video_playlist

    @video_playlist.setter
    def video_playlist(self, value):
        if value is None:
            self.set_video_clips()
        else:
            self.set_video_clips(value, True)

    @componentmethod
    def clear_video_clips(self):
        raise RuntimeError('[bhill] This function is believed to be dead code and is scheduled for pruning. If this exception has been raised, the code is not dead and this exception should be removed.')
        self.set_video_clips()

    @componentmethod
    def set_video_clips(self, clip_names=[], loop_last=False):
        if self.owner.video_playlist:
            version_id = self._next_version(self.owner.video_playlist.version_id)
        else:
            version_id = 0
        self.owner.video_playlist = VideoPlaylist(version_id, clip_names, loop_last)

    @componentmethod
    def add_video_clips(self, clip_names, loop_last=False):
        if not clip_names:
            return
        if self.owner.video_playlist is None:
            self.set_video_clips(clip_names, loop_last)
        else:
            self.owner.video_playlist.append_clips(clip_names, loop_last)
            self.owner._resend_video_playlist()

    @staticmethod
    def _next_version(version_id):
        if version_id >= 65535:
            return 0
        return version_id + 1

class TunableVideoComponent(TunableFactory):
    __qualname__ = 'TunableVideoComponent'
    FACTORY_TYPE = VideoComponent

    def __init__(self, description='Holds information about video playback facilities on an object.', **kwargs):
        super().__init__(description=description, **kwargs)

