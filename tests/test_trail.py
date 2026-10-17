from types import SimpleNamespace

import numpy as np

from motion import trail


def _comp():
    return SimpleNamespace(width=320, height=180, fps=30, duration=4.0, name="t", build_dir="build")


def _frames(v):
    return [np.full((90, 160, 3), v, np.uint8) for _ in range(4)]


def test_records_changed_layers_and_a_return_to_an_older_version(tmp_path):
    proj = tmp_path / "p"
    proj.mkdir()
    code = proj / "project.py"
    code.write_text("A = 1\n")
    trail.record(proj, _comp(), "render", "最初", _frames(20))
    trail.record(proj, _comp(), "review", "同じ版のレビュー", _frames(21))       # 絵の差 1 は変化ではない
    code.write_text("A = 2\n")
    trail.record(proj, _comp(), "render", "試す", _frames(200))
    (proj / "edits.json").write_text("{}")
    trail.record(proj, _comp(), "render", "人が動かした", _frames(200))
    (proj / "edits.json").unlink()
    code.write_text("A = 1\n")
    trail.record(proj, _comp(), "render", "戻す", _frames(20))
    es = trail.load(proj)
    assert [e["changed"] for e in es[1:]] == [[], ["code", "picture"], ["edits"], ["code", "edits", "picture"]]
    assert es[-1]["back_to"] == 2 and trail.dead_ends(es) == {3, 4}
    assert (proj / "trail" / "003.jpg").exists()


def test_text_spans_join_consecutive_frames():
    per = [{}, {"h1": "見出し"}, {"h1": "見出し"}, {}, {"h1": "見出し", "s": "小見出し"}]
    sp = trail.text_spans(per, 10)
    assert sp["h1"] == ("見出し", [(0.1, 0.3), (0.4, 0.5)]) and sp["s"] == ("小見出し", [(0.4, 0.5)])


def test_build_writes_one_page_per_version(tmp_path, monkeypatch):
    proj = tmp_path / "p"
    proj.mkdir()
    (proj / "project.py").write_text("A = 1\n")
    for v in (20, 120):
        trail.record(proj, _comp(), "render", f"版 {v}", _frames(v))
    monkeypatch.setattr("motion.render.load_project", lambda p: SimpleNamespace(build_dir=str(tmp_path / "b")))
    mp4, png = trail.build(proj, per_page=0.2)
    import cv2
    cap = cv2.VideoCapture(str(mp4))
    assert int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) == 6 + 90       # 0.2 秒 + 最後の版は 3 秒
    assert cv2.imread(str(png)).shape[1] == 2 * 644 + 4
