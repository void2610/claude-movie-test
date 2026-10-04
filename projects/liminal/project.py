"""LiminalPalette の紹介動画。24 秒・120 BPM・12 小節。"""
import math

import pedalboard as pb
import skia

from motion import Composition, Scene, audio, draw, easing, noise, post, scene, sfx, text
from motion.anim import clamp, impact, lerp, progress, spring, stagger, tween, window
from motion.transition import Transition

from ui import (MONO, background, caret, checkmark, chip, colored_line, fuzzy, keycap, logo_mark, pal, panel,
                point_on, tokenize_cs, type_count, wire)

BPM = 120
DUR = 24.0

# 映像と音で共有するタイミング (秒)
T_PRESS = 1.5         # ⌘K を押す
T_TYPE = 2.0          # 検索語の入力開始 (16 分音符ごとに 1 文字)
QUERY = "player health set"
T_SELECT = T_TYPE + len(QUERY) / 8 + 0.125
T_ARG = 4.5           # 引数 50 を入力
T_RUN = 5.0           # 実行
T_CODE = 7.0          # コードのタイプ開始
T_ATTR = 8.0          # 属性が光る
T_DIAG = 9.5          # 3 経路の図へ
ARRIVE = [12.0, 12.5, 13.0]
T_CLI = 14.0
CLI_CMD = "$ liminal exec Player/Health/Set value=50"
CLI_RATE = 48         # 1 秒あたりの文字数
T_RESP = 15.0         # 応答が返る (拍の頭)
T_SCN = 16.0
SCN_STEP = 0.375      # シナリオの各ステップの間隔 (付点 8 分)
T_FEAT = 18.0
T_LOGO = 20.0

COMMANDS = ["Player/Health/Set", "Player/Health/Reset", "Player/Teleport", "Enemy/Spawn", "Enemy/Damage",
            "Game/TimeScale", "Anim/CompleteAll", "Debug/ShowColliders", "Save/WriteSlot", "Audio/Mute"]

CODE = ['[LiminalCommand("Player/Health/Set")]', "public void SetHealth(int value)", "    => Hp.Value = value;"]

CUES = [T_PRESS, T_RUN, T_ATTR, *ARRIVE, T_RESP, T_SCN + 1.5, T_LOGO]


