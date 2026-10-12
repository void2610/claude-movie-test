import manimgx as m

from motion import mgx


class Dot(m.Scene):
    def construct(self) -> None:
        dot = m.Dot(radius=mgx.params().get("radius", 1.0), color=m.YELLOW)
        self.play(m.FadeIn(dot), run_time=0.4)
        self.wait(0.2)
