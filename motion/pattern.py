"""TidalCycles / Strudel の短い記法 (mini-notation) を読み、音の時刻に直す。

    events("808bd*4, ~ cp ~ cp, 808hc*8", cycles=2)   # 1 周期 = 1 小節。重ね (,) も 1 本の列で返す

使える記法: 空白で並べて 1 周期を等分、`~` 休符、`[ ]` 細分、`< >` 周期ごとに交互、`*n` `/n` 速さ、
`,` 重ね、`(k,n[,r])` ユークリッドリズム、`!n` 繰り返し、`@n` 長さの重み、`?` `?0.3` 間引き
(シードで決まるので何度書き出しても同じ)、`bd:3` サンプルの番号。各音は元の文字列の位置を持つ
(コードを画面に出して、鳴っている語を光らせるため)。
"""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from fractions import Fraction


@dataclass(frozen=True)
class Event:
    start: Fraction              # 周期を単位にした時刻 (0 が最初の周期の頭)
    end: Fraction
    value: str
    span: tuple[int, int]        # 元の文字列の中の位置 [開始, 終了)


@dataclass
class _Node:
    kind: str                    # atom / rest / seq / stack / alt
    value: str = ""
    span: tuple[int, int] = (0, 0)
    children: list = None
    weights: list = None
    fast: Fraction = Fraction(1)
    euclid: tuple[int, int, int] | None = None
    degrade: float = 0.0
    seed: int = 0


class PatternError(ValueError):
    pass


_WORD = re.compile(r"[A-Za-z0-9#.:\-_']+")
_NUM = re.compile(r"-?\d+(?:\.\d+)?")


class _Parser:
    def __init__(self, s: str):
        self.s, self.i, self.n_degrade = s, 0, 0

    def error(self, msg: str):
        raise PatternError(f"{msg} ({self.i} 文字目): {self.s}")

    def ws(self):
        while self.i < len(self.s) and self.s[self.i].isspace():
            self.i += 1

    def peek(self) -> str:
        self.ws()
        return self.s[self.i] if self.i < len(self.s) else ""

    def number(self) -> Fraction:
        self.ws()
        m = _NUM.match(self.s, self.i)
        if not m:
            self.error("数が要る")
        self.i = m.end()
        return Fraction(m.group())

    def stack(self, close: str) -> _Node:
        """「,」で重ねた列。close は閉じ括弧 (最上位は "")。"""
        seqs = [self.seq(close)]
        while self.peek() == ",":
            self.i += 1
            seqs.append(self.seq(close))
        return seqs[0] if len(seqs) == 1 else _Node("stack", children=seqs)

    def seq(self, close: str) -> _Node:
        steps, weights = [], []
        while True:
            c = self.peek()
            if c in ("", ",") or c == close:
                break
            if c in "])>":
                self.error(f"閉じ括弧 {c} が合わない")
            if c == "!" and steps:          # 単独の「!」は直前の音をもう 1 回
                self.i += 1
                steps.append(steps[-1])
                weights.append(weights[-1])
                continue
            node, w, rep = self.step()
            steps += [node] * rep
            weights += [w] * rep
        if not steps:
            return _Node("rest")
        return _Node("seq", children=steps, weights=weights)

    def step(self) -> tuple[_Node, Fraction, int]:
        c = self.peek()
        start = self.i
        if c == "[":
            self.i += 1
            node = self.stack("]")
            if self.peek() != "]":
                self.error("] が閉じていない")
            self.i += 1
        elif c == "<":
            self.i += 1
            inner = self.stack(">")
            if self.peek() != ">":
                self.error("> が閉じていない")
            self.i += 1
            # <a b, c d> は列ごとに交互にする
            seqs = inner.children if inner.kind == "stack" else [inner]
            alts = [_Node("alt", children=(sq.children if sq.kind == "seq" else [sq])) for sq in seqs]
            node = alts[0] if len(alts) == 1 else _Node("stack", children=alts)
        elif c == "~":
            self.i += 1
            node = _Node("rest", span=(start, self.i))
        else:
            m = _WORD.match(self.s, self.i)
            if not m:
                self.error(f"読めない文字 {c!r}")
            self.i = m.end()
            node = _Node("atom", value=m.group(), span=(m.start(), m.end()))
        weight, rep = Fraction(1), 1
        while self.i < len(self.s) and self.s[self.i] in "*/!@?(":
            op = self.s[self.i]
            self.i += 1
            if op == "*":
                node = _Node("seq", children=[node], weights=[1], fast=self.number())
            elif op == "/":
                node = _Node("seq", children=[node], weights=[1], fast=1 / self.number())
            elif op == "!":
                rep = int(self.number()) if _NUM.match(self.s, self.i) else 2
            elif op == "@":
                weight = self.number()
            elif op == "?":
                prob = float(self.number()) if _NUM.match(self.s, self.i) else 0.5
                self.n_degrade += 1
                node = _Node("seq", children=[node], weights=[1], degrade=prob, seed=self.n_degrade)
            elif op == "(":
                k = int(self.number())
                self.expect(",")
                n = int(self.number())
                r = 0
                if self.peek() == ",":
                    self.i += 1
                    r = int(self.number())
                self.expect(")")
                node = _Node("seq", children=[node], weights=[1], euclid=(k, n, r))
        return node, weight, rep

    def expect(self, ch: str):
        if self.peek() != ch:
            self.error(f"{ch} が要る")
        self.i += 1


