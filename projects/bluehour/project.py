"""bluehour。夜明け前の青い時間の、電子音のチル (90 BPM・F リディアン・117 秒)。制作の判断は brief.md / style.md / shotlist.md にある。"""
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pedalboard as pb
import skia

from motion import Composition, Palette, audio, draw, overlay, post, scene, text
from motion.color import to_color
from motion.noise import hash01
from motion.nodes import node
from motion.shots import ShotList
from motion.timeline import Timeline

HERE = Path(__file__).parent
pal = Palette(bg="#070A14", fg="#E6EAF2", accent="#FFC58F")
DIM = "#7C8AAE"
BPM = 90
tl = Timeline(bpm=BPM)
BARS = 44
DUR = BARS * tl.bar_len
# 16 分の裏だけ少し後ろへ (ハットとシェイカーが揺れる程度。強く跳ねるとジャズやヒップホップに寄る)
SWING = 0.55
# 盛り上がりを作らない: 冒頭の a の雰囲気を最後まで保ち、途中の b だけキックを抜いて和音の色を少し変える
SECTIONS = [("intro", 0), ("a", 8), ("b", 24), ("a2", 32), ("outro", 40)]
HARMONY = {"intro": ["Fmaj9", "G/F"], "a": ["Fmaj9", "G/F"], "b": ["Dm9", "Bbmaj9"], "a2": ["Fmaj9", "G/F"],
           "outro": ["Fmaj9", "G/F", "Fmaj9"]}

PAD = "Pads/Verb Pad"
ARP = "Plucks/Sinus Verby Pops"
BASS = "Basses/Smoothie"
CRICKETS = "ambience/own-ov-3f1df54f"
BIRDS = "ambience/own-ov-9c53f3f3"

KICK = "808bd:3 ~ ~ 808bd:3 ~ ~ <~ ~ ~ 808bd:3> ~"
VAMP_PAD = "<[a3,c4,e4,g4] [g3,b3,d4,a4]>/2"
VAMP_ARP = "<[a4 c5 e5 g5]*2!2 [b4 d5 g5 a5]*2!2>"
VAMP_BASS = "f1@3 f1@3 f1@2"


@dataclass
class Part:
    """画面の 1 行と、曲の中でそれを鳴らす小節の範囲。row が同じパートは同じ行に入れ替わりで出る。"""
    row: str
    pat: str
    bars: tuple[int, int]
    gain: float = 0.0
    bus: str = "drums"
    pan: float = 0.0
    patch: str | None = None
    legato: float = 1.0
    velocity: int = 100
    octave: int = 3


ROWS = ["kick", "rim", "hat", "shaker", "bass", "pad", "arp"]
PARTS = [
    # ドラム: キックは 1 拍目と 2 拍目の裏、4 小節に 1 度だけ 4 拍目の裏にも。b ではキックだけ休む
    Part("kick", KICK, (8, 24), -0.5, bus="kick"),
    Part("kick", KICK, (32, 40), -0.5, bus="kick"),
    Part("rim", "~ 808:5 ~ 808:5", (8, 40), -6, pan=0.1),
    Part("hat", "[~ 808:1]*4", (8, 40), -10, pan=-0.2),
    Part("shaker", "drumtraks:0*8", (8, 40), -20, pan=0.25),
    # サブベース: 3+3+2 の 8 分。a は F の保続音
    Part("bass", VAMP_BASS, (8, 24), bus="bass", gain=-1, patch=BASS, legato=0.9, velocity=100),
    # b はキックで沈まない分と、F1 より高い D2 の分だけ大きく聞こえるので、パッドとベースを下げて a より少し静かに
    Part("bass", "<[d2@3 d2@3 d2@2]!2 [bb1@3 bb1@3 bb1@2]!2>", (24, 32), bus="bass", gain=-3.5, patch=BASS, legato=0.9,
         velocity=96),
    Part("bass", VAMP_BASS, (32, 40), bus="bass", gain=-1, patch=BASS, legato=0.9, velocity=100),
    Part("bass", "f1", (40, 42), bus="bass", gain=-1, patch=BASS, legato=0.98, velocity=80),
    Part("bass", "f1/2", (42, 44), bus="bass", gain=-1, patch=BASS, legato=0.95, velocity=80),
    # 和音
    Part("pad", VAMP_PAD, (0, 24), bus="pad", gain=-5, patch=PAD, legato=0.99, velocity=70),
    Part("pad", "<[f3,a3,c4,e4] [f3,a3,c4,d4]>/2", (24, 32), bus="pad", gain=-7, patch=PAD, legato=0.99, velocity=70),
    Part("pad", VAMP_PAD, (32, 40), bus="pad", gain=-5, patch=PAD, legato=0.99, velocity=70),
    Part("pad", "<[a3,c4,e4,g4] [g3,b3,d4,a4]>", (40, 42), bus="pad", gain=-5, patch=PAD, legato=0.99, velocity=70),
    # 最後の和音は 2 小節伸ばし、マスターのフェードで明け方へ消す
    Part("pad", "[a3,c4,e4,g4,c5]/2", (42, 44), bus="pad", gain=-5, patch=PAD, legato=0.95, velocity=70),
    Part("arp", VAMP_ARP, (4, 24), bus="arp", gain=-3.5, patch=ARP, legato=0.6, velocity=84),
    Part("arp", "<[a4 c5 e5 f5]*2!2 [a4 c5 d5 f5]*2!2>", (24, 32), bus="arp", gain=-3.5, patch=ARP, legato=0.6,
         velocity=84),
    Part("arp", VAMP_ARP, (32, 42), bus="arp", gain=-3.5, patch=ARP, legato=0.6, velocity=84),
]


