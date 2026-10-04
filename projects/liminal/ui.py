"""LiminalPalette 紹介動画用の UI 部品。README のヒーロー画像の見た目に合わせる。"""
import math
import re

import numpy as np
import skia

from motion import Palette, draw, text
from motion.anim import clamp

pal = Palette(
    bg="#121214", bg2="#18181C", panel="#1C1C21", panel2="#232329", line="#34343C", grid="#2A2A31",
    text="#ECECEF", dim="#8B8B95", faint="#55555E",
    blue="#3B82F6", blue_hi="#60A5FA", sel="#2B5A8C", yellow="#FACC15", green="#4ADE80", lime="#A3E635",
    purple="#C084FC", red="#F87171",
)
MONO = "sans-mono"


def background(c: skia.Canvas, ctx, glow: float = 1.0, grid_alpha: float = 1.0) -> None:
    """暗いグラデーション + 「+」の格子 + 右上の青いにじみ。"""
    W, H = ctx.W, ctx.H
    p = skia.Paint(Shader=skia.GradientShader.MakeLinear(
        [skia.Point(0, 0), skia.Point(0, H)], [pal.bg.skia(), pal.bg2.skia()]))
    c.drawRect(skia.Rect.MakeWH(W, H), p)
    if glow > 0:
        g = skia.Paint(Shader=skia.GradientShader.MakeRadial(
            skia.Point(W * 0.85, H * 0.12), W * 0.6,
            [pal.blue.alpha(0.22 * glow).skia(), pal.blue.alpha(0.0).skia()]))
        c.drawRect(skia.Rect.MakeWH(W, H), g)
    if grid_alpha > 0:
        step = 120
        off = (ctx.t * 6) % step
        pt = draw.paint(pal.grid, stroke=2, alpha=grid_alpha, cap="butt")
        for x in np.arange(-step, W + step, step) + off:
            for y in np.arange(-step, H + step, step) + off * 0.5:
                c.drawLine(x - 9, y, x + 9, y, pt)
                c.drawLine(x, y - 9, x, y + 9, pt)


def panel(c: skia.Canvas, x, y, w, h, *, border=None, glow: float = 0.0, label: str | None = None,
          label_color=None, fill=None, radius: float = 18, alpha: float = 1.0, border_w: float = 2.0) -> None:
    border = border or pal.line
    rr = skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(x, y, w, h), radius, radius)
    if glow > 0:
        gp = draw.paint(border, stroke=10, alpha=0.55 * glow * alpha, blur=18)
        c.drawRRect(rr, gp)
    c.drawRRect(rr, draw.paint(fill or pal.panel, alpha=alpha))
    c.drawRRect(rr, draw.paint(border, stroke=border_w, alpha=alpha))
    if label:
        chip(c, x + 26, y, label, color=label_color or pal.dim, alpha=alpha, size=20, center_y=True)


def chip(c: skia.Canvas, x, y, label: str, *, color=None, fill=None, size: float = 20, alpha: float = 1.0,
         center_y: bool = False, border=None, pad: float = 12) -> float:
    """角丸の小さなラベル。戻り値は幅。"""
    color = color or pal.dim
    sh = text.shape(label, MONO, size, {"wght": 500})
    w, h = sh.width + pad * 2, size * 1.6
    top = y - h / 2 if center_y else y
    rr = skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(x, top, w, h), h / 2, h / 2)
    c.drawRRect(rr, draw.paint(fill or pal.bg, alpha=alpha))
    c.drawRRect(rr, draw.paint(border or color, stroke=1.6, alpha=alpha * 0.9))
    text.text(c, label, x + pad, top + h / 2, font=MONO, size=size, axes={"wght": 500}, color=color, valign="cap",
              alpha=alpha)
    return w


_KW = {"public", "void", "int", "float", "string", "bool", "await", "static", "return", "yield", "new", "var",
       "class", "using", "IEnumerable", "IEnumerator"}
_TOKEN = re.compile(r'"[^"]*"|\[|\]|\(|\)|=>|[A-Za-z_][A-Za-z0-9_]*|\d+(?:\.\d+)?|\s+|.')


def tokenize_cs(line: str) -> list[tuple[str, object]]:
    """C# 1 行をざっくり色分けする。"""
    out = []
    toks = _TOKEN.findall(line)
    for i, tk in enumerate(toks):
        nxt = next((t for t in toks[i + 1:] if not t.isspace()), "")
        if tk.startswith('"'):
            col = pal.lime
        elif tk in _KW:
            col = pal.purple
        elif tk in ("[", "]") or tk.startswith("Liminal"):
            col = pal.yellow
        elif re.fullmatch(r"\d+(\.\d+)?", tk):
            col = pal.yellow
        elif nxt == "(" and tk[0].isalpha():
            col = pal.blue_hi
        else:
            col = pal.text
        out.append((tk, col))
    return out


