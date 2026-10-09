"""`motion new <名前>` で作る作品のひな形。制作の判断をチャットではなくファイルに残すための文書つき。"""
from __future__ import annotations

from pathlib import Path

BRIEF = """# {name} ブリーフ

<!-- 書き終えるまでレンダリングしない。空欄はモデルが無難な既定値で埋めてしまう -->

## 一文
視聴者に残したいこと:

## 観客と場所
- 観客:
- 載せる場所: (X / YouTube / Steam / 登壇 …)
- 尺: {dur} 秒
- 形式: {aspect}

## 素材 (実物だけを使う)
- ロゴ:
- 画面・キャプチャ:
- 色と書体:
- 音楽・効果音:

## 守ること・避けること
- 守る:
- 避ける:
- 製品の画面や数値は捏造しない。足りない素材があれば止めて確認する

## 納品物
動画 ({aspect})、ポスター用の 1 コマ、レビューシート、ソース
"""

STYLE = """# {name} スタイル

<!-- 参照から読み取ったことを書く。形容詞ではなく値で -->

## 参照
- (動画・画像・URL)。真似するのは文法で、被写体やロゴやコピーは真似しない

## 色 (これ以外の色を使わない)
| 役割 | 値 |
|---|---|
| 背景 | #0C0C0F |
| 文字 | #F2EEE6 |
| アクセント (変化したもの・答えにだけ使う) | #FF5A1F |

## 書体
- 見出し: sans (Mona Sans) wght 900 / wdth 110
- 本文・ラベル: mono
- サイズは 3 階層まで

## 動き (motion.rules の種類で指定する)
| 要素 | 種類 |
|---|---|
| 小さな UI | micro / ui |
| パネル・カード | panel |
| 見出し | headline |
| カメラ | camera (活発さ 1〜5 のうち: 3) |

## 質感
- (グレイン、紙、ハーフトーン、なし …)

## 避ける定番
- 中央の大きな文字 + グラデーション背景 + 全部フェードイン + 最後にロゴ
- 全要素が同時に同じ尺で動く
- 0 フレーム目が真っ黒
"""

SHOTLIST = """# {name} ショットリスト

<!-- 効果の羅列ではなく「その時点で視聴者が何を知っているか」を書く。存在理由を言えないショットは消す -->

| 時間 | ショット | 目的 | 入り | 出 |
|---|---|---|---|---|
| 0-2 | hook | 最初の 2 秒で見続ける理由を作る | | |
| 2-5 | problem | 不便さを文章ではなく絵で見せる | | |
| 5-9 | reveal | 実物の操作で製品が登場する | | |
| 9-13 | proof | 主張を 1 つの画面か数字で裏づける | | |
| 13-{dur} | close | 読める行動喚起で止める (最後のコマがポスターになる) | | |
"""

PROJECT = '''"""{name}。制作の判断は brief.md / style.md / shotlist.md にある。"""
from pathlib import Path

from motion import Composition, Palette, post, rules, scene, text
from motion.shots import ShotList

HERE = Path(__file__).parent
pal = Palette(bg="#0C0C0F", fg="#F2EEE6", accent="#FF5A1F")


def build(aspect: str = "{aspect}") -> Composition:
    shots = ShotList.from_md(HERE / "shotlist.md")
    W, H = {{"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080)}}[aspect]
    comp = Composition(width=W, height=H, duration=shots.duration, bpm=120, background=pal.bg, shots=shots,
                       motion_blur=3)

    def placeholder(shot):
        @scene(shot.start, shot.end)
        def draw(c, ctx):
            p = rules.enter("headline", ctx.t, shot.start)
            text.text(c, shot.name.upper(), W * 0.08, H * 0.46, size=W * 0.07, axes={{"wght": 900}},
                      color=pal.fg, alpha=min(p, 1.0))
            text.text(c, shot.purpose, W * 0.08, H * 0.46 + W * 0.05, size=W * 0.022, color=pal.accent)
        return draw

    comp.add(*[placeholder(s) for s in shots])
    comp.post = [post.vignette(0.3), post.grain(0.02)]
    return comp
'''

def create(name: str, root: str | Path = "projects", aspect: str = "16:9", dur: int = 16) -> Path:
    d = Path(root) / name
    if (d / "project.py").exists():
        raise FileExistsError(f"{d} は既にある")
    (d / "assets").mkdir(parents=True, exist_ok=True)
    (d / "reviews").mkdir(exist_ok=True)
    kw = {"name": name, "aspect": aspect, "dur": dur}
    (d / "brief.md").write_text(BRIEF.format(**kw), encoding="utf-8")
    (d / "style.md").write_text(STYLE.format(**kw), encoding="utf-8")
    (d / "shotlist.md").write_text(SHOTLIST.format(**kw), encoding="utf-8")
    (d / "project.py").write_text(PROJECT.format(**kw), encoding="utf-8")
    return d
