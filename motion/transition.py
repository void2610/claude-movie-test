"""マスク・マット・シーン間のトランジション・分割モンタージュ。

    a, b = Intro(0, 4), Grid(3.5, 8)
    comp.add(a, b, Transition(a, b, at=3.5, dur=0.5, kind="wipe", angle=20))
"""
from __future__ import annotations

import math
from contextlib import contextmanager
from typing import Callable

import skia

from . import easing
from .anim import clamp, stagger
from .draw import paint
from .scene import Composition, Ctx, Scene, paint_scene

Draw = Callable[[skia.Canvas], None]


@contextmanager
def mask(c: skia.Canvas, path: skia.Path, invert: bool = False):
    """path の内側 (invert なら外側) だけに描く。縁はアンチエイリアスされる。"""
    c.save()
    c.clipPath(path, skia.ClipOp.kDifference if invert else skia.ClipOp.kIntersect, True)
    try:
        yield c
    finally:
        c.restore()


def matte(c: skia.Canvas, content: Draw, matte_fn: Draw, invert: bool = False) -> None:
    """matte_fn で描いたもののアルファで content を切り抜く (トラックマット)。"""
    c.saveLayer(None, None)
    content(c)
    p = skia.Paint()
    p.setBlendMode(skia.BlendMode.kDstOut if invert else skia.BlendMode.kDstIn)
    c.saveLayer(None, p)
    matte_fn(c)
    c.restore()
    c.restore()


def _half_plane(W: float, H: float, p: float, angle: float) -> skia.Path:
    """angle 度の方向に進む境界線より手前側の領域。p=0 で空、p=1 で全面。"""
    a = math.radians(angle)
    dx, dy = math.cos(a), math.sin(a)
    # 画面の四隅を進行方向に射影した範囲を境界線が横切る
    proj = [x * dx + y * dy for x, y in ((0, 0), (W, 0), (0, H), (W, H))]
    lo, hi = min(proj), max(proj)
    d = lo + (hi - lo) * p
    big = (W + H) * 2
    nx, ny = -dy, dx
    cx, cy = dx * d, dy * d
    pts = [(cx + nx * big, cy + ny * big), (cx - nx * big, cy - ny * big),
           (cx - nx * big - dx * big, cy - ny * big - dy * big), (cx + nx * big - dx * big, cy + ny * big - dy * big)]
    path = skia.Path()
    path.addPoly([skia.Point(*q) for q in pts], True)
    return path


def _frame(c: skia.Canvas, ctx: Ctx) -> None:
    # draw.fill (drawPaint) は変換を無視してクリップ全体を塗るため、動かすときはフレーム枠で切る
    c.clipRect(skia.Rect.MakeWH(ctx.W, ctx.H), skia.ClipOp.kIntersect, True)


def crossfade(c, a: Draw, b: Draw, p: float, ctx: Ctx) -> None:
    a(c)
    c.saveLayerAlpha(None, int(round(clamp(p) * 255)))
    b(c)
    c.restore()


def push(c, a: Draw, b: Draw, p: float, ctx: Ctx, direction: str = "left") -> None:
    dx, dy = {"left": (-1, 0), "right": (1, 0), "up": (0, -1), "down": (0, 1)}[direction]
    for fn, k in ((a, p), (b, p - 1)):
        c.save()
        c.translate(dx * ctx.W * k, dy * ctx.H * k)
        _frame(c, ctx)
        fn(c)
        c.restore()


def wipe(c, a: Draw, b: Draw, p: float, ctx: Ctx, angle: float = 0.0, edge: float = 0.0,
         edge_color: str = "#FF5A1F") -> None:
    """b が angle 度の方向から a を押しのけて現れる。edge > 0 で境界に色の帯を付ける。"""
    a(c)
    with mask(c, _half_plane(ctx.W, ctx.H, p, angle)):
        b(c)
    if edge > 0 and 0 < p < 1:
        rad = math.radians(angle)
        dx, dy = math.cos(rad), math.sin(rad)
        proj = [x * dx + y * dy for x, y in ((0, 0), (ctx.W, 0), (0, ctx.H), (ctx.W, ctx.H))]
        d = min(proj) + (max(proj) - min(proj)) * p
        big = ctx.W + ctx.H
        cx, cy = dx * d, dy * d
        c.drawLine(cx - dy * big, cy + dx * big, cx + dy * big, cy - dx * big, paint(edge_color, stroke=edge))


def iris(c, a: Draw, b: Draw, p: float, ctx: Ctx, cx: float | None = None, cy: float | None = None) -> None:
    a(c)
    cx = ctx.CX if cx is None else cx
    cy = ctx.CY if cy is None else cy
    r = math.hypot(max(cx, ctx.W - cx), max(cy, ctx.H - cy)) * p
    path = skia.Path()
    path.addCircle(cx, cy, max(r, 0.01))
    with mask(c, path):
        b(c)


