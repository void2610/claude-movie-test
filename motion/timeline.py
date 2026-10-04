import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Timeline:
    bpm: float = 120.0
    offset: float = 0.0
    beats_per_bar: int = 4

    @property
    def beat_len(self) -> float:
        return 60.0 / self.bpm

    @property
    def bar_len(self) -> float:
        return self.beat_len * self.beats_per_bar

    def beat(self, n: float) -> float:
        return self.offset + n * self.beat_len

    def bar(self, n: float) -> float:
        return self.offset + n * self.bar_len

    def step(self, n: float, div: int = 4) -> float:
        return self.offset + n * self.beat_len / div

    def beat_at(self, t: float) -> float:
        return (t - self.offset) / self.beat_len

    def bar_at(self, t: float) -> float:
        return (t - self.offset) / self.bar_len

    def beat_phase(self, t: float) -> float:
        b = self.beat_at(t)
        return b - math.floor(b)

    def since_beat(self, t: float, div: int = 1) -> float:
        unit = self.beat_len / div
        x = (t - self.offset) / unit
        return (x - math.floor(x)) * unit

    def pulse(self, t: float, decay: float = 10.0, div: int = 1) -> float:
        return math.exp(-decay * self.since_beat(t, div))
