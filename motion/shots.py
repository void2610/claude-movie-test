"""ショットリスト。各ショットの時刻・目的・入りと出の状態を持ち、タイミングとレビューの元にする。

shotlist.md の表 (| 時間 | ショット | 目的 | 入り | 出 |) から読める。時間は「0-2」「2.5-5」のように秒で書く。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Shot:
    name: str
    start: float
    end: float
    purpose: str = ""
    enter: str = ""
    exit: str = ""

    @property
    def dur(self) -> float:
        return self.end - self.start

    def at(self, frac: float) -> float:
        """ショット内の割合 (0〜1) の時刻。"""
        return self.start + self.dur * frac


class ShotList:
    def __init__(self, shots: list[Shot]):
        self.shots = sorted(shots, key=lambda s: s.start)
        names = [s.name for s in self.shots]
        if len(set(names)) != len(names):
            raise ValueError(f"ショット名が重複している: {names}")
        for a, b in zip(self.shots, self.shots[1:]):
            if b.start < a.end - 1e-6:
                raise ValueError(f"ショットが重なっている: {a.name} ({a.end}) と {b.name} ({b.start})")

    def __getitem__(self, name: str) -> Shot:
        for s in self.shots:
            if s.name == name:
                return s
        raise KeyError(f"ショット {name!r} は無い。あるのは {[s.name for s in self.shots]}")

    def __iter__(self):
        return iter(self.shots)

    def __len__(self) -> int:
        return len(self.shots)

    def at(self, t: float) -> Shot | None:
        return next((s for s in self.shots if s.start <= t < s.end), None)

    @property
    def cuts(self) -> list[float]:
        """ショットの境目 (最初のショットの頭は含まない)。"""
        return [s.start for s in self.shots[1:]]

    @property
    def duration(self) -> float:
        return self.shots[-1].end if self.shots else 0.0

    @classmethod
    def from_md(cls, path: str | Path) -> ShotList:
        rows = []
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) < 2 or not re.fullmatch(r"\d+(\.\d+)?\s*-\s*\d+(\.\d+)?", cells[0]):
                continue
            a, b = (float(x) for x in cells[0].split("-"))
            rows.append(Shot(cells[1], a, b, *(cells[2:5] + [""] * (5 - len(cells)))[:3]))
        if not rows:
            raise ValueError(f"{path} にショットの行が無い (| 0-2 | 名前 | 目的 | 入り | 出 | の形で書く)")
        return cls(rows)
