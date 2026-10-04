# @shneural の自作 Python エンジンの構造 (メイキング動画の解析, 2026-10-04)

出典: https://x.com/shneural/status/2103472385563459833 (56 秒・720p)。Opus 自身がセッションのログを動画化したもので、画面は実録画ではなく再構成。ファイル名・行数・コード断片はセッションの実物と見てよい。

## セッションの流れ (Claude Code v2.1.281, Opus 5.5 1M, effort max, bypass permissions)

1. 2 分 29 秒考えてから計画を出す: 15 秒、8 小節、128 BPM、1920x1080、60fps = 900 フレーム。2D は Python + skia の自作エンジン、3D は Blender のショット 1 本、オリジナルの音楽
2. `plan.md` に 8 シーンを書き、`shared/palette.json` に 5 色を書く (#0C0C0F / #F2EEE6 / #FF5A1F / #3044FF / #8A8A8F)
3. サブエージェントを 2 体バックグラウンドで起動: 「3D plate — Blender」と「Soundtrack & SFX」。メインは 2D エンジンを書く
4. エンジンを書く → `render.py --frames 0:900:4` で 225 フレームと 8 枚のコンタクトシート (`review/sheets`) を出して自分で見る
5. 見つけた問題をパラメータ単位で直す (「グリッドの位相がずれる」「MOTION の whip が遅れて入る」「HUD の等幅フォントの字間が広すぎる」)
6. 書体を検証: `tools/specimen.py --roles hero,mono` で候補 4 書体を「EVERY」で組んで比較 → 見出しは Mona Sans Black、HUD は Fragment Mono
7. 本番レンダリング: `render.py --nsub 8` で 900 フレームを 27 秒
8. サウンドのエージェントが完了: 42 個のキューすべてが ±10ms 以内、-10.0 LUFS
9. Blender のエージェントが完了: 116 フレーム (Cycles) を 28 分 20 秒
10. `engine/final.sh assemble` で音声と合成 (3 分 13 秒) → `ffmpeg -crf 18` で X 向けに再エンコード (35MB)
11. 合計 1 時間 32 分、81.26 ドル、4,947 行

## ファイル構成

| ファイル | 行数 | 役割 |
|---|---|---|
| core.py | 547 | 時間・イージング・ノイズ・テキスト・可変フォント。skia, numpy, uharfbuzz |
| s1_bounce.py | 208 | ボールのバウンド (squash & stretch, 弧, 予備動作) |
| s2_type.py | 302 | キネティックタイプ EVERY / FRAME / is / CODE |
| s3_grid.py | 106 | ジェネレーティブなグリッド (タイルをビートに位相同期) |
| s4_plate.py | 32 | Blender のレンダー `plates/s4/f_%04d.png` を 2D の上に合成 (frame 336〜451) |
| s5_vartype.py | 203 | 可変フォントの MOTION ストライプ (wght / wdth 軸を波で揺らす) |
| s6_particles.py | 234 | 12,000 粒子、curl noise (perlin3 の差分で計算)。シミュ結果は `cache/s6_sim.npz` にキャッシュ |
| s7_montage.py | 89 | 2 / 4 / 9 分割のモンタージュ (clipRRect + scale で各シーン関数を再利用) |
| s8_end.py | 119 | エンドカード「CLAUDE.」 |
| hud.py | 77 | 四隅のフレームとタイムコード |
| post.py | 87 | bloom、色収差、グリッチ、グレイン (cv2) |
| render.py | 152 | サブフレームのモーションブラー、HUD、ポスト処理、PNG 出力 → パイプ。multiprocessing で並列化 |

## 設計の要点

- core.py に定数を集約: `W,H=1920,1080`、`FPS=60`、`DUR=15.0`、`BPM=128`、`BEAT=60/BPM`、`BAR=4*BEAT`、`STEP=BEAT/4`、`beat(n)=n*BEAT`
- シーンはどれも `from core import *` で始まり、`T0, T1 = k*BAR, (k+1)*BAR` で受け持つ小節を宣言し、`draw(c, t)` (skia の canvas と時刻) を実装する。キーとなる拍は `B9 = beat(9)` のように名前を付ける
- render.py は `SCENES = [s1_bounce, ...]` と `scene_for(t)` で時刻からシーンを引く純粋な `f(t)` 型
- 動きの速い区間だけサブフレーム数を増やす: `FAST = [(t0, t1, k), ...]` と `nsub_for(t, base)`
- カメラシェイク: `post.env(t, post.IMPACTS, 10)` で衝撃のエンベロープを取り、noise1 で平行移動と微小ズームをかける。IMPACTS (音のキューと同じ拍) を映像と音で共有している
- 重い素材はキャッシュする: Blender の PNG は LRU 風の dict (12 枚)、粒子は npz
- 自己レビューのループ: 4 フレームおきの低解像度レンダリング → コンタクトシートを画像として読む → パラメータを直す → 再レンダリング
- 書体はフォントの見本を作って比較し、自分で選んでいる
