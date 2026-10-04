from __future__ import annotations

import importlib.util
import math
import multiprocessing as mp
import os
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import skia

from .scene import Composition, Ctx

cv2.setNumThreads(1)


def load_project(path: str | Path) -> Composition:
    """project.py (またはそれを含むディレクトリ) を読み込み、build() の結果を返す。"""
    p = Path(path).resolve()
    if p.is_dir():
        p = p / "project.py"
    if str(p.parent) not in sys.path:
        sys.path.insert(0, str(p.parent))
    spec = importlib.util.spec_from_file_location(f"motion_project_{p.parent.name}", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    comp: Composition = mod.build()
    if comp.name == "untitled":
        comp.name = p.parent.name
    if not Path(comp.build_dir).is_absolute():
        comp.build_dir = str(p.parent.parent.parent / comp.build_dir / comp.name)
    return comp


def prepare(comp: Composition) -> None:
    for fn in comp.prepare:
        fn(comp)


class FrameRenderer:
    def __init__(self, comp: Composition, scale: float = 1.0, motion_blur: bool = True, post: bool = True):
        self.comp = comp
        self.scale = scale
        self.mb = motion_blur
        self.use_post = post
        self.w = max(int(round(comp.width * scale)), 1)
        self.h = max(int(round(comp.height * scale)), 1)
        self.surface = skia.Surface(self.w, self.h)
        self.scenes = sorted(comp.scenes, key=lambda s: s.z)

    def draw(self, t: float, frame: float) -> np.ndarray:
        comp = self.comp
        c = self.surface.getCanvas()
        c.resetMatrix()
        c.clear(comp.background.skia())
        c.save()
        c.scale(self.scale, self.scale)
        for s in self.scenes:
            if not s.active(t, comp):
                continue
            s.ensure_setup(comp)
            st, en = s.span(comp)
            ctx = Ctx(t, frame, comp, st, en)
            a = s.alpha(ctx)
            if a <= 0.0:
                continue
            c.save()
            if comp.camera and not s.fixed:
                comp.camera(c, ctx)
            if a < 1.0:
                c.saveLayerAlpha(None, int(round(a * 255)))
            s.draw(c, ctx)
            if a < 1.0:
                c.restore()
            c.restore()
        c.restore()
        return self.surface.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)

    def frame(self, f: int) -> np.ndarray:
        """f 番目のフレームを RGB uint8 (H, W, 3) で返す。"""
        comp = self.comp
        t = f / comp.fps
        n = comp.subframes(t) if self.mb else 1
        if n == 1:
            rgb = self.draw(t, f)[..., :3].astype(np.float32) / 255.0
        else:
            acc = np.zeros((self.h, self.w, 3), np.float32)
            span = comp.shutter / comp.fps
            for i in range(n):
                dt = ((i + 0.5) / n - 0.5) * span
                acc += self.draw(t + dt, f + dt * comp.fps)[..., :3]
            rgb = acc / (255.0 * n)
        if self.use_post and comp.post:
            ctx = Ctx(t, f, comp, 0.0, comp.duration)
            for fx in comp.post:
                rgb = fx(rgb, ctx)
        return (np.clip(rgb, 0, 1) * 255 + 0.5).astype(np.uint8)


_R: FrameRenderer | None = None


def _init_worker(project: str, scale: float, mb: bool, post: bool) -> None:
    global _R
    _R = FrameRenderer(load_project(project), scale, mb, post)


def _render_one(f: int) -> bytes:
    return _R.frame(f).tobytes()


def _pool(project, scale, mb, post, workers):
    ctx = mp.get_context("spawn")
    return ctx.Pool(workers or max(os.cpu_count() - 1, 1), _init_worker, (str(project), scale, mb, post))


def _frames(comp: Composition, start: float | None, end: float | None, step: int = 1) -> list[int]:
    f0 = 0 if start is None else int(round(start * comp.fps))
    f1 = comp.nframes if end is None else min(int(round(end * comp.fps)), comp.nframes)
    return list(range(f0, f1, step))


