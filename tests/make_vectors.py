"""Write tests/vectors.json: reference cases computed by the Python library.

web/parity.test.mjs runs the JavaScript core in web/app.html on the same
inputs and checks it matches.
"""

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from wellpath import SurveyError, TieIn, compute, detect_units, interpolate, parse_text  # noqa: E402

FIELDS = ("md", "inc", "azi", "tvd", "north", "east", "vs", "dogleg", "dls", "build", "turn")
SUMMARY = ("td_md", "td_tvd", "vs_azimuth", "closure_distance", "closure_azimuth", "max_dls", "max_dls_md")


def arc(bur, azi):
    R = 18000.0 / math.pi / bur
    return [[R * math.radians(i), i, azi] for i in (0, 10, 30, 60, 90)]


def helix(n):
    return [[1000.0 * k / n, 20 + 50.0 * k / n, (300 + 100.0 * k / n) % 360] for k in range(n + 1)]


CASES = [
    {"name": "example_horizontal", "surveys": parse_text((ROOT / "examples" / "horizontal_example.csv").read_text()), "units": "ft", "interp": [8000, 8640.5, 9500, 13000]},
    {"name": "example_horizontal_vs0_metric", "surveys": parse_text((ROOT / "examples" / "horizontal_example.csv").read_text()), "units": "m", "vs": 0.0},
    {"name": "vertical", "surveys": [[0, 0, 0], [500, 0, 0], [3000, 0, 120]], "units": "ft", "interp": [1234]},
    {"name": "vertical_first_deep", "surveys": [[800, 0, 0], [900, 0, 0]], "units": "ft"},
    {"name": "tangent", "surveys": [[2000, 35, 222], [3500, 35, 222]], "units": "ft", "tie": {"md": 2000, "tvd": 1900, "north": 10, "east": -5}},
    {"name": "arc_10", "surveys": arc(10, 0), "units": "ft", "interp": [100, 500, 777]},
    {"name": "arc_3_az271", "surveys": arc(3, 271), "units": "ft"},
    {"name": "helix_8", "surveys": helix(8), "units": "ft", "tie": {"md": 0}, "interp": [333.3, 999]},
    {"name": "wrap_359_1", "surveys": [[1000, 45, 359], [1100, 45, 1], [1200, 46, 358.5]], "units": "ft", "tie": {"md": 1000, "tvd": 900}},
    {"name": "worked_example", "surveys": [[1000, 15, 20], [1100, 25, 45]], "units": "ft", "tie": {"md": 1000, "tvd": 980, "north": 50, "east": 20}, "interp": [1050]},
    {"name": "tie_above_with_dir", "surveys": [[1100, 10, 90], [1200, 12, 95]], "units": "m", "tie": {"md": 1000, "tvd": 995, "inc": 10, "azi": 90}, "vs": 100},
    {"name": "skip_above_tie", "surveys": [[0, 0, 0], [500, 1, 10], [1000, 3, 20], [1100, 5, 25]], "units": "ft", "tie": {"md": 1000, "tvd": 999}},
    {"name": "tiny_dogleg", "surveys": [[0, 30, 100], [100, 30.0000001, 100], [200, 30.0000001, 100.0000002]], "units": "ft", "tie": {"md": 0}},
    {"name": "normalize_az", "surveys": [[0, 10, 360], [100, 10, -10], [200, 10, 720.5]], "units": "ft", "tie": {"md": 0}},
    {"name": "near_vertical_turn", "surveys": [[0, 0, 0], [500, 1, 120], [600, 2.99, 300], [700, 3, 310], [800, 6, 330], [900, 178, 10], [1000, 177, 20]], "units": "ft", "tie": {"md": 0}, "interp": [550, 750]},
    # error cases
    {"name": "err_md_not_increasing", "surveys": [[0, 0, 0], [0, 1, 1]], "units": "ft", "error": True},
    {"name": "err_md_decreasing", "surveys": [[0, 0, 0], [100, 1, 1], [90, 2, 2]], "units": "ft", "error": True},
    {"name": "err_inc_neg", "surveys": [[0, -1, 0]], "units": "ft", "error": True},
    {"name": "err_inc_big", "surveys": [[0, 180.01, 0]], "units": "ft", "error": True},
    {"name": "err_empty", "surveys": [], "units": "ft", "error": True},
    {"name": "err_all_above_tie", "surveys": [[0, 0, 0], [100, 1, 1]], "units": "ft", "tie": {"md": 500}, "error": True},
    {"name": "err_opposite", "surveys": [[0, 0, 0], [100, 180, 0]], "units": "ft", "tie": {"md": 0}, "error": True},
]


UNIT_TEXTS = [
    "MD (m),Inc,Azi\n0,0,0\n",
    "Measured Depth [ft]\tInclination\tAzimuth\n0\t0\t0\n",
    "MD (metres);Inc;Azi\n0;0;0\n",
    "# Units: m\nMD,Inc,Azi\n0,0,0\n",
    "# Example data. Units ft.\n0,0,0\n",
    "# unit mass, no depth unit here\nMD,Inc,Azi\n0,0,0\n",
    "MD,Inc,Azi\n0,0,0\n",
    "0,0,0\n100,1,1\n",
    "Inc (deg),MD (usft),Azi (deg)\n0,0,0\n",
    "MD (km),Inc,Azi\n0,0,0\n",
    '{"units": "m", "surveys": [[0, 0, 0]]}',
    '{"units": "furlongs", "surveys": [[0, 0, 0]]}',
    '[[0, 0, 0]]',
    "\ufeffMD (m),Inc,Azi\n0,0,0\n",
    "",
]


def run(case):
    tie = TieIn(**case["tie"]) if "tie" in case else None
    out = {k: v for k, v in case.items() if k != "error"}
    out["surveys"] = [list(map(float, r)) for r in case["surveys"]]
    try:
        path = compute(case["surveys"], units=case["units"], vs_azimuth=case.get("vs"), tie_in=tie)
    except SurveyError:
        out["expect_error"] = True
        return out
    assert not case.get("error"), case["name"]
    out["expect_error"] = False
    out["points"] = [{**{f: getattr(p, f) for f in FIELDS}, "turn_suppressed": p.turn_suppressed} for p in path.points]
    s = path.summary()
    out["summary"] = {k: s[k] for k in SUMMARY}
    out["summary"]["skipped_above_tie_in"] = path.skipped_above_tie_in
    out["interp_results"] = [{**{f: getattr(q, f) for f in FIELDS}, "turn_suppressed": q.turn_suppressed} for q in (interpolate(path, m) for m in case.get("interp", []))]
    return out


def main():
    data = {"generator": "tests/make_vectors.py", "fields": list(FIELDS), "cases": [run(c) for c in CASES],
            "detect_units": [{"text": t, "units": detect_units(t)[0], "why": detect_units(t)[1]} for t in UNIT_TEXTS]}
    path = ROOT / "tests" / "vectors.json"
    path.write_text(json.dumps(data, indent=1) + "\n")
    print(f"wrote {path.relative_to(ROOT)} with {len(data['cases'])} cases")


if __name__ == "__main__":
    main()