def build() -> Composition:
    comp = Composition(duration=DUR, bpm=BPM, background=pal.bg, motion_blur=4, shutter=0.5, cues=sorted(CUES))
    tl = comp.timeline
    W, H = comp.width, comp.height

    @scene(0, None, z=-10)
    def bg(c, ctx):
        glow = 0.6 + 0.6 * impact(ctx.t, CUES, 4)
        background(c, ctx, glow=glow * tween(ctx.t, 0, 1.0, 0.3, 1.0), grid_alpha=tween(ctx.t, 0, 1.2, 0, 1))

    # ---------------------------------------------------------------- 1. ⌘K
    @scene(0, 2.25)
    def intro(c, ctx):
        # カーソルは拍に合わせて点滅
        blink = tl.beat_phase(ctx.t) < 0.5
        out = progress(ctx.t, T_PRESS + 0.1, T_PRESS + 0.5, easing.in_expo)
        if blink and ctx.t < T_PRESS:
            draw.rect(c, ctx.CX - 20, ctx.CY - 120, 40, 8, pal.yellow)
        for i, (lab, dx) in enumerate((("⌘", -80), ("K", 80))):
            s0 = 0.5 + i * 0.25
            up = spring(ctx.t, s0, 3.0, 0.55)
            press = clamp(1 - abs(ctx.t - T_PRESS) / 0.12) if ctx.t < T_PRESS + 0.12 else 0.0
            press = max(press, float(T_PRESS - 0.04 <= ctx.t < T_PRESS + 0.1))
            y = ctx.CY + 30 + (1 - up) * 260 + out * 400
            keycap(c, ctx.CX + dx, y, lab, press, 140, alpha=clamp(up * 2) * (1 - out))
        text.text(c, "Open the palette", ctx.CX, ctx.CY + 210, font=MONO, size=24, color=pal.dim, align="center",
                  valign="cap", alpha=window(ctx.t, 0.9, T_PRESS + 0.3, 0.3, 0.2))

    # ---------------------------------------------------------------- 2. パレット
    PW, PH = 1180, 620
    PX, PY = (W - PW) / 2, (H - PH) / 2 + 10

    def query_at(t):
        return QUERY[:type_count(t, T_TYPE, len(QUERY), 8)]

    def ranked(q):
        hits = [(c_, fuzzy(q, c_)) for c_ in COMMANDS]
        return [(c_, m) for c_, m in hits if m is not None] if q else [(c_, []) for c_ in COMMANDS]

    def draw_list(c, ctx, x, y, w):
        row = 62
        n = type_count(ctx.t, T_TYPE, len(QUERY), 8)
        since = (ctx.t - T_TYPE) - (n - 1) / 8 if n > 0 else 1.0
        q_now, q_prev = QUERY[:n], QUERY[:max(n - 1, 0)]
        k = easing.out_cubic(clamp(since / 0.1))
        now = {c_: (i, m) for i, (c_, m) in enumerate(ranked(q_now))}
        prev = {c_: (i, m) for i, (c_, m) in enumerate(ranked(q_prev))}
        for c_ in COMMANDS:
            a, b = prev.get(c_), now.get(c_)
            if a is None and b is None:
                continue
            ia = a[0] if a else (b[0] if b else 0)
            ib = b[0] if b else ia
            ry = y + lerp(ia, ib, k) * row
            alpha = 1.0 if (a and b) else (k if b else 1 - k)
            if ry > y + row * 6.5 or alpha <= 0:
                continue
            rank = ib if b else ia
            if rank == 0 and b:
                c.drawRRect(skia_rrect(x, ry, w, row - 8, 10), draw.paint(pal.sel, alpha=alpha))
            marks = set((b or a)[1])
            pen = x + 22
            for j, ch in enumerate(c_):
                col = pal.yellow if j in marks else (pal.text if rank == 0 else pal.dim)
                sh = text.text(c, ch, pen, ry + (row - 8) / 2, font=MONO, size=28,
                               axes={"wght": 650 if j in marks else 450}, color=col, valign="cap", alpha=alpha)
                pen += sh.width
            if rank == 0 and b and q_now:
                text.text(c, "Enter", x + w - 24, ry + (row - 8) / 2, font=MONO, size=20, color=pal.blue_hi,
                          align="right", valign="cap", alpha=alpha * 0.9)

    def draw_args(c, ctx, x, y, w):
        text.text(c, "Player/Health/Set", x, y + 30, font=MONO, size=34, axes={"wght": 650}, color=pal.yellow,
                  valign="cap")
        text.text(c, "プレイヤーの HP を設定する", x, y + 82, font="jp", size=24, color=pal.dim, valign="cap")
        # 観測フィールド (現在値が常時表示される)
        hp = round(tween(ctx.t, T_RUN, T_RUN + 0.45, 100, 50, easing.out_expo))
        panel(c, x, y + 120, w, 110, fill=pal.bg, radius=12)
        text.text(c, "● Player/Health", x + 24, y + 175, font=MONO, size=22, color=pal.green, valign="cap")
        text.text(c, f"{hp}", x + w - 24, y + 175, font=MONO, size=44, axes={"wght": 700}, color=pal.text,
                  align="right", valign="cap")
        bar_w = (w - 48) * hp / 100
        draw.rect(c, x + 24, y + 206, w - 48, 6, pal.line, r=3)
        draw.rect(c, x + 24, y + 206, bar_w, 6, pal.green, r=3)
        # 引数
        text.text(c, "value", x, y + 290, font=MONO, size=24, color=pal.dim, valign="cap")
        chip(c, x + 90, y + 290, "int", color=pal.purple, size=18, center_y=True)
        fld = skia_rrect(x + 170, y + 258, 220, 64, 10)
        c.drawRRect(fld, draw.paint(pal.bg))
        c.drawRRect(fld, draw.paint(pal.blue if ctx.t < T_RUN else pal.line, stroke=2))
        v = "50"[:type_count(ctx.t, T_ARG, 2, 8)]
        sh = text.text(c, v, x + 192, y + 290, font=MONO, size=30, color=pal.text, valign="cap")
        if ctx.t < T_RUN:
            caret(c, x + 192 + sh.width, y + 302, 30, ctx.t, pal.blue_hi)
        # Run ボタン
        pr = clamp(1 - abs(ctx.t - T_RUN) / 0.15)
        btn = skia_rrect(x + w - 190, y + 258, 190, 64, 12)
        c.drawRRect(btn, draw.paint(pal.blue.mix("#ffffff", pr * 0.3)))
        text.text(c, "Run", x + w - 95, y + 290, font=MONO, size=26, axes={"wght": 700}, color="#ffffff",
                  align="center", valign="cap")
        ok = progress(ctx.t, T_RUN + 0.1, T_RUN + 0.35)
        if ok > 0:
            checkmark(c, x + 18, y + 382, 26, ok)
            text.text(c, "success  ·  HP 100 → 50  ·  0.51 ms", x + 50, y + 382, font=MONO, size=24,
                      color=pal.green, valign="cap", alpha=ok)

    @scene(T_PRESS, 6.25, z=1)
    def palette(c, ctx):
        op = spring(ctx.t, T_PRESS, 2.6, 0.62)
        s = 0.55 + 0.45 * op
        c.save()
        c.translate(ctx.CX, ctx.CY)
        c.scale(s, s)
        c.translate(-ctx.CX, -ctx.CY)
        a = clamp(op * 1.6)
        # 中身も含めてまとめて不透明度をかける (開き始めに一覧だけが浮いて見えないように)
        c.saveLayerAlpha(None, int(round(a * 255)))
        a = 1.0
        panel(c, PX, PY, PW, PH, border=pal.blue, glow=0.6, radius=22)
        # タブ
        for i, lab in enumerate(("Command", "Scenario", "Log", "History")):
            col = pal.blue_hi if i == 0 else pal.faint
            text.text(c, lab, PX + 40 + i * 150, PY + 46, font=MONO, size=20, color=col, valign="cap", alpha=a)
        draw.line(c, PX + 40, PY + 66, PX + 150, PY + 66, pal.blue, 2, alpha=a)
        # 検索欄
        sf = skia_rrect(PX + 32, PY + 86, PW - 64, 76, 12)
        c.drawRRect(sf, draw.paint(pal.bg, alpha=a))
        c.drawRRect(sf, draw.paint(pal.blue, stroke=2, alpha=a))
        text.text(c, ">", PX + 58, PY + 124, font=MONO, size=32, axes={"wght": 700}, color=pal.blue, valign="cap",
                  alpha=a)
        q = query_at(ctx.t)
        sh = text.text(c, q, PX + 96, PY + 124, font=MONO, size=32, color=pal.text, valign="cap", alpha=a)
        if ctx.t < T_SELECT:
            caret(c, PX + 96 + sh.width, PY + 136, 32, ctx.t, pal.yellow, solid=ctx.t > T_TYPE)
        # 一覧 → 引数画面へ横にスライド
        slide = progress(ctx.t, T_SELECT, T_SELECT + 0.3, easing.inout_expo)
        c.save()
        c.clipRect(skia_rect(PX + 2, PY + 176, PW - 4, PH - 180), True)
        c.translate(-slide * PW, 0)
        if slide < 1:
            draw_list(c, ctx, PX + 32, PY + 190, PW - 64)
        c.translate(PW, 0)
        if slide > 0:
            draw_args(c, ctx, PX + 56, PY + 190, PW - 112)
        c.restore()
        c.restore()
        c.restore()

    # ---------------------------------------------------------------- 3. 1 つの属性 → 3 経路
    CODE_W, CODE_H = 1000, 270

    def code_box_rect(t):
        k = progress(t, T_DIAG, T_DIAG + 0.6, easing.inout_expo)
        x0, y0, w0 = (W - CODE_W) / 2, H / 2 - 40, CODE_W
        x1, y1, w1 = 1060, 560, 790
        return lerp(x0, x1, k), lerp(y0, y1, k), lerp(w0, w1, k), k

    LEFT = [("Human", "GUI", pal.dim), ("AI Agent", "HTTP API", pal.blue_hi), ("Test", "C# API", pal.dim)]
    LX, LW, LH = 90, 720, 150
    LYS = [360, 560, 760]

    def left_panel(c, ctx, i, a, lit):
        label, _, col = LEFT[i]
        y = LYS[i]
        border = pal.blue if i == 1 else pal.line
        panel(c, LX, y, LW, LH, border=border.mix(pal.yellow, lit), glow=lit + (0.3 if i == 1 else 0), label=label,
              label_color=col, alpha=a)
        cy = y + LH / 2 + 4
        if i == 0:
            fx = skia_rrect(LX + 28, y + 28, LW - 56, 46, 8)
            c.drawRRect(fx, draw.paint(pal.bg, alpha=a))
            c.drawRRect(fx, draw.paint(pal.blue, stroke=1.6, alpha=a))
            text.text(c, "> player health set", LX + 46, y + 51, font=MONO, size=24, color=pal.text, valign="cap",
                      alpha=a)
            c.drawRRect(skia_rrect(LX + 28, y + 84, LW - 56, 42, 8), draw.paint(pal.sel, alpha=a))
            text.text(c, "Player/Health/Set", LX + 46, y + 105, font=MONO, size=24, axes={"wght": 650},
                      color=pal.yellow, valign="cap", alpha=a)
        elif i == 1:
            text.text(c, ">  Set player HP to 50", LX + 40, cy, font=MONO, size=28, color=pal.text, valign="cap",
                      alpha=a)
        else:
            colored_line(c, tokenize_cs('await Execute("Player/Health/Set", 50)'), LX + 40, cy + 10, size=28,
                         alpha=a)

    @scene(5.75, 14.25, z=1)
    def code(c, ctx):
        # 見出し
        head = progress(ctx.t, 6.0, 6.5, easing.out_expo)
        head_out = progress(ctx.t, T_CODE - 0.2, T_CODE + 0.3, easing.inout_expo)
        if head > 0 and head_out < 1:
            sh = text.shape("ONE ATTRIBUTE.", "sans", 170, {"wght": 900, "wdth": 112})
            ox, oy = text.origin(sh, ctx.CX, ctx.CY - head_out * 260, "center", "cap")
            sc = 1 - 0.45 * head_out
            c.save()
            c.translate(ctx.CX, oy)
            c.scale(sc, sc)
            c.translate(-ctx.CX, -oy)
            for i, (ch, lx, lw, gi) in enumerate(sh.letters()):
                s0, s1 = stagger(i, len(sh.letters()), 6.0, 6.45, 0.25)
                p = progress(ctx.t, s0, s1, easing.out_expo)
                with draw.clip_rect(c, ox + lx - 10, oy - 180, lw + 20, 220):
                    col = pal.yellow if ch == "." else pal.text
                    c.drawTextBlob(sh.blob(gi), ox, oy + (1 - p) * 180, draw.paint(col))
            c.restore()
        # コードボックス
        appear = progress(ctx.t, T_CODE - 0.2, T_CODE + 0.2, easing.out_expo)
        if appear > 0:
            x, y, w, k = code_box_rect(ctx.t)
            hits = [a for a in ARRIVE if ctx.t >= a]
            lit = impact(ctx.t, ARRIVE + [T_ATTR], 5)
            h = CODE_H + (90 if hits else 0) * progress(ctx.t, ARRIVE[0], ARRIVE[0] + 0.25, easing.out_expo)
            panel(c, x, y, w, h, border=pal.yellow, glow=0.4 + 0.9 * lit, alpha=appear, radius=20)
            size = lerp(34, 30, k)
            for li, line in enumerate(CODE):
                t0 = T_CODE if li == 0 else T_ATTR + (li - 1) * 0.45
                rate = 40 if li == 0 else 60
                vis = type_count(ctx.t, t0, len(line), rate)
                ly = y + 74 + li * size * 1.55
                wdt = colored_line(c, tokenize_cs(line), x + 44, ly, size=size, visible=vis, alpha=appear)
                typing = 0 < vis < len(line) or (li == 2 and vis == len(line) and ctx.t < T_DIAG)
                if typing or (li == 0 and vis == 0 and ctx.t < T_CODE):
                    caret(c, x + 44 + wdt, ly + 8, size, ctx.t)
            # 属性の下線が走る
            ul = progress(ctx.t, T_ATTR, T_ATTR + 0.35, easing.out_expo)
            if ul > 0:
                aw = text.shape(CODE[0], MONO, size, {"wght": 450}).width
                draw.line(c, x + 44, y + 90, x + 44 + aw * ul, y + 90, pal.yellow, 3,
                          alpha=appear * (1 - progress(ctx.t, T_DIAG - 0.3, T_DIAG)))
            if hits:
                hy = y + CODE_H + 30
                draw.line(c, x + 40, hy - 40, x + w - 40, hy - 40, pal.yellow, 1.5, alpha=0.4)
                pop = progress(ctx.t, hits[-1], hits[-1] + 0.2, easing.out_back)
                checkmark(c, x + 58, hy, 24, progress(ctx.t, ARRIVE[0], ARRIVE[0] + 0.2))
                text.text(c, "HP 100 → 50", x + 92, hy, font=MONO, size=32, axes={"wght": 600}, color=pal.green,
                          valign="cap")
                text.text(c, f"×{len(hits)}", x + w - 44, hy, font=MONO, size=32, axes={"wght": 700},
                          color=pal.green, align="right", valign="cap", alpha=pop)

        # 3 経路
        if ctx.t >= T_DIAG:
            title = progress(ctx.t, T_DIAG + 0.2, T_DIAG + 0.7, easing.out_expo)
            text.text(c, "One command.", 90, 180, size=84, axes={"wght": 900, "wdth": 110}, color=pal.text,
                      valign="cap", alpha=title)
            text.text(c, "Three ways in.", 90 + text.shape("One command. ", "sans", 84,
                                                         {"wght": 900, "wdth": 110}).width,
                      180, size=84, axes={"wght": 900, "wdth": 110}, color=pal.blue, valign="cap",
                      alpha=progress(ctx.t, T_DIAG + 0.5, T_DIAG + 1.0, easing.out_expo))
            bx, by, bw, _ = code_box_rect(ctx.t)
            target = (bx, by + CODE_H / 2)
            # 合流点はチップ (最大幅の HTTP API) より右に置く
            hub_x = 1010
            # 灰色の線と共有する合流点〜矢印の区間を上書きされないよう、青い HTTP API の線を最後に描く
            for i in (0, 2, 1):
                a = progress(ctx.t, 10.0 + i * 0.5, 10.3 + i * 0.5, easing.out_expo)
                if a <= 0:
                    continue
                c.save()
                c.translate(-(1 - a) * 80, 0)
                lit = impact(ctx.t, [ARRIVE[i] - 0.45], 4) if ctx.t >= ARRIVE[i] - 0.45 else 0.0
                left_panel(c, ctx, i, a, lit)
                c.restore()
                cy = LYS[i] + LH / 2
                pts = [(LX + LW, cy), (hub_x, cy), (hub_x, target[1]), (target[0] - 6, target[1])]
                wp = progress(ctx.t, 10.5 + i * 0.3, 11.3 + i * 0.3, easing.inout_cubic)
                col = pal.blue if i == 1 else pal.faint
                path = wire(c, pts, wp, col, 3)
                _, chip_lab, chip_col = LEFT[i]
                if wp > 0.2:
                    chip(c, LX + LW + 30, cy, chip_lab, color=chip_col if i != 1 else pal.blue_hi, size=22,
                         center_y=True, fill="#0E0E10", alpha=clamp((wp - 0.2) * 3))
                # 信号が走って属性に届く
                launch = ARRIVE[i] - 0.45
                u = progress(ctx.t, launch, ARRIVE[i], easing.in_cubic)
                if 0 < u < 1:
                    px, py = point_on(path, u)
                    draw.circle(c, px, py, 14, pal.yellow, blur=10)
                    draw.circle(c, px, py, 7, "#ffffff")
            # 矢印
            ap = progress(ctx.t, 11.0, 11.4)
            if ap > 0:
                tx, ty = target
                draw.poly(c, [(tx - 30, ty - 16), (tx - 2, ty), (tx - 30, ty + 16)], pal.blue, closed=True,
                          alpha=ap)

    # ---------------------------------------------------------------- 4. AI Agent / CLI
    SKILLS = ["liminal-overview", "liminal-find-port", "liminal-list-commands", "liminal-execute",
              "liminal-get-state", "liminal-get-logs", "liminal-list-scenarios", "liminal-run-scenario"]

    @scene(13.75, 16.25, z=1)
    def cli(c, ctx):
        text.text(c, "Built for AI agents.", 120, 170, size=84, axes={"wght": 900, "wdth": 110}, color=pal.text,
                  valign="cap", alpha=progress(ctx.t, 14.0, 14.4, easing.out_expo))
        text.text(c, "HTTP API  ·  liminal CLI  ·  Claude Code skills", 124, 250, font=MONO, size=28,
                  color=pal.blue_hi, valign="cap", alpha=progress(ctx.t, 14.2, 14.6))
        tx, ty, tw, th = 120, 330, W - 240, 330
        panel(c, tx, ty, tw, th, fill="#0E0E10", radius=16)
        for i, col in enumerate(("#FF5F57", "#FEBC2E", "#28C840")):
            draw.circle(c, tx + 30 + i * 26, ty + 30, 8, col)
        text.text(c, "liminal — zsh", tx + tw / 2, ty + 30, font=MONO, size=18, color=pal.faint, align="center",
                  valign="cap")
        vis = type_count(ctx.t, T_CLI, len(CLI_CMD), CLI_RATE)
        line = CLI_CMD[:vis]
        sh = text.text(c, line[:1], tx + 36, ty + 110, font=MONO, size=30, color=pal.green, valign="cap")
        sh2 = text.text(c, line[1:], tx + 36 + sh.width, ty + 110, font=MONO, size=30, color=pal.text, valign="cap")
        if ctx.t < T_RESP:
            caret(c, tx + 36 + sh.width + sh2.width, ty + 122, 30, ctx.t)
        r = progress(ctx.t, T_RESP, T_RESP + 0.15)
        if r > 0:
            toks = [("{", pal.dim), ('"success"', pal.blue_hi), (": ", pal.dim), ("true", pal.green), (", ", pal.dim),
                    ('"value"', pal.blue_hi), (": ", pal.dim), ("null", pal.purple), (", ", pal.dim),
                    ('"durationMs"', pal.blue_hi), (": ", pal.dim), ("0.51", pal.yellow), ("}", pal.dim)]
            colored_line(c, toks, tx + 36, ty + 180, size=26, alpha=r)
            checkmark(c, tx + 50, ty + 252, 22, progress(ctx.t, T_RESP + 0.1, T_RESP + 0.3))
            text.text(c, "Player/Health/Set  →  HP 50", tx + 80, ty + 252, font=MONO, size=26, color=pal.green,
                      valign="cap", alpha=r)
        # スキルのチップが 16 分音符で並ぶ
        text.text(c, "8 Claude Code skills, bundled", 120, 750, size=34, axes={"wght": 700}, color=pal.text,
                  valign="cap", alpha=progress(ctx.t, T_RESP, T_RESP + 0.3))
        x0, y0 = 120, 800
        x, y = x0, y0
        for i, sk in enumerate(SKILLS):
            t0 = T_RESP + 0.125 + i * 0.0625
            p = spring(ctx.t, t0, 4.0, 0.5)
            if p <= 0:
                continue
            w = text.shape(sk, MONO, 24, {"wght": 500}).width + 24
            if x + w > W - 120:
                x, y = x0, y + 66
            c.save()
            c.translate(x + w / 2, y + 20)
            c.scale(p, p)
            c.translate(-(x + w / 2), -(y + 20))
            chip(c, x, y, sk, color=pal.text if i != 3 else pal.yellow, border=pal.blue if i != 3 else pal.yellow,
                 size=24, fill="#101830")
            c.restore()
            x += w + 26

    # ---------------------------------------------------------------- 5. シナリオテスト
    STEPS = [("Run", "Enemy/Spawn", "type=Goblin"), ("AssertEquals", "Enemy/Hp", "100"),
             ("Run", "Enemy/Damage", "amount=30"), ("AssertEventually", "Enemy/Hp", "70")]

    @scene(15.75, 18.25, z=1)
    def scenario(c, ctx):
        text.text(c, "Test it as a scenario.", 120, 170, size=84, axes={"wght": 900, "wdth": 110}, color=pal.text,
                  valign="cap", alpha=progress(ctx.t, 16.0, 16.4, easing.out_expo))
        colored_line(c, tokenize_cs('[LiminalScenario("Combat/EnemyTakesDamage")]'), 124, 260, size=30,
                     alpha=progress(ctx.t, 16.1, 16.4))
        for i, (op, path, arg) in enumerate(STEPS):
            y = 340 + i * 112
            a = progress(ctx.t, T_SCN + i * 0.08, T_SCN + 0.2 + i * 0.08, easing.out_expo)
            done_t = T_SCN + 0.25 + i * SCN_STEP
            done = progress(ctx.t, done_t, done_t + 0.15)
            running = done_t - SCN_STEP <= ctx.t < done_t
            panel(c, 120 - (1 - a) * 60, y, 1180, 92, border=pal.green if done > 0 else (pal.blue if running else pal.line),
                  glow=0.5 * done * impact(ctx.t, [done_t], 6) + (0.3 if running else 0), alpha=a, radius=14)
            text.text(c, f"{i + 1:02d}", 150, y + 46, font=MONO, size=22, color=pal.faint, valign="cap", alpha=a)
            text.text(c, op, 210, y + 46, font=MONO, size=28, color=pal.purple, valign="cap", alpha=a)
            ow = text.shape(op, MONO, 28).width
            text.text(c, path, 230 + ow, y + 46, font=MONO, size=28, axes={"wght": 650}, color=pal.yellow,
                      valign="cap", alpha=a)
            pw = text.shape(path, MONO, 28, {"wght": 650}).width
            text.text(c, arg, 250 + ow + pw, y + 46, font=MONO, size=28, color=pal.text, valign="cap", alpha=a)
            if running:
                ang = (ctx.t * 720) % 360
                c.drawArc(skia.Rect.MakeXYWH(1238, y + 30, 32, 32), ang, 270, False,
                          draw.paint(pal.blue_hi, stroke=4))
            if done > 0:
                checkmark(c, 1254, y + 46, 28, done)
        passed = progress(ctx.t, T_SCN + 1.5, T_SCN + 1.7, easing.out_back)
        if passed > 0:
            c.save()
            c.translate(1420, 520)
            c.scale(passed, passed)
            c.translate(-1420, -520)
            c.drawCircle(1580, 520, 150, draw.paint(pal.green, alpha=0.12))
            c.drawCircle(1580, 520, 150, draw.paint(pal.green, stroke=3))
            text.text(c, "4", 1580, 495, size=130, axes={"wght": 900}, color=pal.green, align="center", valign="cap")
            text.text(c, "PASSED", 1580, 600, font=MONO, size=26, axes={"wght": 700}, color=pal.green, align="center",
                      valign="cap")
            c.restore()
        text.text(c, "$ liminal run 'Combat/*' --report junit.xml", 124, 830, font=MONO, size=26, color=pal.dim,
                  valign="cap", alpha=progress(ctx.t, 16.6, 17.0))

    # ---------------------------------------------------------------- 6. 機能一覧
    FEATS = [("Fuzzy search", "Editor & Play Mode"), ("Typed arguments", "int · Vector3 · Color · enum"),
             ("Observable fields", "R3 ReactiveProperty"), ("Scenario tests", "Unity Test Runner + CI"),
             ("HTTP API + CLI", "localhost · Bearer token"), ("Zero in production", "stripped from Player builds")]

    @scene(17.75, 20.25, z=1)
    def features(c, ctx):
        cols, cw, ch, gap = 3, 520, 240, 34
        x0 = (W - (cols * cw + (cols - 1) * gap)) / 2
        y0 = 290
        text.text(c, "Everything a debug console should be.", ctx.CX, 180, size=64,
                  axes={"wght": 900, "wdth": 105}, color=pal.text, align="center", valign="cap",
                  alpha=progress(ctx.t, T_FEAT, T_FEAT + 0.4, easing.out_expo))
        for i, (title, sub) in enumerate(FEATS):
            r, k = divmod(i, cols)
            x, y = x0 + k * (cw + gap), y0 + r * (ch + gap)
            t0 = T_FEAT + 0.25 + i * 0.25
            p = spring(ctx.t, t0, 3.2, 0.55)
            if p <= 0:
                continue
            c.save()
            c.translate(x + cw / 2, y + ch / 2)
            c.scale(0.7 + 0.3 * p, 0.7 + 0.3 * p)
            c.translate(-(x + cw / 2), -(y + ch / 2))
            hot = impact(ctx.t, [t0], 5)
            panel(c, x, y, cw, ch, border=pal.line.mix(pal.blue, hot), glow=hot * 0.8, alpha=clamp(p))
            draw.rect(c, x + 36, y + 44, 44, 6, pal.yellow if i % 2 == 0 else pal.blue, alpha=clamp(p))
            text.text(c, title, x + 36, y + 120, size=44, axes={"wght": 800, "wdth": 105}, color=pal.text,
                      valign="cap", alpha=clamp(p))
            text.text(c, sub, x + 36, y + 180, font=MONO, size=22, color=pal.dim, valign="cap", alpha=clamp(p))
            c.restore()

    # ---------------------------------------------------------------- 7. ロゴ
    @scene(19.75, None, z=2)
    def logo(c, ctx):
        s = 170
        settle = tween(ctx.t, T_LOGO, DUR, 1.0, 1.04, easing.out_cubic)
        c.save()
        c.translate(ctx.CX, ctx.CY)
        c.scale(settle, settle)
        c.translate(-ctx.CX, -ctx.CY)
        word_l = text.shape("Liminal", "sans", 156, {"wght": 900, "wdth": 100})
        word_r = text.shape("Palette", "sans", 156, {"wght": 900, "wdth": 100})
        total = s * 1.25 + word_l.width + word_r.width
        x = ctx.CX - total / 2
        y = ctx.CY - 170
        mark = progress(ctx.t, T_LOGO, T_LOGO + 0.35, easing.out_expo)
        blink = 1.0 if ctx.t < T_LOGO + 1.0 or (ctx.t % 1.0) < 0.5 else 0.0
        logo_mark(c, x, y, s, mark, cursor=progress(ctx.t, T_LOGO + 0.25, T_LOGO + 0.45) * blink)
        wx = x + s * 1.25
        base = y + s * 0.82
        for word, col, t0, dx in ((word_l, pal.text, T_LOGO + 0.15, 0.0), (word_r, pal.blue, T_LOGO + 0.3,
                                                                           word_l.width)):
            for i, (ch, lx, lw, gi) in enumerate(word.letters()):
                s0, s1 = stagger(i, len(word.letters()), t0, t0 + 0.35, 0.25)
                p = progress(ctx.t, s0, s1, easing.out_expo)
                with draw.clip_rect(c, wx + dx + lx - 8, base - 180, lw + 16, 230):
                    c.drawTextBlob(word.blob(gi), wx + dx, base + (1 - p) * 180, draw.paint(col))
        tag = "Unity commands for humans, tests & AI agents"
        vis = type_count(ctx.t, T_LOGO + 0.6, len(tag), 48)
        tsh = text.shape(tag, MONO, 40, {"wght": 600})
        tx = wx
        # タグラインは青 → 黄のグラデーション (ヒーロー画像と同じ)
        g = skia.Paint(AntiAlias=True, Shader=skia.GradientShader.MakeLinear(
            [skia.Point(tx, 0), skia.Point(tx + tsh.width, 0)], [pal.blue_hi.skia(), pal.yellow.skia()]))
        blob = tsh.blob(list(range(min(vis, len(tsh.glyphs)))))
        if blob:
            c.drawTextBlob(blob, tx, y + s + 70, g)
        meta = progress(ctx.t, T_LOGO + 1.8, T_LOGO + 2.2, easing.out_expo)
        if meta > 0:
            mx = tx
            for lab, col in (("Unity 6000.3+", pal.text), ("C# 9", pal.purple), ("UI Toolkit", pal.blue_hi),
                             ("MIT", pal.yellow)):
                mx += chip(c, mx, y + s + 140, lab, color=col, size=22, alpha=meta, fill="#0E0E10") + 14
            text.text(c, "github.com/void2610/liminal-palette", tx, y + s + 250, font=MONO, size=30, color=pal.dim,
                      valign="cap", alpha=progress(ctx.t, T_LOGO + 2.2, T_LOGO + 2.6))
        c.restore()

    def camera(c, ctx):
        e = impact(ctx.t, CUES, 9)
        if e > 0.002:
            sx = noise.noise1(ctx.t * 28, 1) * 10 * e
            sy = noise.noise1(ctx.t * 28, 2) * 10 * e
            c.translate(sx, sy)
        z = 1 + 0.012 * e
        c.translate(ctx.CX, ctx.CY)
        c.scale(z, z)
        c.translate(-ctx.CX, -ctx.CY)

    comp.camera = camera
    comp.add(
        bg, intro, palette, code, cli, scenario, features, logo,
        Transition(palette, code, 5.75, 0.5, "zoom", amount=0.25),
        Transition(code, cli, 13.75, 0.5, "push", direction="left"),
        Transition(cli, scenario, 15.75, 0.5, "slices", n=9),
        Transition(scenario, features, 17.75, 0.5, "wipe", angle=12, edge=10, edge_color=pal.yellow.alpha(1)),
        Transition(features, logo, 19.75, 0.5, "iris"),
    )
    comp.post = [
        post.bloom(threshold=0.65, strength=0.45, radius=26),
        post.chroma(lambda ctx: 0.6 + 6.0 * impact(ctx.t, CUES, 10)),
        post.flash(peak=0.08, decay=22),
        post.vignette(0.32),
        post.grain(0.022),
    ]
    comp.audio = make_audio
    return comp


