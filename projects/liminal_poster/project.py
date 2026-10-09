"""liminal_poster。制作の判断は brief.md / style.md / shotlist.md にある。

12 秒で最初と最後のコマが一致するループ。ショットごとに別のシーンにせず、1 つの 2.5D 空間の中で
パレット・属性のカード・3 経路のカード・見出しをすべて時刻の関数として動かし、継ぎ目を作らない。
"""
import math
import sys
from pathlib import Path

import numpy as np
import pedalboard as pb
import skia

from motion import Composition, Palette, audio, draw, post, rules, scene, sfx, text
from motion.anim import clamp, impact, lerp, progress
from motion.checks import Check, color_along
from motion.nodes import edits_of, node, props
from motion.tune import tune
from motion.persp import Camera, Card, draw_cards
from motion.shots import ShotList
from motion.texture import misregister

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "liminal"))
from ui import MONO, background, chip, colored_line, fuzzy, logo_mark, tokenize_cs  # noqa: E402

WAYS = [("Human", "GUI"), ("AI Agent", "HTTP API"), ("Test", "C# API")]
WAY_IDS = ["way.human", "way.agent", "way.test"]
COMMANDS = ["Player/Health/Set", "Player/Health/Reset", "Player/Teleport", "Enemy/Spawn", "Game/TimeScale"]
CODE = ['[LiminalCommand("Player/Health/Set")]', "public void SetHealth(int value)", "    => Hp.Value = value;"]
QUERY = "player health set"
LOOP = 12.0
MARGIN = 76           # 正方形のセーフエリア (端から 7%)

# タイミング (秒)・色・文言はスタジオから調整できる (tune.json)。音も同じ値を引く
P = tune(HERE,
         T_FLIP=(2.0, 1.5, 3.0), T_CODE=(2.25, 1.75, 3.5), T_UNDERLINE=(3.5, 2.5, 4.5), T_SHIFT=(4.6, 3.8, 5.0),
         T_WAYS=(5.25, 4.75, 6.0), WAY_GAP=(0.5, 0.25, 1.0), ARRIVE0=(7.0, 6.0, 8.0), T_WORDMARK=(9.0, 8.5, 10.0),
         TYPE_RATE=(12, 6, 24), CAM_SWAY=(5.0, 0.0, 15.0), MISREG=(4.0, 0.0, 10.0), GRAIN=(0.018, 0.0, 0.06),
         BLUE="#3B82F6", YELLOW="#FACC15",
         H1="ONE ATTRIBUTE.", H1_SMALL="[LiminalCommand]", H2="THREE WAYS IN.", H2_SMALL="HUMANS · AI AGENTS · TESTS")
T_TYPE = 0.3
TYPE_RATE = P.TYPE_RATE
T_SELECT = T_TYPE + len(QUERY) / TYPE_RATE + 0.08
T_FLIP = P.T_FLIP
T_CODE = P.T_CODE
T_UNDERLINE = P.T_UNDERLINE
T_SHIFT = P.T_SHIFT
T_WAYS = P.T_WAYS
ARRIVE = [P.ARRIVE0 + P.WAY_GAP * i for i in range(3)]
T_WORDMARK = P.T_WORDMARK

pal = Palette(bg="#0E0E11", fg="#ECECEF", panel="#1C1C21", line="#34343C", blue=P.BLUE, yellow=P.YELLOW,
              dim="#8B8B95", sel="#2B5A8C")

T_RETURN = 10.8       # 全部が 0 秒の状態へ戻り始める
T_BACK = 11.0         # パレットが表に戻る


def phase(t: float) -> float:
    return 2 * math.pi * t / LOOP


