"""批評用のレビューシート。書き出し前に「どこが、なぜ悪いか」を画像と数値で確かめる。

    uv run python -m motion review projects/demo

ショットごとの頭・中・終わりのコマ、カット前後の連続コマ、音の波形とカット・キューの位置、
スマホ幅での見え方、自動計測 (ペース・音とのずれ・セーフエリア・ループ) を 1 枚にまとめ、
reviews/ に review.png と、欠点を書き込む review.md を残す。
"""
from __future__ import annotations

import datetime
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import skia

from .render import _pool, _render_one, load_project, prepare
from .shots import Shot, ShotList
from .text import text as draw_text

BG = skia.Color(18, 18, 22)
FG = "#E8E8EC"
DIM = "#8A8C97"
WARN = "#FF7A45"
OK = "#4ADE80"


@dataclass
class Metrics:
    rest_ratio: float               # 動きの少ない時間の割合 (目安 0.4〜0.6)
    contrast: float                 # 動きの起伏 (p90 - p10) / p50。0.15 未満は平坦
    pops: list[float]               # 1 フレームだけ前後と違う瞬間 (閃き・破綻の候補)
    pace: float | None              # 意味のある変化の平均間隔 (秒)
    changes: list[float]            # 変化が起きた時刻
    sync: list[tuple[str, float, float, bool]]   # (種類, 時刻, 8 分のグリッドからのずれ ms, 音の立ち上がりがあるか)
    edge_ink: dict[int, float]      # フレーム → 端 5% に描かれている量 (0〜1)
    loop_diff: float | None         # 最初と最後のコマの差 (0〜255)


def _default_shots(comp) -> ShotList:
    """ショットリストが無いときは 2 小節ずつに区切る。"""
    step = comp.timeline.bar_len * 2
    n = max(int(math.ceil(comp.duration / step)), 1)
    return ShotList([Shot(f"{i * 2 + 1:02d}-{i * 2 + 2:02d}小節", i * step, min((i + 1) * step, comp.duration))
                     for i in range(n)])


def _render(project, frames: list[int], scale: float, workers=None) -> dict[int, np.ndarray]:
    frames = sorted(set(frames))
    comp = load_project(project)
    w, h = max(int(round(comp.width * scale)), 1), max(int(round(comp.height * scale)), 1)
    with _pool(project, scale, False, True, workers) as pool:
        return {f: np.frombuffer(b, np.uint8).reshape(h, w, 3)
                for f, b in zip(frames, pool.imap(_render_one, frames, chunksize=2))}


def _attack_offsets(wav: str, times: list[float], window: float = 0.06) -> list[tuple[float | None, float]]:
    """各時刻の前後 window 秒で最も急な音量の立ち上がりの位置 (ms) と、その鋭さ (周囲 2 秒の中央値比) を返す。

    密なミックスでは「どの立ち上がりがその拍の音か」を ms 単位では決められないので、鋭さは有無の判定にだけ使う。
    スペクトル差分 (librosa の onset) は約 93ms の窓で時刻がずれ、低音だけのキックにほぼ反応しないため使わない。
    """
    from .audio import load
    y = load(wav).mean(axis=0)
    sr = 48000
    win, hop = int(sr * 0.005), int(sr * 0.0025)
    n = (len(y) - win) // hop
    idx = np.arange(n)[:, None] * hop + np.arange(win)[None, :]
    db = 10 * np.log10((y[idx] ** 2).mean(axis=1) + 1e-10)
    rise = np.maximum(np.diff(db, prepend=db[0]), 0)
    tt = np.arange(n) * hop / sr + win / (2 * sr)
    out = []
    for t in times:
        m = (tt >= t - window) & (tt <= t + window)
        if not m.any():
            out.append((None, 0.0))
            continue
        i = np.flatnonzero(m)[np.argmax(rise[m])]
        around = rise[(tt >= t - 1) & (tt <= t + 1)]
        out.append(((tt[i] - t) * 1000, float(rise[i] / (np.median(around[around > 0]) + 1e-9))))
    return out


