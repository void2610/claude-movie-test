"""スタジオから調整できる作品のパラメータ。値は作品の tune.json に保存され、無ければ既定値を使う。

    P = tune(HERE, T_FLIP=(2.0, 1.0, 3.0), ACCENT="#FACC15", H1="ONE ATTRIBUTE.", GRAIN=(0.02, 0, 0.1))
    T_FLIP = P.T_FLIP

数値は (既定値, 最小, 最大) で範囲を与えるとスライダーになる。"#" で始まる文字列は色、その他の文字列は文言。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class Tune:
    def __init__(self, path: Path, spec: dict[str, dict], values: dict[str, Any]):
        self.path = path
        self.spec = spec
        self.values = values

    def __getattr__(self, k: str) -> Any:
        try:
            return self.__dict__["values"][k]
        except KeyError as e:
            raise AttributeError(k) from e

    def schema(self) -> list[dict]:
        return [{"key": k, **s, "value": self.values[k]} for k, s in self.spec.items()]


def _kind(default: Any) -> dict:
    if isinstance(default, tuple):
        v, lo, hi = default
        step = 1 if isinstance(v, int) and isinstance(lo, int) and isinstance(hi, int) else (hi - lo) / 200
        return {"type": "number", "default": v, "min": lo, "max": hi, "step": step}
    if isinstance(default, bool):
        return {"type": "bool", "default": default}
    if isinstance(default, (int, float)):
        return {"type": "number", "default": default, "min": None, "max": None, "step": 0.01}
    if isinstance(default, str) and default.startswith("#") and len(default) in (4, 7):
        return {"type": "color", "default": default}
    return {"type": "text", "default": default}


def tune(project_dir: str | Path, **defaults: Any) -> Tune:
    d = Path(project_dir)
    path = d / "tune.json"
    saved = {}
    if path.exists():
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            saved = {}
    # 案の書き出し (motion variants) では、保存した値を変えずにその案の値で上書きする
    saved.update(json.loads(os.environ.get("MOTION_TUNE", "{}")))
    spec = {k: _kind(v) for k, v in defaults.items()}
    values = {}
    for k, s in spec.items():
        v = saved.get(k, s["default"])
        if s["type"] == "number" and isinstance(s["default"], int) and s.get("step") == 1:
            v = int(round(v))
        values[k] = v
    return Tune(path, spec, values)


def save(path: str | Path, updates: dict[str, Any]) -> dict:
    """tune.json に値を書く。既定値と同じものも残す (どの値を触ったかが分かるように)。"""
    p = Path(path)
    cur = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    for k, v in updates.items():
        if v is None:
            cur.pop(k, None)
        else:
            cur[k] = v
    p.write_text(json.dumps(cur, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return cur
