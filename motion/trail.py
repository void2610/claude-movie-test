"""作品の反復の軌跡: 書き出し・レビューのたびに版を 1 つ記録し、版の並びを 1 本の動画と 1 枚の画像にする。

    uv run python -m motion render projects/x --note "brief v4: 実物の画像だけ"   # 何を試した版かを残す
    uv run python -m motion trail projects/x            # build/x/trail.mp4 と trail.png
    uv run python -m motion trail projects/x --git      # 記録を始める前の版を git の履歴から描いて足す

記録は projects/<名前>/trail/ (trail.jsonl と版ごとのコマの一覧 .jpg)。版ごとに、どの層 (コード・人の調整・値・
文字・音・絵) が前の版から変わったかを持つ。前より古い版と同じ中身に戻ったら、その間の版は行き止まりとして描く。
"""
from __future__ import annotations

import datetime
import hashlib
import json
import math
import subprocess
from pathlib import Path

import numpy as np

LAYERS = [("code", "コード"), ("edits", "調整"), ("tune", "値"), ("text", "文字"), ("sound", "音"), ("picture", "絵")]
THUMBS = 12
THUMB_W = 240


def _dir(project: str | Path) -> Path:
    p = Path(project).resolve()
    return (p if p.is_dir() else p.parent) / "trail"