def _waveform(wav: str, n: int) -> np.ndarray:
    from .audio import load
    y = np.abs(load(wav).mean(axis=0))
    k = max(len(y) // n, 1)
    return y[:k * n].reshape(n, k).max(axis=1)


def measure(project, comp, shots: ShotList, scale: float = 0.08, wav: str | None = None) -> Metrics:
    fps = comp.fps
    frames = list(range(comp.nframes))
    imgs = _render(project, frames, scale)
    arr = np.stack([imgs[f].astype(np.float32).mean(axis=2) for f in frames])
    full = np.r_[0.0, np.abs(np.diff(arr, axis=0)).mean(axis=(1, 2))]
    # 1 フレームだけの閃き: n が前後と大きく違うのに、n-1 と n+1 同士はほぼ同じ
    pops = []
    for n in range(1, len(arr) - 1):
        around = np.abs(arr[n + 1] - arr[n - 1]).mean()
        if full[n] > 6 and full[n + 1] > 6 and around < min(full[n], full[n + 1]) * 0.35:
            pops.append(n / fps)
    k = max(int(fps), 1)
    energy = np.convolve(full, np.ones(k) / k, mode="same")
    p10, p50, p90 = np.percentile(energy, [10, 50, 90])
    # グレインが動きの底を持ち上げるので、0 ではなく p10 を基準に「静止」を測る
    rest_ratio = float((energy < p10 + 0.35 * (p90 - p10)).mean())
    contrast = float((p90 - p10) / (p50 + 1e-6))
    step = max(int(fps / 15), 1)
    frames = frames[::step]
    diff = np.r_[0.0, np.abs(np.diff(arr[::step], axis=0)).mean(axis=(1, 2))]
    # 局所的な山だけを「意味のある変化」とみなす (常に動いている背景は数えない)
    base = np.median(diff) + 1e-6
    peaks = [i for i in range(1, len(diff) - 1)
             if diff[i] > max(base * 3, 2.0) and diff[i] >= diff[i - 1] and diff[i] >= diff[i + 1]]
    changes = [frames[i] / fps for i in peaks]
    pace = float(np.mean(np.diff([0.0] + changes))) if changes else None
    edge = {}
    for f in frames[:: max(len(frames) // 24, 1)]:
        g = imgs[f].astype(np.float32).mean(axis=2)
        h, w = g.shape
        my, mx = max(int(h * 0.05), 1), max(int(w * 0.05), 1)
        bgv = np.median(g)
        ink = np.abs(g - bgv) > 40
        border = np.ones_like(ink)
        border[my:-my, mx:-mx] = False
        edge[f] = float(ink[border].mean())
    sync = []
    grid = comp.timeline.beat_len / 2
    for kind, ts in (("カット", shots.cuts), ("キュー", list(comp.cues))):
        strengths = _attack_offsets(wav, list(ts)) if wav else [(None, 9.9)] * len(ts)
        for t, (_, strength) in zip(ts, strengths):
            off = (t - comp.timeline.offset) / grid
            sync.append((kind, t, (off - round(off)) * grid * 1000, strength >= 1.8))
    loop_diff = None
    if comp.loop:
        a = _render(project, [0, comp.nframes - 1], 0.25)
        loop_diff = float(np.abs(a[0].astype(int) - a[comp.nframes - 1].astype(int)).mean())
    return Metrics(rest_ratio, contrast, pops, pace, changes, sync, edge, loop_diff)


class _Sheet:
    def __init__(self, w: int, h: int):
        self.surface = skia.Surface(w, h)
        self.c = self.surface.getCanvas()
        self.c.clear(BG)

    def image(self, img: np.ndarray, x: float, y: float, w: float | None = None) -> float:
        h0, w0 = img.shape[:2]
        rgba = np.dstack([img, np.full((h0, w0), 255, np.uint8)])
        sk = skia.Image.fromarray(np.ascontiguousarray(rgba), colorType=skia.kRGBA_8888_ColorType)
        w = w or w0
        h = h0 * w / w0
        self.c.drawImageRect(sk, skia.Rect.MakeXYWH(x, y, w, h), skia.SamplingOptions(skia.FilterMode.kLinear))
        return h

    def text(self, s: str, x: float, y: float, size: float = 16, color: str = FG, font: str = "sans", **kw):
        draw_text(self.c, s, x, y, font=font, size=size, color=color, valign="cap", **kw)

    def save(self, path: Path) -> None:
        img = self.surface.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)
        import cv2
        cv2.imwrite(str(path), cv2.cvtColor(img, cv2.COLOR_RGBA2BGR))


def review(project: str | Path, out_dir: str | Path | None = None, scale: float = 0.22, workers=None) -> Path:
    comp = load_project(project)
    prepare(comp)
    shots = comp.shots or _default_shots(comp)
    fps = comp.fps
    f_of = lambda t: min(max(int(round(t * fps)), 0), comp.nframes - 1)  # noqa: E731

    wav = comp.audio(comp) if comp.audio else None
    print("review: measuring...", flush=True)
    m = measure(project, comp, shots, wav=wav)

    shot_frames = {s.name: [f_of(s.start + min(0.15, s.dur * 0.1)), f_of(s.at(0.5)),
                            f_of(s.end - min(0.15, s.dur * 0.1))] for s in shots}
    offs = [-0.25, -0.1, -0.034, 0.0, 0.034, 0.1, 0.25]
    cut_frames = {c: [f_of(c + o) for o in offs] for c in shots.cuts}
    want = [f for v in shot_frames.values() for f in v] + [f for v in cut_frames.values() for f in v]
    want += [0, comp.nframes - 1]
    print(f"review: rendering {len(set(want))} frames...", flush=True)
    imgs = _render(project, want, scale, workers)
    phone = _render(project, [shot_frames[s.name][1] for s in shots], 360 / max(comp.width, comp.height))

    tw = int(comp.width * scale)
    th = int(comp.height * scale)
    W = max(3 * (tw + 12) + 380, 7 * (int(tw * 0.55) + 6) + 40, 1400)
    row_h = th + 50
    cut_h = int(th * 0.55) + 44
    H = 120 + len(shots) * row_h + len(cut_frames) * cut_h + 260 + max(i.shape[0] for i in phone.values()) + 120
    sh = _Sheet(W, H)
    y = 40
    sh.text(f"{comp.name}  レビュー  {datetime.datetime.now():%Y-%m-%d %H:%M}", 24, y, 26)
    pace = f"{m.pace:.2f} 秒ごと" if m.pace else "変化なし"
    sh.text(f"{comp.width}x{comp.height}  {fps}fps  {comp.duration:.1f}s  {comp.bpm} BPM   "
            f"ペース: {pace}   静止 {m.rest_ratio:.0%}   起伏 {m.contrast:.3f}   閃き {len(m.pops)}", 24, y + 34, 16,
            DIM)
    y += 80

    for s in shots:
        sh.text(f"{s.name}", 24, y + 10, 20)
        sh.text(f"{s.start:.2f}–{s.end:.2f}s", 24, y + 38, 14, DIM, font="mono")
        info = [s.purpose, f"入り: {s.enter}" if s.enter else "", f"出: {s.exit}" if s.exit else ""]
        for i, ln in enumerate([x for x in info if x]):
            sh.text(ln[:40], 24, y + 66 + i * 22, 13, DIM)
        x = 360
        for f in shot_frames[s.name]:
            sh.image(imgs[f], x, y, tw)
            sh.text(f"{f / fps:.2f}s", x + 6, y + th + 16, 12, DIM, font="mono")
            x += tw + 12
        y += row_h

    sw = int(tw * 0.55)
    for c, fs in cut_frames.items():
        sh.text(f"カット {c:.2f}s 前後", 24, y + 10, 16)
        x = 24
        for f, o in zip(fs, offs):
            hh = sh.image(imgs[f], x, y + 24, sw)
            sh.text(f"{o:+.2f}", x + 4, y + 24 + hh + 12, 11, WARN if o == 0 else DIM, font="mono")
            x += sw + 6
        y += cut_h

    # 音の波形とカット・キュー
    sh.text("音とタイミング", 24, y + 10, 18)
    gx, gw, gy, gh = 24, W - 48, y + 30, 120
    sh.c.drawRect(skia.Rect.MakeXYWH(gx, gy, gw, gh), skia.Paint(Color=skia.Color(28, 28, 34)))
    if wav:
        wf = _waveform(wav, gw)
        wf = wf / (wf.max() + 1e-9)
        p = skia.Paint(Color=skia.Color(120, 150, 210), AntiAlias=True)
        for i, v in enumerate(wf):
            sh.c.drawLine(gx + i, gy + gh / 2 - v * gh / 2, gx + i, gy + gh / 2 + v * gh / 2, p)
    tx = lambda t: gx + gw * t / comp.duration  # noqa: E731
    for t in shots.cuts:
        sh.c.drawLine(tx(t), gy - 6, tx(t), gy + gh + 6, skia.Paint(Color=skia.Color(255, 255, 255), StrokeWidth=2))
    for t in comp.cues:
        sh.c.drawLine(tx(t), gy, tx(t), gy + gh, skia.Paint(Color=skia.Color(255, 122, 69), StrokeWidth=2))
    for t in m.changes:
        sh.c.drawCircle(tx(t), gy + gh + 14, 3, skia.Paint(Color=skia.Color(74, 222, 128), AntiAlias=True))
    sh.text("白: カット  橙: キュー  緑の点: 画面の大きな変化", gx, gy + gh + 34, 12, DIM)
    y = gy + gh + 60

    sh.text("スマホ幅 (長辺 360px) での見え方", 24, y + 10, 18)
    x = 24
    for s in shots:
        img = phone[shot_frames[s.name][1]]
        sh.image(img, x, y + 30)
        x += img.shape[1] + 10
        if x > W - img.shape[1]:
            break
    pdir = Path(project).resolve()
    pdir = pdir if pdir.is_dir() else pdir.parent
    out = Path(out_dir) if out_dir else pdir / "reviews"
    stamp = f"{datetime.datetime.now():%Y%m%d-%H%M%S}"
    out.mkdir(parents=True, exist_ok=True)
    png = out / f"{stamp}.png"
    sh.save(png)

    lines = [f"# レビュー {stamp}", "", f"シート: {png.name}", "", "## 自動計測", "",
             f"- ペース: {pace} (画面の大きな変化 {len(m.changes)} 回)",
             f"- 静止の割合: {m.rest_ratio:.0%} (目安 40〜60%)",
             f"- 動きの起伏: {m.contrast:.3f} ({'平坦' if m.contrast < 0.15 else 'OK'}。0.15 未満は平坦)",
             f"- 1 フレームだけの閃き: {len(m.pops)} 箇所" + (f" ({', '.join(f'{t:.2f}s' for t in m.pops[:10])})" if m.pops else "")]
    off_grid = [(k, t, d) for k, t, d, _ in m.sync if abs(d) > 1]
    silent = [(k, t) for k, t, _, has in m.sync if not has]
    if m.sync:
        lines.append(f"- 拍のグリッド (8 分) から外れたカット・キュー: {len(m.sync)} 箇所中 {len(off_grid)} 箇所")
        lines += [f"  - {k} {t:.2f}s: グリッドから {d:+.0f}ms" for k, t, d in off_grid]
        lines.append(f"- 目立つ音の立ち上がりが無いカット・キュー: {len(silent)} 箇所")
        lines += [f"  - {k} {t:.2f}s" for k, t in silent]
    edge = [f for f, v in m.edge_ink.items() if v > 0.02]
    lines.append(f"- 画面の端 5% に要素がある: {len(edge)} コマ ({', '.join(f'{f / fps:.1f}s' for f in edge[:8])})"
                 if edge else "- 画面の端 5% に要素があるコマ: なし")
    if m.loop_diff is not None:
        lines.append(f"- ループ: 最初と最後のコマの差 {m.loop_diff:.1f} ({'OK' if m.loop_diff < 3 else '要修正'})")
    lines += ["", "## チェック", "",
              "- [ ] 最初の 2 秒に、見続ける理由になる絵がある",
              "- [ ] スマホ幅で文字が読める",
              "- [ ] 各ショットで、視線を向ける先が 1 つに決まっている",
              "- [ ] 書体と色がショット間で一貫している",
              "- [ ] カット前後の連続コマに、半端で汚いコマが無い",
              "- [ ] カット・キューと音のアタックが揃っている",
              "- [ ] 中央の大きな文字・グラデーション背景・全部フェードイン、の定番に頼っていない",
              "- [ ] 最後のコマがポスターとして成立する",
              "", "## 大きな欠点 (上位 3 つ)", "",
              "1. 時刻: / 根拠: / 局所的な修正:",
              "2. 時刻: / 根拠: / 局所的な修正:",
              "3. 時刻: / 根拠: / 局所的な修正:", ""]
    md = out / f"{stamp}.md"
    md.write_text("\n".join(lines), encoding="utf-8")
    print(f"-> {png}\n-> {md}")
    return png
