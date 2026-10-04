# claude-movie-test

コードだけでモーショングラフィックス動画 (映像・3D・音楽) を制作するリポジトリ。
目的は良い動画を作ること。ワンショットの再現にはこだわらず、ユーザーとの対話・反復・ハーネスを積極的に使う。

## 動画エンジン `motion/`

作品は `projects/<名前>/project.py` に置き、`build() -> Composition` を定義する。見本は `projects/demo/project.py`。

```sh
uv run python -m motion render projects/demo            # 1080p・音付きで build/demo/demo.mp4
uv run python -m motion render projects/demo --draft    # 半解像度・ブラーなし・高速エンコード
uv run python -m motion render projects/demo --start 2 --end 4
uv run python -m motion sheet projects/demo             # コンタクトシート (build/demo/sheet.png)
uv run python -m motion still projects/demo 3.5         # 1 フレームの PNG
uv run python -m motion audio projects/demo             # 音だけ
uv run python -m motion patches pads/                   # Surge XT のパッチ検索
uv run python -m motion audition pads/ -n 8             # 候補を同じ和音で順に鳴らした build/audition.wav
```

| モジュール | 役割 |
|---|---|
| `scene` | `Composition` (解像度・fps・BPM・シーン・ポスト・カメラ・キュー・音)、`Scene` / `@scene(start, end)`、`Ctx` (t, lt, p, tl, W, H, CX, CY) |
| `timeline` | `beat(n)` `bar(n)` `step(n, div)` `beat_at(t)` `pulse(t)` |
| `anim` / `easing` | `tween` `progress` `Keys` `spring` `stagger` `window` `impact`、各種イージングと `cubic_bezier` |
| `draw` / `color` | 図形・パス・`trim`・`transform` / `layer` / `clip_rect`、`Color` `Palette` |
| `text` | harfbuzz で組み、可変フォントの軸を指定して描く。`letters()` で 1 文字ずつ動かせる。フォントは `assets/fonts` (`sans` / `sans-mono` / `mono`) |
| `noise` | `perlin3` `fbm3` `curl2` `noise1` `hash01` |
| `post` | `bloom` `chroma` `grain` `vignette` `glitch` `scanlines` `flash` `grade`。引数に `lambda ctx: ...` を渡せる |
| `audio` | `Mix`: `hit` (サンプル)、`tone` (内蔵シンセ)、`instrument` (Surge XT 等の VST3。`patch="Pads/MKS-70 Warm Pad"` でパッチ指定)、`fx` `duck`、`render` で LUFS を揃えて wav 出力 |
| `blender` | `render_plate` で Blender をヘッドレス実行して連番 PNG を作る (入力が同じならキャッシュ)。`Plate` で時刻から引いて合成。初回だけ Metal カーネルのコンパイルに数分かかる |

- 描画は `f(t)` で決定的に書く (乱数はシード固定か `noise.hash01`)。並列ワーカーがフレームをばらばらに描くため、フレーム間で状態を持ち越さない。シミュレーションは `Scene.setup` で一括して前計算する
- 映像と音で同じ `comp.cues` を使うと、カメラシェイク・フラッシュ・音のアタックが揃う
- 仕上がりは `sheet` / `still` の画像を自分で見て確認してから、本番の `render` に進む

## 参考資料

- `Knowledge/motion-engine-design.md`: このエンジンの設計判断
- `Knowledge/shneural-engine-anatomy.md`: 自作 Python エンジンの構成例 (BPM 基準の core、シーンごとのファイル、`f(t)` 型のレンダラ、コンタクトシートでの自己レビュー)
- `Knowledge/opus55-video-stack-survey.md`: 他の事例の技術スタックと品質を上げる工夫
- `Knowledge/shneural-motion-reel-setup.md`: 参考にしたツイートと制作環境

## 使えるツール

| 用途 | ツール | 場所・使い方 |
|---|---|---|
| 2D 描画 | skia-python, numpy | このリポジトリの uv 環境 (`uv run python ...`) |
| 文字組み | uharfbuzz | uv 環境。可変フォントの軸 (wght / wdth 等) を指定したシェーピング |
| ポスト処理 | opencv-python | uv 環境。bloom・色収差・グリッチ・グレイン等 |
| 3D | Blender 5.2 | CLI: `blender --background --python <script>`。GUI 操作は Blender MCP (`.mcp.json` の `blender`、Blender 起動中のみ有効) |
| シンセ | Surge XT | VST3: `/Library/Audio/Plug-Ins/VST3/Surge XT.vst3`。プリセットは `/Library/Application Support/Surge XT/` |
| エフェクト | Surge XT Effects | VST3: `/Library/Audio/Plug-Ins/VST3/Surge XT Effects.vst3` |
| VST ホスト | pedalboard | uv 環境。`pedalboard.load_plugin(<vst3 パス>)` で上記 VST3 を Python から鳴らす・かける |
| ドラムサンプル | Dirt-Samples | `~/Music/Samples/Dirt-Samples/` (808bd, 808sd, 808hc, 808oh, 909, bd, sn, hh, cp など) |
| エンコード | ffmpeg | `/opt/homebrew/bin/ffmpeg` |

## Git 運用

- main で直接作業し、コミットと push は確認なしで行ってよい (ship / PR フローは使わない)。コミット規約は commit スキルに従う

## 環境の管理

- アプリ (Blender, Surge XT, Chrome) は `~/nix-config` の Homebrew cask で宣言管理している。手動の `brew install` はしない
- Python パッケージは `uv add` で追加する
