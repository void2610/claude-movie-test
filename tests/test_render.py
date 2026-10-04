import os
from pathlib import Path

import cv2
import numpy as np
import pytest

from motion import colorspace
from motion.render import FrameRenderer, load_project, prepare

MINI = Path(__file__).parent / "fixtures" / "mini"
GOLDEN = Path(__file__).parent / "golden"
GOLDEN_FRAMES = [0, 20, 40, 59]


@pytest.fixture(scope="module")
def renderer(tmp_path_factory):
    comp = load_project(MINI)
    comp.build_dir = str(tmp_path_factory.mktemp("build"))
    prepare(comp)
    return FrameRenderer(comp)


def test_deterministic(renderer):
    a = renderer.frame(33)
    b = renderer.frame(33)
    renderer.frame(5)
    c = renderer.frame(33)
    assert np.array_equal(a, b) and np.array_equal(a, c)


@pytest.mark.parametrize("f", GOLDEN_FRAMES)
def test_golden(renderer, f):
    """描画結果が基準画像から変わっていないか。意図した変更なら UPDATE_GOLDEN=1 で更新する。"""
    img = renderer.frame(f)
    path = GOLDEN / f"mini_{f:03d}.png"
    if os.environ.get("UPDATE_GOLDEN") or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(path), cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
        pytest.skip("golden updated")
    ref = cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)
    diff = np.abs(img.astype(int) - ref.astype(int))
    assert diff.max() <= 3, f"max diff {diff.max()} (mean {diff.mean():.3f})"


def test_linear_blend_of_black_and_white():
    # 白と黒の平均はリニア空間では 0.5、sRGB に戻すと 188 になる
    lin = (colorspace.SRGB_TO_LINEAR[0] + colorspace.SRGB_TO_LINEAR[255]) / 2
    assert round(float(colorspace.encode(np.array([lin]))[0]) * 255) == 188


def test_scaled_render_keeps_aspect(renderer):
    comp = renderer.comp
    small = FrameRenderer(comp, scale=0.5).frame(10)
    assert small.shape == (comp.height // 2, comp.width // 2, 3)
