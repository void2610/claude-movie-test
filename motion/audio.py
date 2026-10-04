"""サンプルの配置・簡易シンセ・VST 楽器・バスエフェクトによるミックスダウン。

時刻はすべて秒。Timeline.beat() 等で拍から変換して渡す。
"""
from __future__ import annotations

import math
import os
import re
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

    def instrument(self, notes: Iterable[tuple], *, plugin: str = SURGE, bus: str = "inst", gain_db: float = 0.0,
                   params: dict | None = None) -> None:
        """VST3 楽器で (時刻, 長さ, 音高, ベロシティ) のノート列を演奏してバスに足す。"""
        p = _plugin(plugin)
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
