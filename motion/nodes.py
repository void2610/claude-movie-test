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
    parent: str | None = None
    text: float = 0.0   # この要素が直接描いた文字の最大の不透明度 (0 なら文字を描いていない)
    text_box: tuple[float, float, float, float] | None = None   # その文字の見えている範囲 (大文字の高さ・クリップ後)


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
        # 入れ子の要素: 親の名前と時刻 (子の時刻は親のずれも受ける)、親が記録中の子の一覧
        self._ids: list[tuple[str, float]] = []
        self._rec: list[list[Seen]] = []

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
        self._ids = []
        self._rec = []

    def parent(self) -> str | None:
        return self._ids[-1][0] if self._ids else None

    def base_t(self, t: float) -> float:
        return self._ids[-1][1] if self._ids and self._ids[-1][1] is not None else t

    @contextmanager
    def group(self, id: str, t: float | None):
        """記録を伴わない親 (2.5D のカードなど)。中で描かれた要素の親になり、時刻のずれを子へ渡す。"""
        self._ids.append((id, t))
        try:
            yield
        finally:
            self._ids.pop()

    def emit(self, s: Seen) -> None:
        """親が記録中ならその中の座標で親に預け、そうでなければ画面の座標として記録する。"""
        if self._rec:
            self._rec[-1].append(s)
        else:
            self.note(s)

    def note(self, s: Seen) -> None:
        # モーションブラーでは 1 フレームに数回描かれるので、範囲を合わせる
        if s.id in self.seen:
            a, b = self.seen[s.id].bounds, s.bounds
            s.bounds = (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))
            s.text = max(s.text, self.seen[s.id].text)
            s.text_box = _union(s.text_box, self.seen[s.id].text_box)
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
        self.t = edits.base_t(ctx.t) - edits.tr(id, "dt")
        self.props: dict[str, dict] = {}
        self.text = 0.0
        self.text_box: tuple[float, float, float, float] | None = None

    def prop(self, key: str, default: Any) -> Any:
        """スタジオから変えられる値。既定値の型で、文言・色・数値・真偽のどれかになる。"""
        v = self._e.prop(self.id, key, default)
        self.props[key] = {"type": _kind(default), "default": default, "value": v}
        return v


# 描いている途中の要素。文字を描く関数は、どの要素の中で描かれたかを知らないのでここで引く
_open: list[Node] = []


def _union(a, b):
    if a is None or b is None:
        return a or b
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def _clipped(c: skia.Canvas, r: skia.Rect) -> tuple[float, float, float, float] | None:
    r = skia.Rect.MakeLTRB(r.left(), r.top(), r.right(), r.bottom())
    if not r.intersect(skia.Rect.Make(c.getDeviceClipBounds())):
        return None
    return (r.left(), r.top(), r.right(), r.bottom())


def note_text(c: skia.Canvas, alpha: float, rect: tuple[float, float, float, float]) -> None:
    """描いている途中の要素が c に文字を描いたことを残す (review とスタジオが文字の重なりを見つけるため)。

    rect は文字の範囲 (c の座標)。今の変換とクリップを当てて、要素の記録の座標で持つ。
    """
    if not _open or alpha <= 0:
        return
    box = _clipped(c, c.getTotalMatrix().mapRect(skia.Rect.MakeLTRB(*rect)))
    if box is None:
        return
    n = _open[-1]
    n.text = max(n.text, alpha)
    n.text_box = _union(n.text_box, box)


def props(ctx, id: str) -> Node:
    """描画を囲まずに、要素の文言・色などの差分だけを読む (2.5D のカードの中身など)。"""
    return Node(None, ctx, id, edits_of(ctx.comp))


@contextmanager
def node(c: skia.Canvas, ctx, id: str, *, origin: tuple[float, float] = (0.0, 0.0), label: str | None = None,
         span: tuple[float, float] | None = None):
    """要素を名前付きで描く。origin は拡大縮小・回転の中心 (作品の座標)。span は出ている区間 (タイムライン用)。

    node の中で node を使うと入れ子になる。子は親の移動・拡大・回転・時刻のずれを受け、単独でも動かせる。
    """
    e = edits_of(ctx.comp)
    o = e.of(id)
    n = Node(c, ctx, id, e)
    parent = e.parent()
    if span:
        e.spans[id] = span
    e.labels[id] = label or id
    rec = skia.PictureRecorder()
    rc = rec.beginRecording(_BIG, skia.RTreeFactory()())
    n.c = rc
    children: list[Seen] = []
    e._ids.append((id, n.t))
    e._rec.append(children)
    _open.append(n)
    try:
        yield n
    finally:
        _open.pop()
        e._rec.pop()
        e._ids.pop()
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
    m = c.getTotalMatrix()
    cull = pic.cullRect()
    if cull.width() > 0 and cull.height() > 0 and cull.width() < 1e5:
        r = m.mapRect(cull)
        org = m.mapXY(ox, oy)
        tb = _clipped(c, m.mapRect(skia.Rect.MakeLTRB(*n.text_box))) if n.text_box else None
        e.emit(Seen(id, e.labels[id], (r.left(), r.top(), r.right(), r.bottom()), (org.x(), org.y()), n.props, span,
                    parent=parent, text=n.text * op if tb else 0.0, text_box=tb))
    # 子の範囲は親の記録の中の座標なので、親を描いた変換で写してから上へ渡す
    for ch in children:
        r = m.mapRect(skia.Rect.MakeLTRB(*ch.bounds))
        org = m.mapXY(*ch.origin)
        ch.bounds = (r.left(), r.top(), r.right(), r.bottom())
        ch.origin = (org.x(), org.y())
        if ch.text_box:
            ch.text_box = _clipped(c, m.mapRect(skia.Rect.MakeLTRB(*ch.text_box)))
            ch.text = ch.text if ch.text_box else 0.0
        e.emit(ch)
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
