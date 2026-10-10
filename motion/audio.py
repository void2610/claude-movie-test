"""サンプルの配置・簡易シンセ・VST 楽器・バスエフェクトによるミックスダウン。

時刻はすべて秒。Timeline.beat() 等で拍から変換して渡す。
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import struct
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Iterable

import numpy as np
import pedalboard as pb
from numpy.lib.stride_tricks import sliding_window_view
from pedalboard.io import AudioFile

SR = 48000
SAMPLES_DIR = Path(os.environ.get("MOTION_SAMPLES", "~/Music/Samples/Dirt-Samples")).expanduser()
SURGE = "/Library/Audio/Plug-Ins/VST3/Surge XT.vst3"
SURGE_FX = "/Library/Audio/Plug-Ins/VST3/Surge XT Effects.vst3"
_EXT = {".wav", ".aif", ".aiff", ".flac", ".mp3"}


def sample_files(name: str) -> list[Path]:
    d = Path(name) if Path(name).is_dir() else SAMPLES_DIR / name
    return sorted(p for p in d.iterdir() if p.suffix.lower() in _EXT)


def sample_path(name: str, i: int = 0) -> Path:
    p = Path(name)
    if p.is_file():
        return p
    files = sample_files(name)
    if not files:
        raise FileNotFoundError(f"no samples in {name}")
    return files[i % len(files)]


@lru_cache(maxsize=512)
def load(path: str | Path, sr: int = SR) -> np.ndarray:
    """音声ファイルを (2, n) の float32 ステレオで読む。"""
    with AudioFile(str(path)).resampled_to(sr) as f:
        x = f.read(f.frames)
    if x.shape[0] == 1:
        x = np.vstack([x, x])
    return x[:2].astype(np.float32)


def load_any(path: str | Path, sr: int = SR) -> np.ndarray:
    """load と同じだが、読めない形式 (動画の音声トラック等) は ffmpeg で wav にしてから読む。"""
    try:
        return load(str(path), sr)
    except Exception:
        p = Path(path).resolve()
        h = hashlib.sha1(f"{p}{p.stat().st_mtime}{sr}".encode()).hexdigest()[:16]
        wav = Path(tempfile.gettempdir()) / f"motion-audio-{h}.wav"
        if not wav.exists():
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(p), "-vn", "-ac", "2", "-ar", str(sr),
                            str(wav)], check=True)
        return load(str(wav), sr)


_NOTE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def midi(n: int | str) -> int:
    """'C3' や 'F#2' を MIDI ノート番号に変換する (C4 = 60)。"""
    if isinstance(n, int):
        return n
    m = re.fullmatch(r"([A-Ga-g])([#b]?)(-?\d+)", n)
    if not m:
        raise ValueError(n)
    v = _NOTE[m.group(1).upper()] + {"#": 1, "b": -1, "": 0}[m.group(2)]
    return v + (int(m.group(3)) + 1) * 12


def hz(n: int | str | float) -> float:
    if isinstance(n, float):
        return n
    return 440.0 * 2 ** ((midi(n) - 69) / 12)


def db(x: float) -> float:
    return 10 ** (x / 20)


def _pan(buf: np.ndarray, pan: float) -> np.ndarray:
    a = (pan + 1) * math.pi / 4
    return buf * np.array([[math.cos(a)], [math.sin(a)]], np.float32) * math.sqrt(2)


def _osc(wave: str, f: float, n: int, sr: int, phase: float = 0.0) -> np.ndarray:
    t = np.arange(n) / sr
    ph = (f * t + phase) % 1.0
    if wave == "sine":
        return np.sin(2 * np.pi * ph)
    if wave == "noise":
        return np.random.default_rng(int(f * 1000) + n).uniform(-1, 1, n)
    dt = f / sr

    # polyBLEP でエイリアシングを抑える
    def blep(p):
        out = np.zeros_like(p)
        m = p < dt
        x = p[m] / dt
        out[m] = x + x - x * x - 1
        m = p > 1 - dt
        x = (p[m] - 1) / dt
        out[m] = x * x + x + x + 1
        return out

    saw = 2 * ph - 1 - blep(ph)
    if wave == "saw":
        return saw
    sq = np.where(ph < 0.5, 1.0, -1.0) + blep(ph) - blep((ph + 0.5) % 1.0)
    if wave == "square":
        return sq
    if wave == "tri":
        return 1 - 4 * np.abs(ph - 0.5)
    raise ValueError(wave)


def adsr(n: int, sr: int, a: float, d: float, s: float, r: float, gate: float) -> np.ndarray:
    t = np.arange(n) / sr
    env = np.where(t < a, t / max(a, 1e-6), s + (1 - s) * np.exp(-(t - a) / max(d, 1e-6) * 3))
    after = t >= gate
    level_at_gate = env[min(int(gate * sr), n - 1)] if n else 0
    env[after] = level_at_gate * np.exp(-(t[after] - gate) / max(r, 1e-6) * 5)
    return env.astype(np.float32)


def limit(y: np.ndarray, sr: int, ceiling_db: float = -1.0, lookahead: float = 0.005,
          release: float = 0.08) -> np.ndarray:
    """先読み型のピークリミッター。ピークが ceiling_db を超えないようにゲインを下げる。"""
    c = db(ceiling_db)
    peak = np.abs(y).max(axis=0)
    need = np.minimum(1.0, c / np.maximum(peak, 1e-9))
    w = max(int(lookahead * sr), 1)
    # ピークの w サンプル前からゲインを下げ始める
    padded = np.concatenate([need, np.ones(w)])
    g = sliding_window_view(padded, w + 1).min(axis=1)[:len(need)]
    k = math.exp(-1.0 / (release * sr))
    out = np.empty_like(g)
    cur = 1.0
    for i, v in enumerate(g):
        cur = v if v < cur else v + (cur - v) * k
        out[i] = cur
    kernel = np.ones(w) / w
    smooth = np.convolve(out, kernel, mode="same")
    gain = np.minimum(smooth, out)
    return np.clip(y * gain.astype(np.float32), -c, c)


INSTRUMENT_CACHE = Path(os.environ.get("MOTION_INSTRUMENT_CACHE",
                                       Path(__file__).resolve().parents[1] / "build" / "cache" / "instrument"))


@lru_cache(maxsize=8)
def _plugin(path: str):
    return pb.load_plugin(path)


SURGE_PATCH_DIRS = [Path("/Library/Application Support/Surge XT/patches_factory"),
                    Path("/Library/Application Support/Surge XT/patches_3rdparty"),
                    Path("~/Documents/Surge XT/Patches").expanduser()]

# JUCE の MemoryBlock::toBase64Encoding 独自形式 ("<バイト数>.<文字列>"、6bit を LSB から詰める)
_JB64 = ".ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+"


def _juce_b64decode(s: str) -> bytes:
    size, data = s.split(".", 1)
    n = int(size)
    bits = 0
    acc = 0
    out = bytearray()
    for ch in data:
        acc |= _JB64.index(ch) << bits
        bits += 6
        while bits >= 8 and len(out) < n:
            out.append(acc & 0xFF)
            acc >>= 8
            bits -= 8
    return bytes(out.ljust(n, b"\0"))


def _juce_b64encode(b: bytes) -> str:
    chars = []
    acc = 0
    bits = 0
    for byte in b:
        acc |= byte << bits
        bits += 8
        while bits >= 6:
            chars.append(_JB64[acc & 63])
            acc >>= 6
            bits -= 6
    if bits:
        chars.append(_JB64[acc & 63])
    return f"{len(b)}.{''.join(chars)}"


def surge_patches(query: str = "") -> list[Path]:
    """Surge XT のパッチ (.fxp) を名前・カテゴリの部分一致で探す。"""
    q = query.lower()
    out = []
    for d in SURGE_PATCH_DIRS:
        if d.exists():
            out += [p for p in d.rglob("*.fxp") if q in str(p.relative_to(d)).lower()]
    return sorted(out)


def surge_load(plugin, patch: str | Path) -> None:
    """Surge XT に .fxp パッチを読み込ませる。名前だけ渡すとファクトリーパッチから探す。"""
    p = Path(patch)
    if not p.exists():
        hits = [h for h in surge_patches(str(patch)) if h.stem.lower() == p.stem.lower()] or surge_patches(str(patch))
        if not hits:
            raise FileNotFoundError(f"surge patch not found: {patch}")
        p = hits[0]
    fxp = p.read_bytes()
    if fxp[:4] != b"CcnK" or fxp[8:12] != b"FPCh":
        raise ValueError(f"not a chunk fxp: {p}")
    chunk = fxp[60:60 + struct.unpack(">I", fxp[56:60])[0]]

    # 状態は "VC2!" + XML 長 + XML。XML の IComponent に Surge のチャンク + JUCE の付加データが入っている
    st = plugin.raw_state
    xml = st[8:8 + struct.unpack("<I", st[4:8])[0]].decode("utf-8")
    m = re.search(r"<IComponent>([^<]*)</IComponent>", xml)
    comp = _juce_b64decode(m.group(1))
    xmlsize = struct.unpack("<I", comp[4:8])[0]
    wt = struct.unpack("<6I", comp[8:32])
    trailer = comp[32 + xmlsize + sum(wt):]
    xml = xml[:m.start(1)] + _juce_b64encode(chunk + trailer) + xml[m.end(1):]
    xb = xml.encode("utf-8")
    plugin.raw_state = b"VC2!" + struct.pack("<I", len(xb)) + xb + b"\0"
    # Surge は状態の反映を次の処理ブロックで行い、その回は無音になるため空打ちしておく
    plugin([], duration=0.25, sample_rate=SR)


def audition(patches: list[str | Path], out: str | Path, notes: Iterable[int | str] = ("F3", "G#3", "C4"),
             hold: float = 2.5, gap: float = 0.75) -> list[tuple[float, str]]:
    """パッチを順番に同じ和音で鳴らした試聴用 wav を作り、(開始秒, パッチ名) の一覧を返す。"""
    patches = list(patches)
    span = hold + gap
    mx = Mix(span * len(patches), tail=1.0)
    index = []
    for i, pt in enumerate(patches):
        t = i * span
        mx.instrument([(t, hold, n, 100) for n in notes], patch=pt, bus=f"p{i}")
        index.append((t, Path(pt).stem))
    mx.render(out, lufs=-16)
    return index


_BANDS = [(125, 250), (250, 500), (500, 1000), (1000, 2000), (2000, 4000), (4000, 8000), (8000, 16000)]


def _band(x: np.ndarray, lo: float, hi: float, sr: int) -> float:
    from scipy import signal
    hi = min(sr / 2 - 100, hi)
    if len(x) < 64 or hi <= lo * 1.05:
        return 0.0
    return float(np.sqrt(np.mean(signal.sosfilt(signal.butter(4, [lo, hi], "bandpass", fs=sr, output="sos"), x) ** 2)))


def _bands_at(x: np.ndarray, pk: int, start: float, bed: np.ndarray, sr: int):
    """効果音 x の本体 (山の 10ms 前から 20dB 下がるまで、40〜150ms) と、同じ時刻の音楽の、帯域ごとの音量。"""
    s0 = int(round(start * sr))
    n = len(bed)
    seg = x[pk:pk + int(0.3 * sr)]
    k_ = max(1, int(0.005 * sr))
    env = np.sqrt(np.convolve(seg * seg, np.ones(k_) / k_, mode="same")) if len(seg) else np.zeros(1)
    k0 = int(np.argmax(env))
    below = np.flatnonzero(env[k0:] < env.max() * 0.1)
    dur = np.clip(((below[0] + k0) if len(below) else len(env)) / sr, 0.04, 0.15)
    a, b = max(0, pk - int(0.01 * sr)), min(len(x), pk + int(dur * sr))
    if pk > 0.7 * len(x):
        # 山に向かって育つ音 (ライザー・逆再生) は、中身が山の手前にある
        a, b = max(0, pk - int(0.3 * sr)), pk + 1
    xa = x[a:b]
    bseg = np.zeros(len(xa))
    lo, hi = max(s0 + a, 0), min(s0 + a + len(xa), n)
    if hi > lo:
        bseg[lo - (s0 + a):hi - (s0 + a)] = bed[lo:hi]
    floor = 10 ** (-60 / 20)
    e_b = np.array([_band(xa, lo, hi, sr) for lo, hi in _BANDS])
    m_b = np.maximum([_band(bseg, lo, hi, sr) for lo, hi in _BANDS], floor)
    return xa, bseg, e_b, m_b


def _lift(x: np.ndarray, pk: int, start: float, bed: np.ndarray, gain_db: float, sr: int) -> tuple[float, list, float]:
    """音量 gain_db で置いた効果音が、音楽より何 dB 浮くか: (主な帯域のうち最も浮く量, その帯域, 最も強い帯域での量)。"""
    xa, bseg, e_b, m_b = _bands_at(x, pk, start, bed, sr)
    share = e_b ** 2 / (np.sum(e_b ** 2) + 1e-20)
    g = 10 ** (gain_db / 20)
    lifts = [20 * math.log10(_band(bseg + xa * g, lo, hi, sr) / m + 1e-12) for (lo, hi), m in zip(_BANDS, m_b)]
    ok = [i for i in range(len(_BANDS)) if share[i] >= 0.1]
    k = max(ok, key=lambda i: lifts[i]) if ok else int(np.argmax(share))
    return round(lifts[k], 2), list(_BANDS[k]), round(lifts[int(np.argmax(share))], 2)


def _solve_gain(x: np.ndarray, pk: int, start: float, bed: np.ndarray, hero: bool, sr: int) -> float:
    """効果音 x (山は pk サンプル目) を、時刻 start に置いたとき音楽などより自分の帯域で浮く音量 (dB)。

    見せ場は一番エネルギーのある帯域で +5dB、それ以外は一番浮かせやすい帯域で +3.5dB。2〜8kHz の浮きは
    6dB (見せ場 9dB) まで、ピークは周りの音楽のピークの +6dB (見せ場 +8dB) までに抑える (耳に刺さらないように)。
    """
    s0 = int(round(start * sr))
    n = len(bed)
    xa, bseg, e_b, m_b = _bands_at(x, pk, start, bed, sr)
    floor = 10 ** (-60 / 20)
    share = e_b ** 2 / (np.sum(e_b ** 2) + 1e-20)
    lift = 5.0 if hero else 3.5
    need = np.where(share >= 0.1, m_b * math.sqrt(10 ** (lift / 10) - 1) / (e_b + 1e-12), np.inf)
    k = int(np.argmax(share)) if hero else int(np.argmin(need))
    g = float(m_b[k] * math.sqrt(10 ** (lift / 10) - 1) / (e_b[k] + 1e-12))
    e28 = _band(xa, 2000, 8000, sr)
    bed_rms = float(np.sqrt(np.mean(bseg ** 2))) if len(bseg) else 0.0
    m28 = max(_band(bseg, 2000, 8000, sr), bed_rms * 10 ** (-20 / 20), floor)
    # 芯が 2kHz より下にある見せ場は、明るい縁のために全体を抑えない
    if e28 > 0 and not (hero and _BANDS[k][1] <= 2000):
        g = min(g, m28 * math.sqrt(10 ** ((9 if hero else 6) / 10) - 1) / e28)
    # 見せ場は直前の無音で周りが静かなので、±1 秒の音楽のピークを基準にする
    reach = int((1.0 if hero else 0.15) * sr)
    p = s0 + pk
    lw0, lw1 = min(max(0, p - reach), n), min(max(0, p + reach), n)
    bed_pk = max(float(np.abs(bed[lw0:lw1]).max()) if lw1 > lw0 else 0.0, 10 ** (-26 / 20))
    g = min(g, bed_pk * 10 ** ((8 if hero else 6) / 20) / (np.abs(x).max() + 1e-12))
    return 20 * math.log10(max(g, 1e-6))


def _dead_stop(y: np.ndarray, t: float, dur: float, sr: int) -> np.ndarray:
    """t の直前 dur 秒を -24dB まで落とす (20ms で滑らかに)。見せ場の打撃を際立たせる。"""
    g = np.ones(y.shape[1], np.float32)
    a, b = int(max(0.0, t - dur) * sr), min(int(t * sr), y.shape[1])
    if b <= a:
        return y
    g[a:b] = 10 ** (-24 / 20)
    k = max(1, int(0.02 * sr))
    g = np.convolve(g, np.ones(k) / k, mode="same").astype(np.float32)
    return y * g


def _hp_build(y: np.ndarray, t: float, dur: float, sr: int) -> np.ndarray:
    """t までの dur 秒で、ハイパスを 40Hz から 300Hz へ上げる (低音が抜けて、打撃で戻る)。"""
    from scipy import signal
    a, b = int(max(0.0, t - dur) * sr), min(int(t * sr), y.shape[1])
    if b - a < sr // 10:
        return y
    seg = y[:, a:b].astype(np.float64)
    cuts = np.geomspace(40, 300, 16)
    vers = [signal.sosfilt(signal.butter(2, c, "highpass", fs=sr, output="sos"), seg, axis=1) for c in cuts]
    pos = np.linspace(0, len(cuts) - 1, b - a)
    k = np.minimum(pos.astype(int), len(cuts) - 2)
    w = pos - k
    out = np.empty_like(seg)
    for j in range(len(cuts) - 1):
        m = k == j
        out[:, m] = (1 - w[m]) * vers[j][:, m] + w[m] * vers[j + 1][:, m]
    y = y.copy()
    y[:, a:b] = out
    return y


def _room(y: np.ndarray, decay: float, wet_db: float, sr: int, seed: int = 7) -> np.ndarray:
    """左右で無相関な短い残響 (12ms の前置き遅延、250Hz〜7kHz、残響時間 decay 秒) を wet_db で足す。"""
    from scipy import signal
    rng = np.random.default_rng(seed)
    n = int(decay * sr)
    t = np.arange(n) / sr
    ir = rng.standard_normal((2, n)) * np.exp(-6.91 * t / decay)
    ir = signal.sosfilt(signal.butter(2, [250, 7000], "bandpass", fs=sr, output="sos"), ir, axis=1)
    ir = np.hstack([np.zeros((2, int(0.012 * sr))), ir / np.sqrt(np.sum(ir ** 2, axis=1, keepdims=True))])
    mono = y.mean(axis=0).astype(np.float64)
    wet = np.vstack([signal.fftconvolve(mono, ir[ch])[:y.shape[1]] for ch in (0, 1)])
    return (y + wet * 10 ** (wet_db / 20)).astype(np.float32)


class Mix:
    def __init__(self, duration: float, sr: int = SR, tail: float = 1.5):
        self.sr = sr
        self.duration = duration
        self.n = int((duration + tail) * sr)
        self.buses: dict[str, np.ndarray] = {}
        self.chains: dict[str, list] = {}
        self.gains: dict[str, float] = {}
        self.ducks: dict[str, tuple] = {}
        # 置いた効果音の記録。review が絵との一致・聞こえ方を検査するのに使う
        self.events: list[dict] = []
        # 音量を後で決める効果音 (音楽などが揃ってから、その音の帯域で浮く量を解く)
        self._pending: list[dict] = []
        self._bufs: list[tuple[dict, np.ndarray, float]] = []
        self._loop = False
        self.stops: list[dict] = []
        self.builds: list[dict] = []
        self.room_params: tuple[float, float] | None = (0.6, -16.0)

    def bus(self, name: str) -> np.ndarray:
        if name not in self.buses:
            self.buses[name] = np.zeros((2, self.n), np.float32)
        return self.buses[name]

    def place(self, buf: np.ndarray, t: float, gain_db: float = 0.0, pan: float = 0.0, bus: str = "main",
              rate: float = 1.0, length: float | None = None) -> None:
        """buf ((2, n) か (n,)) を時刻 t に足し込む。rate でピッチと長さを変える。"""
        if buf.ndim == 1:
            buf = np.vstack([buf, buf])
        if rate != 1.0:
            src = np.arange(buf.shape[1])
            pos = np.arange(0, buf.shape[1] - 1, rate)
            buf = np.vstack([np.interp(pos, src, ch) for ch in buf]).astype(np.float32)
        if length is not None:
            m = int(length * self.sr)
            buf = buf[:, :m].copy()
            fade = min(int(0.01 * self.sr), buf.shape[1])
            if fade:
                buf[:, -fade:] *= np.linspace(1, 0, fade, dtype=np.float32)
        buf = _pan(buf, pan) * db(gain_db)
        i0 = int(round(t * self.sr))
        if i0 >= self.n:
            return
        j0 = max(0, -i0)
        i0 = max(0, i0)
        m = min(buf.shape[1] - j0, self.n - i0)
        if m > 0:
            self.bus(bus)[:, i0:i0 + m] += buf[:, j0:j0 + m]

    def sfx(self, sound, t: float, gain_db: float | None = 0.0, pan: float = 0.0, bus: str = "sfx",
            hero: bool = False, rel_to: dict | None = None) -> dict:
        """sfx.Sound を、山 (peak) がちょうど時刻 t に来るように置く。hero=True は見せ場の音 (検査が厳しくなる)。

        gain_db=None は音量を自動で決める: 効果音以外のバスに対し、その音の帯域で +3.5dB (見せ場 +5dB) 浮かせる。
        rel_to に別の sfx の戻り値を渡すと、その音量 + gain_db にする (重ねる層用)。
        """
        ev = dict(t=round(float(t), 4), start=round(float(t - sound.peak), 4), dur=round(sound.duration, 4),
                  origin=getattr(sound, "origin", "synth"), bus=bus, hero=hero, gain_db=gain_db,
                  layer=rel_to is not None)
        self.events.append(ev)
        self._bufs.append((ev, sound.buf, sound.peak))
        if gain_db is None or rel_to is not None:
            self._pending.append(dict(ev=ev, buf=sound.buf, peak=sound.peak, pan=pan, rel_to=rel_to,
                                      offset=gain_db or 0.0))
        else:
            self.place(sound.buf, t - sound.peak, gain_db, pan, bus)
        return ev

    def hero(self, t: float, hit="hit", boom="boom", riser="riser", stop_before: float = 0.4,
             build: float = 2.0, pan: float = 0.0, bus: str = "sfx", gain_db: float | None = None,
             music: list[str] | None = None) -> dict:
        """見せ場の音。打撃と低音を山で揃えて重ね (低音は -4dB)、ライザーの山をそこに合わせる。

        直前 stop_before 秒は音楽 (music のバス、既定は効果音以外の全部) を止め、build 秒前からハイパスで
        低音を抜いて盛り上げる。hit / boom / riser は sfxlib の id か種類か Sound。None で省く。
        """
        from . import sfxlib

        def get(x):
            return sfxlib.sound(x) if isinstance(x, str) else x

        ev = self.sfx(get(hit), t, gain_db, pan, bus, hero=True)
        if boom is not None:
            self.sfx(get(boom), t, -4.0, pan, bus, rel_to=ev)
        if riser is not None:
            self.sfx(get(riser), t, None, pan, bus)
        if stop_before:
            self.stops.append(dict(t=float(t), dur=stop_before, music=music))
        if build:
            self.builds.append(dict(t=float(t), dur=build, music=music))
        return ev

    def room(self, decay: float | None = 0.6, wet_db: float = -16.0) -> None:
        """効果音のバス全体に共通の短い残響 (出所の違う録音を同じ部屋に置く)。None で切る。"""
        self.room_params = None if decay is None else (decay, wet_db)

    def file(self, path: str | Path, t: float = 0.0, offset: float = 0.0, length: float | None = None,
             gain_db: float = 0.0, pan: float = 0.0, bus: str = "media") -> None:
        """音声ファイルや動画の音を、元の offset 秒から時刻 t に配置する。"""
        buf = load_any(path, self.sr)
        self.place(buf[:, int(offset * self.sr):], t, gain_db, pan, bus, length=length)

    def clip(self, clip, gain_db: float = 0.0, pan: float = 0.0, bus: str = "game", fade: float = 0.02,
             mute_holds: bool = True) -> None:
        """footage.Clip の音を、速度変化・逆再生・ジャンプカットに合わせて配置する。

        速度に合わせて音程も変わる (テープを速回し・遅回しした音になる)。フリーズ中は無音にする。
        """
        src = load_any(clip.footage.path, self.sr)
        n = int(clip.duration * self.sr)
        if n <= 0:
            return
        u = np.arange(n) / self.sr
        grid = np.linspace(0.0, clip.duration, max(int(clip.duration * 480), 2))
        s = np.array([clip.time(g) for g in grid]) + clip.src_in
        pos = np.interp(u, grid, s) * self.sr
        idx = np.arange(src.shape[1])
        out = np.vstack([np.interp(pos, idx, ch, left=0.0, right=0.0) for ch in src]).astype(np.float32)
        gain = np.ones(n, np.float32)
        if mute_holds:
            speed = np.abs(np.gradient(np.interp(u, grid, s), u))
            gain = np.clip((speed - 0.05) / 0.1, 0, 1).astype(np.float32)
            k = max(int(0.01 * self.sr), 1)
            gain = np.convolve(gain, np.ones(k) / k, mode="same").astype(np.float32)
        f = min(int(fade * self.sr), n // 2)
        if f > 0:
            gain[:f] *= np.linspace(0, 1, f, dtype=np.float32)
            gain[-f:] *= np.linspace(1, 0, f, dtype=np.float32)
        self.place(out * gain, clip.at, gain_db, pan, bus)

    def hit(self, name: str, t: float, i: int = 0, gain_db: float = 0.0, pan: float = 0.0, bus: str = "drums",
            rate: float = 1.0, length: float | None = None) -> None:
        """サンプル (Dirt-Samples のフォルダ名かファイルパス) を鳴らす。"""
        self.place(load(sample_path(name, i), self.sr), t, gain_db, pan, bus, rate, length)

    def tone(self, t: float, dur: float, pitch: int | str | float, *, wave: str = "saw",
             env: tuple[float, float, float, float] = (0.005, 0.15, 0.6, 0.25), gain_db: float = -12.0,
             pan: float = 0.0, bus: str = "synth", voices: int = 1, detune: float = 0.12,
             glide_from: int | str | float | None = None) -> None:
        """内蔵の簡易シンセで 1 音鳴らす。voices > 1 でデチューンしたユニゾンになる。"""
        a, d, s, r = env
        n = int((dur + r * 2) * self.sr)
        f = hz(pitch)
        out = np.zeros(n, np.float32)
        for v in range(voices):
            cents = (v - (voices - 1) / 2) * detune * 100 / max(voices - 1, 1) if voices > 1 else 0.0
            fv = f * 2 ** (cents / 1200)
            if glide_from is not None:
                f0 = hz(glide_from) * 2 ** (cents / 1200)
                tt = np.arange(n) / self.sr
                freq = fv + (f0 - fv) * np.exp(-tt / 0.06)
                ph = np.cumsum(freq) / self.sr
                out += np.sin(2 * np.pi * ph) if wave == "sine" else 2 * (ph % 1.0) - 1
            else:
                out += _osc(wave, fv, n, self.sr, phase=v * 0.37)
        out *= adsr(n, self.sr, a, d, s, r, dur) / math.sqrt(voices)
        self.place(out, t, gain_db, pan, bus)

    def instrument(self, notes: Iterable[tuple], *, plugin: str = SURGE, patch: str | Path | None = None,
                   bus: str = "inst", gain_db: float = 0.0, params: dict | None = None) -> None:
        """VST3 楽器で (時刻, 長さ, 音高, ベロシティ) のノート列を演奏してバスに足す。

        patch は Surge XT のパッチ名 ("MKS-70 Warm Pad" 等) か .fxp のパス。
        """
        msgs = []
        for note in notes:
            t, dur, pitch = note[:3]
            vel = int(note[3]) if len(note) > 3 else 100
            m = midi(pitch)
            msgs.append((bytes([0x90, m, vel]), float(t)))
            msgs.append((bytes([0x80, m, 0]), float(t + dur)))
        msgs.sort(key=lambda x: x[1])
        stamp = Path(patch).stat().st_mtime if patch is not None and Path(patch).exists() else None
        key = hashlib.sha1(repr((plugin, str(patch), stamp, sorted((params or {}).items()), msgs, self.n,
                                 self.sr)).encode()).hexdigest()[:16]
        # Surge XT は鳴らすたびに位相などが揺れ、音楽に合わせて決める効果音の音量まで毎回変わってしまう
        path = INSTRUMENT_CACHE / f"{key}.npy"
        if path.exists():
            y = np.load(path)
        else:
            p = _plugin(plugin)
            if patch is not None:
                surge_load(p, patch)
            for k, v in (params or {}).items():
                setattr(p, k, v)
            y = p(msgs, duration=self.n / self.sr, sample_rate=self.sr, num_channels=2, reset=True)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(f".{os.getpid()}.tmp.npy")
            np.save(tmp, y)
            os.replace(tmp, path)
        self.bus(bus)[:, :y.shape[1]] += y[:, :self.n] * db(gain_db)

    def fx(self, bus: str, *plugins) -> None:
        self.chains[bus] = list(plugins)

    def gain(self, bus: str, gain_db: float) -> None:
        self.gains[bus] = gain_db

    def duck(self, bus: str, times: Iterable[float], depth_db: float = -9.0, release: float = 0.18) -> None:
        """times のたびに bus の音量を下げる (キックへのサイドチェイン風)。"""
        self.ducks[bus] = (list(times), depth_db, release)

    def _duck_env(self, times, depth_db, release) -> np.ndarray:
        env = np.ones(self.n, np.float32)
        t = np.arange(self.n) / self.sr
        depth = 1 - db(depth_db)
        for c in times:
            i0 = int(c * self.sr)
            if i0 >= self.n:
                continue
            seg = slice(max(i0 - int(0.003 * self.sr), 0), self.n)
            dt = np.clip(t[seg] - c, 0, None)
            attack = np.clip((t[seg] - (c - 0.003)) / 0.003, 0, 1)
            env[seg] = np.minimum(env[seg], 1 - depth * attack * np.exp(-dt / release * 3))
        return env

    def _proc(self, name: str) -> np.ndarray:
        y = self.buses[name]
        if name in self.chains:
            y = pb.Pedalboard(self.chains[name])(y, self.sr)
        if name in self.ducks:
            y = y * self._duck_env(*self.ducks[name])
        z = np.zeros((2, self.n), np.float32)
        z[:, :min(y.shape[1], self.n)] = y[:, :self.n] * db(self.gains.get(name, 0.0))
        return z

    def _processed(self) -> dict[str, np.ndarray]:
        sfx_b = {e["bus"] for e in self.events}
        out = {k: self._proc(k) for k in list(self.buses) if k not in sfx_b}
        for st in self.stops:
            for k in st["music"] or out:
                if k in out:
                    out[k] = _dead_stop(out[k], st["t"], st["dur"], self.sr)
        for b in self.builds:
            for k in b["music"] or out:
                if k in out:
                    out[k] = _hp_build(out[k], b["t"], b["dur"], self.sr)
        bed = sum(out.values(), np.zeros((2, self.n), np.float32)).mean(axis=0)
        end = int(self.duration * self.sr)
        if self._loop:
            # ループ作品は尺を超えた残響が頭に回り込むので、それも含めた音楽に対して音量を決める
            bed = bed.copy()
            for k in range(end, len(bed), end):
                seg = bed[k:k + end]
                bed[:len(seg)] += seg
        self._place_pending(bed)
        for ev, buf, peak in self._bufs:
            pk = int(round(peak * self.sr))
            ev["lift_db"], ev["band"], ev["body_db"] = _lift(buf.mean(axis=0), pk, ev["start"], bed, ev["gain_db"],
                                                             self.sr)
        for k in sorted(sfx_b):
            if k in self.buses:
                y = self._proc(k)
                out[k] = _room(y, *self.room_params, self.sr) if self.room_params else y
        return out

    def _place_pending(self, bed: np.ndarray) -> None:
        done = []
        # 重ねる層は親の音量が決まってから置く
        for p in sorted(self._pending, key=lambda p: p["rel_to"] is not None):
            ev = p["ev"]
            if p["rel_to"] is not None:
                ev["gain_db"] = round(p["rel_to"]["gain_db"] + p["offset"], 2)
            else:
                kind = ev["origin"].split("/")[0]
                prev = [d["ev"] for d in done if d["rel_to"] is None and d["ev"]["t"] <= ev["t"]]
                g = _solve_gain(p["buf"].mean(axis=0), int(round(p["peak"] * self.sr)), ev["start"], bed, ev["hero"],
                                self.sr)
                # 0.15 秒以内に別の音が続くと 0.6 倍 (見せ場に重ねる音と、打鍵のような同じ種類の連打は除く)
                last = max(prev, key=lambda e: e["t"]) if prev else None
                in_hero = any(e["hero"] and e["t"] == ev["t"] for e in self.events)
                if (last and ev["t"] - last["t"] < 0.15 and not ev["hero"] and not in_hero
                        and (kind == "synth" or last["origin"].split("/")[0] != kind)):
                    g += 20 * math.log10(0.6)
                ev["gain_db"] = round(g, 2)
            self.place(p["buf"], ev["start"], ev["gain_db"], p["pan"], ev["bus"])
            done.append(p)
        self._pending = []

    def mixdown(self) -> np.ndarray:
        return sum(self._processed().values(), np.zeros((2, self.n), np.float32))

    def render(self, path: str | Path, lufs: float = -14.0, ceiling_db: float = -2.0,
               master: list | None = None, loop: bool = False) -> str:
        """ミックスダウンし、ラウドネスを lufs に揃え、リミッターをかけて書き出す。

        loop=True なら、尺を超えた残響を頭に足し込み、末尾のフェードもかけない (継ぎ目なく繰り返せる)。
        天井の既定 -2dB は、AAC にした後の真のピークを -1dBTP 以下に保つため。
        横に <名前>.sfx.wav (効果音のバス) と <名前>.bed.wav (それ以外) と <名前>.mix.json (効果音の記録) を書く。
        """
        self._loop = loop
        procs = self._processed()
        src = sum(procs.values(), np.zeros((2, self.n), np.float32))
        if master:
            src = pb.Pedalboard(master)(src, self.sr)
        sfx_buses = sorted({e["bus"] for e in self.events})
        stems = {"sfx": sum((procs[b] for b in sfx_buses if b in procs), np.zeros((2, self.n), np.float32)),
                 "bed": sum((v for k, v in procs.items() if k not in sfx_buses), np.zeros((2, self.n), np.float32))}
        end = int(self.duration * self.sr)

        def fold(x):
            tail = x[:, end:]
            x = x[:, :end].copy()
            if loop:
                for k in range(0, tail.shape[1], end):
                    seg = tail[:, k:k + end]
                    x[:, :seg.shape[1]] += seg
            return x

        src = fold(src)
        stems = {k: fold(v) for k, v in stems.items()}
        import pyloudnorm
        meter = pyloudnorm.Meter(self.sr)
        # リミッターでラウドネスが下がる分を、計り直して詰めていく
        g = 1.0
        y = src
        for _ in range(4):
            y = limit(src * g, self.sr, ceiling_db)
            gy = g
            cur = meter.integrated_loudness(y.T.astype(np.float64))
            if not np.isfinite(cur) or abs(cur - lufs) < 0.1:
                break
            g *= db(lufs - cur)
        if not loop:
            fade = int(0.02 * self.sr)
            y[:, -fade:] *= np.linspace(1, 0, fade, dtype=np.float32)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with AudioFile(str(path), "w", self.sr, num_channels=2) as f:
            f.write(y)
        base = Path(path).with_suffix("")
        for k, v in stems.items():
            with AudioFile(f"{base}.{k}.wav", "w", self.sr, num_channels=2) as f:
                f.write((v * gy).astype(np.float32))
        report = dict(duration=self.duration, lufs=lufs, ceiling_db=ceiling_db, gain_db=round(20 * math.log10(gy), 2),
                      loop=loop, sfx_buses=sfx_buses, events=self.events,
                      stops=[dict(t=x["t"], dur=x["dur"]) for x in self.stops],
                      builds=[dict(t=x["t"], dur=x["dur"]) for x in self.builds])
        Path(f"{base}.mix.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        return str(path)
