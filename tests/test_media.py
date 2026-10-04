import subprocess

import numpy as np
import pytest
import skia

from motion import Composition, audio, media
from motion.scene import Ctx


@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    d = tmp_path_factory.mktemp("media")
    p = d / "clip.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=320x180:r=24:d=2",
                    "-f", "lavfi", "-i", "sine=f=440:d=2", "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", str(p)], check=True)
    return p


def test_fit_rects():
    src, dst = media.fit_rects(200, 100, 0, 0, 100, 100, "cover")
    assert (src.width(), src.height()) == (100, 100) and src.left() == 50
    src, dst = media.fit_rects(200, 100, 0, 0, 100, 100, "contain")
    assert (dst.width(), dst.height(), dst.top()) == (100, 50, 25)


def test_video_frames_follow_comp_fps(clip, tmp_path):
    comp = Composition(width=320, height=180, fps=30, duration=2.0, build_dir=str(tmp_path))
    v = media.Video(clip, start=0.5, offset=0.5, duration=1.0)
    v.prepare(comp)
    assert v.frame_count(comp) == 30
    assert v.image(comp, 0.0) is v.image(comp, 0.5)  # 開始前は先頭フレームで止まる
    s = skia.Surface(320, 180)
    v.draw(s.getCanvas(), Ctx(1.0, 30, comp), fit="cover")
    assert s.makeImageSnapshot().toarray()[..., :3].std() > 10


def test_audio_from_video_file(clip):
    mx = audio.Mix(2.0)
    mx.file(clip, t=0.5, offset=0.25, length=1.0)
    y = mx.bus("media")
    assert np.abs(y[:, :int(0.45 * 48000)]).max() == 0
    assert np.abs(y[:, int(0.6 * 48000):int(1.4 * 48000)]).max() > 0.1
