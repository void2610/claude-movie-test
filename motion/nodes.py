"""スタジオで直接つかんで編集できる要素 (ノード)。

作品のコードは描く要素を名前付きで囲む。人間がスタジオで動かした結果は、要素の名前ごとの差分として
作品の edits.json に残る。コードは「何を描くか」、edits.json は「人間がどこをどう変えたか」を持つ。

    with node(c, ctx, "h2", origin=(x, y), label="見出し") as n:
        text.text(n.c, n.prop("text", "THREE WAYS IN."), x, y, color=n.prop("color", "#ECECEF"))
        # アニメーションは ctx.t ではなく n.t を使う (スタジオで出のタイミングをずらせるように)

2.5D のカードは persp.Card(id=...) で同じ差分 (dx, dy, dz, rot, scale, dt) を受ける。
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import skia

TRANSFORM_KEYS = ("dx", "dy", "dz", "scale", "rot", "opacity", "dt", "hidden")
_BIG = skia.Rect.MakeLTRB(-1e6, -1e6, 1e6, 1e6)


def _kind(v: Any) -> str:
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "number"
    if isinstance(v, str) and v.startswith("#") and len(v) in (4, 7, 9):
        return "color"
    return "text"


@dataclass
class Seen:
    """あるフレームで描かれた要素。bounds は出力画像の画素座標 (左, 上, 右, 下)。"""
    id: str
    label: str
    bounds: tuple[float, float, float, float]
    origin: tuple[float, float]
    props: dict[str, dict] = field(default_factory=dict)
    span: tuple[float, float] | None = None
    space: str = "2d"


class Edits:
    def __init__(self, path: Path | None):
        self.path = path
        self.data: dict[str, dict] = {}
        if path and path.exists():
            try:
                self.data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                self.data = {}
        self.seen: dict[str, Seen] = {}
        self.spans: dict[str, tuple[float, float]] = {}
        self.labels: dict[str, str] = {}

    def of(self, id: str) -> dict:
        return self.data.get(id, {})

    def tr(self, id: str, key: str, default: float = 0.0) -> float:
        return self.of(id).get(key, default)

    def t(self, id: str, t: float) -> float:
        return t - self.tr(id, "dt")

    def prop(self, id: str, key: str, default: Any) -> Any:
        return self.of(id).get("props", {}).get(key, default)

    def begin_frame(self) -> None:
        self.seen = {}

    def note(self, s: Seen) -> None:
        # モーションブラーでは 1 フレームに数回描かれるので、範囲を合わせる
        if s.id in self.seen:
            a, b = self.seen[s.id].bounds, s.bounds
            s.bounds = (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))
        self.seen[s.id] = s


def edits_of(comp) -> Edits:
    e = getattr(comp, "_edits", None)
    if e is None:
        path = Path(comp.project_dir) / "edits.json" if getattr(comp, "project_dir", None) else None
        e = Edits(path)
        comp._edits = e
    return e


class Node:
    def __init__(self, c: skia.Canvas, ctx, id: str, edits: Edits):
        self.c = c
        self.ctx = ctx
        self.id = id
        self._e = edits
        self.t = edits.t(id, ctx.t)
        self.props: dict[str, dict] = {}

    def prop(self, key: str, default: Any) -> Any:
        """スタジオから変えられる値。既定値の型で、文言・色・数値・真偽のどれかになる。"""
        v = self._e.prop(self.id, key, default)
        self.props[key] = {"type": _kind(default), "default": default, "value": v}
        return v


def props(ctx, id: str) -> Node:
    """描画を囲まずに、要素の文言・色などの差分だけを読む (2.5D のカードの中身など)。"""
    return Node(None, ctx, id, edits_of(ctx.comp))


@contextmanager
def node(c: skia.Canvas, ctx, id: str, *, origin: tuple[float, float] = (0.0, 0.0), label: str | None = None,
         span: tuple[float, float] | None = None):
    """要素を名前付きで描く。origin は拡大縮小・回転の中心 (作品の座標)。span は出ている区間 (タイムライン用)。"""
    e = edits_of(ctx.comp)
    o = e.of(id)
    n = Node(c, ctx, id, e)
    if span:
        e.spans[id] = span
    e.labels[id] = label or id
    rec = skia.PictureRecorder()
    rc = rec.beginRecording(_BIG, skia.RTreeFactory()())
    n.c = rc
    yield n
    pic = rec.finishRecordingAsPicture()
    if o.get("hidden"):
        return
    c.save()
    ox, oy = origin
    c.translate(ox + o.get("dx", 0.0), oy + o.get("dy", 0.0))
    if o.get("rot"):
        c.rotate(o["rot"])
    s = o.get("scale", 1.0)
    c.scale(s, s)
    c.translate(-ox, -oy)
    op = o.get("opacity", 1.0)
    if op < 1.0:
        c.saveLayerAlpha(None, int(round(max(op, 0.0) * 255)))
    c.drawPicture(pic)
    if op < 1.0:
        c.restore()
    cull = pic.cullRect()
    if cull.width() > 0 and cull.height() > 0 and cull.width() < 1e5:
        r = c.getTotalMatrix().mapRect(cull)
        m = c.getTotalMatrix()
        org = m.mapXY(ox, oy)
        e.note(Seen(id, e.labels[id], (r.left(), r.top(), r.right(), r.bottom()), (org.x(), org.y()), n.props, span))
    c.restore()


def save(path: str | Path, id: str, updates: dict[str, Any]) -> dict:
    """edits.json の要素 id に差分を書く。値に None を渡すとその差分を消す。props は入れ子で渡す。"""
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    cur = data.get(id, {})
    for k, v in updates.items():
        if k == "props":
            props = cur.get("props", {})
            for pk, pv in v.items():
                if pv is None:
                    props.pop(pk, None)
                else:
                    props[pk] = pv
            if props:
                cur["props"] = props
            else:
                cur.pop("props", None)
        elif v is None:
            cur.pop(k, None)
        else:
            cur[k] = v
    if cur:
        data[id] = cur
    else:
        data.pop(id, None)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return data