def slices(c, a: Draw, b: Draw, p: float, ctx: Ctx, n: int = 8, vertical: bool = False, spread: float = 0.6,
           ease=easing.inout_expo) -> None:
    """n 本の帯が少しずつずれながら b を運んでくる。"""
    a(c)
    span = ctx.W if vertical else ctx.H
    size = span / n
    for i in range(n):
        s0, s1 = stagger(i, n, 0.0, 1.0, 1.0 - spread)
        q = ease(clamp((p - s0) / (s1 - s0)))
        if q <= 0:
            continue
        rect = skia.Rect.MakeXYWH(i * size, 0, size + 0.5, ctx.H) if vertical else \
            skia.Rect.MakeXYWH(0, i * size, ctx.W, size + 0.5)
        c.save()
        c.clipRect(rect, skia.ClipOp.kIntersect, True)
        off = (1 - q) * (ctx.H if vertical else ctx.W) * (1 if i % 2 else -1)
        c.translate(0, off) if vertical else c.translate(off, 0)
        _frame(c, ctx)
        b(c)
        c.restore()


def zoom(c, a: Draw, b: Draw, p: float, ctx: Ctx, amount: float = 0.3) -> None:
    """a が拡大しながら消え、b が縮みながら現れる。"""
    for fn, s, alpha in ((a, 1 + amount * p, 1 - p), (b, 1 - amount * (1 - p) * 0.5, p)):
        c.save()
        c.translate(ctx.CX, ctx.CY)
        c.scale(s, s)
        c.translate(-ctx.CX, -ctx.CY)
        _frame(c, ctx)
        c.saveLayerAlpha(None, int(round(clamp(alpha) * 255)))
        fn(c)
        c.restore()
        c.restore()


KINDS = {"cut": None, "crossfade": crossfade, "push": push, "wipe": wipe, "iris": iris, "slices": slices,
         "zoom": zoom}


class Transition(Scene):
    """a から b へ切り替える区間を受け持つシーン。区間中の a と b は直接描かれなくなる。"""

    def __init__(self, a: Scene, b: Scene, at: float, dur: float, kind: str | Callable = "crossfade",
                 ease=easing.inout_cubic, z: int | None = None, **kw):
        super().__init__(at, at + dur, z if z is not None else max(a.z, b.z))
        self.a, self.b = a, b
        self.fn = KINDS[kind] if isinstance(kind, str) else kind
        self.ease = easing.get(ease)
        self.kw = kw
        # トランジション中も両方が「生きている」ように区間を広げておく
        if a.end is not None and a.end < at + dur:
            a.end = at + dur
        if b.start > at:
            b.start = at
        a.hide(at, at + dur)
        b.hide(at, at + dur)

    def draw(self, c: skia.Canvas, ctx: Ctx) -> None:
        comp: Composition = ctx.comp
        p = self.ease(clamp(ctx.p))
        da = lambda cv: paint_scene(cv, self.a, ctx.t, ctx.frame, comp)  # noqa: E731
        db = lambda cv: paint_scene(cv, self.b, ctx.t, ctx.frame, comp)  # noqa: E731
        if self.fn is None:
            (db if p >= 0.5 else da)(c)
        else:
            self.fn(c, da, db, p, ctx, **self.kw)


def montage(c: skia.Canvas, ctx: Ctx, cells: list[Draw], cols: int, rows: int, gap: float = 12.0,
            radius: float = 8.0, pop: Callable[[int], float] | None = None) -> None:
    """全画面用の描画関数を、縮小して格子状に並べる。pop(i) で各セルの出現度 (0〜1) を与えられる。"""
    cw = (ctx.W - gap * (cols + 1)) / cols
    ch = (ctx.H - gap * (rows + 1)) / rows
    s = min(cw / ctx.W, ch / ctx.H)
    for i, fn in enumerate(cells[:cols * rows]):
        r, k = divmod(i, cols)
        x = gap + k * (cw + gap)
        y = gap + r * (ch + gap)
        q = 1.0 if pop is None else clamp(pop(i))
        if q <= 0:
            continue
        c.save()
        cx, cy = x + cw / 2, y + ch / 2
        c.translate(cx, cy)
        c.scale(q, q)
        c.translate(-cx, -cy)
        c.clipRRect(skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(x, y, cw, ch), radius, radius), skia.ClipOp.kIntersect,
                    True)
        c.translate(cx - ctx.W * s / 2, cy - ctx.H * s / 2)
        c.scale(s, s)
        fn(c)
        c.restore()
