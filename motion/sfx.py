"""効果音の合成。各関数は Sound を返し、Mix.sfx(sound, t) で山 (peak) が時刻 t に来るように置ける。

打撃・クリック・風切りは合成せず、録音のライブラリ (sfxlib) から選ぶ。合成の音は安っぽいビープ音になりやすく、
review が「合成の効果音」として数える。ここの関数は、録音が無い音 (音楽的なアクセント・試作) に限って使う。

    mx.sfx(sfxlib.sound("whoosh", like="air"), cut_time)   # 録音を使う
    mx.sfx(sfx.riser(2.0), drop_time)                      # 合成 (試作用)
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

SR = 48000


@dataclass
class Sound:
    buf: np.ndarray  # (2, n) float32
    peak: float      # 山の位置 (秒)
    origin: str = "synth"  # 録音なら sfxlib の id

    @property
    def duration(self) -> float:
        return self.buf.shape[1] / SR

    def pitched(self, semitones: float) -> "Sound":
        """再生速度を変えて音程をずらす (長さも変わる)。"""
        if not semitones:
            return self
        rate = 2 ** (semitones / 12)
        src = np.arange(self.buf.shape[1])
        pos = np.arange(0, self.buf.shape[1] - 1, rate)
        buf = np.vstack([np.interp(pos, src, ch) for ch in self.buf]).astype(np.float32)
        return Sound(buf, self.peak / rate, self.origin)


def _stereo(x: np.ndarray, pan: np.ndarray | float = 0.0) -> np.ndarray:
    a = (np.asarray(pan) + 1) * np.pi / 4
    return (np.vstack([x * np.cos(a), x * np.sin(a)]) * np.sqrt(2)).astype(np.float32)


def _norm(x: np.ndarray, peak: float = 0.9) -> np.ndarray:
    m = np.abs(x).max()
    return x * (peak / m) if m > 0 else x


def swept_noise(dur: float, fc: callable, q: float = 1.5, seed: int = 0, n_fft: int = 1024) -> np.ndarray:
    """中心周波数 fc(t) [Hz] が時間とともに動くバンドパスをかけたノイズ (モノラル)。"""
    hop = n_fft // 4
    n = int(dur * SR)
    rng = np.random.default_rng(seed)
    x = rng.standard_normal(n + n_fft).astype(np.float32)
    win = np.hanning(n_fft).astype(np.float32)
    idx = np.arange(0, n, hop)
    frames = np.stack([x[i:i + n_fft] * win for i in idx])
    spec = np.fft.rfft(frames, axis=1)
    freqs = np.fft.rfftfreq(n_fft, 1 / SR)
    centers = np.array([fc(i / SR) for i in idx])[:, None]
    # 対数周波数上のガウス窓。q が大きいほど帯域が狭い
    gain = np.exp(-0.5 * (np.log2(np.maximum(freqs[None, :], 1) / centers) * q) ** 2)
    out_frames = np.fft.irfft(spec * gain, n=n_fft, axis=1) * win
    out = np.zeros(n + n_fft, np.float32)
    for k, i in enumerate(idx):
        out[i:i + n_fft] += out_frames[k]
    return out[:n]


def _env(n: int, attack: float, release_curve: float = 3.0) -> np.ndarray:
    """0→1 を attack (0〜1 の比率) まで上げ、その後 0 へ下げる山型の包絡。"""
    t = np.linspace(0, 1, n, dtype=np.float32)
    a = max(attack, 1e-3)
    up = (t / a) ** 2
    down = np.clip((1 - t) / (1 - a + 1e-6), 0, 1) ** release_curve
    return np.where(t < a, up, down)


def whoosh(dur: float = 0.6, rise: float = 0.55, f0: float = 250.0, f1: float = 3500.0, q: float = 1.2,
           pan_from: float = -0.6, pan_to: float = 0.6, seed: int = 0) -> Sound:
    """風切り音。周波数と音量が rise の位置で頂点になり、左右に流れる。"""
    n = int(dur * SR)
    peak = rise * dur

    def fc(t):
        u = t / dur
        return f0 + (f1 - f0) * (u / rise if u < rise else max(1 - (u - rise) / (1 - rise), 0) * 0.6 + 0.4)

    x = swept_noise(dur, fc, q, seed) * _env(n, rise, 2.0)
    pan = np.linspace(pan_from, pan_to, n)
    return Sound(_stereo(_norm(x, 0.8), pan), peak)


def riser(dur: float = 2.0, f0: float = 200.0, f1: float = 6000.0, tone: bool = True, seed: int = 1) -> Sound:
    """だんだん高く大きくなる音。最後の瞬間が山。"""
    n = int(dur * SR)
    noise = swept_noise(dur, lambda t: f0 * (f1 / f0) ** (t / dur), 1.0, seed)
    t = np.arange(n) / SR
    out = noise * 0.7
    if tone:
        # 音程も対数的に上げる (ノコギリ波 3 本を少しずらす)
        for det in (-0.08, 0.0, 0.08):
            f = 110 * (2 ** (det / 12)) * (8 ** (t / dur))
            ph = np.cumsum(f) / SR
            out = out + (2 * (ph % 1.0) - 1) * 0.12
    env = (t / dur) ** 2.5
    return Sound(_stereo(_norm(out * env, 0.85)), dur)


def impact(dur: float = 1.4, f_start: float = 140.0, f_end: float = 38.0, noise: float = 0.5, seed: int = 2) -> Sound:
    """ドンという衝撃音 (サブの急降下 + ノイズの破裂 + クリック)。先頭が山。"""
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = f_end + (f_start - f_end) * np.exp(-t * 18)
    sub = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 3.2)
    burst = swept_noise(dur, lambda tt: 1800 * np.exp(-tt * 6) + 120, 0.6, seed) * np.exp(-t * 9) * noise
    click = np.zeros(n, np.float32)
    k = int(0.004 * SR)
    click[:k] = np.random.default_rng(seed).uniform(-1, 1, k) * np.linspace(1, 0, k)
    x = np.tanh((sub + burst + click * 0.6) * 1.5)
    return Sound(_stereo(_norm(x, 0.95)), 0.0)


def click(freq: float = 2800.0, dur: float = 0.03, pan: float = 0.0) -> Sound:
    """UI 風の短いクリック音。"""
    n = int(dur * SR)
    t = np.arange(n) / SR
    x = np.sin(2 * np.pi * freq * t) * np.exp(-t * 180)
    return Sound(_stereo(_norm(x, 0.7), pan), 0.0)


def glitch(dur: float = 0.4, seed: int = 3) -> Sound:
    """デジタルなノイズの断片。ビット深度を落とした短い音片をランダムに並べる。"""
    rng = np.random.default_rng(seed)
    n = int(dur * SR)
    out = np.zeros(n, np.float32)
    i = 0
    while i < n:
        seg = int(rng.uniform(0.008, 0.04) * SR)
        kind = rng.integers(0, 3)
        tt = np.arange(seg) / SR
        if kind == 0:
            s = np.sign(np.sin(2 * np.pi * rng.uniform(80, 1200) * tt))
        elif kind == 1:
            s = rng.uniform(-1, 1, seg)
        else:
            s = np.zeros(seg)
        bits = rng.integers(2, 6)
        s = np.round(s * 2 ** bits) / 2 ** bits
        out[i:i + seg] = s[: n - i] * rng.uniform(0.3, 1.0)
        i += seg
    return Sound(_stereo(_norm(out, 0.6), rng.uniform(-0.5, 0.5)), 0.0)


def reverse_swell(dur: float = 1.0, seed: int = 4) -> Sound:
    """シンバルを逆再生したような吸い込み音。最後が山。"""
    n = int(dur * SR)
    t = np.arange(n) / SR
    x = swept_noise(dur, lambda tt: 6000 + 4000 * tt / dur, 0.7, seed) * np.exp(-(dur - t) * 4.5)
    return Sound(_stereo(_norm(x, 0.8)), dur)
