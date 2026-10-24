# Testing

This file lists every function of Wellpath, how it was tested and the result. The browser checks ran against the published form of the page: `git archive HEAD`, publish placeholders filled, `docs/` served under `/wellpath/` on localhost, headless Chromium at 1280 px and 400 px (touch), light and dark.

## How to rerun

```bash
pip install -e .[dev]
pytest -q                                   # library, parser, CLI, regressions
python tests/make_vectors.py && node web/parity.test.mjs   # JS core matches Python
python web/build_pages.py                   # rebuild docs/index.html
pip install playwright && python -m playwright install chromium
pytest -q tests/test_published_browser.py   # published page under /wellpath/, main workflows
```

`tests/test_published_browser.py` copies `docs/`, fills the publish placeholders, serves the copy under `/wellpath/` and fails on any page error, console error, CSP violation, sideways scroll or leftover placeholder. It skips itself when Playwright is not installed; CI installs it in the `browser` job.

Suite size: 74 pytest + 1609 parity checks before this pass; 90 pytest (10 of them browser) + 1624 parity checks after.

## Function inventory

### Browser page

| Function | What was done | Result |
|---|---|---|
| Page load, published form | Opened `/wellpath/` with filled placeholders | Pass: example computes, 29 stations, no errors, no CSP violations |
| Layout 1280 px and 400 px | Measured scroll width, light and dark | Pass: no sideways scroll |
| Touch targets | Measured every control at 400 px touch | Pass: all at least 44 px |
| Dark theme | `prefers-color-scheme: dark` | Pass |
| Example data tag | Shown on load, hidden after edit or upload | Pass |
| Survey text box | Typing recomputes after 250 ms | Pass |
| Units ft / m | Click and arrow keys | Pass: rates per 100 ft or 30 m, labels change, max DLS scales by 0.3 |
| Units read from input | `MD (m)` header, `# Units: m` comment, JSON `units` | Pass after fix (new) |
| VS azimuth box | Blank (auto), 90, -90 | Pass: auto closure, user set, -90 shown as 270 |
| Bad number in a number box | Typed `1e` | Fail before (silently ignored, auto azimuth used); pass after fix |
| Tie-in MD, TVD, N, E | At a survey MD, between surveys, below TD, TVD without MD | Pass after fix (false "station added" note removed; missing MD now marks the MD box) |
| Calculate button | Click | Pass |
| Upload CSV (CSV, TSV, JSON) | `set_input_files` | Pass |
| Upload over 5 MB | 5 MB + 10 bytes | Pass: rejected with message |
| Upload empty file, Latin-1 file, same file twice | | Pass |
| Load example | After changing units and VS | Pass: text, ft and fields reset |
| Status line | good, warn, bad states | Pass |
| Summary chips | TD MD, TD TVD, max DLS, closure, VS azimuth | Pass |
| Results after an error | Bad input after a good run | Fail before (old numbers stayed, Copy CSV copied them); pass after fix |
| Plan view chart | Render, hover tooltip, leave | Pass |
| Section view chart | Render, hover tooltip, legend shows VS azimuth | Pass |
| Charts on resize | 1280 to 700 px | Pass: redrawn |
| Single-point and vertical well charts | MD 0 only; vertical | Pass: no NaN in SVG |
| Interpolate at MD | Default 9000, Enter key, at a station, at MD 0, out of range, blank | Pass |
| Results table | Tie-in row, max DLS row, turn n/a near vertical | Pass |
| Copy results as CSV | Clipboard; values checked against the Python library to 4 dp | Pass |
| Copy fallback | Clipboard missing or rejected | Pass: text box with CSV |
| Method and limits | Expand | Pass |
| Network | `fetch` from the page | Pass: blocked by `connect-src 'none'`; no network features exist |
| Print | Print media to PDF | Pass: renders |
| 50,000-row survey | Paste and calculate | Fail before (page frozen 48 s); pass after fix (2.6 s; table shows first 2,000 rows, CSV has all) |
| 50,001 rows | | Pass: rejected |
| `web/app.html` via file:// | Opened directly | Pass: computes the example (quirks mode, as the file is a fragment) |

