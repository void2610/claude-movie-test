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

    # 小節頭: 低音域のオンセットが最も強く乗る位相を選ぶ
    S = np.abs(librosa.stft(y, hop_length=hop))
    freqs = librosa.fft_frequencies(sr=sr)
    low = librosa.onset.onset_strength(S=librosa.amplitude_to_db(S[freqs < 150]), sr=sr, hop_length=hop)
    scores = [low[beat_frames[k::beats_per_bar]].sum() if len(beat_frames) > k else 0
              for k in range(beats_per_bar)]
    phase = int(np.argmax(scores)) if len(beat_frames) else 0
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
