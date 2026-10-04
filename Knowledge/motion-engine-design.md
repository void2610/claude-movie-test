# motion エンジンの設計判断 (2026-10-04)

## 方針

- @shneural のエンジン (`shneural-engine-anatomy.md`) を下敷きにしつつ、作品ごとの定数をハードコードせず、`Composition` に寄せて使い回せるようにした
- 作品は `projects/<名前>/project.py` の `build()` で組み立てる。エンジンと作品を分け、作品は短いコードで書けるようにする

## 判断と理由

- **`f(t)` で決定的に描く**: フレームを並列にばらばらの順で描くため。モーションブラーのサブフレームも同じ関数を `t ± dt` で呼ぶだけで済む
- **ワーカーごとにプロジェクトを読み直す (spawn)**: skia のオブジェクトは pickle できない。親プロセスは RGB のバイト列を受け取り、順番どおり ffmpeg に rawvideo でパイプする (PNG を経由しないので速い)
- **`Scene.setup` で前計算**: 粒子などのシミュレーションは時間方向に依存するため、ワーカーごとに一度だけ全区間を計算してキャッシュし、描画は補間で引く
- **`Composition.prepare` はメインプロセスで実行**: Blender のプレート生成は重く、並列ワーカーが同時に走らせると競合するため
- **`comp.cues` を映像と音で共有**: カメラシェイク・フラッシュ・色収差・効果音のタイミングを 1 か所で定義すると、ずれない
- **ポスト処理の量は 1080p 基準**: `--draft` やコンタクトシートで解像度を落としても、見た目の比率が変わらない
- **文字組みは harfbuzz → skia の TextBlob**: skia 単体の drawString はカーニングもリガチャも効かないため
- **自作の先読み型ピークリミッター**: pedalboard の `Limiter` (JUCE) は閾値の値に応じて出力レベルが予測しにくく変わり、ラウドネスを目標値に揃えられなかった。リミット → 計測 → ゲイン調整を繰り返して目標の LUFS に収束させる

## ハマりどころ

- skia-python の可変フォント: `FontArguments().setVariationDesignPosition(pos)` の戻り値を `makeClone` に渡すと指定が失われる。`FontArguments` を変数に保持してから渡す
- skia-python に `SetFourByteTag` は無い。タグは `int.from_bytes(b"wght", "big")` で作る
- 可変フォントでない書体に `getVariationDesignParameters()` を呼ぶと RuntimeError になる
- 可変軸の値は 0.5 単位に丸めてキャッシュする。アニメーションで毎フレーム値が変わると、書体のクローンが際限なく増える

## 性能の目安 (M 系 Mac)

- デモ (1080p60・8 秒・モーションブラー 4 倍・ポスト 5 段): 480 フレームを約 85 秒
- Blender Cycles (Metal): 初回だけカーネルのコンパイルに約 3 分。以降は 320x180・3 フレームで約 3 秒
