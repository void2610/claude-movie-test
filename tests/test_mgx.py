from pathlib import Path

import numpy as np
import pytest
import skia

pytest.importorskip("manimgx")

from motion import Composition  # noqa: E402
from motion.mgx import MgxPlate  # noqa: E402
from motion.scene import Ctx  # noqa: E402

SCENES = Path(__file__).parent / "fixtures" / "mgx" / "scenes.py"


def test_plate_is_transparent_and_follows_comp_time(tmp_path):
    comp = Composition(width=160, height=90, fps=20, duration=2, background="#000000", linear=False)
    comp.project_dir, comp.build_dir = str(tmp_path), str(tmp_path / "build")
    plate = MgxPlate(SCENES, "Dot", start=1.0, params={"radius": 2.0})
    plate.prepare(comp)
    assert plate.frames(comp) >= 12                       # 0.6 秒 × 20fps (同じ画面が続くコマも埋まる)
    s = skia.Surface(160, 90)
    c = s.getCanvas()

    def at(t):
        c.clear(skia.Color(0, 0, 255))
        plate.draw(c, Ctx(t, t * 20, comp, 0.0, 2.0))
        return s.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)

    end = at(1.6)
    assert tuple(end[45, 80, :3]) == pytest.approx((247, 217, 111), abs=3)   # 中央は Manim の YELLOW (#F7D96F) の点
    assert tuple(end[5, 5, :3]) == (0, 0, 255)            # 背景は透けて下の青が見える
    assert np.abs(at(1.0).astype(int) - end).mean() > 1   # 開始時刻はまだ消えている途中 (作品の時刻で引く)
    mtime = next((Path(comp.build_dir) / "mgx").glob("Dot-*/f_0000.png")).stat().st_mtime
    plate.prepare(comp)                                   # 入力が同じなら作り直さない
    assert next((Path(comp.build_dir) / "mgx").glob("Dot-*/f_0000.png")).stat().st_mtime == mtime
