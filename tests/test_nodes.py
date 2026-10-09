import json

import numpy as np
import skia

from motion import Composition, draw, scene
from motion.nodes import edits_of, node, save
from motion.persp import Camera, Card, draw_cards
from motion.render import FrameRenderer
from motion.scene import Ctx


def make(tmp_path):
    comp = Composition(width=200, height=100, fps=10, duration=2, background="#000000", linear=False)
    comp.project_dir = str(tmp_path)

    @scene(0, 2)
    def s(c, ctx):
        with node(c, ctx, "box", origin=(50, 50), label="箱", span=(0.5, 2)) as n:
            if n.t >= 0.5:
                draw.rect(n.c, 40, 40, 20, 20, n.prop("color", "#ff0000"))

    comp.add(s)
    return comp


def test_node_records_bounds_and_props(tmp_path):
    comp = make(tmp_path)
    r = FrameRenderer(comp)
    r.draw(1.0, 10)
    seen = edits_of(comp).seen["box"]
    assert seen.bounds == (40, 40, 60, 60)
    assert seen.props["color"]["type"] == "color"


def test_edits_move_scale_recolor_and_retime(tmp_path):
    save(tmp_path / "edits.json", "box", {"dx": 30, "dy": -10, "scale": 2.0, "dt": 0.6, "props": {"color": "#00ff00"}})
    comp = make(tmp_path)
    r = FrameRenderer(comp)
    assert r.frame(10)[50, 80].sum() == 0                      # dt=0.6 なので 1.0 秒ではまだ出ていない (n.t=0.4)
    img = r.frame(15)
    assert img[40, 80, 1] > 200 and img[40, 80, 0] < 50         # 緑に変わり、右上へ動いて 2 倍
    b = edits_of(comp).seen["box"].bounds
    assert b == (60, 20, 100, 60)
    data = json.loads((tmp_path / "edits.json").read_text())
    save(tmp_path / "edits.json", "box", {"props": {"color": None}, "dt": None})
    assert "props" not in json.loads((tmp_path / "edits.json").read_text())["box"]
    assert data["box"]["dt"] == 0.6


def test_card_edits_and_bounds(tmp_path):
    comp = Composition(width=400, height=300)
    comp.project_dir = str(tmp_path)
    save(tmp_path / "edits.json", "c", {"dx": 50, "hidden": None})
    E = edits_of(comp)
    s = skia.Surface(400, 300)
    cam = Camera.default(Ctx(0, 0, comp))
    E.begin_frame()
    draw_cards(s.getCanvas(), cam, [Card((200, 150, 0), (100, 100), fill=skia.ColorRED, shade=0, id="c")], edits=E)
    l, t, r, b = E.seen["c"].bounds
    assert (round(l), round(r)) == (200, 300)
    img = s.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)
    assert img[150, 250, 0] > 200 and img[150, 170, 0] < 50
