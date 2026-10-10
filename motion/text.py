from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import skia
import uharfbuzz as hb

from . import nodes as _nodes
from .color import Color
from .draw import paint as make_paint

FONTS_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
ALIASES = {
    "sans": "MonaSans-VF.ttf",
    "sans-mono": "MonaSansMono-VF.ttf",
    "mono": "FragmentMono-Regular.ttf",
    "jp": "NotoSansJP-VF.ttf",
}
# 字形が無い文字を補うフォントの順番
FALLBACK = ["jp"]

Axes = dict[str, float] | None


def _tag(s: str) -> int:
    return int.from_bytes(s.encode("ascii"), "big")


class Font:
    def __init__(self, path: str | Path):
        self.path = str(path)
        data = Path(path).read_bytes()
        self.hb_face = hb.Face(hb.Blob(data))
        self.upem = self.hb_face.upem
        self.base = skia.Typeface.MakeFromFile(self.path)
        try:
            params = self.base.getVariationDesignParameters() or []
        except RuntimeError:
            # 可変フォントでないと例外になる
            params = []
        self.axes = {int(a.tag).to_bytes(4, "big").decode("ascii"): (a.min, a.max) for a in params}
        self._plain = hb.Font(self.hb_face)

    def _key(self, axes: Axes) -> tuple:
        # 軸の値を丸めてキャッシュを効かせる (0.5 単位の差は見た目に出ない)。持たない軸は捨てる
        return tuple(sorted((k, round(v * 2) / 2) for k, v in (axes or {}).items() if k in self.axes))

    @lru_cache(maxsize=1024)
    def _typeface(self, key: tuple) -> skia.Typeface:
        if not key:
            return self.base
        VP = skia.FontArguments.VariationPosition
        coords = VP.Coordinates([VP.Coordinate(_tag(k), float(v)) for k, v in key])
        pos = VP(coords)
        # setVariationDesignPosition の戻り値を渡すと指定が失われるため、引数オブジェクトを保持して渡す
        args = skia.FontArguments()
        args.setVariationDesignPosition(pos)
        return self.base.makeClone(args)

    @lru_cache(maxsize=1024)
    def _hb_font(self, key: tuple) -> hb.Font:
        f = hb.Font(self.hb_face)
        if key:
            f.set_variations(dict(key))
        return f

    @lru_cache(maxsize=4096)
    def has(self, ch: str) -> bool:
        return self._plain.get_nominal_glyph(ord(ch)) is not None

    def skfont(self, size: float, axes: Axes = None) -> skia.Font:
        f = skia.Font(self._typeface(self._key(axes)), size)
        f.setSubpixel(True)
        f.setEdging(skia.Font.Edging.kSubpixelAntiAlias)
        f.setHinting(skia.FontHinting.kNone)
        return f

    def metrics(self, size: float, axes: Axes = None) -> skia.FontMetrics:
        return self.skfont(size, axes).getMetrics()

    def shape_run(self, s: str, size: float, axes: Axes, features: dict | None = None):
        buf = hb.Buffer()
        buf.add_str(s)
        buf.guess_segment_properties()
        hb.shape(self._hb_font(self._key(axes)), buf, features or {"kern": True, "liga": True})
        k = size / self.upem
        return [(i.codepoint, i.cluster, p.x_offset * k, -p.y_offset * k, p.x_advance * k)
                for i, p in zip(buf.glyph_infos, buf.glyph_positions)]


def _runs(s: str, fonts: list[Font]) -> list[tuple[int, int, Font]]:
    """文字ごとに字形を持つ最初のフォントを選び、同じフォントの連続区間にまとめる。"""
    out: list[tuple[int, int, Font]] = []
    for i, ch in enumerate(s):
        if out and (unicodedata.combining(ch) or ch in "‍️"):
            f = out[-1][2]
        elif ch.isspace() and out:
            f = out[-1][2]
        else:
            f = next((ft for ft in fonts if ft.has(ch)), fonts[0])
        if out and out[-1][2] is f and out[-1][1] == i:
            out[-1] = (out[-1][0], i + 1, f)
        else:
            out.append((i, i + 1, f))
    return out


