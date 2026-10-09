import numpy as np
import skia

from motion import text
from motion.checks import color_along, edge_clips


def _render(fn, w=400, h=200):
    s = skia.Surface(w, h)
    c = s.getCanvas()
    c.clear(skia.Color(14, 14, 17))
    fn(c)
    return s.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)[..., :3].copy()


def test_edge_clips_finds_text_cut_by_frame():
    cut = _render(lambda c: text.text(c, "ONE", -30, 150, size=120, axes={"wght": 900}, color="#ECECEF"))
    safe = _render(lambda c: text.text(c, "ONE", 30, 150, size=120, axes={"wght": 900}, color="#ECECEF"))
    assert any(side == "left" for side, _, _ in edge_clips(cut))
    assert edge_clips(safe) == []


def test_edge_clips_ignores_grain():
    rng = np.random.default_rng(0)
    img = np.clip(14 + rng.normal(0, 12, (200, 400, 3)), 0, 255).astype(np.uint8)
    assert edge_clips(img) == []


def test_color_along_detects_overdrawn_line():
    def lines(order):
        def f(c):
            for col in order:
                c.drawLine(100, 20, 100, 180, skia.Paint(Color=col, StrokeWidth=3, AntiAlias=True))
        return f
    pts = [(100, y) for y in range(40, 170, 10)]
    ok = _render(lines([skia.Color(138, 139, 149), skia.Color(59, 130, 246)]))
    bad = _render(lines([skia.Color(59, 130, 246), skia.Color(138, 139, 149)]))
    assert color_along(ok, pts, "#3B82F6") is None
    assert color_along(bad, pts, "#3B82F6") is not None
