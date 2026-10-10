# claude-movie-test

コードだけでモーショングラフィックス動画 (映像・3D・音楽) を制作するリポジトリ。
目的は良い動画を作ること。ワンショットの再現にはこだわらず、ユーザーとの対話・反復・ハーネスを積極的に使う。

## 動画エンジン `motion/`

作品は `projects/<名前>/project.py` に置き、`build() -> Composition` を定義する。見本は `projects/demo/project.py`。

### 制作の進め方

1. `uv run python -m motion new <名前>` でひな形を作り、`brief.md` → `style.md` → `shotlist.md` を埋める。空欄のままレンダリングしない (モデルが無難な既定値で埋め、凡庸な定番になる)
2. 素材 (ロゴ・画面・キャプチャ・音) は実物だけを使う。足りなければ止めてユーザーに確認し、それらしいものを捏造しない
3. 最も大事な 1 ショットを先に作り、`still` で見せて方向性の合意を取ってから他を作る
4. `review` のシートと review.md で最も大きな欠点を 3 つ、時刻・根拠・局所的な修正つきで書き、その区間だけ直して `review` し直す。`review` は等倍の画素で検査し (縁での見切れ・1 フレームの閃き・ループ・全コマでの別々の要素の文字の重なり・作品ごとの `comp.checks`)、エラーが 1 件でも残ると失敗で終わる。エラーが 0 件になるまで完了と報告しない
6. 調整はスタジオ (`motion studio`) で行う。人間は映像の要素を直接つかんで動かす・拡大縮小・回転し、文言・色・出のタイミングを変える。そのため作品のコードでは、画面に描く要素を必ず `node(c, ctx, "名前", origin=..., span=...)` (2.5D のカードは `Card(id=...)`) で名前を付けて囲み、文言・色など人間が変えそうな値は `n.prop("text", 既定値)` で読み、アニメーションの時刻は `ctx.t` ではなく `n.t` を使う。作品全体に効く値 (BPM 由来の時刻など) だけ `tune()` にする
   - 人間の変更は作品の `edits.json` に要素の名前ごとの差分 (dx, dy, dz, scale, rot, opacity, dt, hidden, props) で残り、書き出しにもそのまま反映される。作業の前に読み、人間が何をどう変えたかを把握する。要素の名前は変えない (変えると差分が外れる)。コードを大きく作り直すときは、差分をコードの既定値に取り込んでから edits.json の該当項目を消す
   - `dt` は要素の入りと抜けを同じだけずらす (スタジオの操作が「全体をずらす」しか無いため)。コードに取り込むときは、人間が動かしたかったのが入りか抜けかを決め、もう片方は前後の要素との受け渡し (前の要素が抜けきる・次の要素が入る時刻) に合わせて置き直す
   - 1 つのショットで迷ったら、案を `variants.json` に複数書いて (`tune` の値か `build()` の引数の違い) `motion variants` で書き出し、ユーザーにスタジオの「案」で選んでもらう。選ばれた案は `chosen` に入るので、その値を作品に取り込む
   - メモは作品の `notes.md` に「- [ ] 08.30s [要素名] 本文」で残る。作業前に読み、未完了の項目をその時刻・その要素だけ直して `[x]` にする
7. ユーザーから見た目の指摘を受けたら、直す前にその症状を `comp.checks` に `Check` として書き、今の版で失敗することを確かめてから直す (同じミスを別の作品で繰り返さないため)。どの作品でも起こりうる症状 (文字の重なりなど) は、作品ではなく `review` の検査としてエンジンに足し、他の作品で誤検出が無いことも確かめる。意図した例外だけ理由つきの `Waiver` にする
5. 縦長・正方形は切り抜きではなく、同じ素材とショットで別の構成として組む (`--set aspect=...`)

