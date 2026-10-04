"""テスト用の小さな作品。図形・文字・ノイズ・ポスト処理・カメラを一通り通す。"""
import numpy as np

from motion import Composition, draw, easing, noise, post, scene, text
from motion.anim import progress, tween


def build() -> Composition:
    comp = Composition(width=320, height=180, fps=30, duration=2.0, bpm=120, background="#101014",
                       motion_blur=3, cues=[0.5, 1.0])

    @scene(0, 2)
    def shapes(c, ctx):
        x = tween(ctx.t, 0, 2, 40, 280, easing.inout_cubic)
        draw.circle(c, x, 90, 20, "#FF5A1F")
        draw.rect(c, 160, 40, 60, 20, "#3044FF", r=6, center=True)
        n = noise.perlin2(np.linspace(0, 3, 10), np.full(10, ctx.t))
        for i, v in enumerate(n):
            draw.rect(c, 20 + i * 28, 150 - v * 20, 10, 10, "#F2EEE6")

    @scene(0.5, 2, z=1)
    def title(c, ctx):
        a = progress(ctx.t, 0.5, 1.0, easing.out_expo)
        text.text(c, "Motion", ctx.CX, 120, size=40, axes={"wght": 200 + 700 * a}, align="center", valign="cap",
                  alpha=a)

    comp.add(shapes, title)
    comp.post = [post.bloom(0.6, 0.4, 10), post.vignette(0.3), post.grain(0.02)]
    return comp