def skia_rect(x, y, w, h):
    return skia.Rect.MakeXYWH(x, y, w, h)


def skia_rrect(x, y, w, h, r):
    return skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(x, y, w, h), r, r)


def make_audio(comp: Composition) -> str:
    tl = comp.timeline
    mx = audio.Mix(comp.duration)
    beat = tl.beat_len
    nb = int(DUR / beat)

    def in_full(t):
        return (2.0 <= t < 6.0) or (T_ATTR <= t < T_LOGO)

    # ドラム
    for i in range(nb):
        t = tl.beat(i)
        if in_full(t):
            mx.hit("808bd", t, i=1, gain_db=-2)
            if i % 2 == 1 and t >= T_ATTR:
                mx.hit("cp", t, gain_db=-9, pan=0.1)
    for k in range(int(DUR / (beat / 2))):
        t = tl.step(k, 2)
        if in_full(t) and not (T_LOGO - 1.0 <= t < T_LOGO):
            mx.hit("808hc", t, gain_db=-17 + (3 if k % 2 else 0), pan=-0.25)
    for k in range(int(DUR / (beat / 4))):
        t = tl.step(k, 4)
        if T_ATTR <= t < T_LOGO - 1.0 and k % 4 in (1, 3):
            mx.hit("808hc", t, i=0, gain_db=-24, pan=0.3)

    # 和音: Am - F - C - G (小節ごと)
    roots = ["A1", "F1", "C2", "G1"]
    chords = [["A3", "C4", "E4"], ["F3", "A3", "C4"], ["G3", "C4", "E4"], ["G3", "B3", "D4"]]
    nbars = int(DUR / tl.bar_len)
    pad = []
    for b in range(nbars):
        ch = chords[b % 4] if b < 10 else ["A3", "C4", "E4", "B4"]
        dur = tl.bar_len * 0.98 if b < 10 else DUR - tl.bar(b)
        if b < 10 or b == 10:
            pad += [(tl.bar(b), dur, n, 78) for n in ch]
    mx.instrument(pad, patch="Pads/MKS-70 Warm Pad", bus="pad", gain_db=-6)
    mx.fx("pad", pb.HighpassFilter(cutoff_frequency_hz=180), pb.Reverb(room_size=0.8, wet_level=0.32))

    bass = []
    for k in range(int(DUR / (beat / 2))):
        t = tl.step(k, 2)
        if in_full(t) and k % 2 == 1:
            bass.append((t, beat * 0.42, roots[int(tl.bar_at(t)) % 4], 110))
    bass.append((T_LOGO, 1.6, "A1", 120))
    mx.instrument(bass, patch="Basses/Bass 1", bus="bass", gain_db=5)
    mx.fx("bass", pb.HighpassFilter(cutoff_frequency_hz=35), pb.LowpassFilter(cutoff_frequency_hz=900))

    arp = []
    for k in range(int(DUR / (beat / 4))):
        t = tl.step(k, 4)
        if T_ATTR <= t < T_LOGO:
            ch = chords[int(tl.bar_at(t)) % 4]
            n = audio.midi(ch[[0, 1, 2, 1][k % 4]]) + 12 + (12 if k % 8 >= 4 else 0)
            arp.append((t, beat / 4 * 0.8, n, 110 if k % 4 == 0 else 78))
    mx.instrument(arp, patch="Plucks/Clean", bus="arp", gain_db=-13)
    mx.fx("arp", pb.HighpassFilter(cutoff_frequency_hz=300),
          pb.Delay(delay_seconds=beat * 0.75, feedback=0.3, mix=0.22), pb.Reverb(room_size=0.5, wet_level=0.2))

    # UI の音: カーソルの点滅、タイプ音、チップの出現
    for i in range(3):
        mx.sfx(sfx.click(1800, pan=0.0), tl.beat(i), gain_db=-20)
    for k in range(len(QUERY)):
        mx.sfx(sfx.click(3200 + (k % 3) * 300, pan=-0.2 + 0.4 * (k % 2)), T_TYPE + k / 8, gain_db=-15)
    for k in range(2):
        mx.sfx(sfx.click(3000), T_ARG + k / 8, gain_db=-14)
    for k in range(len(CLI_CMD)):
        mx.sfx(sfx.click(3500 + (k % 4) * 250, 0.02, pan=-0.3 + 0.6 * ((k * 7) % 5) / 4), T_CLI + k / CLI_RATE,
               gain_db=-19)
    for k in range(len(CODE[0])):
        mx.sfx(sfx.click(2600 + (k % 3) * 200, 0.02), T_CODE + k / 40, gain_db=-21)
    for i in range(8):
        mx.sfx(sfx.click(1400 + i * 180, 0.06), T_RESP + 0.125 + i * 0.0625, gain_db=-13)
    for i in range(4):
        mx.sfx(sfx.click(1900, 0.08), T_SCN + 0.25 + i * SCN_STEP, gain_db=-11)
    for i in range(6):
        mx.sfx(sfx.click(1200 + i * 120, 0.05), T_FEAT + 0.25 + i * 0.25, gain_db=-12)

    # 衝撃と場面転換
    mx.sfx(sfx.impact(0.8, f_start=110, f_end=45, noise=0.3), T_PRESS, gain_db=-8)
    mx.sfx(sfx.impact(0.7, noise=0.25), T_RUN, gain_db=-10)
    mx.sfx(sfx.reverse_swell(1.0), T_ATTR, gain_db=-14)
    mx.sfx(sfx.impact(1.0), T_ATTR, gain_db=-7)
    for i, t in enumerate(ARRIVE):
        mx.sfx(sfx.whoosh(0.45, rise=0.95, f0=400, f1=5000, seed=10 + i), t, gain_db=-14)
        mx.sfx(sfx.click(2400 + i * 400, 0.1), t, gain_db=-8)
    for i, t in enumerate((6.0, 14.0, 16.0, 18.0)):
        mx.sfx(sfx.whoosh(0.7, seed=i), t, gain_db=-11)
    mx.sfx(sfx.riser(2.0), T_LOGO, gain_db=-12)
    mx.sfx(sfx.impact(1.6), T_LOGO, gain_db=-4)

    mx.duck("pad", [tl.beat(i) for i in range(nb) if in_full(tl.beat(i))], -9)
    mx.duck("arp", [tl.beat(i) for i in range(nb) if in_full(tl.beat(i))], -4)
    mx.fx("drums", pb.Compressor(threshold_db=-14, ratio=3), pb.Reverb(room_size=0.2, wet_level=0.06))
    mx.fx("sfx", pb.Reverb(room_size=0.5, wet_level=0.15))
    return mx.render(f"{comp.build_dir}/audio.wav", lufs=-14)
