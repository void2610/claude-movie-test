import numpy as np
import pytest

from motion import audio, sfx
from motion.scene import Composition, Cue
from motion.soundqa import check, picture_check


def test_picture_check_finds_each_kind_of_event():
    m = np.zeros(60)
    m[30] = 20.0                                    # 画面全体が変わる
    assert picture_check("cut", 30, m)[0]
    assert not picture_check("cut", 40, m)[0]
    move = np.zeros(60)
    move[10:21] = np.r_[np.linspace(0.2, 3, 6), np.linspace(2.5, 0.2, 5)]   # 15 コマ目が最も速い
    assert picture_check("move", 15, move)[0]
    assert not picture_check("move", 25, move)[0]
    land = np.zeros(60)
    land[20:35] = np.linspace(4, 1, 15)              # 35 コマ目で止まる
    assert picture_check("land", 35, land)[0]
    assert not picture_check("land", 45, land)[0]


def test_cue_is_still_a_number():
    c = Cue(1.5, "land", hero=True)
    assert c + 1 == 2.5 and sorted([Cue(2.0), c])[0] is c
    assert c.kind == "land" and c.hero


def _mix(tmp_path, hero_gain):
    mx = audio.Mix(3.0, tail=0.5)
    for i in range(12):
        mx.tone(i * 0.25, 0.24, "A2", wave="saw", gain_db=-6, bus="music")
    mx.sfx(sfx.impact(0.8), 1.5, gain_db=hero_gain, hero=True)
    return mx.render(tmp_path / "a.wav", lufs=-14)


def test_hero_sound_that_stands_out_passes(tmp_path):
    comp = Composition(duration=3.0, fps=30, cues=[Cue(1.5, hero=True)])
    q = check(comp, _mix(tmp_path, 0.0), np.zeros(90))
    assert [f.rule for f in q.findings] == []
    assert q.listen and abs(q.listen[0][0] - 1.5) < 1e-6
    assert any(r == "sound: 合成の効果音" for _, r, _ in q.warnings)


def test_buried_hero_sound_and_missing_hero_are_errors(tmp_path):
    comp = Composition(duration=3.0, fps=30, cues=[Cue(1.5, hero=True), Cue(2.5, hero=True)])
    q = check(comp, _mix(tmp_path, -40.0), np.zeros(90))
    rules = {(f.rule, f.t) for f in q.findings}
    assert ("sound: 聞こえない", 1.5) in rules
    assert ("sound: 見せ場の音", 2.5) in rules


def test_unplanned_silence_is_an_error_unless_declared(tmp_path):
    mx = audio.Mix(3.0, tail=0.2)
    mx.tone(0.0, 1.0, "A3", gain_db=-6, bus="music")
    wav = mx.render(tmp_path / "s.wav", lufs=-14)
    comp = Composition(duration=3.0, fps=30)
    assert any(f.rule == "sound: 無音" for f in check(comp, wav, np.zeros(90)).findings)
    comp.silence_ok = [(1.0, 3.0)]
    assert not any(f.rule == "sound: 無音" for f in check(comp, wav, np.zeros(90)).findings)


def test_hero_gap_must_be_filled_by_the_riser(tmp_path):
    def mix(riser):
        mx = audio.Mix(3.0, tail=0.5)
        for i in range(12):
            mx.tone(i * 0.25, 0.24, "A2", wave="saw", gain_db=-6, bus="music")
        mx.hero(2.0, hit=sfx.impact(0.8), boom=None, riser=riser, stop_before=0.4, build=0.8)
        return mx.render(tmp_path / f"{len(riser.buf[0])}.wav", lufs=-14)

    comp = Composition(duration=3.0, fps=30, cues=[Cue(2.0, hero=True)])
    # 山の 20ms 前まで鳴らないライザー (短い逆再生) では、音楽を止めた 0.4 秒が途切れて聞こえる
    n = int(0.6 * 48000)
    spike = np.zeros((2, n), np.float32)
    spike[:, -960:] = np.random.default_rng(0).normal(0, 0.3, (2, 960))
    q = check(comp, mix(sfx.Sound(spike, (n - 1) / 48000)), np.zeros(90))
    assert any(f.rule == "sound: 見せ場の溜め" for f in q.findings)
    q = check(comp, mix(sfx.riser(1.5)), np.zeros(90))
    assert not any(f.rule == "sound: 見せ場の溜め" for f in q.findings)


