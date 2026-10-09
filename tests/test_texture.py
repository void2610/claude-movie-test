import numpy as np

from motion import Composition
from motion.scene import Ctx
from motion.texture import _paper_rgb, halftone, misregister


def test_paper_is_deterministic_and_subtle():
    a = _paper_rgb(960, 540, "#EDE6D6", 0.6, 1)
    b = _paper_rgb(960, 540, "#EDE6D6", 0.6, 1)
    assert np.array_equal(a, b)
    luma = a.mean(axis=2)
    assert 180 < luma.mean() < 245 and luma.std() < 25


def test_halftone_turns_gray_into_dots():
    img = np.full((540, 960, 3), 0.5, np.float32)
    out = halftone(9.0)(img, Ctx(0, 0, Composition()))
    assert out.max() > 0.9 and out.min() < 0.2          # 中間の灰色が紙の白とインクの点に分かれる
    assert abs(out.mean() - 0.5) < 0.2


def test_misregister_shifts_red_and_blue_opposite():
    img = np.zeros((108, 192, 3), np.float32)
    img[:, 90:100] = 1.0
    out = misregister(20.0, angle=0)(img, Ctx(0, 0, Composition()))
    assert np.argmax(out[50, :, 0]) > 90 > np.argmax(out[50, :, 2])
