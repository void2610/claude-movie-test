"""エンジンの機能を一通り使うデモ。9 秒・120 BPM・4 小節 + エンドカード半小節。"""
import math

import numpy as np
import pedalboard as pb

from motion import Composition, Palette, Scene, anim, audio, cache, draw, easing, noise, post, scene, sfx, text
from motion.anim import impact, progress, spring, stagger, tween, window
from motion.transition import Transition

BPM = 120
pal = Palette(bg="#0C0C0F", paper="#F2EEE6", orange="#FF5A1F", blue="#3044FF", grey="#8A8A8F")
# シーン間のトランジションの長さ (秒)。小節頭をまたいで前後に半分ずつ
XF = 0.5


def build() -> Composition:
    comp = Composition(duration=9.0, bpm=BPM, background=pal.bg, motion_blur=4, shutter=0.5)
    tl = comp.timeline
    B = tl.bar

    # ボールの着地と小節頭を衝撃キューにして、カメラ・ポスト・音で共有する
    landings = [tl.beat(1), tl.beat(2), tl.beat(3)]
    comp.cues = sorted(landings + [B(1), B(2), B(3), B(4)])

    def ball_y(b, floor):
        i = int(b)
        ph = b - i
        return floor - 40 - 420 * (0.75 ** i) * 4 * ph * (1 - ph)

    @scene(B(0), B(1))
    def bounce(c, ctx):
        floor = ctx.CY + 160
        x0, x1 = ctx.W * 0.22, ctx.W * 0.78
        draw.line(c, x0 - 80, floor, x1 + 260, floor, pal.grey, 2, alpha=tween(ctx.t, 0, 0.4, 0, 0.6))
        # 拍ごとの放物線。着地直後だけ潰れて、離陸で伸びる
        b = max(tl.beat_at(ctx.t), 0.0)
        ph = b - int(b)
        x = anim.remap(b, 0, 4, x0, x1, clip=False)
        squash = impact(ctx.t, landings, 22)
        vy = abs(1 - 2 * ph)
        sx = 1 + 0.45 * squash - 0.15 * vy * (1 - squash)
        sy = 1 - 0.38 * squash + 0.22 * vy * (1 - squash)
        r = 40
        for k in range(6, 0, -1):
            bb = tl.beat_at(ctx.t - k * 0.035)
            if bb >= 0:
                draw.circle(c, anim.remap(bb, 0, 4, x0, x1, clip=False), ball_y(bb, floor), r * (1 - k * 0.1),
                            pal.orange, alpha=0.12 * (7 - k) / 6)
        with draw.transform(c, x, ball_y(b, floor) + r * (1 - sy), sx=sx, sy=sy):
            draw.circle(c, 0, 0, r, pal.orange)

    @scene(B(1), B(2))
    def kinetic(c, ctx):
        t0 = B(1)
        size = 260
        sh = text.shape("MOTION", "sans", size, {"wght": 900, "wdth": 125})
        ox, oy = text.origin(sh, ctx.CX, ctx.CY, "center", "cap")
        letters = sh.letters()
        for i, (ch, lx, lw, gi) in enumerate(letters):
            s0, s1 = stagger(i, len(letters), t0, t0 + 0.6, 0.35)
            pin = progress(ctx.t, s0, s1, easing.out_expo)
            # 拍ごとにウェイトと幅が波打つ
            wave = 0.5 + 0.5 * math.sin(2 * math.pi * (tl.beat_at(ctx.t) * 0.5 - i * 0.12))
            axes = {"wght": 200 + 700 * wave, "wdth": 75 + 50 * (1 - wave)}
            gsh = text.shape(ch, "sans", size, axes)
            lx2 = ox + lx + (lw - gsh.width) / 2
            with draw.clip_rect(c, lx2 - 20, oy - size, gsh.width + 40, size * 1.25):
                col = pal.paper if i % 2 == 0 else pal.orange
                c.drawTextBlob(gsh.blob(), lx2, oy + (1 - pin) * 220, draw.paint(col))
        text.text(c, "EVERY FRAME IS CODE", ctx.CX, ctx.CY + 210, font="mono", size=22, color=pal.grey,
                  align="center", tracking=0.3, alpha=progress(ctx.t, t0 + 0.5, t0 + 0.8))

    @scene(B(2), B(3))
    def grid(c, ctx):
        cell = 54
        cols, rows = int(ctx.W / cell) + 2, int(ctx.H / cell) + 2
        xs = (np.arange(cols) - cols / 2 + 0.5) * cell + ctx.CX
        ys = (np.arange(rows) - rows / 2 + 0.5) * cell + ctx.CY
        X, Y = np.meshgrid(xs, ys)
        d = np.hypot(X - ctx.CX, Y - ctx.CY) / 700
        n = noise.perlin3(X / 300, Y / 300, np.full_like(X, ctx.t * 0.8))
        # 拍ごとに中心から外側へ広がる波
        lb = tl.beat_at(ctx.t) - tl.beat_at(B(2))
        ring = np.exp(-((d - (lb % 1.0) * 1.4) ** 2) * 40)
        # トランジションの最中から中心付近は見えているようにする
        appear = np.clip(ctx.lt * 3.0 + 0.5 - d, 0, 1)
        r = (5 + 16 * ring + 5 * n) * appear
        for j in range(rows):
            for i in range(cols):
                if r[j, i] < 0.4:
                    continue
                col = pal.blue if ring[j, i] > 0.5 else (pal.orange if n[j, i] > 0.35 else pal.paper)
                draw.rect(c, X[j, i], Y[j, i], r[j, i] * 2, r[j, i] * 2, col, r=r[j, i] * 0.4, center=True)

    class Particles(Scene):
        N = 5000
        HZ = 240

        def setup(self, comp):
            def simulate():
                rng = np.random.default_rng(7)
                a = rng.uniform(0, 2 * math.pi, self.N)
                rad = 260 * np.sqrt(rng.uniform(0, 1, self.N))
                p = np.stack([comp.width / 2 + rad * np.cos(a), comp.height / 2 + rad * np.sin(a)], 1)
                steps = int((self.end - self.start) * self.HZ) + 2
                traj = np.zeros((steps, self.N, 2), np.float32)
                dt = 1 / self.HZ
                for k in range(steps):
                    traj[k] = p
                    vx, vy = noise.curl2(p[:, 0], p[:, 1], k * dt * 0.6, scale=1 / 380, seed=3)
                    # 中心からの外向き成分を少し足して、花火のように開かせる
                    ox, oy = p[:, 0] - comp.width / 2, p[:, 1] - comp.height / 2
                    rr = np.hypot(ox, oy) + 1
                    p = p + np.stack([vx * 520 + ox / rr * 90, vy * 520 + oy / rr * 90], 1) * dt
                return {"traj": traj, "hue": rng.uniform(0, 1, self.N)}

            data = cache.cached(comp, "particles", simulate, self.N, self.HZ, self.start, self.end)
            self.traj, self.hue = data["traj"], data["hue"]

        def draw(self, c, ctx):
            k = ctx.lt * self.HZ
            k0 = min(int(k), len(self.traj) - 2)
            f = k - k0
            p = self.traj[k0] * (1 - f) + self.traj[k0 + 1] * f
            # エンドカードの前に粒子を引かせて、文字だけを残す
            fade = 1 - progress(ctx.t, B(4) - 0.4, B(4) + 0.1, easing.in_cubic)
            groups = [(self.hue < 0.55, pal.paper), ((self.hue >= 0.55) & (self.hue < 0.8), pal.orange),
                      (self.hue >= 0.8, pal.blue)]
            if fade > 0:
                for m, col in groups:
                    pt = draw.paint(col, stroke=3.4, alpha=0.9 * fade, blend="screen")
                    c.drawPoints(c.kPoints_PointMode, [tuple(v) for v in p[m]], pt)

    @scene(B(3) + 0.8, None, z=5)
    def endcard(c, ctx):
        word = progress(ctx.t, ctx.start, ctx.start + 0.4, easing.out_expo)
        pop = spring(ctx.t, B(4), freq=3.5, damping=0.35)
        lift = tween(ctx.t, B(4), B(4) + 0.5, 0, -50, easing.out_expo)
        sz = 150 * (0.9 + 0.1 * word) * (1 + 0.06 * (1 - pop) * (ctx.t >= B(4)))
        text.text(c, "ENGINE.", ctx.CX, ctx.CY + lift, size=sz, axes={"wght": 900, "wdth": 125},
                  color=pal.paper, align="center", valign="cap", alpha=word)
        sub = "すべてのフレームは、コードでできている。"
        # 1 文字ずつタイプされていく
        n = int(len(sub) * progress(ctx.t, B(4) + 0.1, B(4) + 0.6))
        if n > 0:
            text.text(c, sub[:n], ctx.CX - text.shape(sub, "jp", 34).width / 2, ctx.CY + 80, font="jp", size=34,
                      axes={"wght": 500}, color=pal.paper, valign="cap")
        rule = progress(ctx.t, B(4), B(4) + 0.5, easing.out_expo)
        if rule > 0:
            draw.line(c, ctx.CX - 260 * rule, ctx.CY + 140, ctx.CX + 260 * rule, ctx.CY + 140, pal.orange, 3)

    @scene(0, None, z=10, fixed=True)
    def hud(c, ctx):
        m, L = 44, 22
        col = pal.grey
        for sx, sy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
            x = m if sx > 0 else ctx.W - m
            y = m if sy > 0 else ctx.H - m
            draw.poly(c, [(x, y + sy * L), (x, y), (x + sx * L, y)], col, stroke=2, cap="square")
        text.text(c, "MOTION ENGINE  ·  DEMO", m + 34, m + 18, font="mono", size=16, color=col, valign="cap")
        tc = f"{int(ctx.t // 60):02d}:{int(ctx.t % 60):02d}:{int((ctx.t % 1) * comp.fps):02d}"
        text.text(c, f"{BPM} BPM  ·  {comp.fps} FPS", ctx.W - m - 34, m + 18, font="mono", size=16, color=col,
                  align="right", valign="cap")
        text.text(c, tc, m + 34, ctx.H - m - 18, font="mono", size=16, color=col, valign="cap")
        total = math.ceil(comp.duration / tl.bar_len)
        text.text(c, f"BAR {int(tl.bar_at(ctx.t)) + 1:02d} / {total:02d}", ctx.W - m - 34, ctx.H - m - 18,
                  font="mono", size=16, color=col, align="right", valign="cap")
        # 拍で点滅するインジケータ
        draw.circle(c, ctx.W / 2, ctx.H - m - 18, 4, pal.orange, alpha=0.3 + 0.7 * tl.pulse(ctx.t, 8))

    def camera(c, ctx):
        e = impact(ctx.t, comp.cues, 10)
        if e > 0.002:
            sx = noise.noise1(ctx.t * 30, 1) * 14 * e
            sy = noise.noise1(ctx.t * 30, 2) * 14 * e
            z = 1 + 0.02 * e
            c.translate(ctx.CX + sx, ctx.CY + sy)
            c.scale(z, z)
            c.translate(-ctx.CX, -ctx.CY)

    particles = Particles(B(3), comp.duration)
    comp.camera = camera
    comp.add(
        bounce, kinetic, grid, particles, endcard, hud,
        Transition(bounce, kinetic, B(1) - XF / 2, XF, "iris", cx=comp.width * 0.78 + 80, cy=comp.height / 2 + 120),
        Transition(kinetic, grid, B(2) - XF / 2, XF, "slices", n=10),
        Transition(grid, particles, B(3) - XF / 2, XF, "zoom"),
    )
    comp.post = [
        post.bloom(threshold=0.7, strength=0.5, radius=28),
        post.chroma(lambda ctx: 1.0 + 7.0 * impact(ctx.t, comp.cues, 9)),
        post.flash(peak=0.12, decay=20),
        post.vignette(0.35),
        post.grain(0.03),
    ]
    comp.audio = make_audio
    return comp


