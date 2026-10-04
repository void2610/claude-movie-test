import math
from functools import lru_cache

import numpy as np


@lru_cache(maxsize=16)
def _perm(seed: int) -> np.ndarray:
    p = np.random.default_rng(seed).permutation(256)
    return np.concatenate([p, p]).astype(np.int64)


def _fade(t):
    return t * t * t * (t * (t * 6 - 15) + 10)


def _grad3(h, x, y, z):
    h = h & 15
    u = np.where(h < 8, x, y)
    v = np.where(h < 4, y, np.where((h == 12) | (h == 14), x, z))
    return np.where(h & 1, -u, u) + np.where(h & 2, -v, v)


def perlin3(x, y, z, seed: int = 0):
    """ベクトル化した 3D Perlin ノイズ。出力はおよそ -1〜1。"""
    p = _perm(seed)
    x, y, z = np.asarray(x, np.float64), np.asarray(y, np.float64), np.asarray(z, np.float64)
    xi, yi, zi = np.floor(x).astype(np.int64), np.floor(y).astype(np.int64), np.floor(z).astype(np.int64)
    xf, yf, zf = x - xi, y - yi, z - zi
    xi, yi, zi = xi & 255, yi & 255, zi & 255
    u, v, w = _fade(xf), _fade(yf), _fade(zf)
    a, b = p[xi] + yi, p[xi + 1] + yi
    aa, ab, ba, bb = p[a] + zi, p[a + 1] + zi, p[b] + zi, p[b + 1] + zi

    def lerp(t, a, b):
        return a + t * (b - a)

    x1 = lerp(u, _grad3(p[aa], xf, yf, zf), _grad3(p[ba], xf - 1, yf, zf))
    x2 = lerp(u, _grad3(p[ab], xf, yf - 1, zf), _grad3(p[bb], xf - 1, yf - 1, zf))
    y1 = lerp(v, x1, x2)
    x1 = lerp(u, _grad3(p[aa + 1], xf, yf, zf - 1), _grad3(p[ba + 1], xf - 1, yf, zf - 1))
    x2 = lerp(u, _grad3(p[ab + 1], xf, yf - 1, zf - 1), _grad3(p[bb + 1], xf - 1, yf - 1, zf - 1))
    y2 = lerp(v, x1, x2)
    return lerp(w, y1, y2)


def perlin2(x, y, seed: int = 0):
    return perlin3(x, y, np.zeros_like(np.asarray(x, np.float64)), seed)


def fbm3(x, y, z, octaves: int = 4, lacunarity: float = 2.0, gain: float = 0.5, seed: int = 0):
    total, amp, freq, norm = 0.0, 1.0, 1.0, 0.0
    for i in range(octaves):
        total = total + amp * perlin3(x * freq, y * freq, z * freq, seed + i)
        norm += amp
        amp *= gain
        freq *= lacunarity
    return total / norm


def noise1(t: float, seed: float = 0.0) -> float:
    """スカラーの滑らかな 1D ノイズ (-1〜1)。カメラの揺れなどに使う。"""
    return float(perlin3(t, seed * 17.13 + 0.5, 0.37, 0)) * 1.4


def curl2(x, y, t, scale: float = 1.0, seed: int = 0, eps: float = 1e-3):
    """2D の curl ノイズ場 (発散ゼロの流れ)。戻り値は (vx, vy)。"""
    x, y = np.asarray(x) * scale, np.asarray(y) * scale
    z = np.full_like(x, t, dtype=np.float64)
    dy = (perlin3(x, y + eps, z, seed) - perlin3(x, y - eps, z, seed)) / (2 * eps)
    dx = (perlin3(x + eps, y, z, seed) - perlin3(x - eps, y, z, seed)) / (2 * eps)
    return dy, -dx


def hash01(*xs: float) -> float:
    """引数から決定的に 0〜1 の値を作る (乱数のシード固定の代わり)。"""
    h = 0.0
    for i, x in enumerate(xs):
        h += x * (12.9898 + 78.233 * i)
    v = math.sin(h) * 43758.5453
    return v - math.floor(v)
