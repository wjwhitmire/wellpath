import math

import pytest

from wellpath import (
    SurveyError,
    TieIn,
    compute,
    dogleg,
    interpolate,
    min_curve_step,
    normalize_azimuth,
    ratio_factor,
    turn_difference,
)

D = math.radians


def close(a, b, tol=1e-9):
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


# ---------------------------------------------------------------------------
# Analytic cases
# ---------------------------------------------------------------------------


def test_vertical_well_tvd_equals_md():
    surveys = [(0, 0, 0), (500, 0, 0), (1234.5, 0, 0), (10000, 0, 137)]
    path = compute(surveys)
    for p, s in zip(path.points, surveys):
        assert close(p.tvd, s[0])
        assert p.north == 0.0 and p.east == 0.0
        assert p.dls == 0.0
        assert p.turn == 0.0  # no turn reported when inclination is zero
    assert all(p.turn_suppressed for p in path.points[1:])
    assert path.closure_distance == 0.0
    assert path.vs_azimuth == 0.0


def test_vertical_first_survey_below_surface_defaults_tvd_equals_md():
    path = compute([(800, 0, 0), (900, 0, 0)])
    assert path.points[0].md == 0.0 and path.points[0].is_tie_in
    assert close(path.points[1].tvd, 800.0)
    assert close(path.points[2].tvd, 900.0)


@pytest.mark.parametrize("inc,azi", [(30, 0), (45, 90), (60, 225), (89.5, 333.3), (12.25, 359.99)])
def test_straight_inclined_tangent_exact_trig(inc, azi):
    md0, md1 = 2000.0, 3500.0
    tie = TieIn(md=md0, tvd=1900.0, north=10.0, east=-5.0)
    path = compute([(md0, inc, azi), (md0 + 500, inc, azi), (md1, inc, azi)], tie_in=tie)
    L = md1 - md0
    last = path.points[-1]
    assert close(last.tvd, 1900.0 + L * math.cos(D(inc)))
    assert close(last.north, 10.0 + L * math.sin(D(inc)) * math.cos(D(azi)))
    assert close(last.east, -5.0 + L * math.sin(D(inc)) * math.sin(D(azi)))
    assert abs(last.dls) < 1e-9
    assert abs(last.build) < 1e-12 and abs(last.turn) < 1e-12


@pytest.mark.parametrize("bur", [3.0, 8.0, 10.0, 15.0])
@pytest.mark.parametrize("azi", [0.0, 47.0, 270.0])
def test_constant_build_circular_arc_is_exact(bur, azi):
    # Constant build in a vertical plane is a circular arc. Minimum
    # curvature models each course as a circular arc, so it must reproduce
    # the arc exactly whatever the station spacing.
    #   R = (180/pi) * 100 / BUR = 5729.58 / BUR  (ft, BUR in deg/100 ft)
    #   TVD = R sin I,  departure = R (1 - cos I),  MD = R I (I in radians)
    R = 18000.0 / math.pi / bur
    incs = [0, 1, 5, 12.5, 30, 45, 60, 77.7, 90]
    surveys = [(R * D(i), i, azi) for i in incs]
    path = compute(surveys)
    for p, i in zip(path.points, incs):
        dep = R * (1 - math.cos(D(i)))
        assert close(p.tvd, R * math.sin(D(i)), 1e-11)
        assert close(p.north, dep * math.cos(D(azi)), 1e-11) or abs(p.north - dep * math.cos(D(azi))) < 1e-9
        assert close(p.east, dep * math.sin(D(azi)), 1e-11) or abs(p.east - dep * math.sin(D(azi))) < 1e-9
    for p in path.points[1:]:
        assert close(p.dls, bur, 1e-9)
        assert close(p.build, bur, 1e-9)
    assert close(path.max_dls, bur, 1e-9)


def test_5729_constant():
    # 100 * 180 / pi
    assert abs(18000.0 / math.pi - 5729.58) < 0.01


def _helix_reference(inc0, azi0, dI, dA, md_total, n):
    """Reference position by fine subdivision of a path whose inclination and
    azimuth vary linearly with MD (not a circular arc), integrated with
    composite Simpson's rule on the exact tangent. Independent of min curve."""
    h = md_total / n
    N = E = V = 0.0
    for k in range(n + 1):
        f = k / n
        i = D(inc0 + dI * f)
        a = D(azi0 + dA * f)
        w = 1 if k in (0, n) else (4 if k % 2 else 2)
        N += w * math.sin(i) * math.cos(a)
        E += w * math.sin(i) * math.sin(a)
        V += w * math.cos(i)
    return N * h / 3, E * h / 3, V * h / 3


