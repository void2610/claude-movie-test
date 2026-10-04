"""キャプチャ機能のテスト用の「ゲーム画面っぽい」映像。2D シューティング風、20 秒。

環境変数 FAKEGAME=old で、ダッシュのエフェクトと敵の撃破エフェクトが無い「改修前」の版になる。
"""
import math
import os

import numpy as np

from motion import Composition, audio, draw, noise, scene, sfx, text
from motion.noise import hash01

OLD = os.environ.get("FAKEGAME", "new") == "old"
DUR = 20.0


def player_pos(t):
    x = 960 + 520 * math.sin(t * 0.7) + 120 * math.sin(t * 2.3)
    y = 760 + 90 * math.sin(t * 1.1)
    return x, y


def dash_times():
    return [3.0, 7.5, 11.2, 15.8]


def enemies(t):
    out = []
    for i in range(14):
        born = i * 1.3 + 0.5
        if t < born:
            continue
        life = t - born
        kill = born + 2.4 + hash01(i, 3) * 1.2
        x = 200 + 1520 * hash01(i, 1) + 60 * math.sin(life * 2 + i)
        y = 120 + life * 170
        out.append((i, x, y, born, kill))
    return out


def build() -> Composition:
    comp = Composition(duration=DUR, fps=60, bpm=120, background="#0B1020", motion_blur=1, linear=False,
                       name="fakegame_old" if OLD else "fakegame")

    @scene(0, DUR)
    def game(c, ctx):
        t = ctx.t
        # 背景: 流れる星と格子
        for k in range(120):
            x = hash01(k, 7) * ctx.W
            y = (hash01(k, 9) * ctx.H + t * (80 + 220 * hash01(k, 2))) % ctx.H
            draw.circle(c, x, y, 1 + 2 * hash01(k, 5), "#3A4A7A")
        for gx in range(0, ctx.W, 160):
            draw.line(c, gx, 0, gx, ctx.H, "#121A33", 2)
        px, py = player_pos(t)
        # 敵と撃破
        for i, x, y, born, kill in enemies(t):
            if t < kill:
                draw.rect(c, x, y, 64, 64, "#E0457B", r=10, center=True)
                draw.rect(c, x, y, 24, 24, "#0B1020", r=4, center=True)
            elif not OLD and t < kill + 0.6:
                e = (t - kill) / 0.6
                for j in range(14):
                    a = j / 14 * 2 * math.pi
                    r = 20 + 160 * e
                    draw.circle(c, x + math.cos(a) * r, y + math.sin(a) * r, 10 * (1 - e), "#FFB347")
                draw.circle(c, x, y, 90 * e, "#FFFFFF", stroke=6 * (1 - e), alpha=1 - e)
        # 弾
        for b in range(10):
            bt = (t * 6 + b) % 10 / 10
            bx, by = player_pos(t - bt * 0.5)
            draw.rect(c, bx, by - 60 - bt * 900, 8, 36, "#7CF7FF", r=4, center=True)
        # ダッシュの残像
        for d in dash_times():
            if d <= t < d + 0.35 and not OLD:
                for k in range(8):
                    qx, qy = player_pos(t - k * 0.03)
                    draw.circle(c, qx, qy, 40, "#7CF7FF", alpha=0.5 * (1 - k / 8))
        draw.poly(c, [(px, py - 50), (px + 40, py + 36), (px, py + 18), (px - 40, py + 36)], "#7CF7FF", closed=True)
        # HUD
        score = int(t * 1234) // 10 * 10
        text.text(c, f"SCORE {score:08d}", 48, 64, font="mono", size=34, color="#FFFFFF", valign="cap")
        text.text(c, "STAGE 1-3", ctx.W - 48, 64, font="mono", size=34, color="#FFFFFF", align="right", valign="cap")
        hp = 1 - 0.1 * int(t / 4)
        draw.rect(c, 48, ctx.H - 70, 400, 18, "#2A3355", r=9)
        draw.rect(c, 48, ctx.H - 70, 400 * hp, 18, "#4ADE80", r=9)
        if OLD:
            text.text(c, "build 0.3.1", ctx.W - 48, ctx.H - 60, font="mono", size=22, color="#55607F",
                      align="right", valign="cap")
        else:
            text.text(c, "build 0.4.0", ctx.W - 48, ctx.H - 60, font="mono", size=22, color="#55607F",
                      align="right", valign="cap")

    comp.add(game)

    def make_audio(comp):
        mx = audio.Mix(DUR)
        for k in range(int(DUR * 6)):
            mx.sfx(sfx.click(4200, 0.03, pan=-0.2), k / 6, gain_db=-24)
        for i, x, y, born, kill in enemies(DUR):
            if kill < DUR:
                mx.sfx(sfx.impact(0.5, f_start=200, f_end=60, noise=0.8, seed=i), kill, gain_db=-10,
                       pan=(x / 1920) * 2 - 1)
        if not OLD:
            for d in dash_times():
                mx.sfx(sfx.whoosh(0.4, rise=0.3, seed=int(d)), d + 0.1, gain_db=-8)
        tl = comp.timeline
        mx.instrument([(tl.bar(b), 1.9, n, 70) for b in range(10) for n in ("D3", "F3", "A3")],
                      patch="Pads/Pad 1", bus="music", gain_db=-14)
        return mx.render(f"{comp.build_dir}/audio.wav", lufs=-16)

    comp.audio = make_audio
    return comp