@dataclass
class Shaped:
    font: Font
    text: str
    size: float
    axes: Axes
    glyphs: list[int]
    xs: list[float]
    ys: list[float]
    advances: list[float]
    clusters: list[int]
    width: float
    fonts: list[Font]

    @property
    def skfont(self) -> skia.Font:
        return self.font.skfont(self.size, self.axes)

    @property
    def cap_height(self) -> float:
        m = self.font.metrics(self.size, self.axes)
        return m.fCapHeight or self.size * 0.7

    def blob(self, indices: list[int] | None = None) -> skia.TextBlob | None:
        idx = list(range(len(self.glyphs)) if indices is None else indices)
        if not idx:
            return None
        b = skia.TextBlobBuilder()
        start = 0
        for j in range(1, len(idx) + 1):
            if j == len(idx) or self.fonts[idx[j]] is not self.fonts[idx[start]]:
                run = idx[start:j]
                b.allocRunPos(self.fonts[run[0]].skfont(self.size, self.axes), [self.glyphs[i] for i in run],
                              [skia.Point(self.xs[i], self.ys[i]) for i in run])
                start = j
        return b.make()

    def letters(self) -> list[tuple[str, float, float, list[int]]]:
        """クラスタ単位の (文字, x, 幅, グリフ index 群)。1 文字ずつ動かす演出に使う。"""
        out: dict[int, list[int]] = {}
        for i, cl in enumerate(self.clusters):
            out.setdefault(cl, []).append(i)
        starts = sorted(out)
        res = []
        for j, cl in enumerate(starts):
            end = starts[j + 1] if j + 1 < len(starts) else len(self.text)
            gi = out[cl]
            res.append((self.text[cl:end], self.xs[gi[0]], sum(self.advances[i] for i in gi), gi))
        return res

    def path(self) -> skia.Path:
        p = skia.Path()
        for g, x, y, f in zip(self.glyphs, self.xs, self.ys, self.fonts):
            gp = f.skfont(self.size, self.axes).getPath(g)
            if gp is not None:
                gp.offset(x, y)
                p.addPath(gp)
        return p


@lru_cache(maxsize=32)
def get_font(name: str) -> Font:
    p = Path(name)
    if not p.exists():
        p = FONTS_DIR / ALIASES.get(name, name)
    return Font(p)


def shape(s: str, font: str = "sans", size: float = 100.0, axes: Axes = None, tracking: float = 0.0,
          fallback: list[str] | None = None) -> Shaped:
    """文字列を組む。font に字形が無い文字 (日本語等) は fallback のフォントで補う。"""
    primary = get_font(font)
    chain = [primary] + [get_font(n) for n in (FALLBACK if fallback is None else fallback) if n != font]
    glyphs, xs, ys, adv, clusters, fonts = [], [], [], [], [], []
    pen = 0.0
    for a, b, f in _runs(s, chain):
        for gid, cl, dx, dy, ax in f.shape_run(s[a:b], size, axes):
            glyphs.append(gid)
            clusters.append(a + cl)
            xs.append(pen + dx)
            ys.append(dy)
            step = ax + tracking * size
            adv.append(step)
            fonts.append(f)
            pen += step
    width = pen - (tracking * size if glyphs else 0.0)
    return Shaped(primary, s, size, axes, glyphs, xs, ys, adv, clusters, width, fonts)


def origin(sh: Shaped, x: float, y: float, align: str = "left", valign: str = "baseline") -> tuple[float, float]:
    """揃え指定から、ベースライン左端の座標を求める。"""
    ox = {"left": x, "center": x - sh.width / 2, "right": x - sh.width}[align]
    cap = sh.cap_height
    oy = {"baseline": y, "cap": y + cap / 2, "top": y + cap, "bottom": y}[valign]
    return ox, oy


