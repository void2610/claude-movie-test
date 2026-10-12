"""ManimGX のシーンを別のプロセスで透明な背景の連番 PNG にする (motion.mgx から呼ぶ)。

    python -m motion.mgx_rt '{"file": ..., "scene": ..., "fps": 60, "width": 960, "height": 540, "params": {}, "out": ...}'

ManimGX の設定は全体で 1 つなので、作品のプロセスとは分けて動かす。
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np


def main(args: dict) -> None:
    import manimgx as m
    w, h = args["width"], args["height"]
    m.config.pixel_width, m.config.pixel_height = w, h
    m.config.frame_rate = args["fps"]
    m.config.background_opacity = 0.0
    os.environ["MOTION_MGX_PARAMS"] = json.dumps(args["params"])
    spec = importlib.util.spec_from_file_location("motion_mgx_scene", args["file"])
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = Path(args["out"])
    count = 0

    n = os.cpu_count() or 4
    # 描画は保存より何倍も速いので、保存待ちのコマを抱えすぎない (1080² で 1 コマ 4.7MB)
    slots = threading.BoundedSemaphore(n * 2)

    def save(raw: bytes, index: int, repeat: int) -> None:
        try:
            _save(raw, index, repeat)
        finally:
            slots.release()

    def _save(raw: bytes, index: int, repeat: int) -> None:
        a = np.frombuffer(raw, np.uint8).reshape(h, w, 4)
        al = a[..., 3:4].astype(np.float32)
        # ManimGX はアルファを掛けた色で返すが、PNG は掛ける前の色で持つ (そのままだと読み込みで二重に掛かり縁が暗くなる)
        rgb = np.where(al > 0, np.clip(a[..., :3] * (255.0 / np.maximum(al, 1.0)) + 0.5, 0, 255), 0).astype(np.uint8)
        first = out / f"f_{index:04d}.png"
        cv2.imwrite(str(first), cv2.cvtColor(np.dstack([rgb, a[..., 3]]), cv2.COLOR_RGBA2BGRA),
                    [cv2.IMWRITE_PNG_COMPRESSION, 1])
        # 同じ画面が続くコマは 1 回しか届かないので、残りはハードリンクで埋める
        for k in range(1, repeat):
            p = out / f"f_{index + k:04d}.png"
            if p.exists():
                p.unlink()
            os.link(first, p)

    # 描画は 1 コマ数 ms で、PNG の圧縮が律速になるので、圧縮はスレッドで並べる (cv2 はロックを外して動く)
    with ThreadPoolExecutor(n) as pool:
        jobs = []

        def sink(fr) -> None:
            nonlocal count
            raw = fr.pixels()
            slots.acquire()
            jobs.append(pool.submit(save, raw, fr.index, fr.repeat))
            count = max(count, fr.index + fr.repeat)

        getattr(mod, args["scene"])().render(frames=sink)
        for j in jobs:
            j.result()
    print(f"{count} frames")


if __name__ == "__main__":
    main(json.loads(sys.argv[1]))
