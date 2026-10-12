# ManimGX: エージェント向けの 3D アニメーションエンジン (2026-10-12 調査)

出典: @sinaatalay の投稿 (2026-10-11)、github.com/academa-labs/manimgx、manimgx.academa.ai (llms.txt・developer-guide/engine・reference/rendering/command-line)

## 何か

- Manim Community Edition と同じ Python API (型注釈つき) で、数学・3D の動画を作る。描画は Rust + wgpu (Metal / D3D12 / Vulkan、GPU が無ければ同梱の lavapipe で CPU)。文字と数式は Typst (LaTeX は mitex で変換)、エンコードは同梱の x264
- `pip install manimgx` だけで動く (65〜110MB、Python 3.13 以上、LaTeX・FFmpeg 不要)。ブラウザでも Pyodide + WebGPU で同じシーンを動かせる
- ライセンス: 本体は MIT だが、ネイティブの wheel は x264 を含むので全体として GPL-3.0-or-later
- 3D: PBR 材質・画像ベースのライティング・AO・ブルーム・AgX トーンマッピング (Google Filament を移植)

## 速さ

- 1080p60・合計 36.2 秒 (5 シーン) を起動から MP4 まで 3.08 秒 (M4 Pro)。ManimCE の 90.6 倍、ManimGL の 11.5 倍、Blender Workbench の 18.7 倍
- 1 コマの描画は 2560×1440 で中央値 0.5〜1.7ms
- 工夫: 形状は鍵つきで GPU に 1 度だけ送り、毎コマは「ビュー」と「レコード (1 件 336 バイト)」だけ渡す。曲線は画面上の大きさに応じて GPU で分割 (1/32px、最大 256 本)。MSAA ではなく解析的な被覆。変化したマクロブロックだけを GPU で NV12 にして読み戻し、x264 は別スレッドで変化の無い領域の解析を省く。描画とエンコードの間は GIL を外す。GPU の初期化は別スレッドで、最初のコマだけが待つ
- このエンジン (skia の CPU 描画 + プロセス並列) は liminal_poster の 720 コマ (1080×1080、モーションブラーとポスト処理あり) で約 14 秒 = 約 50 コマ/秒。グレインで毎コマ全画素が変わるため、「変化した領域だけエンコード」は効かない

## エージェント向けの確認手段

- `manimgx inspect`: 動画を作らずに、各 play / wait の終わりの時点 (または `-t 1.5,end`) を描いてストーリーボード PNG (1 枚 6 コマ、各コマに `#play t=… file:line`) とタイムラインを出す。レイアウトの問題に番号つきの枠を付け、1 件でもあれば終了コード 1
- 2D のレイアウト検査の種類: 内容の見切れ (「左の縁を 4.89 はみ出す」)、文字どうしの重なり、線や塗りが文字を横切る (「Polygon runs through the text」)、小さすぎる文字 (「1080p で 20px」)。グラフが枠から出るなどは注記で、終了コードに影響しない。3D のシーンは検査しない
- 検査は区切りの時点だけ。このエンジンの `review` の文字の重なりは全コマを見る (2026-10-11 追加)
- `manimgx preview`: 保存のたびに作り直し、再生位置を保ち、エラーは最後に描けたコマの上に出す (このエンジンのスタジオも同じ動き)
- ナレーション: `self.say("The derivative of [x squared] is [two x].", anim1, anim2)` で、括弧の語が読まれる時刻に各アニメーションを始める。TTS は差し替え可能で、render が字幕 (.srt) も書き出す
- エラーは失敗した行と、Manim CE からの名前の違いのヒント (ShowCreation → Create) を出す。毎コマのコールバックはコマ数を数えず時刻から状態を決める (このエンジンの `f(t)` と同じ原則)

## このエンジンへの取り込み (2026-10-12)

- **文字の検査**: `inspect` の 4 種類のうち、文字どうしの重なり (2026-10-11)、小さすぎる文字・縁での見切れ (2026-10-12) を `review` の全コマの検査にした。線や図形が文字を横切る検査は、図形の形まで記録する必要があるので見送り。判断の詳細は `motion-engine-design.md`
- **ストーリーボードの番号と `file:line`**: `review` のシートで、問題の要素を番号つきの赤枠で囲んだ切り出しと、要素を描いたコードの場所 (`project.py:331 › 280`) を出す。review.md とターミナルにも同じ番号と場所を出す
- **プレートの素材**: `motion.mgx.MgxPlate` で ManimGX のシーンを透明な背景の連番 PNG にして合成する
  - `Scene.render(frames=fn)` で各コマが `Frame` として届き、`pixels()` が RGBA を返す。`m.config.background_opacity = 0` で背景が透ける。色はアルファを掛けた形 (premultiplied) で返るので、PNG に保存する前に戻す (戻さないと読み込みで二重に掛かり縁が暗くなる)
  - 同じ画面が続くコマは `repeat` つきで 1 回しか届かないので、残りのコマはハードリンクで埋める
  - ManimGX の設定は全体で 1 つなので、別のプロセス (`python -m motion.mgx_rt`) で動かす。書き出しの前にメインプロセスで 1 度だけ作り (`comp.prepare`)、入力 (シーンのファイル・パラメータ・大きさ・fps・ManimGX の版) が同じなら作り直さない
  - 1080×1080・60fps・3 秒の 3D (トーラスと球、181 コマ): ManimGX の描画と読み戻しは 0.48 秒、PNG の保存が 5〜7 秒で律速だった。保存をスレッドで並べ (cv2 はロックを外して動く)、圧縮を 1 にして、全体で 2.8 秒。描画の方が速いので、保存待ちは CPU 数の 2 倍までに抑える (1 コマ 4.7MB)
  - ManimGX は Python 3.13 以上だけに対応する。このプロジェクトの `requires-python` (>=3.12) は変えず、`python_version >= '3.13'` の条件付きの依存にした
  - Manim の `YELLOW` は #F7D96F、`Sphere` は既定で市松模様 (`color` だけでは単色にならない)

