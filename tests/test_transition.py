import numpy as np
import pytest

from motion import Composition, draw, scene
from motion.render import FrameRenderer
from motion.transition import KINDS, Transition


def make(kind):
    comp = Composition(width=64, height=36, fps=10, duration=3, background="#000000", linear=False)

    @scene(0, 1.5)
    def a(c, ctx):
        draw.fill(c, "#0000ff")

    @scene(1.0, 3)
    def b(c, ctx):
        draw.fill(c, "#ff0000")

    comp.add(a, b, Transition(a, b, at=1.0, dur=1.0, kind=kind, ease="linear"))
    return comp, a, b


@pytest.mark.parametrize("kind", list(KINDS))
def test_transition_starts_at_a_and_ends_at_b(kind):
    comp, a, b = make(kind)
    r = FrameRenderer(comp)
    start, end = r.frame(10), r.frame(20)
    assert start[..., 2].mean() > 250 and start[..., 0].mean() < 5
    assert end[..., 0].mean() > 250 and end[..., 2].mean() < 5


def test_scenes_are_hidden_during_transition():
    comp, a, b = make("wipe")
    assert a.end == 2.0 and b.start == 1.0
    assert not a.active(1.5, comp) and not b.active(1.5, comp)
    assert a.active(0.5, comp) and b.active(2.5, comp)


@pytest.mark.parametrize("kind", ["crossfade", "wipe", "iris", "slices", "push"])
def test_transparent_scene_a_does_not_show_through(kind):
    """背景を描かないシーン同士でも、トランジションの終盤に a が b の下から透けない。"""
    comp = Composition(width=64, height=36, fps=10, duration=3, background="#000000", linear=False)

    @scene(0, 1.5)
    def a(c, ctx):
        draw.rect(c, 4, 4, 20, 20, "#0000ff")

    @scene(1.0, 3)
    def b(c, ctx):
        draw.rect(c, 40, 10, 20, 20, "#ff0000")

    comp.add(a, b, Transition(a, b, at=1.0, dur=1.0, kind=kind, ease="linear"))
    img = FrameRenderer(comp).frame(19)
    assert img[..., 2].max() < 40
