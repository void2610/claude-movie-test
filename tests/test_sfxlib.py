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


def _rain(dur=40.0, seed=1):
    from scipy import signal
    rng = np.random.default_rng(seed)
    x = signal.sosfilt(signal.butter(2, [300, 5000], "bandpass", fs=SR, output="sos"), rng.standard_normal(int(dur * SR)))
    return x / np.abs(x).max() * 0.3


def test_ambience_is_kept_long_looped_and_judged_by_steadiness(tmp_path):
    side = sfxlib.prepare(_wav(tmp_path / "rain.wav", _rain()), "ambience", tmp_path / "out", "rain")[0]
    assert side["verdict"] == "ok" and side["dur_s"] > 30
    from motion.audio import load
    y = load(side["file"]).mean(axis=0)
    seam = np.abs(np.r_[y[-2:], y[:2]]).max()         # 終わりから頭へ跳ばずにつながる
    assert seam < 4 * np.sqrt(np.mean(y ** 2))
    loud = _rain()
    loud[int(20 * SR):int(20.3 * SR)] *= 12             # 途中にドアの音のような大きな音
    bad = sfxlib.prepare(_wav(tmp_path / "door.wav", loud), "ambience", tmp_path / "out", "door")[0]
    assert "目立つ音" in bad["verdict"]
    gap = _rain()
    gap[int(10 * SR):int(11.5 * SR)] *= 0.05            # 一瞬音が抜ける
    holed = sfxlib.prepare(_wav(tmp_path / "gap.wav", gap), "ambience", tmp_path / "out", "gap")[0]
    assert "途切れる" in holed["verdict"]


def test_mix_lays_ambience_under_the_music_at_the_given_level():
    from motion import audio
    mx = audio.Mix(8.0, tail=0.2)
    mx.ambience(_rain(3.0).astype(np.float32), start=0.5, end=7.5, level_db=-30)   # 3 秒の録音を輪にして 7 秒敷く
    y = mx.buses["ambience"][0]
    mid = y[int(3.0 * SR):int(5.0 * SR)]                                             # 頭と終わりのフェードの外
    assert abs(20 * np.log10(np.sqrt(np.mean(mid ** 2))) + 30) < 1
    assert np.abs(y[:int(0.5 * SR)]).max() == 0 and np.abs(y[int(7.6 * SR):]).max() == 0


def test_credits_list_only_sounds_that_need_attribution(tmp_path):
    src = _wav(tmp_path / "raw.wav", _hit())
    sfxlib._write_catalog(tmp_path, [], [])
    sfxlib.add([src], "hit", ["mine"], root=tmp_path)
    sfxlib.add([src.rename(tmp_path / "by.wav")], "hit", ["theirs"], "\"Hit\" by someone, BY", root=tmp_path,
               license="by")
    ids = [e["id"] for e in sfxlib.catalog(tmp_path)["sounds"]]
    assert sfxlib.credits(ids, tmp_path) == ['hit/own-by: "Hit" by someone, BY']


def test_search_reuses_saved_results_without_the_network(tmp_path, monkeypatch):
    calls = []

    def fake(req, timeout=0):
        calls.append(req.full_url)
        raise OSError("offline")
    monkeypatch.setattr(sfxlib.urllib.request, "urlopen", fake)
    params = dict(q="rain", license="cc0", source="freesound", page_size=4, filter_dead="true")
    import hashlib
    import json
    key = hashlib.sha1(json.dumps(params, sort_keys=True).encode()).hexdigest()[:16]
    (tmp_path / "_search").mkdir()
    (tmp_path / "_search" / f"{key}.json").write_text("[]", encoding="utf-8")
    assert sfxlib.search("rain", "ambience", 4, root=tmp_path) == [] and calls == []
