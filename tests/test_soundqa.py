import numpy as np

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
