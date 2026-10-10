from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import skia

from .color import Color, to_color
from .timeline import Timeline


@dataclass
class Ctx:
    """描画関数に渡る、ある時刻の情報。"""

    t: float
    frame: float
    comp: Composition
    start: float = 0.0
    end: float = 0.0

    @property
    def lt(self) -> float:
        return self.t - self.start

    @property
    def dur(self) -> float:
        return self.end - self.start

    @property
    def p(self) -> float:
        return self.lt / self.dur if self.dur > 0 else 0.0

    @property
    def tl(self) -> Timeline:
        return self.comp.timeline

    @property
    def W(self) -> int:
        return self.comp.width

    @property
    def H(self) -> int:
        return self.comp.height

    @property
    def CX(self) -> float:
        return self.comp.width / 2

    @property
    def CY(self) -> float:
        return self.comp.height / 2

    @property
    def cues(self) -> list[float]:
        return self.comp.cues


class Scene:
    """[start, end) の間だけ描画されるレイヤー。サブクラスで draw を実装する。"""

    start: float = 0.0
    end: float | None = None
    z: int = 0
    # True ならカメラの変換 (揺れ・ズーム) を受けない。HUD 等に使う
    fixed: bool = False

    def __init__(self, start: float | None = None, end: float | None = None, z: int | None = None,
                 fixed: bool | None = None):
        if start is not None:
            self.start = start
        if end is not None:
            self.end = end
        if z is not None:
            self.z = z
        if fixed is not None:
            self.fixed = fixed
        self._ready = False

    def setup(self, comp: Composition) -> None:
        """重い前計算 (シミュレーション・キャッシュ読み込み等) をワーカーごとに一度だけ行う。"""

    def alpha(self, ctx: Ctx) -> float:
        return 1.0

    def draw(self, c: skia.Canvas, ctx: Ctx) -> None:
        raise NotImplementedError

    def span(self, comp: Composition) -> tuple[float, float]:
        return self.start, comp.duration if self.end is None else self.end

    def active(self, t: float, comp: Composition) -> bool:
        s, e = self.span(comp)
        return s <= t < e and not any(a <= t < b for a, b in getattr(self, "hidden", ()))

    def hide(self, start: float, end: float) -> None:
        """この区間はレンダラから直接は描かない (トランジションが代わりに描く)。"""
        if not hasattr(self, "hidden"):
            self.hidden = []
        self.hidden.append((start, end))

    def ensure_setup(self, comp: Composition) -> None:
        if not self._ready:
            self.setup(comp)
            self._ready = True


class FnScene(Scene):
    def __init__(self, fn: Callable[[skia.Canvas, Ctx], None], start: float, end: float | None, z: int,
                 alpha: Callable[[Ctx], float] | None = None, fixed: bool = False):
        super().__init__(start, end, z, fixed)
        self.fn = fn
        self._alpha = alpha
        self.__name__ = getattr(fn, "__name__", "scene")

    def alpha(self, ctx: Ctx) -> float:
        return self._alpha(ctx) if self._alpha else 1.0

    def draw(self, c: skia.Canvas, ctx: Ctx) -> None:
        self.fn(c, ctx)


def scene(start: float = 0.0, end: float | None = None, z: int = 0, alpha: Callable[[Ctx], float] | None = None,
          fixed: bool = False):
    """関数を Scene にするデコレータ。`@scene(0, 2)` のように使う。"""
    def deco(fn: Callable[[skia.Canvas, Ctx], None]) -> FnScene:
        return FnScene(fn, start, end, z, alpha, fixed)
    return deco


def paint_scene(c: skia.Canvas, s: Scene, t: float, frame: float, comp: Composition) -> None:
    """シーン 1 つを時刻 t で描く (不透明度を含む)。カメラはかけない。"""
    s.ensure_setup(comp)
    st, en = s.span(comp)
    ctx = Ctx(t, frame, comp, st, en)
    a = s.alpha(ctx)
    if a <= 0.0:
        return
    if a < 1.0:
        c.saveLayerAlpha(None, int(round(a * 255)))
    s.draw(c, ctx)
    if a < 1.0:
        c.restore()