def build(aspect: str = "1:1") -> Composition:
    shots = ShotList.from_md(HERE / "shotlist.md")
    W, H = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080)}[aspect]
    comp = Composition(width=W, height=H, duration=LOOP, bpm=120, background=pal.bg, shots=shots,
                       motion_blur=3, loop=True, tune=P)
    comp.cues = [T_UNDERLINE] + ARRIVE

    @scene(0, None, z=-10)
    def bg(c, ctx):
        n = props(ctx, "background")
        # 格子は 12 秒でちょうど 1 マス (120px) 流す。半端だとループの継ぎ目で跳ぶ
        background(c, ctx, glow=n.prop("glow", 0.5), grid_alpha=n.prop("grid", 0.8), drift=120 / LOOP)

    # ------------------------------------------------------------ カードの中身
    PW, PH = 720, 420

    def palette_face(t, n):
        query = n.prop("query", QUERY)
        sel_col = n.prop("selection", "#2B5A8C")

        def f(c):
            draw.fill(c, pal.panel)
            c.drawRRect(skia.RRect.MakeRectXY(skia.Rect.MakeWH(PW, PH), 20, 20), draw.paint(pal.blue, stroke=3))
            for i, lab in enumerate(("Command", "Scenario", "Log", "History")):
                text.text(c, lab, 30 + i * 128, 36, font=MONO, size=17, color=pal.blue if i == 0 else "#55555E",
                          valign="cap")
            c.drawRRect(skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(24, 62, PW - 48, 62), 10, 10),
                        draw.paint(pal.bg))
            c.drawRRect(skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(24, 62, PW - 48, 62), 10, 10),
                        draw.paint(pal.blue, stroke=2))
            text.text(c, ">", 44, 93, font=MONO, size=26, axes={"wght": 700}, color=pal.blue, valign="cap")
            q = query[:int(clamp((t - T_TYPE) * TYPE_RATE / len(query)) * len(query))] if t < 9 else ""
            sh = text.text(c, q, 76, 93, font=MONO, size=26, color=pal.fg, valign="cap")
            if t < T_SELECT and (t % 0.5) < 0.3 or T_TYPE <= t < T_SELECT:
                draw.rect(c, 78 + sh.width, 76, 13, 32, pal.yellow)
            rows = [(cmd, fuzzy(q, cmd)) for cmd in COMMANDS]
            rows = [(cmd, m) for cmd, m in rows if m is not None] if q else [(cmd, []) for cmd in COMMANDS]
            for r, (cmd, marks) in enumerate(rows[:5]):
                y = 146 + r * 52
                selected = r == 0 and t >= T_SELECT
                if selected:
                    c.drawRRect(skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(24, y, PW - 48, 46), 8, 8),
                                draw.paint(sel_col))
                pen = 44
                for j, ch in enumerate(cmd):
                    hit = j in set(marks)
                    col = pal.yellow if hit else (pal.fg if selected else pal.dim)
                    s2 = text.text(c, ch, pen, y + 23, font=MONO, size=22, axes={"wght": 650 if hit else 450},
                                   color=col, valign="cap")
                    pen += s2.width
        return f

    def code_face(lit: float, underline: float, hits: int, k: float, n):
        lines = [n.prop("line1", CODE[0]), n.prop("line2", CODE[1]), n.prop("line3", CODE[2])]
        result = n.prop("result", "HP 100 → 50")

        def f(c):
            c.scale(k, k)
            draw.fill(c, pal.panel)
            c.drawRRect(skia.RRect.MakeRectXY(skia.Rect.MakeWH(560, 250), 18, 18),
                        draw.paint(pal.line.mix(pal.yellow, 0.55 + 0.45 * lit), stroke=3))
            for i, ln in enumerate(lines):
                colored_line(c, tokenize_cs(ln), 28, 60 + i * 42, size=21)
            if underline > 0:
                aw = text.shape(lines[0], MONO, 21, {"wght": 450}).width
                draw.line(c, 28, 72, 28 + aw * underline, 72, pal.yellow, 3)
            if hits:
                text.text(c, f"{result}   ×{hits}", 28, 212, font=MONO, size=24, axes={"wght": 650},
                          color="#4ADE80", valign="cap")
        return f

    def way_face(i: int, glow: float, n):
        label = n.prop("label", WAYS[i][0])
        via = n.prop("via", WAYS[i][1])
        body = n.prop("body", ["> player health set", "> Set player HP to 50", 'await Execute("…/Set", 50)'][i])

        def f(c):
            draw.fill(c, pal.panel)
            border = pal.blue if i == 1 else pal.line
            c.drawRRect(skia.RRect.MakeRectXY(skia.Rect.MakeWH(360, 132), 16, 16),
                        draw.paint(border.mix(pal.yellow, glow), stroke=2.5))
            chip(c, 20, 18, label, color=pal.blue if i == 1 else pal.dim, size=18)
            if i == 2:
                colored_line(c, tokenize_cs(body), 22, 96, size=20)
            else:
                text.text(c, body, 22, 92, font=MONO, size=21, color=pal.fg, valign="cap")
            text.text(c, via, 340, 30, font=MONO, size=16, color=pal.dim, align="right", valign="cap")
        return f

    # ------------------------------------------------------------ 空間
    def layout(t0_: float, ctx) -> dict:
        """カメラと各カードの位置。描画と検査 (comp.checks) の両方から同じ値を引く。

        スタジオで動かした差分 (edits.json) の位置を含める。配線の端点がカードに追従するように。
        """
        E = edits_of(comp)
        t = t0_
        # カメラは 12 秒周期の滑らかな揺れだけにする (style.md: 活発さ 2。周期関数なのでループの継ぎ目が出ない)
        cam = Camera.default(ctx).orbit(yaw=-10 + P.CAM_SWAY * math.sin(phase(t)), pitch=6 + 2 * math.sin(phase(t) + 1.0))
        cam = cam.dolly(1.02 + 0.03 * (1 - math.cos(phase(t))) / 2)
        tc = E.t("code", t)
        come = clamp(rules.enter("panel", tc, T_CODE))
        go = progress(tc, T_RETURN, T_RETURN + 0.6, rules.EXIT)
        # 右に寄ったまま奥へ去る (中央へ戻すと、まだ残っている 3 経路のカードに重なる)
        shift = progress(tc, T_SHIFT, T_SHIFT + 0.6, rules.MOVE)
        k = lerp(1.5, 1.0, shift)
        target = (lerp(W * 0.5, W * 0.71, shift), lerp(H * 0.4, H * 0.47, shift), 700 * (1 - come) + 600 * go)
        src = []
        for i, wid in enumerate(WAY_IDS):
            tw = E.t(wid, t)
            t0 = rules.stagger(i, 3, T_WAYS, gap=P.WAY_GAP)
            p = clamp(rules.enter("panel", tw, t0))
            out = progress(tw, T_RETURN + i * 0.08, T_RETURN + 0.5 + i * 0.08, rules.EXIT)
            src.append(((W * 0.19, H * (0.25 + 0.22 * i), 900 * (1 - p) + 900 * out), p, out, t0 + E.tr(wid, "dt")))

        def moved(id, pos):
            return (pos[0] + E.tr(id, "dx"), pos[1] + E.tr(id, "dy"), pos[2] + E.tr(id, "dz"))

        return {"cam": cam, "come": come, "go": go, "k": k, "target": target, "src": src,
                "target_e": moved("code", target), "k_e": k * E.tr("code", "scale", 1.0),
                "src_e": [moved(wid, s[0]) for wid, s in zip(WAY_IDS, src)],
                "ws_e": [E.tr(wid, "scale", 1.0) for wid in WAY_IDS]}

    def wires(t: float, ctx) -> list[tuple[int, list[tuple[float, float]], float]]:
        """見えている配線の (経路番号, 折れ線の点, 描き進み具合)。"""
        if not (T_WAYS < t < T_RETURN + 0.6):
            return []
        L = layout(t, ctx)
        cam, target, k = L["cam"], L["target_e"], L["k_e"]
        tq = cam.project(np.array([[target[0] - 280 * k, target[1], target[2]]]))[0]
        out = []
        for i, ((_, p, gone, t0), pos, ws) in enumerate(zip(L["src"], L["src_e"], L["ws_e"])):
            if p * (1 - gone) < 0.6:
                continue
            sq = cam.project(np.array([[pos[0] + 180 * ws, pos[1], pos[2]]]))[0]
            mid = (sq[0] + tq[0]) / 2
            wp = progress(t, t0 + 0.35, t0 + 0.9, rules.MOVE) * (1 - progress(t, T_RETURN - 0.3, T_RETURN))
            out.append((i, [(sq[0], sq[1]), (mid, sq[1]), (mid, tq[1]), (tq[0], tq[1])], wp))
        return out

    @scene(0, None)
    def world(c, ctx):
        t = ctx.t
        E = edits_of(comp)
        L = layout(t, ctx)
        cards = []

        # パレット: 0 秒で既に開いている。裏返って消え、最後に表へ戻る
        tp = E.t("palette", t)
        pn = props(ctx, "palette")
        flip = progress(tp, T_FLIP, T_FLIP + 0.7, rules.MOVE) - progress(tp, T_BACK, T_BACK + 0.8, rules.MOVE)
        cards.append(Card((W * 0.5, H * 0.42, 220 * flip), (PW, PH), rot=(12 + 88 * flip, -6, 0),
                          draw=palette_face(tp, pn), radius=20, shadow=30, id="palette", label="パレット",
                          span=(0.0, T_FLIP + 0.7), node=pn))

        # 属性のカード
        tc = E.t("code", t)
        cn = props(ctx, "code")
        hits = sum(tc >= a for a in ARRIVE) if tc < T_RETURN + 0.4 else 0
        lit = impact(tc, ARRIVE + [T_UNDERLINE], 6)
        k = L["k"]
        underline = progress(tc, T_UNDERLINE, T_UNDERLINE + 0.4, rules.ENTER) * (1 - L["go"])
        if L["come"] > 0.02 and L["go"] < 0.98:
            cards.append(Card(L["target"], (560 * k, 250 * k), rot=(-8, 0, 0),
                              draw=code_face(lit, underline, hits, k, cn), radius=18 * k, shadow=26, id="code",
                              label="属性のコード", span=(T_CODE, T_RETURN + 0.6), node=cn))

        # 3 経路のカード
        for i, (pos, p, gone, t0) in enumerate(L["src"]):
            if p > 0.02 and gone < 0.98:
                wid = WAY_IDS[i]
                tw = E.t(wid, t)
                wn = props(ctx, wid)
                glow = impact(tw, [ARRIVE[i] - 0.4], 5) if tw >= ARRIVE[i] - 0.4 else 0.0
                cards.append(Card(pos, (360, 132), rot=(14, 0, 0), draw=way_face(i, glow, wn), radius=16, shadow=18,
                                  id=wid, label=f"経路: {WAYS[i][0]}", span=(t0, T_RETURN + 0.5), node=wn))

        # 配線は 3D の端点を写してから 2D で描く (カードの奥行きに追従させる)
        # 灰色の線と区間を共有するので、青い HTTP API の線を最後に描く
        with node(c, ctx, "wires", label="配線", span=(T_WAYS, T_RETURN)) as n:
            http_col, other_col = n.prop("http_color", P.BLUE), n.prop("other_color", "#8B8B95")
            width = n.prop("width", 3.0)
            for i, pts, wp in sorted(wires(t, ctx), key=lambda w: w[0] == 1):
                wire = draw.path(pts)
                n.c.drawPath(draw.trim(wire, 0, wp), draw.paint(http_col if i == 1 else other_col, stroke=width))
                u = progress(t, ARRIVE[i] - 0.4, ARRIVE[i], rules.EXIT)
                if 0 < u < 1:
                    m = skia.PathMeasure(wire, False)
                    pt, _ = m.getPosTan(m.getLength() * u)
                    draw.circle(n.c, pt.x(), pt.y(), 13, pal.yellow, blur=9)
                    draw.circle(n.c, pt.x(), pt.y(), 6, "#FFFFFF")
        draw_cards(c, L["cam"], cards, edits=E)

    # ------------------------------------------------------------ 左下の文字 (ワードマーク → 見出し → 見出し → ワードマーク)
    def headline(c0, ctx, id: str, label: str, small: str, t0: float, t1: float):
        with node(c0, ctx, id, origin=(MARGIN, H - MARGIN), label=f"見出し {id}", span=(t0, t1)) as n:
            _headline(n, ctx, n.prop("text", label), n.prop("small", small), t0, t1)

    def _headline(n, ctx, label, small, t0, t1):
        c, t = n.c, n.t
        p = rules.enter("headline", t, t0)
        q = rules.leave("headline", t, t1)
        if p <= 0 or q <= 0:
            return
        fg, accent = n.prop("color", "#ECECEF"), n.prop("small_color", P.YELLOW)
        size = text.fit_size(label, W - 2 * MARGIN, axes={"wght": 900, "wdth": 112})
        c.save()
        # 抜ける見出しは上へ、入る見出しは下から。入れ替えの間に空白のコマを作らない
        c.clipRect(skia.Rect.MakeLTRB(0, H - MARGIN - size * 0.8, W, H), skia.ClipOp.kIntersect, True)
        c.translate(MARGIN, H - MARGIN - (1 - q) * size + (1 - min(p, 1.0)) * size)
        s = rules.scale_in("headline", min(p, 1.0))
        c.scale(s, s)
        text.text(c, label, 0, 0, size=size, axes={"wght": 900, "wdth": 112}, color=fg, alpha=min(p, 1.0) * q)
        c.restore()
        text.text(c, small, MARGIN, H - MARGIN - size * 0.86, font=MONO, size=24, color=accent,
                  alpha=progress(t, t0 + 0.2, t0 + 0.5) * q)

    def wordmark(c0, ctx, alpha: float, rise: float):
        with node(c0, ctx, "wordmark", origin=(MARGIN, H - MARGIN), label="ワードマーク", span=(T_WORDMARK, LOOP)) as n:
            _wordmark(n, alpha, rise)

    def _wordmark(n, alpha, rise):
        c = n.c
        s = 92
        tagline = n.prop("tagline", "Unity commands for humans, tests & AI agents")
        x, y = MARGIN, H - MARGIN - 80 + rise
        logo_mark(c, x, y, s, alpha=alpha)
        wl = text.shape("Liminal", "sans", 84, {"wght": 900})
        text.text(c, "Liminal", x + s * 1.2, y + s * 0.82, size=84, axes={"wght": 900}, color=pal.fg, alpha=alpha)
        text.text(c, "Palette", x + s * 1.2 + wl.width, y + s * 0.82, size=84, axes={"wght": 900},
                  color=pal.blue, alpha=alpha)
        text.text(c, tagline, x, y - 26, font=MONO, size=22,
                  color=pal.dim, alpha=alpha)

    @scene(0, None, z=5, fixed=True)
    def captions(c, ctx):
        t = ctx.t
        headline(c, ctx, "h1", P.H1, P.H1_SMALL, T_FLIP + 0.1, T_WAYS - 0.05)
        headline(c, ctx, "h2", P.H2, P.H2_SMALL, T_WAYS - 0.3, T_WORDMARK + 0.15)
        # ワードマークは 9 秒に見出しと入れ替わりで出て、ループをまたいで次の 1.8 秒まで残る
        if t >= T_WORDMARK:
            a = clamp(rules.enter("panel", t, T_WORDMARK))
            wordmark(c, ctx, a, (1 - a) * 60)
        elif t < T_FLIP:
            a = rules.leave("micro", t, T_FLIP - 0.05)
            wordmark(c, ctx, a, 0.0)

    def http_wire_is_blue(img, ctx):
        """ユーザー指摘 (2026-10-04, 2026-10-09): HTTP API の線の合流区間が灰色の線に上書きされていた。"""
        ws = {i: pts for i, pts, wp in wires(ctx.t, ctx) if wp > 0.99}
        if 1 not in ws:
            return "HTTP API の線が描かれていない"
        (_, _), (mx_, y0), (_, y1), (x1, _) = ws[1]
        # 縦の合流区間と、矢印までの横の区間を、端を避けて調べる
        pts = [(mx_, y0 + (y1 - y0) * u) for u in np.linspace(0.15, 0.85, 12)]
        pts += [(mx_ + (x1 - mx_) * u, y1) for u in np.linspace(0.2, 0.8, 8)]
        return color_along(img, pts, edits_of(comp).prop("wires", "http_color", P.BLUE))

    comp.checks.append(Check("HTTP API の線の合流区間は青", [8.3, 8.7, 9.6], http_wire_is_blue))
    comp.add(bg, world, captions)
    comp.post = [
        post.bloom(threshold=0.7, strength=0.35, radius=20),
        misregister(lambda ctx: P.MISREG * impact(ctx.t, ARRIVE, 7)),
        post.vignette(0.28),
        post.grain(P.GRAIN),
    ]
    comp.audio = make_audio
    return comp


