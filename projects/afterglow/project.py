"""afterglow。雨の夜のチルな lo-fi (80 BPM・D♭ メジャー・114 秒)。制作の判断は brief.md / style.md / shotlist.md にある。"""
import math
from functools import lru_cache
from pathlib import Path

import numpy as np
import pedalboard as pb

from motion import Composition, Palette, audio, draw, post, scene, sfxlib, text
from motion.noise import hash01
from motion.nodes import node
from motion.shots import ShotList
from motion.timeline import Timeline

HERE = Path(__file__).parent
pal = Palette(bg="#0E0F14", fg="#E9E4DA", accent="#E8A15A")
BPM = 80
tl = Timeline(bpm=BPM)
BARS = 38
DUR = BARS * tl.bar_len
SWING = 0.58
# 最後の和音は 5 拍で離し、尺の終わり (6 拍目の後) までに残響を消す
FINAL_BEATS = 5.0
# スラーで前後の音を重ねる長さ。長いと 2 つの音程が同時に鳴り、電子音のようににじむ (CLAP の「機械的な合成音」0.6 → 0.2)
SLUR_OVERLAP = 0.03
GRETSCH = audio.SAMPLES_DIR / "gretsch"
SAX = audio.SAMPLES_DIR / "sax"
RAIN = "ambience/own-ov-abdcb580"
AFTER_RAIN = "ambience/own-ov-1d398b2b"
REVERSE = "reverse/fs-148930-cymbal-hits-reversed-wav-1"

# 和音: (ベースの根音, エレピの声部)。声部は根音を省いた 7・9・3・5 の形で、次の和音へ半音か保留で動く
CHORDS = {
    "G♭△9": ("Gb1", ["F3", "Ab3", "Bb3", "Db4"]),
    "F7(♭9,♭13)": ("F1", ["Eb3", "A3", "Db4", "Gb4"]),
    "B♭m9": ("Bb1", ["Ab3", "C4", "Db4", "F4"]),
    "A♭m9": ("Ab1", ["Gb3", "Bb3", "B3", "Eb4"]),
    "D♭13(♭9)": ("Db2", ["F3", "Bb3", "B3", "D4"]),
    "A♭13": ("Ab1", ["Gb3", "Bb3", "C4", "F4"]),
    "Fm9": ("F1", ["Eb3", "G3", "Ab3", "C4"]),
    "E♭m9": ("Eb2", ["Db3", "F3", "Gb3", "Bb3"]),
    "A♭13sus": ("Ab1", ["Gb3", "Bb3", "Db4", "F4"]),
    "Fm7": ("F1", ["Eb3", "Ab3", "C4", "F4"]),
    "B♭7(♭9)": ("Bb1", ["Ab3", "B3", "D4", "F4"]),
    "A♭7sus": ("Ab1", ["Gb3", "Bb3", "Db4", "Eb4"]),
    "G♭△9(♯11)": ("Gb1", ["F3", "Ab3", "Bb3", "Db4", "C5"]),
}
ROMAN = {"G♭△9": "IV△7", "F7(♭9,♭13)": "III7", "B♭m9": "vim7", "A♭m9": "vm7", "D♭13(♭9)": "I7", "A♭13": "V7",
         "Fm9": "iiim7", "E♭m9": "iim7", "A♭13sus": "V7sus4", "Fm7": "iiim7", "B♭7(♭9)": "VI7", "A♭7sus": "V7sus4",
         "G♭△9(♯11)": "IV△7"}
# 丸サ進行 (IV△7–III7–vim7–vm7 I7) と王道進行 (IV–V–iii–vi)。1 小節を (拍, 和音) の並びで書く
MARU = [[(0, "G♭△9")], [(0, "F7(♭9,♭13)")], [(0, "B♭m9")], [(0, "A♭m9"), (2, "D♭13(♭9)")]]
OHDO = [[(0, "G♭△9")], [(0, "A♭13")], [(0, "Fm9")], [(0, "B♭m9")], [(0, "E♭m9")], [(0, "A♭13sus")],
        [(0, "Fm7"), (2, "B♭7(♭9)")], [(0, "E♭m9"), (2, "A♭7sus")]]
