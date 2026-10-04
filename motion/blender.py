"""Blender をヘッドレスで動かして連番 PNG (プレート) を作り、2D に合成する。

Blender 用スクリプトの書き方:

    import sys, os
    sys.path.insert(0, os.environ["MOTION_BLENDER_RT"])
    import blender_rt as rt
    args = rt.args()          # out / frame_start / frame_end / fps / width / height / params
    rt.reset_scene()
    ...                       # bpy でシーンを組む (args["params"] で値を受け取る)
    rt.render(args)
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from collections import OrderedDict
from pathlib import Path

import skia

BLENDER = shutil.which("blender") or "/Applications/Blender.app/Contents/MacOS/Blender"
_RT_DIR = Path(__file__).resolve().parent


def render_plate(script: str | Path, out_dir: str | Path, *, frame_start: int, frame_end: int, fps: int,
                 width: int, height: int, params: dict | None = None, force: bool = False) -> Path:
    """script を実行して out_dir/f_0000.png 形式の連番を作る。入力が同じなら再実行しない。"""
    out_dir = Path(out_dir)
    args = {
        "out": str(out_dir / "f_####"),
        "frame_start": frame_start,
        "frame_end": frame_end,
        "fps": fps,
        "width": width,
        "height": height,
        "params": params or {},
    }
    stamp = hashlib.sha1((Path(script).read_text() + json.dumps(args, sort_keys=True)).encode()).hexdigest()
    stamp_file = out_dir / ".stamp"
    done = all((out_dir / f"f_{i:04d}.png").exists() for i in range(frame_start, frame_end + 1))
    if not force and done and stamp_file.exists() and stamp_file.read_text() == stamp:
        return out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "MOTION_BLENDER_RT": str(_RT_DIR)}
    cmd = [BLENDER, "-b", "--factory-startup", "--python", str(script), "--", json.dumps(args)]
    print(f"blender: {Path(script).name} frames {frame_start}-{frame_end}", flush=True)
    subprocess.run(cmd, env=env, check=True, stdout=subprocess.DEVNULL)
    stamp_file.write_text(stamp)
    return out_dir


class Plate:
    """連番 PNG を時刻で引いて描く。frame_start の画像が start 秒に対応する。"""

    def __init__(self, directory: str | Path, fps: int, start: float = 0.0, frame_start: int = 0,
                 frame_end: int | None = None, cache: int = 12):
        self.dir = Path(directory)
        self.fps = fps
        self.start = start
        self.frame_start = frame_start
        self.frame_end = frame_end
        self._cache: OrderedDict[int, skia.Image] = OrderedDict()
        self._max = cache

    def index(self, t: float) -> int:
        i = self.frame_start + int(round((t - self.start) * self.fps))
        i = max(i, self.frame_start)
        if self.frame_end is not None:
            i = min(i, self.frame_end)
        return i

    def image(self, t: float) -> skia.Image | None:
        i = self.index(t)
        if i in self._cache:
            self._cache.move_to_end(i)
            return self._cache[i]
        p = self.dir / f"f_{i:04d}.png"
        if not p.exists():
            return None
        img = skia.Image.open(str(p))
        self._cache[i] = img
        if len(self._cache) > self._max:
            self._cache.popitem(last=False)
        return img

    def draw(self, c: skia.Canvas, t: float, x: float = 0.0, y: float = 0.0, w: float | None = None,
             h: float | None = None, alpha: float = 1.0) -> None:
        img = self.image(t)
        if img is None:
            return
        w = img.width() if w is None else w
        h = img.height() if h is None else h
        p = skia.Paint(Alphaf=alpha)
        c.drawImageRect(img, skia.Rect.MakeXYWH(x, y, w, h), skia.SamplingOptions(skia.FilterMode.kLinear), p)