def render_video(project: str | Path, out: str | Path | None = None, *, scale: float = 1.0,
                 start: float | None = None, end: float | None = None, workers: int | None = None,
                 crf: int = 18, preset: str = "medium", motion_blur: bool = True, post: bool = True,
                 audio: bool = True) -> Path:
    comp = load_project(project)
    prepare(comp)
    frames = _frames(comp, start, end)
    w, h = max(int(round(comp.width * scale)), 1), max(int(round(comp.height * scale)), 1)
    out = Path(out) if out else Path(comp.build_dir) / f"{comp.name}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)

    wav = None
    if audio and comp.audio:
        print("audio: rendering...", flush=True)
        wav = comp.audio(comp)

    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{w}x{h}", "-r", str(comp.fps), "-i", "-"]
    if wav:
        cmd += ["-ss", f"{frames[0] / comp.fps:.6f}", "-i", str(wav)]
    # 奇数解像度だと yuv420p でエンコードできないため偶数に丸める
    cmd += ["-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
            "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    if wav:
        cmd += ["-c:a", "aac", "-b:a", "320k", "-shortest"]
    cmd += [str(out)]

    ff = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    t0 = time.time()
    with _pool(project, scale, motion_blur, post, workers) as pool:
        for i, buf in enumerate(pool.imap(_render_one, frames, chunksize=2)):
            ff.stdin.write(buf)
            if i % max(len(frames) // 20, 1) == 0 or i == len(frames) - 1:
                el = time.time() - t0
                print(f"\rrender: {i + 1}/{len(frames)}  {el:.1f}s  ({(i + 1) / max(el, 1e-6):.1f} fps)",
                      end="", flush=True)
    ff.stdin.close()
    if ff.wait() != 0:
        raise RuntimeError("ffmpeg failed")
    print(f"\n-> {out}")
    return out


def _label(img: np.ndarray, s: str) -> np.ndarray:
    img = img.copy()
    k = img.shape[0] / 270
    cv2.putText(img, s, (int(6 * k), int(18 * k)), cv2.FONT_HERSHEY_SIMPLEX, 0.45 * k, (0, 0, 0), int(3 * k) + 1,
                cv2.LINE_AA)
    cv2.putText(img, s, (int(6 * k), int(18 * k)), cv2.FONT_HERSHEY_SIMPLEX, 0.45 * k, (255, 230, 80),
                max(int(k), 1), cv2.LINE_AA)
    return img


def contact_sheet(project: str | Path, out: str | Path | None = None, *, count: int = 24, cols: int = 6,
                  scale: float = 0.25, start: float | None = None, end: float | None = None,
                  workers: int | None = None, motion_blur: bool = False) -> Path:
    """等間隔のフレームを一覧にした画像を作る。レンダリング結果の目視確認用。"""
    comp = load_project(project)
    prepare(comp)
    allf = _frames(comp, start, end)
    idx = np.linspace(0, len(allf) - 1, min(count, len(allf))).round().astype(int)
    frames = [allf[i] for i in idx]
    w, h = max(int(round(comp.width * scale)), 1), max(int(round(comp.height * scale)), 1)
    with _pool(project, scale, motion_blur, True, workers) as pool:
        imgs = [np.frombuffer(b, np.uint8).reshape(h, w, 3) for b in pool.imap(_render_one, frames)]
    imgs = [_label(im, f"{f / comp.fps:6.2f}s  #{f}") for im, f in zip(imgs, frames)]
    rows = math.ceil(len(imgs) / cols)
    pad = 4
    sheet = np.full((rows * (h + pad) + pad, cols * (w + pad) + pad, 3), 24, np.uint8)
    for i, im in enumerate(imgs):
        r, cl = divmod(i, cols)
        y, x = pad + r * (h + pad), pad + cl * (w + pad)
        sheet[y:y + h, x:x + w] = im
    out = Path(out) if out else Path(comp.build_dir) / "sheet.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), cv2.cvtColor(sheet, cv2.COLOR_RGB2BGR))
    print(f"-> {out}")
    return out


def still(project: str | Path, t: float, out: str | Path | None = None, *, scale: float = 1.0,
          motion_blur: bool = True) -> Path:
    comp = load_project(project)
    prepare(comp)
    r = FrameRenderer(comp, scale, motion_blur)
    f = int(round(t * comp.fps))
    img = r.frame(f)
    out = Path(out) if out else Path(comp.build_dir) / f"still_{f:05d}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
    print(f"-> {out}")
    return out
