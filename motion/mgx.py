"""ManimGX (Rust + wgpu、Manim CE 互換の API) で数式・グラフ・3D のプレートを作り、2D に合成する。

    plate = mgx.MgxPlate(HERE / "torus.py", "Torus", start=2.0, size=(960, 540))
    comp.prepare.append(plate.prepare)          # 書き出しの前にメインプロセスで 1 度だけ作る
    ...
    plate.draw(c, ctx, x, y)                    # シーンの中で、作品の時刻から引いて描く

シーンのファイルは普通の ManimGX のシーン (`m.Scene` / `m.ThreeDScene`)。背景は透明、fps は作品に合わせて
透明な背景の連番 PNG (build/<作品>/mgx/) にする。値は `MgxPlate(params=...)` で渡し、シーンでは `mgx.params()` で読む。
入力 (シーンのファイル・パラメータ・大きさ・fps・ManimGX の版) が同じなら作り直さない。
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import skia

from .blender import Plate


def params() -> dict:
    """シーンのファイルの中で、MgxPlate に渡した params を読む。"""
    return json.loads(os.environ.get("MOTION_MGX_PARAMS", "{}"))


def _version() -> str:
    try:
        from importlib.metadata import version
        return version("manimgx")
    except Exception:
        return ""


class MgxPlate:
    """ManimGX のシーンを透明な背景の連番にして、時刻から引いて描く。シーンの 0 コマ目が作品の start 秒に来る。"""

    def __init__(self, file: str | Path, scene: str, *, start: float = 0.0, size: tuple[int, int] | None = None,
                 params: dict | None = None):
        self.file = Path(file).resolve()
        self.scene = scene
        self.start = start
        self.size = size
        self.params = params or {}
        self._plate: Plate | None = None

    def _args(self, comp) -> dict:
        w, h = self.size or (comp.width, comp.height)
        return {"file": str(self.file), "scene": self.scene, "fps": comp.fps, "width": w, "height": h,
                "params": self.params}

    def _dir(self, comp) -> Path:
        args = self._args(comp)
        key = hashlib.sha1((self.file.read_text(encoding="utf-8") + json.dumps(args, sort_keys=True)
                            + _version()).encode()).hexdigest()[:12]
        return Path(comp.build_dir) / "mgx" / f"{self.scene}-{key}"

    def prepare(self, comp) -> None:
        d = self._dir(comp)
        if (d / ".done").exists():
            return
        d.mkdir(parents=True, exist_ok=True)
        args = {**self._args(comp), "out": str(d)}
        print(f"mgx: {self.file.name} {self.scene} {args['width']}x{args['height']}@{args['fps']}", flush=True)
        r = subprocess.run([sys.executable, "-m", "motion.mgx_rt", json.dumps(args)], capture_output=True, text=True,
                           cwd=Path(__file__).resolve().parents[1])
        if r.returncode != 0:
            hint = " (サンドボックスの中では GPU が見えないので、外で実行する)" if "no GPU adapter" in r.stderr else ""
            raise RuntimeError(f"ManimGX のシーン {self.scene} を描けなかった{hint}\n{r.stderr[-2000:]}")
        (d / ".done").write_text(r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "")

    def frames(self, comp) -> int:
        """書き出したコマの数 (prepare の後)。"""
        return len(list(self._dir(comp).glob("f_*.png")))

    def draw(self, c: skia.Canvas, ctx, x: float = 0.0, y: float = 0.0, w: float | None = None,
             h: float | None = None, alpha: float = 1.0) -> None:
        if self._plate is None:
            d = self._dir(ctx.comp)
            if not (d / ".done").exists():
                return
            n = len(list(d.glob("f_*.png")))
            self._plate = Plate(d, ctx.comp.fps, start=self.start, frame_end=max(n - 1, 0))
        self._plate.draw(c, ctx.t, x, y, w, h, alpha)
