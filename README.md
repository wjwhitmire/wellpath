# Wellpath

Directional survey calculator for drilling people. Give it surveys (MD, inclination, azimuth) and it returns the full well path by the minimum curvature method: TVD, north, east, vertical section, dogleg severity, build rate, turn rate, closure, and interpolation at any MD.

Two ways to use it:

- **Browser tool:** https://wjwhitmire.github.io/wellpath/. Paste or upload surveys and get the table, plan view and section view. It runs entirely in your browser. Nothing you enter is uploaded.
- **Python library and CLI:** `wellpath`, pure Python, no runtime dependencies.

## Quick start

```bash
pip install -e .
wellpath examples/horizontal_example.csv                 # CSV to stdout, summary to stderr; units read from the file
wellpath examples/horizontal_example.csv --units m --vs-azi 0 --json
wellpath surveys.csv --tie-md 5000 --tie-tvd 4870.2 --tie-north 12.5 --tie-east -3.1 --interp 5250
```

```python
from wellpath import compute, interpolate, TieIn

path = compute([(0, 0, 0), (8500, 0.5, 205), (8594, 9.8, 352), (9440, 90.1, 359.1)], units="ft")
print(path.summary())             # TD MD/TVD, closure, VS azimuth, max DLS and its MD
for p in path.points:
    print(p.md, p.tvd, p.north, p.east, p.vs, p.dls, p.build, p.turn)
print(interpolate(path, 9000.0))  # point on the minimum curvature arc
```

Input text can be comma, tab, semicolon or space separated. A header row is optional; columns named MD, Inc and Azi (or Measured Depth, Inclination, Azimuth, with units in brackets) are found in any order and extra columns are ignored. Lines starting with `#` are comments. The depth unit is read from the input when it says so (`MD (m)` or `Measured Depth [ft]` in the header, a comment such as `# Units: m`, or `"units": "m"` in JSON); the browser tool and CLI then use it and say why, and the unit buttons or `--units` override it. Without a hint the unit is ft. JSON is also accepted: a list of `{md, inc, azi}` objects or `[md, inc, azi]` rows, or an object with a `surveys` list.

## Method

Each course between two surveys is modeled as a circular arc in the plane of the two survey directions. This is the minimum curvature method, the industry standard (SPE / ISCWSA; see SPE 84246, Sawaryn and Thorogood, "A Compendium of Directional Calculations Based on the Minimum Curvature Method", 2005).

With inclination I and azimuth A at the upper (1) and lower (2) stations and course length dMD = MD2 - MD1:

```
beta = arccos( cos(I2 - I1) - sin I1 sin I2 (1 - cos(A2 - A1)) )      dogleg angle
RF   = (2 / beta) tan(beta / 2)                                        ratio factor
       RF = 1 when beta < 1e-7 rad (series limit, RF = 1 + beta^2/12 + ...)
dN   = dMD/2 (sin I1 cos A1 + sin I2 cos A2) RF
dE   = dMD/2 (sin I1 sin A1 + sin I2 sin A2) RF
dTVD = dMD/2 (cos I1 + cos I2) RF
```

**Numerically stable dogleg.** The arccos form loses about half its significant digits for small doglegs because arccos is flat near 1. Wellpath computes the same angle as `beta = 2 atan2(|t2 - t1|, |t2 + t1|)`, where t is the unit tangent `(sin I cos A, sin I sin A, cos I)`. This is an identity for the same geometry and is accurate to machine precision from 0 to near 180 degrees. Tests check it against the arccos form.

**Rates.** C is the course length: 100 ft for feet, 30 m for metres.

```
DLS   = beta(deg) / dMD x C
Build = (I2 - I1) / dMD x C
Turn  = d / dMD x C,  d = shortest signed (A2 - A1), in (-180, 180]
```

So a turn from 359 to 1 degree is +2 degrees, not -358. Each rate is reported at the lower station of its course. Turn is not reported when either station of the course is within 3 degrees of vertical (`TURN_MIN_INC`): azimuth is undefined at zero inclination and dominated by noise just above it, so azimuth change per course length is not a steering number there. In the library `turn` is 0 and `turn_suppressed` is True; the CLI and the browser CSV leave the turn cell blank and the browser table shows n/a. DLS and build are still reported.

**Vertical section and closure.**

```
VS                = N cos(VSaz) + E sin(VSaz)
closure distance  = sqrt(N^2 + E^2)
closure azimuth   = atan2(E, N), in [0, 360)
```

The VS azimuth defaults to the closure azimuth to the last station (0 if there is no horizontal offset). You can override it.

