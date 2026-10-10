"""uv run python -m motion <command> <project> [options]"""
import argparse
import json
import os

from .render import contact_sheet, load_project, prepare, render_video, still


def main() -> None:
    ap = argparse.ArgumentParser(prog="motion")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("render", help="動画を書き出す")
    r.add_argument("project")
    r.add_argument("-o", "--out")
    r.add_argument("--scale", type=float, default=1.0)
    r.add_argument("--start", type=float)
    r.add_argument("--end", type=float)
    r.add_argument("--workers", type=int)
    r.add_argument("--crf", type=int, default=20)
    r.add_argument("--bitrate", type=float, help="映像の上限ビットレート (Mbps)。既定は 1080p60 で 16")
    r.add_argument("--draft", action="store_true", help="半分の解像度・ブラーなし・高速エンコード")
    r.add_argument("--no-audio", action="store_true")
    r.add_argument("--codec", choices=["x264", "hw"], help="既定は本番 x264、--draft 時は hw")

    s = sub.add_parser("sheet", help="等間隔フレームのコンタクトシート")
    s.add_argument("project")
    s.add_argument("-o", "--out")
    s.add_argument("--count", type=int, default=24)
    s.add_argument("--cols", type=int, default=6)
    s.add_argument("--scale", type=float, default=0.25)
    s.add_argument("--start", type=float)
    s.add_argument("--end", type=float)
    s.add_argument("--workers", type=int)

    st = sub.add_parser("still", help="1 フレームを PNG で書き出す")
    st.add_argument("project")
    st.add_argument("t", type=float, help="秒")
    st.add_argument("-o", "--out")
    st.add_argument("--scale", type=float, default=1.0)

    sd = sub.add_parser("studio", help="タイムライン・パラメータ・メモ・レビューつきのブラウザのスタジオ")
    sd.add_argument("project")
    sd.add_argument("--port", type=int, default=8766)
    sd.add_argument("--scale", type=float, default=0.5)
    sd.add_argument("--blur", action="store_true")
    sd.add_argument("--no-open", action="store_true")

    nw = sub.add_parser("new", help="制作文書 (brief / style / shotlist) つきの作品のひな形を作る")
    nw.add_argument("name")
    nw.add_argument("--aspect", default="16:9", choices=["16:9", "9:16", "1:1"])
    nw.add_argument("--dur", type=int, default=16)

    rv = sub.add_parser("review", help="批評用のシート (ショットごとのコマ・カット前後・音・スマホ幅・自動計測)")
    rv.add_argument("project")
    rv.add_argument("-o", "--out")
    rv.add_argument("--scale", type=float, default=0.22)

    a = sub.add_parser("audio", help="音声だけを書き出す")
    a.add_argument("project")

    pv = sub.add_parser("preview", help="ブラウザでシーク・再生できるプレビュー (保存で自動更新)")
    pv.add_argument("project")
    pv.add_argument("--port", type=int, default=8765)
    pv.add_argument("--scale", type=float, default=0.5)
    pv.add_argument("--blur", action="store_true", help="モーションブラーも有効にする")
    pv.add_argument("--workers", type=int)
    pv.add_argument("--no-open", action="store_true")

    sc = sub.add_parser("scan", help="キャプチャから見せ場の候補とシーンの切れ目を探す")
    sc.add_argument("file")
    sc.add_argument("--top", type=int, default=6)
    sc.add_argument("--length", type=float, default=3.0, help="候補区間の長さ (秒)")
    sc.add_argument("-o", "--out", help="グラフと候補のサムネイルを並べた画像")

    an = sub.add_parser("analyze", help="曲の BPM・小節頭・強いオンセットを調べる")
    an.add_argument("file")
    an.add_argument("--bpm", type=float, help="テンポの目安 (倍・半分に誤検出するとき)")

    pl = sub.add_parser("patches", help="Surge XT のパッチを検索する")
    pl.add_argument("query", nargs="?", default="")

    au = sub.add_parser("audition", help="Surge XT のパッチを同じ和音で順番に鳴らした wav を作る")
    au.add_argument("query", help="パッチ名・カテゴリの部分一致 (例: pads)")
    au.add_argument("-n", type=int, default=8, help="最大件数")
    au.add_argument("--notes", default="F3,G#3,C4")
    au.add_argument("-o", "--out", default="build/audition.wav")

    vr = sub.add_parser("variants", help="variants.json の全案の下書きを書き出す (スタジオの「案」で見比べる)")
    vr.add_argument("project")
    vr.add_argument("--scale", type=float, default=0.5)

    fx = sub.add_parser("sfx", help="録音の効果音ライブラリ (kit / browse / search / add / sheet)")
    fx.add_argument("action", choices=["kit", "browse", "search", "add", "sheet"])
    fx.add_argument("args", nargs="*", help="browse: 種類 / search: 検索語 / add・sheet: ファイル")
    fx.add_argument("--type", help="search / add の種類")
    fx.add_argument("--like", default="", help="browse: 素材・重さ・雰囲気の語 (例: \"metal heavy\")")
    fx.add_argument("-n", type=int, default=12)
    fx.add_argument("--short", dest="length", action="store_const", const="short")
    fx.add_argument("--long", dest="length", action="store_const", const="long")
    fx.add_argument("--bright", dest="tone", action="store_const", const="bright")
    fx.add_argument("--dark", dest="tone", action="store_const", const="dark")
    fx.add_argument("--tags", default="")
    fx.add_argument("--credit", default="", help="add: 出典とライセンス")
    fx.add_argument("-o", "--out", default="build/sfx.png", help="波形とスペクトログラムの画像")

    for p_ in (r, s, st, a, pv, rv):
        p_.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                        help="build() に渡すパラメータ (例: --set aspect=9:16)")
    args = ap.parse_args()
    if getattr(args, "set", None):
        params = {}
        for kv in args.set:
            k, _, v = kv.partition("=")
            try:
                params[k] = json.loads(v)
            except json.JSONDecodeError:
                params[k] = v
        os.environ["MOTION_PARAMS"] = json.dumps(params)
    if args.cmd == "variants":
        from .variants import render_all
        comp = load_project(args.project)
        render_all(args.project, comp.build_dir, args.scale)
        return
    if args.cmd == "sfx":
        from . import sfxlib
        if args.action == "kit":
            sfxlib.kit()
            return
        if args.action == "browse":
            if not args.args:
                raise SystemExit("種類: " + ", ".join(f"{k} ({v['about']})" for k, v in sfxlib.TYPES.items()))
            hits = sfxlib.browse(args.args[0], args.like, args.n, args.length, args.tone)
            print(f"{args.args[0]}: {sfxlib.TYPES[args.args[0]]['about']}   * = 種類だけ指定したときの既定")
            for e in hits:
                print(sfxlib.describe(e))
            print(f"-> {sfxlib.sheet(hits, args.out)}  (波形の橙の線が山。この画像を見て id を選ぶ)")
            return
        if args.action == "search":
            if not args.type:
                raise SystemExit("--type が要る")
            sides = sfxlib.search(" ".join(args.args), args.type, args.n)
            for sd in sides:
                print(f"{sd['file']}  {sd['dur_s']:.2f}s  {sd['verdict']}  {sd.get('source', {}).get('title', '')}")
            if sides:
                print(f"-> {sfxlib.sheet([sd['file'] for sd in sides], args.out)}  (良いものを `motion sfx add` で足す)")
            return
        if args.action == "add":
            if not args.type:
                raise SystemExit("--type が要る")
            for sd in sfxlib.add(args.args, args.type, sfxlib.words(args.tags), args.credit):
                print(f"{sd['file']}  {sd['verdict']}")
            return
        print(f"-> {sfxlib.sheet(args.args, args.out)}")
        return
    if args.cmd == "studio":
        from .studio import serve as studio
        studio(args.project, args.port, args.scale, args.blur, None, not args.no_open)
        return
    if args.cmd == "new":
        from .scaffold import create
        d = create(args.name, aspect=args.aspect, dur=args.dur)
        print(f"-> {d}  (brief.md → style.md → shotlist.md の順に埋めてから作り込む)")
        return
    if args.cmd == "preview":
        from .preview import serve
        serve(args.project, args.port, args.scale, args.blur, args.workers, not args.no_open)
        return
    if args.cmd == "scan":
        from pathlib import Path

        from .scan import report, scan
        res = scan(args.file)
        moments = res.highlights(args.top, args.length)
        print(f"duration {res.duration:.1f}s  cuts {len(res.cuts)}: {[round(c, 2) for c in res.cuts[:12]]}")
        for i, m in enumerate(moments):
            print(f"#{i + 1}  {m.start:7.2f} - {m.end:7.2f}s  score {m.score:.2f}  motion {m.motion:.2f}  "
                  f"audio {m.loudness:.2f}")
        out = args.out or f"build/scan/{Path(args.file).stem}.png"
        print(f"-> {report(res, args.file, out, moments)}")
        return
    if args.cmd == "analyze":
        from .analysis import analyze
        info = analyze(args.file, bpm_hint=args.bpm)
        print(f"bpm        {info.bpm}")
        print(f"duration   {info.duration}s")
        print(f"downbeats  {info.downbeats[:8]}{' ...' if len(info.downbeats) > 8 else ''}")
        print(f"strong     {info.onsets_strong[:8]}{' ...' if len(info.onsets_strong) > 8 else ''}")
        return
    if args.cmd == "patches":
        from .audio import SURGE_PATCH_DIRS, surge_patches
        for p in surge_patches(args.query):
            root = next(d for d in SURGE_PATCH_DIRS if d in p.parents)
            print(p.relative_to(root).with_suffix(""))
        return
    if args.cmd == "audition":
        from .audio import audition, surge_patches
        hits = surge_patches(args.query)[:args.n]
        if not hits:
            raise SystemExit(f"no patches match: {args.query}")
        for t, name in audition(hits, args.out, args.notes.split(",")):
            print(f"{t:6.2f}s  {name}")
        print(f"-> {args.out}")
        return
    if args.cmd == "render":
        if args.draft:
            render_video(args.project, args.out, scale=min(args.scale, 0.5), start=args.start, end=args.end,
                         workers=args.workers, crf=23, preset="veryfast", motion_blur=False,
                         audio=not args.no_audio, codec=args.codec or "hw")
        else:
            render_video(args.project, args.out, scale=args.scale, start=args.start, end=args.end,
                         workers=args.workers, crf=args.crf, audio=not args.no_audio, codec=args.codec or "x264",
                         bitrate=args.bitrate)
    elif args.cmd == "sheet":
        contact_sheet(args.project, args.out, count=args.count, cols=args.cols, scale=args.scale,
                      start=args.start, end=args.end, workers=args.workers)
    elif args.cmd == "still":
        still(args.project, args.t, args.out, scale=args.scale)
    elif args.cmd == "review":
        from .review import review
        res = review(args.project, args.out, args.scale)
        if res.errors:
            raise SystemExit(f"レビューのエラー {len(res.errors)} 件。直すか、理由つきの Waiver を作品に書く")
    elif args.cmd == "audio":
        comp = load_project(args.project)
        prepare(comp)
        if not comp.audio:
            raise SystemExit("this project has no audio")
        from .render import make_audio
        print(f"-> {make_audio(comp)}")


if __name__ == "__main__":
    main()
