from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from motion import ears

HUB = Path.home() / ".cache" / "huggingface" / "hub" / f"models--{ears.MODEL.replace('/', '--')}"


def test_z_removes_the_bias_of_dense_sounds(monkeypatch):
    # 2 次元の玩具: 語 0 と語 1、語 1 はどの音にも高く出る (偏りの大きい語)
    E = np.array([[1.0, 0.0], [0.6, 0.8]], np.float32)
    monkeypatch.setattr(ears, "vocab", lambda: (["a", "b"], ["x", "x"], E, np.array([0.0, 1.0], np.float32)))
    zt, zq = ears.calibrate(np.array([[0.8, 0.6]], np.float32), E[:1])
    # 生のコサインは語 1 の方が高いが、偏りを引くと語 0 が目立つ
    assert (np.array([[0.8, 0.6]]) @ E.T)[0, 1] > (np.array([[0.8, 0.6]]) @ E.T)[0, 0]
    assert zt[0, 0] > zt[0, 1] and zq[0, 0] == pytest.approx(zt[0, 0])


def test_verdict_bands():
    assert [ears.verdict(z) for z in (3.2, 2.7, 2.1, 0.5)] == ["強い一致", "ありそう", "弱い", "合わない"]


@pytest.mark.skipif(not (HUB / "snapshots").exists(), reason="CLAP のモデルが未取得")
def test_clap_tells_a_beep_from_noise(tmp_path, monkeypatch):
    monkeypatch.setattr(ears, "CACHE", tmp_path / "cache")
    t = np.arange(int(0.4 * 48000)) / 48000
    beep = (np.sin(2 * np.pi * 1000 * t) * np.minimum(1, (0.4 - t) * 50) * 0.5).astype(np.float32)
    noise = (np.random.default_rng(0).standard_normal(48000 * 5) * 0.2).astype(np.float32)
    sf.write(tmp_path / "beep.wav", np.c_[beep, beep], 48000)
    sf.write(tmp_path / "noise.wav", np.c_[noise, noise], 48000)
    files = [tmp_path / "beep.wav", tmp_path / "noise.wav"]
    z = ears.match(files, "a short electronic beep")
    assert z[0] >= 3.0 and z[1] < 2.0
    z = ears.match(files, "white noise static")
    assert z[1] >= 3.0 and z[0] < 2.0
    assert len(list((tmp_path / "cache" / "audio").glob("*.npy"))) == 2   # 2 度目の問いは埋め込みを測り直さない