def make_audio(comp: Composition) -> str:
    tl = comp.timeline
    mx = audio.Mix(LOOP, tail=2.0)
    beats = [tl.beat(i) for i in range(int(LOOP / tl.beat_len))]
    for i, t in enumerate(beats):
        mx.hit("808bd", t, i=1, gain_db=-3)
        if i % 2 == 1:
            mx.hit("cp", t, gain_db=-10, pan=0.1)
    for k in range(int(LOOP / (tl.beat_len / 2))):
        mx.hit("808hc", tl.step(k, 2), gain_db=-18 + 3 * (k % 2), pan=-0.2)
    chords = [["A3", "C4", "E4"], ["F3", "A3", "C4"], ["G3", "C4", "E4"], ["G3", "B3", "D4"], ["F3", "A3", "C4"],
              ["G3", "B3", "D4"]]
    roots = ["A1", "F1", "C2", "G1", "F1", "G1"]
    mx.instrument([(tl.bar(b), tl.bar_len * 0.98, n, 76) for b, ch in enumerate(chords) for n in ch],
                  patch="Pads/MKS-70 Warm Pad", bus="pad", gain_db=-7)
    mx.instrument([(tl.step(k, 2), tl.beat_len * 0.42, roots[int(tl.bar_at(tl.step(k, 2)))], 108)
                   for k in range(int(LOOP / (tl.beat_len / 2))) if k % 2 == 1], patch="Basses/Bass 1", bus="bass",
                  gain_db=4)
    arp = []
    for k in range(int(T_WAYS / (tl.beat_len / 4)), int(9.0 / (tl.beat_len / 4))):
        t = tl.step(k, 4)
        ch = chords[int(tl.bar_at(t))]
        arp.append((t, tl.beat_len / 4 * 0.8, audio.midi(ch[[0, 1, 2, 1][k % 4]]) + 24, 105 if k % 4 == 0 else 78))
    mx.instrument(arp, patch="Plucks/Clean", bus="arp", gain_db=-13)
    mx.fx("pad", pb.HighpassFilter(cutoff_frequency_hz=180), pb.Reverb(room_size=0.8, wet_level=0.3))
    mx.fx("arp", pb.HighpassFilter(cutoff_frequency_hz=300),
          pb.Delay(delay_seconds=tl.beat_len * 0.75, feedback=0.3, mix=0.22), pb.Reverb(room_size=0.5, wet_level=0.2))
    mx.fx("bass", pb.HighpassFilter(cutoff_frequency_hz=35), pb.LowpassFilter(cutoff_frequency_hz=900))
    # UI の音: 入力、選択、下線、信号の到着
    for k in range(len(QUERY)):
        mx.sfx(sfx.click(3200 + (k % 3) * 300, pan=-0.2 + 0.4 * (k % 2)), T_TYPE + k / TYPE_RATE, gain_db=-17)
    mx.sfx(sfx.click(1800, 0.06), T_SELECT, gain_db=-11)
    mx.sfx(sfx.whoosh(0.6, rise=0.6, seed=1), T_FLIP + 0.35, gain_db=-12)
    mx.sfx(sfx.click(2600, 0.1), T_UNDERLINE, gain_db=-9)
    for i, t in enumerate(ARRIVE):
        mx.hit(["808lt", "808mt", "808ht"][i], t, gain_db=-4, pan=-0.3 + 0.3 * i)
        mx.sfx(sfx.whoosh(0.4, rise=0.95, f0=400, f1=5000, seed=10 + i), t, gain_db=-15)
        mx.sfx(sfx.click(2200 + 400 * i, 0.1), t, gain_db=-8)
    mx.sfx(sfx.impact(1.0, noise=0.3), ARRIVE[-1], gain_db=-8)
    mx.sfx(sfx.reverse_swell(0.8), T_WORDMARK, gain_db=-14)
    mx.sfx(sfx.whoosh(0.7, seed=4), T_BACK + 0.4, gain_db=-13)
    mx.duck("pad", beats, -9)
    mx.duck("arp", beats, -4)
    mx.fx("drums", pb.Compressor(threshold_db=-14, ratio=3), pb.Reverb(room_size=0.2, wet_level=0.06))
    mx.fx("sfx", pb.Reverb(room_size=0.5, wet_level=0.15))
    return mx.render(f"{comp.build_dir}/audio.wav", lufs=-14, loop=True)