def section_at(t: float) -> tuple[str, int]:
    bar = int(t // tl.bar_len)
    name, start = [s for s in SECTIONS if s[1] <= bar][-1]
    return name, start


def events(p: Part) -> list[dict]:
    return audio.pattern_events(p.pat, tl, tl.bar(p.bars[0]), tl.bar(p.bars[1]), SWING)


def build(aspect: str = "16:9") -> Composition:
    shots = ShotList.from_md(HERE / "shotlist.md")
    W, H = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080)}[aspect]
    comp = Composition(width=W, height=H, duration=DUR, fps=30, bpm=BPM, background=pal.bg, shots=shots,
                       motion_blur=0)
    m = W * 0.06
    played = {id(p): events(p) for p in PARTS}

    @scene(0, DUR)
    def board(c, ctx):
        with node(c, ctx, "sky", origin=(W / 2, H / 2), label="空", span=(0, DUR)) as n:
            sky(n.c, n.t, W, H)
        with node(c, ctx, "code", origin=(m, H * 0.35), label="パターンのコード", span=(0, DUR)) as n:
            code(n.c, ctx, n.t, played, m, H * 0.35, W * 0.0135, n.prop("accent", pal.accent))
        with node(c, ctx, "section", origin=(m, H * 0.13), label="区間と和音", span=(0, DUR)) as n:
            harmony(n.c, n.t, m, H * 0.13, W * 0.016, n.prop("accent", pal.accent))
        with node(c, ctx, "title", origin=(W - m, H * 0.13), label="題", span=(0, DUR)) as n:
            text.text(n.c, n.prop("text", "bluehour"), W - m, H * 0.13, font="mono", size=W * 0.016,
                      color=pal.fg, align="right", alpha=0.7)
            text.text(n.c, f"{BPM} bpm  ·  F lydian", W - m, H * 0.13 + W * 0.024, font="mono", size=W * 0.013,
                      color=DIM, align="right")
        with node(c, ctx, "progress", origin=(m, H * 0.88), label="曲の中の位置", span=(0, DUR)) as n:
            progress(n.c, n.t, m, H * 0.88, W - 2 * m, W * 0.013, n.prop("accent", pal.accent))

    comp.add(board)
    comp.post = [post.vignette(0.25), post.grain(0.012)]
    comp.audio = make_audio
    return comp


# 空の色: 夜 → 青い時間 → 地平線だけ明け方の色。(時刻, 上, 地平線)
SKY = [(0.0, "#05070F", "#0B1226"), (40.0, "#070C1C", "#142046"), (85.0, "#0C1630", "#26365F"),
       (DUR, "#13214A", "#6E5A6E")]


