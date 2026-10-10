"""録音の効果音ライブラリ。打撃・クリック・風切りは合成せず、CC0 の録音から目で見て選ぶ。

    uv run python -m motion sfx kit                                # 初回だけ: 取得・加工して catalog.json を作る
    uv run python -m motion sfx browse hit --like "metal heavy"    # 候補の一覧と、波形・スペクトログラムの画像
    uv run python -m motion sfx search "laptop key press" --type key   # 足りないとき: Openverse で CC0 を探す
    uv run python -m motion sfx add FILE --type key --credit "出典, ライセンス"

    mx.sfx(sfxlib.sound("hit/fs-578790-metal-hit-1-1"), t)        # 選んだ id を、山が t に来るように置く
    mx.sfx(sfxlib.sound("whoosh", i=2), t)                         # 種類だけなら既定の音を順に使う

1 本の作品で音の系統 (ガラス + 空気、金属 + 低音 など) を 1 つに揃え、同じ音の繰り返しは i と pitch で変える。
取得元の一覧 (data/sfx_sources.json) と、切り出し・判定の基準は opus-sound-layer に倣う
(MIT License, Copyright (c) 2026 Bodila51。全文は data/opus-sound-layer.LICENSE)。
"""
from __future__ import annotations

import concurrent.futures
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
import zipfile
from functools import lru_cache
from pathlib import Path

import numpy as np
from scipy import signal

from .sfx import Sound

SR = 48000
LIB = Path(os.environ.get("MOTION_SFX", "~/Music/Samples/motion-sfx")).expanduser()
SOURCES = Path(__file__).parent / "data" / "sfx_sources.json"
UA = "motion-sfxlib/1.0 (motion graphics sound design)"

# kind は切り出し方と判定の基準を決める (swell は膨らんで消える、riser は山に向かって育つ)
TYPES = {
    "click": dict(kind="transient", win=(0.03, 0.20), hp=200, lp=12000, hi_max=0.5, about="マウス・スイッチ・ボタン"),
    "key": dict(kind="transient", win=(0.05, 0.15), hp=200, lp=11000, about="キーボードの打鍵"),
    "tick": dict(kind="transient", win=(0.03, 0.15), hp=300, lp=12000, hi_max=0.55, about="小さなカウンタ・スクロールの刻み"),
    "tap": dict(kind="transient", win=(0.06, 0.60), hp=100, lp=12000, hi_max=0.55, about="軽い当たり (ガラス・木・金属・樹脂)"),
    "pop": dict(kind="transient", win=(0.05, 0.40), hp=150, lp=12000, about="要素が出る・泡・コルク"),
    "thump": dict(kind="transient", win=(0.12, 1.00), hp=35, lp=8000, allow_low=True, about="柔らかく重い着地"),
    "hit": dict(kind="transient", win=(0.20, 4.00), hp=28, lp=15000, allow_low=True, allow_sub=True, rise_max=60,
                layered=True, min_s=0.35, about="見せ場の衝撃 (映画的な打撃・金属・パンチ)"),
    "boom": dict(kind="transient", win=(0.40, 4.00), hp=22, lp=9000, allow_low=True, allow_sub=True, rise_max=80,
                 layered=True, min_s=0.4, about="打撃の下に重ねる低音の落下"),
    "paper": dict(kind="swell", win=(0.12, 0.70), hp=200, lp=12000, noise_ok=True, about="紙・カード・本"),
    "swish": dict(kind="swell", win=(0.15, 0.70), hp=150, lp=12000, noise_ok=True, about="布・カードの滑り・小さく速い動き"),
    "whoosh": dict(kind="swell", win=(0.25, 1.20), hp=100, lp=14000, noise_ok=True, about="物が横切る"),
    "transition": dict(kind="swell", win=(0.60, 3.00), hp=50, lp=15000, noise_ok=True, allow_low=True, spiky_max=4.0,
                       about="画面全体の切り替え・深い風切り"),
    "riser": dict(kind="riser", win=(1.00, 6.00), hp=40, lp=15000, noise_ok=True, allow_low=True,
                  about="打撃に向かって高まる"),
    "reverse": dict(kind="riser", win=(0.40, 3.00), hp=60, lp=15000, noise_ok=True, allow_low=True,
                    about="逆再生のシンバル・吸い込み (キューで終わる)"),
    "glitch": dict(kind="glitch", win=(0.06, 1.50), hp=80, lp=16000, noise_ok=True, hi_max=0.7, designed_end=True,
                   about="デジタルな途切れ・データ・静電気"),
    "ui": dict(kind="tonal", win=(0.04, 0.90), hp=200, lp=15000, hi_max=0.6, designed_end=True,
               about="画面の操作音 (決定・選択・開閉・エラー)"),
    "zap": dict(kind="tonal", win=(0.06, 1.50), hp=120, lp=15000, noise_ok=True, hi_max=0.6, designed_end=True,
                about="SF のレーザー・パワーアップ"),
    "chime": dict(kind="tonal", win=(0.25, 2.50), hp=200, lp=14000, hi_max=0.6, about="ベル・ディン・グラスの響き"),
    "shimmer": dict(kind="tonal", win=(0.40, 3.50), hp=300, lp=16000, hi_max=0.75, noise_ok=True,
                    about="きらめき (見せ場の出現に重ねる)"),
}


