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


def test_onion_stacks_the_moving_parts(tmp_path):
    import cv2

    from motion.onion import onion
    out = onion(Path(__file__).parent / "fixtures" / "mini", 0.0, 1.0, n=5, scale=0.25, out=tmp_path / "o.png")
    img = cv2.imread(str(out))
    assert img is not None and img.shape[0] > 44


def test_pattern_code_lights_the_word_that_is_sounding():
    import skia

    from motion import audio, overlay
    from motion.scene import Composition, Ctx
    comp = Composition(width=640, height=120, fps=60, duration=2, bpm=120)
    code = 's("808bd ~ cp ~")'
    played = audio.Mix(2.0).pattern("808bd ~ cp ~", comp.timeline)

    def yellow(t):
        s = skia.Surface(640, 120)
        c = s.getCanvas()
        c.clear(skia.Color(0, 0, 0))
        overlay.pattern_code(c, Ctx(t, t * 60, comp, 0, 2), code, played, 20, 60, size=30, hi="#FFD000")
        img = s.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)
        m = (img[..., 0] > 200) & (img[..., 1] > 150) & (img[..., 2] < 80)
        xs = np.nonzero(m)[1]
        return (xs.min(), xs.max()) if len(xs) else None

    first, second = yellow(0.01), yellow(1.01)            # 808bd は 0 秒、cp は 1 秒 (1 小節 2 秒の半分)
    assert first and second and second[0] > first[1]     # 光る語が右へ移る
    assert yellow(0.7) is None                            # 休符の間は何も光らない
