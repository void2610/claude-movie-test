"""ゲームの devlog の見本。偽のゲーム映像 (tests/fixtures/fakegame) を素材に、キャプチャ編集の機能を一通り使う。

    uv run python -m motion render projects/devlog                      # 16:9
    uv run python -m motion render projects/devlog --set aspect=9:16    # Shorts / Reels 用の縦長
"""
import math
from pathlib import Path

import pedalboard as pb

from motion import Composition, audio, cache, draw, easing, overlay, post, scene, sfx, text
from motion.anim import clamp, impact, progress, spring, tween
from motion.edit import Sequence, Shot, blur_fill, compare, cut_on_beats
from motion.footage import Clip, Footage, Grade, TimeMap
from motion.overlay import Captions, Cue
from motion.scan import scan
from motion.transition import Transition

ROOT = Path(__file__).resolve().parents[2]
NEW = ROOT / "assets/footage/fakegame_new.mp4"
OLD = ROOT / "assets/footage/fakegame_old.mp4"

GAME = "STARFALL"
ACCENT = "#7CF7FF"
WARM = "#FFB347"

# タイミング (秒)
T_CMP = 2.5          # 比較スライダー
T_DASH = 8.0         # ダッシュの紹介
DASH_SRC = 2.0       # 素材内のダッシュ紹介の開始位置 (3.0 秒にダッシュ)
T_MONT = 14.0        # モンタージュ
T_END = 20.0         # エンドカード
DUR = 24.0

GRADE = Grade(saturation=1.12, contrast=1.06)


def ensure_footage() -> None:
    """素材が無ければテスト用の偽ゲームを書き出す (assets/footage は git 管理外)。"""
    if NEW.exists() and OLD.exists():
        return
    import os

    from motion.render import render_video
    fixture = ROOT / "tests/fixtures/fakegame"
    NEW.parent.mkdir(parents=True, exist_ok=True)
    saved = os.environ.pop("MOTION_PARAMS", None)
    render_video(fixture, NEW, codec="hw")
    os.environ["FAKEGAME"] = "old"
    render_video(fixture, OLD, codec="hw")
    del os.environ["FAKEGAME"]
    if saved:
        os.environ["MOTION_PARAMS"] = saved


def player_src(t):
    """素材内の時刻 t の自機の位置 (素材の画素)。偽ゲームの動きの式と同じ。"""
    return (960 + 520 * math.sin(t * 0.7) + 120 * math.sin(t * 2.3), 760 + 90 * math.sin(t * 1.1))