```sh
uv run python -m motion render projects/demo            # 1080p・音付きで build/demo/demo.mp4
uv run python -m motion studio projects/liminal_poster  # スタジオ: タイムライン・パラメータ・メモ・レビュー・書き出し
uv run python -m motion preview projects/demo           # 軽量なプレビュー (シーク・再生のみ)
uv run python -m motion render projects/demo --draft    # 半解像度・ブラーなし・HW エンコード
uv run python -m motion render projects/demo --start 2 --end 4
uv run python -m motion new myfilm --aspect 1:1         # 制作文書つきのひな形 (projects/myfilm)
uv run python -m motion review projects/demo            # 批評用シート + review.md (projects/demo/reviews/)
uv run python -m motion variants projects/demo          # variants.json の全案の下書き → スタジオの「案」で並べて同時に再生して選ぶ
uv run python -m motion sheet projects/demo             # コンタクトシート (build/demo/sheet.png)
uv run python -m motion still projects/demo 3.5         # 1 フレームの PNG
uv run python -m motion onion projects/demo 2.0 2.8     # 区間のコマを重ねて動きの経路と加減速を 1 枚で見る
uv run python -m motion audio projects/demo             # 音だけ
uv run python -m motion patches pads/                   # Surge XT のパッチ検索
uv run python -m motion audition pads/ -n 8             # 候補を同じ和音で順に鳴らした build/audition.wav
uv run python -m motion sfx browse hit --like "metal heavy"  # 効果音の候補と波形・スペクトログラムの画像 (build/sfx.png)
uv run python -m motion sfx search "page turn" --type paper  # ライブラリに無い音を CC0 から探す → sfx add で足す
uv run python -m motion analyze song.mp3                # 既存の曲の BPM・小節頭・強いオンセット
uv run python -m motion scan capture.mp4 --top 6        # キャプチャの見せ場の候補とシーンの切れ目 (グラフ画像つき)
uv run python -m motion render projects/devlog --set aspect=9:16          # build(aspect="9:16") で書き出す
uv run python -m motion render projects/devlog --start 3 --end 8 -o x.gif # GIF / .webm も拡張子で切り替わる
uv run pytest                                           # テスト (描画を意図して変えたら UPDATE_GOLDEN=1 で基準画像を更新)
```

| モジュール | 役割 |
|---|---|
| `scene` | `Composition` (解像度・fps・BPM・シーン・ポスト・カメラ・キュー・音・`linear`・`silence_ok`)、`Scene` / `@scene(start, end)` (`fixed=True` でカメラ無視)、`Ctx` (t, lt, p, tl, W, H, CX, CY)、`Cue(t, kind, hero)` (秒として使えるキュー。kind は cut / move / land / appear) |
| `transition` | `Transition(a, b, at, dur, kind)` (cut / crossfade / push / wipe / iris / slices / zoom / tear)、`mask` `matte` `montage` |
| `timeline` | `beat(n)` `bar(n)` `step(n, div)` `beat_at(t)` `pulse(t)` |
| `shots` | `ShotList.from_md("shotlist.md")` を `Composition(shots=...)` に渡すと、`shots["proof"].start` のように時刻を引け、`review` がショットごとにコマを選ぶ |
| `rules` | 動きの種類 (micro / ui / panel / headline / playful / camera / move) ごとの `enter` `leave` `scale_in`、`peak_time` / `land_time` (風切り・着地の音を置く時刻を動きの定義から出す。手で打たない)、`read_time` (文字列を読ませる最低時間)、`stagger` (時間差の合計を抑える)。作品の中で場当たり的に曲線を作らない |
| `persp` | 2.5D。`Camera.default(ctx).orbit(yaw).dolly(k)` と `Card(center, size, rot, draw=...)` を `draw_cards` で奥から描く。`grid_floor` |
| `nodes` | `with node(c, ctx, id, origin, label, span) as n:` で要素を名前付きで描く (`n.c` に描き、`n.t` で時刻、`n.prop` で人間が変えられる値)。`props(ctx, id)` は描画を囲まずに値だけ読む。差分は `edits.json` |
| `tune` | `P = tune(HERE, T_RUN=(5.0, 3, 8), ACCENT="#FACC15", H1="...")` をモジュールの先頭で呼び、`Composition(tune=P)` に渡す。値は作品の `tune.json` に保存される |
| `checks` | `Check(name, times, fn)` (等倍の画像で症状を確かめる)、`color_along` (線の上の画素の色)、`edge_clips` (縁で切れた要素)、`Waiver` (理由つきの例外) |
| `texture` | `paper` (くしゃっとした紙)、`halftone` (網点)、`misregister` (印刷の版ずれ。衝撃の時だけ強める) |
| `anim` / `easing` | `tween` `progress` `Keys` `spring` `stagger` `window` `impact`、各種イージングと `cubic_bezier` |
| `draw` / `color` | 図形・パス・`trim`・`transform` / `layer` / `clip_rect`、`Color` `Palette` |
| `text` | harfbuzz で組み、可変フォントの軸を指定して描く。`letters()` で 1 文字ずつ動かせる。日本語は `jp` (Noto Sans JP) に自動で切り替わる。`paragraph` / `layout` で禁則つきの折り返し。フォントは `assets/fonts` (`sans` / `sans-mono` / `mono` / `jp`) |
| `noise` | `perlin3` `fbm3` `curl2` `noise1` `hash01` |
| `post` | `bloom` `chroma` `grain` `vignette` `glitch` `scanlines` `flash` `grade`。引数に `lambda ctx: ...` を渡せる。光学系はリニア空間、演出系 (`fx.space = "display"`) は sRGB で処理される |
| `media` | `Image` / `Video` (動画は `comp.prepare.append(clip.prepare)` で作品の fps にフレームを書き出す)、`fit="cover" / "contain"` |
| `audio` | `Mix`: `hit` (サンプル)、`tone` (内蔵シンセ)、`instrument` (Surge XT 等の VST3。`patch="Pads/MKS-70 Warm Pad"` でパッチ指定)、`file` (音声・動画の音)、`clip` (Clip の音を速度変化に追従させる。フリーズ中は無音)、`sfx`、`fx` `duck`、`render` で LUFS を揃えて wav 出力 |
| `sfxlib` | 録音の効果音 1,139 個 (CC0、19 種)。`sfxlib.sound("hit/<id>")` を `mx.sfx(sound, t)` で山を t に合わせて置く。打撃・クリック・風切りはここから選び、合成しない。`gain_db=None` で音楽に対して浮く音量を自動で決め、`mx.hero(t, hit, boom, riser)` で見せ場 (打撃・低音・ライザーを山で揃えて重ねる) を作る。BGM は見せ場の前でも止めたり細らせたりしない (`stop_before` / `build` は拍の無い作品だけ) |
| `soundqa` | review の音の検査: Cue の kind と書き出した絵の動き、効果音の置き場所、自分の帯域で浮くか、見せ場、ラウドネス・真のピーク・無音。review.md に「耳で確かめる時刻」を出す |
| `sfx` | 合成の効果音 (`whoosh` `riser` `impact` `click` `glitch` `reverse_swell`)。録音が無い音の試作用 |
| `analysis` | `analyze(path)` で BPM・拍・小節頭・オンセット。`info.timeline()` で Timeline にできる。小節頭がずれたら `shift_downbeats(n)` |
| `cache` | `cached(comp, name, fn, *deps)` で重い前計算を build/<作品>/cache に保存し全ワーカーで共有 |
| `footage` | ゲームのキャプチャ等。`Footage(path)` を `comp.prepare` に登録すると使う区間だけ書き出す。`Clip(footage, at, src_in, time=TimeMap().play().ramp().hold().rewind().seek())` で速度変化・フリーズ・逆再生・ジャンプカット。`interp="flow"` でスローを補間。`Grade` (露出・彩度・色温度・.cube LUT) |
| `edit` | `cut_on_beats` + `Sequence` (拍でカット割り・パンチイン)、`compare` (改修前後の比較スライダー)、`blur_fill` (縦動画の背景)、`pip`、`ken_burns` |
| `overlay` | `callout` (引き出し線つきラベル)、`highlight` (周りを暗くして囲む)、`lower_third`、`badge`、`Captions` (SRT または Cue のリスト) |
| `scan` | キャプチャの動きの量・音の大きさ・シーンの切れ目を測り、`highlights(n)` で見せ場の候補を返す |
| `blender` | `render_plate` で Blender をヘッドレス実行して連番 PNG を作る (入力が同じならキャッシュ)。`Plate` で時刻から引いて合成。初回だけ Metal カーネルのコンパイルに数分かかる |