def make_audio(comp: Composition) -> str:
    tl = comp.timeline
    mx = audio.Mix(comp.duration)
    end = tl.bar(4)
    beats = [tl.beat(i) for i in range(16)]
    for i, t in enumerate(beats):
        mx.hit("808bd", t, i=1, gain_db=-2)
        if i % 2 == 1:
            mx.hit("cp", t, i=0, gain_db=-8, pan=0.1)
    # ハイハットはドロップ前の半小節で抜いて溜めを作る
    for k in range(32):
        if tl.step(k, 2) < end - tl.bar_len / 2:
            mx.hit("808hc", tl.step(k, 2), i=0, gain_db=-16 + (3 if k % 2 else 0), pan=-0.25)
    for t in comp.cues:
        mx.hit("808cy", t, i=0, gain_db=-14, pan=0.3)

    # Fm の i - iv - VII - VI、最後の半小節で i に戻る
    roots = ["F1", "A#1", "D#1", "C#1"]
    chords = [["F3", "G#3", "C4"], ["F3", "A#3", "C#4"], ["D#3", "G3", "A#3"], ["C#3", "F3", "G#3"]]
    bass = [(tl.step(i * 2 + 1, 2), tl.beat_len * 0.42, roots[i // 4], 110) for i in range(16)]
    bass.append((end, 0.9, "F1", 120))
    mx.instrument(bass, patch="Basses/Bass 1", bus="bass", gain_db=5)
    mx.fx("bass", pb.HighpassFilter(cutoff_frequency_hz=35), pb.LowpassFilter(cutoff_frequency_hz=900))

    pad = [(tl.bar(i), tl.bar_len * 0.98, n, 80) for i, ch in enumerate(chords) for n in ch]
    pad += [(end, comp.duration - end, n, 90) for n in ("F3", "G#3", "C4", "F4")]
    mx.instrument(pad, patch="Pads/MKS-70 Warm Pad", bus="pad", gain_db=-5)
    mx.fx("pad", pb.HighpassFilter(cutoff_frequency_hz=180), pb.Reverb(room_size=0.75, wet_level=0.3))

    # 2 小節目から和音を 1 オクターブ上で 16 分アルペジオにする
    arp = []
    for k in range(16, 64):
        ch = chords[k // 16]
        n = audio.midi(ch[[0, 1, 2, 1][k % 4]]) + 12 + (12 if k % 8 >= 4 else 0)
        arp.append((tl.step(k, 4), tl.beat_len / 4 * 0.8, n, 110 if k % 4 == 0 else 80))
    mx.instrument(arp, patch="Plucks/Clean", bus="arp", gain_db=-12)
    mx.fx("arp", pb.HighpassFilter(cutoff_frequency_hz=300), pb.Delay(delay_seconds=tl.beat_len * 0.75,
          feedback=0.3, mix=0.25), pb.Reverb(room_size=0.5, wet_level=0.2))

    # トランジションの中心に whoosh の頂点、ドロップに向けて riser、ドロップで impact
    for i, t in enumerate((tl.bar(1), tl.bar(2), tl.bar(3))):
        mx.sfx(sfx.whoosh(0.7, seed=i), t, gain_db=-10)
    mx.sfx(sfx.riser(1.5), end, gain_db=-12)
    mx.sfx(sfx.impact(), end, gain_db=-4)
    mx.sfx(sfx.reverse_swell(0.6), end, gain_db=-14)

    mx.duck("pad", beats, -10)
    mx.duck("arp", beats, -4)
    mx.duck("bass", beats, -6, 0.12)
    mx.fx("drums", pb.Compressor(threshold_db=-14, ratio=3), pb.Reverb(room_size=0.2, wet_level=0.08))
    mx.fx("sfx", pb.Reverb(room_size=0.6, wet_level=0.2))
    return mx.render(f"{comp.build_dir}/audio.wav", lufs=-14)
