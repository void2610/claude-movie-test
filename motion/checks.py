"""等倍の画素で確かめる検査。レビューで毎回実行し、1 つでも失敗したらレビュー全体を失敗にする。

ユーザーから見た目の指摘を受けたら、直す前にその症状を検査として作品に書き、失敗することを確かめてから直す。
作品が変わっても同じミスが再発しないようにするため。

    comp.checks.append(Check("HTTP API の合流区間は青", [7.6, 8.5], lambda img, ctx: ...))
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import cv2
import numpy as np

from .color import to_color


@dataclass
class Check:
    name: str
    times: list[float]
    # 等倍の RGB uint8 画像と ctx を受け取り、問題があれば説明の文字列 (無ければ None) を返す
    fn: Callable[[np.ndarray, object], str | None]


@dataclass
class Waiver:
    """自動検査の例外。理由が書けないなら例外にせず直す。"""
    rule: str          # "edge-clip" など
    reason: str
    times: tuple[float, float] = (0.0, 1e9)
    sides: tuple[str, ...] = ("left", "right", "top", "bottom")


@dataclass
class Finding:
    rule: str
    t: float
    detail: str
    crop: tuple[int, int, int, int] | None = None   # 問題箇所 (x, y, w, h) 等倍の座標
    waived: str | None = None


def is_color(rgb: np.ndarray, target: str, tol: float = 60.0) -> bool:
    """画素 (または画素群の中央値) が target の色に近いか。"""
    px = np.median(rgb.reshape(-1, 3), axis=0) if rgb.ndim > 1 else rgb
    want = np.array(to_color(target).rgba[:3]) * 255
    return float(np.linalg.norm(px.astype(float) - want)) < tol


def color_along(img: np.ndarray, pts: list[tuple[float, float]], target: str, tol: float = 70.0,
                min_ratio: float = 0.8, radius: int = 1) -> str | None:
    """点列の上の画素が target の色か。線の色が別の線に上書きされていないかを確かめるのに使う。"""
    h, w = img.shape[:2]
    want = np.array(to_color(target).rgba[:3]) * 255
    ok = 0
    n = 0
    for x, y in pts:
        xi, yi = int(round(x)), int(round(y))
        if not (0 <= xi < w and 0 <= yi < h):
            continue
        patch = img[max(yi - radius, 0):yi + radius + 1, max(xi - radius, 0):xi + radius + 1].reshape(-1, 3)
        d = np.linalg.norm(patch.astype(float) - want, axis=1).min()
        ok += d < tol
        n += 1
    if n == 0:
        return "検査する点が画面の外にある"
    if ok / n < min_ratio:
        return f"{target} の画素が {ok}/{n} 点しかない (期待 {min_ratio:.0%} 以上)"
    return None


def edge_clips(img: np.ndarray, band: int = 3, min_run: int = 12) -> list[tuple[str, int, int]]:
    """画面の縁で切れている要素 (文字・線・図形) を探す。返り値は (辺, 縁に沿った開始位置, 長さ)。

    背景 (縁の帯の中央値) との差が大きい画素が、縁から内側へ連続していて、縁に沿って min_run 画素以上続く所を
    「縁で切れた要素」とみなす。グレインや格子の点は短いので数えない。
    """
    g = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY).astype(np.int16)
    h, w = g.shape
    out = []
    sides = {
        "left": g[:, :band * 3].T, "right": g[:, -band * 3:][:, ::-1].T,
        "top": g[:band * 3, :], "bottom": g[-band * 3:, :][::-1, :],
    }
    for side, strip in sides.items():
        # strip[0] が最も外側の列 (行)。外側 band と、その内側 band の両方で背景と違う画素だけを残す
        bg = np.median(strip)
        ink = np.abs(strip - bg) > 45
        hit = ink[:band].all(axis=0) & ink[band:band * 2].any(axis=0)
        run = 0
        for i, v in enumerate(np.r_[hit, False]):
            if v:
                run += 1
            else:
                if run >= min_run:
                    out.append((side, i - run, run))
                run = 0
    return out
