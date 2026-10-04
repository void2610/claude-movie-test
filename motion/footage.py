"""ゲームのキャプチャなど、外部の動画素材をクリップとして扱う。

    cap = Footage("captures/run01.mp4")
    hit = Clip(cap, at=2.0, src_in=31.2, time=TimeMap().play(0.8).ramp(0.6, 1.0, 0.2).hold(0.4).play(0.5))
    comp.prepare.append(cap.prepare)          # 使う区間だけを書き出しておく
    ...
    hit.draw(c, ctx, fit="cover", zoom=lambda t: 1 + 0.2 * progress(t, 2.5, 3.0), grade=Grade(saturation=1.2))

素材のフレームは使う区間だけを素材の fps で JPEG に書き出してキャッシュする。
スローや速度変化では、間のフレームをブレンドかオプティカルフローで補う。
"""
from __future__ import annotations

import hashlib
import json
import math
import subprocess
from collections import OrderedDict
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
import skia

from .media import fit_rects, probe

_SAMPLING = skia.SamplingOptions(skia.FilterMode.kLinear, skia.MipmapMode.kNone)


class TimeMap:
    """クリップのローカル時刻 → 素材内の経過秒 の対応を、区間をつないで組み立てる。"""

    def __init__(self):
        self.segs: list[tuple[float, Callable[[float], float], float]] = []  # (長さ, 区間内の写像, 区間の開始値)
        self.pos = 0.0

    def _add(self, dur: float, fn: Callable[[float], float], end: float) -> TimeMap:
        self.segs.append((dur, fn, self.pos))
        self.pos = end
        return self

    def play(self, dur: float, speed: float = 1.0) -> TimeMap:
        p = self.pos
        return self._add(dur, lambda u, p=p: p + u * speed, p + dur * speed)

    def hold(self, dur: float) -> TimeMap:
        """フリーズフレーム。"""
        p = self.pos
        return self._add(dur, lambda u, p=p: p, p)

    def ramp(self, dur: float, s0: float, s1: float) -> TimeMap:
        """速度を s0 から s1 へ直線的に変える (スピードランプ)。"""
        p = self.pos
        return self._add(dur, lambda u, p=p: p + s0 * u + (s1 - s0) * u * u / (2 * dur),
                         p + (s0 + s1) / 2 * dur)

    def rewind(self, dur: float, speed: float = 1.0) -> TimeMap:
        """逆再生。"""
        p = self.pos
        return self._add(dur, lambda u, p=p: p - u * speed, p - dur * speed)

    def seek(self, src: float) -> TimeMap:
        """素材内の位置へ飛ぶ (ジャンプカット)。長さは 0。"""
        self.pos = src
        return self

    @property
    def duration(self) -> float:
        return sum(d for d, _, _ in self.segs)

    @property
    def spans(self) -> list[tuple[float, float]]:
        """素材内で使う範囲を区間ごとに返す (seek で飛ばした部分は含めない)。"""
        out = []
        for d, fn, _ in self.segs:
            vals = [fn(d * k / 16) for k in range(17)]
            out.append((min(vals), max(vals)))
        return out or [(0.0, 0.0)]

    def __call__(self, u: float) -> float:
        acc = 0.0
        for d, fn, _ in self.segs:
            if u < acc + d:
                return fn(max(u - acc, 0.0))
            acc += d
        if not self.segs:
            return u
        d, fn, _ = self.segs[-1]
        return fn(d)

    def speed(self, u: float, eps: float = 1e-3) -> float:
        return (self(u + eps) - self(u - eps)) / (2 * eps)