def colored_line(c: skia.Canvas, tokens, x, y, *, size: float = 34, visible: int | None = None,
                 alpha: float = 1.0, font: str = MONO, wght: float = 450) -> float:
    """色付きトークン列を描く。visible で先頭から何文字まで見せるか (タイプライター)。戻り値は描いた幅。"""
    pen = x
    left = visible if visible is not None else 10 ** 9
    for tk, col in tokens:
        if left <= 0:
            break
        s = tk[:left]
        left -= len(tk)
        sh = text.text(c, s, pen, y, font=font, size=size, axes={"wght": wght}, color=col, alpha=alpha)
        pen += sh.width
    return pen - x


def type_count(t: float, t0: float, n: int, rate: float) -> int:
    """t0 から 1 秒あたり rate 文字ずつ打った時点で見えている文字数。"""
    return int(clamp((t - t0) * rate / n) * n) if t > t0 else 0


def caret(c: skia.Canvas, x, y, size, t: float, color=None, period: float = 0.5, solid: bool = False) -> None:
    on = solid or (t % period) < period / 2
    if on:
        draw.rect(c, x + 2, y - size * 0.8, size * 0.5, size * 0.95, color or pal.yellow)


def keycap(c: skia.Canvas, cx, cy, label: str, press: float, size: float = 120, alpha: float = 1.0) -> None:
    """キーボードのキー。press=1 で押し込まれる。"""
    depth = 14 * (1 - press)
    x, y = cx - size / 2, cy - size / 2
    c.drawRRect(skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(x, y + 14, size, size), 22, 22),
                draw.paint("#0A0A0C", alpha=alpha))
    top = y + 14 - depth
    lit = press
    c.drawRRect(skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(x, top, size, size), 22, 22),
                draw.paint(pal.panel2.mix(pal.sel, lit * 0.6), alpha=alpha))
    c.drawRRect(skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(x, top, size, size), 22, 22),
                draw.paint(pal.line.mix(pal.blue, lit), stroke=2.5, alpha=alpha))
    text.text(c, label, cx, top + size / 2, size=size * 0.42, axes={"wght": 600}, color=pal.text, align="center",
              valign="cap", alpha=alpha)


def logo_mark(c: skia.Canvas, x, y, s: float, draw_p: float = 1.0, cursor: float = 1.0, alpha: float = 1.0) -> None:
    """「>」+ 黄色のアンダースコア。(x, y) は左上、s は高さ。"""
    pts = [(0.0, 0.0), (0.42, 0.0), (0.78, 0.5), (0.42, 1.0), (0.0, 1.0), (0.36, 0.5)]
    path = draw.path([(x + px * s, y + py * s) for px, py in pts], closed=True)
    if draw_p < 1.0:
        c.save()
        c.clipRect(skia.Rect.MakeXYWH(x - s, y - s, s * 3 * draw_p, s * 3), skia.ClipOp.kIntersect, True)
    c.drawPath(path, draw.paint(pal.blue, alpha=alpha))
    if draw_p < 1.0:
        c.restore()
    if cursor > 0:
        draw.rect(c, x + s * 0.68, y + s * 0.80, s * 0.44 * cursor, s * 0.2, pal.yellow, alpha=alpha)


def wire(c: skia.Canvas, pts, progress: float, color, width: float = 3.0, alpha: float = 1.0) -> skia.Path:
    p = draw.path(pts)
    seg = draw.trim(p, 0.0, progress)
    c.drawPath(seg, draw.paint(color, stroke=width, alpha=alpha, cap="round"))
    return p


def point_on(path: skia.Path, u: float) -> tuple[float, float]:
    m = skia.PathMeasure(path, False)
    pos, _ = m.getPosTan(m.getLength() * clamp(u))
    return pos.x(), pos.y()


def checkmark(c: skia.Canvas, cx, cy, s, p: float, color=None, width: float = 5) -> None:
    pts = [(cx - s * 0.5, cy), (cx - s * 0.15, cy + s * 0.35), (cx + s * 0.55, cy - s * 0.4)]
    c.drawPath(draw.trim(draw.path(pts), 0, p), draw.paint(color or pal.green, stroke=width, cap="round"))


def fuzzy(query: str, cand: str) -> list[int] | None:
    """VS Code 風のあいまい一致。一致した文字の位置を返す (一致しなければ None)。"""
    q = query.replace(" ", "").lower()
    idx, j = [], 0
    low = cand.lower()
    for i, ch in enumerate(low):
        if j < len(q) and ch == q[j]:
            idx.append(i)
            j += 1
    return idx if j == len(q) else None


def ease_pop(p: float) -> float:
    return 1 - (1 - clamp(p)) ** 3 * math.cos(clamp(p) * math.pi * 1.5) if p < 1 else 1.0