def sky(c, t: float, W: float, H: float) -> None:
    k = max(i for i, s in enumerate(SKY) if s[0] <= t) if t < DUR else len(SKY) - 2
    (t0, top0, hz0), (t1, top1, hz1) = SKY[k], SKY[min(k + 1, len(SKY) - 1)]
    u = 0.0 if t1 == t0 else min(max((t - t0) / (t1 - t0), 0.0), 1.0)
    u = u * u * (3 - 2 * u)
    top, hz = to_color(top0).mix(top1, u), to_color(hz0).mix(hz1, u)
    paint = skia.Paint(Shader=skia.GradientShader.MakeLinear(
        [skia.Point(0, 0), skia.Point(0, H)], [top.skia(), hz.skia()]))
    c.drawRect(skia.Rect.MakeWH(W, H), paint)
    # 星は明け方に近づくほど消える。瞬きは星ごとの位相で
    fade = min(max(1 - (t - 50) / 50, 0.0), 1.0)
    if fade <= 0:
        return
    for i in range(70):
        x, y = hash01(i, 1) * W, hash01(i, 2) ** 1.6 * H * 0.62
        # コードの行の上には置かない (記号の点と見分けがつかない)
        if x < W * 0.78 and H * 0.29 < y < H * 0.72:
            continue
        tw = 0.55 + 0.45 * np.sin(t * (0.6 + hash01(i, 3) * 1.4) + hash01(i, 4) * 6.28)
        draw.circle(c, x, y, 0.8 + hash01(i, 5) * 1.3, color=pal.fg, alpha=fade * tw * (0.25 + 0.5 * hash01(i, 6)))


def code(c, ctx, t: float, played: dict, x: float, y: float, size: float, accent: str) -> None:
    """パートごとの行。鳴っている間は明るく、鳴っていない行は前後の区間のパターンを薄く残す。"""
    lead = size * 1.75
    label_w = size * 0.6 * 8
    for r, row in enumerate(ROWS):
        yy = y + (r + (1 if r >= ROWS.index("bass") else 0)) * lead
        parts = [p for p in PARTS if p.row == row]
        bar = t / tl.bar_len
        now = [p for p in parts if p.bars[0] <= bar < p.bars[1]]
        if now:
            p = now[0]
            on = min((bar - p.bars[0]) * tl.bar_len / 0.35, 1.0)
            off = min((p.bars[1] - bar) * tl.bar_len / 0.35, 1.0)
            k = 0.3 + 0.7 * min(on, off)
        else:
            later = [p for p in parts if p.bars[0] > bar]
            p = later[0] if later else max(parts, key=lambda q: q.bars[1])
            k = 0.3
        text.text(c, row, x, yy, font="mono", size=size, color=DIM if not now else pal.fg, valign="cap",
                  alpha=0.85 if now else 0.45)
        if not now:
            text.text(c, "// ", x, yy, font="mono", size=size, color=DIM, align="right", valign="cap", alpha=0.45,
                      features=text.CODE)
        overlay.pattern_code(c, ctx, p.pat, played[id(p)] if now else [], x + label_w, yy, size=size, color=DIM,
                             hi=accent, alpha=k)