def parse(s: str) -> _Node:
    p = _Parser(s)
    node = p.stack("")
    if p.peek():
        p.error(f"余分な {p.peek()!r}")
    return node


def bjorklund(k: int, n: int, r: int = 0) -> list[bool]:
    """n 拍に k 個をなるべく均等に置く (ユークリッドリズム)。r だけ左に回す。"""
    if n <= 0:
        return []
    k = max(0, min(k, n))
    hits = [(i * k) % n < k for i in range(n)]
    r %= n
    return hits[r:] + hits[:r]


def _hash01(*xs) -> float:
    h = hashlib.sha1(repr(xs).encode()).digest()
    return int.from_bytes(h[:8], "big") / 2 ** 64


def _query(node: _Node, cycle: int) -> list[Event]:
    """cycle 番目の周期 [cycle, cycle+1) に頭が来る音。"""
    if node.kind == "rest":
        return []
    if node.kind == "atom":
        return [Event(Fraction(cycle), Fraction(cycle + 1), node.value, node.span)]
    if node.kind == "stack":
        return [e for ch in node.children for e in _query(ch, cycle)]
    if node.kind == "alt":
        n = len(node.children)
        k = cycle // n
        return [Event(e.start + cycle - k, e.end + cycle - k, e.value, e.span)
                for e in _query(node.children[cycle % n], k)]
    # seq: ユークリッド → 重みで区切った並び → 速さ → 間引き
    if node.euclid:
        k, n, r = node.euclid
        child = node.children[0]
        inner = _Node("seq", children=[child if h else _Node("rest") for h in bjorklund(k, n, r)], weights=[1] * n)
    else:
        inner = None
    f = node.fast
    out: list[Event] = []
    for c in range(math.floor(cycle * f), math.ceil((cycle + 1) * f)):
        for e in (_query(inner, c) if inner else _slots(node, c)):
            s, t = e.start / f, e.end / f
            if cycle <= s < cycle + 1:
                out.append(Event(s, t, e.value, e.span))
    if node.degrade:
        out = [e for e in out if _hash01(node.seed, e.start, e.span) >= node.degrade]
    return out


def _slots(node: _Node, cycle: int) -> list[Event]:
    total = sum(node.weights)
    out, acc = [], Fraction(0)
    for ch, w in zip(node.children, node.weights):
        a, b = acc / total, (acc + w) / total
        for e in _query(ch, cycle):
            out.append(Event(cycle + a + (e.start - cycle) * (b - a), cycle + a + (e.end - cycle) * (b - a),
                             e.value, e.span))
        acc += w
    return out


def events(s: str, cycles: int = 1, first: int = 0) -> list[Event]:
    """first 番目から cycles 周期分の音を、時刻の順に返す。"""
    node = parse(s)
    out = [e for c in range(first, first + cycles) for e in _query(node, c)]
    return sorted(out, key=lambda e: (e.start, e.span))


def sample_name(value: str) -> tuple[str, int]:
    """「808bd:3」→ ("808bd", 3)。"""
    name, _, idx = value.partition(":")
    return name, int(idx) if idx.isdigit() else 0


_NOTE_RE = re.compile(r"([A-Ga-g])([#b]?)(-?\d+)?$")


def note_number(value: str, default_octave: int = 3) -> int | None:
    """「a3」「c#4」「eb」「60」を MIDI の番号に直す (音名でも数でもなければ None)。"""
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    m = _NOTE_RE.match(value)
    if not m:
        return None
    base = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}[m.group(1).upper()]
    base += {"#": 1, "b": -1, "": 0}[m.group(2)]
    octave = int(m.group(3)) if m.group(3) is not None else default_octave
    return base + (octave + 1) * 12
