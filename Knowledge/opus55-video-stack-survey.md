# X 上の Opus 5.5 動画制作事例の技術スタック調査 (2026-10-04)

## 全体傾向

- HyperFrames 社 (@liu8in) が X で話題になったワンショットのプロンプト約 70 本を、素の Opus 5.5 (スキル・MCP・Web なし) で再実行した結果
  - 約 55%: Python でフレームを描き FFmpeg にパイプ
  - 約 1/3: Web コード。HTML を headless ブラウザでフレームごとにキャプチャ、または JS で直接描画
  - 約 10%: Blender や、プロンプトで指定されたフレームワーク
  - 共通する設計は `f(t)` (時刻からフレームを決定的に算出する関数)。74 本中 71 本が乱数をシード固定するか、乱数を使っていない
- Skillry (https://skillry.dev/ai-videos/opus-5-5) の 48 事例のタグ集計: SVG 37 / Canvas 24 / CSS 13 / GSAP 11 / Three.js 7 / GLSL 4
- 素の Opus 5.5 は Remotion / HyperFrames より依存ゼロの自作を好む (@__morse)

## 代表事例

| 投稿 | スタック | 要点 |
|---|---|---|
| @shneural 2103151003272962130 | skia-python 自作エンジン + Blender + Python で音のシーケンス (Surge XT / サンプル) | ワンショット、約 1.5h、81 ドル |
| @__morse 2103485566570369333 | 単一 index.html → Playwright でフレームごとに seek+screenshot → FFmpeg | ビート位置は Python で解析し、マジックナンバーとして埋め込み |
| @kimmonismus 2102844654169575547 | Remotion (React/TS 約 7,400 行) + SVG/Canvas + OSS TTS + Python 合成スコア | 3 分の解説映画、約 1h |
| @tequilafunks 2103528644828127728 | Remotion | shneural と同じプロンプト |
| @minosdevs 2104959910903464200 | Remotion + Three.js + GPT-image-2 | 教育系の量産 |
| @__gsk__ 2104832372164444162 | TypeScript + three.js、自作 TS DSP (144BPM の配置データ → EQ / リバーブ / サイドチェイン / リミッター → WAV)、Grok Imagine API | ワンショットではない。対話型のクリエイティブディレクション用ハーネスを自作し、50 回以上のディレクションを経た v9 |
| @LexnLin 2106101651010449796 | 参照動画 + 長い構造化プロンプト (リサーチ → ディレクション → ルール) | ultracode で実行。Opus の SFX はシンセっぽいのが弱点で、ElevenLabs を検討 |
| @Voxyz_ai 2104194355556671987 | HyperFrames + `~/.claude/agents` に 4 役のチーム | reference-breaker → storyboarder → build (main) → film-reviewer (P0/P1/P2) |
| @jesscaroline7 (Skillry) | HyperFrames スキル + iOS シミュレータ録画 + 実データ + Higgsfield | プロジェクトフォルダを参照させたことが効いた |

## HyperFrames

- heygen-com/hyperframes (★5.6 万)、npm `hyperframes` (CLI 0.8.x): HTML でコンポジションを書き、CLI で lint / check / snapshot / render する
- Opus 5.5 は学習時に HyperFrames を学んでおり、名前を出すだけで正しい契約 (`data-composition-id`, `window.__timelines`) を書く (20/20)
- CLI の制約を与えると、レンダリング回数の中央値が 2 回から 1 回に、トークンコストが約半分になる (29 組の比較)
- Code2Video Bench (Kaggle / Google DeepMind 共同) で Opus 5.5 が 1 位

## 品質を上げる工夫として共通するもの

- 参照動画を渡し、ffmpeg で 1 秒ごとのフレームをタイル状に並べた画像にして、ペーシング・タイプ・トランジションを分解させる (whatships.com に製品ローンチ動画が 2,000 本以上ある)
- レンダリング後に秒単位でフレームを見るレビュー役を分ける
- 一発勝負より、ディレクションを反復するハーネスを作るほうが意図どおりの品質になる (@__gsk__)
