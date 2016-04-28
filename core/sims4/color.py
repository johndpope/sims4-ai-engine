import enum
import math
import colorsys
import sims4.math
__all__ = ['Color', 'from_rgba', 'to_rgba', 'interpolate', 'pseudo_random_color', 'red_green_lerp']

class ColorARGB32(int):
    __qualname__ = 'ColorARGB32'
    __slots__ = ()

    def __repr__(self):
        return '<Color(0x{0:08X})>'.format(self)

class Color(ColorARGB32, metaclass=enum.Metaclass, enum_math=False):
    __qualname__ = 'Color'
    WHITE = ColorARGB32(4294967295)
    BLACK = ColorARGB32(4278190080)
    GREY = ColorARGB32(4287137928)
    RED = ColorARGB32(4294901760)
    GREEN = ColorARGB32(4278255360)
    BLUE = ColorARGB32(4278190335)
    CYAN = ColorARGB32(4278255615)
    MAGENTA = ColorARGB32(4294902015)
    YELLOW = ColorARGB32(4294967040)
    ORANGE = ColorARGB32(4294944000)
    PINK = ColorARGB32(4294951115)
    PEACH = ColorARGB32(4294957753)

MAX_INT_COLOR_VALUE = 255

def _convert_from_rbga_to_color(value, scale=1, as_int=False):
    v = value
    if not as_int:
        v = int(MAX_INT_COLOR_VALUE*value)
    v = sims4.math.clamp(0, v, MAX_INT_COLOR_VALUE)
    return v*scale

def _convert_from_color_to_rgba(c, scale=1, as_int=False):
    v = c & MAX_INT_COLOR_VALUE*scale
    if as_int:
        v /= scale
        return int(v)
    v /= MAX_INT_COLOR_VALUE*scale
    return sims4.math.clamp(0, v, 1.0)

def from_rgba(r, g, b, a=1.0):
    value = _convert_from_rbga_to_color(a, 16777216) + _convert_from_rbga_to_color(r, 65536) + _convert_from_rbga_to_color(g, 256) + _convert_from_rbga_to_color(b)
    return ColorARGB32(value)

def from_rgba_as_int(r, g, b, a=1.0):
    value = _convert_from_rbga_to_color(a, 16777216) + _convert_from_rbga_to_color(r, 65536, as_int=True) + _convert_from_rbga_to_color(g, 256, as_int=True) + _convert_from_rbga_to_color(b, as_int=True)
    return ColorARGB32(value)

def to_rgba(color):
    return (_convert_from_color_to_rgba(color, 65536), _convert_from_color_to_rgba(color, 256), _convert_from_color_to_rgba(color), _convert_from_color_to_rgba(color, 16777216))

def to_rgba_as_int(color):
    return (_convert_from_color_to_rgba(color, 65536, as_int=True), _convert_from_color_to_rgba(color, 256, as_int=True), _convert_from_color_to_rgba(color, as_int=True), _convert_from_color_to_rgba(color, 16777216))

def interpolate(x, y, fraction):
    x_rgba = to_rgba(x)
    y_rgba = to_rgba(y)
    z_rgba = [sims4.math.interpolate(v, w, fraction) for (v, w) in zip(x_rgba, y_rgba)]
    z = from_rgba(*z_rgba)
    return z

def pseudo_random_color(n, a=1.0):
    x = n % 28657
    h = x*math.pi % 1.0
    s = x*math.e % 0.5 + 0.5
    v = x*math.sqrt(2) % 0.25 + 0.75
    (r, g, b) = colorsys.hsv_to_rgb(h, s, v)
    return from_rgba(r, g, b, a=a)

def red_green_lerp(n, a=1.0):
    return from_rgba(a=a, *colorsys.hsv_to_rgb(n*0.4, 0.9, 0.9))