def test_3d_turning_arc_converges_under_subdivision():
    # A 3D build-and-turn: inclination 20 -> 70, azimuth 300 -> 40 (through
    # north) over 1000 ft. Survey it at coarser and finer spacings; min curve
    # must converge to the true integral, with error falling roughly as h^2.
    inc0, dI, azi0, dA, L = 20.0, 50.0, 300.0, 100.0, 1000.0
    ref = _helix_reference(inc0, azi0, dI, dA, L, 20000)
    errs = []
    for n in (2, 4, 8, 16, 32, 64, 128, 256):
        surveys = [
            (L * k / n, inc0 + dI * k / n, normalize_azimuth(azi0 + dA * k / n)) for k in range(n + 1)
        ]
        p = compute(surveys, tie_in=TieIn(md=0.0)).points[-1]
        err = math.sqrt((p.north - ref[0]) ** 2 + (p.east - ref[1]) ** 2 + (p.tvd - ref[2]) ** 2)
        errs.append(err)
    for a, b in zip(errs, errs[1:]):
        assert b < a
        assert 3.0 < a / b < 5.0  # second order
    assert errs[-1] < 5e-3  # about 0.003 ft at 4 ft spacing


def test_azimuth_wrap_359_to_1():
    path = compute([(1000, 45, 359), (1100, 45, 1)], tie_in=TieIn(md=1000, tvd=900))
    p = path.points[-1]
    # Turn is +2 deg over 100 ft, not -358
    assert close(p.turn, 2.0)
    # Same geometry as 179 -> 181 rotated: symmetric about north, so east ~ 0
    # and north = 2 * 50 * sin45 * cos1 * RF
    beta = dogleg(45, 359, 45, 1)
    rf = ratio_factor(beta)
    assert close(p.north, 100 * math.sin(D(45)) * math.cos(D(1)) * rf)
    assert abs(p.east) < 1e-12
    # Dogleg is small (about 1.41 deg), not 358
    assert close(p.dogleg, math.degrees(math.acos(math.cos(0) - math.sin(D(45)) ** 2 * (1 - math.cos(D(2))))), 1e-9)
    assert p.dls < 1.5


def test_azimuth_normalization_and_360():
    path = compute([(0, 10, 360), (100, 10, -10), (200, 10, 720.5)])
    assert path.points[0].azi == 0.0
    assert close(path.points[1].azi, 350.0)
    assert close(path.points[2].azi, 0.5)
    assert normalize_azimuth(-1e-20) == 0.0
    assert turn_difference(350, 10) == 20
    assert turn_difference(10, 350) == -20
    assert turn_difference(0, 180) == 180


def test_vs_default_and_override():
    path = compute([(0, 0, 0), (1000, 30, 135), (2000, 30, 135)])
    assert path.vs_azimuth_is_auto
    assert close(path.vs_azimuth, 135.0)
    assert close(path.points[-1].vs, path.closure_distance)
    p2 = compute([(0, 0, 0), (1000, 30, 135), (2000, 30, 135)], vs_azimuth=45)
    assert not p2.vs_azimuth_is_auto
    assert abs(p2.points[-1].vs) < 1e-9  # perpendicular to the well direction


def test_metric_course_length():
    ft = compute([(0, 0, 0), (100, 10, 0)], units="ft")
    m = compute([(0, 0, 0), (100, 10, 0)], units="m")
    assert close(ft.points[-1].dls, 10.0)
    assert close(m.points[-1].dls, 3.0)
    assert close(ft.points[-1].tvd, m.points[-1].tvd)


# ---------------------------------------------------------------------------
# Numerical behaviour of dogleg and ratio factor
# ---------------------------------------------------------------------------


def test_tiny_dogleg_is_not_noisy():
    # arccos loses half the digits near 1; atan2 form keeps them.
    b = dogleg(30, 100, 30 + 1e-7, 100)
    assert close(b, D(1e-7), 1e-6)
    assert dogleg(30, 100, 30, 100) == 0.0
    assert ratio_factor(0.0) == 1.0
    assert ratio_factor(5e-8) == 1.0
    # Series: RF = 1 + beta^2/12 + ...
    assert close(ratio_factor(1e-3), 1 + 1e-6 / 12, 1e-12)


def test_dogleg_matches_textbook_formula():
    for (i1, a1, i2, a2) in [(15, 20, 25, 45), (5, 350, 40, 10), (80, 90, 95, 120), (0, 0, 60, 200)]:
        c = math.cos(D(i2 - i1)) - math.sin(D(i1)) * math.sin(D(i2)) * (1 - math.cos(D(a2 - a1)))
        assert close(dogleg(i1, a1, i2, a2), math.acos(c), 1e-12)


