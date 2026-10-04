"""長いキャプチャを解析して、見せ場の候補 (動きが激しい・音が大きい区間) とシーンの切れ目を探す。"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .audio import load_any
from .media import probe


@dataclass
class Moment:
    start: float
    end: float
    score: float
    motion: float
    loudness: float

    @property
    def mid(self) -> float:
        return (self.start + self.end) / 2


@dataclass
class ScanResult:
    duration: float
    step: float
    times: np.ndarray
    motion: np.ndarray       # 0〜1 に正規化した動きの量
    loudness: np.ndarray     # 0〜1 に正規化した音の大きさ
    cuts: list[float]        # シーンの切れ目 (画面が大きく変わった時刻)

    def highlights(self, n: int = 5, length: float = 3.0, gap: float = 1.0,
                   w_motion: float = 1.0, w_audio: float = 1.0) -> list[Moment]:
        """スコアの高い順に、重ならない長さ length 秒の区間を n 個選ぶ。"""
        k = max(int(round(length / self.step)), 1)
        score = w_motion * self.motion + w_audio * self.loudness
        win = np.convolve(score, np.ones(k) / k, mode="valid")
        order = np.argsort(win)[::-1]
        picked: list[Moment] = []
        for i in order:
            s = float(self.times[i])
            if any(abs(s - m.start) < length + gap for m in picked):
                continue
            e = min(s + length, self.duration)
            picked.append(Moment(s, e, float(win[i]), float(self.motion[i:i + k].mean()),
                                 float(self.loudness[i:i + k].mean())))
            if len(picked) >= n:
                break
        return sorted(picked, key=lambda m: m.start)


def _norm(x: np.ndarray) -> np.ndarray:
    lo, hi = np.percentile(x, 5), np.percentile(x, 98)
    return np.clip((x - lo) / (hi - lo + 1e-9), 0, 1)


def scan(path: str | Path, step: float = 0.25, cut_threshold: float = 0.35) -> ScanResult:
    """動画を低解像度でざっと読み、step 秒ごとの動きの量と音の大きさを測る。"""
    info = probe(path)
    fps = 1 / step
    w, h = 160, 90
    cmd = ["ffmpeg", "-loglevel", "error", "-i", str(path), "-vf", f"fps={fps},scale={w}:{h},format=gray",
           "-f", "rawvideo", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    frames = np.frombuffer(raw, np.uint8).reshape(-1, h, w).astype(np.float32) / 255.0
    n = len(frames)
    times = np.arange(n) * step
    diff = np.zeros(n, np.float32)
    if n > 1:
        diff[1:] = np.abs(np.diff(frames, axis=0)).mean(axis=(1, 2))
    # 画面全体が入れ替わるような変化はシーンの切れ目とみなし、動きの量からは外す
    hist_d = np.zeros(n, np.float32)
    for i in range(1, n):
        a = cv2.calcHist([frames[i - 1]], [0], None, [32], [0, 1])
        b = cv2.calcHist([frames[i]], [0], None, [32], [0, 1])
        hist_d[i] = cv2.compareHist(a, b, cv2.HISTCMP_BHATTACHARYYA)
    cuts = [float(times[i]) for i in range(1, n) if hist_d[i] > cut_threshold]
    motion = diff.copy()
    for ct in cuts:
        motion[int(round(ct / step))] = np.median(diff)
    try:
        y = load_any(path, 16000).mean(axis=0)
        hop = int(16000 * step)
        m = min(n, len(y) // hop)
        rms = np.sqrt((y[:m * hop].reshape(m, hop) ** 2).mean(axis=1) + 1e-12)
        loud = np.zeros(n, np.float32)
        loud[:m] = 20 * np.log10(rms)
        loud[m:] = loud[:m].min() if m else 0
    except Exception:
        loud = np.zeros(n, np.float32)
    return ScanResult(info["duration"], step, times, _norm(motion), _norm(loud) if loud.any() else loud, cuts)


def report(res: ScanResult, path: str | Path, out: str | Path, moments: list[Moment]) -> Path:
    """動き・音のグラフと、候補区間の中央フレームを並べた画像を書き出す。"""
    W = 1600
    G = 220
    img = np.full((G + 40, W, 3), 18, np.uint8)
    xs = (res.times / max(res.duration, 1e-6) * (W - 40) + 20).astype(int)

    def plot(vals, color):
        pts = np.stack([xs, (G - 10 - vals * (G - 30)).astype(int)], 1)
        cv2.polylines(img, [pts.reshape(-1, 1, 2)], False, color, 2, cv2.LINE_AA)

    for m in moments:
        x0 = int(m.start / res.duration * (W - 40) + 20)
        x1 = int(m.end / res.duration * (W - 40) + 20)
        cv2.rectangle(img, (x0, 10), (x1, G - 10), (60, 50, 20), -1)
    plot(res.motion, (255, 180, 80))
    plot(res.loudness, (80, 200, 120))
    for ct in res.cuts:
        x = int(ct / res.duration * (W - 40) + 20)
        cv2.line(img, (x, 10), (x, G - 10), (80, 80, 220), 1)
    cv2.putText(img, "motion", (24, G + 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 180, 80), 1, cv2.LINE_AA)
    cv2.putText(img, "loudness", (110, G + 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (80, 200, 120), 1, cv2.LINE_AA)
    cv2.putText(img, "cut", (220, G + 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (80, 80, 220), 1, cv2.LINE_AA)
    thumbs = []
    tw = W // max(len(moments), 1)
    for i, m in enumerate(moments):
        raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", f"{m.mid:.3f}", "-i", str(path), "-frames:v", "1",
                              "-vf", f"scale={tw}:-2", "-f", "image2pipe", "-vcodec", "png", "-"],
                             capture_output=True, check=True).stdout
        th = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        cv2.putText(th, f"#{i + 1} {m.start:.1f}-{m.end:.1f}s", (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (0, 0, 0), 4, cv2.LINE_AA)
        cv2.putText(th, f"#{i + 1} {m.start:.1f}-{m.end:.1f}s", (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (80, 230, 255), 1, cv2.LINE_AA)
        thumbs.append(th)
    if thumbs:
        hmax = max(t.shape[0] for t in thumbs)
        row = np.full((hmax, W, 3), 18, np.uint8)
        for i, th in enumerate(thumbs):
            row[:th.shape[0], i * tw:i * tw + th.shape[1]] = th[:, :min(th.shape[1], W - i * tw)]
        img = np.vstack([img, row])
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), img)
    return out
