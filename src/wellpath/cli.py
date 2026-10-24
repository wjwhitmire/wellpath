"""Command line interface: wellpath surveys.csv [--units ft|m] [--vs-azi DEG] ..."""

from __future__ import annotations

import argparse
import json
import os
import sys

from .parse import MAX_BYTES, detect_units, parse_text
from .survey import SurveyError, TieIn, compute, interpolate

COLUMNS = ("md", "inc", "azi", "tvd", "north", "east", "vs", "dls", "build", "turn")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="wellpath",
        description="Minimum curvature well path from directional surveys (MD, Inc, Azi).",
    )
    p.add_argument("file", help="CSV, TSV or JSON survey file, or - for standard input")
    p.add_argument(
        "--units",
        choices=("ft", "m"),
        default=None,
        help="depth units; default: read from the file header (MD (m), # Units: m), else ft",
    )
    p.add_argument("--vs-azi", type=float, default=None, help="vertical section azimuth, deg")
    p.add_argument("--tie-md", type=float, default=None, help="tie-in MD")
    p.add_argument("--tie-tvd", type=float, default=0.0, help="tie-in TVD")
    p.add_argument("--tie-north", type=float, default=0.0, help="tie-in north")
    p.add_argument("--tie-east", type=float, default=0.0, help="tie-in east")
    p.add_argument("--interp", type=float, action="append", default=[], help="interpolate at MD (repeatable)")
    p.add_argument("--json", action="store_true", help="print JSON instead of CSV")
    return p


def _read(path: str) -> str:
    if path == "-":
        return sys.stdin.read(MAX_BYTES + 1)
    if os.path.getsize(path) > MAX_BYTES:
        raise SurveyError("Input file is larger than 5 MB.")
    with open(path, "r", encoding="utf-8-sig") as fh:
        return fh.read()


def _csv_row(p) -> str:
    """One CSV row. Turn is left blank where it is suppressed near vertical."""
    d = p.as_dict()
    return ",".join("" if c == "turn" and d["turn_suppressed"] else f"{d[c]:.4f}" for c in COLUMNS)


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        text = _read(args.file)
        rows = parse_text(text)
        units = args.units
        if units is None:
            units, why = detect_units(text)
            if units:
                print(f"# units {units} ({why}); use --units to change", file=sys.stderr)
            else:
                units = "ft"
        tie = None
        if args.tie_md is not None:
            tie = TieIn(md=args.tie_md, tvd=args.tie_tvd, north=args.tie_north, east=args.tie_east)
        path = compute(rows, units=units, vs_azimuth=args.vs_azi, tie_in=tie)
        interp = [interpolate(path, md) for md in args.interp]
    except UnicodeDecodeError:
        print("error: input is not UTF-8 text. Save the survey file as UTF-8 CSV and try again.", file=sys.stderr)
        return 2
    except (SurveyError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        out = {
            "summary": path.summary(),
            "points": [p.as_dict() for p in path.points],
            "interpolated": [p.as_dict() for p in interp],
        }
        print(json.dumps(out, indent=2))
        return 0
    print(",".join(COLUMNS))
    for p in path.points:
        print(_csv_row(p))
    s = path.summary()
    print(
        f"# TD MD {s['td_md']:.2f}, TVD {s['td_tvd']:.2f}, closure {s['closure_distance']:.2f} "
        f"@ {s['closure_azimuth']:.2f} deg, VS azimuth {s['vs_azimuth']:.2f} deg, "
        f"max DLS {s['max_dls']:.3f} deg/{s['course_length']:g}{s['units']} at MD {s['max_dls_md']:.2f}",
        file=sys.stderr,
    )
    for p in interp:
        print("# interp " + _csv_row(p), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
