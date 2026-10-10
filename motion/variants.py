"""1 つのショットの案を並べて選ぶ。書き出しが速いので、案を何本も作って細部を詰められる。

作品の variants.json に、見比べる区間と案を書く。案は build() の引数 (params) と tune の値 (tune) の違い:

    {"start": 2.0, "end": 4.0,
     "variants": [{"name": "A 現行", "note": "いまの値"},
                  {"name": "B 速い反転", "note": "反転を早める", "tune": {"T_FLIP": 1.8}},
                  {"name": "C 縦長", "params": {"aspect": "9:16"}}],
     "chosen": null}

    uv run python -m motion variants projects/x    # 全案の下書きを build/<作品>/variants/ に書き出す

スタジオの「案」で横に並べて同時に再生し、「これにする」で chosen に名前が入る。Claude はそれを読んで作品に取り込む。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path


def path_of(project_dir: Path) -> Path:
    return Path(project_dir) / "variants.json"


def load(project_dir: Path) -> dict | None:
    p = path_of(project_dir)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def save(project_dir: Path, data: dict) -> None:
    path_of(project_dir).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def slug(name: str, i: int) -> str:
    s = re.sub(r"[^0-9A-Za-z]+", "-", name).strip("-").lower()
    return f"{i:02d}-{s or 'variant'}"


def clip(build_dir: Path, name: str, i: int) -> Path:
    return Path(build_dir) / "variants" / f"{slug(name, i)}.mp4"


def render_all(project: str | Path, build_dir: Path, scale: float = 0.5) -> list[Path]:
    """全案を別プロセスで下書きとして書き出す (tune は import 時に読むので、案ごとにプロセスを分ける)。"""
    d = Path(project).resolve()
    d = d if d.is_dir() else d.parent
    data = load(d)
    if not data or not data.get("variants"):
        raise SystemExit(f"{path_of(d)} に案が無い (書き方は motion/variants.py の冒頭)")
    out = []
    for i, v in enumerate(data["variants"]):
        dst = clip(build_dir, v["name"], i)
        dst.parent.mkdir(parents=True, exist_ok=True)
        args = [sys.executable, "-m", "motion", "render", str(project), "--draft", "--scale", str(scale),
                "--start", str(data["start"]), "--end", str(data["end"]), "-o", str(dst)]
        for k, val in (v.get("params") or {}).items():
            args += ["--set", f"{k}={json.dumps(val) if not isinstance(val, str) else val}"]
        env = dict(os.environ, MOTION_TUNE=json.dumps(v.get("tune") or {}))
        print(f"variants: {i + 1}/{len(data['variants'])} {v['name']}", flush=True)
        subprocess.run(args, env=env, check=True, stdout=subprocess.DEVNULL)
        out.append(dst)
    print(f"-> {Path(build_dir) / 'variants'}")
    return out