# ---------------------------------------------------------------- 加工と判定

def decode(path: str | Path) -> np.ndarray:
    """どんな形式でも ffmpeg でモノラル 48kHz の float64 にする (取得元がエラーページを返したら例外)。"""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).astype(np.float64)


def envelope(y: np.ndarray, win_s: float = 0.004) -> np.ndarray:
    n = max(1, int(win_s * SR))
    return np.sqrt(np.convolve(y * y, np.ones(n) / n, mode="same"))


def event_span(y: np.ndarray, t: dict) -> tuple[int, int]:
    """一番強い出来事の範囲。隣の音まで広げない (短い録音は短いまま)。"""
    hi_len = int(t["win"][1] * SR)
    if t["kind"] == "riser":
        env = envelope(y, 0.03)
        p = int(np.argmax(env))
        thr = env[p] * 10 ** (-30 / 20)
        a = p
        while a > 0 and env[a - 1] > thr and p - a < hi_len - int(0.4 * SR):
            a -= 1
        b = p
        while b < len(y) - 1 and env[b + 1] > env[p] * 0.1 and b - p < int(0.6 * SR):
            b += 1
        return a, b
    if t["kind"] == "swell":
        env = envelope(y, 0.02)
        p = int(np.argmax(env))
        thr = env[p] * 0.1
        a = b = p
        # 大きい側へ広げ、両端が 20dB 下がったら止める
        while b - a < hi_len:
            left = env[a - 1] if a > 0 else 0.0
            right = env[b + 1] if b < len(y) - 1 else 0.0
            if left <= thr and right <= thr:
                break
            if left >= right:
                a -= 1
            else:
                b += 1
        return a, b
    fine = envelope(y, 0.002)
    smooth = envelope(y, 0.015)
    p = int(np.argmax(fine))
    ps = smooth[p]
    a = p
    while a > 0 and fine[a] > fine[p] * 0.1 and p - a < int(0.05 * SR):
        a -= 1
    a = max(0, a - int(0.005 * SR))
    tail = ps * 10 ** (-40 / 20)
    b, low = p, ps
    while b < len(y) - 1 and smooth[b] > tail and b - a < hi_len:
        low = min(low, smooth[b])
        # 2 発目: 山の後の谷から大きく持ち上がったら、その谷で切る (グリッチは複数発が本来の姿)
        if (t["kind"] != "glitch" and not t.get("layered") and b - p > int(0.01 * SR)
                and smooth[b] > max(4 * low, 0.1 * ps)):
            b = p + int(np.argmin(smooth[p:b]))
            break
        b += 1
    return a, b