def text(c: skia.Canvas, s: str, x: float, y: float, *, font: str = "sans", size: float = 100.0,
         axes: Axes = None, color: Color | str = "#ffffff", align: str = "left", valign: str = "baseline",
         tracking: float = 0.0, alpha: float = 1.0, paint: skia.Paint | None = None, **paint_kw) -> Shaped:
    """文字列を描く。valign="cap" で (x, y) が大文字の高さの中心になる。"""
    sh = shape(s, font, size, axes, tracking)
    ox, oy = origin(sh, x, y, align, valign)
    blob = sh.blob()
    if blob is not None:
        p = paint or make_paint(color, alpha=alpha, **paint_kw)
        c.drawTextBlob(blob, ox, oy, p)
        _nodes.note_text(c, p.getAlphaf(), (ox, oy - sh.cap_height, ox + sh.width, oy))
    return sh


def fit_size(s: str, width: float, font: str = "sans", axes: Axes = None, tracking: float = 0.0) -> float:
    w = shape(s, font, 100.0, axes, tracking).width
    return 100.0 * width / w if w > 0 else 100.0


# 行頭に来てはいけない文字 / 行末に来てはいけない文字 (簡易な禁則処理)
_NO_START = set("、。，．・：；？！ー―…‥）」』】〕〉》｝］)]}!?,.:;%’”ぁぃぅぇぉっゃゅょゎァィゥェォッャュョヮヵヶ々〻")
_NO_END = set("（「『【〔〈《｛［([{‘“")


def _is_cjk(ch: str) -> bool:
    o = ord(ch)
    return (0x3000 <= o <= 0x9FFF) or (0xF900 <= o <= 0xFAFF) or (0xFF00 <= o <= 0xFFEF)


def _tokens(s: str) -> list[str]:
    """改行可能な単位に分ける。欧文は単語、和文は 1 文字ずつ。禁則文字は前後にくっつける。"""
    toks: list[str] = []
    word = ""
    for ch in s:
        if ch == " " or _is_cjk(ch):
            if word:
                toks.append(word)
                word = ""
            toks.append(ch)
        else:
            word += ch
    if word:
        toks.append(word)
    merged: list[str] = []
    for t in toks:
        if merged and (t[0] in _NO_START or merged[-1][-1] in _NO_END):
            merged[-1] += t
        else:
            merged.append(t)
    return merged


@dataclass
class Line:
    shaped: Shaped
    x: float
    y: float


def layout(s: str, width: float, *, font: str = "sans", size: float = 40.0, axes: Axes = None,
           tracking: float = 0.0, leading: float = 1.4, align: str = "left") -> list[Line]:
    """width に収まるように折り返す。y は 1 行目のベースラインを 0 とした値。"""
    lines: list[str] = []
    for para in s.split("\n"):
        cur = ""
        for tok in _tokens(para):
            trial = cur + tok
            if cur and shape(trial.rstrip(), font, size, axes, tracking).width > width:
                lines.append(cur.rstrip())
                cur = tok.lstrip()
            else:
                cur = trial
        lines.append(cur.rstrip())
    out = []
    for i, ln in enumerate(lines):
        sh = shape(ln, font, size, axes, tracking)
        x = {"left": 0.0, "center": (width - sh.width) / 2, "right": width - sh.width}[align]
        out.append(Line(sh, x, i * size * leading))
    return out


def paragraph(c: skia.Canvas, s: str, x: float, y: float, width: float, *, font: str = "sans",
              size: float = 40.0, axes: Axes = None, color: Color | str = "#ffffff", tracking: float = 0.0,
              leading: float = 1.4, align: str = "left", alpha: float = 1.0, **paint_kw) -> list[Line]:
    """(x, y) を左上として、width で折り返した文章を描く。"""
    lines = layout(s, width, font=font, size=size, axes=axes, tracking=tracking, leading=leading, align=align)
    if not lines:
        return lines
    top = lines[0].shaped.cap_height
    p = make_paint(color, alpha=alpha, **paint_kw)
    for ln in lines:
        blob = ln.shaped.blob()
        if blob is not None:
            c.drawTextBlob(blob, x + ln.x, y + top + ln.y, p)
            _nodes.note_text(c, p.getAlphaf(), (x + ln.x, y + ln.y, x + ln.x + ln.shaped.width, y + top + ln.y))
    return lines
