"""ブラウザで確認するプレビューサーバー。

作品の .py を保存すると読み直し、全フレームを並列で先読みする。motion/ 自体を変更したときは再起動が必要。
"""
from __future__ import annotations

import json
import sys
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import cv2
import numpy as np

from .render import FrameRenderer, _pool, _render_one, load_project, make_audio, prepare

PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><title>motion preview</title>
<style>
:root{--bg:#0e0e11;--fg:#e8e6e1;--dim:#8a8a8f;--acc:#ff5a1f}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:13px ui-monospace,Menlo,monospace}
#wrap{display:flex;flex-direction:column;height:100vh;padding:12px;gap:10px}
#view{flex:1;min-height:0;display:flex;align-items:center;justify-content:center;background:#000;border-radius:6px;position:relative}
#view img{max-width:100%;max-height:100%;image-rendering:auto}
#err{position:absolute;inset:0;background:#200a;color:#ff8a7a;white-space:pre-wrap;padding:16px;overflow:auto;display:none}
#bar{display:flex;gap:10px;align-items:center}
#seek{flex:1;accent-color:var(--acc)}
button{background:#222;color:var(--fg);border:1px solid #333;border-radius:4px;padding:4px 10px;font:inherit;cursor:pointer}
#cache{height:3px;background:#222;border-radius:2px;overflow:hidden}#cache div{height:100%;background:var(--acc);width:0}
.dim{color:var(--dim)}
</style></head><body><div id="wrap">
<div id="view"><img id="img"><div id="err"></div></div>
<div id="cache"><div id="cbar"></div></div>
<div id="bar"><button id="play">▶</button><button id="prev">◀︎ 1f</button><button id="next">1f ▶︎</button>
<input id="seek" type="range" min="0" value="0"><span id="tc"></span><span id="st" class="dim"></span></div>
<div class="dim">space: 再生/停止 · ←/→: 1 フレーム · shift+←/→: 1 拍 · 作品を保存すると自動で読み直します</div>
</div><audio id="aud" preload="auto"></audio>
<script>
let info=null, ver=-1, cur=0, playing=false, inflight=false, pending=null, t0=0, f0=0;
const img=document.getElementById('img'), seek=document.getElementById('seek'), aud=document.getElementById('aud');
function fmt(f){const t=f/info.fps;return `${t.toFixed(2)}s  #${f}  bar ${(Math.floor(t/(240/info.bpm))+1)}  beat ${(Math.floor(t/(60/info.bpm))%4+1)}`}
function show(f){f=Math.max(0,Math.min(info.nframes-1,f|0));cur=f;seek.value=f;document.getElementById('tc').textContent=fmt(f);
  if(inflight){pending=f;return}inflight=true;const im=new Image();im.onload=()=>{img.src=im.src;inflight=false;if(pending!==null){const p=pending;pending=null;show(p)}};
  im.onerror=()=>{inflight=false};im.src=`/frame/${f}.jpg?v=${ver}`}
async function poll(){try{const r=await fetch('/info');const j=await r.json();
  const e=document.getElementById('err');e.style.display=j.error?'block':'none';e.textContent=j.error||'';
  document.getElementById('cbar').style.width=(100*j.cached/j.nframes)+'%';
  document.getElementById('st').textContent=`${j.name}  ${j.width}x${j.height}@${j.fps}  preview x${j.scale}  cached ${j.cached}/${j.nframes}`;
  if(j.version!==ver){const first=!info;info=j;ver=j.version;seek.max=j.nframes-1;if(j.audio){aud.src='/audio.wav?v='+ver}show(first?0:cur)}else info=j}catch(e){}
  setTimeout(poll,500)}
function tick(){if(!playing)return;const t=aud.src&&!aud.paused?aud.currentTime:(f0/info.fps+(performance.now()-t0)/1000);
  let f=Math.round(t*info.fps);if(f>=info.nframes){f=0;aud.currentTime=0;t0=performance.now();f0=0}
  if(f!==cur)show(f);requestAnimationFrame(tick)}
function toggle(){playing=!playing;document.getElementById('play').textContent=playing?'❚❚':'▶';
  if(playing){t0=performance.now();f0=cur;if(aud.src){aud.currentTime=cur/info.fps;aud.play().catch(()=>{})}requestAnimationFrame(tick)}else aud.pause()}
seek.oninput=()=>{show(+seek.value);if(playing){aud.currentTime=cur/info.fps;t0=performance.now();f0=cur}};
document.getElementById('play').onclick=toggle;
document.getElementById('prev').onclick=()=>show(cur-1);document.getElementById('next').onclick=()=>show(cur+1);
document.onkeydown=e=>{if(e.code==='Space'){e.preventDefault();toggle()}
  const step=e.shiftKey?Math.round(info.fps*60/info.bpm):1;
  if(e.code==='ArrowLeft')show(cur-step);if(e.code==='ArrowRight')show(cur+step)};
poll();
</script></body></html>"""


class Previewer:
    def __init__(self, project: str, scale: float, motion_blur: bool, workers: int | None):
        self.project = str(Path(project).resolve())
        self.dir = Path(self.project) if Path(self.project).is_dir() else Path(self.project).parent
        self.scale = scale
        self.mb = motion_blur
        self.workers = workers
        self.lock = threading.Lock()
        self.version = 0
        self.frames: dict[int, bytes] = {}
        self.error = ""
        self.comp = None
        self.renderer: FrameRenderer | None = None
        self.audio_path: str | None = None
        self.mtime = 0.0
        self._prefetch: threading.Thread | None = None
        self._stop = threading.Event()

    def _mtime(self) -> float:
        return max((p.stat().st_mtime for p in self.dir.rglob("*.py")), default=0.0)

    def reload(self, skip_audio: bool = False) -> None:
        # 作品ディレクトリ内の自作モジュールも読み直す
        for name, mod in list(sys.modules.items()):
            f = getattr(mod, "__file__", None)
            if f and Path(f).resolve().is_relative_to(self.dir):
                del sys.modules[name]
        try:
            comp = load_project(self.project)
            prepare(comp)
            renderer = FrameRenderer(comp, self.scale, self.mb)
            audio_path = self.audio_path if skip_audio else make_audio(comp)
        except Exception:
            self.error = traceback.format_exc()
            print(self.error, file=sys.stderr)
            return
        self._stop.set()
        if self._prefetch:
            self._prefetch.join()
        with self.lock:
            self.comp, self.renderer, self.audio_path = comp, renderer, audio_path
            self.frames = {}
            self.error = ""
            self.version += 1
        self._stop = threading.Event()
        self._prefetch = threading.Thread(target=self._run_prefetch, args=(self.version, self._stop), daemon=True)
        self._prefetch.start()
        print(f"reloaded v{self.version}", flush=True)

    def _encode(self, rgb: np.ndarray) -> bytes:
        ok, buf = cv2.imencode(".jpg", cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 88])
        return buf.tobytes()

    def _run_prefetch(self, version: int, stop: threading.Event, start: int = 0) -> None:
        comp = self.comp
        n = comp.nframes
        h, w = self.renderer.h, self.renderer.w
        # 今見ているコマから先に描く (編集の直後に近くのコマへシークしてもすぐ出るように)
        order = list(range(start, n)) + list(range(0, start))
        try:
            with _pool(self.project, self.scale, self.mb, True, self.workers) as pool:
                for f, buf in zip(order, pool.imap(_render_one, order, chunksize=2)):
                    if stop.is_set():
                        pool.terminate()
                        return
                    jpg = self._encode(np.frombuffer(buf, np.uint8).reshape(h, w, 3))
                    with self.lock:
                        if self.version == version:
                            self.frames.setdefault(f, jpg)
        except Exception:
            self.error = traceback.format_exc()

    def frame(self, f: int) -> bytes | None:
        with self.lock:
            if f in self.frames:
                return self.frames[f]
            if self.renderer is None:
                return None
            try:
                jpg = self._encode(self.renderer.frame(f))
            except Exception:
                self.error = traceback.format_exc()
                return None
            self.frames[f] = jpg
            return jpg

    def watch(self) -> None:
        while True:
            m = self._mtime()
            if m != self.mtime:
                self.mtime = m
                self.reload()
            time.sleep(0.4)

    def info(self) -> dict:
        c = self.comp
        if c is None:
            return {"version": -1, "error": self.error, "nframes": 1, "cached": 0, "fps": 60, "bpm": 120,
                    "name": "", "width": 0, "height": 0, "scale": self.scale, "audio": False}
        return {"version": self.version, "error": self.error, "nframes": c.nframes, "cached": len(self.frames),
                "fps": c.fps, "bpm": c.bpm, "name": c.name, "width": c.width, "height": c.height,
                "scale": self.scale, "audio": bool(self.audio_path)}


def serve(project: str, port: int = 8765, scale: float = 0.5, motion_blur: bool = False,
          workers: int | None = None, open_browser: bool = True) -> None:
    pv = Previewer(project, scale, motion_blur, workers)
    threading.Thread(target=pv.watch, daemon=True).start()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urlparse(self.path)
            if u.path == "/":
                return self._send(200, PAGE.encode(), "text/html; charset=utf-8")
            if u.path == "/info":
                return self._send(200, json.dumps(pv.info()).encode(), "application/json")
            if u.path.startswith("/frame/"):
                f = int(u.path.split("/")[-1].split(".")[0])
                jpg = pv.frame(f)
                return self._send(200, jpg, "image/jpeg") if jpg else self._send(503, b"", "text/plain")
            if u.path == "/audio.wav" and pv.audio_path:
                return self._send(200, Path(pv.audio_path).read_bytes(), "audio/wav")
            self._send(404, b"", "text/plain")

    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    url = f"http://127.0.0.1:{port}/"
    print(f"preview: {url}  (Ctrl+C で終了)", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
