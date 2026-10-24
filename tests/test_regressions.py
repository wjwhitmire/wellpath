"""Regression tests for bugs found in the full function test pass."""

import subprocess
import sys
from pathlib import Path

from wellpath import compute, detect_units, parse_text
from wellpath.cli import main

ROOT = Path(__file__).resolve().parent.parent


def test_detect_units_header_comment_json():
    assert detect_units("MD (m),Inc,Azi\n0,0,0\n")[0] == "m"
    assert detect_units("Measured Depth [ft],Inc,Azi\n0,0,0\n")[0] == "ft"
    assert detect_units("# Units: m\n0,0,0\n")[0] == "m"
    assert detect_units('{"units": "metres", "surveys": [[0,0,0]]}')[0] == "m"
    assert detect_units("MD,Inc,Azi\n0,0,0\n") == (None, "")
    assert detect_units("0,0,0\n") == (None, "")
    assert detect_units("MD (km),Inc,Azi\n0,0,0\n") == (None, "")
    assert detect_units("# a unit mass note\nMD,Inc,Azi\n") == (None, "")


def test_example_file_reads_as_feet():
    assert detect_units((ROOT / "examples" / "horizontal_example.csv").read_text())[0] == "ft"


def test_cli_picks_units_from_header(tmp_path, capsys):
    f = tmp_path / "s.csv"
    f.write_text("MD (m),Inc,Azi\n0,0,0\n30,3,0\n")
    assert main([str(f), "--json"]) == 0
    out = capsys.readouterr()
    assert '"units": "m"' in out.out
    assert "units m (from the header 'MD (m)')" in out.err
    # 3 degrees over 30 m is 3 deg/30 m
    assert '"max_dls": 3.0' in out.out


def test_cli_units_flag_overrides_header(tmp_path, capsys):
    f = tmp_path / "s.csv"
    f.write_text("MD (m),Inc,Azi\n0,0,0\n30,3,0\n")
    assert main([str(f), "--json", "--units", "ft"]) == 0
    out = capsys.readouterr()
    assert '"units": "ft"' in out.out
    assert "units m" not in out.err


def test_cli_defaults_to_feet_without_hint(tmp_path, capsys):
    f = tmp_path / "s.csv"
    f.write_text("0,0,0\n100,3,0\n")
    assert main([str(f), "--json"]) == 0
    assert '"units": "ft"' in capsys.readouterr().out


def test_large_survey_computes():
    rows = parse_text("".join(f"{i * 10},{min(90, i * 0.01):.2f},{(i * 0.1) % 360:.1f}\n" for i in range(50000)))
    assert len(compute(rows).points) == 50000