def test_opposite_directions_rejected():
    with pytest.raises(SurveyError):
        min_curve_step(100, 0, 0, 180, 0)


# ---------------------------------------------------------------------------
# Worked example, by hand
# ---------------------------------------------------------------------------


def test_worked_example_by_hand():
    # Tie-in: MD 1000 ft, TVD 980.00, N 50.00, E 20.00; survey there 15 deg / 20 deg.
    # Next survey: MD 1100 ft, 25 deg / 45 deg. Course length dMD = 100 ft.
    #
    # Dogleg:
    #   cos(beta) = cos(25-15) - sin15 sin25 (1 - cos(45-20))
    #             = 0.98480775 - 0.25881905 * 0.42261826 * (1 - 0.90630779)
    #             = 0.98480775 - 0.10938021 * 0.09369221
    #             = 0.98480775 - 0.01024808 = 0.97455954
    #   beta = arccos(0.97455954) = 0.22604895 rad = 12.9517 deg
    # Ratio factor:
    #   RF = (2 / 0.22604895) * tan(0.11302447) = 8.84764 * 0.11350858 = 1.00428005
    # Direction terms:
    #   sinI1 cosA1 = 0.25881905 * 0.93969262 = 0.24321035
    #   sinI2 cosA2 = 0.42261826 * 0.70710678 = 0.29883624
    #   sinI1 sinA1 = 0.25881905 * 0.34202014 = 0.08852133
    #   sinI2 sinA2 = 0.42261826 * 0.70710678 = 0.29883624
    #   cosI1 = 0.96592583, cosI2 = 0.90630779
    # Increments (dMD/2 = 50):
    #   dN   = 50 * (0.24321035 + 0.29883624) * 1.00428005 = 27.2183
    #   dE   = 50 * (0.08852133 + 0.29883624) * 1.00428005 = 19.4508
    #   dTVD = 50 * (0.96592583 + 0.90630779) * 1.00428005 = 94.0123
    # Station at 1100: TVD 1074.0123, N 77.2183, E 39.4508
    # DLS   = 12.9517 deg / 100 ft
    # Build = (25 - 15) / 100 * 100 = 10.00 deg/100 ft
    # Turn  = (45 - 20) / 100 * 100 = 25.00 deg/100 ft
    # Closure = sqrt(77.2183^2 + 39.4508^2) = 86.7123 @ atan2(39.4508, 77.2183) = 27.0624 deg
    tie = TieIn(md=1000, tvd=980.0, north=50.0, east=20.0)
    path = compute([(1000, 15, 20), (1100, 25, 45)], tie_in=tie)
    p = path.points[-1]
    assert abs(p.tvd - 1074.0123) < 5e-5
    assert abs(p.north - 77.2183) < 5e-5
    assert abs(p.east - 39.4508) < 5e-5
    assert abs(p.dls - 12.9517) < 5e-5
    assert abs(p.build - 10.0) < 1e-12
    assert abs(p.turn - 25.0) < 1e-12
    assert abs(path.closure_distance - 86.7123) < 5e-4
    assert abs(path.closure_azimuth - 27.0624) < 5e-4
    assert path.max_dls_md == 1100


# ---------------------------------------------------------------------------
# Interpolation
# ---------------------------------------------------------------------------


def test_interpolate_on_circular_arc_is_exact():
    bur = 10.0
    R = 18000.0 / math.pi / bur
    path = compute([(0, 0, 30), (R * D(30), 30, 30), (R * D(90), 90, 30)])
    for inc in (7.0, 30.0, 51.3, 89.0):
        q = interpolate(path, R * D(inc))
        assert close(q.inc, inc, 1e-10)
        assert close(q.azi, 30.0, 1e-10)
        assert close(q.tvd, R * math.sin(D(inc)), 1e-10)
        dep = R * (1 - math.cos(D(inc)))
        assert close(math.hypot(q.north, q.east), dep, 1e-10)


def test_interpolate_consistent_with_stations_and_3d():
    path = compute([(0, 0, 0), (1000, 20, 300), (1500, 60, 40), (2000, 61, 41)])
    # At a station it returns the station
    q = interpolate(path, 1500)
    assert q.tvd == path.points[2].tvd
    # Splitting a course at the interpolated point and recomputing gives the same end point
    mid = interpolate(path, 1234.0)
    split = compute([(0, 0, 0), (1000, 20, 300), (1234.0, mid.inc, mid.azi), (1500, 60, 40), (2000, 61, 41)])
    a, b = split.points[3], path.points[2]
    assert close(a.tvd, b.tvd, 1e-10) and close(a.north, b.north, 1e-10) and close(a.east, b.east, 1e-10)
    assert close(split.points[2].tvd, mid.tvd, 1e-12)
    with pytest.raises(SurveyError):
        interpolate(path, 2500)
    with pytest.raises(SurveyError):
        interpolate(path, -1)


