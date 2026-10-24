"""Minimum curvature well path calculation.

All angles at the public interface are in degrees. Lengths are in whatever
unit the surveys are in (feet or metres); the unit only changes the course
length used for dogleg severity, build rate and turn rate (100 ft or 30 m).

Positions (TVD, north, east) are measured from the wellhead reference. The
tie-in point carries its own TVD, north and east relative to that reference.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence

__all__ = [
    "Station",
    "TieIn",
    "PathPoint",
    "WellPath",
    "SurveyError",
    "COURSE_LENGTH",
    "BETA_SMALL",
    "TURN_MIN_INC",
    "normalize_azimuth",
    "turn_difference",
    "dogleg",
    "ratio_factor",
    "min_curve_step",
    "compute",
    "interpolate",
]

#: Course length used for DLS, build and turn rate, keyed by unit.
COURSE_LENGTH = {"ft": 100.0, "m": 30.0}

#: Below this dogleg (radians) the ratio factor is set to its series limit, 1.
BETA_SMALL = 1e-7

#: Doglegs this close to 180 degrees make the ratio factor blow up.
BETA_MAX = math.pi - 1e-6

#: Turn rate is not reported for a course where either station is within
#: this many degrees of vertical (0 or 180 inclination). Azimuth readings
#: there are dominated by noise, so azimuth change per course length is not
#: a meaningful steering number.
TURN_MIN_INC = 3.0


class SurveyError(ValueError):
    """Raised for invalid survey input. The message is meant for a person."""


@dataclass(frozen=True)
class Station:
    md: float
    inc: float
    azi: float


@dataclass(frozen=True)
class TieIn:
    """Known position the calculation starts from.

    If ``md`` equals the first survey MD, that survey's inclination and
    azimuth are used and ``inc`` / ``azi`` here are ignored. Otherwise the
    tie-in becomes its own station and ``inc`` / ``azi`` describe the hole
    direction there (default vertical).
    """

    md: float = 0.0
    tvd: float = 0.0
    north: float = 0.0
    east: float = 0.0
    inc: float = 0.0
    azi: float = 0.0


@dataclass
class PathPoint:
    md: float
    inc: float
    azi: float
    tvd: float
    north: float
    east: float
    vs: float
    dogleg: float  # degrees, over the course ending at this station
    dls: float  # degrees per course length
    build: float  # degrees per course length
    turn: float  # degrees per course length
    is_tie_in: bool = False
    turn_suppressed: bool = False  # True when the course is too near vertical for turn

    def as_dict(self) -> dict:
        return {
            "md": self.md,
            "inc": self.inc,
            "azi": self.azi,
            "tvd": self.tvd,
            "north": self.north,
            "east": self.east,
            "vs": self.vs,
            "dogleg": self.dogleg,
            "dls": self.dls,
            "build": self.build,
            "turn": self.turn,
            "is_tie_in": self.is_tie_in,
            "turn_suppressed": self.turn_suppressed,
        }


@dataclass
class WellPath:
    points: List[PathPoint]
    units: str
    course_length: float
    vs_azimuth: float
    vs_azimuth_is_auto: bool
    closure_distance: float
    closure_azimuth: float
    max_dls: float
    max_dls_md: float
    tie_in: TieIn = field(default_factory=TieIn)
    skipped_above_tie_in: int = 0

    def summary(self) -> dict:
        last = self.points[-1]
        return {
            "units": self.units,
            "course_length": self.course_length,
            "td_md": last.md,
            "td_tvd": last.tvd,
            "td_north": last.north,
            "td_east": last.east,
            "vs_azimuth": self.vs_azimuth,
            "vs_azimuth_is_auto": self.vs_azimuth_is_auto,
            "closure_distance": self.closure_distance,
            "closure_azimuth": self.closure_azimuth,
            "max_dls": self.max_dls,
            "max_dls_md": self.max_dls_md,
            "skipped_above_tie_in": self.skipped_above_tie_in,
        }


# ---------------------------------------------------------------------------
# Angle helpers
# ---------------------------------------------------------------------------


def _finite(x: float, what: str) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        raise SurveyError(f"{what} is not a number: {x!r}") from None
    if not math.isfinite(v):
        raise SurveyError(f"{what} is not a finite number: {x!r}")
    return v


def normalize_azimuth(a: float) -> float:
    """Return azimuth in [0, 360)."""
    r = math.fmod(a, 360.0)
    if r < 0.0:
        r += 360.0
    if r >= 360.0:  # -1e-20 + 360 rounds to 360
        r = 0.0
    return r


def turn_difference(a1: float, a2: float) -> float:
    """Shortest signed azimuth change a2 - a1 in degrees, in (-180, 180]."""
    d = math.fmod(a2 - a1, 360.0)
    if d <= -180.0:
        d += 360.0
    elif d > 180.0:
        d -= 360.0
    return d


def _unit_vector(inc_rad: float, azi_rad: float):
    s = math.sin(inc_rad)
    return (s * math.cos(azi_rad), s * math.sin(azi_rad), math.cos(inc_rad))


def dogleg(inc1: float, azi1: float, inc2: float, azi2: float) -> float:
    """Dogleg angle in radians between two survey directions (degrees in).

    Equivalent to arccos(cos(I2-I1) - sin I1 sin I2 (1 - cos(A2-A1))) but
    computed as beta = 2 atan2(|t2 - t1|, |t2 + t1|) from the unit tangent
    vectors, which keeps full precision for very small and very large angles.
    """
    t1 = _unit_vector(math.radians(inc1), math.radians(azi1))
    t2 = _unit_vector(math.radians(inc2), math.radians(azi2))
    return _dogleg_vec(t1, t2)


def _dogleg_vec(t1, t2) -> float:
    dx, dy, dz = t2[0] - t1[0], t2[1] - t1[1], t2[2] - t1[2]
    sx, sy, sz = t2[0] + t1[0], t2[1] + t1[1], t2[2] + t1[2]
    return 2.0 * math.atan2(
        math.sqrt(dx * dx + dy * dy + dz * dz), math.sqrt(sx * sx + sy * sy + sz * sz)
    )


def ratio_factor(beta: float) -> float:
    """RF = (2 / beta) tan(beta / 2); 1 when beta < BETA_SMALL."""
    if beta < BETA_SMALL:
        return 1.0
    return 2.0 / beta * math.tan(beta / 2.0)


def min_curve_step(dmd: float, inc1: float, azi1: float, inc2: float, azi2: float):
    """One minimum curvature course. Returns (dN, dE, dTVD, beta_rad)."""
    i1, a1 = math.radians(inc1), math.radians(azi1)
    i2, a2 = math.radians(inc2), math.radians(azi2)
    t1 = _unit_vector(i1, a1)
    t2 = _unit_vector(i2, a2)
    beta = _dogleg_vec(t1, t2)
    if beta > BETA_MAX:
        raise SurveyError(
            "Two consecutive surveys point in opposite directions (dogleg near 180 deg); "
            "minimum curvature is undefined there."
        )
    rf = ratio_factor(beta)
    h = dmd / 2.0 * rf
    dn = h * (t1[0] + t2[0])
    de = h * (t1[1] + t2[1])
    dv = h * (t1[2] + t2[2])
    return dn, de, dv, beta


def _near_vertical(inc: float) -> bool:
    return inc < TURN_MIN_INC or inc > 180.0 - TURN_MIN_INC


# ---------------------------------------------------------------------------
# Main calculation
# ---------------------------------------------------------------------------


def _as_station(row, index: int) -> Station:
    if isinstance(row, Station):
        md, inc, azi = row.md, row.inc, row.azi
    elif isinstance(row, dict):
        try:
            md, inc, azi = row["md"], row["inc"], row["azi"]
        except KeyError as exc:
            raise SurveyError(f"Survey {index + 1}: missing key {exc.args[0]!r}") from None
    else:
        try:
            md, inc, azi = row[0], row[1], row[2]
        except (TypeError, IndexError):
            raise SurveyError(f"Survey {index + 1}: expected MD, Inc, Azi") from None
    md = _finite(md, f"Survey {index + 1} MD")
    inc = _finite(inc, f"Survey {index + 1} inclination")
    azi = _finite(azi, f"Survey {index + 1} azimuth")
    if inc < 0.0 or inc > 180.0:
        raise SurveyError(
            f"Survey {index + 1} (MD {md:g}): inclination {inc:g} is outside 0 to 180 degrees."
        )
    return Station(md, inc, normalize_azimuth(azi))


def validate(surveys: Iterable) -> List[Station]:
    """Check and normalise survey rows. Returns a list of Station."""
    out: List[Station] = []
    for k, row in enumerate(surveys):
        st = _as_station(row, k)
        if out and not st.md > out[-1].md:
            raise SurveyError(
                f"Survey {k + 1}: MD {st.md:g} is not greater than the previous MD "
                f"{out[-1].md:g}. Measured depth must strictly increase."
            )
        out.append(st)
    if not out:
        raise SurveyError("No surveys given.")
    return out


def _vs(north: float, east: float, vs_az_deg: float) -> float:
    a = math.radians(vs_az_deg)
    return north * math.cos(a) + east * math.sin(a)


def closure(north: float, east: float):
    """Closure distance and azimuth (degrees, [0, 360)) from the reference."""
    dist = math.hypot(north, east)
    if dist == 0.0:
        return 0.0, 0.0
    return dist, normalize_azimuth(math.degrees(math.atan2(east, north)))


def compute(
    surveys: Sequence,
    units: str = "ft",
    vs_azimuth: Optional[float] = None,
    tie_in: Optional[TieIn] = None,
) -> WellPath:
    """Compute the full well path by minimum curvature.

    surveys: rows of (MD, Inc, Azi), dicts with md/inc/azi, or Station.
    units: "ft" (rates per 100 ft) or "m" (rates per 30 m).
    vs_azimuth: vertical section azimuth in degrees. None means the closure
        azimuth to the last station (0 if the well has no horizontal offset).
    tie_in: starting position. Default is the surface: MD 0, TVD 0, N 0, E 0,
        vertical. With the default and a first survey deeper than MD 0, the
        hole is assumed to run from a vertical surface station to the first
        survey by minimum curvature (so a vertical first survey gives TVD = MD).
        Surveys shallower than the tie-in MD are ignored and counted in
        ``skipped_above_tie_in``.
    """
    if units not in COURSE_LENGTH:
        raise SurveyError(f"Units must be 'ft' or 'm', got {units!r}.")
    course = COURSE_LENGTH[units]
    stations = validate(surveys)
    tie = tie_in if tie_in is not None else TieIn()
    t_md = _finite(tie.md, "Tie-in MD")
    t_tvd = _finite(tie.tvd, "Tie-in TVD")
    t_n = _finite(tie.north, "Tie-in north")
    t_e = _finite(tie.east, "Tie-in east")
    t_inc = _finite(tie.inc, "Tie-in inclination")
    t_azi = normalize_azimuth(_finite(tie.azi, "Tie-in azimuth"))
    if t_inc < 0.0 or t_inc > 180.0:
        raise SurveyError(f"Tie-in inclination {t_inc:g} is outside 0 to 180 degrees.")
    tie = TieIn(t_md, t_tvd, t_n, t_e, t_inc, t_azi)

    skipped = sum(1 for st in stations if st.md < t_md)
    stations = [st for st in stations if st.md >= t_md]
    if not stations:
        raise SurveyError(
            f"Every survey is above the tie-in MD {t_md:g}. Surveys must reach the tie-in or below."
        )

    points: List[PathPoint] = []
    if stations[0].md == t_md:
        first = stations[0]
        rest = stations[1:]
        points.append(
            PathPoint(first.md, first.inc, first.azi, t_tvd, t_n, t_e, 0.0, 0.0, 0.0, 0.0, 0.0, True)
        )
    else:
        rest = stations
        points.append(PathPoint(t_md, t_inc, t_azi, t_tvd, t_n, t_e, 0.0, 0.0, 0.0, 0.0, 0.0, True))

    for st in rest:
        p = points[-1]
        dmd = st.md - p.md
        dn, de, dv, beta = min_curve_step(dmd, p.inc, p.azi, st.inc, st.azi)
        dl_deg = math.degrees(beta)
        scale = course / dmd
        suppressed = _near_vertical(p.inc) or _near_vertical(st.inc)
        if suppressed:
            turn = 0.0  # azimuth is noise near vertical; see TURN_MIN_INC
        else:
            turn = turn_difference(p.azi, st.azi) * scale
        points.append(
            PathPoint(
                md=st.md,
                inc=st.inc,
                azi=st.azi,
                tvd=p.tvd + dv,
                north=p.north + dn,
                east=p.east + de,
                vs=0.0,
                dogleg=dl_deg,
                dls=dl_deg * scale,
                build=(st.inc - p.inc) * scale,
                turn=turn,
                turn_suppressed=suppressed,
            )
        )

    last = points[-1]
    cdist, cazi = closure(last.north, last.east)
    if vs_azimuth is None:
        vs_az = cazi
        auto = True
    else:
        vs_az = normalize_azimuth(_finite(vs_azimuth, "VS azimuth"))
        auto = False
    for p in points:
        p.vs = _vs(p.north, p.east, vs_az)

    max_dls, max_md = 0.0, points[0].md
    for p in points[1:]:
        if p.dls > max_dls:
            max_dls, max_md = p.dls, p.md

    return WellPath(
        points=points,
        units=units,
        course_length=course,
        vs_azimuth=vs_az,
        vs_azimuth_is_auto=auto,
        closure_distance=cdist,
        closure_azimuth=cazi,
        max_dls=max_dls,
        max_dls_md=max_md,
        tie_in=tie,
        skipped_above_tie_in=skipped,
    )


def interpolate(path: WellPath, md: float) -> PathPoint:
    """Interpolate a point at measured depth ``md`` along the minimum curvature arc.

    The direction at a fraction f of the course is the spherical linear
    interpolation of the end tangents: t(f) = [sin((1-f) beta) t1 + sin(f beta) t2] / sin(beta),
    and the position comes from a minimum curvature step from the upper
    station to that point. DLS, build and turn are those of the course.
    """
    md = _finite(md, "Interpolation MD")
    pts = path.points
    if md < pts[0].md or md > pts[-1].md:
        raise SurveyError(
            f"MD {md:g} is outside the surveyed interval {pts[0].md:g} to {pts[-1].md:g}."
        )
    for p in pts:
        if p.md == md:
            return PathPoint(**p.as_dict())
    k = 1
    while pts[k].md < md:
        k += 1
    p1, p2 = pts[k - 1], pts[k]
    f = (md - p1.md) / (p2.md - p1.md)
    t1 = _unit_vector(math.radians(p1.inc), math.radians(p1.azi))
    t2 = _unit_vector(math.radians(p2.inc), math.radians(p2.azi))
    beta = _dogleg_vec(t1, t2)
    if beta < BETA_SMALL:
        w1, w2 = 1.0 - f, f
    else:
        sb = math.sin(beta)
        w1 = math.sin((1.0 - f) * beta) / sb
        w2 = math.sin(f * beta) / sb
    tx = w1 * t1[0] + w2 * t2[0]
    ty = w1 * t1[1] + w2 * t2[1]
    tz = w1 * t1[2] + w2 * t2[2]
    norm = math.sqrt(tx * tx + ty * ty + tz * tz)
    tx, ty, tz = tx / norm, ty / norm, tz / norm
    horiz = math.hypot(tx, ty)
    inc = math.degrees(math.atan2(horiz, tz))
    if horiz < 1e-12:
        azi = p1.azi
    else:
        azi = normalize_azimuth(math.degrees(math.atan2(ty, tx)))
    dn, de, dv, _ = min_curve_step(md - p1.md, p1.inc, p1.azi, inc, azi)
    north = p1.north + dn
    east = p1.east + de
    return PathPoint(
        md=md,
        inc=inc,
        azi=azi,
        tvd=p1.tvd + dv,
        north=north,
        east=east,
        vs=_vs(north, east, path.vs_azimuth),
        dogleg=p2.dogleg * f,
        dls=p2.dls,
        build=p2.build,
        turn=p2.turn,
        turn_suppressed=p2.turn_suppressed,
    )
