# @shneural のモーションリール制作環境 (2026-10-04 調査)

出典: https://x.com/shneural/status/2103151003272962130 と作者本人のリプライ (2103441806532706655, 2103259736707850356, 2103423477281706342, 2103443810621727230, 2103443283624018379, 2103472385563459833)

## 作者が明かした構成

- 素の Claude Code + Opus 5.5、最大推論 (effort max)、メモリオフ。スキル・プラグインなし
- プロンプトは 1 文のみ、ワンショット、人手編集ゼロ、共有アセットなし
  - "make a dynamic 15-second motion graphics video that shows what an incredible motion designer you are, like it's your showreel for a résumé. go all out."
- マシンに入っていたレンダリング環境 (使えとは指示していない)
  - ドラムサンプルライブラリ (909 / 808 + 無料パック)
  - Surge XT (シンセ) と VST エフェクト数種
  - Blender MCP
- 生成物はすべてコード
  - 2D: skia-python で自作のフレームレンダリングエンジンを書かせた
  - 3D: Blender スクリプト (Opus が自発的に Blender を選んだ)
  - 音: サンプルをビートグリッド上にシーケンスしてミックスする Python スクリプト
- 15 秒 / 60fps / 900 フレーム / 1920x1080、120BPM のビートグリッドに同期
- 所要: レンダリングを除いて約 1.5 時間。総計 1 時間 32 分・API 換算 81 ドル (Max 20x の週制限の約 3%)

## 再現の要点

- 環境 (ツールとアセット) を用意し、プロンプトでは使い方を指示しないのが肝。モデルが手元のツールを見つけて使う
## 手元の導入状況

- Chrome / Blender / Surge XT は `~/nix-config` の `desktopCasks` で宣言。`cleanup = "zap"` のため未宣言の cask は darwin-rebuild で消える
- skia-python / numpy はこのリポジトリの uv 環境 (`pyproject.toml`)
- Blender MCP は `mcp-for-blender` (ahujasid/blender-mcp)。サーバは `.mcp.json` に project スコープで登録、アドオンは Blender 5.2 に導入済みで、Blender 起動時に port 9876 で自動起動
- ドラムサンプルは `~/Music/Samples/Dirt-Samples` (tidalcycles/Dirt-Samples)。808 フルキット・909・bd/sn/hh/cp 等。リポジトリにライセンス表記はない
