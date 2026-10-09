import os

import numpy as np
import pyloudnorm
import pytest

from motion import audio


def test_juce_base64_roundtrip():
    for data in (b"", b"\x00", b"sub3\x82\xc4" + bytes(range(256)) * 3):
        enc = audio._juce_b64encode(data)
        assert audio._juce_b64decode(enc) == data


def test_midi_and_hz():
    assert audio.midi("C4") == 60
    assert audio.midi("F#2") == 42
    assert audio.hz("A4") == pytest.approx(440.0)


def test_limiter_respects_ceiling():
    rng = np.random.default_rng(0)
    y = (rng.standard_normal((2, 48000)) * 0.8).astype(np.float32)
    out = audio.limit(y, 48000, ceiling_db=-1.0)
    assert np.abs(out).max() <= audio.db(-1.0) + 1e-6


def test_mix_hits_target_loudness(tmp_path):
    mx = audio.Mix(2.0)
    for i in range(8):
        mx.tone(i * 0.25, 0.2, "A3", wave="saw", gain_db=-6)
    path = mx.render(tmp_path / "a.wav", lufs=-16)
    y = audio.load(path)
    assert pyloudnorm.Meter(48000).integrated_loudness(y.T.astype(np.float64)) == pytest.approx(-16, abs=0.3)
    assert y.shape[1] == 2 * 48000


@pytest.mark.skipif(not os.path.exists(audio.SURGE), reason="Surge XT が無い")
def test_surge_patch_changes_sound():
    p = audio._plugin(audio.SURGE)
    msgs = [(bytes([0x90, 57, 100]), 0.0), (bytes([0x80, 57, 0]), 0.8)]

    def centroid(y):
        sp = np.abs(np.fft.rfft(y[0]))
        fr = np.fft.rfftfreq(len(y[0]), 1 / 48000)
        return (sp * fr).sum() / sp.sum()

    audio.surge_load(p, "Pads/Pad 1")
    a = p(msgs, duration=1.0, sample_rate=48000)
    audio.surge_load(p, "Basses/Bass 1")
    b = p(msgs, duration=1.0, sample_rate=48000)
    assert np.abs(a).max() > 0.01 and np.abs(b).max() > 0.01
    assert abs(centroid(a) - centroid(b)) > 100


def test_loop_render_wraps_tail_to_head(tmp_path):
    mx = audio.Mix(1.0, tail=1.0)
    mx.tone(0.8, 0.5, "A3", wave="sine", env=(0.001, 0.1, 1.0, 0.3), gain_db=-6)
    y = audio.load(mx.render(tmp_path / "loop.wav", lufs=-20, loop=True))
    assert np.abs(y[:, :int(0.1 * 48000)]).max() > 0.01      # 1 秒をはみ出した音が頭に回り込む
    assert np.abs(y[:, -100:]).max() > 0.01                   # 末尾をフェードで切らない
