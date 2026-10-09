"""作品を調整するブラウザのスタジオ。

    uv run python -m motion studio projects/liminal_poster

- タイムライン: ショット・カット・キュー・音の波形・メモ・レビューのエラーを並べ、クリックでシーク
- パラメータ: 作品が tune() で宣言した値をスライダー・色・文言で調整し、tune.json に保存して描き直す
- メモ: その時刻に「ここが悪い」を残す。notes.md に書かれ、Claude はそれを読んで該当箇所だけ直す
- レビュー・書き出しをボタンで実行する
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import numpy as np

from . import tune as tune_mod
from .preview import Previewer

UI = Path(__file__).with_name("studio_ui.html")
NOTE_RE = re.compile(r"^- \[( |x)\] (\d+(?:\.\d+)?)s (.*)$")
ERR_RE = re.compile(r"^- (\d+(?:\.\d+)?)s `([^`]+)`: (.*)$")


class Notes:
    """notes.md の「- [ ] 08.30s 本文」の行を読み書きする。"""

    def __init__(self, path: Path):
        self.path = path

    def load(self) -> list[dict]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            m = NOTE_RE.match(line.strip())
            if m:
                out.append({"id": len(out), "done": m.group(1) == "x", "t": float(m.group(2)), "text": m.group(3)})
        return out

    def save(self, notes: list[dict]) -> None:
        notes = sorted(notes, key=lambda n: n["t"])
        lines = ["# メモ", "", "<!-- スタジオで付けた指摘。Claude は未完了 ([ ]) の項目を、時刻の箇所だけ直して [x] にする -->", ""]
        lines += [f"- [{'x' if n['done'] else ' '}] {n['t']:.2f}s {n['text']}" for n in notes]
        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def add(self, t: float, text: str) -> None:
        notes = self.load()
        notes.append({"done": False, "t": t, "text": text.replace("\n", " ").strip()})
        self.save(notes)

    def update(self, i: int, **kw) -> None:
        notes = self.load()
        if 0 <= i < len(notes):
            if kw.get("delete"):
                notes.pop(i)
            else:
                notes[i].update({k: v for k, v in kw.items() if k in ("done", "text", "t")})
            self.save(notes)


class Job:
    """review / render をサブプロセスで走らせ、出力の最終行を進捗として見せる。"""

    def __init__(self):
        self.name = ""
        self.running = False
        self.last = ""
        self.lines: list[str] = []
        self.code: int | None = None

    def start(self, name: str, args: list[str], on_done=None) -> bool:
        if self.running:
            return False
        self.name, self.running, self.last, self.lines, self.code = name, True, "開始", [], None

        def run():
            p = subprocess.Popen([sys.executable, "-m", "motion", *args], stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True, bufsize=1)
            buf = ""
            while True:
                ch = p.stdout.read(1)
                if not ch:
                    break
                if ch in "\r\n":
                    if buf.strip():
                        self.last = buf.strip()
                        if ch == "\n":
                            self.lines.append(self.last)
                    buf = ""
                else:
                    buf += ch
            self.code = p.wait()
            self.running = False
            if on_done:
                on_done(self)

        threading.Thread(target=run, daemon=True).start()
        return True

    def info(self) -> dict:
        return {"name": self.name, "running": self.running, "last": self.last, "code": self.code}


class Studio(Previewer):
    def __init__(self, project: str, scale: float, motion_blur: bool, workers: int | None):
        super().__init__(project, scale, motion_blur, workers)
        self.notes = Notes(self.dir / "notes.md")
        self.job = Job()
        self.findings: list[dict] = self._latest_findings()
        self.peaks: list[float] = []
        self.output: str | None = None

    def _mtime(self) -> float:
        # メモの保存では描き直さない。パラメータとショットリストの変更では描き直す
        files = list(self.dir.rglob("*.py")) + [self.dir / n for n in ("tune.json", "shotlist.md")]
        return max((p.stat().st_mtime for p in files if p.exists()), default=0.0)

    def reload(self) -> None:
        super().reload()
        if self.audio_path:
            from .audio import load
            y = np.abs(load(self.audio_path).mean(axis=0))
            n = 1600
            k = max(len(y) // n, 1)
            pk = y[:k * n].reshape(-1, k).max(axis=1)
            self.peaks = [round(float(v), 3) for v in pk / (pk.max() + 1e-9)]

    def _latest_findings(self) -> list[dict]:
        mds = sorted((self.dir / "reviews").glob("*.md")) if (self.dir / "reviews").exists() else []
        if not mds:
            return []
        out, inside = [], False
        for line in mds[-1].read_text(encoding="utf-8").splitlines():
            if line.startswith("## "):
                inside = line.startswith("## エラー")
                continue
            m = ERR_RE.match(line.strip()) if inside else None
            if m:
                out.append({"t": float(m.group(1)), "rule": m.group(2), "detail": m.group(3)})
        return out

    def run_review(self) -> bool:
        return self.job.start("レビュー", ["review", self.project],
                              on_done=lambda j: setattr(self, "findings", self._latest_findings()))

    def run_render(self, draft: bool) -> bool:
        def done(j):
            m = next((ln[3:] for ln in reversed(j.lines) if ln.startswith("-> ")), None)
            self.output = m
        return self.job.start("下書き" if draft else "書き出し",
                              ["render", self.project] + (["--draft"] if draft else []), on_done=done)

    def info(self) -> dict:
        base = super().info()
        c = self.comp
        if c is None:
            return base
        shots = [{"name": s.name, "start": s.start, "end": s.end, "purpose": s.purpose} for s in (c.shots or [])]
        base.update({
            "duration": c.duration, "shots": shots, "cues": list(c.cues),
            "tune": c.tune.schema() if c.tune else [], "notes": self.notes.load(), "findings": self.findings,
            "peaks": self.peaks, "job": self.job.info(), "output": self.output, "loop": c.loop,
        })
        return base


def serve(project: str, port: int = 8766, scale: float = 0.5, motion_blur: bool = False,
          workers: int | None = None, open_browser: bool = True) -> None:
    st = Studio(project, scale, motion_blur, workers)
    threading.Thread(target=st.watch, daemon=True).start()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj, ensure_ascii=False).encode())

        def do_GET(self):
            u = urlparse(self.path)
            if u.path == "/":
                return self._send(200, UI.read_bytes(), "text/html; charset=utf-8")
            if u.path == "/info":
                return self._json(st.info())
            if u.path.startswith("/frame/"):
                jpg = st.frame(int(u.path.split("/")[-1].split(".")[0]))
                return self._send(200, jpg, "image/jpeg") if jpg else self._send(503, b"", "text/plain")
            if u.path == "/audio.wav" and st.audio_path:
                return self._send(200, Path(st.audio_path).read_bytes(), "audio/wav")
            self._send(404, b"", "text/plain")

        def do_POST(self):
            u = urlparse(self.path)
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
            if u.path == "/tune":
                if not st.comp or not st.comp.tune:
                    return self._json({"error": "この作品は tune() を使っていない"}, 400)
                return self._json(tune_mod.save(st.comp.tune.path, body))
            if u.path == "/notes/add":
                st.notes.add(float(body["t"]), str(body["text"]))
                return self._json({"ok": True})
            if u.path == "/notes/update":
                st.notes.update(int(body.pop("id")), **body)
                return self._json({"ok": True})
            if u.path == "/review":
                return self._json({"started": st.run_review()})
            if u.path == "/render":
                return self._json({"started": st.run_render(bool(body.get("draft")))})
            if u.path == "/open" and st.output:
                subprocess.run(["open", st.output])
                return self._json({"ok": True})
            self._json({"error": "not found"}, 404)

    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    url = f"http://127.0.0.1:{port}/"
    print(f"studio: {url}  (Ctrl+C で終了)", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
