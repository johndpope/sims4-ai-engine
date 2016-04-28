from _trace import set_color
from contextlib import contextmanager
colors_enabled = True

class ConsoleColor:
    __qualname__ = 'ConsoleColor'
    LIGHT = 8
    BG_LIGHT = 128
    BLACK = 0
    DARK_GRAY = BLACK | LIGHT
    DARK_BLUE = 1
    BLUE = DARK_BLUE | LIGHT
    DARK_GREEN = 2
    GREEN = DARK_GREEN | LIGHT
    DARK_CYAN = 3
    CYAN = DARK_CYAN | LIGHT
    DARK_RED = 4
    RED = DARK_RED | LIGHT
    DARK_MAGENTA = 5
    MAGENTA = DARK_MAGENTA | LIGHT
    DARK_YELLOW = 6
    YELLOW = DARK_YELLOW | LIGHT
    LIGHT_GRAY = 7
    WHITE = LIGHT_GRAY | LIGHT
    BG_BLACK = 0
    BG_DARK_GRAY = BG_BLACK | BG_LIGHT
    BG_DARK_BLUE = 16
    BG_BLUE = BG_DARK_BLUE | BG_LIGHT
    BG_DARK_GREEN = 32
    BG_GREEN = BG_DARK_GREEN | BG_LIGHT
    BG_DARK_CYAN = 48
    BG_CYAN = BG_DARK_CYAN | BG_LIGHT
    BG_DARK_RED = 64
    BG_RED = BG_DARK_RED | BG_LIGHT
    BG_DARK_MAGENTA = 80
    BG_MAGENTA = BG_DARK_MAGENTA | BG_LIGHT
    BG_DARK_YELLOW = 96
    BG_YELLOW = BG_DARK_YELLOW | BG_LIGHT
    BG_LIGHT_GRAY = 112
    BG_WHITE = BG_LIGHT_GRAY | BG_LIGHT
    default_color = CYAN

    @classmethod
    @contextmanager
    def colored_text(cls, color):
        revert_color = cls.default_color
        if revert_color == color or not colors_enabled:
            yield None
            return
        cls.default_color = color
        set_color(color)
        try:
            yield None
        finally:
            set_color(revert_color)
            cls.default_color = revert_color

    @classmethod
    def change_color(cls, color):
        if color == cls.default_color or not colors_enabled:
            return
        cls.default_color = color
        set_color(color)