def cut_events(y: np.ndarray, t: dict, k: int = 1) -> list[tuple[int, np.ndarray]]:
    """1 つのファイルから最大 k 個の出来事を時間順に切り出す。一番強いものの -12dB 以上だけ。"""
    y = y.copy()
    out = []
    first = None
    for _ in range(k):
        pk = np.max(np.abs(y)) if len(y) else 0.0
        if pk <= 1e-6 or (first is not None and pk < first * 0.25):
            break
        a, b = event_span(y, t)
        if b - a < int(0.01 * SR):
            break
        out.append((a, y[a:b].copy()))
        first = first or pk
        m = int(0.05 * SR)
        y[max(0, a - m):b + m] = 0.0
    return sorted(out, key=lambda e: e[0])


def clean(x: np.ndarray, t: dict) -> np.ndarray:
    hp = signal.butter(4, t["hp"], "highpass", fs=SR, output="sos")
    lp = signal.butter(4, min(t["lp"], SR / 2 - 100), "lowpass", fs=SR, output="sos")
    x = signal.sosfilt(lp, signal.sosfilt(hp, x))
    f = min(int(0.005 * SR), len(x) // 4)
    # 作られた操作音はわざと途切れるので、クリックにならない程度の 20ms で閉じる
    fo = min(int((0.02 if t.get("designed_end") else 0.005) * SR), len(x) // 4)
    if f > 0:
        x[:f] *= np.linspace(0, 1, f)
        x[-fo:] *= np.linspace(1, 0, fo)
    if t.get("layered"):
        # 長く響く打撃は窓で切れるので、最後の 30% で自然に減衰させる
        e = envelope(x, 0.01)
        edge = max(1, len(x) // 10)
        if e[-edge:].max() > e.max() * 0.1:
            n = int(len(x) * 0.3)
            x[-n:] *= np.cos(np.linspace(0, np.pi / 2, n)) ** 2
    return x * (10 ** (-3 / 20) / (np.max(np.abs(x)) + 1e-12))


def measure(x: np.ndarray, t: dict) -> dict:
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
    fr = np.fft.rfftfreq(len(x), 1 / SR)
    tot = spec.sum() + 1e-20
    env = envelope(x, 0.002)
    p = int(np.argmax(env))
    a10 = np.where(env[:p + 1] >= 0.1 * env[p])[0]
    a90 = np.where(env[:p + 1] >= 0.9 * env[p])[0]
    rise = (a90[0] - a10[0]) / SR * 1000 if len(a10) and len(a90) else 0.0
    # 平坦さは通過帯域の中だけで、下限を付けて測る (切った帯域が幾何平均を 0 にしないように)
    band = spec[(fr >= max(t["hp"], 100)) & (fr <= t["lp"])]
    band = np.maximum(band, band.max() * 1e-6 + 1e-20)
    flat = float(np.exp(np.mean(np.log(band))) / np.mean(band))
    env10 = envelope(x, 0.01)
    env30 = envelope(x, 0.03)
    edge = max(int(0.005 * SR), len(x) // 10)

    def rel(v):
        return float(20 * np.log10(v / (env10.max() + 1e-12) + 1e-12))

    pk = int(np.argmax(spec * (fr > 80)))
    tonal = float(spec[pk] / (np.mean(spec[max(0, pk - 40):pk + 40]) + 1e-20))
    q = max(1, len(x) // 4)
    return dict(
        dur_s=round(len(x) / SR, 3),
        peak_s=round(p / SR, 4),
        rise_ms=round(float(rise), 1),
        centroid_hz=int((fr * spec).sum() / tot),
        below150=round(float(spec[fr < 150].sum() / tot), 3),
        above6k=round(float(spec[fr > 6000].sum() / tot), 3),
        flatness=round(flat, 3),
        note=round(69 + 12 * float(np.log2(fr[pk] / 440.0)), 1) if fr[pk] > 0 and tonal > 8 else None,
        build_db=round(float(20 * np.log10((env30[-q:].mean() + 1e-12) / (env30[:2 * q].mean() + 1e-12))), 1),
        start_db=round(rel(env10[:edge].max()), 1),
        end_db=round(rel(env10[-edge:].max()), 1),
        spikiness=round(float(env.max() / (env30.max() + 1e-12)), 2),
    )


def judge(m: dict, t: dict) -> list[str]:
    """種類として使えない理由。空なら合格。"""
    why = []
    if m["below150"] > 0.5 and not t.get("allow_low"):
        why.append("低音ばかり")
    if m["below150"] > 0.85 and not t.get("allow_sub"):
        why.append("150Hz 以上に中身が無い (スマホで聞こえない)")
    if m["above6k"] > t.get("hi_max", 0.4):
        why.append("シャリシャリ")
    if m["flatness"] > 0.35 and not t.get("noise_ok"):
        why.append("ノイズのよう")
    if t["kind"] == "transient" and m["rise_ms"] > t.get("rise_max", 25):
        why.append("立ち上がりが遅い")
    if t["kind"] == "swell":
        if max(m["start_db"], m["end_db"]) > -12:
            why.append("膨らまない (一定のノイズ)")
        if m["spikiness"] > t.get("spiky_max", 2.5):
            why.append("中にクリック")
    elif t["kind"] == "riser":
        if m["start_db"] > -12:
            why.append("始めから大きい")
        if m["peak_s"] < 0.7 * m["dur_s"]:
            why.append("山が早すぎる")
        if m["spikiness"] > 3:
            why.append("中にクリック")
        if m["build_db"] < 6:
            why.append("育たない")
    elif not t.get("designed_end") and m["end_db"] > -20:
        why.append("減衰しきる前に切れている")
    if m["dur_s"] < t.get("min_s", t["win"][0] * 0.5):
        why.append("短すぎる")
    if t.get("layered") and m["build_db"] > -6:
        why.append("減衰しない")
    return why


def _write_wav(path: Path, x: np.ndarray) -> None:
    from pedalboard.io import AudioFile
    path.parent.mkdir(parents=True, exist_ok=True)
    with AudioFile(str(path), "w", SR, num_channels=1, bit_depth=24) as f:
        f.write(x.astype(np.float32)[None, :])


def prepare(src: str | Path, typ: str, out_dir: Path, name: str, meta: dict | None = None, k: int = 1) -> list[dict]:
    """1 つのファイルから最大 k 個を切り出し、掃除・計測・判定して wav と .json を書く。"""
    t = TYPES[typ]
    evs = cut_events(decode(src), t, k)
    out = []
    for i, (_, y) in enumerate(evs):
        nm = name if len(evs) == 1 and k == 1 else f"{name}-{i + 1}"
        x = clean(y, t)
        m = measure(x, t)
        why = judge(m, t)
        dst = out_dir / f"{nm}.wav"
        _write_wav(dst, x)
        side = dict(type=typ, file=str(dst), verdict="ok" if not why else "不合格: " + "、".join(why), **m)
        if meta:
            side["source"] = meta
        dst.with_suffix(".json").write_text(json.dumps(side, ensure_ascii=False, indent=1), encoding="utf-8")
        out.append(side)
    return out


def slug(s: str) -> str:
    s = re.sub(r"([a-z])([A-Z])", r"\1-\2", s)
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:48]


_STOP = {"wav", "mp3", "aif", "aiff", "flac", "ogg", "sfx", "fx", "sound", "sounds", "the", "and", "of", "by"}


def words(s: str) -> list[str]:
    return [w for w in re.split(r"[^a-z0-9]+", re.sub(r"([a-z])([A-Z])", r"\1 \2", s or "").lower())
            if w and not w.isdigit() and len(w) > 1 and w not in _STOP]


# ---------------------------------------------------------------- ライブラリ

def _fetch(url: str, dst: Path) -> None:
    # 途中で切れたファイルを取得済みと見なさないよう、.part に書いてから置き換える
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    dst.parent.mkdir(parents=True, exist_ok=True)
    part = dst.with_name(dst.name + ".part")
    with urllib.request.urlopen(req, timeout=120) as r:
        part.write_bytes(r.read())
    part.replace(dst)


def _fetch_all(jobs: list[tuple[str, Path]], workers: int = 16) -> dict[Path, Exception]:
    todo = [(u, d) for u, d in jobs if not d.exists()]
    if not todo:
        return {}
    print(f"sfx: {len(todo)} 個を取得 ({len(jobs) - len(todo)} 個は取得済み)", flush=True)
    errors: dict[Path, Exception] = {}

    def one(job):
        u, d = job
        try:
            _fetch(u, d)
        except Exception as ex:  # noqa: BLE001
            return d, ex
        return d, None

    with concurrent.futures.ThreadPoolExecutor(workers) as ex:
        for i, (d, err) in enumerate(ex.map(one, todo), 1):
            if err is not None:
                errors[d] = err
            if i % 100 == 0 or i == len(todo):
                print(f"  {i}/{len(todo)}", flush=True)
    return errors


def _entry(side: dict, root: Path, tags: list[str], credit: str, default: bool) -> dict:
    rel = Path(side["file"]).relative_to(root).as_posix()
    keys = ("dur_s", "peak_s", "rise_ms", "centroid_hz", "below150", "above6k", "flatness", "note")
    return dict(id=rel[:-4], type=side["type"], file=rel, tags=sorted(set(tags)), credit=credit, default=default,
                **{k: side[k] for k in keys})


def _write_catalog(root: Path, entries: list[dict], credits: list[str]) -> None:
    entries = sorted(entries, key=lambda e: e["id"])
    by_type: dict[str, list[dict]] = {}
    for e in entries:
        by_type.setdefault(e["type"], []).append(e)
    cat = dict(types={k: dict(about=TYPES[k]["about"], count=len(by_type.get(k, [])),
                              defaults=[e["id"] for e in by_type.get(k, []) if e["default"]]) for k in TYPES},
               sounds=entries)
    (root / "catalog.json").write_text(json.dumps(cat, ensure_ascii=False, indent=1), encoding="utf-8")
    head = ["# 効果音の出典", "", "Kenney のパックと Freesound の録音は CC0 (パブリックドメイン)。表記は不要だが残す。", ""]
    (root / "CREDITS.md").write_text("\n".join(head + sorted(set(credits))) + "\n", encoding="utf-8")
    catalog.cache_clear()


def _added(root: Path) -> list[dict]:
    p = root / "added.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def kit(root: Path = LIB, sources: Path = SOURCES, workers: int = 8) -> Path:
    """取得元の一覧から CC0 の録音を集めて加工し、root/catalog.json と CREDITS.md を作り直す。

    add で足した音 (own-*) は残す。取得済みのファイルは取り直さない。
    """
    lib = json.loads(sources.read_text(encoding="utf-8"))
    raw = root / "_raw"
    defaults = set(lib.get("defaults", []))
    for typ in TYPES:
        d = root / typ
        if d.is_dir():
            for f in d.iterdir():
                if not f.name.startswith("own-"):
                    f.unlink()
    zip_of = {p["name"]: raw / Path(p["url"]).name for p in lib["packs"]}
    fs_of = {it["id"]: raw / "freesound" / f"{it['id']}.mp3" for it in lib["freesound"]}
    failed = _fetch_all([(p["url"], zip_of[p["name"]]) for p in lib["packs"]]
                        + [(it["url"], fs_of[it["id"]]) for it in lib["freesound"]])

    jobs = []  # (src, typ, name, meta, k, keep, tags, credit, landing-line)
    credits = []
    for pack in lib["packs"]:
        zp = zip_of[pack["name"]]
        try:
            if zp in failed:
                raise failed[zp]
            z = zipfile.ZipFile(zp)
        except Exception as ex:  # noqa: BLE001
            print(f"sfx: パック {pack['name']} を飛ばす: {ex}", file=sys.stderr)
            continue
        rules = [(re.compile(r, re.I), typ, tags) for r, typ, tags in pack["map"]]
        for member in sorted(z.namelist()):
            if not re.search(r"\.(ogg|wav)$", member, re.I) or "__MACOSX" in member:
                continue
            stem = Path(member).stem
            rule = next(((typ, tags) for rx, typ, tags in rules if rx.search(stem)), None)
            if not rule or rule[0] == "skip":
                continue
            src = raw / pack["name"] / Path(member).name
            if not src.exists():
                src.parent.mkdir(parents=True, exist_ok=True)
                src.write_bytes(z.read(member))
            jobs.append((src, rule[0], f"kenney-{pack['name']}-{slug(stem)}", dict(pack=pack["name"], file=member), 1,
                         None, words(stem) + rule[1] + ["kenney", pack["name"]], pack["credit"], None))
        credits.append(f"- {pack['credit']}, {pack['license'].upper()}, {pack['landing']}")
    for it in lib["freesound"]:
        src = fs_of[it["id"]]
        if src in failed or not src.exists():
            print(f"sfx: {it['title']} を飛ばす: {failed.get(src, '未取得')}", file=sys.stderr)
            continue
        credit = f"\"{it['title']}\" by {it['creator']}"
        jobs.append((src, it["type"], f"fs-{it['id']}-{slug(it['title'])[:28]}".rstrip("-"), it, it.get("k", 1),
                     it.get("keep"), words(it["title"]) + it.get("tags", []) + ["freesound"], credit,
                     f"{credit}, {it['license'].upper()}, {it['landing']}"))

    def run(job):
        src, typ, name, meta, k, keep, tags, credit, line = job
        try:
            sides = prepare(src, typ, root / typ, name, meta, k)
        except Exception as ex:  # noqa: BLE001
            return job, ex, []
        return job, None, sides

    entries, total, rejected = [], 0, 0
    print(f"sfx: {len(jobs)} 個のファイルを加工", flush=True)
    with concurrent.futures.ThreadPoolExecutor(workers) as ex:
        for job, err, sides in ex.map(run, jobs):
            src, typ, name, meta, k, keep, tags, credit, line = job
            if err is not None:
                print(f"sfx: {name} を飛ばす: {err}", file=sys.stderr)
                continue
            for i, side in enumerate(sides):
                total += 1
                if side["verdict"] != "ok" or (keep is not None and i not in keep):
                    rejected += 1
                    Path(side["file"]).unlink()
                    Path(side["file"]).with_suffix(".json").unlink()
                    continue
                e = _entry(side, root, tags, credit, False)
                e["default"] = e["id"] in defaults
                entries.append(e)
                if line:
                    credits.append(f"- {e['id']}: {line}")
    for e in _added(root):
        if (root / e["file"]).exists():
            entries.append(e)
            credits.append(f"- {e['id']}: {e['credit']}")
    _write_catalog(root, entries, credits)
    counts = {k: sum(e["type"] == k for e in entries) for k in TYPES}
    print(f"sfx: {len(entries)} 個 ({total} 個の切り出しのうち {rejected} 個は判定で除外) -> {root / 'catalog.json'}")
    print("  " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    return root / "catalog.json"


@lru_cache(maxsize=4)
def catalog(root: Path = LIB) -> dict:
    p = root / "catalog.json"
    if not p.exists():
        raise FileNotFoundError(f"{p} が無い。`uv run python -m motion sfx kit` で作る")
    return json.loads(p.read_text(encoding="utf-8"))


def browse(typ: str, like: str = "", n: int = 12, length: str | None = None, tone: str | None = None,
           root: Path = LIB) -> list[dict]:
    """種類の中から、like の語 (素材・重さ・雰囲気) に合う順に n 個。length は short / long、tone は bright / dark。"""
    pool = [e for e in catalog(root)["sounds"] if e["type"] == typ]
    if not pool:
        raise ValueError(f"種類 '{typ}' の音が無い。種類: {', '.join(TYPES)}")
    q = words(like)

    def score(e):
        hay = " ".join(e["tags"] + [e["id"]])
        s = sum(2 if w in e["tags"] else 1 if w in hay else 0 for w in q)
        if length == "short":
            s -= e["dur_s"]
        elif length == "long":
            s += e["dur_s"]
        if tone == "bright":
            s += e["centroid_hz"] / 4000
        elif tone == "dark":
            s -= e["centroid_hz"] / 4000
        return (s, e["default"])

    return sorted(pool, key=score, reverse=True)[:n]


def entry(ref: str, root: Path = LIB) -> dict:
    for e in catalog(root)["sounds"]:
        if e["id"] == ref:
            return e
    raise KeyError(f"効果音 '{ref}' が無い。`motion sfx browse <種類>` で id を探す")


def sound(ref: str, i: int = 0, like: str = "", pitch: float = 0.0, root: Path = LIB) -> Sound:
    """録音を Sound にする。ref は id ("hit/fs-...") か種類 ("hit")。種類だけなら like に合う順 (無ければ既定) の i 番目。"""
    if "/" in ref:
        e = entry(ref, root)
    else:
        cat = catalog(root)
        ids = cat["types"].get(ref, {}).get("defaults") if not like else None
        e = entry(ids[i % len(ids)], root) if ids else browse(ref, like, n=max(i + 1, 1), root=root)[i]
    from .audio import load
    buf = load(str(root / e["file"]))
    return Sound(buf.copy(), e["peak_s"], e["id"]).pitched(pitch)


def search(query: str, typ: str, n: int = 6, root: Path = LIB) -> list[dict]:
    """ライブラリに合う音が無いとき、Openverse (Freesound の CC0) を探して加工・判定する。候補は root/_candidates。"""
    q = urllib.parse.urlencode(dict(q=query, license="cc0", source="freesound", page_size=n, filter_dead="true"))
    req = urllib.request.Request("https://api.openverse.org/v1/audio/?" + q, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        res = json.load(r)["results"]
    out = []
    for r in res:
        rawf = root / "_candidates" / typ / "_raw" / f"ov-{r['id'][:8]}.mp3"
        try:
            if not rawf.exists():
                _fetch(r["url"], rawf)
            meta = dict(title=r.get("title"), creator=r.get("creator"), license=r.get("license"), url=r.get("url"),
                        landing=r.get("foreign_landing_url"))
            out += prepare(rawf, typ, root / "_candidates" / typ, f"ov-{r['id'][:8]}", meta)
        except Exception as ex:  # noqa: BLE001
            print(f"sfx: {r.get('title')} を飛ばす: {ex}", file=sys.stderr)
    return out


def add(files: list[str | Path], typ: str, tags: list[str] | None = None, credit: str = "", root: Path = LIB) -> list[dict]:
    """手元のファイルや search の候補をライブラリに足す (kit で作り直しても残る)。判定に落ちても警告して残す。"""
    added = _added(root)
    cat = catalog(root)
    entries = cat["sounds"]
    out = []
    for f in map(Path, files):
        meta = None
        if f.suffix == ".wav" and f.with_suffix(".json").exists():
            meta = json.loads(f.with_suffix(".json").read_text(encoding="utf-8")).get("source")
        c = credit
        if not c and meta and meta.get("creator"):
            c = f"\"{meta.get('title')}\" by {meta.get('creator')}, {str(meta.get('license', '')).upper()}, {meta.get('landing', '')}"
        c = c or "手で追加 (--credit に出典とライセンスを書く)"
        for side in prepare(f, typ, root / typ, "own-" + slug(f.stem), meta):
            e = _entry(side, root, (tags or []) + words(f.stem) + ["own"], c, False)
            entries = [x for x in entries if x["id"] != e["id"]] + [e]
            added = [x for x in added if x["id"] != e["id"]] + [e]
            out.append(side)
    (root / "added.json").write_text(json.dumps(added, ensure_ascii=False, indent=1), encoding="utf-8")
    lines = [ln for ln in (root / "CREDITS.md").read_text(encoding="utf-8").splitlines() if ln.startswith("- ")]
    _write_catalog(root, entries, lines + [f"- {e['id']}: {e['credit']}" for e in added])
    return out


def describe(e: dict) -> str:
    note = "" if e.get("note") is None else f"{e['note']:.0f}"
    tags = " ".join(t for t in e["tags"] if t not in ("kenney", "freesound"))[:56]
    return (f"{'*' if e.get('default') else ' '}{e['id']:50s} {e['dur_s']:5.2f}s {e['rise_ms']:5.0f}ms "
            f"{e['centroid_hz']:6d}Hz {note:>4s}  {tags}")


# ---------------------------------------------------------------- 見て選ぶための画像

def _spectrogram(x: np.ndarray, w: int, h: int, fmax: float = 12000) -> np.ndarray:
    import cv2
    n_fft, hop = 512, 128
    if len(x) < n_fft:
        x = np.pad(x, (0, n_fft - len(x)))
    win = np.hanning(n_fft)
    idx = np.arange(0, len(x) - n_fft + 1, hop)
    spec = np.abs(np.fft.rfft(np.stack([x[i:i + n_fft] * win for i in idx]), axis=1)) ** 2
    spec = spec[:, :int(fmax / (SR / n_fft))]
    db = 10 * np.log10(spec + 1e-12)
    db = np.clip((db - (db.max() - 90)) / 90, 0, 1)
    img = (db.T[::-1] * 255).astype(np.uint8)
    img = cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(cv2.applyColorMap(img, cv2.COLORMAP_MAGMA), cv2.COLOR_BGR2RGB)


def sheet(items: list[dict | str | Path], png: str | Path, root: Path = LIB) -> Path:
    """1 行に 1 音: 波形とスペクトログラム (0〜12kHz)。山の位置に線。聞けない代わりにこれを見て選ぶ。"""
    import skia

    from .text import text as draw_text
    rows = []
    for it in items:
        if isinstance(it, dict):
            path = root / it["file"] if "file" in it and not Path(it["file"]).is_absolute() else Path(it["file"])
            label = it.get("id") or Path(it["file"]).stem
            info = it
        else:
            path = Path(it)
            label = path.stem
            side = path.with_suffix(".json")
            info = json.loads(side.read_text(encoding="utf-8")) if side.exists() else {}
            if info.get("verdict"):
                label += f"  {info['verdict']}"
        rows.append((decode(path), label, info))
    W, rh, lw = 1400, 118, 420
    surf = skia.Surface(W, max(len(rows), 1) * rh + 20)
    c = surf.getCanvas()
    c.clear(skia.Color(18, 18, 22))
    for k, (x, label, info) in enumerate(rows):
        y0 = 10 + k * rh
        draw_text(c, label[:70], 14, y0 + 6, font="mono", size=13, color="#E8E8EC", valign="cap")
        meta = (f"{info.get('dur_s', len(x) / SR):.2f}s  山 {info.get('peak_s', 0):.3f}s  明るさ {info.get('centroid_hz', '?')}Hz  "
                f"<150Hz {info.get('below150', '?')}  >6k {info.get('above6k', '?')}")
        draw_text(c, meta, 14, y0 + 26, font="mono", size=11, color="#8A8C97", valign="cap")
        gy, gh = y0 + 40, rh - 50
        n = lw - 28
        if len(x):
            k_ = max(len(x) // n, 1)
            env = np.abs(x[:k_ * n]).reshape(-1, k_).max(axis=1) if len(x) >= n else np.abs(x)
            env = env / (env.max() + 1e-9)
            p = skia.Paint(Color=skia.Color(140, 170, 230), AntiAlias=True)
            for i, v in enumerate(env):
                c.drawLine(14 + i, gy + gh / 2 - v * gh / 2, 14 + i, gy + gh / 2 + v * gh / 2, p)
            if "peak_s" in info:
                px = 14 + n * info["peak_s"] / max(len(x) / SR, 1e-6)
                c.drawLine(px, gy, px, gy + gh, skia.Paint(Color=skia.Color(255, 122, 69), StrokeWidth=1.5))
        sp = _spectrogram(x, W - lw - 20, gh + 30)
        rgba = np.dstack([sp, np.full(sp.shape[:2], 255, np.uint8)])
        c.drawImage(skia.Image.fromarray(np.ascontiguousarray(rgba), colorType=skia.kRGBA_8888_ColorType), lw, y0 + 10)
        for f in (2000, 6000, 10000):
            fy = y0 + 10 + (gh + 30) * (1 - f / 12000)
            draw_text(c, f"{f // 1000}k", lw + 4, fy, font="mono", size=10, color="#FFFFFFAA", valign="cap")
    png = Path(png)
    png.parent.mkdir(parents=True, exist_ok=True)
    import cv2
    img = surf.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)
    cv2.imwrite(str(png), cv2.cvtColor(img, cv2.COLOR_RGBA2BGR))
    return png