- 描画は `f(t)` で決定的に書く (乱数はシード固定か `noise.hash01`)。並列ワーカーがフレームをばらばらに描くため、フレーム間で状態を持ち越さない。シミュレーションは `Scene.setup` で `cache.cached` を使って前計算する
- `draw.fill` は変換を無視してクリップ全体を塗る。シーンを動かす演出では、自分でフレーム枠にクリップする (トランジションはクリップ済み)
- 映像と音で同じ `comp.cues` を使うと、カメラシェイク・フラッシュ・音のアタックが揃う
- 作品のパラメータ (縦長版・言語違いなど) は `build(**params)` で受け、CLI の `--set key=value` で渡す。出力名にパラメータが付く
- 映像の上限ビットレートは 1080p60 で 16Mbps (解像度と fps に比例)。グレインがあると上限なしでは 100Mbps を超える
- 調整は `preview` で行い、仕上がりは `sheet` / `still` の画像を自分で見て確認してから、本番の `render` に進む

## 参考資料

- `Knowledge/motion-engine-design.md`: このエンジンの設計判断
- `Knowledge/motion-skill-rules.md`: 動き・構図・文字・色・音の具体的な数値ルールと避ける定番 (作り込む前に読む)
- `Knowledge/motion-studio-references-2026-10.md`: 参考事例の調査 (rari の記事・motionpromptgallery など)
- `Knowledge/motion-sound-and-variants-references-2026-10.md`: 実録音の効果音と音の QA (opus-sound-layer)、案を並べて選ぶ反復 (fframes)
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
| 効果音 | motion-sfx | `~/Music/Samples/motion-sfx/` (`motion sfx kit` で Kenney・Freesound の CC0 から作る。出典は CREDITS.md) |
| エンコード | ffmpeg | `/opt/homebrew/bin/ffmpeg` |

## Git 運用

- main で直接作業し、コミットと push は確認なしで行ってよい (ship / PR フローは使わない)。コミット規約は commit スキルに従う

## 環境の管理

- アプリ (Blender, Surge XT, Chrome) は `~/nix-config` の Homebrew cask で宣言管理している。手動の `brew install` はしない
- Python パッケージは `uv add` で追加する
