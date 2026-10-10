import numpy as np

from motion import sfxlib

SR = sfxlib.SR


def _wav(path, x):
    sfxlib._write_wav(path, x)
    return path


def _hit(dur=0.8, f=180.0):
    t = np.arange(int(dur * SR)) / SR
    rng = np.random.default_rng(0)
    x = np.sin(2 * np.pi * f * t) * np.exp(-t * 7) + rng.standard_normal(len(t)) * np.exp(-t * 40) * 0.5
    return np.r_[np.zeros(int(0.1 * SR)), x * 0.8]


def test_hit_is_cut_at_its_onset_and_passes(tmp_path):
    src = _wav(tmp_path / "raw.wav", _hit())
    side = sfxlib.prepare(src, "hit", tmp_path / "out", "x")[0]
    assert side["verdict"] == "ok", side["verdict"]
    # 先頭の無音 0.1 秒は落とし、山は頭から数十 ms に来る
    assert side["peak_s"] < 0.05


def test_steady_noise_is_rejected_as_whoosh(tmp_path):
    x = np.random.default_rng(1).standard_normal(SR) * 0.3
    side = sfxlib.prepare(_wav(tmp_path / "n.wav", x), "whoosh", tmp_path / "out", "n")[0]
    assert side["verdict"] != "ok"


def test_riser_peaks_near_its_end(tmp_path):
    t = np.arange(2 * SR) / SR
    from scipy import signal
    noise = signal.sosfilt(signal.butter(2, 2500, "lowpass", fs=SR, output="sos"),
                           np.random.default_rng(2).standard_normal(len(t)))
    x = noise / np.abs(noise).max() * (t / 2) ** 3 * 0.8
    side = sfxlib.prepare(_wav(tmp_path / "r.wav", x), "riser", tmp_path / "out", "r")[0]
    assert side["verdict"] == "ok", side["verdict"]
    assert side["peak_s"] > 0.7 * side["dur_s"]


def test_added_sound_is_found_by_id_type_and_words(tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    sfxlib._write_catalog(root, [], [])
    a = _wav(tmp_path / "metal_clang.wav", _hit(f=900.0))
    b = _wav(tmp_path / "wood_knock.wav", _hit(f=150.0))
    sfxlib.add([a, b], "hit", credit="自作, CC0", root=root)
    ids = [e["id"] for e in sfxlib.catalog(root)["sounds"]]
    assert ids == ["hit/own-metal-clang", "hit/own-wood-knock"]
    assert sfxlib.browse("hit", "wood", root=root)[0]["id"] == "hit/own-wood-knock"
    s = sfxlib.sound("hit/own-metal-clang", root=root)
    assert s.origin == "hit/own-metal-clang" and s.buf.shape[0] == 2
    assert sfxlib.sound("hit", like="metal", root=root).origin == "hit/own-metal-clang"
    # 1 オクターブ上げると半分の長さで、山の位置も半分になる
    up = s.pitched(12)
    assert abs(up.duration - s.duration / 2) < 0.01 and abs(up.peak - s.peak / 2) < 1e-3
    assert "own-metal-clang" in (root / "CREDITS.md").read_text(encoding="utf-8")


def test_sheet_draws_one_row_per_sound(tmp_path):
    files = [_wav(tmp_path / f"{i}.wav", _hit(f=200.0 * (i + 1))) for i in range(3)]
    png = sfxlib.sheet(files, tmp_path / "s.png")
    import cv2
    assert cv2.imread(str(png)).shape[0] == 3 * 118 + 20
