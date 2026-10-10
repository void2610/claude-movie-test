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


def _bed_mix(dur=4.0):
    mx = audio.Mix(dur, tail=0.5)
    for i in range(int(dur / 0.25)):
        mx.tone(i * 0.25, 0.24, "A2", wave="saw", gain_db=-6, bus="music")
    return mx


def test_auto_gain_follows_the_music_level():
    from motion import sfx
    gains = []
    for music_db in (-30.0, -6.0):
        mx = audio.Mix(2.0, tail=0.5)
        mx.tone(0.0, 2.0, "A2", wave="saw", gain_db=music_db, bus="music")
        ev = mx.sfx(sfx.impact(0.6), 1.0, gain_db=None)
        mx.mixdown()
        gains.append(ev["gain_db"])
    # 音楽が 24dB 大きいと、同じだけ浮かせるために効果音も大きくなる
    assert gains[1] - gains[0] > 15


def test_hero_layers_stops_the_music_and_builds(tmp_path):
    from motion import sfx
    from motion.scene import Composition, Cue
    from motion.soundqa import check
    mx = _bed_mix()
    ev = mx.hero(2.0, hit=sfx.impact(0.8), boom=sfx.impact(1.2, f_start=90, f_end=30, seed=5),
                 riser=sfx.riser(1.5))
    path = mx.render(tmp_path / "h.wav", lufs=-14)
    boom = next(e for e in mx.events if e["t"] == 2.0 and not e["hero"] and e["dur"] > 1.0)
    assert boom["gain_db"] == round(ev["gain_db"] - 4, 2)
    bed = audio.load(str(tmp_path / "h.bed.wav"))
    rms = lambda a, b: float(np.sqrt(np.mean(bed[:, int(a * 48000):int(b * 48000)] ** 2)))  # noqa: E731
    # 直前 0.4 秒の音楽は止まっている
    assert rms(1.7, 1.98) < rms(1.0, 1.3) * 0.2
    q = check(Composition(duration=4.0, fps=30, cues=[Cue(2.0, hero=True)]), path, np.zeros(120))
    assert [f.rule for f in q.findings] == []


def test_hp_build_removes_low_end_toward_the_cue():
    t = np.arange(48000 * 2) / 48000
    y = np.vstack([np.sin(2 * np.pi * 60 * t)] * 2).astype(np.float32)
    out = audio._hp_build(y, 2.0, 2.0, 48000)
    early, late = np.abs(out[0, 4800:9600]).max(), np.abs(out[0, -4800:]).max()
    assert late < early * 0.3
