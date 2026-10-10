import json
import os
import subprocess
import sys
from pathlib import Path

from motion import tune


def test_tune_values_can_be_overridden_for_one_render(tmp_path, monkeypatch):
    (tmp_path / "tune.json").write_text(json.dumps({"T": 2.0}))
    assert tune.tune(tmp_path, T=(1.0, 0.0, 5.0)).T == 2.0
    monkeypatch.setenv("MOTION_TUNE", json.dumps({"T": 3.5}))
    assert tune.tune(tmp_path, T=(1.0, 0.0, 5.0)).T == 3.5
    # 保存した値は変えない
    assert json.loads((tmp_path / "tune.json").read_text())["T"] == 2.0


def test_variants_render_each_clip_with_its_own_values(tmp_path):
    from motion import variants
    proj = Path(__file__).parent / "fixtures" / "mini"
    work = tmp_path / "projects" / "mini"
    import shutil
    shutil.copytree(proj, work)
    variants.save(work, {"start": 0.0, "end": 0.5, "chosen": None,
                         "variants": [{"name": "A"}, {"name": "B", "params": {}}]})
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).parent.parent))
    subprocess.run([sys.executable, "-m", "motion", "variants", str(work), "--scale", "0.2"], check=True, env=env,
                   cwd=tmp_path)
    from motion.render import load_project
    clips = sorted(p.name for p in (Path(load_project(work).build_dir) / "variants").glob("*.mp4"))
    assert clips == ["00-a.mp4", "01-b.mp4"]