def build(aspect: str = "16:9") -> Composition:
    ensure_footage()
    vertical = aspect == "9:16"
    W, H = (1080, 1920) if vertical else (1920, 1080)
    comp = Composition(width=W, height=H, duration=DUR, bpm=120, background="#05070F", motion_blur=2,
                       shutter=0.5)
    tl = comp.timeline
    new, old = Footage(NEW), Footage(OLD)
    comp.prepare += [new.prepare, old.prepare]

    # 素材を見せる枠: 横長は全面、縦長は中央に横長の枠を置き、周りをぼかした映像で埋める
    if vertical:
        bw = W - 64
        BOX = (32, (H - bw * 9 / 16) / 2 - 80, bw, bw * 9 / 16)
    else:
        BOX = (0, 0, W, H)
    S = W / 1920 if not vertical else 1.0

    def show(c, ctx, clip, **kw):
        if vertical:
            blur_fill(c, ctx, clip, box=BOX, grade=GRADE, **kw)
        else:
            clip.draw(c, ctx, *BOX, grade=GRADE, **kw)

    def to_canvas(sx, sy, zoom=1.0, focus=(0.5, 0.5)):
        """素材の画素座標を、BOX に cover で描いたときのキャンバス座標に変換する。"""
        bx, by, bw, bh = BOX
        k = bw / 1920
        vw, vh = 1920 / zoom, 1080 / zoom
        ox, oy = (1920 - vw) * focus[0], (1080 - vh) * focus[1]
        return bx + (sx - ox) * zoom * k, by + (sy - oy) * zoom * k

    # ---------------------------------------------------------------- タイトル
    title_bg = Clip(new, at=0.0, src_in=12.0, src_out=15.0)

    @scene(0, T_CMP + 0.25)
    def title(c, ctx):
        c.save()
        p = draw.paint("#000000")
        p.setImageFilter(__import__("skia").ImageFilters.Blur(30, 30))
        c.saveLayer(None, p)
        title_bg.draw(c, ctx, fit="cover", zoom=1.1, grade=Grade(saturation=0.7, exposure=-0.6))
        c.restore()
        c.restore()
        cy = H * (0.42 if vertical else 0.45)
        a = progress(ctx.t, 0.1, 0.5, easing.out_expo)
        sz = 190 * (0.62 if vertical else 1.0)
        sh = text.shape("DEVLOG", "sans", sz, {"wght": 900, "wdth": 118})
        num = text.shape("#12", "sans", sz, {"wght": 900, "wdth": 118})
        total = sh.width + 30 + num.width
        x0 = (W - total) / 2
        with draw.clip_rect(c, 0, cy - sz, W, sz * 1.2):
            c.drawTextBlob(sh.blob(), x0, cy + (1 - a) * sz, draw.paint("#FFFFFF"))
            b = progress(ctx.t, 0.25, 0.65, easing.out_expo)
            c.drawTextBlob(num.blob(), x0 + sh.width + 30, cy + (1 - b) * sz, draw.paint(ACCENT))
        sub = "ダッシュと撃破エフェクト"
        n = int(len(sub) * progress(ctx.t, 0.7, 1.3))
        if n:
            text.text(c, sub[:n], W / 2, cy + 80 * (0.8 if vertical else 1), font="jp", size=56 * (0.8 if vertical else 1),
                      axes={"wght": 700}, color="#FFFFFF", align="center", valign="cap")
        overlay.badge(c, W / 2, cy - sz - 50, GAME, spring(ctx.t, 1.2, 3.0, 0.5), color=WARM, fg="#05070F",
                      size=30, angle=-4)

    # ---------------------------------------------------------------- 改修前後の比較
    cmp_new = Clip(new, at=T_CMP - 0.25, src_in=6.0, src_out=12.0)
    cmp_old = Clip(old, at=T_CMP - 0.25, src_in=6.0, src_out=12.0)

    def split_at(t):
        if t < T_CMP + 0.6:
            return 0.0 + 0.03
        if t < T_CMP + 2.0:
            return progress(t, T_CMP + 0.6, T_CMP + 2.0, easing.inout_cubic) * 0.94 + 0.03
        if t < T_CMP + 3.5:
            return 0.97 - progress(t, T_CMP + 2.4, T_CMP + 3.5, easing.inout_cubic) * 0.94
        return 0.03 + progress(t, T_CMP + 3.9, T_CMP + 4.6, easing.out_back) * 0.47

    @scene(T_CMP - 0.25, T_DASH)
    def comparison(c, ctx):
        if vertical:
            blur_fill(c, ctx, cmp_new, box=BOX, grade=GRADE)
        bx, by, bw, bh = BOX
        compare(c, ctx, lambda cv: cmp_old.draw(cv, ctx, *BOX, grade=GRADE),
                lambda cv: cmp_new.draw(cv, ctx, *BOX, grade=GRADE), split_at(ctx.t),
                labels=("v0.3.1  BEFORE", "v0.4.0  AFTER"), accent=ACCENT, x=bx, y=by, w=bw, h=bh,
                label_y=bh * 0.11)

    # ---------------------------------------------------------------- ダッシュの紹介
    dash_tm = TimeMap().play(0.9).ramp(0.6, 1.0, 0.12).hold(1.6).ramp(0.5, 0.12, 1.0).play(2.4)
    dash = Clip(new, at=T_DASH, src_in=DASH_SRC, time=dash_tm, interp="flow")
    T_FREEZE = T_DASH + 0.9 + 0.6
    freeze_src = dash.src_time(T_FREEZE + 0.1)
    fx, fy = player_src(freeze_src)
    focus = (fx / 1920, fy / 1080)

    def dash_zoom(t):
        return 1 + 0.6 * progress(t, T_DASH + 0.9, T_FREEZE, easing.inout_cubic) * \
            (1 - progress(t, T_FREEZE + 1.6, T_FREEZE + 2.1, easing.inout_cubic))

    @scene(T_DASH, T_MONT)
    def dash_scene(c, ctx):
        show(c, ctx, dash, zoom=dash_zoom, focus=focus)
        z = dash_zoom(ctx.t)
        px, py = to_canvas(*player_src(dash.src_time(ctx.t)), z, focus)
        hp = progress(ctx.t, T_FREEZE, T_FREEZE + 0.35) * (1 - progress(ctx.t, T_FREEZE + 1.6, T_FREEZE + 1.9))
        r = 120 * z * (BOX[2] / 1920)
        overlay.highlight(c, ctx, (px - r, py - r, 2 * r, 2 * r), hp, color=ACCENT, circle=True, dim=0.45)
        cp = progress(ctx.t, T_FREEZE + 0.15, T_FREEZE + 0.8) * (1 - progress(ctx.t, T_FREEZE + 1.6, T_FREEZE + 1.8))
        if cp > 0:
            side = 1 if px < W * 0.6 else -1
            off = (side * (220 if not vertical else 140), -200 if not vertical else -240)
            # 強調の円の縁のうち、ラベルのある斜め上側を指す
            ang = math.radians(-45 if side > 0 else -135)
            target = (px + math.cos(ang) * r, py + math.sin(ang) * r)
            overlay.callout(c, target, "DASH", cp, offset=off, color=ACCENT, sub="無敵 0.35 秒",
                            size=44 if not vertical else 36)
        overlay.lower_third(c, ctx, "NEW ACTION", "Shift でダッシュ", T_DASH + 0.3, T_FREEZE - 0.1,
                            accent=ACCENT, x=80 if not vertical else 48, y=(H - 260) if not vertical else BOX[1] + BOX[3] + 60,
                            size=48 if not vertical else 40)
        # スロー中は画面の端に速度を出す
        spd = dash_tm.speed(min(max(ctx.t - T_DASH, 0), dash_tm.duration))
        if spd < 0.95:
            label = "FREEZE" if spd < 0.02 else f"x{spd:.2f}"
            text.text(c, label, BOX[0] + BOX[2] - 40, BOX[1] + 70, font="mono", size=34, color=ACCENT,
                      align="right", valign="cap")

    # ---------------------------------------------------------------- 見せ場のモンタージュ
    def find():
        res = scan(NEW)
        return {"starts": [m.start for m in res.highlights(6, length=1.0, gap=0.5)]}

    starts = list(cache.cached(comp, "highlights", find, str(NEW), NEW.stat().st_mtime)["starts"])
    shots = [Shot(new, s) for s in starts]
    mont = Sequence(cut_on_beats(shots, start=T_MONT, beat_len=tl.beat_len, beats=2), punch=0.08, grade=GRADE)
    if vertical:
        clips = mont.clips

        @scene(T_MONT, T_END)
        def montage(c, ctx):
            clip = next((cl for cl in clips if cl.at <= ctx.t < cl.end), clips[-1])
            blur_fill(c, ctx, clip, box=BOX, grade=GRADE, zoom=1 + 0.08 * impact(ctx.t, [clip.at], 9))
    else:
        montage = mont

    @scene(T_MONT, T_END, z=3)
    def montage_text(c, ctx):
        i = int((ctx.t - T_MONT) / tl.beat_len / 2)
        words = ["BLAST", "DASH", "DODGE", "CHAIN", "BURST", "CLEAR"]
        if i < len(words):
            t0 = T_MONT + i * tl.beat_len * 2
            p = progress(ctx.t, t0, t0 + 0.2, easing.out_expo)
            sz = 150 if not vertical else 110
            y = BOX[1] + BOX[3] * 0.82 if not vertical else BOX[1] - 120
            text.text(c, words[i], W / 2, y, size=sz * (1.15 - 0.15 * p), axes={"wght": 900, "wdth": 120},
                      color="#FFFFFF", align="center", valign="cap", alpha=p * 0.95)

    # ---------------------------------------------------------------- エンドカード
    end_bg = Clip(new, at=T_END - 0.25, src_in=15.0, src_out=20.0)

    @scene(T_END - 0.25, DUR)
    def endcard(c, ctx):
        p = draw.paint("#000000")
        p.setImageFilter(__import__("skia").ImageFilters.Blur(24, 24))
        c.saveLayer(None, p)
        end_bg.draw(c, ctx, fit="cover", zoom=1.15, grade=Grade(saturation=0.6, exposure=-0.9))
        c.restore()
        cy = H * 0.44
        a = spring(ctx.t, T_END, 2.8, 0.55)
        sz = 220 if not vertical else 150
        c.save()
        c.translate(W / 2, cy)
        c.scale(0.7 + 0.3 * a, 0.7 + 0.3 * a)
        c.translate(-W / 2, -cy)
        text.text(c, GAME, W / 2, cy, size=sz, axes={"wght": 900, "wdth": 125}, color="#FFFFFF", align="center",
                  valign="cap", alpha=clamp(a * 1.5))
        c.restore()
        draw.line(c, W / 2 - 300 * progress(ctx.t, T_END + 0.2, T_END + 0.7, easing.out_expo), cy + sz * 0.62,
                  W / 2 + 300 * progress(ctx.t, T_END + 0.2, T_END + 0.7, easing.out_expo), cy + sz * 0.62, WARM, 4)
        b = progress(ctx.t, T_END + 0.5, T_END + 0.9, easing.out_expo)
        text.text(c, "Wishlist on Steam", W / 2, cy + sz * 0.62 + 90, size=60 if not vertical else 50,
                  axes={"wght": 800}, color=WARM, align="center", valign="cap", alpha=b)
        text.text(c, "build 0.4.0  ·  2026.10", W / 2, cy + sz * 0.62 + 170, font="mono", size=28,
                  color="#9AA3C0", align="center", valign="cap", alpha=progress(ctx.t, T_END + 0.8, T_END + 1.2))

    caps = Captions([
        Cue(0.6, 2.3, "今週の進捗: ダッシュと撃破エフェクト"),
        Cue(T_CMP + 0.2, T_CMP + 2.9, "敵を倒したときに、破片とリングのエフェクトを追加"),
        Cue(T_CMP + 3.0, T_DASH - 0.2, "左が以前のビルド、右が今のビルド"),
        Cue(T_DASH + 0.2, T_FREEZE - 0.1, "新しいアクション「ダッシュ」"),
        Cue(T_FREEZE + 0.1, T_FREEZE + 2.2, "発動から 0.35 秒は無敵。弾の間をすり抜けられる"),
        Cue(T_END + 1.2, DUR - 0.3, "次回はボス戦を作ります"),
    ], size=46 if not vertical else 40, bottom=90 if not vertical else 300, width=0.8 if not vertical else 0.86)

    def camera(c, ctx):
        e = impact(ctx.t, comp.cues, 10)
        if e > 0.003:
            c.translate(8 * e * math.sin(ctx.t * 90), 8 * e * math.cos(ctx.t * 77))

    comp.cues = [T_CMP, T_FREEZE, T_MONT, T_END]
    comp.camera = camera
    comp.add(
        title, comparison, dash_scene, montage, montage_text, endcard, caps,
        Transition(title, comparison, T_CMP - 0.25, 0.5, "wipe", angle=-15, edge=8, edge_color=ACCENT),
        Transition(comparison, dash_scene, T_DASH - 0.25, 0.5, "push", direction="left"),
        Transition(montage, endcard, T_END - 0.25, 0.5, "zoom"),
    )
    comp.post = [
        post.bloom(threshold=0.7, strength=0.35, radius=22),
        post.chroma(lambda ctx: 0.5 + 5.0 * impact(ctx.t, comp.cues, 10)),
        post.flash(peak=0.18, decay=16),
        post.vignette(0.3),
        post.grain(0.018),
    ]

    def make_audio(comp):
        mx = audio.Mix(DUR)
        beats = [tl.beat(i) for i in range(int(DUR / tl.beat_len))]
        for i, t in enumerate(beats):
            if 0.0 <= t < T_END or t == T_END:
                mx.hit("808bd", t, i=1, gain_db=-3 if t >= T_MONT else -6)
                if i % 2 == 1 and t >= T_CMP:
                    mx.hit("cp", t, gain_db=-11)
        for k in range(int(DUR / (tl.beat_len / 2))):
            t = tl.step(k, 2)
            if T_CMP <= t < T_END and not (T_FREEZE <= t < T_FREEZE + 1.6):
                mx.hit("808hc", t, gain_db=-18 + 3 * (k % 2), pan=-0.2)
        roots = ["D2", "A#1", "F1", "C2"]
        chords = [["D3", "F3", "A3"], ["A#2", "D3", "F3"], ["F3", "A3", "C4"], ["C3", "E3", "G3"]]
        nb = int(DUR / tl.bar_len)
        mx.instrument([(tl.bar(b), tl.bar_len * 0.98, n, 75) for b in range(nb) for n in chords[b % 4]],
                      patch="Pads/MKS-70 Warm Pad", bus="pad", gain_db=-9)
        mx.instrument([(tl.step(k, 2), tl.beat_len * 0.4, roots[int(tl.bar_at(tl.step(k, 2))) % 4], 105)
                       for k in range(int(DUR / (tl.beat_len / 2))) if k % 2 == 1 and T_CMP <= tl.step(k, 2) < T_END],
                      patch="Basses/Bass 1", bus="bass", gain_db=2)
        mx.fx("pad", pb.HighpassFilter(cutoff_frequency_hz=180), pb.Reverb(room_size=0.7, wet_level=0.3))
        mx.fx("bass", pb.LowpassFilter(cutoff_frequency_hz=900))
        # ゲーム音: スローの区間では音も伸びて低くなる
        mx.clip(cmp_new, gain_db=-10, bus="game")
        mx.clip(dash, gain_db=-6, bus="game")
        for cl in mont.clips:
            mx.clip(cl, gain_db=-8, bus="game")
        for t in (T_CMP, T_DASH, T_END):
            mx.sfx(sfx.whoosh(0.6, seed=int(t)), t, gain_db=-10)
        mx.sfx(sfx.reverse_swell(0.8), T_FREEZE, gain_db=-12)
        mx.sfx(sfx.impact(1.2), T_FREEZE, gain_db=-6)
        mx.sfx(sfx.riser(1.6), T_MONT, gain_db=-12)
        mx.sfx(sfx.impact(1.0), T_MONT, gain_db=-6)
        mx.sfx(sfx.impact(1.6), T_END, gain_db=-5)
        mx.duck("pad", beats, -8)
        mx.duck("game", beats, -3)
        mx.fx("drums", pb.Compressor(threshold_db=-14, ratio=3))
        return mx.render(f"{comp.build_dir}/audio.wav", lufs=-14)

    comp.audio = make_audio
    return comp
