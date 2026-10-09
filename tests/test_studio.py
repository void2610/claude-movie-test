import json

from motion.studio import Notes, Studio
from motion.tune import save, tune


def test_tune_defaults_saved_values_and_schema(tmp_path):
    p = tune(tmp_path, T=(2.0, 1.0, 3.0), N=(12, 6, 24), C="#FACC15", H="ONE.", B=False)
    assert (p.T, p.N, p.C, p.H, p.B) == (2.0, 12, "#FACC15", "ONE.", False)
    kinds = {s["key"]: s["type"] for s in p.schema()}
    assert kinds == {"T": "number", "N": "number", "C": "color", "H": "text", "B": "bool"}
    save(p.path, {"T": 2.5, "N": 9.6, "H": "TWO."})
    q = tune(tmp_path, T=(2.0, 1.0, 3.0), N=(12, 6, 24), C="#FACC15", H="ONE.", B=False)
    assert (q.T, q.N, q.H) == (2.5, 10, "TWO.")
    save(q.path, {"T": None})
    assert "T" not in json.loads(q.path.read_text())


def test_notes_roundtrip(tmp_path):
    n = Notes(tmp_path / "notes.md")
    n.add(8.3, "線が細い")
    n.add(2.25, "見出しが\n切れている")
    rows = n.load()
    assert [(r["t"], r["text"]) for r in rows] == [(2.25, "見出しが 切れている"), (8.3, "線が細い")]
    n.update(0, done=True)
    n.update(1, delete=True)
    rows = n.load()
    assert len(rows) == 1 and rows[0]["done"]
    assert "- [x] 2.25s" in (tmp_path / "notes.md").read_text(encoding="utf-8")


def test_latest_findings_parses_review_md(tmp_path):
    (tmp_path / "reviews").mkdir()
    (tmp_path / "reviews" / "20260101-000000.md").write_text(
        "# レビュー\n\n## エラー (1 件)\n\n- 8.30s `check: 青`: 0/20 点\n\n## 自動計測\n\n- 1.00s `x`: 無視\n",
        encoding="utf-8")
    (tmp_path / "project.py").write_text("")
    st = Studio(str(tmp_path), 0.5, False, None)
    assert st.findings == [{"t": 8.3, "rule": "check: 青", "detail": "0/20 点"}]


def test_apply_edits_renders_current_frame_without_reloading(tmp_path):
    import shutil
    from pathlib import Path
    src = Path(__file__).parent / "fixtures" / "mini" / "project.py"
    shutil.copy(src, tmp_path / "project.py")
    st = Studio(str(tmp_path), 0.25, False, 1)
    st.reload()
    comp = st.comp
    (tmp_path / "edits.json").write_text('{"x": {"dx": 10}}', encoding="utf-8")
    v0 = st.version
    v = st.apply_edits(30)
    assert v == v0 + 1 and st.comp is comp          # 作品は読み直さない
    assert 30 in st.frames                          # 今のコマは返す前に描き終えている
    assert st.comp._edits.of("x") == {"dx": 10}
    st._stop.set()
