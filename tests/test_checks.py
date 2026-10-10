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


def _two_titles(tmp_path, a_out, b_in, clip_a=False):
    """同じ場所に 2 つの見出しを描く。a は a_out 秒まで、b は b_in 秒から (入れ替えの 0.2 秒は薄く重ねる)。"""
    from motion import Composition, scene
    from motion.anim import progress
    from motion.nodes import node
    comp = Composition(width=400, height=200, fps=20, duration=2, background="#000000", linear=False)
    comp.project_dir = str(tmp_path)

    @scene(0, 2)
    def s(c, ctx):
        with node(c, ctx, "a", origin=(20, 150)) as n:
            alpha = 1 - progress(n.t, a_out - 0.2, a_out)
            if alpha > 0:
                n.c.save()
                if clip_a:
                    n.c.clipRect(skia.Rect.MakeLTRB(0, 0, 400, 40))   # 押し上げて上の帯だけに残した状態
                text.text(n.c, "ONE ATTRIBUTE", 20, 150, size=48, alpha=alpha)
                n.c.restore()
        with node(c, ctx, "b", origin=(20, 150)) as n:
            alpha = progress(n.t, b_in, b_in + 0.2)
            if alpha > 0:
                text.text(n.c, "THREE WAYS IN", 20, 150, size=48, alpha=alpha)

    comp.add(s)
    return comp


def _overlaps_at(comp, t):
    from motion.checks import text_overlaps
    from motion.nodes import edits_of
    from motion.render import FrameRenderer
    FrameRenderer(comp).draw(t, t * comp.fps)
    return text_overlaps(edits_of(comp).seen)


def test_text_overlaps_finds_two_titles_on_top_of_each_other(tmp_path):
    comp = _two_titles(tmp_path, a_out=1.5, b_in=0.8)       # a が抜ける前に b が入りきる
    assert [(a, b) for a, b, _ in _overlaps_at(comp, 1.2)] == [("a", "b")]


def test_text_overlaps_ignores_crossfade_and_clipped_text(tmp_path):
    comp = _two_titles(tmp_path, a_out=1.0, b_in=0.8)       # 入れ替えの間はどちらかが薄い
    assert all(not _overlaps_at(comp, t) for t in (0.85, 0.9, 0.95))
    comp = _two_titles(tmp_path, a_out=1.5, b_in=0.8, clip_a=True)
    assert not _overlaps_at(comp, 1.2)
