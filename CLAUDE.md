# claude-movie-test

コードだけでモーショングラフィックス動画 (映像・3D・音楽) を制作するリポジトリ。
目的は良い動画を作ること。ワンショットの再現にはこだわらず、ユーザーとの対話・反復・ハーネスを積極的に使う。

## 参考資料

- `Knowledge/shneural-engine-anatomy.md`: 自作 Python エンジンの構成例 (BPM 基準の core、シーンごとのファイル、`f(t)` 型のレンダラ、コンタクトシートでの自己レビュー)。新しく作るときはこれを下敷きにする
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

## 環境の管理

- アプリ (Blender, Surge XT, Chrome) は `~/nix-config` の Homebrew cask で宣言管理している。手動の `brew install` はしない
- Python パッケージは `uv add` で追加する
