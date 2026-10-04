import subprocess

import numpy as np
import pytest
import skia

from motion import Composition, audio, overlay
from motion.edit import Sequence, Shot, compare, cut_on_beats
from motion.footage import Clip, Footage, Grade, TimeMap, read_cube
from motion.render import FrameRenderer
from motion.scan import scan
from motion.scene import Ctx, scene


@pytest.fixture(scope="module")
def cap(tmp_path_factory):
    """白い四角が 1 フレーム約 6.7px で右へ動き (280px で折り返す)、5 秒目で画面が赤に変わる 10 秒・30fps の素材。"""
    d = tmp_path_factory.mktemp("cap")
    p = d / "cap.mp4"
    vf = ("color=c=black:s=320x180:r=30:d=10[bg];color=c=white:s=40x40:r=30:d=10[box];"
          "[bg][box]overlay=x='mod(t*200\\,280)':y=70,drawbox=enable='gte(t,5)':x=0:y=0:w=320:h=180:c=red@1:t=fill")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=f=330:d=10", "-filter_complex",
                    vf, "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(p)], check=True)
    return p


def test_timemap_segments():
    tm = TimeMap().play(1.0).ramp(1.0, 1.0, 0.0).hold(0.5).rewind(0.5, 2.0).seek(8.0).play(1.0)
    assert tm.duration == pytest.approx(4.0)
    assert tm(0.5) == pytest.approx(0.5)
    assert tm(2.0) == pytest.approx(1.5)          # 1 → 0 の減速で 0.5 秒ぶん進む
    assert tm(2.25) == pytest.approx(1.5)         # フリーズ
    assert tm(2.75) == pytest.approx(1.0)         # 2 倍速で 0.5 秒巻き戻す
    assert tm(3.5) == pytest.approx(8.5)          # seek 後
    assert tm.speed(0.5) == pytest.approx(1.0, abs=1e-3)
    assert tm.spans[-1] == (pytest.approx(8.0), pytest.approx(9.0))


def test_clip_follows_source_and_only_extracts_needed_range(cap, tmp_path):
    comp = Composition(width=320, height=180, fps=30, duration=4, build_dir=str(tmp_path))
    f = Footage(cap)
    clip = Clip(f, at=1.0, src_in=2.0, time=TimeMap().play(1.0).seek(4.0).play(1.0))
    f.prepare(comp)
    n = len(list(f._cache_dir(comp).glob("f_*.jpg")))
    assert n < 30 * 3.5  # 素材 10 秒のうち使う 2 区間 (+余白) だけ
    assert clip.src_time(1.5) == pytest.approx(2.5)
    assert clip.src_time(2.5) == pytest.approx(6.5)

    def box_x(img):
        return int(np.argmax(img[90, :, 0] > 128))

    a = clip.frame(comp, 1.0)
    b = clip.frame(comp, 1.3)
    assert box_x(b) > box_x(a)                     # 四角は右へ動いている
    assert clip.frame(comp, 2.5)[..., 0].mean() > 200 and clip.frame(comp, 2.5)[..., 2].mean() < 60  # 赤の区間


def test_flow_interpolation_moves_object(cap, tmp_path):
    comp = Composition(width=320, height=180, fps=30, duration=4, build_dir=str(tmp_path))
    f = Footage(cap)
    f.need(1.0, 1.2)
    f.prepare(comp)
    x = lambda img: np.argmax(img[90, :, 0] > 128)  # noqa: E731
    a, b = f.frame(comp, 1.0, "nearest"), f.frame(comp, 1.0 + 1 / 30, "nearest")
    mid = f.frame(comp, 1.0 + 0.5 / 30, "flow")
    assert x(a) < x(mid) < x(b)

    def ghost(img):
        row = img[90, :, 0].astype(int)
        return int(((row > 50) & (row < 200)).sum())

    # ブレンドは四角の両端が半透明に二重になるが、フローでは輪郭が保たれる
    blend = f.frame(comp, 1.0 + 0.5 / 30, "blend")
    assert ghost(mid) < ghost(blend)


def test_grade_and_cube(tmp_path):
    img = np.full((4, 4, 3), 128, np.uint8)
    assert Grade(exposure=1.0)(img)[0, 0, 0] > 200
    assert Grade(saturation=0.0)(np.array([[[255, 0, 0]]], np.uint8)).std() < 1
    cube = tmp_path / "inv.cube"
    lines = ["LUT_3D_SIZE 2"]
    for b in (0, 1):
        for g in (0, 1):
            for r in (0, 1):
                lines.append(f"{1 - r} {1 - g} {1 - b}")
    cube.write_text("\n".join(lines))
    assert read_cube(cube).shape == (2, 2, 2, 3)
    out = Grade(lut=cube)(np.array([[[255, 0, 0]]], np.uint8))
    assert out.tolist() == [[[0, 255, 255]]]


def test_sequence_and_overlays_render(cap, tmp_path):
    comp = Composition(width=320, height=180, fps=30, duration=4, build_dir=str(tmp_path), linear=False)
    f = Footage(cap)
    clips = cut_on_beats([Shot(f, 1.0), Shot(f, 6.0)], start=0.0, beat_len=1.0, beats=2)
    seq = Sequence(clips, punch=0.1)
    comp.prepare.append(f.prepare)

    @scene(0, 4, z=5)
    def notes(c, ctx):
        overlay.callout(c, (100, 90), "Dash", 1.0)
        overlay.highlight(c, ctx, (20, 20, 80, 60), 1.0)
        overlay.badge(c, 260, 40, "NEW", 1.0)

    comp.add(seq, notes, overlay.Captions([overlay.Cue(0, 4, "字幕のテスト")], size=20))
    for fn in comp.prepare:
        fn(comp)
    r = FrameRenderer(comp)
    assert r.frame(30)[..., 2].mean() < r.frame(75)[..., 0].mean()  # 2 カット目は赤い区間
    assert seq.cuts == [pytest.approx(2.0)]


def test_compare_splits_frame():
    comp = Composition(width=200, height=100)
    s = skia.Surface(200, 100)
    c = s.getCanvas()
    compare(c, Ctx(0, 0, comp), lambda cv: cv.drawColor(skia.ColorBLUE), lambda cv: cv.drawColor(skia.ColorRED),
            0.3, labels=None)
    img = s.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)
    assert img[50, 10, 2] > 200 and img[50, 190, 0] > 200


def test_clip_audio_follows_time_map(cap):
    mx = audio.Mix(4.0)
    f = Footage(cap)
    mx.clip(Clip(f, at=1.0, src_in=0.0, time=TimeMap().play(1.0).hold(1.0).play(0.5, 2.0)))
    y = mx.bus("game")
    sr = mx.sr
    assert np.abs(y[:, int(0.5 * sr):int(0.9 * sr)]).max() == 0          # クリップの前は無音
    assert np.abs(y[:, int(1.2 * sr):int(1.8 * sr)]).max() > 0.05        # 再生中は鳴る
    assert np.abs(y[:, int(2.2 * sr):int(2.8 * sr)]).max() < 1e-3        # フリーズ中は無音


def test_scan_finds_cut_and_motion(cap):
    res = scan(cap)
    assert any(abs(c - 5.0) < 0.3 for c in res.cuts)
    top = res.highlights(2, length=1.0)
    assert len(top) == 2
