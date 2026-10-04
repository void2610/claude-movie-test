from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import skia
import uharfbuzz as hb

from .color import Color
from .draw import paint as make_paint

FONTS_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
ALIASES = {
    "sans": "MonaSans-VF.ttf",
    "sans-mono": "MonaSansMono-VF.ttf",
    "mono": "FragmentMono-Regular.ttf",
}

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

    def _key(self, axes: Axes) -> tuple:
        # 軸の値を丸めてキャッシュを効かせる (0.5 単位の差は見た目に出ない)
        return tuple(sorted((k, round(v * 2) / 2) for k, v in (axes or {}).items()))

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

    def skfont(self, size: float, axes: Axes = None) -> skia.Font:
        f = skia.Font(self._typeface(self._key(axes)), size)
        f.setSubpixel(True)
        f.setEdging(skia.Font.Edging.kSubpixelAntiAlias)
        f.setHinting(skia.FontHinting.kNone)
        return f

    def metrics(self, size: float, axes: Axes = None) -> skia.FontMetrics:
        return self.skfont(size, axes).getMetrics()

    def shape(self, s: str, size: float, axes: Axes = None, tracking: float = 0.0,
              features: dict | None = None) -> Shaped:
        key = self._key(axes)
        buf = hb.Buffer()
        buf.add_str(s)
        buf.guess_segment_properties()
        hb.shape(self._hb_font(key), buf, features or {"kern": True, "liga": True})
        k = size / self.upem
        glyphs, xs, ys, adv, clusters = [], [], [], [], []
        pen = 0.0
        for info, p in zip(buf.glyph_infos, buf.glyph_positions):
            glyphs.append(info.codepoint)
            clusters.append(info.cluster)
            xs.append(pen + p.x_offset * k)
            ys.append(-p.y_offset * k)
            a = p.x_advance * k + tracking * size
            adv.append(a)
            pen += a
        width = pen - (tracking * size if glyphs else 0.0)
        return Shaped(self, s, size, axes, glyphs, xs, ys, adv, clusters, width)


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

    @property
    def skfont(self) -> skia.Font:
        return self.font.skfont(self.size, self.axes)

    @property
    def cap_height(self) -> float:
        m = self.font.metrics(self.size, self.axes)
        return m.fCapHeight or self.size * 0.7

    def blob(self, indices: list[int] | None = None) -> skia.TextBlob | None:
        idx = range(len(self.glyphs)) if indices is None else indices
        g = [self.glyphs[i] for i in idx]
        if not g:
            return None
        b = skia.TextBlobBuilder()
        b.allocRunPos(self.skfont, g, [skia.Point(self.xs[i], self.ys[i]) for i in idx])
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
        f = self.skfont
        for g, x, y in zip(self.glyphs, self.xs, self.ys):
            gp = f.getPath(g)
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


def shape(s: str, font: str = "sans", size: float = 100.0, axes: Axes = None, tracking: float = 0.0) -> Shaped:
    return get_font(font).shape(s, size, axes, tracking)


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
        c.drawTextBlob(blob, ox, oy, paint or make_paint(color, alpha=alpha, **paint_kw))
    return sh


def fit_size(s: str, width: float, font: str = "sans", axes: Axes = None, tracking: float = 0.0) -> float:
    w = shape(s, font, 100.0, axes, tracking).width
    return 100.0 * width / w if w > 0 else 100.0
