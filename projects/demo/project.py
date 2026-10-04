"""エンジンの機能を一通り使うデモ。8 秒・120 BPM・4 小節。"""
import math

import numpy as np
import pedalboard as pb

from motion import Composition, Palette, Scene, anim, audio, cache, draw, easing, noise, post, scene, text
from motion.anim import impact, progress, spring, stagger, tween, window

BPM = 120
pal = Palette(bg="#0C0C0F", paper="#F2EEE6", orange="#FF5A1F", blue="#3044FF", grey="#8A8A8F")


def build() -> Composition:
    comp = Composition(duration=8.0, bpm=BPM, background=pal.bg, motion_blur=4, shutter=0.5)
    tl = comp.timeline
    B = tl.bar

    # ボールの着地と小節頭を衝撃キューにして、カメラ・ポスト・音で共有する
    landings = [tl.beat(1), tl.beat(2), tl.beat(3)]
    comp.cues = sorted(landings + [B(1), B(2), B(3)])

    @scene(B(0), B(1))
    def bounce(c, ctx):
        floor = ctx.CY + 160
        x0, x1 = ctx.W * 0.22, ctx.W * 0.78
        draw.line(c, x0 - 80, floor, x1 + 80, floor, pal.grey, 2, alpha=tween(ctx.t, 0, 0.4, 0, 0.6))
        # 拍ごとの放物線。着地直後だけ潰れて、離陸で伸びる
        b = tl.beat_at(ctx.t)
        i = min(int(b), 3)
        ph = b - i
        h = 420 * (0.75 ** i)
        y = floor - 40 - h * 4 * ph * (1 - ph)
        x = anim.remap(b, 0, 4, x0, x1)
        squash = impact(ctx.t, landings, 22)
        vy = abs(1 - 2 * ph)
        sx = 1 + 0.45 * squash - 0.15 * vy * (1 - squash)
        sy = 1 - 0.38 * squash + 0.22 * vy * (1 - squash)
        r = 40
        with draw.transform(c, x, y + r * (1 - sy), sx=sx, sy=sy):
            draw.circle(c, 0, 0, r, pal.orange)
        for k in range(1, 7):
            tt = ctx.t - k * 0.035
            bb = tl.beat_at(tt)
            if bb < 0:
                break
            ii = min(int(bb), 3)
            pp = bb - ii
            yy = floor - 40 - 420 * (0.75 ** ii) * 4 * pp * (1 - pp)
            draw.circle(c, anim.remap(bb, 0, 4, x0, x1), yy, r * (1 - k * 0.1), pal.orange, alpha=0.12 * (7 - k) / 6)

    @scene(B(1), B(2))
    def kinetic(c, ctx):
        word = "MOTION"
        t0 = B(1)
        size = 260
        sh = text.shape(word, "sans", size, {"wght": 900, "wdth": 125})
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
            y = oy + (1 - pin) * 220
            out = progress(ctx.t, B(2) - 0.35 + i * 0.02, B(2) - 0.05 + i * 0.02, easing.in_expo)
            with draw.clip_rect(c, lx2 - 20, oy - size, gsh.width + 40, size * 1.25):
                col = pal.paper if i % 2 == 0 else pal.orange
                c.drawTextBlob(gsh.blob(), lx2, y - out * 300, draw.paint(col))
        sub = "every frame is code"
        text.text(c, sub.upper(), ctx.CX, ctx.CY + 210, font="mono", size=22, color=pal.grey, align="center",
                  tracking=0.3, alpha=window(ctx.t, t0 + 0.5, B(2), 0.3, 0.25))

    @scene(B(2), B(3))
    def grid(c, ctx):
        cell = 54
        cols, rows = int(ctx.W / cell) + 2, int(ctx.H / cell) + 2
        xs = (np.arange(cols) - cols / 2 + 0.5) * cell + ctx.CX
        ys = (np.arange(rows) - rows / 2 + 0.5) * cell + ctx.CY
        X, Y = np.meshgrid(xs, ys)
        d = np.hypot(X - ctx.CX, Y - ctx.CY) / 700
        n = noise.perlin3(X / 300, Y / 300, np.full_like(X, ctx.t * 0.8))
        # 小節頭から中心→外側へ広がる波。拍ごとに再点火する
        lb = tl.beat_at(ctx.t) - tl.beat_at(B(2))
        ring = np.exp(-((d - (lb % 1.0) * 1.4) ** 2) * 40)
        appear = np.clip((ctx.lt * 2.2 - d), 0, 1)
        r = (5 + 16 * ring + 5 * n) * appear
        leave = progress(ctx.t, B(3) - 0.3, B(3), easing.in_cubic)
        r = r * (1 - leave)
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
            fade = window(ctx.t, self.start, self.end, 0.2, 0.25)
            groups = [(self.hue < 0.55, pal.paper), ((self.hue >= 0.55) & (self.hue < 0.8), pal.orange),
                      (self.hue >= 0.8, pal.blue)]
            for m, col in groups:
                pts = [tuple(v) for v in p[m]]
                pt = draw.paint(col, stroke=3.4, alpha=0.9 * fade, blend="screen")
                c.drawPoints(c.kPoints_PointMode, pts, pt)
            word = progress(ctx.t, self.start + 0.9, self.start + 1.3, easing.out_expo)
            if word > 0:
                sz = 150 * (0.9 + 0.1 * word)
                text.text(c, "ENGINE.", ctx.CX, ctx.CY, size=sz, axes={"wght": 900, "wdth": 125},
                          color=pal.paper, align="center", valign="cap", alpha=word * fade)

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
        bar = int(tl.bar_at(ctx.t)) + 1
        text.text(c, f"BAR {bar:02d} / 04", ctx.W - m - 34, ctx.H - m - 18, font="mono", size=16, color=col,
                  align="right", valign="cap")
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

    comp.camera = camera
    comp.add(bounce, kinetic, grid, Particles(B(3), B(4)), hud)
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
    beats = [tl.beat(i) for i in range(16)]
    for i, t in enumerate(beats):
        mx.hit("808bd", t, i=1, gain_db=-2)
        if i % 2 == 1:
            mx.hit("cp", t, i=0, gain_db=-8, pan=0.1)
    for k in range(32):
        mx.hit("808hc", tl.step(k, 2), i=0, gain_db=-16 + (3 if k % 2 else 0), pan=-0.25)
    for t in comp.cues:
        mx.hit("808cy", t, i=0, gain_db=-14, pan=0.3)
    # Fm の i - iv - VII - VI。ベースは小節ごとにルートを変えて 8 分の裏で刻む
    roots = ["F1", "A#1", "D#1", "C#1"]
    chords = [["F3", "G#3", "C4"], ["F3", "A#3", "C#4"], ["D#3", "G3", "A#3"], ["C#3", "F3", "G#3"]]
    bass = [(tl.step(i * 2 + 1, 2), tl.beat_len * 0.42, roots[i // 4], 110) for i in range(16)]
    mx.instrument(bass, patch="Basses/Bass 1", bus="bass", gain_db=5)
    mx.fx("bass", pb.HighpassFilter(cutoff_frequency_hz=35), pb.LowpassFilter(cutoff_frequency_hz=900))

    pad = [(tl.bar(i), tl.bar_len * 0.98, n, 80) for i, ch in enumerate(chords) for n in ch]
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

    mx.duck("pad", beats, -10)
    mx.duck("arp", beats, -4)
    mx.duck("bass", beats, -6, 0.12)
    mx.fx("drums", pb.Compressor(threshold_db=-14, ratio=3), pb.Reverb(room_size=0.2, wet_level=0.08))
    return mx.render(f"{comp.build_dir}/audio.wav", lufs=-14)
