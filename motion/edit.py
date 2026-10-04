"""キャプチャを使った編集の部品: 拍に合わせたカット割り、比較スライダー、PiP、縦動画用の背景、パンチイン。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import skia

from . import easing
from .anim import clamp, impact, progress
from .footage import Clip, Footage, Grade, TimeMap
from .scene import Ctx, Scene
from .text import shape, text


@dataclass
class Shot:
    """カット割りの 1 カット。素材の src から、作品上で dur 秒ぶん使う。"""
    footage: Footage
    src: float
    dur: float | None = None
    speed: float = 1.0
    time: TimeMap | None = None
    draw_kw: dict = field(default_factory=dict)


def cut_on_beats(shots: list[Shot], start: float, beat_len: float, beats: int | list[int] = 2) -> list[Clip]:
    """ショットを拍の長さで順に並べたクリップ列にする。beats は全カット共通か、カットごとの拍数のリスト。"""
    clips = []
    t = start
    for i, s in enumerate(shots):
        n = beats[i % len(beats)] if isinstance(beats, list) else beats
        dur = s.dur if s.dur is not None else n * beat_len
        tm = s.time or TimeMap().play(dur, s.speed)
        clip = Clip(s.footage, at=t, src_in=s.src, time=tm)
        clip.draw_kw = s.draw_kw
        clips.append(clip)
        t += tm.duration
    return clips


class Sequence(Scene):
    """クリップを時間順に全画面で描くシーン。カットの瞬間にフラッシュやズームを入れられる。"""

    def __init__(self, clips: list[Clip], *, fit: str = "cover", grade: Grade | None = None,
                 punch: float = 0.0, z: int | None = None):
        super().__init__(clips[0].at, clips[-1].end, z)
        self.clips = clips
        self.fit = fit
        self.grade = grade
        self.punch = punch

    @property
    def cuts(self) -> list[float]:
        return [c.at for c in self.clips[1:]]

    def draw(self, c: skia.Canvas, ctx: Ctx) -> None:
        clip = next((cl for cl in self.clips if cl.at <= ctx.t < cl.end), self.clips[-1])
        kw = dict(getattr(clip, "draw_kw", {}) or {})
        z = kw.pop("zoom", 1.0)
        # カットの頭で少し寄ってから戻る (パンチイン)
        pz = 1 + self.punch * impact(ctx.t, [clip.at], 9)
        zoom = (lambda t: (z(t) if callable(z) else z) * pz)
        clip.draw(c, ctx, fit=kw.pop("fit", self.fit), grade=kw.pop("grade", self.grade), zoom=zoom, **kw)


def compare(c: skia.Canvas, ctx: Ctx, left: Callable[[skia.Canvas], None], right: Callable[[skia.Canvas], None],
            split: float, *, labels: tuple[str, str] | None = ("BEFORE", "AFTER"), color: str = "#FFFFFF",
            accent: str = "#FACC15", x: float = 0.0, y: float = 0.0, w: float | None = None,
            h: float | None = None, label_y: float = 36.0) -> None:
    """左右比較スライダー。split (0〜1) の位置で left と right を切り替えて見せる。

    label_y は枠の上端からラベルまでの距離。ゲームの HUD と重なるときに下げる。
    """
    w = ctx.W if w is None else w
    h = ctx.H if h is None else h
    sx = x + w * clamp(split)
    c.save()
    c.clipRect(skia.Rect.MakeLTRB(x, y, sx, y + h), skia.ClipOp.kIntersect, True)
    left(c)
    c.restore()
    c.save()
    c.clipRect(skia.Rect.MakeLTRB(sx, y, x + w, y + h), skia.ClipOp.kIntersect, True)
    right(c)
    c.restore()
    p = skia.Paint(AntiAlias=True, Color=skia.Color(255, 255, 255))
    c.drawRect(skia.Rect.MakeLTRB(sx - 2, y, sx + 2, y + h), p)
    hp = skia.Paint(AntiAlias=True)
    hp.setColor(skia.Color(*[int(color.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]))
    c.drawCircle(sx, y + h / 2, 26, hp)
    ap = skia.Paint(AntiAlias=True, Color=skia.Color(20, 20, 24))
    for d in (-1, 1):
        path = skia.Path()
        path.addPoly([skia.Point(sx + d * 6, y + h / 2 - 9), skia.Point(sx + d * 16, y + h / 2),
                      skia.Point(sx + d * 6, y + h / 2 + 9)], True)
        c.drawPath(path, ap)
    if labels:
        for i, lab in enumerate(labels):
            sh = shape(lab, "mono", 26)
            lx = x + 40 if i == 0 else x + w - 40 - sh.width - 28
            vis = (sx - x) > 40 + sh.width + 40 if i == 0 else (x + w - sx) > 40 + sh.width + 40
            if not vis:
                continue
            bg = skia.Paint(AntiAlias=True, Color=skia.Color(10, 10, 14, 200))
            c.drawRRect(skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(lx, y + label_y, sh.width + 28, 46), 8, 8), bg)
            text(c, lab, lx + 14, y + label_y + 23, font="mono", size=26, color=accent if i == 1 else color,
                 valign="cap")


def blur_fill(c: skia.Canvas, ctx: Ctx, clip: Clip, *, blur: float = 40.0, dim: float = 0.45,
              box: tuple[float, float, float, float] | None = None, radius: float = 24.0, **kw) -> None:
    """縦動画などで、横長のクリップを中央に置き、背景をぼかした同じ映像で埋める。"""
    c.save()
    p = skia.Paint()
    p.setImageFilter(skia.ImageFilters.Blur(blur, blur))
    c.saveLayer(None, p)
    clip.draw(c, ctx, fit="cover", zoom=1.15)
    c.restore()
    c.drawRect(skia.Rect.MakeWH(ctx.W, ctx.H), skia.Paint(Color=skia.Color(0, 0, 0, int(255 * dim))))
    c.restore()
    if box is None:
        bw = ctx.W - 64
        bh = bw * clip.footage.height / clip.footage.width
        box = (32, (ctx.H - bh) / 2, bw, bh)
    clip.draw(c, ctx, *box, fit="cover", radius=radius, shadow=30, **kw)


def pip(c: skia.Canvas, ctx: Ctx, clip: Clip, *, corner: str = "br", width: float = 0.32, margin: float = 48,
        radius: float = 18, pop: float = 1.0, **kw) -> tuple[float, float, float, float]:
    """ピクチャーインピクチャー。戻り値は描いた枠。"""
    w = ctx.W * width
    h = w * clip.footage.height / clip.footage.width
    x = margin if "l" in corner else ctx.W - margin - w
    y = margin if "t" in corner else ctx.H - margin - h
    s = 0.6 + 0.4 * clamp(pop)
    c.save()
    c.translate(x + w / 2, y + h / 2)
    c.scale(s, s)
    c.translate(-(x + w / 2), -(y + h / 2))
    clip.draw(c, ctx, x, y, w, h, radius=radius, shadow=24, border=3, alpha=clamp(pop * 2), **kw)
    c.restore()
    return x, y, w, h


def ken_burns(t0: float, t1: float, z0: float = 1.0, z1: float = 1.15, f0=(0.5, 0.5), f1=(0.5, 0.5),
              ease=easing.inout_sine):
    """zoom と focus に渡すアニメーション関数の組を作る。"""
    def zoom(t):
        return z0 + (z1 - z0) * progress(t, t0, t1, ease)

    def focus(t):
        p = progress(t, t0, t1, ease)
        return f0[0] + (f1[0] - f0[0]) * p, f0[1] + (f1[1] - f0[1]) * p

    return zoom, focus
