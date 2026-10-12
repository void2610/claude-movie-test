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
    res = review(MINI, tmp_path)
    png, md = res.png, res.md.read_text(encoding="utf-8")
    assert png.exists() and png.stat().st_size > 10_000
    assert "静止の割合" in md and "大きな欠点" in md


def test_scaffold_renders(tmp_path):
    from motion.render import FrameRenderer, load_project
    from motion.scaffold import create
    d = create("sample", root=tmp_path / "projects", aspect="1:1", dur=16)
    comp = load_project(d)
    assert (comp.width, comp.height) == (1080, 1080)
    assert len(comp.shots) == 5 and comp.duration == 16
    assert FrameRenderer(comp, 0.2).frame(60).mean() > 5


TEXT_ISSUES = '''
from motion import Composition, scene, text
from motion.checks import Waiver
from motion.nodes import node


def build():
    comp = Composition(width=640, height=360, fps=20, duration=2.0, background="#000000", linear=False)
    comp.waivers.append(Waiver("text-small", "読ませない飾り", elements=("tin?",)))
    comp.waivers.append(Waiver("text-overlap", "片方だけ当たる例外は効かない", elements=("title",)))

    @scene(0, 2.0)
    def s(c, ctx):
        with node(c, ctx, "title", origin=(40, 120)) as n:
            text.text(n.c, "TITLE", 40, 120, size=80)
        with node(c, ctx, "over", origin=(60, 120)) as n:
            if 0.5 <= n.t < 1.0:                       # 0.5 秒だけ見出しに重なる
                text.text(n.c, "OVER", 60, 120, size=80)
        with node(c, ctx, "tiny", origin=(40, 300)) as n:
            text.text(n.c, "tiny caption", 40, 300, size=14)
        with node(c, ctx, "slide", origin=(300, 200)) as n:
            x = 300 if n.t >= 1.0 else 700 - 400 * n.t       # 1 秒かけて画面の外から滑り込み、中で止まる
            text.text(n.c, "SLIDE IN", x, 200, size=40)
        with node(c, ctx, "edge", origin=(560, 250)) as n:
            if n.t >= 1.2:                                     # 縁で切れたまま止まる
                text.text(n.c, "EDGE CUT", 560, 250, size=40)

    comp.add(s)
    return comp
'''


def test_text_findings_group_runs_and_point_to_code(tmp_path):
    from motion.render import load_project
    from motion.review import text_findings
    (tmp_path / "project.py").write_text(TEXT_ISSUES, encoding="utf-8")
    fds = text_findings(tmp_path, load_project(tmp_path), workers=2)
    by = {fd.rule: fd for fd in fds}
    assert sorted(by) == ["text-cut", "text-overlap", "text-small"] and len(fds) == 3
    assert by["text-overlap"].t == pytest.approx(0.5) and "0.50〜1.00s" in by["text-overlap"].detail
    assert by["text-cut"].t == pytest.approx(1.25) and "「edge」" in by["text-cut"].detail   # 滑り込みの途中は数えない
    assert all(fd.boxes and fd.frame is not None and "project.py:" in fd.where for fd in fds)
    assert by["text-small"].waived == "読ませない飾り" and by["text-small"].elements == ["tiny"]
    assert by["text-overlap"].waived is None and by["text-cut"].waived is None
    # 文字の大きさはデザインの判断なので注意に留め、重なりと縁での見切れだけをエラーにする
    assert by["text-small"].note and not by["text-overlap"].note and not by["text-cut"].note
