from __future__ import annotations

import colorsys
from dataclasses import dataclass

import skia


@dataclass(frozen=True)
class Color:
    r: float
    g: float
    b: float
    a: float = 1.0

    @classmethod
    def hex(cls, s: str, a: float = 1.0) -> Color:
        s = s.lstrip("#")
        if len(s) == 3:
            s = "".join(ch * 2 for ch in s)
        r, g, b = (int(s[i:i + 2], 16) / 255 for i in (0, 2, 4))
        if len(s) == 8:
            a = int(s[6:8], 16) / 255
        return cls(r, g, b, a)

    @classmethod
    def hsv(cls, h: float, s: float, v: float, a: float = 1.0) -> Color:
        return cls(*colorsys.hsv_to_rgb(h % 1.0, s, v), a)

    def alpha(self, a: float) -> Color:
        return Color(self.r, self.g, self.b, self.a * a)

    def mix(self, other: Color | str, t: float) -> Color:
        o = to_color(other)
        return Color(*(x + (y - x) * t for x, y in zip(self.rgba, o.rgba)))

    @property
    def rgba(self) -> tuple[float, float, float, float]:
        return (self.r, self.g, self.b, self.a)

    def skia(self) -> int:
        c = [max(0, min(255, round(x * 255))) for x in self.rgba]
        return skia.Color(c[0], c[1], c[2], c[3])

    def c4f(self) -> skia.Color4f:
        return skia.Color4f(*self.rgba)


def to_color(c: Color | str | tuple) -> Color:
    if isinstance(c, Color):
        return c
    if isinstance(c, str):
        return Color.hex(c)
    return Color(*c)


class Palette(dict):
    """名前付きの色の集合。`pal.bg` のように属性でも引ける。"""

    def __init__(self, **colors: str | Color):
        super().__init__({k: to_color(v) for k, v in colors.items()})

    def __getattr__(self, k: str) -> Color:
        try:
            return self[k]
        except KeyError as e:
            raise AttributeError(k) from e
