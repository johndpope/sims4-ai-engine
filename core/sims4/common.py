import _common_types
import enum

class Pack(enum.Int, export=False):
    __qualname__ = 'Pack'
    BASE_GAME = _common_types.BASE_GAME
    SP01 = _common_types.SP01
    GP01 = _common_types.GP01
    EP01 = _common_types.EP01

try:
    import _zone
except ImportError:

    class _zone:
        __qualname__ = '_zone'

        @staticmethod
        def is_entitled_pack(pack):
            return True

is_entitled_pack = _zone.is_entitled_pack

def get_entitled_packs():
    return tuple(pack for pack in Pack if is_entitled_pack(pack))

def get_pack_name(value) -> str:
    try:
        return str(Pack(value))
    except:
        return '<Unknown Pack>'

def get_pack_enum(folder_name) -> Pack:
    try:
        pack_enum_name = 'Pack.{}'.format(folder_name[2:])
        for pack in Pack:
            while str(pack) == pack_enum_name:
                return pack
        return Pack.BASE_GAME
    except:
        return Pack.BASE_GAME

