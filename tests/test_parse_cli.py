import json
from pathlib import Path

import pytest

from wellpath import SurveyError, parse_text
from wellpath.cli import main

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "horizontal_example.csv"


def test_header_and_extra_columns_any_order():
    text = "Azimuth (deg)\tMD (ft)\tTool\tInclination\n10\t0\tMWD\t0\n\n20\t100\tMWD\t3.5\n"
    assert parse_text(text) == [(0.0, 0.0, 10.0), (100.0, 3.5, 20.0)]


def test_no_header_comments_and_separators():
    text = "# comment\n0,0,0\n100, 1.5 ,200\n200;3;210\n300 4.5 220\n"
    assert parse_text(text)[-1] == (300.0, 4.5, 220.0)


def test_json_forms():
    assert parse_text('[{"md":0,"inc":0,"azi":0},[100,2,3]]') == [(0, 0, 0), (100, 2, 3)]
    assert parse_text('{"surveys":[[0,0,0]]}') == [(0, 0, 0)]
    with pytest.raises(SurveyError):
        parse_text('[{"md":"x","inc":0,"azi":0}]')
    with pytest.raises(SurveyError):
        parse_text("[1,2")


@pytest.mark.parametrize(
    "text",
    ["", "\n\n", "MD,Inc\n0,0", "foo,bar,baz\n1,2,3", "0,0,0\n100,abc,0", "0,0,0\n100,NaN,0", "0,0"],
)
def test_parse_errors(text):
    with pytest.raises(SurveyError):
        parse_text(text)


def test_row_cap():
    text = "\n".join(f"{i},0,0" for i in range(50_001))
    with pytest.raises(SurveyError):
        parse_text(text)


def test_cli_csv(capsys):
    assert main([str(EXAMPLE)]) == 0
    out = capsys.readouterr()
    lines = out.out.strip().splitlines()
    assert lines[0].startswith("md,inc,azi,tvd")
    assert len(lines) == 30
    assert "closure" in out.err


def test_cli_json_and_interp(capsys):
    assert main([str(EXAMPLE), "--json", "--vs-azi", "0", "--interp", "9000"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["summary"]["vs_azimuth"] == 0
    assert data["interpolated"][0]["md"] == 9000


def test_cli_error(tmp_path, capsys):
    f = tmp_path / "bad.csv"
    f.write_text("0,0,0\n0,1,1\n")
    assert main([str(f)]) == 2
    assert "strictly increase" in capsys.readouterr().err


def test_example_well_shape():
    from wellpath import compute

    path = compute(parse_text(EXAMPLE.read_text()))
    s = path.summary()
    assert 9000 < s["td_tvd"] < 9100
    assert 10 < s["max_dls"] < 11.5
    assert 8500 < s["max_dls_md"] < 9500


# ---------------------------------------------------------------------------
# Review fixes: hostile input
# ---------------------------------------------------------------------------


def test_bom_before_numeric_first_row():
    assert parse_text("\ufeff0,0,0\n100,1,1") == [(0.0, 0.0, 0.0), (100.0, 1.0, 1.0)]


@pytest.mark.parametrize("text", ["[" * 100000, "[[0,0,0],[100,1," + "9" * 400 + "]]"])
def test_hostile_json_is_survey_error(text):
    with pytest.raises(SurveyError):
        parse_text(text)


def test_cli_non_utf8_file(tmp_path, capsys):
    f = tmp_path / "bad.csv"
    f.write_bytes(b"0,0,0\n100,\xff\xfe,1\n")
    assert main([str(f)]) == 2
    assert "UTF-8" in capsys.readouterr().err


def test_cli_turn_blank_near_vertical(capsys):
    assert main([str(EXAMPLE)]) == 0
    rows = [r.split(",") for r in capsys.readouterr().out.strip().splitlines()[1:]]
    kop = next(r for r in rows if r[0] == "8594.0000")
    assert kop[-1] == ""  # turn suppressed at KOP, not 155.7
    assert rows[-1][-1] != ""
