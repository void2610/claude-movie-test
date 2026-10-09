"""質感: 紙、ハーフトーン、印刷のずれ。"""
from __future__ import annotations

import math
from functools import lru_cache

import cv2
import numpy as np
import skia

from .color import to_color
from .noise import fbm3


@lru_cache(maxsize=8)
def _paper_rgb(w: int, h: int, tone: str, crumple: float, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    # 折り目: ランダムな直線に沿った稜線と谷を重ねた高さ場を作り、斜めの光で陰影にする
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    height = np.zeros((h, w), np.float32)
    s = max(w, h) / 1920
    # 細い折り目をたくさん。各折り目は端に向かって弱まる線分にして、紙全体を横切る直線にしない
    for _ in range(int(60 * crumple) + 4):
        a = rng.uniform(0, math.pi)
        px, py = rng.uniform(0, w), rng.uniform(0, h)
        along = (xx - px) * math.cos(a) + (yy - py) * math.sin(a)
        d = (xx - px) * math.sin(a) - (yy - py) * math.cos(a)
        length = rng.uniform(200, 900) * s
        width = rng.uniform(6, 40) * s
        fade = np.exp(-(along / length) ** 2)
        height += rng.choice([-1, 1]) * np.exp(-np.abs(d) / width) * fade * rng.uniform(0.2, 0.7)
    height = cv2.GaussianBlur(height, (0, 0), 2.0 * s + 0.5)
    gx, gy = np.meshgrid(np.linspace(0, 6 * w / 1920, w), np.linspace(0, 6 * h / 1920, h))
    height += 0.35 * fbm3(gx, gy, np.full_like(gx, seed * 0.1), octaves=4, seed=seed).astype(np.float32)
    nx = cv2.Sobel(height, cv2.CV_32F, 1, 0, ksize=5) / (8 * s)
    ny = cv2.Sobel(height, cv2.CV_32F, 0, 1, ksize=5) / (8 * s)
    shade = np.clip(1 + (-nx * 0.6 - ny * 0.8) * crumple * 0.35, 0.78, 1.08)
    # 繊維: 細かいノイズを横に少し伸ばす
    fiber = rng.normal(0, 1, (h, w)).astype(np.float32)
    fiber = cv2.GaussianBlur(fiber, (0, 0), sigmaX=1.6 * s + 0.3, sigmaY=0.6 * s + 0.2)
    base = np.array(to_color(tone).rgba[:3], np.float32)
    rgb = base[None, None, :] * shade[..., None] * (1 + fiber[..., None] * 0.035)
    return (np.clip(rgb, 0, 1) * 255).astype(np.uint8)


def paper_image(w: int, h: int, tone: str = "#EDE6D6", crumple: float = 0.6, seed: int = 0) -> skia.Image:
    rgb = _paper_rgb(int(w), int(h), tone, crumple, seed)
    rgba = np.dstack([rgb, np.full(rgb.shape[:2], 255, np.uint8)])
    return skia.Image.fromarray(np.ascontiguousarray(rgba), colorType=skia.kRGBA_8888_ColorType)


def paper(c: skia.Canvas, ctx, tone: str = "#EDE6D6", crumple: float = 0.6, seed: int = 0, scale: float = 0.5) -> None:
    """くしゃっとした紙で画面を塗る。scale は紙を作る解像度 (低いほど速い。紙は低周波なので 0.5 で十分)。"""
    img = paper_image(ctx.W * scale, ctx.H * scale, tone, crumple, seed)
    c.drawImageRect(img, skia.Rect.MakeWH(ctx.W, ctx.H), skia.SamplingOptions(skia.FilterMode.kLinear))


def _v(x, ctx):
    return x(ctx) if callable(x) else x


def halftone(cell: float = 9.0, angle: float = 22.0, amount=1.0, ink=(0.08, 0.08, 0.1)):
    """明るさを網点に置き換える。amount は元の画像との混ぜ具合 (0〜1)。"""
    ink_c = np.array(ink, np.float32)

    def fx(img, ctx):
        a = _v(amount, ctx)
        if a <= 0:
            return img
        h, w = img.shape[:2]
        k = h / 1080
        cs = max(cell * k, 2.0)
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        ca, sa = math.cos(math.radians(angle)), math.sin(math.radians(angle))
        u, v = (xx * ca + yy * sa) / cs, (-xx * sa + yy * ca) / cs
        du, dv = u - np.floor(u) - 0.5, v - np.floor(v) - 0.5
        dist = np.sqrt(du * du + dv * dv)
        luma = cv2.blur(img @ np.array([0.2126, 0.7152, 0.0722], np.float32), (max(int(cs), 1),) * 2)
        r = np.sqrt(np.clip(1 - luma, 0, 1)) * 0.62
        edge = 1.2 / cs
        dot = np.clip((r - dist) / edge + 0.5, 0, 1)[..., None]
        paper_c = img.max(axis=2, keepdims=True) * 0 + 0.97
        out = paper_c * (1 - dot) + ink_c * dot
        return img * (1 - a) + out * a
    fx.space = "display"
    return fx


def misregister(amount=3.0, angle: float = -35.0):
    """印刷の版ずれ。赤の版と青の版を逆向きにずらす。amount は 1080p 基準の画素で、関数で衝撃の時だけ増やせる。"""
    def fx(img, ctx):
        a = _v(amount, ctx) * img.shape[0] / 1080
        if abs(a) < 0.25:
            return img
        dx, dy = a * math.cos(math.radians(angle)), a * math.sin(math.radians(angle))
        h, w = img.shape[:2]
        out = img.copy()
        for ch, sgn in ((0, 1), (2, -1)):
            M = np.float32([[1, 0, dx * sgn], [0, 1, dy * sgn]])
            out[..., ch] = cv2.warpAffine(img[..., ch], M, (w, h), borderMode=cv2.BORDER_REFLECT)
        return out
    fx.space = "display"
    return fx
