"""liminal_poster。制作の判断は brief.md / style.md / shotlist.md にある。

現在は要のショット (three-ways) だけを作り込み、他は仮置き。方向性の合意を取ってから残りを作る。
"""
import sys
from pathlib import Path

import numpy as np
import skia

from motion import Composition, Palette, draw, post, rules, scene, text
from motion.anim import impact, progress, tween
from motion.persp import Camera, Card, draw_cards
from motion.shots import ShotList
from motion.texture import misregister

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "liminal"))
from ui import MONO, background, chip, colored_line, tokenize_cs  # noqa: E402

pal = Palette(bg="#0E0E11", fg="#ECECEF", panel="#1C1C21", line="#34343C", blue="#3B82F6", yellow="#FACC15",
              dim="#8B8B95", sel="#2B5A8C")
WAYS = [("Human", "GUI"), ("AI Agent", "HTTP API"), ("Test", "C# API")]


def build(aspect: str = "1:1") -> Composition:
    shots = ShotList.from_md(HERE / "shotlist.md")
    W, H = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080)}[aspect]
    comp = Composition(width=W, height=H, duration=shots.duration, bpm=120, background=pal.bg, shots=shots,
                       motion_blur=3, loop=True)
    tl = comp.timeline
    sh = shots["three-ways"]
    arrive = [tl.beat(14), tl.beat(15), tl.beat(16)]      # 7.0 / 7.5 / 8.0 秒
    comp.cues = arrive

    @scene(0, None, z=-10)
    def bg(c, ctx):
        background(c, ctx, glow=0.5, grid_alpha=0.8)

    def placeholder(shot):
        @scene(shot.start, shot.end)
        def draw_(c, ctx):
            text.text(c, shot.name.upper(), W * 0.08, H * 0.46, size=W * 0.07, axes={"wght": 900}, color=pal.dim)
            text.text(c, shot.purpose, W * 0.08, H * 0.46 + W * 0.05, size=W * 0.022, color=pal.dim)
        return draw_

    def code_card(lit: float, hits: int):
        def f(c):
            draw.fill(c, pal.panel)
            c.drawRRect(skia.RRect.MakeRectXY(skia.Rect.MakeWH(560, 250), 18, 18),
                        draw.paint(pal.line.mix(pal.yellow, 0.55 + 0.45 * lit), stroke=3))
            for i, ln in enumerate(['[LiminalCommand("Player/Health/Set")]', "public void SetHealth(int value)",
                                    "    => Hp.Value = value;"]):
                colored_line(c, tokenize_cs(ln), 28, 60 + i * 42, size=21)
            if hits:
                text.text(c, f"HP 100 → 50   ×{hits}", 28, 212, font=MONO, size=24, axes={"wght": 650},
                          color="#4ADE80", valign="cap")
        return f

    def way_card(i: int, glow: float):
        label, via = WAYS[i]

        def f(c):
            draw.fill(c, pal.panel)
            border = pal.blue if i == 1 else pal.line
            c.drawRRect(skia.RRect.MakeRectXY(skia.Rect.MakeWH(360, 132), 16, 16),
                        draw.paint(border.mix(pal.yellow, glow), stroke=2.5))
            chip(c, 20, 18, label, color=pal.blue if i == 1 else pal.dim, size=18)
            body = ["> player health set", "> Set player HP to 50", 'await Execute("…/Set", 50)'][i]
            if i == 2:
                colored_line(c, tokenize_cs(body), 22, 96, size=20)
            else:
                text.text(c, body, 22, 92, font=MONO, size=21, color=pal.fg, valign="cap")
            text.text(c, via, 340, 30, font=MONO, size=16, color=pal.dim, align="right", valign="cap")
        return f

    @scene(sh.start, sh.end)
    def three_ways(c, ctx):
        t = ctx.t
        # カメラは 1 ショットに遅い回り込みを 1 回だけ (style.md: 活発さ 2)
        cam = Camera.default(ctx).orbit(yaw=tween(t, sh.start, sh.end, -16, -6, rules.rule("camera").ease),
                                        pitch=6).dolly(1.02)
        hits = sum(t >= a for a in arrive)
        lit = impact(t, arrive, 6)
        target = (W * 0.71, H * 0.47, 0.0)
        cards = [Card(target, (560, 250), rot=(-8, 0, 0), draw=code_card(lit, hits), radius=18, shadow=26)]
        starts = [rules.stagger(i, 3, sh.start + 0.25, gap=0.5) for i in range(3)]
        src = []
        for i in range(3):
            p = rules.enter("panel", t, starts[i])
            y = H * (0.25 + 0.22 * i)
            pos = (W * 0.19, y, 900 * (1 - min(p, 1.0)))
            glow = impact(t, [arrive[i] - 0.4], 5) if t >= arrive[i] - 0.4 else 0.0
            cards.append(Card(pos, (360, 132), rot=(14, 0, 0), draw=way_card(i, glow), radius=16, shadow=18))
            src.append((pos, p))
        # 配線は 3D の端点を写してから 2D で描く (カードの奥行きに追従させる)
        tq = cam.project(np.array([[target[0] - 280, target[1], 0.0]]))[0]
        for i, (pos, p) in enumerate(src):
            if p < 0.6:
                continue
            sq = cam.project(np.array([[pos[0] + 180, pos[1], pos[2]]]))[0]
            mid = (sq[0] + tq[0]) / 2
            wire = draw.path([(sq[0], sq[1]), (mid, sq[1]), (mid, tq[1]), (tq[0], tq[1])])
            wp = progress(t, starts[i] + 0.35, starts[i] + 0.9, rules.MOVE)
            col = pal.blue if i == 1 else pal.dim
            c.drawPath(draw.trim(wire, 0, wp), draw.paint(col, stroke=3))
            u = progress(t, arrive[i] - 0.4, arrive[i], rules.EXIT)
            if 0 < u < 1:
                m = skia.PathMeasure(wire, False)
                pt, _ = m.getPosTan(m.getLength() * u)
                draw.circle(c, pt.x(), pt.y(), 13, pal.yellow, blur=9)
                draw.circle(c, pt.x(), pt.y(), 6, "#FFFFFF")
        draw_cards(c, cam, cards)
        # 見出しは左下に寄せて画面からはみ出させる (中央の大きな文字にしない)
        hp = rules.enter("headline", t, sh.start + 0.1)
        s = rules.scale_in("headline", min(hp, 1.0))
        c.save()
        # 左端だけ少しはみ出させ、右端は画面内に収める
        hsize = text.fit_size("THREE WAYS IN.", W * 0.98, axes={"wght": 900, "wdth": 112})
        c.translate(-W * 0.02, H - 70)
        c.scale(s, s)
        text.text(c, "THREE WAYS IN.", 0, 0, size=hsize, axes={"wght": 900, "wdth": 112}, color=pal.fg,
                  alpha=min(hp, 1.0))
        c.restore()
        text.text(c, "ONE ATTRIBUTE ·", 34, H - 222, font=MONO, size=24, color=pal.yellow,
                  alpha=progress(t, sh.start + 0.3, sh.start + 0.6))

    comp.add(bg, *[placeholder(s) for s in shots if s.name != "three-ways"], three_ways)
    comp.post = [
        post.bloom(threshold=0.7, strength=0.35, radius=20),
        misregister(lambda ctx: 4.0 * impact(ctx.t, arrive, 7)),
        post.vignette(0.28),
        post.grain(0.018),
    ]
    return comp
