"""動きの軌跡を 1 枚に重ねる (オニオンスキン)。動画を見られない Claude が、動きの経路と加減速を確かめる。

    uv run python -m motion onion projects/demo 2.0 2.8 -n 7

区間を等間隔に n コマ描き、動かない部分 (コマの中央値) を暗い背景にして、動いた部分だけを
時刻順に青→橙で重ねる。等間隔のコマなので、像の間隔が詰まっている所は遅く、空いている所は速い。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .render import FrameRenderer, load_project, prepare


def onion(project: str | Path, t0: float, t1: float, n: int = 7, scale: float = 0.5,
          out: str | Path | None = None) -> Path:
    import cv2
    comp = load_project(project)
    prepare(comp)
    r = FrameRenderer(comp, scale, motion_blur=False, post=False)
    ts = np.linspace(t0, t1, n)
    frames = [r.frame(min(int(round(t * comp.fps)), comp.nframes - 1)).astype(np.float32) for t in ts]
    bg = np.median(np.stack(frames), axis=0)
    canvas = bg * 0.3
    cold, warm = np.array([80, 160, 255], np.float32), np.array([255, 140, 60], np.float32)
    for i, fr in enumerate(frames):
        k = i / max(n - 1, 1)
        a = np.clip(np.abs(fr - bg).max(axis=2) / 40.0, 0, 1)[..., None] * (0.45 + 0.55 * k)
        tint = cold * (1 - k) + warm * k
        canvas = canvas * (1 - a) + (fr * 0.55 + tint * 0.45) * a
    img = np.clip(canvas, 0, 255).astype(np.uint8)
    h, w = img.shape[:2]
    bar = np.full((44, w, 3), 18, np.uint8)
    for i, t in enumerate(ts):
        k = i / max(n - 1, 1)
        x = int(12 + (w - 24) * k)
        col = tuple(int(c) for c in (cold * (1 - k) + warm * k))
        cv2.circle(bar, (x, 14), 5, col, -1, cv2.LINE_AA)
        cv2.putText(bar, f"{t:.2f}", (min(max(x - 16, 2), w - 36), 36), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (200, 200, 205), 1, cv2.LINE_AA)
    img = np.vstack([img, bar])
    out = Path(out) if out else Path(comp.build_dir) / f"onion_{t0:.2f}-{t1:.2f}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
    return out
