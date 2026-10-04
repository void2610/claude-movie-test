"""サンプルの配置・簡易シンセ・VST 楽器・バスエフェクトによるミックスダウン。

時刻はすべて秒。Timeline.beat() 等で拍から変換して渡す。
"""
from __future__ import annotations

import hashlib
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
import pyloudnorm
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


class Mix:
    def __init__(self, duration: float, sr: int = SR, tail: float = 1.5):
        self.sr = sr
        self.duration = duration
        self.n = int((duration + tail) * sr)
        self.buses: dict[str, np.ndarray] = {}
        self.chains: dict[str, list] = {}
        self.gains: dict[str, float] = {}
        self.ducks: dict[str, tuple] = {}

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

    def file(self, path: str | Path, t: float = 0.0, offset: float = 0.0, length: float | None = None,
             gain_db: float = 0.0, pan: float = 0.0, bus: str = "media") -> None:
        """音声ファイルや動画の音を、元の offset 秒から時刻 t に配置する。"""
        buf = load_any(path, self.sr)
        self.place(buf[:, int(offset * self.sr):], t, gain_db, pan, bus, length=length)

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
        p = _plugin(plugin)
        if patch is not None:
            surge_load(p, patch)
        for k, v in (params or {}).items():
            setattr(p, k, v)
        msgs = []
        for note in notes:
            t, dur, pitch = note[:3]
            vel = int(note[3]) if len(note) > 3 else 100
            m = midi(pitch)
            msgs.append((bytes([0x90, m, vel]), float(t)))
            msgs.append((bytes([0x80, m, 0]), float(t + dur)))
        msgs.sort(key=lambda x: x[1])
        y = p(msgs, duration=self.n / self.sr, sample_rate=self.sr, num_channels=2, reset=True)
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

    def mixdown(self) -> np.ndarray:
        out = np.zeros((2, self.n), np.float32)
        for name, buf in self.buses.items():
            y = buf
            if name in self.chains:
                y = pb.Pedalboard(self.chains[name])(y, self.sr)
            if name in self.ducks:
                y = y * self._duck_env(*self.ducks[name])
            out[:, :y.shape[1]] += y[:, :self.n] * db(self.gains.get(name, 0.0))
        return out

    def render(self, path: str | Path, lufs: float = -14.0, ceiling_db: float = -1.0,
               master: list | None = None) -> str:
        """ミックスダウンし、ラウドネスを lufs に揃え、リミッターをかけて書き出す。"""
        src = self.mixdown()
        if master:
            src = pb.Pedalboard(master)(src, self.sr)
        end = int(self.duration * self.sr)
        src = src[:, :end]
        meter = pyloudnorm.Meter(self.sr)
        # リミッターでラウドネスが下がる分を、計り直して詰めていく
        g = 1.0
        y = src
        for _ in range(4):
            y = limit(src * g, self.sr, ceiling_db)
            cur = meter.integrated_loudness(y.T.astype(np.float64))
            if not np.isfinite(cur) or abs(cur - lufs) < 0.1:
                break
            g *= db(lufs - cur)
        fade = int(0.02 * self.sr)
        y[:, -fade:] *= np.linspace(1, 0, fade, dtype=np.float32)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with AudioFile(str(path), "w", self.sr, num_channels=2) as f:
            f.write(y)
        return str(path)
