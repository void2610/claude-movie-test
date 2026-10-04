"""float32 の RGB 画像 (H, W, 3)・値域 0〜1 に作用するポスト処理。

各関数はエフェクト `fx(img, ctx) -> img` を返す。数値の引数には ctx を受け取る関数も渡せる。
ピクセル単位の量は 1080p 基準で指定し、解像度に合わせて自動で拡縮する。
"""
from __future__ import annotations

import math

import cv2
import numpy as np

from .anim import impact


def _v(x, ctx):
    return x(ctx) if callable(x) else x


def _k(img) -> float:
    return img.shape[0] / 1080.0


def bloom(threshold=0.75, strength=0.6, radius=24.0, knee=0.15):
    def fx(img, ctx):
        s = _v(strength, ctx)
        if s <= 0:
            return img
        th = _v(threshold, ctx)
        luma = img @ np.array([0.2126, 0.7152, 0.0722], np.float32)
        w = np.clip((luma - th + knee) / (2 * knee), 0, 1)[..., None]
        bright = img * w
        r = _v(radius, ctx) * _k(img)
        acc = np.zeros_like(img)
        h, wdt = img.shape[:2]
        small = bright
        # 解像度を落としながら重ねると、広い半径のグローを安く作れる
        for i in range(4):
            sigma = max(r * (0.5 ** (3 - i)) / (2 ** i), 0.5)
            blurred = cv2.GaussianBlur(small, (0, 0), sigma)
            acc += cv2.resize(blurred, (wdt, h), interpolation=cv2.INTER_LINEAR)
            small = cv2.resize(small, (max(small.shape[1] // 2, 1), max(small.shape[0] // 2, 1)),
                               interpolation=cv2.INTER_AREA)
        return img + acc * (s / 4)
    return fx


def chroma(amount=2.0, center=True):
    """色収差。center=True で画面端ほど大きくずれる。"""
    def fx(img, ctx):
        a = _v(amount, ctx) * _k(img)
        if abs(a) < 0.05:
            return img
        h, w = img.shape[:2]
        if not center:
            M_r = np.float32([[1, 0, a], [0, 1, 0]])
            M_b = np.float32([[1, 0, -a], [0, 1, 0]])
        else:
            s = 1 + a / (w / 2)
            M_r = cv2.getRotationMatrix2D((w / 2, h / 2), 0, s)
            M_b = cv2.getRotationMatrix2D((w / 2, h / 2), 0, 1 / s)
        out = img.copy()
        out[..., 0] = cv2.warpAffine(img[..., 0], M_r, (w, h), borderMode=cv2.BORDER_REFLECT)
        out[..., 2] = cv2.warpAffine(img[..., 2], M_b, (w, h), borderMode=cv2.BORDER_REFLECT)
        return out
    return fx


def grain(amount=0.035, size=1.0, seed=0):
    def fx(img, ctx):
        a = _v(amount, ctx)
        if a <= 0:
            return img
        h, w = img.shape[:2]
        rng = np.random.default_rng(seed + int(round(ctx.frame * 7919)))
        sz = max(_v(size, ctx) * _k(img), 1.0)
        gh, gw = max(int(h / sz), 1), max(int(w / sz), 1)
        n = rng.standard_normal((gh, gw), dtype=np.float32)
        if (gh, gw) != (h, w):
            n = cv2.resize(n, (w, h), interpolation=cv2.INTER_LINEAR)
        # 暗部ほど粒子を強く見せるとフィルムらしくなる
        luma = img.mean(axis=2, keepdims=True)
        return img + n[..., None] * a * (1.2 - luma)
    return fx


def vignette(strength=0.35, softness=0.6):
    cache: dict = {}

    def fx(img, ctx):
        s = _v(strength, ctx)
        if s <= 0:
            return img
        h, w = img.shape[:2]
        key = (h, w, softness)
        if key not in cache:
            y, x = np.mgrid[0:h, 0:w].astype(np.float32)
            d = np.sqrt(((x - w / 2) / (w / 2)) ** 2 + ((y - h / 2) / (h / 2)) ** 2) / math.sqrt(2)
            cache[key] = np.clip((d - (1 - softness)) / softness, 0, 1) ** 2
        return img * (1 - s * cache[key])[..., None]
    return fx


def glitch(intensity=0.0, slices=18, shift=80.0, seed=0):
    """横方向のスライスずれと RGB 分離。intensity は 0〜1 (関数で時間変化させる想定)。"""
    def fx(img, ctx):
        it = _v(intensity, ctx)
        if it <= 0.01:
            return img
        h, w = img.shape[:2]
        rng = np.random.default_rng(seed + int(ctx.frame * 3))
        out = img.copy()
        for _ in range(int(slices * it) + 1):
            y0 = int(rng.uniform(0, h))
            hh = int(rng.uniform(2, h / 12) * it) + 1
            dx = int(rng.normal(0, shift * _k(img) * it))
            out[y0:y0 + hh] = np.roll(img[y0:y0 + hh], dx, axis=1)
            ch = int(rng.integers(0, 3))
            out[y0:y0 + hh, :, ch] = np.roll(img[y0:y0 + hh, :, ch], dx * 2, axis=1)
        return out
    return fx


def scanlines(strength=0.06, period=3.0):
    def fx(img, ctx):
        s = _v(strength, ctx)
        if s <= 0:
            return img
        h = img.shape[0]
        y = np.arange(h, dtype=np.float32)
        m = 1 - s * (0.5 + 0.5 * np.cos(2 * np.pi * y / (period * _k(img))))
        return img * m[:, None, None]
    return fx


def flash(color=(1.0, 1.0, 1.0), decay=18.0, peak=0.6):
    """ctx.cues のたびに画面を一瞬明るくする。"""
    col = np.array(color, np.float32)

    def fx(img, ctx):
        e = impact(ctx.t, ctx.cues, decay) * _v(peak, ctx)
        if e < 0.003:
            return img
        return img + (col - img) * e
    return fx


def grade(lift=0.0, gamma=1.0, gain=1.0, saturation=1.0):
    def fx(img, ctx):
        out = img * _v(gain, ctx) + _v(lift, ctx)
        g = _v(gamma, ctx)
        if g != 1.0:
            out = np.power(np.clip(out, 0, None), 1 / g)
        s = _v(saturation, ctx)
        if s != 1.0:
            luma = out.mean(axis=2, keepdims=True)
            out = luma + (out - luma) * s
        return out
    return fx
