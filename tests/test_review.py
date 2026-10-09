from pathlib import Path

import pytest

from motion.review import review
from motion.shots import Shot, ShotList

MINI = Path(__file__).parent / "fixtures" / "mini"


def test_shotlist_from_md(tmp_path):
    md = tmp_path / "shotlist.md"
    md.write_text("| 時間 | ショット | 目的 | 入り | 出 |\n|---|---|---|---|---|\n"
                  "| 0-2 | hook | 目を止める | 黒 | 文字 |\n| 2-5.5 | proof | 実演 | 文字 | 画面 |\n", encoding="utf-8")
    sl = ShotList.from_md(md)
    assert [s.name for s in sl] == ["hook", "proof"]
    assert sl["proof"].dur == pytest.approx(3.5)
    assert sl.cuts == [2.0]
    assert sl.at(3.0).name == "proof"
    assert sl["hook"].purpose == "目を止める" and sl["proof"].exit == "画面"


def test_shotlist_rejects_overlap():
    with pytest.raises(ValueError):
        ShotList([Shot("a", 0, 2), Shot("b", 1.5, 3)])


def test_review_writes_sheet_and_notes(tmp_path):
    png = review(MINI, tmp_path)
    md = png.with_suffix(".md").read_text(encoding="utf-8")
    assert png.exists() and png.stat().st_size > 10_000
    assert "静止の割合" in md and "大きな欠点" in md
