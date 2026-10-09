"""2.5D: 平面 (カード) を 3D 空間に置き、遠近のあるカメラで写す。

座標は x 右・y 下・z 奥 (画面の向こう) で、単位は画素。既定のカメラでは z=0 の平面がちょうど 1:1 に写るので、
回転させないカードは普通の 2D と同じ位置・大きさに見える。

    cam = Camera.default(ctx).orbit(yaw=tween(ctx.t, 0, 2, -20, 0))
    draw_cards(c, cam, [Card((ctx.CX, ctx.CY, 0), (800, 500), rot=(0, 15, 0), draw=ui_panel)])
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Callable

import numpy as np
import skia

Vec = tuple[float, float, float]


def _rot(yaw: float, pitch: float, roll: float) -> np.ndarray:
    """度で与えた回転 (y 軸まわり → x 軸まわり → z 軸まわり) の行列。"""
    y, p, r = (math.radians(a) for a in (yaw, pitch, roll))
    Ry = np.array([[math.cos(y), 0, math.sin(y)], [0, 1, 0], [-math.sin(y), 0, math.cos(y)]])
    Rx = np.array([[1, 0, 0], [0, math.cos(p), -math.sin(p)], [0, math.sin(p), math.cos(p)]])
    Rz = np.array([[math.cos(r), -math.sin(r), 0], [math.sin(r), math.cos(r), 0], [0, 0, 1]])
    return Ry @ Rx @ Rz


@dataclass(frozen=True)
class Camera:
    pos: Vec
    target: Vec
    fov: float          # 縦の画角 (度)
    cx: float           # 画面の中心
    cy: float
    roll: float = 0.0

    @classmethod
    def default(cls, ctx, fov: float = 38.0) -> Camera:
        """z=0 の平面がちょうど 1:1 の画素で写る位置に置いたカメラ。"""
        d = (ctx.H / 2) / math.tan(math.radians(fov) / 2)
        return cls((ctx.CX, ctx.CY, -d), (ctx.CX, ctx.CY, 0.0), fov, ctx.CX, ctx.CY)

    @property
    def focal(self) -> float:
        return self.cy / math.tan(math.radians(self.fov) / 2)

    def orbit(self, yaw: float = 0.0, pitch: float = 0.0) -> Camera:
        """注視点を中心に回り込む (度)。"""
        off = np.subtract(self.pos, self.target)
        p = np.asarray(self.target) + _rot(yaw, pitch, 0) @ off
        return replace(self, pos=tuple(p))

    def dolly(self, k: float) -> Camera:
        """注視点との距離を k 倍にする (1 未満で寄る)。"""
        off = np.subtract(self.pos, self.target) * k
        return replace(self, pos=tuple(np.asarray(self.target) + off))

    def pan(self, dx: float = 0.0, dy: float = 0.0) -> Camera:
        return replace(self, pos=(self.pos[0] + dx, self.pos[1] + dy, self.pos[2]),
                       target=(self.target[0] + dx, self.target[1] + dy, self.target[2]))

    def basis(self) -> np.ndarray:
        f = np.subtract(self.target, self.pos)
        f = f / np.linalg.norm(f)
        up = np.array([0.0, 1.0, 0.0])
        r = np.cross(up, f)
        if np.linalg.norm(r) < 1e-6:
            r = np.array([1.0, 0.0, 0.0])
        r = r / np.linalg.norm(r)
        u = np.cross(f, r)
        if self.roll:
            c, s = math.cos(math.radians(self.roll)), math.sin(math.radians(self.roll))
            r, u = r * c + u * s, u * c - r * s
        return np.stack([r, u, f])

    def project(self, pts: np.ndarray) -> np.ndarray:
        """(N, 3) の点を (N, 3) = (画面 x, 画面 y, 奥行き) に写す。奥行きが正なら前方。"""
        rel = np.asarray(pts, float) - np.asarray(self.pos)
        v = rel @ self.basis().T
        z = v[:, 2]
        f = self.focal
        safe = np.where(np.abs(z) < 1e-6, 1e-6, z)
        return np.stack([self.cx + v[:, 0] * f / safe, self.cy + v[:, 1] * f / safe, z], 1)


@dataclass
class Card:
    center: Vec
    size: tuple[float, float]
    rot: Vec = (0.0, 0.0, 0.0)          # (yaw, pitch, roll) 度
    draw: Callable[[skia.Canvas], None] | None = None   # (0, 0)〜(w, h) の座標で中身を描く
    fill: int | None = None              # 背景色 (skia の色)
    radius: float = 0.0
    shade: float = 0.35                  # 面がカメラから逸れるほど暗くする強さ
    two_sided: bool = False
    shadow: float = 0.0                  # 影のぼかし量 (0 で無し)
    meta: dict = field(default_factory=dict)

    def corners(self) -> np.ndarray:
        w, h = self.size
        local = np.array([[-w / 2, -h / 2, 0], [w / 2, -h / 2, 0], [w / 2, h / 2, 0], [-w / 2, h / 2, 0]], float)
        return local @ _rot(*self.rot).T + np.asarray(self.center)

    def normal(self) -> np.ndarray:
        return _rot(*self.rot) @ np.array([0.0, 0.0, -1.0])


def draw_cards(c: skia.Canvas, cam: Camera, cards: list[Card], near: float = 10.0) -> None:
    """カードを奥から順に描く。カメラの後ろにはみ出すカードは描かない。"""
    items = []
    for card in cards:
        q = cam.project(card.corners())
        if (q[:, 2] < near).any():
            continue
        items.append((q[:, 2].mean(), card, q))
    for _, card, q in sorted(items, key=lambda x: -x[0]):
        _draw_card(c, cam, card, q)


def _draw_card(c: skia.Canvas, cam: Camera, card: Card, q: np.ndarray) -> None:
    w, h = card.size
    # 2D の符号付き面積が負なら裏面がこちらを向いている
    area = sum(q[i, 0] * q[(i + 1) % 4, 1] - q[(i + 1) % 4, 0] * q[i, 1] for i in range(4))
    back = area < 0
    if back and not card.two_sided:
        return
    m = skia.Matrix()
    src = [skia.Point(0, 0), skia.Point(w, 0), skia.Point(w, h), skia.Point(0, h)]
    dst = [skia.Point(float(x), float(y)) for x, y in q[:, :2]]
    if not m.setPolyToPoly(src, dst):
        return
    rr = skia.RRect.MakeRectXY(skia.Rect.MakeWH(w, h), card.radius, card.radius)
    if card.shadow > 0:
        sp = skia.Paint(AntiAlias=True, Color=skia.Color(0, 0, 0, 110))
        sp.setMaskFilter(skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, card.shadow))
        c.save()
        c.concat(m)
        c.drawRRect(rr.makeOffset(0, card.shadow * 0.6), sp)
        c.restore()
    c.save()
    c.concat(m)
    c.clipRRect(rr, skia.ClipOp.kIntersect, True)
    if card.fill is not None:
        c.drawRRect(rr, skia.Paint(AntiAlias=True, Color=card.fill))
    if card.draw:
        card.draw(c)
    if card.shade > 0:
        view = np.subtract(cam.pos, card.center)
        view = view / np.linalg.norm(view)
        facing = abs(float(np.dot(card.normal(), view)))
        dark = card.shade * (1 - facing)
        if dark > 0.003:
            c.drawRect(skia.Rect.MakeWH(w, h), skia.Paint(Color=skia.Color(0, 0, 0, int(255 * min(dark, 1)))))
    c.restore()


def grid_floor(c: skia.Canvas, cam: Camera, y: float, *, extent: float = 4000, step: float = 160,
               color: int = skia.Color(255, 255, 255, 40), z0: float = -500) -> None:
    """y の高さにある床の格子。奥へ行くほど細く薄くなる。"""
    p = skia.Paint(AntiAlias=True, Color=color, StrokeWidth=1.2, Style=skia.Paint.kStroke_Style)
    xs = np.arange(cam.target[0] - extent, cam.target[0] + extent + 1, step)
    zs = np.arange(z0, z0 + extent * 2 + 1, step)
    for x in xs:
        _line3(c, cam, (x, y, zs[0]), (x, y, zs[-1]), p)
    for z in zs:
        _line3(c, cam, (xs[0], y, z), (xs[-1], y, z), p)


def _line3(c, cam, a, b, paint, near=10.0):
    pa, pb = np.asarray(a, float), np.asarray(b, float)
    qa, qb = cam.project(np.stack([pa, pb]))
    if qa[2] < near and qb[2] < near:
        return
    # カメラの手前で切る (後ろに回った端点を投影すると反転する)
    if qa[2] < near or qb[2] < near:
        ta = (near - qa[2]) / (qb[2] - qa[2])
        cut = pa + (pb - pa) * ta
        if qa[2] < near:
            pa = cut
        else:
            pb = cut
        qa, qb = cam.project(np.stack([pa, pb]))
    c.drawLine(float(qa[0]), float(qa[1]), float(qb[0]), float(qb[1]), paint)
