import numpy as np
import pytest
from pedalboard.io import AudioFile

from motion import analysis, audio


@pytest.fixture(scope="module")
def song(tmp_path_factory):
    """128 BPM・最初の拍が 0.30 秒・1 拍目だけキックが入るテスト曲。"""
    bpm, off = 128.0, 0.30
    beat = 60 / bpm
    mx = audio.Mix(16.0)
    for i in range(int((16 - off) / beat)):
        t = off + i * beat
        if i % 4 == 0:
            mx.hit("808bd", t, i=1, gain_db=0)
        mx.hit("808hc", t, gain_db=-8)
        mx.hit("808hc", t + beat / 2, gain_db=-14)
    path = tmp_path_factory.mktemp("song") / "song.wav"
    return mx.render(path, lufs=-14), bpm, off


def test_detects_tempo_and_downbeat(song):
    path, bpm, off = song
    info = analysis.analyze(path, cache=False)
    assert info.bpm == pytest.approx(bpm, abs=1.0)
    beat = 60 / bpm
    first_down = info.downbeats[0]
    # 小節頭はキックの位置 (off + 4 拍 * k) のどれかに乗る
    k = round((first_down - off) / (4 * beat))
    assert first_down == pytest.approx(off + 4 * beat * k, abs=0.03)
    tl = info.timeline()
    assert tl.bpm == pytest.approx(bpm, abs=1.0)
    assert len(info.onsets_strong) > 0
