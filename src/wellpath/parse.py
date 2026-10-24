"""Survey text parsing: CSV or tab separated, optional header, or JSON."""

from __future__ import annotations

import json
import math
import re
from typing import List, Tuple

from .survey import SurveyError

MAX_ROWS = 50_000
MAX_BYTES = 5 * 1024 * 1024

_MD_NAMES = ("md", "measured depth", "measureddepth", "depth", "mdepth")
_INC_NAMES = ("inc", "incl", "inclination", "angle")
_AZI_NAMES = ("azi", "az", "azm", "azimuth", "dir", "direction")


def _split(line: str) -> List[str]:
    if "\t" in line:
        parts = line.split("\t")
    elif "," in line:
        parts = line.split(",")
    elif ";" in line:
        parts = line.split(";")
    else:
        parts = line.split()
    return [p.strip().strip('"').strip("'").strip() for p in parts]


def _num(s: str):
    if not re.fullmatch(r"[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?", s):
        return None
    v = float(s)
    return v if math.isfinite(v) else None


def _match(cell: str, names) -> bool:
    c = re.sub(r"\(.*?\)|\[.*?\]", "", cell.lower()).strip()
    c = re.sub(r"[^a-z ]", "", c).strip()
    return c in names or c.replace(" ", "") in names


_UNIT_WORDS = {
    "ft": "ft", "feet": "ft", "foot": "ft", "usft": "ft",
    "m": "m", "metre": "m", "metres": "m", "meter": "m", "meters": "m",
}
_COMMENT_UNITS = re.compile(r"\bunits?\s*[:=]?\s*(ft|feet|foot|usft|m|metres|meters|metre|meter)\b", re.I)
_BRACKET = re.compile(r"[(\[]\s*([a-z]+)\s*[)\]]")


def detect_units(text: str):
    """Guess the depth unit from the input itself.

    Returns ``(units, reason)`` where units is "ft", "m" or None. Looks at,
    in order: a JSON object's "units" key, a comment line such as
    ``# Units: m``, and the unit in brackets after the MD column name in the
    header row, for example ``MD (m)`` or ``Measured Depth [ft]``.
    """
    if not isinstance(text, str):
        return None, ""
    body = text[1:] if text.startswith("\ufeff") else text
    stripped = body.lstrip()
    if stripped.startswith("{"):
        try:
            data = json.loads(stripped)
        except (ValueError, RecursionError):
            return None, ""
        u = data.get("units") if isinstance(data, dict) else None
        u = _UNIT_WORDS.get(str(u).strip().lower()) if isinstance(u, str) else None
        return (u, 'from "units" in the JSON') if u else (None, "")
    if stripped.startswith("["):
        return None, ""
    for raw in body.splitlines()[:200]:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            m = _COMMENT_UNITS.search(line)
            if m:
                return _UNIT_WORDS[m.group(1).lower()], "from the comment line"
            continue
        cells = _split(line)
        if all(_num(c) is not None for c in cells[:3]):
            return None, ""  # no header row
        for c in cells:
            if _match(c, _MD_NAMES):
                m = _BRACKET.search(c.lower())
                if m and m.group(1) in _UNIT_WORDS:
                    return _UNIT_WORDS[m.group(1)], f"from the header '{c}'"
        return None, ""
    return None, ""


def parse_text(text: str) -> List[Tuple[float, float, float]]:
    """Parse survey rows from text. Returns a list of (md, inc, azi).

    Lines starting with # are comments. Blank lines are skipped. A first
    non-numeric line is treated as a header and used to find the MD, Inc and
    Azi columns; without a header the first three columns are used. Extra
    columns are ignored.
    """
    if len(text.encode("utf-8")) > MAX_BYTES:
        raise SurveyError("Input is larger than 5 MB.")
    if text.startswith("\ufeff"):
        text = text[1:]  # byte order mark
    stripped = text.lstrip()
    if stripped.startswith("[") or stripped.startswith("{"):
        return _parse_json(stripped)
    cols = (0, 1, 2)
    header_seen = False
    rows: List[Tuple[float, float, float]] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        cells = _split(line)
        nums = [_num(c) for c in cells]
        if not rows and not header_seen and any(v is None for v in nums[:3]):
            # header line
            found = [None, None, None]
            for i, c in enumerate(cells):
                for k, names in enumerate((_MD_NAMES, _INC_NAMES, _AZI_NAMES)):
                    if found[k] is None and _match(c, names):
                        found[k] = i
            if all(f is not None for f in found):
                cols = tuple(found)
            elif any(f is not None for f in found):
                raise SurveyError(
                    f"Line {lineno}: header found but could not find all of MD, Inc and Azi columns."
                )
            else:
                raise SurveyError(
                    f"Line {lineno}: expected a header (MD, Inc, Azi) or three numbers, got {line[:60]!r}."
                )
            header_seen = True
            continue
        need = max(cols) + 1
        if len(cells) < need:
            raise SurveyError(f"Line {lineno}: expected at least {need} columns, found {len(cells)}.")
        vals = [nums[c] for c in cols]
        for name, c, v in zip(("MD", "inclination", "azimuth"), cols, vals):
            if v is None:
                raise SurveyError(f"Line {lineno}: {name} {cells[c]!r} is not a number.")
        rows.append((vals[0], vals[1], vals[2]))
        if len(rows) > MAX_ROWS:
            raise SurveyError(f"More than {MAX_ROWS:,} survey rows.")
    if not rows:
        raise SurveyError("No survey rows found.")
    return rows


def _parse_json(text: str) -> List[Tuple[float, float, float]]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SurveyError(f"JSON could not be read: {exc.msg} at line {exc.lineno}.") from None
    except RecursionError:
        raise SurveyError("JSON could not be read: nested too deeply.") from None
    if isinstance(data, dict):
        data = data.get("surveys")
    if not isinstance(data, list):
        raise SurveyError("JSON must be a list of surveys or an object with a 'surveys' list.")
    if len(data) > MAX_ROWS:
        raise SurveyError(f"More than {MAX_ROWS:,} survey rows.")
    rows = []
    for k, item in enumerate(data, start=1):
        if isinstance(item, dict):
            vals = [item.get(key) for key in ("md", "inc", "azi")]
        elif isinstance(item, list) and len(item) >= 3:
            vals = item[:3]
        else:
            raise SurveyError(f"JSON survey {k}: expected {{md, inc, azi}} or [md, inc, azi].")
        out = []
        for name, v in zip(("md", "inc", "azi"), vals):
            try:
                ok = not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(float(v))
            except OverflowError:
                ok = False
            if not ok:
                raise SurveyError(f"JSON survey {k}: {name} is missing or not a finite number.")
            out.append(float(v))
        rows.append((out[0], out[1], out[2]))
    if not rows:
        raise SurveyError("No survey rows found.")
    return rows
