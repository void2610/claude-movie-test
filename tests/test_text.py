import pytest

from motion import text


def test_variable_axes_change_glyphs():
    # skia 側に可変軸が渡らない不具合があったため、描画用の Font で幅を確かめる
    f = text.get_font("sans")
    thin = f.skfont(100, {"wght": 200}).measureText("ENGINE")
    bold = f.skfont(100, {"wght": 900}).measureText("ENGINE")
    wide = f.skfont(100, {"wght": 900, "wdth": 125}).measureText("ENGINE")
    assert thin < bold < wide


def test_shaping_width_tracks_axes():
    a = text.shape("MOTION", "sans", 100, {"wdth": 75})
    b = text.shape("MOTION", "sans", 100, {"wdth": 125})
    assert b.width > a.width * 1.2


def test_letters_and_tracking():
    sh = text.shape("AVA", "sans", 100)
    assert [l[0] for l in sh.letters()] == ["A", "V", "A"]
    tr = text.shape("AVA", "sans", 100, tracking=0.1)
    assert tr.width == pytest.approx(sh.width + 2 * 10)


def test_non_variable_font_loads():
    sh = text.shape("12:34", "mono", 20)
    assert len(sh.glyphs) == 5 and sh.width > 0