PostFx = Callable[[Any, Ctx], Any]

CUE_KINDS = ("cut", "move", "land", "appear")


class Cue(float):
    """秒としてそのまま使えるキュー。kind を付けると、review が書き出した絵の動きと照らし合わせる。

    cut は画面全体が変わるコマ、move は動きが最も速いコマ、land は動きが止まるコマ、appear は要素が出るコマ。
    hero は約 4 秒に 1 つの見せ場 (重ねた打撃音を置き、検査も厳しくする)。
    """
    kind: str | None
    hero: bool
    name: str

    def __new__(cls, t: float, kind: str | None = None, hero: bool = False, name: str = ""):
        if kind not in (None, *CUE_KINDS):
            raise ValueError(f"kind は {CUE_KINDS} のどれか: {kind}")
        obj = super().__new__(cls, t)
        obj.kind, obj.hero, obj.name = kind, hero, name
        return obj

    def __reduce__(self):
        return (Cue, (float(self), self.kind, self.hero, self.name))

    def __repr__(self) -> str:
        return f"Cue({float(self):.3f}, {self.kind!r}{', hero=True' if self.hero else ''})"


@dataclass
class Composition:
    width: int = 1920
    height: int = 1080
    fps: int = 60
    duration: float = 10.0
    bpm: float = 120.0
    beat_offset: float = 0.0
    background: Color | str = "#0C0C0F"
    scenes: list[Scene] = field(default_factory=list)
    post: list[PostFx] = field(default_factory=list)
    # 全シーン共通のカメラ (揺れ・ズーム等)。canvas に変換をかける関数
    camera: Callable[[skia.Canvas, Ctx], None] | None = None
    # モーションブラーのサブフレーム数。時刻ごとに変えたい場合は関数を渡す
    motion_blur: int | Callable[[float], int] = 1
    shutter: float = 0.5
    # サブフレームの平均と光学系のポスト処理をリニア空間で行う (明るい物のブラーや bloom が濁らない)
    linear: bool = True
    # 映像と音で共有する衝撃のタイミング (秒か Cue)
    cues: list[float] = field(default_factory=list)
    # 意図した無音の区間 [(開始, 終了)]。review の無音の検査から外す
    silence_ok: list = field(default_factory=list)
    # comp を受け取り wav のパスを返す関数
    audio: Callable[[Composition], str] | None = None
    # レンダリング前にメインプロセスで一度だけ走らせる準備 (Blender のプレート生成等)
    prepare: list[Callable[[Composition], None]] = field(default_factory=list)
    name: str = "untitled"
    build_dir: str = "build"
    # ショットリスト (shots.ShotList)。レビューのシートはこれに沿ってコマを選ぶ
    shots: Any = None
    # 最初と最後のコマが一致するべきループ作品か (レビューで差を測る)
    loop: bool = False
    # 等倍の画素で確かめる作品ごとの検査 (checks.Check) と、自動検査の例外 (checks.Waiver)
    checks: list = field(default_factory=list)
    waivers: list = field(default_factory=list)
    # スタジオから調整できるパラメータ (tune.Tune)
    tune: Any = None

    def __post_init__(self):
        self.background = to_color(self.background)

    @property
    def timeline(self) -> Timeline:
        return Timeline(self.bpm, self.beat_offset)

    @property
    def nframes(self) -> int:
        return int(round(self.duration * self.fps))

    def add(self, *scenes: Scene) -> Composition:
        self.scenes.extend(scenes)
        return self

    def subframes(self, t: float) -> int:
        mb = self.motion_blur
        return max(1, int(mb(t) if callable(mb) else mb))
