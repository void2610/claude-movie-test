import math

import pytest

from motion import easing
from motion.anim import Keys, impact, progress, spring, stagger, tween, window
from motion.timeline import Timeline

EASES = [name for name in dir(easing) if name.split("_")[0] in {"linear", "in", "out", "inout"}] + [
    "snap", "whip", "settle"]


@pytest.mark.parametrize("name", EASES)
def test_easing_endpoints(name):
    e = easing.get(name)
    assert e(0.0) == pytest.approx(0.0, abs=1e-6)
    assert e(1.0) == pytest.approx(1.0, abs=1e-6)


def test_cubic_bezier_matches_linear():
    e = easing.cubic_bezier(1 / 3, 1 / 3, 2 / 3, 2 / 3)
    for x in (0.1, 0.5, 0.9):
        assert e(x) == pytest.approx(x, abs=1e-4)


def test_timeline():
    tl = Timeline(bpm=120, offset=0.1)
    assert tl.beat(2) == pytest.approx(1.1)
    assert tl.bar(1) == pytest.approx(2.1)
    assert tl.beat_at(1.1) == pytest.approx(2.0)
    assert tl.since_beat(1.35) == pytest.approx(0.25)
    assert tl.pulse(tl.beat(3)) == pytest.approx(1.0)


def test_tween_and_progress_clamp():
    assert tween(-1, 0, 1, 10, 20) == 10
    assert tween(2, 0, 1, 10, 20) == 20
    assert tween(0.5, 0, 1, (0, 0), (2, 4)) == (1, 2)
    assert progress(0.5, 0, 1, easing.in_quad) == pytest.approx(0.25)


def test_keys():
    k = Keys((0, 0.0), (1, 10.0, easing.linear), (2, 0.0))
    assert k(-1) == 0.0
    assert k(0.5) == pytest.approx(5.0)
    assert k(1.5) == pytest.approx(5.0)
    assert k(3) == 0.0


def test_spring_settles():
    assert spring(0, 0) == 0.0
    assert spring(5, 0, freq=2, damping=0.3) == pytest.approx(1.0, abs=1e-3)
    assert max(spring(t / 100, 0, 3, 0.2) for t in range(100)) > 1.0


def test_stagger_and_window():
    s0, e0 = stagger(0, 5, 0, 2, 0.4)
    s4, e4 = stagger(4, 5, 0, 2, 0.4)
    assert (s0, e4) == (0, pytest.approx(2.0))
    assert window(1.0, 0, 2, 0.5, 0.5) == 1.0
    assert window(0.25, 0, 2, 0.5, 0.5) == pytest.approx(0.5)


def test_impact():
    assert impact(1.0, [1.0]) == 1.0
    assert impact(0.9, [1.0]) == 0.0
    assert impact(1.1, [1.0], decay=10) == pytest.approx(math.exp(-1))
