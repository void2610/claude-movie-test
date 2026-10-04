import math
from bisect import bisect_right
from typing import Any, Sequence

from . import easing


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if x < lo else hi if x > hi else x


def lerp(a: Any, b: Any, t: float) -> Any:
    if isinstance(a, tuple):
        return tuple(lerp(x, y, t) for x, y in zip(a, b))
    return a + (b - a) * t


def remap(x: float, a0: float, a1: float, b0: float = 0.0, b1: float = 1.0, clip: bool = True) -> float:
    p = (x - a0) / (a1 - a0) if a1 != a0 else float(x >= a1)
    if clip:
        p = clamp(p)
    return b0 + (b1 - b0) * p


def smoothstep(a: float, b: float, x: float) -> float:
    p = clamp((x - a) / (b - a)) if b != a else float(x >= b)
    return p * p * (3 - 2 * p)


def progress(t: float, t0: float, t1: float, ease=None) -> float:
    return easing.get(ease)(remap(t, t0, t1))


def tween(t: float, t0: float, t1: float, a: Any, b: Any, ease=None) -> Any:
    return lerp(a, b, progress(t, t0, t1, ease))


def window(t: float, t0: float, t1: float, fade_in: float, fade_out: float, ease=None) -> float:
    """t0 から fade_in 秒で 0→1、t1 の fade_out 秒前から 1→0 になる包絡。"""
    e = easing.get(ease)
    a = e(remap(t, t0, t0 + fade_in)) if fade_in > 0 else float(t >= t0)
    b = e(remap(t, t1 - fade_out, t1)) if fade_out > 0 else float(t >= t1)
    return a * (1 - b)


class Keys:
    """(時刻, 値, 次のキーまでのイージング) のキーフレーム列。"""

    def __init__(self, *keys: Sequence):
        self.keys = sorted(((k[0], k[1], k[2] if len(k) > 2 else None) for k in keys), key=lambda k: k[0])
        self.times = [k[0] for k in self.keys]

    def __call__(self, t: float) -> Any:
        i = bisect_right(self.times, t)
        if i == 0:
            return self.keys[0][1]
        if i >= len(self.keys):
            return self.keys[-1][1]
        (t0, v0, e), (t1, v1, _) = self.keys[i - 1], self.keys[i]
        return tween(t, t0, t1, v0, v1, e)


def spring(t: float, t0: float, freq: float = 3.0, damping: float = 0.35) -> float:
    """t0 で 0→1 に動き出す減衰振動。freq は Hz、damping は減衰比。"""
    x = t - t0
    if x <= 0:
        return 0.0
    w = 2 * math.pi * freq
    if damping >= 1:
        return 1 - (1 + w * x) * math.exp(-w * x)
    wd = w * math.sqrt(1 - damping * damping)
    return 1 - math.exp(-damping * w * x) * (math.cos(wd * x) + damping * w / wd * math.sin(wd * x))


def stagger(i: int, n: int, t0: float, t1: float, each: float) -> tuple[float, float]:
    """n 個の要素を t0〜t1 に順番に割り当てたときの i 番目の (開始, 終了)。"""
    span = max(t1 - t0 - each, 0.0)
    s = t0 + (span * i / (n - 1) if n > 1 else 0.0)
    return s, s + each


def impact(t: float, cues: Sequence[float], decay: float = 12.0) -> float:
    """直近のキューからの経過時間で指数減衰する衝撃量 (0〜1)。"""
    v = 0.0
    for c in cues:
        if c <= t:
            v = max(v, math.exp(-decay * (t - c)))
    return v