### Parser (browser and Python)

| Input | Result |
|---|---|
| Comma, tab, semicolon, space separated | Pass |
| Header in any order, units in brackets, extra columns, quoted cells | Pass |
| Comments, blank lines, BOM, CRLF | Pass |
| JSON list of objects, list of rows, object with `surveys` | Pass |
| Empty, header only, partial header, free text | Pass: clear error |
| Non-numeric, NaN, 1e400, unicode digits, too few columns | Pass: clear error with line number |
| Inclination above 180 or below 0, MD equal or decreasing | Pass: rejected |
| Negative start MD, azimuth 720.5 | Pass: computed, azimuth normalised |
| Consecutive surveys 180 degrees apart | Pass: rejected |
| JSON malformed, string values, booleans | Pass: rejected |

### CLI

| Command | Result |
|---|---|
| `wellpath file.csv` | Pass: CSV out, summary on stderr, units line |
| `--json`, `--units m`, `--vs-azi 0` | Pass |
| `-` (stdin), `--interp` repeated | Pass |
| `--tie-md/--tie-tvd/--tie-north/--tie-east` | Pass |
| Missing file, bad survey, non-UTF-8, over 5 MB, interp out of range | Pass: message, exit 2 |
| `--vs-azi abc`, `--units km` | Pass: argparse error |
| `--vs-azi nan`, `--tie-md inf` | Pass: rejected |
| Units from the file header when `--units` is not given | Pass (new) |

### Library

`normalize_azimuth`, `turn_difference`, `dogleg`, `ratio_factor`, `min_curve_step`, `validate`, `closure`, `compute`, `interpolate`, `parse_text`, `detect_units`, `Station`, `TieIn`, `PathPoint.as_dict`, `WellPath.summary`: all covered by pytest and the parity vectors. Pass.

## Correctness checks

An independent implementation of the SPE 84246 arccos form was written outside the repo and compared with both the Python library and the JavaScript core in the published page. Largest relative difference in every case below 2.1e-12.

| Case | Hand or reference value | Result |
|---|---|---|
| Vertical well to 10,000 ft | TVD = MD, N = E = 0, DLS 0 | Pass |
| Tie-in 1000 ft, 15/20 to 25/45 over 100 ft | dogleg 12.9517, dN 27.2183, dE 19.4508, dTVD 94.0123 | Pass |
| Build 3 deg/100 ft, 0 to 90 deg | R = 5729.578/3 = 1909.859 ft; TVD = departure = R | Pass to 1e-12 |
| Zero dogleg 45 deg tangent | Straight-line trigonometry | Pass |
| Azimuth wrap 359 to 1 | Turn +2 deg, DLS 1.00 deg/100 ft at 30 deg inc | Pass |
| Azimuth 0 to 180 at zero inclination | Dogleg 0 | Pass |
| 180 deg dogleg (0 to 180 inc; 90/0 to 90/180) | Undefined | Pass: rejected |
| 179.9 deg dogleg | Finite, matches reference | Pass |
| 40,000 ft MD, 12,000 m metric well | Matches reference; DLS per 30 m | Pass |
| Published example: 45/130 to 52/139 over 95 ft | DLS 10.2168 deg/100 ft | Pass (10.216778) |

## Automation audit

| Decision point | Before | After |
|---|---|---|
| Depth units | User had to pick ft or m; default ft even for a metric file | Read from the header (`MD (m)`), a `# Units` comment or JSON `units`; one-line reason under the buttons; buttons override until the data changes. CLI does the same unless `--units` is given |
| VS azimuth | Already automatic (closure azimuth), override box | No change |
| Tie-in | Already defaults to surface | No change |
| Tie-in TVD/N/E without MD | Dead-end message | Message says where the MD goes and marks the MD box |
| Calculate | Already automatic on every edit | No change |

## Known limits

- The CLI rejects non-UTF-8 files; the browser reads them with replacement characters, so a Latin-1 comment still computes.
- The table shows the first 2,000 stations; the copied CSV has every station.
- No magnetic declination, grid convergence or uncertainty model (see README).
