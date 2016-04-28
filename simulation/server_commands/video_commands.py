from objects.components import types
import objects
import services
import sims4.commands

@sims4.commands.Command('video.object_info')
def get_video_object_info(obj_id, _connection=None):
    manager = services.object_manager()
    obj = None
    if obj_id in manager:
        obj = manager.get(obj_id)
    else:
        sims4.commands.output('Object ID {} not present in the object manager.'.format(obj_id), _connection)
    if obj is not None:
        sims4.commands.output('Object {} ({})'.format(obj_id, obj.__class__.__name__), _connection)
        v = obj.get_component(types.VIDEO_COMPONENT)
        if v is not None:
            sims4.commands.output('  ' + repr(v), _connection)
        else:
            sims4.commands.output('  Object does not have video playback capabilities.', _connection)

@sims4.commands.Command('video.set_clips')
def set_video_clips(obj_id, *clip_names, _connection=None):
    manager = services.object_manager()
    obj = None
    if obj_id in manager:
        obj = manager.get(obj_id)
    else:
        sims4.commands.output('Object ID {} not present in the object manager.'.format(obj_id), _connection)
    if obj is not None:
        sims4.commands.output('Object {} ({})'.format(obj_id, obj.__class__.__name__), _connection)
        v = obj.get_component(types.VIDEO_COMPONENT)
        if v is not None:
            v.set_video_clips(clip_names, False)
            sims4.commands.output('  Added {} clip(s).'.format(len(clip_names)), _connection)
        else:
            sims4.commands.output('  Object does not have video playback capabilities.', _connection)

@sims4.commands.Command('video.add_clips')
def add_video_clips(obj_id, *clip_names, _connection=None):
    manager = services.object_manager()
    obj = None
    if obj_id in manager:
        obj = manager.get(obj_id)
    else:
        sims4.commands.output('Object ID {} not present in the object manager.'.format(obj_id), _connection)
    if obj is not None:
        sims4.commands.output('Object {} ({})'.format(obj_id, obj.__class__.__name__), _connection)
        v = obj.get_component(types.VIDEO_COMPONENT)
        if v is not None:
            v.add_video_clips(clip_names, False)
            sims4.commands.output('  Added {} clip(s).'.format(len(clip_names)), _connection)
        else:
            sims4.commands.output('  Object does not have video playback capabilities.', _connection)

