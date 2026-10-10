"""キャプチャの上に重ねる注釈: 吹き出し、強調、ロワーサード、字幕、バッジ。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import skia

from . import easing
from .anim import clamp, progress, window
from .color import Color, to_color
from .draw import paint, path, trim
from .nodes import note_text
from .scene import Ctx, Scene
from .text import layout, shape, text


def callout(c: skia.Canvas, target: tuple[float, float], label: str, p: float, *, offset=(160, -120),
            color: Color | str = "#FACC15", fg: Color | str = "#0C0C0F", size: float = 30, sub: str | None = None,
            font: str = "sans") -> None:
    """target を指す引き出し線つきのラベル。p (0〜1) で点 → 線 → ラベルの順に現れる。"""
    col = to_color(color)
    tx, ty = target
    ex, ey = tx + offset[0], ty + offset[1]
    dot = clamp(p * 4)
    if dot > 0:
        c.drawCircle(tx, ty, 9 * dot, paint(col))
        c.drawCircle(tx, ty, 9 + 14 * dot, paint(col, stroke=3, alpha=0.5 * dot))
    lp = clamp((p - 0.15) / 0.35)
    if lp > 0:
        c.drawPath(trim(path([(tx, ty), (tx + (ex - tx) * 0.6, ey), (ex, ey)]), 0, lp), paint(col, stroke=3))
    bp = easing.out_back(clamp((p - 0.45) / 0.4))
    if bp > 0:
        sh = shape(label, font, size, {"wght": 800})
        sw = sh.width + 32
        if sub:
            sw = max(sw, shape(sub, "mono", size * 0.6).width + 32)
        bh = size * 1.7 + (size * 0.9 if sub else 0)
        bx = ex if offset[0] >= 0 else ex - sw
        by = ey - bh / 2
        c.save()
        c.translate(ex, ey)
        c.scale(bp, bp)
        c.translate(-ex, -ey)
        c.drawRRect(skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(bx, by, sw, bh), 10, 10), paint(col))
        text(c, label, bx + 16, by + size * 0.85, size=size, axes={"wght": 800}, color=fg, valign="cap", font=font)
        if sub:
            text(c, sub, bx + 16, by + size * 1.75, font="mono", size=size * 0.6, color=fg, valign="cap", alpha=0.75)
        c.restore()


def highlight(c: skia.Canvas, ctx: Ctx, rect: tuple[float, float, float, float], p: float, *,
              color: Color | str = "#FACC15", dim: float = 0.55, radius: float = 14, circle: bool = False) -> None:
    """rect の外側を暗くして、枠を描き込む。p (0〜1) で現れる。"""
    x, y, w, h = rect
    if p <= 0:
        return
    shape_path = skia.Path()
    if circle:
        shape_path.addOval(skia.Rect.MakeXYWH(x, y, w, h))
    else:
        shape_path.addRRect(skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(x, y, w, h), radius, radius))
    c.save()
    c.clipPath(shape_path, skia.ClipOp.kDifference, True)
    c.drawRect(skia.Rect.MakeWH(ctx.W, ctx.H), paint("#000000", alpha=dim * clamp(p)))
    c.restore()
    c.drawPath(trim(shape_path, 0, easing.out_cubic(clamp(p * 1.3))), paint(color, stroke=5))


def lower_third(c: skia.Canvas, ctx: Ctx, title: str, sub: str | None, t0: float, t1: float, *,
                accent: Color | str = "#FACC15", x: float = 80, y: float | None = None, size: float = 48) -> None:
    """画面下の名前・説明テロップ。t0 で入り、t1 で抜ける。"""
    y = ctx.H - 200 if y is None else y
    a = progress(ctx.t, t0, t0 + 0.45, easing.out_expo)
    b = progress(ctx.t, t1 - 0.35, t1, easing.in_expo)
    if a <= 0 or b >= 1:
        return
    sh = shape(title, "sans", size, {"wght": 850})
    sw = sh.width + 48
    bar_w = sw * a * (1 - b)
    c.drawRect(skia.Rect.MakeXYWH(x, y, 8, size * 1.5), paint(accent, alpha=1 - b))
    c.save()
    c.clipRect(skia.Rect.MakeXYWH(x + 8, y - 4, bar_w, size * 2.6), skia.ClipOp.kIntersect, True)
    c.drawRect(skia.Rect.MakeXYWH(x + 8, y, sw, size * 1.5), paint("#0C0C0F", alpha=0.82))
    text(c, title, x + 32, y + size * 0.75, size=size, axes={"wght": 850}, valign="cap", color="#FFFFFF")
    if sub:
        ssh = shape(sub, "mono", size * 0.5)
        c.drawRect(skia.Rect.MakeXYWH(x + 8, y + size * 1.5, ssh.width + 48, size * 0.95), paint(accent))
        text(c, sub, x + 32, y + size * 1.98, font="mono", size=size * 0.5, valign="cap", color="#0C0C0F")
    c.restore()


def badge(c: skia.Canvas, x: float, y: float, label: str, p: float, *, color: Color | str = "#FF5A1F",
          fg: Color | str = "#FFFFFF", size: float = 34, angle: float = -6) -> None:
    """「NEW!」のような傾いたバッジ。p でばねのように弾んで出る。"""
    if p <= 0:
        return
    sh = shape(label, "sans", size, {"wght": 900, "wdth": 110})
    w, h = sh.width + 40, size * 1.7
    c.save()
    c.translate(x, y)
    c.rotate(angle)
    c.scale(p, p)
    c.drawRRect(skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(-w / 2, -h / 2, w, h), 10, 10), paint(color))
    text(c, label, 0, 0, size=size, axes={"wght": 900, "wdth": 110}, color=fg, align="center", valign="cap")
    c.restore()


@dataclass
class Cue:
    start: float
    end: float
    text: str


def read_srt(path: str | Path) -> list[Cue]:
    """SRT 字幕を読む。"""
    body = Path(path).read_text(encoding="utf-8-sig")
    out = []
    for block in re.split(r"\n\s*\n", body.strip()):
        lines = block.strip().splitlines()
        tline = next((ln for ln in lines if "-->" in ln), None)
        if not tline:
            continue

        def sec(s):
            h, m, rest = s.strip().replace(",", ".").split(":")
            return int(h) * 3600 + int(m) * 60 + float(rest)

        a, b = tline.split("-->")
        txt = "\n".join(lines[lines.index(tline) + 1:]).strip()
        out.append(Cue(sec(a), sec(b), txt))
    return out


class Captions(Scene):
    """字幕のシーン。cues は Cue のリストか SRT のパス。"""
    fixed = True

    def __init__(self, cues: list[Cue] | str | Path, *, size: float = 44, width: float = 0.75,
                 bottom: float = 110, font: str = "sans", z: int = 50, start: float = 0.0, end: float | None = None):
        super().__init__(start, end, z, True)
        self.cues = read_srt(cues) if isinstance(cues, (str, Path)) else cues
        self.size, self.width, self.bottom, self.font = size, width, bottom, font

    def draw(self, c: skia.Canvas, ctx: Ctx) -> None:
        for q in self.cues:
            if not (q.start <= ctx.t < q.end):
                continue
            a = window(ctx.t, q.start, q.end, 0.12, 0.12)
            lines = layout(q.text, ctx.W * self.width, font=self.font, size=self.size, axes={"wght": 700},
                           align="center", leading=1.35)
            total = (len(lines) - 1) * self.size * 1.35
            base_y = ctx.H - self.bottom - total
            ox = ctx.W * (1 - self.width) / 2
            for ln in lines:
                blob = ln.shaped.blob()
                if blob is None:
                    continue
                y = base_y + ln.y
                # 縁取りの黒 → 本体の白の順に描いて、明るい映像の上でも読めるようにする
                stroke = paint("#000000", stroke=self.size * 0.16, alpha=0.85 * a)
                stroke.setStrokeJoin(skia.Paint.kRound_Join)
                c.drawTextBlob(blob, ox + ln.x, y, stroke)
                c.drawTextBlob(blob, ox + ln.x, y, paint("#FFFFFF", alpha=a))
                note_text(c, a, (ox + ln.x, y - ln.shaped.cap_height, ox + ln.x + ln.shaped.width, y))