def harmony(c, t: float, x: float, y: float, size: float, accent: str) -> None:
    name, start = section_at(t)
    chords = HARMONY[name]
    bar = int(t // tl.bar_len) - start
    per = 1 if name == "outro" else 2
    cur = min(bar // per % len(chords) if name != "outro" else min(bar, 2), len(chords) - 1)
    text.text(c, name, x, y, font="mono", size=size, color=DIM)
    pen = x + size * 0.6 * 7
    for i, ch in enumerate(chords):
        if i:
            pen += text.text(c, "  ", pen, y, font="mono", size=size, color=DIM).width
        pen += text.text(c, ch, pen, y, font="mono", size=size, color=accent if i == cur else pal.fg,
                         alpha=1.0 if i == cur else 0.45).width


def progress(c, t: float, x: float, y: float, w: float, size: float, accent: str) -> None:
    draw.line(c, x, y, x + w, y, color=DIM, width=1.5, alpha=0.5)
    for name, b in SECTIONS:
        sx = x + w * tl.bar(b) / DUR
        draw.line(c, sx, y - 6, sx, y + 6, color=DIM, width=1.5, alpha=0.7)
        text.text(c, name, sx + 6, y + size * 1.6, font="mono", size=size, color=DIM, alpha=0.8)
    px = x + w * min(t / DUR, 1.0)
    draw.line(c, x, y, px, y, color=accent, width=2.0, alpha=0.9)
    draw.circle(c, px, y, 4.5, color=accent)


def make_audio(comp: Composition) -> str:
    mx = audio.Mix(DUR, tail=3.0)
    kicks = []
    for p in PARTS:
        ev = mx.pattern(p.pat, tl, start=tl.bar(p.bars[0]), end=tl.bar(p.bars[1]), bus=p.bus, gain_db=p.gain,
                        pan=p.pan, patch=p.patch, legato=p.legato, velocity=p.velocity, octave=p.octave,
                        swing=SWING)
        if p.row == "kick":
            kicks += [e["t"] for e in ev]
    mx.ambience(CRICKETS, start=0.0, end=tl.bar(18), level_db=-39, fade=4.0)
    mx.ambience(BIRDS, start=tl.bar(39), end=DUR, level_db=-36, fade=4.0)
    bar = tl.bar_len
    mx.fx("kick", pb.HighpassFilter(cutoff_frequency_hz=30),
          pb.Compressor(threshold_db=-14, ratio=2.5, attack_ms=8, release_ms=120))
    mx.fx("drums", pb.HighpassFilter(cutoff_frequency_hz=180), pb.LowpassFilter(cutoff_frequency_hz=9000),
          pb.Reverb(room_size=0.35, damping=0.6, wet_level=0.12, dry_level=1.0, width=1.0))
    mx.fx("bass", pb.HighpassFilter(cutoff_frequency_hz=28), pb.LowpassFilter(cutoff_frequency_hz=300),
          pb.Distortion(drive_db=3), pb.LowpassFilter(cutoff_frequency_hz=900),
          pb.Compressor(threshold_db=-20, ratio=3, attack_ms=20, release_ms=150))
    # パッドは夜の間はこもり、a で開いたまま、終わりにまたこもる (途中で開閉させて山を作らない)
    mx.fx("pad", audio.Sweep(pb.LadderFilter(mode=pb.LadderFilter.Mode.LPF24, resonance=0.15),
                             cutoff_hz=[(0, 380), (tl.bar(8), 3200), (tl.bar(40), 3200), (DUR, 1400)]),
          pb.HighpassFilter(cutoff_frequency_hz=150), pb.Chorus(rate_hz=0.3, depth=0.2, mix=0.3),
          pb.Reverb(room_size=0.85, damping=0.5, wet_level=0.35, dry_level=0.8, width=1.0))
    mx.fx("arp", audio.Sweep(pb.LadderFilter(mode=pb.LadderFilter.Mode.LPF24, resonance=0.25),
                             cutoff_hz=[(tl.bar(4), 500), (tl.bar(8), 5500)]),
          pb.HighpassFilter(cutoff_frequency_hz=250),
          pb.Delay(delay_seconds=bar / 16 * 3, feedback=0.38, mix=0.28),
          pb.Reverb(room_size=0.7, damping=0.5, wet_level=0.22, dry_level=1.0, width=1.0))
    mx.duck("pad", kicks, -6.0, 0.35)
    mx.duck("arp", kicks, -3.0, 0.25)
    mx.duck("bass", kicks, -4.0, 0.12)
    master = [pb.LowShelfFilter(cutoff_frequency_hz=90, gain_db=0.5),
              pb.HighShelfFilter(cutoff_frequency_hz=10000, gain_db=-2.0),
              pb.Compressor(threshold_db=-16, ratio=1.8, attack_ms=25, release_ms=250),
              # 和音を離して終わると最後の 2 秒で急に落ちるので、伸ばしたまま最後の 2 小節で消す (1 小節目はゆっくり)
              audio.Sweep(pb.Gain(), gain_db=[(tl.bar(42), 0.0), (tl.bar(43), -8.0), (DUR, -40.0)])]
    return mx.render(f"{comp.build_dir}/audio.wav", lufs=-14, master=master)
