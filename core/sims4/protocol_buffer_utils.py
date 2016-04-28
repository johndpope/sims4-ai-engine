from _net_proto2___python import TYPE_MESSAGE, LABEL_REPEATED
from protocolbuffers import SimsCustomOptions_pb2 as custom_options

def has_field(proto, field_name):
    result = False
    try:
        result = proto.HasField(field_name)
    except ValueError:
        pass
    return result

def persist_fields_for_new_game(message):
    all_clear = True
    if message is None:
        return all_clear
    for (name, value) in message.DESCRIPTOR.fields_by_name.items():
        options = value.GetOptions()
        if options.Extensions[custom_options.persist_for_new_game]:
            all_clear = False
        elif value.type == TYPE_MESSAGE:
            msg_recur = getattr(message, name)
            recur = (m for m in msg_recur) if value.label == LABEL_REPEATED else (msg_recur,)
            for _msg in recur:
                result = persist_fields_for_new_game(_msg)
                if result:
                    _msg.Clear()
                else:
                    all_clear = False
        else:
            message.ClearField(name)
    return all_clear

