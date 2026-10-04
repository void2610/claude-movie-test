"""既存の曲を解析して、映像を音楽に合わせるための拍・小節・オンセットを得る。

    info = analysis.analyze("song.mp3")
    comp = Composition(bpm=info.bpm, beat_offset=info.downbeats[0], duration=info.duration)
    comp.cues = info.onsets_strong          # 強いアタックに映像の衝撃を合わせる
"""
from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

import librosa
import numpy as np

from .timeline import Timeline


@dataclass
class MusicInfo:
    bpm: float
    beats: list[float]
    downbeats: list[float]
    onsets: list[float]
    onsets_strong: list[float]
    duration: float

    def timeline(self, beats_per_bar: int = 4) -> Timeline:
        return Timeline(self.bpm, self.downbeats[0] if self.downbeats else 0.0, beats_per_bar)

    def shift_downbeats(self, n: int, beats_per_bar: int = 4) -> MusicInfo:
        """小節頭の推定が n 拍ずれているときに補正する (毎拍キックの曲などでは推定が曖昧になる)。"""
        idx = int(np.argmin(np.abs(np.asarray(self.beats) - self.downbeats[0]))) + n
        return MusicInfo(self.bpm, self.beats, self.beats[idx % beats_per_bar::beats_per_bar], self.onsets,
                         self.onsets_strong, self.duration)

    def nearest_beat(self, t: float) -> float:
        b = np.asarray(self.beats)
        return float(b[np.argmin(np.abs(b - t))]) if len(b) else t


def analyze(path: str | Path, beats_per_bar: int = 4, bpm_hint: float | None = None,
            cache: bool = True) -> MusicInfo:
    p = Path(path).resolve()
    key = hashlib.sha1(f"{p}{p.stat().st_mtime}{beats_per_bar}{bpm_hint}".encode()).hexdigest()[:16]
    cache_file = Path(tempfile.gettempdir()) / f"motion-analysis-{key}.json"
    if cache and cache_file.exists():
        return MusicInfo(**json.loads(cache_file.read_text()))

    y, sr = librosa.load(str(p), sr=22050, mono=True)
    hop = 256
    env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop)
    kw = {"start_bpm": bpm_hint} if bpm_hint else {}
    tempo, beat_frames = librosa.beat.beat_track(onset_envelope=env, sr=sr, hop_length=hop, units="frames", **kw)
    beats = librosa.frames_to_time(beat_frames, sr=sr, hop_length=hop)
    bpm = float(np.atleast_1d(tempo)[0])
    if len(beats) > 4:
        # 拍の位置はフレーム単位に量子化されているので、拍番号と時刻の回帰直線の傾きから BPM を求める
        slope = np.polyfit(np.arange(len(beats)), beats, 1)[0]
        bpm = 60.0 / float(slope)

    # 小節頭: 低音域のアタックと和音の変わり目 (クロマの変化) が最も多く乗る位相を選ぶ
    S = np.abs(librosa.stft(y, hop_length=hop))
    freqs = librosa.fft_frequencies(sr=sr)
    low = librosa.onset.onset_strength(S=librosa.amplitude_to_db(S[freqs < 150]), sr=sr, hop_length=hop)
    phase = 0
    if len(beat_frames) > beats_per_bar:
        chroma = librosa.feature.chroma_stft(S=S ** 2, sr=sr, hop_length=hop)
        sync = librosa.util.sync(chroma, beat_frames, aggregate=np.median)
        # sync の先頭は最初の拍より前の区間なので、diff の j 番目が j 番目の拍での変化になる
        change = np.linalg.norm(np.diff(sync, axis=1), axis=0)[:len(beat_frames)]
        lows = low[beat_frames]

        def z(v):
            return (v - v.mean()) / (v.std() + 1e-9)

        score = z(lows) + z(change)
        phase = int(np.argmax([score[k::beats_per_bar].mean() for k in range(beats_per_bar)]))
    downbeats = beats[phase::beats_per_bar]

    onset_frames = librosa.onset.onset_detect(onset_envelope=env, sr=sr, hop_length=hop, units="frames")
    onsets = librosa.frames_to_time(onset_frames, sr=sr, hop_length=hop)
    strengths = env[onset_frames] if len(onset_frames) else np.array([])
    strong = onsets[strengths >= np.percentile(strengths, 80)] if len(strengths) else onsets

    info = MusicInfo(bpm=round(bpm, 3), beats=[round(float(b), 4) for b in beats],
                     downbeats=[round(float(b), 4) for b in downbeats],
                     onsets=[round(float(o), 4) for o in onsets], onsets_strong=[round(float(o), 4) for o in strong],
                     duration=round(len(y) / sr, 4))
    if cache:
        cache_file.write_text(json.dumps(asdict(info)))
    return info