FORM = [("intro", MARU), ("a1", MARU * 2), ("b1", OHDO), ("brk", MARU), ("a2", MARU * 2), ("outro", MARU),
        ("outro", [[(0, "G♭△9(♯11)")], []])]
PROGRESSION = {"intro": "丸サ進行", "a1": "丸サ進行", "b1": "王道進行", "brk": "丸サ進行", "a2": "丸サ進行",
               "outro": "丸サ進行"}

T3 = 1 / 3
# メロディ: 小節 → [(拍, 長さ (拍), 音, 強さ, 記号)]。記号は s = 下からしゃくる、f = 終わりで落とす、v = ビブラートを深く、
# g = 半音下の装飾音。2 小節の問いと答えで息継ぎし、同じ音型は移して使う (b1 の 12 小節目の型を 14 小節目で 5 度上に)
SAX_LINE = {
    11: [(3.0, T3, "Ab2", 70, "s"), (3 + T3, T3, "Bb2", 74), (3 + 2 * T3, T3, "Db3", 78)],
    12: [(0.0, 1.5, "F3", 86, "s"), (1 + 2 * T3, T3, "Eb3", 70), (2.0, 0.5, "Db3", 76), (2.5, 1.0, "Bb2", 80, "f")],
    13: [(0.5, 0.5, "C3", 74), (1.0, 0.5, "Eb3", 80), (1.5, 1.0, "F3", 86), (2.5, 0.5, "Eb3", 74), (3.0, 0.75, "C3", 80)],
    14: [(0.0, 1.5, "C4", 90, "s"), (1 + 2 * T3, T3, "Bb3", 72), (2.0, 0.5, "Ab3", 80), (2.5, 1.0, "F3", 82, "f")],
    15: [(0.5, 0.25, "F3", 72), (0.75, 0.25, "Ab3", 76), (1.0, 0.5, "Bb3", 82), (1.5, 0.5, "Db4", 88),
         (2.0, 2.0, "C4", 92, "v")],
    16: [(0.0, T3, "Bb3", 78), (T3, T3, "Db4", 84), (2 * T3, T3, "Bb3", 76), (1.0, 1.0, "Gb3", 84), (2.0, 0.5, "F3", 76),
         (2.5, 0.5, "Eb3", 74), (3.0, 0.75, "Gb3", 80), (3.75, 0.25, "Ab3", 78)],
    17: [(0.0, 2.5, "Db4", 100, "sv"), (2.5, 0.25, "C4", 78), (2.75, 0.25, "Bb3", 76), (3.0, 1.0, "Ab3", 82)],
    18: [(0.0, 0.75, "C4", 84), (0.75, 0.25, "Bb3", 72), (1.0, 0.5, "Ab3", 78), (1.5, 0.5, "G3", 74),
         (2.0, 0.5, "D3", 80, "s"), (2.5, 0.5, "F3", 76), (3.0, 1.0, "Ab3", 82)],
    19: [(0.0, 1.5, "Gb3", 84), (1.5, 0.5, "Ab3", 76), (2.0, 1.0, "Bb3", 82), (3.0, 1.0, "Db4", 86, "f")],
    20: [(1.0, 2.5, "Bb2", 76, "s")],
    21: [(0.0, 0.5, "A2", 70), (0.5, 2.5, "Eb3", 80)],
    22: [(0.0, T3, "Db3", 72), (T3, T3, "F3", 78), (2 * T3, T3, "Ab3", 82), (1.0, 2.0, "C4", 90, "s")],
    23: [(0.0, 1.0, "B3", 84), (1.0, 0.5, "Bb3", 76), (1.5, 0.5, "Gb3", 72), (2.0, 1.0, "F3", 80, "f")],
    24: [(0.5, 0.5, "Db3", 78), (1.0, 0.5, "F3", 84), (1.5, 0.5, "Ab3", 86), (2.0, 1.25, "Bb3", 92, "v"),
         (3.5, 0.5, "Ab3", 76)],
    25: [(0.0, 0.75, "A3", 90, "s"), (0.75, 0.25, "Gb3", 72), (1.0, 1.0, "F3", 82), (2.5, 0.25, "Ab3", 74),
         (2.75, 1.25, "A3", 84)],
    26: [(0.5, 0.5, "F3", 80), (1.0, 0.5, "Ab3", 84, "g"), (1.5, 0.5, "C4", 90), (2.0, 1.0, "Bb3", 86),
         (3.0, 0.5, "Db4", 84), (3.5, 0.5, "C4", 78)],
    27: [(0.0, 1.0, "Gb3", 82, "s"), (1.0, 0.5, "B2", 76), (1.5, 0.5, "Eb3", 78), (2.0, 1.75, "F3", 84, "f")],
    28: [(0.0, 0.5, "Db4", 92, "s"), (0.5, 0.5, "C4", 84), (1.0, 0.5, "Bb3", 82), (1.5, 0.5, "Ab3", 78),
         (2.0, T3, "Ab3", 76), (2 + T3, T3, "Bb3", 80), (2 + 2 * T3, T3, "C4", 84), (3.0, 1.0, "Db4", 90)],
    29: [(0.5, 0.5, "Eb3", 80), (1.0, 0.5, "Gb3", 84), (1.5, 2.0, "A3", 92, "sv")],
    30: [(0.0, 1.0, "Db4", 96, "v"), (1.0, T3, "C4", 84), (1 + T3, T3, "Db4", 86), (1 + 2 * T3, T3, "C4", 80),
         (2.0, 0.5, "Ab3", 80, "g"), (2.5, 1.0, "Bb3", 84)],
    31: [(0.0, T3, "Eb3", 74), (T3, T3, "Gb3", 78), (2 * T3, T3, "Bb3", 82), (1.0, 1.0, "B3", 88, "v"),
         (2.0, 0.5, "Bb3", 80), (2.5, 0.5, "Ab3", 76), (3.0, 1.0, "Ab3", 80, "f")],
    32: [(1.0, 1.5, "F3", 78, "s"), (2 + 2 * T3, T3, "Eb3", 66), (3.0, 1.0, "Db3", 72)],
    33: [(0.5, 2.5, "A2", 72, "s")],
    34: [(1.0, 0.5, "Db3", 70), (1.5, 2.0, "F3", 74)],
    35: [(0.0, 1.5, "Gb3", 72), (2.0, 2 * T3, "Ab3", 70), (2 + 2 * T3, T3, "Bb3", 66)],
    36: [(0.0, 4.0, "F3", 70, "s")],
}
# a1 はサックスが入る前なので、エレピの上の音で短く答える
KEYS_LINE = {
    4: [(2.5, 0.25, "Db5", 70), (2.75, 0.25, "C5", 64), (3.0, 0.9, "Bb4", 72)],
    7: [(3.0, 0.25, "Bb4", 70), (3.25, 0.25, "Ab4", 64), (3.5, 0.5, "F4", 68)],
    8: [(2.5, 0.25, "Db5", 72), (2.75, 0.25, "C5", 66), (3.0, 0.5, "Bb4", 72), (3.5, 0.5, "Ab4", 64)],
}
# 実測の音程 (pyin、Hz)。サンプルは A440 より 11〜41 セント高いので、再生速度で合わせる
SAX_F0 = {"006_notes121c2": 65.81, "008_notes121csharp2": 70.13, "012_notes121eflat": 78.26,
          "010_notes121e": 82.91, "014_notes121f": 87.85, "016_notes121fsharp": 93.07, "018_notes121g": 98.60,
          "020_notes121gsharp": 104.47, "000_notes121a": 110.04, "003_notes121bflat": 117.26,
          "002_notes121b": 124.23, "005_notes121c": 131.62, "007_notes121csharp": 140.25, "009_notes121d": 147.74,
          "013_notes121eflat2": 158.34, "011_notes121e2": 166.79, "015_notes121f2": 178.76,
          "017_notes121fsharp2": 187.22, "019_notes121g2": 198.35, "021_notes121gsharp2": 210.14,
          "001_notes121a2": 221.36, "004_notes121bflat2": 235.88}


