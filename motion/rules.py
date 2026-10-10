"""動きのルール。要素の種類ごとに入り方・抜け方・尺を決めておき、作品の中で場当たり的に曲線を作らない。

    from motion import rules
    p = rules.enter("panel", ctx.t, t0)        # 0→1 (ばねの種類は行き過ぎることがある)
    q = rules.leave("panel", ctx.t, t1)        # 1→0。抜けは入りの 6 割の長さ
    hold = rules.read_time("One command.")     # この文字列を読ませるのに要る秒数

値の出典は Knowledge/motion-skill-rules.md。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from . import easing
from .anim import clamp, spring

# 方向ごとのイージング。登場は減速、退場は加速、画面内の移動は加減速、値が着地する時だけ少し行き過ぎる
ENTER = easing.cubic_bezier(0.16, 1.0, 0.3, 1.0)
EXIT = easing.cubic_bezier(0.6, 0.0, 0.9, 0.35)
MOVE = easing.cubic_bezier(0.65, 0.0, 0.35, 1.0)
LAND = easing.cubic_bezier(0.55, 0.0, 0.2, 1.12)


@dataclass(frozen=True)
class Rule:
    dur: float                       # 入りの長さ (秒)。ばねの場合は収束の目安
    ease: easing.Ease | None = None  # ベジェで動かす場合
    freq: float | None = None        # ばねで動かす場合の固有振動数 (Hz)
    damping: float | None = None     # ばねの減衰比 (1 で行き過ぎなし)
    from_scale: float = 0.94         # 入りの開始時の大きさ (0 から拡大しない)


def _k(stiffness: float, damping: float, mass: float = 1.0) -> tuple[float, float]:
    """stiffness / damping 表記のばねを、固有振動数 (Hz) と減衰比に直す。"""
    w = math.sqrt(stiffness / mass)
    return w / (2 * math.pi), damping / (2 * math.sqrt(stiffness * mass))


RULES: dict[str, Rule] = {
    # 小さな UI の反応: 速く、ほぼ行き過ぎない
    "micro": Rule(0.2, ENTER, from_scale=0.97),
    "ui": Rule(0.35, None, *_k(320, 30), from_scale=0.96),
    # パネル・カード: 制御された収まり
    "panel": Rule(0.7, None, *_k(170, 26)),
    # 見出し・ロゴ: 強く入って、行き過ぎずに止まる
    "headline": Rule(0.5, None, *_k(120, 24), from_scale=0.92),
    # マスコットなど遊びのある要素: はっきり跳ねる (1 本に多用しない)
    "playful": Rule(0.9, None, *_k(180, 12), from_scale=0.9),
    # カメラ: ほとんど気づかれないほど滑らか
    "camera": Rule(2.4, easing.inout_sine, from_scale=1.0),
    # 画面内の移動
    "move": Rule(0.6, MOVE, from_scale=1.0),
}


def rule(kind: str) -> Rule:
    if kind not in RULES:
        raise KeyError(f"動きの種類 {kind!r} は無い。使えるのは {list(RULES)}")
    return RULES[kind]


def enter(kind: str, t: float, t0: float, dur: float | None = None) -> float:
    """t0 から入る要素の進み具合 (0→1)。ばねの種類は 1 を少し超えることがある。"""
    r = rule(kind)
    if r.freq is not None:
        return spring(t, t0, r.freq, r.damping)
    d = dur or r.dur
    return r.ease(clamp((t - t0) / d)) if t > t0 else 0.0


def leave(kind: str, t: float, t1: float, dur: float | None = None) -> float:
    """t1 までに抜ける要素の残り具合 (1→0)。抜けは入りの 6 割の長さで、加速して去る。"""
    d = (dur or rule(kind).dur) * 0.6
    return 1.0 - EXIT(clamp((t - (t1 - d)) / d))


def _speed(kind: str, t0: float, dur: float | None) -> tuple[list[float], list[float]]:
    span = (dur or rule(kind).dur) * 3
    ts = [t0 + span * i / 3000 for i in range(3001)]
    xs = [enter(kind, t, t0, dur) for t in ts]
    return ts[1:], [abs(b - a) for a, b in zip(xs, xs[1:])]


def peak_time(kind: str, t0: float, dur: float | None = None) -> float:
    """t0 から入る要素が最も速く動く時刻。風切り音 (Cue の move) はここに置く。"""
    ts, v = _speed(kind, t0, dur)
    return ts[max(range(len(v)), key=v.__getitem__)]


def land_time(kind: str, t0: float, dur: float | None = None, frac: float = 0.05) -> float:
    """t0 から入る要素が止まる時刻 (速さが最大の frac 未満に落ちきる)。着地の音 (Cue の land) はここに置く。"""
    ts, v = _speed(kind, t0, dur)
    vmax = max(v)
    i = max(i for i, x in enumerate(v) if x >= vmax * frac)
    return ts[i]


def scale_in(kind: str, p: float) -> float:
    """入りの進み具合から大きさを出す。0 からではなく from_scale から 1 へ。"""
    s0 = rule(kind).from_scale
    return s0 + (1 - s0) * p


def read_time(s: str) -> float:
    """文字列を読ませるのに要る最低の表示時間 (秒)。日本語は 1 文字を英字 2 文字分として数える。"""
    n = sum(2 if ord(ch) > 0x2E80 else 1 for ch in s.strip())
    return max(0.7, 0.25 + n / 17)


def stagger(i: int, n: int, t0: float, gap: float = 0.08, total: float = 0.5) -> float:
    """n 個の兄弟要素の i 番目の開始時刻。間隔は gap だが、全体が total を超えないよう詰める。"""
    g = min(gap, total / max(n - 1, 1))
    return t0 + i * g
