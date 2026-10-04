import math
from typing import Callable

Ease = Callable[[float], float]


def linear(x): return x
def in_quad(x): return x * x
def out_quad(x): return 1 - (1 - x) ** 2
def inout_quad(x): return 2 * x * x if x < 0.5 else 1 - (-2 * x + 2) ** 2 / 2
def in_cubic(x): return x ** 3
def out_cubic(x): return 1 - (1 - x) ** 3
def inout_cubic(x): return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2
def in_quart(x): return x ** 4
def out_quart(x): return 1 - (1 - x) ** 4
def inout_quart(x): return 8 * x ** 4 if x < 0.5 else 1 - (-2 * x + 2) ** 4 / 2
def in_quint(x): return x ** 5
def out_quint(x): return 1 - (1 - x) ** 5
def inout_quint(x): return 16 * x ** 5 if x < 0.5 else 1 - (-2 * x + 2) ** 5 / 2
def in_sine(x): return 1 - math.cos(x * math.pi / 2)
def out_sine(x): return math.sin(x * math.pi / 2)
def inout_sine(x): return -(math.cos(math.pi * x) - 1) / 2
def in_expo(x): return 0.0 if x <= 0 else 2 ** (10 * x - 10)
def out_expo(x): return 1.0 if x >= 1 else 1 - 2 ** (-10 * x)


def inout_expo(x):
    if x <= 0 or x >= 1:
        return float(x >= 1)
    return 2 ** (20 * x - 10) / 2 if x < 0.5 else (2 - 2 ** (-20 * x + 10)) / 2


def in_circ(x): return 1 - math.sqrt(1 - x * x)
def out_circ(x): return math.sqrt(1 - (x - 1) ** 2)


def in_back(x, s=1.70158): return (s + 1) * x ** 3 - s * x * x
def out_back(x, s=1.70158): return 1 + (s + 1) * (x - 1) ** 3 + s * (x - 1) ** 2


def inout_back(x, s=1.70158):
    s2 = s * 1.525
    if x < 0.5:
        return ((2 * x) ** 2 * ((s2 + 1) * 2 * x - s2)) / 2
    return ((2 * x - 2) ** 2 * ((s2 + 1) * (x * 2 - 2) + s2) + 2) / 2


def out_elastic(x):
    if x <= 0 or x >= 1:
        return float(x >= 1)
    return 2 ** (-10 * x) * math.sin((x * 10 - 0.75) * (2 * math.pi / 3)) + 1


def out_bounce(x):
    n, d = 7.5625, 2.75
    if x < 1 / d:
        return n * x * x
    if x < 2 / d:
        x -= 1.5 / d
        return n * x * x + 0.75
    if x < 2.5 / d:
        x -= 2.25 / d
        return n * x * x + 0.9375
    x -= 2.625 / d
    return n * x * x + 0.984375


def cubic_bezier(x1: float, y1: float, x2: float, y2: float) -> Ease:
    """CSS の cubic-bezier と同じ定義のイージングを返す。"""
    def bez(t, a, b):
        return 3 * a * (1 - t) ** 2 * t + 3 * b * (1 - t) * t * t + t ** 3

    def ease(x):
        if x <= 0 or x >= 1:
            return float(x >= 1)
        lo, hi = 0.0, 1.0
        for _ in range(40):
            mid = (lo + hi) / 2
            if bez(mid, x1, x2) < x:
                lo = mid
            else:
                hi = mid
        return bez((lo + hi) / 2, y1, y2)

    return ease


# モーションデザインで定番のカーブ
snap = cubic_bezier(0.7, 0.0, 0.2, 1.0)
whip = cubic_bezier(0.9, 0.0, 0.1, 1.0)
settle = cubic_bezier(0.2, 0.8, 0.2, 1.0)


def get(name: str | Ease | None) -> Ease:
    if name is None:
        return linear
    if callable(name):
        return name
    return globals()[name]