def section_bars() -> list[tuple[str, int, list]]:
    """(区間, 小節番号, その小節の和音の並び) を曲の頭から。"""
    out, b = [], 0
    for name, bars in FORM:
        for chords in bars:
            out.append((name, b, chords))
            b += 1
    return out


def chord_at(bar: int, beat: float) -> str:
    chords = section_bars()[min(bar, BARS - 1)][2]
    if not chords:
        return chord_at(bar - 1, 3.99)
    return [c for b, c in chords if b <= beat + 1e-6][-1]


def at(bar: float, beat: float = 0.0) -> float:
    """小節と拍から秒。8 分の中の 16 分の裏を SWING の位置へずらす。3 連符など 16 分の格子に無い位置はそのまま。"""
    if abs(beat * 4 - round(beat * 4)) > 1e-6:
        return tl.bar(bar) + beat * tl.beat_len
    e = math.floor(beat * 2 + 1e-9)
    u = beat * 2 - e
    u = u * 2 * SWING if u < 0.5 else SWING + (u - 0.5) * 2 * (1 - SWING)
    return tl.bar(bar) + (e + u) / 2 * tl.beat_len


def jit(*key: float, ms: float = 6.0) -> float:
    """手で弾いた揺れ。同じ音は何度書き出しても同じだけずれる。"""
    return (hash01(*key) - 0.5) * 2 * ms / 1000


