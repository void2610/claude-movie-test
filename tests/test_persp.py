import numpy as np
import pytest
import skia

from motion import Composition
from motion.persp import Camera, Card, draw_cards
from motion.scene import Ctx

COMP = Composition(width=400, height=300)
CTX = Ctx(0, 0, COMP)


def test_default_camera_maps_z0_plane_one_to_one():
    cam = Camera.default(CTX)
    q = cam.project(np.array([[10.0, 20.0, 0.0], [390.0, 280.0, 0.0]]))
    assert q[:, :2] == pytest.approx(np.array([[10, 20], [390, 280]]), abs=1e-6)


def test_farther_is_smaller_and_orbit_keeps_target():
    cam = Camera.default(CTX)
    near = Card((200, 150, 0), (100, 100)).corners()
    far = Card((200, 150, 500), (100, 100)).corners()
    wn = np.ptp(cam.project(near)[:, 0])
    wf = np.ptp(cam.project(far)[:, 0])
    assert wf < wn
    o = cam.orbit(yaw=30)
    assert o.project(np.array([[200.0, 150.0, 0.0]]))[0, :2] == pytest.approx([200, 150], abs=1e-6)


def test_cards_draw_back_to_front_and_cull_backfaces():
    s = skia.Surface(400, 300)
    c = s.getCanvas()
    cam = Camera.default(CTX)
    front = Card((200, 150, 0), (120, 120), fill=skia.ColorRED, shade=0)
    back = Card((200, 150, 200), (300, 260), fill=skia.ColorBLUE, shade=0)
    hidden = Card((60, 60, 0), (40, 40), rot=(180, 0, 0), fill=skia.ColorGREEN, shade=0)
    draw_cards(c, cam, [front, back, hidden])
    img = s.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)
    assert img[150, 200, 0] > 200 and img[150, 200, 2] < 50   # 手前の赤が奥の青より上
    assert img[150, 110, 2] > 200                              # 奥の青は手前の赤からはみ出た部分だけ見える
    assert img[60, 60, 1] < 50                                 # 裏返ったカードは描かない
