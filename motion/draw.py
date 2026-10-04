from __future__ import annotations

import math
from contextlib import contextmanager
from typing import Iterable

import skia

from .color import Color, to_color

_CAPS = {"butt": skia.Paint.kButt_Cap, "round": skia.Paint.kRound_Cap, "square": skia.Paint.kSquare_Cap}
_BLENDS = {
    "add": skia.BlendMode.kPlus,
    "screen": skia.BlendMode.kScreen,
    "multiply": skia.BlendMode.kMultiply,
    "overlay": skia.BlendMode.kOverlay,
    "difference": skia.BlendMode.kDifference,
    "exclusion": skia.BlendMode.kExclusion,
}


def paint(color: Color | str = "#ffffff", *, stroke: float | None = None, cap: str = "round",
          blend: str | None = None, blur: float = 0.0, alpha: float = 1.0, aa: bool = True) -> skia.Paint:
    p = skia.Paint(AntiAlias=aa, Color=to_color(color).alpha(alpha).skia())
    if stroke is not None:
        p.setStyle(skia.Paint.kStroke_Style)
        p.setStrokeWidth(stroke)
        p.setStrokeCap(_CAPS[cap])
        p.setStrokeJoin(skia.Paint.kRound_Join)
    if blend:
        p.setBlendMode(_BLENDS[blend])
    if blur > 0:
        p.setMaskFilter(skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, blur))
    return p


def fill(c: skia.Canvas, color: Color | str, alpha: float = 1.0) -> None:
    c.drawPaint(paint(color, alpha=alpha))


def rect(c: skia.Canvas, x: float, y: float, w: float, h: float, color: Color | str = "#fff",
         r: float = 0.0, center: bool = False, **kw) -> None:
    if center:
        x, y = x - w / 2, y - h / 2
    rr = skia.Rect.MakeXYWH(x, y, w, h)
    if r > 0:
        c.drawRRect(skia.RRect.MakeRectXY(rr, r, r), paint(color, **kw))
    else:
        c.drawRect(rr, paint(color, **kw))


def circle(c: skia.Canvas, x: float, y: float, r: float, color: Color | str = "#fff", **kw) -> None:
    c.drawCircle(x, y, r, paint(color, **kw))


def ellipse(c: skia.Canvas, x: float, y: float, rx: float, ry: float, color: Color | str = "#fff", **kw) -> None:
    c.drawOval(skia.Rect.MakeLTRB(x - rx, y - ry, x + rx, y + ry), paint(color, **kw))


def line(c: skia.Canvas, x0: float, y0: float, x1: float, y1: float, color: Color | str = "#fff",
         width: float = 2.0, **kw) -> None:
    c.drawLine(x0, y0, x1, y1, paint(color, stroke=width, **kw))


def path(pts: Iterable[tuple[float, float]], closed: bool = False) -> skia.Path:
    p = skia.Path()
    for i, (x, y) in enumerate(pts):
        if i == 0:
            p.moveTo(x, y)
        else:
            p.lineTo(x, y)
    if closed:
        p.close()
    return p


def poly(c: skia.Canvas, pts: Iterable[tuple[float, float]], color: Color | str = "#fff",
         closed: bool = False, **kw) -> None:
    c.drawPath(path(pts, closed), paint(color, **kw))


def trim(p: skia.Path, start: float, end: float) -> skia.Path:
    """パスの start〜end (0〜1) の区間だけを切り出す。線を描き進める演出用。"""
    out = skia.Path()
    meas = skia.PathMeasure(p, False)
    total = meas.getLength()
    if total <= 0 or end <= start:
        return out
    meas.getSegment(total * max(start, 0.0), total * min(end, 1.0), out, True)
    return out


def regular(cx: float, cy: float, r: float, n: int, rot: float = 0.0) -> list[tuple[float, float]]:
    return [(cx + r * math.cos(rot + 2 * math.pi * i / n), cy + r * math.sin(rot + 2 * math.pi * i / n))
            for i in range(n)]


@contextmanager
def transform(c: skia.Canvas, x: float = 0.0, y: float = 0.0, rot: float = 0.0, sx: float = 1.0,
              sy: float | None = None, origin: tuple[float, float] = (0.0, 0.0)):
    """origin を中心に回転・拡縮してから (x, y) だけ平行移動する。rot は度。"""
    c.save()
    c.translate(x + origin[0], y + origin[1])
    if rot:
        c.rotate(rot)
    c.scale(sx, sx if sy is None else sy)
    c.translate(-origin[0], -origin[1])
    try:
        yield c
    finally:
        c.restore()


@contextmanager
def layer(c: skia.Canvas, alpha: float = 1.0, blend: str | None = None, blur: float = 0.0):
    """以降の描画をオフスクリーンにまとめ、不透明度・ブレンド・ぼかしをかけて合成する。"""
    p = skia.Paint(Alphaf=max(0.0, min(1.0, alpha)))
    if blend:
        p.setBlendMode(_BLENDS[blend])
    if blur > 0:
        p.setImageFilter(skia.ImageFilters.Blur(blur, blur))
    c.saveLayer(None, p)
    try:
        yield c
    finally:
        c.restore()


@contextmanager
def clip_rect(c: skia.Canvas, x: float, y: float, w: float, h: float, r: float = 0.0):
    c.save()
    rr = skia.Rect.MakeXYWH(x, y, w, h)
    if r > 0:
        c.clipRRect(skia.RRect.MakeRectXY(rr, r, r), skia.ClipOp.kIntersect, True)
    else:
        c.clipRect(rr, skia.ClipOp.kIntersect, True)
    try:
        yield c
    finally:
        c.restore()