def chord_name(c, s: str, x: float, y: float, size: float, color) -> None:
    """和音の名前。♭・♯・△ は sans に無く jp では全角の字幅になるので、インクの幅で詰めて並べる。"""
    axes = {"wght": 300}
    pen, run = x, ""
    for ch in s + "\0":
        if ch not in "♭♯△\0":
            run += ch
            continue
        if run:
            pen += text.text(c, run, pen, y, size=size, axes=axes, color=color).width
            run = ""
        if ch == "\0":
            break
        k = 0.62 if ch == "△" else 0.8
        sh = text.shape(ch, "jp", size * k, axes)
        r = sh.skfont.getBounds(sh.glyphs)[0]
        gap = size * 0.03
        text.text(c, ch, pen + gap - r.left(), y, font="jp", size=size * k, axes=axes, color=color)
        pen += r.width() + gap * 2


def build(aspect: str = "16:9") -> Composition:
    shots = ShotList.from_md(HERE / "shotlist.md")
    W, H = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080)}[aspect]
    comp = Composition(width=W, height=H, duration=DUR, fps=30, bpm=BPM, background=pal.bg, shots=shots,
                       motion_blur=0)
    m = W * 0.08

    @scene(0, DUR)
    def board(c, ctx):
        bar = min(int(ctx.t // tl.bar_len), BARS - 1)
        beat = (ctx.t % tl.bar_len) / tl.beat_len
        sec = section_bars()[bar][0]
        name = chord_at(bar, beat)
        with node(c, ctx, "section", origin=(m, H * 0.16), label="区間と進行", span=(0, DUR)) as n:
            text.text(n.c, f"{sec}  ·  {PROGRESSION[sec]}", m, H * 0.16, font="mono", size=W * 0.016,
                      color=n.prop("color", pal.fg), alpha=0.55)
        with node(c, ctx, "chord", origin=(m, H * 0.56), label="今の和音", span=(0, DUR)) as n:
            chord_name(n.c, name, m, H * 0.56, W * 0.085, n.prop("color", pal.fg))
            text.text(n.c, ROMAN[name], m, H * 0.56 + W * 0.055, font="mono", size=W * 0.03,
                      color=n.prop("accent", pal.accent))
        with node(c, ctx, "title", origin=(W - m, H * 0.16), label="題", span=(0, DUR)) as n:
            text.text(n.c, n.prop("text", "afterglow"), W - m, H * 0.16, font="mono", size=W * 0.016,
                      color=pal.fg, align="right", alpha=0.55)
        with node(c, ctx, "beats", origin=(m, H * 0.84), label="拍", span=(0, DUR)) as n:
            for k in range(4):
                on = k <= beat < k + 1
                draw.circle(n.c, m + W * 0.005 + k * W * 0.03, H * 0.84, W * 0.005,
                            color=pal.accent if on else pal.fg, alpha=1.0 if on else 0.3)

    comp.add(board)
    comp.post = [post.vignette(0.3), post.grain(0.015)]
    comp.audio = make_audio
    return comp


def drums(mx: audio.Mix) -> list[float]:
    """Gretsch の生ドラム。キックの時刻を返す (他の楽器を軽く沈める)。"""
    kicks = []

    def hit(name, bar, beat, gain, pan=0.0, late=0.0, seed=0.0):
        t = at(bar, beat) + late + jit(bar, beat, seed, ms=5)
        mx.hit(str(GRETSCH / f"{name}.wav"), t, gain_db=gain + (hash01(bar, beat, seed, 9) - 0.5) * 3, pan=pan)
        return t

    for sec, bar, _ in section_bars():
        if sec in ("a1", "b1", "a2"):
            first = bar in (4, 24)
            for s in [0, 10] + ([7] if bar % 2 else []) + ([15] if bar % 4 == 2 else []):
                kicks.append(hit("013_kick", bar, s / 4, -2 if s in (0, 10) else -7, seed=1))
            for s in (4, 12):
                hit("023_snareslack" if sec == "b1" else "020_snare", bar, s / 4, -4, pan=0.05, late=0.018,
                    seed=2)
            for s in (7, 9, 15):
                if hash01(bar, s, 3) > 0.6:
                    hit("021_snareghost", bar, s / 4, -15, pan=0.05, late=0.01, seed=3)
            for s in range(0, 16, 2):
                hit("004_closedhat", bar, s / 4, -12 if s % 4 == 0 else -16, pan=-0.25, seed=4)
            for s in (11, 15):
                if hash01(bar, s, 5) > 0.55 and not (bar % 4 == 3 and s == 15):
                    hit("004_closedhat", bar, s / 4, -20, pan=-0.25, seed=5)
            if bar % 4 == 3:
                hit("016_openclosedhat", bar, 3.5, -15, pan=-0.25, seed=6)
            if first or bar == 12:
                hit("019_ridecymbal", bar, 0, -16, pan=0.3, seed=7)
        elif sec == "brk":
            for s in range(0, 16, 2):
                hit("004_closedhat", bar, s / 4, -17 if s % 4 == 0 else -21, pan=-0.25, seed=8)
            if bar % 2:
                hit("010_foothat", bar, 1, -18, pan=-0.2, seed=9)
    # 区間の変わり目のフィル (ブラシのタム)
    for bar in (11, 23):
        hit("000_brushhitom", bar, 3.5, -9, pan=-0.2, seed=10)
        hit("001_brushlotom", bar, 3.75, -8, pan=0.2, seed=11)
    hit("019_ridecymbal", 32, 0, -15, pan=0.3, seed=12)
    return kicks


def bass(mx: audio.Mix) -> None:
    notes = []
    bars = section_bars()
    for sec, bar, chords in bars:
        if sec == "intro" or not chords:
            continue
        nxt = bars[bar + 1][2] if bar + 1 < BARS and bars[bar + 1][2] else chords
        r_next = audio.midi(CHORDS[nxt[0][1]][0])
        roots = [(b, audio.midi(CHORDS[c][0])) for b, c in chords]
        late = 0.006
        if sec in ("brk", "outro"):
            for k, (b, r) in enumerate(roots):
                end = roots[k + 1][0] if k + 1 < len(roots) else (FINAL_BEATS if bar >= 36 else 4)
                notes.append((at(bar, b) + late, (end - b) * tl.beat_len * 0.95, r, 84))
            continue
        r0 = roots[0][1]
        notes.append((at(bar, 0) + late + jit(bar, 1), 1.6 * tl.beat_len, r0, 104))
        if len(roots) == 1:
            notes.append((at(bar, 2.5) + late + jit(bar, 2), 0.8 * tl.beat_len, r0 + (7 if bar % 2 else 0), 84))
        else:
            notes.append((at(bar, 2) + late + jit(bar, 3), 1.4 * tl.beat_len, roots[1][1], 96))
        if sec != "a1" and hash01(bar, 4) > 0.5:
            notes.append((at(bar, 1.75) + late, 0.2 * tl.beat_len, r0 + 12, 70))
        last = roots[-1][1]
        if r_next != last:
            approach = r_next - 1 if r_next > last else r_next + 1
            notes.append((at(bar, 3.5) + late + jit(bar, 5), 0.42 * tl.beat_len, approach, 78))
    mx.instrument(notes, patch="Basses/E-Bass", bus="bass", gain_db=5.5)


def keys(mx: audio.Mix) -> None:
    """エレピの和音。低い音から 9ms ずつずらして弾き、上の声部を少し強く。イントロと終わりは別のバスでこもらせる。"""
    strikes = []
    for sec, bar, chords in section_bars():
        if not chords:
            continue
        far = sec == "intro" or (sec == "outro" and bar >= 34)
        if len(chords) == 1:
            if bar >= 36:
                pat = [(0.0, FINAL_BEATS, 0.9)]
            else:
                pat = [[(0.0, 2.25, 1.0), (2.5, 1.4, 0.72)], [(0.0, 3.9, 1.0)],
                       [(0.0, 1.4, 1.0), (1.75, 0.6, 0.62), (2.5, 1.4, 0.8)]][int(hash01(bar, 21) * 3)]
            pat = [(b, d, v, chords[0][1]) for b, d, v in pat]
        else:
            pat = [(0.0, 1.8, 1.0, chords[0][1]), (2.0 if bar % 2 else 1.75, 2.0, 0.92, chords[1][1])]
        for b, d, v, ch in pat:
            strikes.append(dict(t=at(bar, b) + jit(bar, b, 22, ms=8), d=d * tl.beat_len, v=v, ch=ch, far=far))
    strikes.sort(key=lambda s: s["t"])
    for s, nx in zip(strikes, strikes[1:] + [None]):
        if nx is not None:
            s["d"] = min(s["d"], nx["t"] - s["t"] - 0.03)
    near, far = [], []
    for s in strikes:
        voicing = CHORDS[s["ch"]][1]
        for i, n in enumerate(voicing):
            vel = int((62 + (8 if i == len(voicing) - 1 else 0) - (3 if 0 < i < len(voicing) - 1 else 0)) * s["v"]
                      + (hash01(s["t"], i, 23) - 0.5) * 8)
            (far if s["far"] else near).append((s["t"] + i * 0.009, s["d"], n, max(30, vel)))
    for bar, line in KEYS_LINE.items():
        for b, d, n, v in line:
            near.append((at(bar, b) + jit(bar, b, 24), d * tl.beat_len * 0.9, n, v))
    mx.instrument(near, patch="Vospi/Keys/EP Middle", bus="keys", gain_db=-15.5)
    mx.instrument(far, patch="Vospi/Keys/EP Middle", bus="keys_far", gain_db=-13.5)


def pad(mx: audio.Mix) -> None:
    notes = []
    for sec, bar, chords in section_bars():
        if sec not in ("b1", "brk", "a2", "outro") or not chords:
            continue
        for k, (b, c) in enumerate(chords):
            end = chords[k + 1][0] if k + 1 < len(chords) else (FINAL_BEATS if bar >= 36 else 4)
            for n in CHORDS[c][1][:4]:
                notes.append((at(bar, b), (end - b) * tl.beat_len, audio.midi(n) + 12, 60))
    mx.instrument(notes, patch="Pads/MKS-70 Warm Pad", bus="pad", gain_db=-13.5)


@lru_cache(maxsize=32)
def sax_source(name: str) -> np.ndarray:
    """サックスの実音。吹き始めまでの無音 (最大 42ms) を詰める。"""
    src = audio.load(SAX / f"{name}.wav")
    env = np.abs(src).max(axis=0)
    return src[:, max(0, int(np.argmax(env > env.max() * 0.03)) - int(0.005 * audio.SR)):]


def sax_events() -> list[dict]:
    """SAX_LINE を時刻の順の音にし、フレーズの頭と終わり、前の音からのスラーを決める。"""
    ev = [dict(bar=bar, beat=b, beats=d, midi=audio.midi(n), vel=v, marks=mk[0] if mk else "",
               t=at(bar, b), pos=bar * 4 + b)
          for bar, line in sorted(SAX_LINE.items()) for b, d, n, v, *mk in line]
    for i, e in enumerate(ev):
        prev = ev[i - 1] if i else None
        gap = e["pos"] - (prev["pos"] + prev["beats"]) if prev else 99.0
        e["head"] = gap > 0.3
        # 短い音の並びは息を切らずに指で変える (つながった音のおよそ 3/4)。大きく跳ぶ音は吹き直す
        e["slur"] = (not e["head"] and abs(e["midi"] - prev["midi"]) <= 5
                     and min(e["beats"], prev["beats"]) <= 0.5 and hash01(e["pos"], 41) > 0.25)
        e["from"] = prev["midi"] if e["slur"] else None
    for e, nx in zip(ev, ev[1:] + [None]):
        e["tail"] = nx is None or nx["head"]
        # つながる音は次の音と重ねすぎない (2 つの音程が同時に鳴ると電子音のようににじむ)。フレーズの終わりだけ長く消える
        if nx is not None and nx["slur"]:
            e["dur"], e["rel"] = nx["t"] - e["t"], SLUR_OVERLAP
        elif nx is not None and not nx["head"]:
            e["dur"], e["rel"] = (nx["t"] - e["t"]) * 0.94, 0.03
        else:
            e["dur"], e["rel"] = e["beats"] * tl.beat_len * 0.94, 0.15
    return ev


def sax_note(midi: int, vel: int, dur: float, marks: str = "", slur_from: int | None = None,
             seed: float = 0.0, rel: float = 0.1) -> np.ndarray:
    """1 音を吹く。録音の実音は音程も音量もまっすぐなので、音程 (セント) と音量を時間で動かして読む。"""
    from scipy import signal
    sr = audio.SR
    target = audio.hz(midi)
    name, f0 = min(SAX_F0.items(), key=lambda kv: abs(math.log2(target / kv[1])))
    src = sax_source(name)
    n = int((dur + rel) * sr)
    t = np.arange(n) / sr
    cents = np.full(n, (hash01(seed, 1) - 0.5) * 8)
    if slur_from is not None:
        cents += (slur_from - midi) * 100 * np.exp(-t / 0.006)
    elif "s" in marks:
        g = 0.08 + hash01(seed, 2) * 0.06
        cents -= (70 + hash01(seed, 3) * 50) * np.clip(1 - t / g, 0, 1) ** 2
    if "g" in marks:
        cents += np.where(t < 0.05, -100.0, -100.0 * np.exp(-(t - 0.05) / 0.012))
    if dur > 0.55:
        # ビブラートは音を伸ばしてから遅れて深くなり、速さと深さも揺らぐ (一定の深い正弦波はゲーム機の音に聞こえる)
        on = min(0.3, dur * 0.35)
        depth = np.clip(6 + (vel - 70) * 0.3, 5, 14) * (1.4 if "v" in marks else 1.0)
        hz_ = (4.8 + hash01(seed, 4) * 0.9) * (1 + 0.08 * np.sin(2 * np.pi * 0.7 * t + seed))
        wob = 1 + 0.35 * np.sin(2 * np.pi * 0.45 * t + seed * 1.7)
        vib = wob * np.clip((t - on) / 0.45, 0, 1) * np.sin(2 * np.pi * np.cumsum(hz_ * (t >= on)) / sr)
        cents += depth * vib
    else:
        vib = np.zeros(n)
    fall = np.clip((t - (dur - 0.22)) / 0.22, 0, 1) if "f" in marks else np.zeros(n)
    cents -= 300 * fall ** 1.6
    rate = target / f0 * 2 ** (cents / 1200)
    pos = (int(0.035 * sr) if slur_from is not None else 0) + np.concatenate([[0.0], np.cumsum(rate[:-1])])
    n = int(np.searchsorted(pos, src.shape[1] - 2))
    t, pos = t[:n], pos[:n]
    idx = np.arange(src.shape[1])
    y = np.vstack([np.interp(pos, idx, ch) for ch in src])
    # 長い音は膨らんでから少し引き、短い音は頭を少し強く吹く
    if dur > 0.6:
        u = np.clip(t / dur, 0, 1)
        env = 10 ** ((-2.5 + 3.5 * np.sin(np.pi * u) ** 0.7 - u) / 20)
    else:
        env = 1 + 0.25 * np.exp(-t / 0.06)
    env *= np.clip(t / (SLUR_OVERLAP if slur_from is not None else 0.004), 0, 1)
    env *= (1 - fall[:n]) ** 0.7
    env *= np.where(t > dur, np.cos(np.clip((t - dur) / rel, 0, 1) * np.pi / 2), 1.0)
    env *= 10 ** (0.8 * vib[:n] / 20)
    # 弱く吹いた音ほど暗い (倍音が減る)。強弱 60 で 3.2kHz、80 で 6.8kHz
    fc = min(3200 * 2 ** ((vel - 60) / 18), sr * 0.45)
    y = signal.lfilter(*signal.butter(1, fc, fs=sr), y, axis=1)
    return (y * env).astype(np.float32)


def sax(mx: audio.Mix) -> None:
    """録音のサックスを 1 音ずつ吹かせて置く。フレーズの頭は少し遅れて入り、音ごとにも揺れる。"""
    for e in sax_events():
        late = 0.012 + (hash01(e["bar"], 43) * 0.02 if e["head"] else 0.0) + jit(e["pos"], 31, ms=7)
        buf = sax_note(e["midi"], e["vel"], e["dur"], e["marks"], e["from"], seed=e["pos"], rel=e["rel"])
        mx.place(buf, e["t"] + late, gain_db=-1.5 + (e["vel"] - 90) / 5, pan=0.08, bus="sax")


def make_audio(comp: Composition) -> str:
    mx = audio.Mix(DUR, tail=3.0)
    kicks = drums(mx)
    bass(mx)
    keys(mx)
    pad(mx)
    sax(mx)
    mx.ambience(RAIN, start=0.0, end=14.0, level_db=-30, fade=1.5)
    mx.ambience(RAIN, start=12.0, end=98.0, level_db=-38, fade=2.0)
    mx.ambience(AFTER_RAIN, start=95.0, end=DUR, level_db=-34, fade=3.0)
    for t in (tl.bar(4), tl.bar(24)):
        mx.sfx(sfxlib.sound(REVERSE), t, None)
    wow = pb.Chorus(rate_hz=0.5, depth=0.12, centre_delay_ms=5.0, feedback=0.0, mix=1.0)
    mx.fx("keys", wow, pb.Distortion(drive_db=4), pb.LowpassFilter(cutoff_frequency_hz=5500),
          pb.Reverb(room_size=0.55, damping=0.6, wet_level=0.18, dry_level=1.0, width=1.0))
    mx.fx("keys_far", pb.Chorus(rate_hz=0.5, depth=0.12, centre_delay_ms=5.0, feedback=0.0, mix=1.0),
          pb.LowpassFilter(cutoff_frequency_hz=700),
          pb.Reverb(room_size=0.7, damping=0.5, wet_level=0.3, dry_level=1.0, width=1.0))
    mx.fx("bass", pb.HighpassFilter(cutoff_frequency_hz=32), pb.Distortion(drive_db=3),
          pb.LowpassFilter(cutoff_frequency_hz=1400),
          pb.Compressor(threshold_db=-22, ratio=3, attack_ms=15, release_ms=150))
    mx.fx("drums", pb.HighpassFilter(cutoff_frequency_hz=30), pb.Resample(target_sample_rate=24000),
          pb.Distortion(drive_db=2), pb.LowpassFilter(cutoff_frequency_hz=9000),
          pb.Compressor(threshold_db=-18, ratio=3, attack_ms=10, release_ms=120),
          pb.Reverb(room_size=0.25, damping=0.7, wet_level=0.08, dry_level=1.0))
    mx.fx("pad", pb.HighpassFilter(cutoff_frequency_hz=220), pb.LowpassFilter(cutoff_frequency_hz=3500),
          pb.Reverb(room_size=0.8, damping=0.5, wet_level=0.35, dry_level=0.8, width=1.0))
    mx.fx("sax", pb.HighpassFilter(cutoff_frequency_hz=100),
          pb.PeakFilter(cutoff_frequency_hz=300, gain_db=-2.5, q=0.8), pb.LowpassFilter(cutoff_frequency_hz=6000),
          pb.Compressor(threshold_db=-20, ratio=2.5, attack_ms=12, release_ms=160),
          pb.Delay(delay_seconds=tl.beat_len * 0.75, feedback=0.25, mix=0.12),
          pb.Reverb(room_size=0.75, damping=0.6, wet_level=0.22, dry_level=1.0, width=1.0))
    mx.duck("keys", kicks, -2.5, 0.25)
    mx.duck("pad", kicks, -4.0, 0.3)
    mx.duck("bass", kicks, -2.0, 0.15)
    master = [pb.LowShelfFilter(cutoff_frequency_hz=90, gain_db=1.0),
              pb.HighShelfFilter(cutoff_frequency_hz=10000, gain_db=-2.5),
              pb.Compressor(threshold_db=-16, ratio=1.8, attack_ms=25, release_ms=250)]
    return mx.render(f"{comp.build_dir}/audio.wav", lufs=-14, master=master)