def test_loudness_curve_agrees_with_bs1770():
    import pyloudnorm

    from motion.soundqa import loudness_curve
    rng = np.random.default_rng(1)
    y = (rng.standard_normal((2, 48000 * 4)) * 0.1).astype(np.float64)
    _, L = loudness_curve(y, 4.0, 1.0)
    assert L[0] == pytest.approx(pyloudnorm.Meter(48000).integrated_loudness(y.T), abs=0.2)


def test_shape_finds_a_late_start_and_a_hole():
    from motion.soundqa import shape
    t = np.arange(48000 * 8) / 48000
    y = np.vstack([np.sin(2 * np.pi * 220 * t) * 0.3] * 2)
    y[:, :int(1.2 * 48000)] = 0                     # 1.2 秒まで鳴らない
    y[:, int(4 * 48000):int(6.5 * 48000)] *= 0.001  # 2.5 秒の穴
    sh = shape(y, -12.0, loop=False)
    assert sh["first_sound_s"] == pytest.approx(1.2, abs=0.06)
    assert sh["max_gap_s"] == pytest.approx(2.5, abs=0.15) and sh["max_gap_at"] == pytest.approx(4.0, abs=0.1)


def test_blemishes_catch_dc_edges_and_digital_holes():
    from motion.soundqa import blemishes
    t = np.arange(48000 * 2) / 48000
    clean = np.vstack([np.sin(2 * np.pi * 220 * t) * np.hanning(len(t)) * 0.5] * 2)
    assert blemishes(clean, loop=False) == []
    bad = clean + 0.05
    bad[:, 48000:48000 + 480] = 0                   # 10ms の 0
    rules = {r for _, r, _ in blemishes(bad, loop=False)}
    assert {"sound: 直流", "sound: 端のクリック", "sound: 0 の穴"} <= rules


def test_machine_gun_needs_the_same_take_level_and_pitch():
    from motion.soundqa import machine_gun
    ev = lambda t, g=-6.0, p=0.0: dict(t=t, origin="key/a", gain_db=g, pitch=p, layer=False)  # noqa: E731
    assert machine_gun([ev(i * 0.1) for i in range(5)])
    assert not machine_gun([ev(i * 0.1, p=(i % 3) * 0.3) for i in range(5)])
    assert not machine_gun([ev(i * 2.0) for i in range(5)])


def test_sync_chance_is_high_for_a_dense_mix_and_low_for_sparse_hits(tmp_path):
    from motion.review import _attack_offsets, _rise_curve, sync_chance
    dense = audio.Mix(8.0, tail=0.0)
    for i in range(64):
        dense.tone(i * 0.125, 0.05, "A4", wave="square", env=(0.001, 0.02, 0.5, 0.02), gain_db=-6)
    sparse = audio.Mix(8.0, tail=0.0)
    cuts = [1.0, 3.0, 5.0, 7.0]
    for c in cuts:
        sparse.tone(c, 0.05, "A4", wave="square", env=(0.001, 0.02, 0.5, 0.02), gain_db=-6)
    for name, mx, lo, hi in (("d", dense, 0.6, 1.0), ("s", sparse, 0.0, 0.2)):
        curve = _rise_curve(str(mx.render(tmp_path / f"{name}.wav", lufs=-16)))
        assert all(st >= 1.8 for _, st in _attack_offsets(curve, cuts))
        assert lo <= sync_chance(curve, cuts, 8.0) <= hi
