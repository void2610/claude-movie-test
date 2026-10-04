"""重い前計算 (シミュレーション等) の結果をディスクに保存して、全ワーカーで共有する。"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Callable

import numpy as np


def _code_hash(fn: Callable) -> str:
    code = getattr(fn, "__code__", None)
    if code is None:
        return ""
    h = hashlib.sha1(code.co_code)
    h.update(repr(code.co_consts).encode())
    return h.hexdigest()


def cached(comp, name: str, fn: Callable[[], dict[str, np.ndarray]], *deps: Any) -> dict[str, np.ndarray]:
    """fn() の結果 (配列の dict) を build/<作品>/cache に保存して再利用する。

    deps と fn のコードが変わると作り直す。レンダリング前にメインプロセスで Scene.setup が
    一度呼ばれるので、各ワーカーはここでファイルを読むだけになる。
    """
    key = hashlib.sha1((name + repr(deps) + _code_hash(fn)).encode()).hexdigest()[:16]
    path = Path(comp.build_dir) / "cache" / f"{name}-{key}.npz"
    if path.exists():
        with np.load(path) as z:
            return {k: z[k] for k in z.files}
    data = fn()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp.npz")
    np.savez(tmp, **data)
    os.replace(tmp, path)
    return data
