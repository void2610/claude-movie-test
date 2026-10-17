"""音を言葉で聞く: CLAP (laion/larger_clap_general) で、録音が説明にどれだけ合うかを z で返す。

    ears.describe("rain.wav")                  # [(語, 分類, z)] 語彙 322 語のうち、この音で目立つ順
    ears.match(["a.wav", "b.wav"], "wind blowing")   # 各ファイルの z (3 以上で強い一致、2.5 以上でありそう)

生のコサインは音ごとに偏る (密な音は何を言っても高い) ので、earshot (MIT, data/earshot.LICENSE) の較正に倣い、
語の偏り (241 録音の平均埋め込みとの内積) を引いてから、その音で語彙 322 語に対する z にする。
初回にモデル (約 800MB) を Hugging Face から取得する。埋め込みは ~/.cache/motion/ears に保存し、同じファイルは 2 度測らない。
"""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

import numpy as np

MODEL = "laion/larger_clap_general"
SR = 48000
WIN_S, HOP_S, MAX_WIN = 10.0, 5.0, 6
CACHE = Path.home() / ".cache" / "motion" / "ears"
DATA = Path(__file__).parent / "data"
VERDICTS = [(3.0, "強い一致"), (2.5, "ありそう"), (2.0, "弱い")]


def verdict(z: float) -> str:
    return next((name for t, name in VERDICTS if z >= t), "合わない")


@lru_cache(maxsize=1)
def _model():
    import logging
    import os
    # 取得済みならネットに問い合わせない (無認証の警告と、オフラインでの待ちを避ける)
    hub = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"
    if (hub / f"models--{MODEL.replace('/', '--')}" / "snapshots").exists():
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
    logging.getLogger("torch.distributed.elastic.multiprocessing.redirects").setLevel(logging.ERROR)
    import torch
    from transformers import ClapModel, ClapProcessor
    from transformers.utils import logging as hf_logging
    hf_logging.set_verbosity_error()
    torch.set_num_threads(max(1, min(8, (torch.get_num_threads() or 2))))
    return ClapModel.from_pretrained(MODEL).eval(), ClapProcessor.from_pretrained(MODEL), torch


def _unit(e: np.ndarray) -> np.ndarray:
    return (e / (np.linalg.norm(e, axis=-1, keepdims=True) + 1e-12)).astype(np.float32)


def _text_raw(texts: list[str]) -> np.ndarray:
    model, proc, torch = _model()
    with torch.inference_mode():
        e = model.get_text_features(**proc(text=texts, return_tensors="pt", padding=True))
    return _unit(getattr(e, "pooler_output", e).float().numpy())


def embed_text(phrases: list[str] | str) -> np.ndarray:
    """(n, 512)。各語を 5 つの言い回し (earshot と同じ) に通した平均。語ごとにディスクに保存する。"""
    phrases = [phrases] if isinstance(phrases, str) else list(phrases)
    templates = _vocab_json()["templates"]
    d = CACHE / "text"
    out, todo = {}, []
    for p in phrases:
        f = d / f"{hashlib.sha1(p.encode()).hexdigest()[:20]}.npy"
        if f.exists():
            out[p] = np.load(f)
        else:
            todo.append(p)
    if todo:
        d.mkdir(parents=True, exist_ok=True)
        flat = _text_raw([t.format(p) for p in todo for t in templates])
        for i, p in enumerate(todo):
            out[p] = _unit(flat[i * len(templates):(i + 1) * len(templates)].mean(axis=0))
            np.save(d / f"{hashlib.sha1(p.encode()).hexdigest()[:20]}.npy", out[p])
    return np.stack([out[p] for p in phrases]) if phrases else np.zeros((0, 512), np.float32)


def _windows(x: np.ndarray) -> list[np.ndarray]:
    """10 秒までは 1 窓 (短い音はプロセッサが繰り返して 10 秒に埋める)。長い音は 5 秒刻みの 10 秒窓を最大 6 つ等間隔に。"""
    w, h = int(WIN_S * SR), int(HOP_S * SR)
    if len(x) <= w:
        return [np.pad(x, (0, max(0, 480 - len(x))))]
    st = list(range(0, len(x) - w + 1, h))
    if (len(x) - w) % h:
        st.append(len(x) - w)
    if len(st) > MAX_WIN:
        st = [st[int(round(i))] for i in np.linspace(0, len(st) - 1, MAX_WIN)]
    return [x[s:s + w] for s in st]


