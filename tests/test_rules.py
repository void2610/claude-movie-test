import pytest

from motion import rules


@pytest.mark.parametrize("kind", list(rules.RULES))
def test_enter_reaches_one_and_leave_reaches_zero(kind):
    r = rules.rule(kind)
    assert rules.enter(kind, 0.0, 0.0) == pytest.approx(0.0, abs=1e-6)
    assert rules.enter(kind, 10.0, 0.0) == pytest.approx(1.0, abs=1e-3)
    assert rules.leave(kind, 5.0, 5.0) == pytest.approx(0.0, abs=1e-6)
    assert rules.leave(kind, 5.0 - r.dur, 5.0) == pytest.approx(1.0, abs=1e-6)


def test_overshoot_only_where_intended():
    peak = lambda k: max(rules.enter(k, t / 200, 0.0) for t in range(400))  # noqa: E731
    assert peak("panel") < 1.01 and peak("headline") < 1.01
    assert peak("playful") > 1.1


def test_read_time_and_stagger():
    assert rules.read_time("Hi") == 0.7
    assert rules.read_time("すべてのフレームは、コードでできている。") > rules.read_time("All frames are code.")
    starts = [rules.stagger(i, 20, 1.0) for i in range(20)]
    assert starts[-1] - starts[0] <= 0.5 + 1e-9
    assert rules.scale_in("panel", 0.0) == pytest.approx(0.94)
