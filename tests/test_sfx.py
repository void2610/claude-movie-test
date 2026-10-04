import numpy as np
import pytest

from motion import audio, sfx


def centroid(x):
    sp = np.abs(np.fft.rfft(x))
    fr = np.fft.rfftfreq(len(x), 1 / sfx.SR)
    return (sp * fr).sum() / max(sp.sum(), 1e-9)


@pytest.mark.parametrize("make", [sfx.whoosh, sfx.riser, sfx.impact, sfx.click, sfx.glitch, sfx.reverse_swell])
def test_sounds_are_finite_and_bounded(make):
    s = make()
    assert s.buf.shape[0] == 2 and s.buf.dtype == np.float32
    assert np.isfinite(s.buf).all() and 0.1 < np.abs(s.buf).max() <= 1.0
    assert 0.0 <= s.peak <= s.duration


def test_whoosh_loudest_near_peak():
    s = sfx.whoosh(0.8, rise=0.5)
    env = np.abs(s.buf).mean(axis=0)
    k = int(0.05 * sfx.SR)
    smooth = np.convolve(env, np.ones(k) / k, mode="same")
    assert abs(np.argmax(smooth) / sfx.SR - s.peak) < 0.12


def test_riser_gets_brighter():
    s = sfx.riser(2.0, tone=False)
    a, b = s.buf[0, : sfx.SR // 2], s.buf[0, -sfx.SR // 2:]
    assert centroid(b) > centroid(a) * 3


def test_mix_aligns_peak():
    mx = audio.Mix(2.0)
    mx.sfx(sfx.impact(0.5), 1.0)
    y = mx.bus("sfx")
    first = np.argmax(np.abs(y[0]) > 1e-4) / sfx.SR
    assert first == pytest.approx(1.0, abs=0.002)