def embed_audio(arrays: list[np.ndarray], batch: int = 8) -> np.ndarray:
    """48kHz モノラルの波形ごとに (512,)。長い音は窓の平均。"""
    model, proc, torch = _model()
    segs, owner = [], []
    for j, x in enumerate(arrays):
        for s in _windows(np.asarray(x, np.float32)):
            segs.append(s)
            owner.append(j)
    out = []
    for i in range(0, len(segs), batch):
        inp = proc(audio=segs[i:i + batch], sampling_rate=SR, return_tensors="pt")
        with torch.inference_mode():
            e = model.get_audio_features(**inp)
        out.append(_unit(getattr(e, "pooler_output", e).float().numpy()))
    e, owner = np.concatenate(out), np.array(owner)
    return _unit(np.stack([e[owner == j].mean(axis=0) for j in range(len(arrays))]))


def _file_key(p: Path) -> str:
    st = p.stat()
    return hashlib.sha1(f"{p.resolve()}|{st.st_mtime_ns}|{st.st_size}|{MODEL}".encode()).hexdigest()[:24]


def embed_files(paths: list[str | Path], progress: bool = False) -> np.ndarray:
    """(n, 512)。ファイルの中身が変わらなければ保存した埋め込みを使う。"""
    from .audio import load
    paths = [Path(p) for p in paths]
    d = CACHE / "audio"
    d.mkdir(parents=True, exist_ok=True)
    keys = [_file_key(p) for p in paths]
    todo = [i for i, k in enumerate(keys) if not (d / f"{k}.npy").exists()]
    for n, i0 in enumerate(range(0, len(todo), 32)):
        chunk = todo[i0:i0 + 32]
        embs = embed_audio([load(str(paths[i])).mean(axis=0) for i in chunk])
        for i, e in zip(chunk, embs):
            np.save(d / f"{keys[i]}.npy", e)
        if progress:
            print(f"ears: {min(i0 + 32, len(todo))}/{len(todo)}", flush=True)
    return np.stack([np.load(d / f"{k}.npy") for k in keys]) if keys else np.zeros((0, 512), np.float32)


@lru_cache(maxsize=1)
def _vocab_json() -> dict:
    return json.loads((DATA / "earshot_vocab.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def vocab() -> tuple[list[str], list[str], np.ndarray, np.ndarray]:
    """(語, 分類, 語の埋め込み, 241 録音の平均埋め込み)。"""
    v = _vocab_json()
    names = [t for ts in v["categories"].values() for t in ts]
    cats = [c for c, ts in v["categories"].items() for _ in ts]
    stats = json.loads((DATA / "earshot_vocab_stats.json").read_text(encoding="utf-8"))
    mean = np.array(stats["mean"], np.float32) if stats.get("model") == MODEL else np.zeros(512, np.float32)
    return names, cats, embed_text(names), mean


def calibrate(A: np.ndarray, Q: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray | None]:
    """(語彙の z (n, 322), 問いの z (n, m))。z は「この音で、その説明が語彙の中でどれだけ目立つか」。"""
    _, _, E, mean = vocab()
    A = np.atleast_2d(A)
    U = A @ E.T - E @ mean
    mu, sd = U.mean(axis=1, keepdims=True), U.std(axis=1, keepdims=True) + 1e-9
    zq = None
    if Q is not None:
        Q = np.atleast_2d(Q)
        zq = ((A @ Q.T - Q @ mean) - mu) / sd
    return (U - mu) / sd, zq


def match(paths: list[str | Path], query: str) -> np.ndarray:
    """各ファイルで query の z。"""
    _, zq = calibrate(embed_files(paths), embed_text([query]))
    return zq[:, 0]


def describe(path: str | Path, k: int = 6, embedding: np.ndarray | None = None) -> list[tuple[str, str, float]]:
    """語彙のうち、この音で目立つ上位 k 語 (語, 分類, z)。音楽の曲調・音質の語は除く (効果音・環境音を選ぶ用)。"""
    names, cats, _, _ = vocab()
    a = embedding if embedding is not None else embed_files([path])[0]
    zt, _ = calibrate(a)
    skip = {"music_genre", "music_mood", "quality", "production"}
    order = [i for i in np.argsort(-zt[0]) if cats[i] not in skip]
    return [(names[i], cats[i], float(zt[0, i])) for i in order[:k]]