def test_interpolate_through_vertical_station():
    path = compute([(0, 0, 0), (100, 0, 0), (200, 0, 0)])
    q = interpolate(path, 150)
    assert close(q.tvd, 150) and q.inc == 0.0


# ---------------------------------------------------------------------------
# Tie-in
# ---------------------------------------------------------------------------


def test_tie_in_offsets_carry_through():
    s = [(5000, 30, 45), (5100, 32, 47)]
    a = compute(s, tie_in=TieIn(md=5000, tvd=0, north=0, east=0))
    b = compute(s, tie_in=TieIn(md=5000, tvd=4800, north=-100, east=250))
    assert close(b.points[-1].tvd - a.points[-1].tvd, 4800)
    assert close(b.points[-1].north - a.points[-1].north, -100)
    assert close(b.points[-1].east - a.points[-1].east, 250)


def test_tie_in_above_first_survey_with_direction():
    path = compute([(1100, 10, 90)], tie_in=TieIn(md=1000, tvd=995, inc=10, azi=90))
    p = path.points[-1]
    assert close(p.tvd, 995 + 100 * math.cos(D(10)))
    assert close(p.east, 100 * math.sin(D(10)))


def test_surveys_above_tie_in_are_skipped():
    path = compute([(0, 0, 0), (500, 1, 10), (1000, 3, 20), (1100, 5, 25)], tie_in=TieIn(md=1000, tvd=999))
    assert path.skipped_above_tie_in == 2
    assert path.points[0].md == 1000 and path.points[0].tvd == 999
    with pytest.raises(SurveyError):
        compute([(0, 0, 0), (100, 1, 1)], tie_in=TieIn(md=500))


# ---------------------------------------------------------------------------
# Bad input
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "surveys",
    [
        [],
        [(0, 0, 0), (0, 1, 1)],  # MD not strictly increasing
        [(0, 0, 0), (100, 1, 1), (90, 2, 2)],
        [(0, -1, 0)],
        [(0, 180.01, 0)],
        [(0, float("nan"), 0)],
        [(0, 0, float("inf"))],
        [("abc", 0, 0)],
        [(0, 0)],
        [{"md": 0, "inc": 0}],
    ],
)
def test_bad_inputs_raise(surveys):
    with pytest.raises(SurveyError):
        compute(surveys)


def test_bad_units_and_vs():
    with pytest.raises(SurveyError):
        compute([(0, 0, 0)], units="yd")
    with pytest.raises(SurveyError):
        compute([(0, 0, 0)], vs_azimuth=float("nan"))


def test_inclination_180_allowed():
    path = compute([(0, 170, 0), (100, 180, 0)], tie_in=TieIn(md=0))
    assert path.points[-1].tvd < 0


# ---------------------------------------------------------------------------
# Turn rate near vertical (review fix)
# ---------------------------------------------------------------------------


def test_turn_suppressed_near_vertical_example_kop():
    # Example KOP course: 8500 ft 0.55/205.6 to 8594 ft 9.80/352.0. The raw
    # azimuth change is +146.4 deg over 94 ft (155.7 deg/100 ft), which is
    # noise from a 0.55 deg station, not steering. It must not be reported.
    path = compute([(0, 0, 0), (8500, 0.55, 205.6), (8594, 9.8, 352.0), (8688, 19.1, 356.4)])
    kop = path.points[2]
    assert kop.turn_suppressed and kop.turn == 0.0
    assert close(kop.build, (9.8 - 0.55) / 94 * 100)  # build and DLS still reported
    assert kop.dls > 10
    nxt = path.points[3]
    assert not nxt.turn_suppressed and close(nxt.turn, 4.4 / 94 * 100)


@pytest.mark.parametrize("inc1,inc2,suppressed", [(2.99, 10, True), (3.0, 10, False), (10, 2.5, True), (177.5, 170, True), (176, 170, False)])
def test_turn_threshold_both_ends(inc1, inc2, suppressed):
    p = compute([(0, inc1, 10), (100, inc2, 20)], tie_in=TieIn(md=0)).points[-1]
    assert p.turn_suppressed is suppressed
    assert p.turn == (0.0 if suppressed else 10.0)


def test_interpolated_point_inherits_turn_suppression():
    path = compute([(0, 0, 0), (8500, 0.55, 205.6), (8594, 9.8, 352.0)])
    assert interpolate(path, 8550).turn_suppressed
