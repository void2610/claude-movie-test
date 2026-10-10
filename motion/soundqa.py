"""書き出した音を測って確かめる。Claude は音を聞けないので、音の担当者が耳で確かめることを数値にする。

review から呼ばれる。見せ場 (hero) の失敗とラウドネス・ピークはエラー、それ以外は警告。
基準は opus-sound-layer の qa.py に倣う (MIT, data/opus-sound-layer.LICENSE)。

- 絵との一致: Cue の kind (cut / move / land / appear) が、書き出した絵の動きの曲線のその位置で起きているか
- 置き場所: 効果音の山が置いた時刻から 1 コマ (見せ場) / 2 コマ以内にあるか
- 聞こえるか: 効果音の主な帯域で、音楽などより 1.5dB 以上浮くか (見せ場は一番強い帯域で 3dB)
- ラウドネス・真のピーク・予定外の無音・音楽の落ち込み・合成の効果音の数
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy import signal

from .checks import Finding

SR = 48000
BANDS = [(125, 250), (250, 500), (500, 1000), (1000, 2000), (2000, 4000), (4000, 8000), (8000, 16000)]


@dataclass
class SoundQA:
    findings: list[Finding] = field(default_factory=list)       # hero・ラウドネス・ピーク (review のエラー)
    warnings: list[tuple[float, str, str]] = field(default_factory=list)   # (時刻, 規則, 説明)
    listen: list[tuple[float, str]] = field(default_factory=list)  # 人間が耳で確かめる時刻と理由
    passed: list[str] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    motion: np.ndarray | None = None


def motion_curve(diff: np.ndarray) -> np.ndarray:
    """フレーム間の差 (灰色の平均絶対差) から、グレインなどの常にある揺らぎの底を引いた動きの量。"""
    return np.maximum(diff - np.percentile(diff, 10), 0.0)


def picture_check(kind: str, f: int, m: np.ndarray) -> tuple[bool, str]:
    n = len(m)
    if f < 1 or f >= n:
        return False, "映像の外"
    if kind == "cut":
        lo, hi = max(1, f - 1), min(n, f + 2)
        i = lo + int(np.argmax(m[lo:hi]))
        base = np.median(m[max(1, f - 15):min(n, f + 15)]) + 1.0
        return bool(m[i] > 4 * base and m[i] > 6.0), f"最大の変化は {i} コマ目 ({m[i]:.1f}、周囲 {base:.1f})"
    if kind == "move":
        lo, hi = max(1, f - 3), min(n, f + 4)
        i = lo + int(np.argmax(m[lo:hi]))
        ok = m[i] >= m[max(1, i - 1)] and m[i] >= m[min(n - 1, i + 1)] and m[i] > 0.5
        return bool(ok and abs(i - f) <= 3), f"動きの山は {i} コマ目 ({m[i]:.2f})"
    if kind == "land":
        pre = m[max(1, f - 15):max(2, f - 1)]
        if len(pre) == 0 or pre.max() < 0.5:
            return False, "止まる前に動きが無い"
        thr = max(0.25, 0.05 * pre.max())
        for i in range(max(1, f - 6), min(n, f + 7)):
            if m[i] <= thr < m[i - 1]:
                return abs(i - f) <= 2, f"動きが止まるのは {i} コマ目"
        return False, "キューの近くで動きが止まらない"
    if kind == "appear":
        lo, hi = max(1, f - 1), min(n, f + 2)
        i = lo + int(np.argmax(m[lo:hi]))
        base = np.median(m[max(1, f - 15):min(n, f + 15)])
        return bool(m[i] >= 0.3 and m[i] >= 3 * (base + 0.1)), f"{i} コマ目の変化 {m[i]:.2f} (周囲 {base:.2f})"
    return True, "検査なし"


def band_rms(x: np.ndarray, lo: float, hi: float) -> float:
    hi = min(SR / 2 - 100, hi)
    if len(x) < 64 or hi <= lo * 1.05:
        return 0.0
    sos = signal.butter(4, [lo, hi], "bandpass", fs=SR, output="sos")
    return float(np.sqrt(np.mean(signal.sosfilt(sos, x) ** 2)))


def _env(x: np.ndarray, win_s: float) -> np.ndarray:
    n = max(1, int(win_s * SR))
    return np.sqrt(np.convolve(x * x, np.ones(n) / n, mode="same"))


def peak_env(x: np.ndarray, win_s: float = 0.002) -> np.ndarray:
    """山の位置を測る包絡。低音は 1 周期が数十 ms あり、短い窓の音量だと波の山を拾うので、解析信号の振幅を使う。"""
    n = max(1, int(win_s * SR))
    return np.convolve(np.abs(signal.hilbert(x)), np.ones(n) / n, mode="same")


def _active_window(sfx: np.ndarray, p: int) -> tuple[int, int]:
    """山の 10ms 前から、20dB 下がるまで (40〜150ms)。短いクリックを 150ms に薄めて判定しない。"""
    seg = sfx[p:p + int(0.3 * SR)]
    env = _env(seg, 0.005)
    if not len(env):
        return p, p
    k = int(np.argmax(env))
    below = np.flatnonzero(env[k:] < env.max() * 0.1)
    dur = np.clip(((below[0] + k) if len(below) else len(env)) / SR, 0.04, 0.15)
    return max(0, p - int(0.01 * SR)), p + int(dur * SR)


def true_peak_db(y: np.ndarray) -> float:
    os4 = signal.resample_poly(y, 4, 1, axis=-1)
    return float(20 * np.log10(np.max(np.abs(os4)) + 1e-12))


def _short_loudness(x: np.ndarray, meter, start: int, n: int) -> float:
    if n < int(0.4 * SR):
        return -70.0
    v = meter.integrated_loudness(x[:, start:start + n].T.astype(np.float64))
    return float(v) if np.isfinite(v) else -70.0


def check(comp, wav: str | Path | None, diff: np.ndarray) -> SoundQA:
    import pyloudnorm

    from .audio import load
    from .scene import Cue
    fps = comp.fps
    q = SoundQA(motion=motion_curve(diff))
    m = q.motion

    def err(rule, t, detail):
        waived = next((w.reason for w in comp.waivers if w.rule == rule and w.times[0] <= t <= w.times[1]), None)
        q.findings.append(Finding(rule, t, detail, None, waived))

    def warn(rule, t, detail):
        q.warnings.append((t, rule, detail))

    cues = [c for c in comp.cues if isinstance(c, Cue)]
    for c in cues:
        if not c.kind:
            continue
        ok, why = picture_check(c.kind, int(round(c * fps)), m)
        label = f"{c.kind}{' (見せ場)' if c.hero else ''}"
        if not ok:
            (err if c.hero else warn)("sound: 絵との一致", float(c), f"{label}: {why}")
        else:
            q.passed.append(f"{float(c):.2f}s {label}: {why}")

    if not wav or not Path(wav).exists():
        return q
    base = Path(wav).with_suffix("")
    mix = load(str(wav)).astype(np.float64)
    meter = pyloudnorm.Meter(SR)
    report_p = Path(f"{base}.mix.json")
    report = json.loads(report_p.read_text(encoding="utf-8")) if report_p.exists() else None
    target = report["lufs"] if report else -14.0
    loud = meter.integrated_loudness(mix.T)
    if abs(loud - target) > 1.0:
        err("sound: ラウドネス", 0.0, f"{loud:.1f} LUFS (目標 {target})")
    tp = true_peak_db(mix)
    if tp > -1.0:
        err("sound: 真のピーク", 0.0, f"{tp:.2f} dBTP (上限 -1.0)")

    # 無音: 50ms ごとの音量が -50dBFS 未満の区間が 0.5 秒以上続く
    mono = mix.mean(axis=0)
    hop = int(0.05 * SR)
    rms = np.sqrt(np.mean(mono[:len(mono) // hop * hop].reshape(-1, hop) ** 2, axis=1))
    quiet = 20 * np.log10(rms + 1e-12) < -50
    i = 0
    while i < len(quiet):
        if quiet[i]:
            j = i
            while j < len(quiet) and quiet[j]:
                j += 1
            a, b = i * hop / SR, j * hop / SR
            if b - a >= 0.5 and not any(s - 0.1 <= a and b <= e + 0.1 for s, e in comp.silence_ok):
                err("sound: 無音", a, f"{a:.2f}〜{b:.2f}s が無音 (意図なら comp.silence_ok に書く)")
            i = j
        i += 1

    if not report:
        return q
    sfx = load(f"{base}.sfx.wav").astype(np.float64).mean(axis=0)
    bed2 = load(f"{base}.bed.wav").astype(np.float64)
    bed = bed2.mean(axis=0)
    events = sorted(report["events"], key=lambda e: e["t"])
    q.events = events
    env = peak_env(sfx)
    synth = [e for e in events if e["origin"] == "synth"]
    if synth:
        warn("sound: 合成の効果音", synth[0]["t"],
             f"{len(synth)} 個が合成 (打撃・クリック・風切りは sfxlib の録音から選ぶ)")
    margins = []
    times = sorted({e["t"] for e in events})
    for k, e in enumerate(events):
        hero = e["hero"]
        p = int(e["t"] * SR)
        # 同じ時刻に重ねた層は山を揃えて置いてあるので、置き場所は時刻ごとに 1 度だけ (見せ場を優先して) 測る
        first = next(x for x in events if x["t"] == e["t"] and (x["hero"] or not any(
            y["hero"] for y in events if y["t"] == e["t"])))
        if first is e:
            # 隣の効果音の山を拾わないよう、探す範囲を隣との中間までに狭める
            j = times.index(e["t"])
            gap_l = (e["t"] - times[j - 1]) / 2 if j > 0 else 0.06
            gap_r = (times[j + 1] - e["t"]) / 2 if j + 1 < len(times) else 0.06
            lo = max(0, p - int(min(0.06, gap_l) * SR))
            hi = min(len(env), p + int(min(0.06, gap_r) * SR))
            if hi > lo:
                found = lo + int(np.argmax(env[lo:hi]))
                off = abs(found - p) / SR * fps
                if off > (1 if hero else 2):
                    (err if hero else warn)("sound: 置き場所", e["t"], f"{e['origin']}: 山が {off:.1f} コマずれている")
        if e.get("layer"):
            continue
        if "lift_db" in e:
            margins.append((e["lift_db"], e))
            if e["lift_db"] < 1.5:
                (err if hero else warn)("sound: 聞こえない", e["t"],
                                        f"{e['origin']}: 自分の帯域で {e['lift_db']:.1f}dB しか浮かない (1.5dB 以上)"
                                        f" {e['band'][0]}-{e['band'][1]}Hz")
            if hero and e["body_db"] < 3.0:
                err("sound: 見せ場の芯", e["t"], f"{e['origin']}: 一番強い帯域で {e['body_db']:.1f}dB (3dB 以上)")
            continue
        w0, w1 = _active_window(sfx, p)
        w1 = min(len(sfx), w1)
        fx_b = [band_rms(sfx[w0:w1], a, b) for a, b in BANDS]
        tot = sum(v * v for v in fx_b) + 1e-20
        best, band = -99.0, None
        for (a, b), v in zip(BANDS, fx_b):
            if v * v / tot < 0.1:
                continue
            floor = max(band_rms(bed[w0:w1], a, b), 10 ** (-60 / 20))
            lift = 20 * np.log10(band_rms(bed[w0:w1] + sfx[w0:w1], a, b) / floor + 1e-12)
            if lift > best:
                best, band = lift, (a, b)
        margins.append((best, e))
        if best < 1.5:
            (err if hero else warn)("sound: 聞こえない", e["t"],
                                    f"{e['origin']}: 自分の帯域で {best:.1f}dB しか浮かない (1.5dB 以上)"
                                    + (f" {band[0]}-{band[1]}Hz" if band else ""))
        if hero:
            kb = int(np.argmax(fx_b))
            a, b = BANDS[kb]
            floor = max(band_rms(bed[w0:w1], a, b), 10 ** (-60 / 20))
            body = 20 * np.log10(band_rms(bed[w0:w1] + sfx[w0:w1], a, b) / floor + 1e-12)
            if body < 3.0:
                err("sound: 見せ場の芯", e["t"], f"{e['origin']}: 一番強い帯域 {a}-{b}Hz で {body:.1f}dB (3dB 以上)")

    for c in cues:
        if c.hero and not any(e["hero"] and abs(e["t"] - c) <= 1 / fps for e in events):
            err("sound: 見せ場の音", float(c), "見せ場のキューに hero の効果音が無い")

    # 音楽の落ち込み: 3 秒ごとの音量が中央値より 12LU 以上下がる (直前に音を止める見せ場の前は除く)
    stops = [(float(c) - 1.5, float(c) + 0.5) for c in cues if c.hero]
    stops += [(s["t"] - 1.5, s["t"] + 0.5) for s in report.get("stops", [])]
    if np.abs(bed).max() > 1e-4 and len(bed) > 3 * SR:
        L = [(s / SR, _short_loudness(bed2, meter, s, 3 * SR)) for s in range(0, len(bed) - 3 * SR, SR // 2)]
        med = float(np.median([v for _, v in L]))
        for t, v in L:
            if v < med - 12 and not any(a <= t + 1.5 <= b for a, b in stops):
                warn("sound: 音楽の落ち込み", t, f"{t:.1f}s からの 3 秒が {v:.1f} LUFS (中央値 {med:.1f})")
                break

    heroes = [e for e in events if e["hero"]]
    q.listen = [(e["t"], f"見せ場: {e['origin']}") for e in heroes[:3]]
    for best, e in sorted(margins, key=lambda x: x[0]):
        if len(q.listen) >= 5:
            break
        if all(abs(e["t"] - t) > 0.3 for t, _ in q.listen):
            q.listen.append((e["t"], f"一番埋もれやすい音 ({best:.1f}dB): {e['origin']}"))
    q.listen.sort()
    return q


def strip(q: SoundQA, wav: str | Path, comp, width: int) -> np.ndarray:
    """波形・スペクトログラム・絵の動きを縦に並べ、効果音とキューに線を引いた RGB 画像 (review のシート用)。"""
    import cv2
    import skia

    from .audio import load
    from .scene import Cue
    from .sfxlib import _spectrogram
    from .text import text as draw_text
    H = 380
    surf = skia.Surface(width, H)
    c = surf.getCanvas()
    c.clear(skia.Color(28, 28, 34))
    dur = comp.duration
    tx = lambda t: width * t / dur  # noqa: E731
    y = load(str(wav)).mean(axis=0) if wav and Path(wav).exists() else np.zeros(int(dur * SR))
    k = max(len(y) // width, 1)
    wf = np.abs(y[:k * width]).reshape(-1, k).max(axis=1)
    wf = wf / (wf.max() + 1e-9)
    p = skia.Paint(Color=skia.Color(120, 150, 210), AntiAlias=True)
    for i, v in enumerate(wf):
        c.drawLine(i, 50 - v * 45, i, 50 + v * 45, p)
    sp = _spectrogram(y.astype(np.float64), width, 150)
    rgba = np.dstack([sp, np.full(sp.shape[:2], 255, np.uint8)])
    c.drawImage(skia.Image.fromarray(np.ascontiguousarray(rgba), colorType=skia.kRGBA_8888_ColorType), 0, 104)
    if q.motion is not None and len(q.motion):
        mm = q.motion / (q.motion.max() + 1e-9)
        path = skia.Path()
        for i, v in enumerate(mm):
            (path.lineTo if i else path.moveTo)(tx(i / comp.fps), 370 - v * 100)
        c.drawPath(path, skia.Paint(Color=skia.Color(74, 222, 128), Style=skia.Paint.kStroke_Style, StrokeWidth=1.2,
                                    AntiAlias=True))
    for e in q.events:
        col = skia.Color(255, 84, 112) if e["hero"] else skia.Color(255, 255, 255, 110)
        c.drawLine(tx(e["t"]), 0, tx(e["t"]), H, skia.Paint(Color=col, StrokeWidth=1.5 if e["hero"] else 1))
    for cu in comp.cues:
        if isinstance(cu, Cue) and cu.kind:
            draw_text(c, cu.kind, tx(cu) + 3, 262, font="mono", size=10, color="#FF9A5C", valign="cap")
    draw_text(c, "波形", 6, 10, font="sans", size=11, color="#8A8C97", valign="cap")
    draw_text(c, "スペクトログラム 0〜12kHz", 6, 112, font="sans", size=11, color="#E8E8EC", valign="cap")
    draw_text(c, "絵の動き (緑) · 効果音 (白) · 見せ場 (赤)", 6, 268, font="sans", size=11, color="#8A8C97", valign="cap")
    img = surf.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)
    return cv2.cvtColor(img, cv2.COLOR_RGBA2RGB)