def load(project: str | Path) -> list[dict]:
    f = _dir(project) / "trail.jsonl"
    if not f.exists():
        return []
    return [json.loads(ln) for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _sha(b: bytes) -> str:
    return hashlib.sha1(b).hexdigest()[:12]


def _git(*args: str, cwd: Path | None = None) -> str:
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True, cwd=cwd, check=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def grid(imgs: list[np.ndarray], cols: int = 4) -> np.ndarray:
    """コマを cols 列に並べた 1 枚 (RGB)。"""
    import cv2
    h0, w0 = imgs[0].shape[:2]
    th = max(1, round(THUMB_W * h0 / w0))
    rows = math.ceil(len(imgs) / cols)
    out = np.full((rows * (th + 4) + 4, cols * (THUMB_W + 4) + 4, 3), 16, np.uint8)
    for i, im in enumerate(imgs):
        r, c = divmod(i, cols)
        out[4 + r * (th + 4):4 + r * (th + 4) + th, 4 + c * (THUMB_W + 4):4 + c * (THUMB_W + 4) + THUMB_W] = \
            cv2.resize(im, (THUMB_W, th), interpolation=cv2.INTER_AREA)
    return out


def _tiny(img: np.ndarray) -> bytes:
    import cv2
    return cv2.resize(cv2.cvtColor(img, cv2.COLOR_RGB2GRAY), (16, 9), interpolation=cv2.INTER_AREA).tobytes()


def picture_hash(imgs: list[np.ndarray]) -> str:
    """コマごとの 16×9 の濃淡 (面積平均でグレインが消える)。"""
    return ",".join(_tiny(im).hex() for im in imgs)


def picture_changed(a: str | None, b: str | None) -> bool | None:
    """同じ位置のコマの 16×9 の濃淡の差の平均が 4 (0〜255) を超えたら絵が変わった。コマの数が違えば比べない。"""
    if not a or not b:
        return None
    xs, ys = a.split(","), b.split(",")
    if len(xs) != len(ys):
        return None
    d = [np.abs(np.frombuffer(bytes.fromhex(x), np.uint8).astype(int) - np.frombuffer(bytes.fromhex(y), np.uint8))
         .mean() for x, y in zip(xs, ys)]
    return float(np.mean(d)) > 4


def layer_hashes(project: str | Path, comp=None, wav: str | None = None, text_spans: dict | None = None) -> dict:
    pdir = Path(project).resolve()
    pdir = pdir if pdir.is_dir() else pdir.parent
    code = b"".join(p.read_bytes() for p in sorted(pdir.glob("*.py")))
    out = {"code": _sha(code)}
    for k, name in (("edits", "edits.json"), ("tune", "tune.json")):
        f = pdir / name
        out[k] = _sha(f.read_bytes()) if f.exists() else "-"
    if text_spans is not None:
        out["text"] = _sha(json.dumps(sorted(v[0] for v in text_spans.values()), ensure_ascii=False).encode())
    if wav:
        mj = Path(wav).with_suffix(".mix.json")
        if mj.exists():
            d = json.loads(mj.read_text(encoding="utf-8"))
            keep = [(e["t"], e["origin"], e.get("gain_db")) for e in d.get("events", [])]
            keep += [(a["t"], a["origin"]) for a in d.get("ambience", [])]
            out["sound"] = _sha(json.dumps([keep, d.get("gain_db")]).encode())
    return out


def lanes(comp, shots=None, wav: str | None = None, text_spans: dict | None = None) -> dict:
    """タイムラインの段: ショット・文字 (要素ごと)・効果音・環境音・音楽 (音のある区間)。秒で持つ。"""
    out: dict = {"duration": comp.duration}
    if shots is not None:
        out["shots"] = [(s.name, s.start, s.end) for s in shots]
    if text_spans:
        out["text"] = [(label, a, b) for label, spans in text_spans.values() for a, b in spans]
    if wav and Path(wav).exists():
        mj = Path(wav).with_suffix(".mix.json")
        if mj.exists():
            d = json.loads(mj.read_text(encoding="utf-8"))
            out["sfx"] = [(e["origin"].split("/")[0], e["start"], e["start"] + e["dur"], e["hero"])
                          for e in d.get("events", []) if not e.get("layer")]
            out["ambience"] = [(a["origin"].split("/")[-1], a["t"], a["end"]) for a in d.get("ambience", [])]
        bed = Path(wav).with_suffix(".bed.wav")
        if bed.exists():
            from .audio import load as load_wav
            y = load_wav(str(bed)).mean(axis=0)
            hop = 4800
            rms = np.sqrt(np.mean(y[:len(y) // hop * hop].reshape(-1, hop) ** 2, axis=1))
            on = 20 * np.log10(rms + 1e-12) > -45
            runs, i = [], 0
            while i < len(on):
                if on[i]:
                    j = i
                    while j < len(on) and on[j]:
                        j += 1
                    runs.append((i * 0.1, min(j * 0.1, comp.duration)))
                    i = j
                i += 1
            out["music"] = runs
    return out


def text_spans(per_frame: list[dict], fps: int) -> dict[str, tuple[str, list[tuple[float, float]]]]:
    """コマごとの見えている文字 {id: 名前} から、要素ごとの見えている区間。"""
    spans: dict[str, tuple[str, list]] = {}
    for f, vis in enumerate(per_frame):
        for i, label in vis.items():
            name, runs = spans.setdefault(i, (label, []))
            if runs and abs(runs[-1][1] - f / fps) < 0.5 / fps:
                runs[-1] = (runs[-1][0], (f + 1) / fps)
            else:
                runs.append((f / fps, (f + 1) / fps))
    return spans


def enabled() -> bool:
    import os
    return not os.environ.get("MOTION_NO_TRAIL")


def record(project: str | Path, comp, kind: str, note: str = "", imgs: list[np.ndarray] | None = None,
           wav: str | None = None, shots=None, text: dict | None = None, **stats) -> dict:
    """版を 1 つ記録する。imgs は等間隔のコマ (RGB)。前の版から変わった層と、古い版への戻りを判定する。"""
    import cv2
    d = _dir(project)
    d.mkdir(parents=True, exist_ok=True)
    prev = load(project)
    n = (prev[-1]["n"] + 1) if prev else 1
    h = layer_hashes(project, comp, wav, text)
    if imgs:
        h["picture"] = picture_hash(imgs)
        cv2.imwrite(str(d / f"{n:03d}.jpg"), cv2.cvtColor(grid(imgs), cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 82])
    commit = _git("rev-parse", "--short", "HEAD", cwd=d)
    dirty = bool(_git("status", "--porcelain", "--", str(d.parent), cwd=d))
    if not note:
        note = "(未コミットの変更)" if dirty else _git("log", "-1", "--format=%s", cwd=d)
    e = dict(n=n, time=datetime.datetime.now().isoformat(timespec="seconds"), kind=kind, note=note, commit=commit,
             dirty=dirty, format=f"{comp.width}x{comp.height}", fps=comp.fps, duration=comp.duration,
             params=json.loads(__import__("os").environ.get("MOTION_PARAMS", "{}") or "{}"),
             hash=h, thumbs=f"{n:03d}.jpg" if imgs else None,
             lanes=lanes(comp, shots, wav, text), **stats)
    e.update(_relate(prev, e))
    if "text" not in e["lanes"]:
        # 書き出しでは文字を数えないので、中身が同じ (変わった層がコードの外だけ) 直前のレビューの文字の段を引き継ぐ
        same = lambda x: all(x["hash"].get(k) == h.get(k) for k in ("code", "edits", "tune"))  # noqa: E731
        src = next((x for x in reversed(prev) if x["kind"] == "review" and same(x)), None)
        if src and src["lanes"].get("text"):
            e["lanes"]["text"] = src["lanes"]["text"]
    with (d / "trail.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    return e


def _relate(prev: list[dict], e: dict) -> dict:
    """前の版から変わった層と、前の前より古い版と同じ中身 (コード・調整・値) に戻ったか。"""
    if not prev:
        return dict(changed=[k for k, _ in LAYERS if k in e["hash"]], back_to=None)
    p = prev[-1]
    changed = []
    for k, _ in LAYERS:
        if k == "picture":
            ch = picture_changed(p["hash"].get(k), e["hash"].get(k))
        else:
            a, b = p["hash"].get(k), e["hash"].get(k)
            ch = None if a is None or b is None else a != b
        if ch:
            changed.append(k)
    key = lambda x: (x["hash"].get("code"), x["hash"].get("edits"), x["hash"].get("tune"))  # noqa: E731
    back = None
    if key(e) != key(p):
        back = next((x["n"] for x in reversed(prev[:-1]) if key(x) == key(e)), None)
    return dict(changed=changed, back_to=back)


def dead_ends(entries: list[dict]) -> set[int]:
    """古い版に戻ったとき、戻り先と戻った版の間にあった版 (試して捨てた版)。"""
    out = set()
    for e in entries:
        if e.get("back_to"):
            out |= {x["n"] for x in entries if e["back_to"] < x["n"] < e["n"]}
    return out


# ---------------------------------------------------------------- 描画

BG, FG, DIM, FAINT, ACCENT = "#101012", "#E8E8EC", "#8A8C97", "#3A3B42", "#FACC15"


def _paint(col: str, stroke: float = 0.0, dash: bool = False):
    import skia
    p = skia.Paint(Color=skia.Color(*bytes.fromhex(col[1:7])), AntiAlias=True)
    if stroke:
        p.setStyle(skia.Paint.kStroke_Style)
        p.setStrokeWidth(stroke)
    if dash:
        p.setPathEffect(skia.DashPathEffect.Make([5, 4], 0))
    return p


def draw_lanes(c, ln: dict, x: float, y: float, w: float, row: float = 18.0, label_w: float = 70.0) -> float:
    """タイムラインの段を描き、描いた高さを返す。"""
    import skia

    from .text import text as draw_text
    dur = ln.get("duration") or 1.0
    tx = lambda t: x + label_w + (w - label_w) * max(0.0, min(t, dur)) / dur  # noqa: E731
    rows = [("ショット", "shots"), ("文字", "text"), ("効果音", "sfx"), ("環境音", "ambience"), ("音楽", "music")]
    yy = y
    for k in range(int(dur) + 1):
        if k % 5 == 0:
            draw_text(c, f"{k}s", tx(k), yy, font="mono", size=9, color=DIM, valign="cap")
    yy += 12
    for name, key in rows:
        items = ln.get(key)
        if not items:
            continue
        draw_text(c, name, x, yy + row / 2, font="sans", size=11, color=DIM, valign="cap")
        if key == "text":
            # 重なる区間は段をずらす (4 段まで)。幅があれば要素の名前を中に書く
            ends = [-1.0] * 4
            used = 0
            for label, a, b in sorted(items, key=lambda r: r[1]):
                k = next((i for i, e_ in enumerate(ends) if a >= e_), 3)
                ends[k] = b + 0.05
                used = max(used, k + 1)
                r = skia.Rect.MakeLTRB(tx(a), yy + k * 15, max(tx(b), tx(a) + 2), yy + k * 15 + 13)
                c.drawRect(r, _paint("#C9CAD1"))
                if r.width() > 30:
                    c.save()
                    c.clipRect(r)
                    draw_text(c, label, r.left() + 3, r.top() + 6.5, font="sans", size=10, color="#16161A",
                              valign="cap", axes={"wght": 600})
                    c.restore()
            yy += used * 15 + 6
            continue
        for it in items:
            if key == "music":
                a, b, label, hot = it[0], it[1], "", False
            elif key == "sfx":
                label, a, b, hot = it
            else:
                label, a, b = it[:3]
                hot = False
            r = skia.Rect.MakeLTRB(tx(a), yy + 2, max(tx(b), tx(a) + 2), yy + row - 2)
            c.drawRect(r, _paint("#FF5470" if hot else ("#6B6E7A" if key != "shots" else "#2A2B31")))
            if key == "shots":
                c.drawRect(r, _paint(FAINT, 1))
                if r.width() > 40:
                    draw_text(c, label[:int(r.width() / 7)], r.left() + 4, yy + row / 2, font="sans", size=10,
                              color=FG, valign="cap", axes={"wght": 500})
        yy += row + 4
    return yy - y


def _page(entries: list[dict], i: int, tdir: Path, W: int = 1920, H: int = 1080) -> np.ndarray:
    import cv2
    import skia

    from .text import text as draw_text
    e = entries[i]
    surf = skia.Surface(W, H)
    c = surf.getCanvas()
    c.clear(skia.Color(16, 16, 18))
    draw_text(c, f"{e['n']:02d}", 80, 110, font="sans", size=44, color=FG, valign="cap")
    from .text import paragraph
    lines = paragraph(c, e.get("note") or "", 80, 140, 320, font="sans", size=17, color=FG, leading=1.35)
    yy = 140 + max(len(lines), 1) * 17 * 1.35 + 30
    rows = [("種類", {"render": "書き出し", "review": "レビュー", "git": "git の版"}.get(e["kind"], e["kind"])),
            ("日時", e["time"].replace("T", " ")[:16]), ("コミット", e.get("commit", "") + (" +変更" if e.get("dirty") else "")),
            ("形式", f"{e['format']} {e['fps']}fps {e['duration']:.1f}s" if e.get("format") else "-")]
    if e.get("failed"):
        rows.append(("描けなかった", e["failed"][:40]))
    if e.get("elapsed_s") is not None:
        rows.append(("書き出し", f"{e['elapsed_s']:.1f} 秒"))
    if e.get("size_mb") is not None:
        rows.append(("大きさ", f"{e['size_mb']:.1f} MB"))
    if e.get("errors") is not None:
        rows.append(("エラー / 注意", f"{e['errors']} / {e.get('notes', 0)}"))
    if e.get("params"):
        rows.append(("引数", " ".join(f"{k}={v}" for k, v in e["params"].items())))
    names = dict(LAYERS)
    rows.append(("変わった層", "・".join(names[k] for k in e.get("changed", [])) or "なし"))
    for k, v in rows:
        draw_text(c, k, 80, yy, font="sans", size=13, color=DIM, valign="cap")
        draw_text(c, str(v), 190, yy, font="sans", size=13, color=FG, valign="cap")
        yy += 24
    # 中央: コマの一覧
    gx, gy, gw, gh = 440, 70, 700, 720
    th = tdir / e["thumbs"] if e.get("thumbs") else None
    if th and th.exists():
        img = cv2.cvtColor(cv2.imread(str(th)), cv2.COLOR_BGR2RGB)
        k = min(gw / img.shape[1], gh / img.shape[0])
        img = cv2.resize(img, (int(img.shape[1] * k), int(img.shape[0] * k)), interpolation=cv2.INTER_AREA)
        rgba = np.dstack([img, np.full(img.shape[:2], 255, np.uint8)])
        c.drawImage(skia.Image.fromarray(np.ascontiguousarray(rgba), colorType=skia.kRGBA_8888_ColorType), gx, gy)
    else:
        draw_text(c, "コマなし (描けなかった版)", gx, gy + 20, font="sans", size=14, color=DIM, valign="cap")
    # 右: 系譜
    _lineage(c, entries, i, 1190, 70, 650, 760)
    # 下: タイムラインの段
    c.drawLine(80, 850, W - 80, 850, _paint(FAINT, 1))
    draw_lanes(c, e.get("lanes") or {}, 80, 866, W - 160)
    img = surf.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)
    return np.ascontiguousarray(img[:, :, :3])


def _lineage(c, entries: list[dict], cur: int, x: float, y: float, w: float, h: float) -> None:
    """版の系譜: 縦に版を並べ、行き止まりの版は横にずらして × で、古い版への戻りは破線で描く。変わった層を点で示す。"""
    import skia

    from .text import text as draw_text
    dead = dead_ends(entries)
    n = len(entries)
    row = min(26.0, (h - 30) / max(n, 1))
    step = 40
    cols_x = x + w - len(LAYERS) * step
    for k, (_, name) in enumerate(LAYERS):
        draw_text(c, name, cols_x + k * step + 6, y, font="sans", size=10, color=DIM, valign="cap", align="center")
    pos = {}
    for j, e in enumerate(entries):
        cy = y + 22 + j * row
        cx = x + 40 + (34 if e["n"] in dead else 0)
        pos[e["n"]] = (cx, cy)
    for j, e in enumerate(entries):
        cx, cy = pos[e["n"]]
        vis = j <= cur
        col = FG if vis else FAINT
        if j > 0:
            px, py = pos[entries[j - 1]["n"]]
            if e.get("back_to"):
                bx, by = pos[e["back_to"]]
                path = skia.Path()
                path.moveTo(bx, by)
                path.cubicTo(bx - 40, by, cx - 40, cy, cx, cy)
                c.drawPath(path, _paint(col, 1.2, dash=True))
            else:
                c.drawLine(px, py, cx, cy, _paint(col, 1.2))
        if e["n"] in dead:
            s = 5
            c.drawLine(cx - s, cy - s, cx + s, cy + s, _paint(col, 1.6))
            c.drawLine(cx - s, cy + s, cx + s, cy - s, _paint(col, 1.6))
        else:
            c.drawCircle(cx, cy, 6 if j == cur else 4, _paint(ACCENT if j == cur else col))
        label = f"{e['n']:02d} {(e.get('note') or '')[:22]}"
        draw_text(c, label, x + 100, cy, font="sans", size=11, color=FG if j == cur else (DIM if vis else FAINT),
                  valign="cap")
        for k, (key, _) in enumerate(LAYERS):
            if key in e.get("changed", []):
                c.drawCircle(cols_x + k * step + 6, cy, 3, _paint(col))
        if j == cur:
            c.drawLine(x, cy, x + w, cy, _paint(FAINT, 1))


def build(project: str | Path, out: str | Path | None = None, per_page: float = 1.2) -> tuple[Path, Path]:
    """版ごとの頁を並べた動画 (1 版 per_page 秒、最後の版は 3 秒) と、全版の一覧の画像を書く。"""
    import cv2

    from .render import load_project
    entries = load(project)
    if not entries:
        raise SystemExit("記録された版が無い。render / review を一度走らせるか、--git で履歴から作る")
    comp = load_project(project)
    tdir = _dir(project)
    out = Path(out) if out else Path(comp.build_dir) / "trail.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)
    fps = 30
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "1920x1080",
           "-r", str(fps), "-i", "-", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-crf", "18", "-movflags",
           "+faststart", str(out)]
    ff = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    pages = []
    for i in range(len(entries)):
        page = _page(entries, i, tdir)
        pages.append(page)
        k = int((3.0 if i == len(entries) - 1 else per_page) * fps)
        for _ in range(k):
            ff.stdin.write(page.tobytes())
    ff.stdin.close()
    ff.wait()
    # 一覧: 各版の頁を縮めて 4 列に
    small = [cv2.resize(p, (640, 360), interpolation=cv2.INTER_AREA) for p in pages]
    cols = min(4, len(small))
    rows = math.ceil(len(small) / cols)
    sheet = np.full((rows * 364 + 4, cols * 644 + 4, 3), 0, np.uint8)
    for i, p in enumerate(small):
        r, cl = divmod(i, cols)
        sheet[4 + r * 364:4 + r * 364 + 360, 4 + cl * 644:4 + cl * 644 + 640] = p
    png = out.with_suffix(".png")
    cv2.imwrite(str(png), cv2.cvtColor(sheet, cv2.COLOR_RGB2BGR))
    print(f"-> {out}\n-> {png}")
    return out, png


def _rewrite(project: str | Path, entries: list[dict]) -> list[dict]:
    """時刻の順に並べ直して番号を振り直し、変わった層と戻りを判定し直す (コマの画像も付け替える)。"""
    d = _dir(project)
    entries = sorted(entries, key=lambda e: e["time"])
    moves = []
    for i, e in enumerate(entries, 1):
        if e.get("thumbs"):
            src = d / e["thumbs"]
            tmp = d / f"_tmp_{i:03d}.jpg"
            if src.exists():
                src.rename(tmp)
                moves.append((tmp, d / f"{i:03d}.jpg"))
            e["thumbs"] = f"{i:03d}.jpg"
        e["n"] = i
    for tmp, dst in moves:
        tmp.rename(dst)
    out: list[dict] = []
    for e in entries:
        e.update(_relate(out, e))
        out.append(e)
    (d / "trail.jsonl").write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in out), encoding="utf-8")
    return out


def from_git(project: str | Path, python: str | None = None) -> list[dict]:
    """記録を始める前の版を、作品を変えた git のコミットごとに、その時点のエンジンで描いて足す。"""
    import shutil
    import sys
    import tempfile

    import cv2
    pdir = Path(project).resolve()
    pdir = pdir if pdir.is_dir() else pdir.parent
    root = Path(_git("rev-parse", "--show-toplevel", cwd=pdir))
    rel = pdir.relative_to(root).as_posix()
    entries = load(project)
    have = {e.get("commit") for e in entries if e["kind"] == "git"}
    commits = _git("log", "--reverse", "--format=%h\t%s\t%aI", "--", rel, cwd=root).splitlines()
    python = python or sys.executable
    tdir = _dir(project)
    tdir.mkdir(parents=True, exist_ok=True)
    added = []
    for line in commits:
        h, subject, when = line.split("\t", 2)
        if h in have:
            continue
        wt = Path(tempfile.mkdtemp(prefix="trail-")) / "wt"
        _git("worktree", "add", "--detach", str(wt), h, cwd=root)
        sheet = wt / "build" / "_trail_sheet.png"
        try:
            # git の外にある素材 (キャプチャ等) は今のものを参照する
            for sub in ("assets/footage",):
                if (root / sub).exists() and not (wt / sub).exists():
                    (wt / sub).parent.mkdir(parents=True, exist_ok=True)
                    (wt / sub).symlink_to(root / sub)
            res = subprocess.run([python, "-m", "motion", "sheet", rel, "--count", str(THUMBS), "--cols", "4",
                                  "--scale", "0.15", "-o", str(sheet)], cwd=wt, capture_output=True, text=True,
                                 timeout=900)
            ok = res.returncode == 0 and sheet.exists()
            img = cv2.cvtColor(cv2.imread(str(sheet)), cv2.COLOR_BGR2RGB) if ok else None
            tree = _git("rev-parse", f"{h}:{rel}", cwd=root)
            name = f"git-{h}.jpg"
            hsh = {"code": _sha((tree or h).encode())}
            if img is not None:
                cv2.imwrite(str(tdir / name), cv2.cvtColor(img, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 82])
                hsh["picture"] = picture_hash([img])
            e = dict(n=0, time=when[:19], kind="git", note=subject, commit=h, dirty=False, format="", fps=0,
                     duration=0.0, params={}, hash=hsh, thumbs=name if img is not None else None, lanes={},
                     failed=None if ok else ((res.stderr or "").strip().splitlines() or ["?"])[-1][:200])
            added.append(e)
            print(f"trail: {h} {subject[:40]} {'ok' if ok else '描けなかった: ' + e['failed']}", flush=True)
        finally:
            _git("worktree", "remove", "--force", str(wt), cwd=root)
            shutil.rmtree(wt.parent, ignore_errors=True)
    if added:
        _rewrite(project, entries + added)
    return added