**Interpolation at MD.** Inside a course the path follows the same circular arc. At fraction f = (MD - MD1) / dMD the direction is the spherical linear interpolation of the end tangents, `t(f) = [sin((1 - f) beta) t1 + sin(f beta) t2] / sin(beta)`, and the position is a minimum curvature step from the upper station to that direction over `MD - MD1`. On a true circular arc this is exact. Splitting a course at an interpolated point and recomputing returns the original lower station to 1e-10.

**Tie-in.** Default: MD 0, TVD 0, N 0, E 0, vertical. If the first survey is deeper than MD 0, a vertical surface station is added at MD 0 and the course to the first survey is computed by minimum curvature, so a vertical first survey gives TVD = MD. A user tie-in sets MD, TVD, N and E. If the tie-in MD equals a survey MD, that survey's inclination and azimuth are used at the tie-in; if the tie-in lies above the first survey, the tie-in is taken as vertical in the browser tool and CLI (the library accepts `inc` and `azi` on `TieIn`). Surveys shallower than the tie-in MD are ignored and counted.

**Validation.** MD must strictly increase. Inclination must be within 0 to 180 degrees. Azimuth is normalized to [0, 360), so 360, -10 and 720.5 become 0, 350 and 0.5. NaN, infinity and non-numeric cells are rejected with the line number. Two consecutive surveys pointing in opposite directions (dogleg within 1e-6 rad of 180 degrees) are rejected, because the arc is undefined there.

## Limits

- Azimuths are used as given. No magnetic declination, grid convergence or north reference conversion is applied. Enter all surveys in one reference (true or grid).
- No tool error model, uncertainty ellipses or anti-collision. Positions are the nominal path only.
- The ft/m switch sets the course length for DLS, build and turn (100 ft or 30 m) and the unit labels. It does not convert numbers.
- Minimum curvature is exact for a constant-curvature arc between stations. On real paths the error depends on survey spacing.
- Near vertical, azimuth readings swing widely. Turn rate is suppressed below 3 degrees inclination for that reason. The DLS a large azimuth change produces at low inclination can still look large while the hole barely moves; the included example shows this at the kickoff station (10.92 deg/100 ft over a 9.25 deg build).
- Interpolation reports DLS, build and turn of the course it falls in.
- Input limits: 5 MB and 50,000 survey rows. The browser table shows the first 2,000 stations; the copied CSV has all of them. Above 2,000 stations the charts draw the path line without station dots.
- Charts are drawn at equal scale on both axes. The section view plots TVD increasing downward.

## Validation

`pytest` covers:

- Vertical well: TVD = MD at every station, zero offset, zero DLS.
- Straight inclined tangent at several inclinations and azimuths, with a tie-in offset: exact trigonometry.
- Constant build at fixed azimuth from 0 to 90 degrees for BUR 3, 8, 10 and 15 deg/100 ft and three azimuths: `TVD = R sin I`, departure `= R (1 - cos I)`, `R = 5729.58 / BUR`, matched to 1e-11 relative, with DLS and build equal to BUR.
- A 3D build and turn (inclination 20 to 70, azimuth 300 to 40 through north, over 1000 ft) surveyed at 2 to 256 intervals, compared with an independent Simpson's rule integration of the exact tangent. Error falls by about 4x per halving (second order) and is under 0.005 ft at 4 ft spacing.
- Azimuth wrap 359 to 1: turn +2 deg/100 ft, small dogleg, east offset zero by symmetry.
- A worked example computed by hand in the test comments (tie-in MD 1000, 15/20 to 25/45 over 100 ft: dogleg 12.9517 deg, RF 1.00428, dN 27.2183, dE 19.4508, dTVD 94.0123).
- Tiny doglegs, ratio factor series limit, interpolation on an arc, tie-in handling, parser edge cases, CLI, and bad input.

`tests/make_vectors.py` writes `tests/vectors.json` from the Python library. `node web/parity.test.mjs` extracts the JavaScript core from `web/app.html` and checks it against those vectors to 1e-9 relative (1e-9 absolute floor near zero).

```bash
pip install -e .[dev]
pytest -q
python tests/make_vectors.py && node web/parity.test.mjs
python web/build_pages.py            # writes docs/index.html for GitHub Pages
```

## Repository layout

```
src/wellpath/      survey.py (math), parse.py (text and JSON input), cli.py
tests/             pytest suites, vectors.json and its generator
web/app.html       the browser tool; JS core in <script id="core">
web/parity.test.mjs, web/build_pages.py
docs/index.html    generated page for GitHub Pages
examples/          example survey file
```

## License

MIT. Copyright 2026 Will Whitmire. See [LICENSE](LICENSE).
