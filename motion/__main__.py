"""uv run python -m motion <command> <project> [options]"""
import argparse

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
    r.add_argument("--crf", type=int, default=18)
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

    a = sub.add_parser("audio", help="音声だけを書き出す")
    a.add_argument("project")

    pl = sub.add_parser("patches", help="Surge XT のパッチを検索する")
    pl.add_argument("query", nargs="?", default="")

    au = sub.add_parser("audition", help="Surge XT のパッチを同じ和音で順番に鳴らした wav を作る")
    au.add_argument("query", help="パッチ名・カテゴリの部分一致 (例: pads)")
    au.add_argument("-n", type=int, default=8, help="最大件数")
    au.add_argument("--notes", default="F3,G#3,C4")
    au.add_argument("-o", "--out", default="build/audition.wav")

    args = ap.parse_args()
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
                         workers=args.workers, crf=args.crf, audio=not args.no_audio, codec=args.codec or "x264")
    elif args.cmd == "sheet":
        contact_sheet(args.project, args.out, count=args.count, cols=args.cols, scale=args.scale,
                      start=args.start, end=args.end, workers=args.workers)
    elif args.cmd == "still":
        still(args.project, args.t, args.out, scale=args.scale)
    elif args.cmd == "audio":
        comp = load_project(args.project)
        prepare(comp)
        if not comp.audio:
            raise SystemExit("this project has no audio")
        print(f"-> {comp.audio(comp)}")


if __name__ == "__main__":
    main()
