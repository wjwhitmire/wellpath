# Security

## What the browser tool does with your data

- It makes no network requests. There is no fetch, XHR, WebSocket, beacon or analytics. The only external resource is the Google Fonts stylesheet, which carries no survey data.
- No data leaves the browser. Surveys you paste or upload are parsed and computed in the page and are never sent anywhere or stored.
- Files are read locally with the browser FileReader API, capped at 5 MB and 50,000 rows.
- User text is never inserted as HTML. The page uses no eval, no `new Function` and no inline event handlers. The GitHub Pages build adds a Content Security Policy that blocks all connections.

## Python library

No network calls, no pickle, no eval, no shell calls. The CLI reads only the file path you give it.

## Reporting an issue

Open a GitHub issue with the label `security`, or use GitHub private vulnerability reporting on this repository for anything sensitive. Please include the input that triggers the problem and the browser or Python version.
