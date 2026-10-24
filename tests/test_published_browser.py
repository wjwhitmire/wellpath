"""Browser test of the page exactly as GitHub Pages serves it.

docs/ is copied to a temporary folder, the publish placeholders are filled
the way the release script fills them, and the copy is served under
/wellpath/ on localhost. Headless Chromium then runs the main workflows and
fails on any page error, console error or Content-Security-Policy violation.

Needs the playwright package and its Chromium; skipped when they are missing.
"""

import functools
import http.server
import shutil
import threading
from pathlib import Path

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

ROOT = Path(__file__).resolve().parent.parent
NAME = "wellpath"
FILL = {
    "https://wjwhitmire.github.io/wellpath/": f"https://wjwhitmire.github.io/{NAME}/",
    "wjwhitmire": "wjwhitmire",
    "https://github.com/wjwhitmire/wellpath": f"https://github.com/wjwhitmire/{NAME}",
}
WATCH = """
window.__csp = [];
document.addEventListener('securitypolicyviolation', e => window.__csp.push(e.violatedDirective + ' ' + e.blockedURI));
"""


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    root = tmp_path_factory.mktemp("pages")
    dest = root / NAME
    shutil.copytree(ROOT / "docs", dest)
    for f in dest.rglob("*"):
        if f.suffix in (".html", ".js", ".json", ".webmanifest", ".css", ".txt", ".xml"):
            text = f.read_text(encoding="utf-8")
            for k, v in FILL.items():
                text = text.replace(k, v)
            f.write_text(text, encoding="utf-8")
    handler = functools.partial(QuietHandler, directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/{NAME}/"
    server.shutdown()


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as exc:  # browser binary not installed
            pytest.skip(f"Chromium not available: {exc}")
        yield b
        b.close()


def open_page(browser, url, width=1280, **ctx):
    context = browser.new_context(viewport={"width": width, "height": 900}, **ctx)
    context.route("https://fonts.googleapis.com/**", lambda r: r.abort())
    context.route("https://fonts.gstatic.com/**", lambda r: r.abort())
    context.add_init_script(WATCH)
    page = context.new_page()
    page.problems = []
    page.on("pageerror", lambda e: page.problems.append(f"pageerror: {e}"))
    page.on(
        "console",
        lambda m: page.problems.append(f"console: {m.text}")
        if m.type == "error" and "fonts.g" not in m.text and "ERR_FAILED" not in m.text
        and not (m.location or {}).get("url", "").endswith("/favicon.ico")
        else None,
    )
    page.goto(url)
    return page


def assert_clean(page):
    csp = page.evaluate("window.__csp")
    assert not csp, csp
    assert not page.problems, page.problems
    assert page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth") <= 0
    for placeholder in FILL:
        assert placeholder not in page.content()


def status(page):
    return page.text_content("#status")


def set_surveys(page, text):
    page.fill("#surveys", text)
    page.click("#calc")


def test_example_loads_and_computes(site, browser):
    page = open_page(browser, site)
    assert status(page).startswith("Computed 29 stations.")
    assert "Set to ft from the comment line" in page.text_content("#unitsHint")
    assert page.locator("#chips .chip").count() == 5
    assert page.locator("#results tbody tr").count() == 29
    assert page.locator("#planBox svg").count() == 1 and page.locator("#secBox svg").count() == 1
    assert page.text_content("#interpOut").startswith("MD 9,000.00 ft")
    assert_clean(page)


def test_metric_header_sets_units_without_a_click(site, browser):
    page = open_page(browser, site)
    set_surveys(page, "MD (m),Inc,Azi\n0,0,0\n30,3,0\n60,6,0\n")
    assert page.is_checked("#unitsM")
    assert "from the header 'MD (m)'" in page.text_content("#unitsHint")
    assert "3.00°/30m" in page.text_content("#chips")
    # the user's own choice wins until the data changes
    page.click("label[for=unitsFt]")
    assert page.is_checked("#unitsFt")
    page.click("#calc")
    assert page.is_checked("#unitsFt")
    assert_clean(page)


def test_error_clears_old_results(site, browser):
    page = open_page(browser, site)
    set_surveys(page, "0,0,0\n100,181,0\n")
    assert "outside 0 to 180" in status(page)
    assert page.locator("#chips .chip").count() == 0
    assert page.locator("#results tbody tr").count() == 0
    assert page.is_disabled("#copyCsv")
    set_surveys(page, "0,0,0\n100,3,0\n")
    assert status(page).startswith("Computed 2")
    assert page.is_enabled("#copyCsv")


def test_bad_number_in_a_number_box_is_reported(site, browser):
    page = open_page(browser, site)
    page.click("#vsAzi")
    page.keyboard.type("1e")
    page.click("#calc")
    assert "VS azimuth (deg) is not a number" in status(page)


def test_tie_in_at_a_survey_has_no_false_note(site, browser):
    page = open_page(browser, site)
    page.fill("#tieMd", "8500")
    page.fill("#tieTvd", "8499")
    page.click("#calc")
    s = status(page)
    assert "6 survey(s) above the tie-in MD were ignored" in s
    assert "Tie-in station added" not in s
    page.fill("#tieMd", "8550")
    page.click("#calc")
    assert "Tie-in station added at MD 8,550.00" in status(page)


def test_tie_in_without_md_points_at_the_box(site, browser):
    page = open_page(browser, site)
    page.fill("#tieTvd", "100")
    page.click("#calc")
    assert "Enter the tie-in MD" in status(page)
    assert page.get_attribute("#tieMd", "aria-invalid") == "true"


def test_interpolate_and_copy_csv_fallback(site, browser):
    page = open_page(browser, site)
    page.fill("#interpMd", "8594")
    page.press("#interpMd", "Enter")
    assert "Inc 9.800" in page.text_content("#interpOut")
    page.evaluate("Object.defineProperty(navigator, 'clipboard', {value: undefined})")
    page.click("#copyCsv")
    csv = page.input_value("#csvFallback").splitlines()
    assert csv[0].startswith("MD (ft),Inc (deg)")
    assert len(csv) == 30


def test_upload_file(site, browser, tmp_path):
    f = tmp_path / "s.json"
    f.write_text('{"units": "m", "surveys": [[0,0,0],[300,10,90]]}')
    page = open_page(browser, site)
    page.set_input_files("#file", str(f))
    page.wait_for_function("document.getElementById('status').textContent.startsWith('Computed 2')")
    assert page.is_checked("#unitsM")


def test_large_survey_stays_responsive(site, browser):
    page = open_page(browser, site)
    text = "MD,Inc,Azi\n" + "".join(f"{i * 10},{min(90, i * 0.01):.2f},{(i * 0.1) % 360:.1f}\n" for i in range(20000))
    page.evaluate("t => { document.getElementById('surveys').value = t; }", text)
    page.evaluate("document.getElementById('calc').click()")
    assert status(page).startswith("Computed 20000 stations.")
    assert page.locator("#results tbody tr").count() == 2001


def test_phone_width(site, browser):
    page = open_page(browser, site, width=400, has_touch=True, is_mobile=True)
    assert status(page).startswith("Computed 29")
    assert_clean(page)
