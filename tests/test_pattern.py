from fractions import Fraction as F

import pytest

from motion.pattern import PatternError, bjorklund, events, note_number, sample_name


def onsets(s, cycles=1):
    return [(e.start, e.value) for e in events(s, cycles)]


def test_sequence_rest_and_subdivision():
    assert onsets("bd ~ [sd sd]") == [(0, "bd"), (F(2, 3), "sd"), (F(5, 6), "sd")]


def test_stack_speed_and_slow():
    got = onsets("bd*2, hh*4")
    assert [t for t, v in got if v == "bd"] == [0, F(1, 2)]
    assert [t for t, v in got if v == "hh"] == [0, F(1, 4), F(1, 2), F(3, 4)]
    assert onsets("bd/2", 2) == [(0, "bd")]                 # 2 周期に 1 回
    assert events("bd/2", 2)[0].end == 2


def test_alternation_advances_each_cycle_and_nests():
    assert [v for _, v in onsets("<a b <c d>>", 6)] == ["a", "b", "c", "a", "b", "d"]


def test_euclid_replicate_elongate():
    assert bjorklund(3, 8) == [True, False, False, True, False, False, True, False]
    assert [t for t, _ in onsets("bd(3,8)")] == [0, F(3, 8), F(6, 8)]
    assert [t for t, _ in onsets("bd!3 sd")] == [0, F(1, 4), F(1, 2), F(3, 4)]
    assert onsets("bd@3 sd") == [(0, "bd"), (F(3, 4), "sd")]


def test_degrade_is_deterministic():
    a, b = onsets("hh*16?", 4), onsets("hh*16?", 4)
    assert a == b and 16 < len(a) < 48


def test_events_keep_source_span_for_highlighting():
    s = "808bd:3 [~ cp]"
    e = events(s)
    assert [s[slice(*x.span)] for x in e] == ["808bd:3", "cp"]
    assert sample_name("808bd:3") == ("808bd", 3)


def test_notes_and_errors():
    assert note_number("c4") == 60 and note_number("a3") == 57 and note_number("eb") == 51 and note_number("62") == 62
    assert note_number("bd") is None
    with pytest.raises(PatternError):
        events("bd [sd")
