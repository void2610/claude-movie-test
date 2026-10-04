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

    args = ap.parse_args()
    if args.cmd == "render":
        if args.draft:
            render_video(args.project, args.out, scale=min(args.scale, 0.5), start=args.start, end=args.end,
                         workers=args.workers, crf=23, preset="veryfast", motion_blur=False,
                         audio=not args.no_audio)
        else:
            render_video(args.project, args.out, scale=args.scale, start=args.start, end=args.end,
                         workers=args.workers, crf=args.crf, audio=not args.no_audio)
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
