"""Wrap web/app.html into docs/index.html as a full HTML document for GitHub Pages."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "web" / "app.html"
OUT = ROOT / "docs" / "index.html"

CSP = (
    "default-src 'none'; "
    "script-src 'unsafe-inline'; "
    "style-src 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src https://fonts.gstatic.com; "
    "img-src 'none'; connect-src 'none'; form-action 'none'; base-uri 'none'"
)


def build() -> str:
    page = SRC.read_text(encoding="utf-8")
    m = re.match(r"\s*(<title>.*?</title>)\s*(<link[^>]*>)\s*(<style>.*?</style>)(.*)\Z", page, re.S)
    if not m:
        raise SystemExit("app.html does not start with <title>, <link>, <style> as the page contract requires")
    title, link, style, body = m.groups()
    return (
        "<!doctype html>\n"
        '<html lang="en">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        f'<meta http-equiv="Content-Security-Policy" content="{CSP}">\n'
        '<meta name="referrer" content="no-referrer">\n'
        '<meta name="description" content="Directional survey calculator: minimum curvature TVD, N/E, vertical section, DLS, build and turn. Runs in your browser.">\n'
        f"{title}\n{link}\n{style}\n"
        "</head>\n<body>\n"
        f"{body.strip()}\n"
        "</body>\n</html>\n"
    )


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(build(), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