class Footage:
    def __init__(self, path: str | Path, max_height: int | None = 1080, quality: int = 3, cache: int = 24):
        self.path = Path(path).resolve()
        info = probe(self.path)
        self.width, self.height, self.fps, self.duration = info["width"], info["height"], info["fps"], info["duration"]
        self.max_height = max_height
        self.quality = quality
        self.ranges: list[tuple[float, float]] = []
        self._lru: OrderedDict[int, np.ndarray] = OrderedDict()
        self._max = cache
        self._dir: Path | None = None
        self._flow = None

    def need(self, a: float, b: float) -> None:
        a, b = max(0.0, a), min(self.duration, b)
        if b > a:
            self.ranges.append((a, b))

    def _cache_dir(self, comp) -> Path:
        if self._dir is None:
            st = self.path.stat()
            key = hashlib.sha1(json.dumps([str(self.path), st.st_mtime, st.st_size, self.max_height,
                                           self.quality]).encode()).hexdigest()[:16]
            self._dir = Path(comp.build_dir) / "footage" / f"{self.path.stem}-{key}"
        return self._dir

    def _merged(self, margin: float = 0.2) -> list[tuple[float, float]]:
        rs = sorted((max(0.0, a - margin), min(self.duration, b + margin)) for a, b in self.ranges)
        out: list[list[float]] = []
        for a, b in rs:
            if out and a <= out[-1][1]:
                out[-1][1] = max(out[-1][1], b)
            else:
                out.append([a, b])
        return [(a, b) for a, b in out]

    def prepare(self, comp) -> None:
        """登録された区間のフレームを、素材の fps のまま JPEG に書き出す。済んだ区間は飛ばす。"""
        d = self._cache_dir(comp)
        d.mkdir(parents=True, exist_ok=True)
        for a, b in self._merged():
            i0, i1 = int(math.floor(a * self.fps)), int(math.ceil(b * self.fps))
            marker = d / f".done_{i0}_{i1}"
            if marker.exists() or all((d / f"f_{i:06d}.jpg").exists() for i in range(i0, i1 + 1)):
                continue
            vf = []
            if self.max_height and self.height > self.max_height:
                vf.append(f"scale=-2:{self.max_height}")
            cmd = ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{i0 / self.fps:.6f}", "-i", str(self.path),
                   "-frames:v", str(i1 - i0 + 1), "-start_number", str(i0), "-q:v", str(self.quality)]
            if vf:
                cmd += ["-vf", ",".join(vf)]
            cmd += [str(d / "f_%06d.jpg")]
            print(f"footage: {self.path.name} {a:.2f}-{b:.2f}s", flush=True)
            subprocess.run(cmd, check=True)
            marker.write_text("ok")

    def _read(self, comp, i: int) -> np.ndarray:
        if i in self._lru:
            self._lru.move_to_end(i)
            return self._lru[i]
        d = self._cache_dir(comp)
        p = d / f"f_{i:06d}.jpg"
        if not p.exists():
            # 区間の端で 1 フレーム足りないことがあるので、近い方に寄せる
            cands = sorted(d.glob("f_*.jpg"), key=lambda q: abs(int(q.stem[2:]) - i))
            if not cands:
                raise FileNotFoundError(f"footage frames not prepared: {self.path.name}. comp.prepare に追加したか確認")
            p = cands[0]
        img = cv2.cvtColor(cv2.imread(str(p)), cv2.COLOR_BGR2RGB)
        self._lru[i] = img
        if len(self._lru) > self._max:
            self._lru.popitem(last=False)
        return img

    def frame(self, comp, src_t: float, interp: str = "blend") -> np.ndarray:
        """素材内の時刻 src_t のフレーム (RGB uint8)。間の時刻は interp で補う。"""
        x = min(max(src_t, 0.0), self.duration) * self.fps
        i0 = int(math.floor(x))
        f = x - i0
        a = self._read(comp, i0)
        if interp == "nearest" or f < 0.02:
            return a if f < 0.5 or interp != "nearest" else self._read(comp, i0 + 1)
        b = self._read(comp, i0 + 1)
        if f > 0.98:
            return b
        if a.shape != b.shape:
            return a
        if interp == "flow":
            return self._flow_interp(a, b, f)
        return cv2.addWeighted(a, 1 - f, b, f, 0)

    def _flow_interp(self, a: np.ndarray, b: np.ndarray, f: float) -> np.ndarray:
        """オプティカルフローで a と b の間の f の位置のフレームを作る (スローモーション用)。"""
        if self._flow is None:
            self._flow = cv2.DISOpticalFlow_create(cv2.DISOPTICAL_FLOW_PRESET_FAST)
        h, w = a.shape[:2]
        s = min(1.0, 540 / h)
        ga = cv2.cvtColor(cv2.resize(a, None, fx=s, fy=s), cv2.COLOR_RGB2GRAY)
        gb = cv2.cvtColor(cv2.resize(b, None, fx=s, fy=s), cv2.COLOR_RGB2GRAY)
        fwd = self._flow.calc(ga, gb, None)
        bwd = self._flow.calc(gb, ga, None)
        fwd = cv2.resize(fwd, (w, h)) / s
        bwd = cv2.resize(bwd, (w, h)) / s
        gy, gx = np.mgrid[0:h, 0:w].astype(np.float32)
        # a を f だけ前へ、b を (1 - f) だけ後ろへ運んで重ねる
        wa = cv2.remap(a, gx - fwd[..., 0] * f, gy - fwd[..., 1] * f, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        wb = cv2.remap(b, gx - bwd[..., 0] * (1 - f), gy - bwd[..., 1] * (1 - f), cv2.INTER_LINEAR,
                       borderMode=cv2.BORDER_REPLICATE)
        return cv2.addWeighted(wa, 1 - f, wb, f, 0)


def read_cube(path: str | Path) -> np.ndarray:
    """Adobe .cube 形式の 3D LUT を (N, N, N, 3) で読む。添字は [b][g][r]。"""
    size, vals = None, []
    for line in Path(path).read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.upper().startswith("LUT_3D_SIZE"):
            size = int(s.split()[1])
        elif s[0].isdigit() or s[0] in "-.":
            vals.append([float(v) for v in s.split()[:3]])
    if size is None:
        raise ValueError(f"not a 3D cube LUT: {path}")
    return np.asarray(vals, np.float32).reshape(size, size, size, 3)


class Grade:
    """素材の色調整。exposure は段 (EV)、temperature / tint は -1〜1。lut に .cube を渡せる。"""

    def __init__(self, exposure: float = 0.0, contrast: float = 1.0, saturation: float = 1.0,
                 temperature: float = 0.0, tint: float = 0.0, lift: float = 0.0, gamma: float = 1.0,
                 lut: str | Path | None = None, lut_strength: float = 1.0):
        self.exposure, self.contrast, self.saturation = exposure, contrast, saturation
        self.temperature, self.tint, self.lift, self.gamma = temperature, tint, lift, gamma
        self.lut = read_cube(lut) if lut else None
        self.lut_strength = lut_strength

    def __call__(self, rgb: np.ndarray) -> np.ndarray:
        x = rgb.astype(np.float32) / 255.0
        if self.exposure:
            x *= 2.0 ** self.exposure
        if self.temperature or self.tint:
            x *= np.array([1 + 0.1 * self.temperature - 0.03 * self.tint, 1 + 0.08 * self.tint,
                           1 - 0.1 * self.temperature - 0.03 * self.tint], np.float32)
        if self.contrast != 1.0:
            x = (x - 0.5) * self.contrast + 0.5
        if self.saturation != 1.0:
            luma = (x @ np.array([0.2126, 0.7152, 0.0722], np.float32))[..., None]
            x = luma + (x - luma) * self.saturation
        if self.lift:
            x = x + self.lift * (1 - x)
        if self.gamma != 1.0:
            x = np.power(np.clip(x, 0, 1), 1 / self.gamma)
        x = np.clip(x, 0, 1)
        if self.lut is not None:
            x = x * (1 - self.lut_strength) + _apply_lut(x, self.lut) * self.lut_strength
        return (x * 255 + 0.5).astype(np.uint8)


def _apply_lut(x: np.ndarray, lut: np.ndarray) -> np.ndarray:
    n = lut.shape[0]
    p = x * (n - 1)
    i0 = np.clip(np.floor(p).astype(np.int32), 0, n - 2)
    f = p - i0
    r0, g0, b0 = i0[..., 0], i0[..., 1], i0[..., 2]
    fr, fg, fb = f[..., 0:1], f[..., 1:2], f[..., 2:3]
    out = np.zeros_like(x)
    for db in (0, 1):
        wb = fb if db else 1 - fb
        for dg in (0, 1):
            wg = fg if dg else 1 - fg
            for dr in (0, 1):
                wr = fr if dr else 1 - fr
                out += lut[b0 + db, g0 + dg, r0 + dr] * (wr * wg * wb)
    return out


def _device_scale(c: skia.Canvas) -> float:
    m = c.getTotalMatrix()
    return math.hypot(m.getScaleX(), m.getSkewY())


class Clip:
    """素材の一部を、作品の at 秒から再生する。time を省くと src_in から等速 (speed 倍) で src_out まで。"""

    def __init__(self, footage: Footage, *, at: float = 0.0, src_in: float = 0.0, src_out: float | None = None,
                 speed: float = 1.0, time: TimeMap | None = None, loop: bool = False, interp: str = "blend"):
        self.footage = footage
        self.at = at
        self.src_in = src_in
        self.loop = loop
        self.interp = interp
        if time is None:
            end = footage.duration if src_out is None else src_out
            time = TimeMap().play((end - src_in) / speed, speed)
        self.time = time
        for lo, hi in time.spans:
            footage.need(src_in + lo, src_in + hi)
        self._cache: OrderedDict = OrderedDict()

    @property
    def duration(self) -> float:
        return self.time.duration

    @property
    def end(self) -> float:
        return self.at + self.duration

    def src_time(self, t: float) -> float:
        u = t - self.at
        if self.loop and self.duration > 0:
            u %= self.duration
        else:
            u = min(max(u, 0.0), self.duration)
        return self.src_in + self.time(u)

    def frame(self, comp, t: float) -> np.ndarray:
        return self.footage.frame(comp, self.src_time(t), self.interp)

    def draw(self, c: skia.Canvas, ctx, x: float = 0.0, y: float = 0.0, w: float | None = None,
             h: float | None = None, *, fit: str = "cover", crop=None, zoom=1.0, focus=(0.5, 0.5),
             radius: float = 0.0, alpha: float = 1.0, grade: Grade | None = None, shadow: float = 0.0,
             border: float = 0.0, border_color: str = "#ffffff") -> None:
        """枠 (x, y, w, h) にクリップを描く。

        crop: 素材の一部 (0〜1 の x, y, w, h) を切り出す。zoom / focus: 枠の中で focus を中心に拡大する。
        crop・zoom・focus には ctx.t を受け取る関数も渡せる (パン・ズームのアニメーション)。
        """
        t = ctx.t
        w = ctx.W if w is None else w
        h = ctx.H if h is None else h
        val = lambda v: v(t) if callable(v) else v  # noqa: E731
        rgb = self.frame(ctx.comp, t)
        ih, iw = rgb.shape[:2]
        cr = val(crop)
        if cr is not None:
            cx0, cy0, cw, ch = cr
            rgb = rgb[int(cy0 * ih):int((cy0 + ch) * ih), int(cx0 * iw):int((cx0 + cw) * iw)]
            ih, iw = rgb.shape[:2]
        src, dst = fit_rects(iw, ih, x, y, w, h, fit)
        z = max(val(zoom), 1e-3)
        if z != 1.0:
            fx, fy = val(focus)
            sw, sh = src.width() / z, src.height() / z
            sx = src.left() + (src.width() - sw) * fx
            sy = src.top() + (src.height() - sh) * fy
            src = skia.Rect.MakeXYWH(sx, sy, sw, sh)
        # 色調整は描画先の解像度に縮めてから行う (1080p の素材を小さく描くときに無駄がない)
        k = _device_scale(c)
        tw, th = max(int(dst.width() * k), 1), max(int(dst.height() * k), 1)
        x0, y0 = max(int(src.left()), 0), max(int(src.top()), 0)
        x1, y1 = min(int(math.ceil(src.right())), iw), min(int(math.ceil(src.bottom())), ih)
        part = rgb[y0:y1, x0:x1]
        if part.size == 0:
            return
        part = cv2.resize(part, (tw, th), interpolation=cv2.INTER_AREA if tw < part.shape[1] else cv2.INTER_LINEAR)
        if grade is not None:
            part = grade(part)
        img = skia.Image.fromarray(cv2.cvtColor(part, cv2.COLOR_RGB2RGBA), colorType=skia.kRGBA_8888_ColorType)
        rr = skia.RRect.MakeRectXY(dst, radius, radius)
        if shadow > 0:
            sp = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(int(160 * alpha), 0, 0, 0))
            sp.setMaskFilter(skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, shadow))
            c.drawRRect(rr.makeOffset(0, shadow * 0.4), sp)
        c.save()
        if radius > 0:
            c.clipRRect(rr, skia.ClipOp.kIntersect, True)
        c.drawImageRect(img, skia.Rect.MakeWH(img.width(), img.height()), dst, _SAMPLING,
                        skia.Paint(Alphaf=alpha, AntiAlias=True), skia.Canvas.kFast_SrcRectConstraint)
        c.restore()
        if border > 0:
            c.drawRRect(rr, skia.Paint(AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=border,
                                       Color=skia.Color4f(*_hex(border_color), alpha).toColor()))


def _hex(s: str) -> tuple[float, float, float]:
    s = s.lstrip("#")
    return tuple(int(s[i:i + 2], 16) / 255 for i in (0, 2, 4))
