"""画像・動画ファイルを取り込んで描く。

    logo = media.Image("assets/logo.png")
    clip = media.Video("footage.mp4", start=2.0, offset=10.0, duration=3.0)
    comp.prepare.append(clip.prepare)      # 動画はレンダリング前にフレームを書き出しておく
    ...
    logo.draw(c, x, y, w, h, fit="contain")
    clip.draw(c, ctx, 0, 0, ctx.W, ctx.H, fit="cover")
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from collections import OrderedDict
from pathlib import Path

import skia

_SAMPLING = skia.SamplingOptions(skia.FilterMode.kLinear, skia.MipmapMode.kLinear)


def fit_rects(iw: float, ih: float, x: float, y: float, w: float, h: float,
              fit: str = "cover", anchor: tuple[float, float] = (0.5, 0.5)) -> tuple[skia.Rect, skia.Rect]:
    """画像 (iw, ih) を枠 (x, y, w, h) に収めるときの (元画像の切り出し範囲, 描画先) を返す。"""
    if fit == "fill":
        return skia.Rect.MakeWH(iw, ih), skia.Rect.MakeXYWH(x, y, w, h)
    if fit == "cover":
        s = max(w / iw, h / ih)
        sw, sh = w / s, h / s
        sx, sy = (iw - sw) * anchor[0], (ih - sh) * anchor[1]
        return skia.Rect.MakeXYWH(sx, sy, sw, sh), skia.Rect.MakeXYWH(x, y, w, h)
    s = min(w / iw, h / ih)
    dw, dh = iw * s, ih * s
    return skia.Rect.MakeWH(iw, ih), skia.Rect.MakeXYWH(x + (w - dw) * anchor[0], y + (h - dh) * anchor[1], dw, dh)


def _draw(c: skia.Canvas, img: skia.Image, x, y, w, h, fit, alpha, radius, anchor) -> None:
    src, dst = fit_rects(img.width(), img.height(), x, y, w, h, fit, anchor)
    p = skia.Paint(Alphaf=alpha, AntiAlias=True)
    if radius > 0:
        c.save()
        c.clipRRect(skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(x, y, w, h), radius, radius), skia.ClipOp.kIntersect,
                    True)
    c.drawImageRect(img, src, dst, _SAMPLING, p, skia.Canvas.kFast_SrcRectConstraint)
    if radius > 0:
        c.restore()


class Image:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._img: skia.Image | None = None

    @property
    def image(self) -> skia.Image:
        if self._img is None:
            self._img = skia.Image.open(str(self.path))
        return self._img

    @property
    def size(self) -> tuple[int, int]:
        return self.image.width(), self.image.height()

    def draw(self, c: skia.Canvas, x: float, y: float, w: float | None = None, h: float | None = None, *,
             fit: str = "cover", alpha: float = 1.0, radius: float = 0.0,
             anchor: tuple[float, float] = (0.5, 0.5)) -> None:
        iw, ih = self.size
        _draw(c, self.image, x, y, iw if w is None else w, ih if h is None else h, fit, alpha, radius, anchor)


def probe(path: str | Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height,r_frame_rate:format=duration", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True)
    j = json.loads(out.stdout)
    st = j["streams"][0]
    num, den = st["r_frame_rate"].split("/")
    return {"width": st["width"], "height": st["height"], "fps": float(num) / float(den),
            "duration": float(j["format"]["duration"])}


class Video:
    """動画クリップ。作品の start 秒から、元動画の offset 秒以降を speed 倍速で再生する。"""

    def __init__(self, path: str | Path, *, start: float = 0.0, offset: float = 0.0, duration: float | None = None,
                 speed: float = 1.0, max_height: int | None = 1080, loop: bool = False, cache: int = 16):
        self.path = Path(path).resolve()
        self.start = start
        self.offset = offset
        self.speed = speed
        self.max_height = max_height
        self.loop = loop
        self._duration = duration
        self._lru: OrderedDict[int, skia.Image] = OrderedDict()
        self._max = cache
        self._dir: Path | None = None
        self._count = 0

    def _key(self, comp) -> str:
        st = self.path.stat()
        src = json.dumps([str(self.path), st.st_mtime, st.st_size, self.offset, self._duration, self.speed,
                          self.max_height, comp.fps])
        return hashlib.sha1(src.encode()).hexdigest()[:16]

    def _cache_dir(self, comp) -> Path:
        if self._dir is None:
            self._dir = Path(comp.build_dir) / "media" / f"{self.path.stem}-{self._key(comp)}"
        return self._dir

    def prepare(self, comp) -> None:
        """作品の fps で必要な区間のフレームを JPEG で書き出す。済んでいれば何もしない。"""
        d = self._cache_dir(comp)
        if (d / ".done").exists():
            return
        d.mkdir(parents=True, exist_ok=True)
        info = probe(self.path)
        dur = self._duration if self._duration is not None else info["duration"] - self.offset
        vf = [f"setpts=PTS/{self.speed}", f"fps={comp.fps}"]
        if self.max_height and info["height"] > self.max_height:
            vf.append(f"scale=-2:{self.max_height}")
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{self.offset}", "-t", f"{dur}", "-i", str(self.path),
               "-vf", ",".join(vf), "-q:v", "2", "-start_number", "0", str(d / "f_%05d.jpg")]
        print(f"media: extracting {self.path.name}", flush=True)
        subprocess.run(cmd, check=True)
        (d / ".done").write_text("ok")

    def frame_count(self, comp) -> int:
        if not self._count:
            self._count = len(list(self._cache_dir(comp).glob("f_*.jpg")))
        return self._count

    @property
    def duration(self) -> float | None:
        return self._duration

    def image(self, comp, t: float) -> skia.Image | None:
        n = self.frame_count(comp)
        if n == 0:
            return None
        i = int(round((t - self.start) * comp.fps))
        i = i % n if self.loop else max(0, min(i, n - 1))
        if i in self._lru:
            self._lru.move_to_end(i)
            return self._lru[i]
        img = skia.Image.open(str(self._cache_dir(comp) / f"f_{i:05d}.jpg"))
        self._lru[i] = img
        if len(self._lru) > self._max:
            self._lru.popitem(last=False)
        return img

    def draw(self, c: skia.Canvas, ctx, x: float = 0.0, y: float = 0.0, w: float | None = None,
             h: float | None = None, *, fit: str = "cover", alpha: float = 1.0, radius: float = 0.0,
             anchor: tuple[float, float] = (0.5, 0.5)) -> None:
        img = self.image(ctx.comp, ctx.t)
        if img is None:
            return
        _draw(c, img, x, y, ctx.W if w is None else w, ctx.H if h is None else h, fit, alpha, radius, anchor)
