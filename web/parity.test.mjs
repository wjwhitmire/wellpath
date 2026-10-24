// Parity test: run the JavaScript core from web/app.html against tests/vectors.json.
// Usage: node web/parity.test.mjs
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import vm from "node:vm";

const here = dirname(fileURLToPath(import.meta.url));
const html = readFileSync(join(here, "app.html"), "utf8");
const m = html.match(/<script id="core">([\s\S]*?)<\/script>/);
if (!m) {
  console.error("Could not find <script id=\"core\"> in app.html");
  process.exit(1);
}
const ctx = vm.createContext({ Math, Number, String, Object, Array, Error, JSON, isFinite });
vm.runInContext(m[1] + "\n;globalThis.WellpathCore = WellpathCore;", ctx);
const C = ctx.WellpathCore;
const vectors = JSON.parse(readFileSync(join(here, "..", "tests", "vectors.json"), "utf8"));

// Relative tolerance 1e-9, with an absolute floor of 1e-9 for values near zero
// (for example a north or east coordinate that is analytically zero).
const REL = 1e-9;
const ABS = 1e-9;
function near(a, b) {
  return Math.abs(a - b) <= Math.max(ABS, REL * Math.max(Math.abs(a), Math.abs(b)));
}

let checks = 0;
let failures = 0;
function fail(msg) {
  failures++;
  console.error("FAIL " + msg);
}
function cmp(name, label, got, want) {
  checks++;
  if (typeof got !== "number" || !near(got, want)) fail(`${name} ${label}: got ${got}, want ${want}`);
}

for (const c of vectors.cases) {
  const opts = { units: c.units, vsAzimuth: c.vs === undefined ? null : c.vs, tieIn: c.tie || null };
  let path;
  try {
    path = C.compute(c.surveys, opts);
  } catch (e) {
    checks++;
    if (!c.expect_error || !e.isSurveyError) fail(`${c.name}: unexpected error ${e.message}`);
    continue;
  }
  if (c.expect_error) {
    checks++;
    fail(`${c.name}: expected an error, got a result`);
    continue;
  }
  checks++;
  if (path.points.length !== c.points.length) {
    fail(`${c.name}: ${path.points.length} points, want ${c.points.length}`);
    continue;
  }
  c.points.forEach((want, i) => {
    for (const f of vectors.fields) cmp(c.name, `point ${i} ${f}`, path.points[i][f], want[f]);
    checks++;
    if (path.points[i].turnSuppressed !== want.turn_suppressed) fail(`${c.name} point ${i} turnSuppressed: got ${path.points[i].turnSuppressed}, want ${want.turn_suppressed}`);
  });
  for (const [k, v] of Object.entries(c.summary)) cmp(c.name, `summary ${k}`, path.summary[k], v);
  (c.interp || []).forEach((md, i) => {
    const q = C.interpolate(path, md);
    for (const f of vectors.fields) cmp(c.name, `interp ${md} ${f}`, q[f], c.interp_results[i][f]);
    checks++;
    if (q.turnSuppressed !== c.interp_results[i].turn_suppressed) fail(`${c.name} interp ${md} turnSuppressed`);
  });
}

// Parser parity on the example file and a few edge inputs.
const example = readFileSync(join(here, "..", "examples", "horizontal_example.csv"), "utf8");
const ex = vectors.cases.find((c) => c.name === "example_horizontal");
const parsed = C.parseText(example);
checks++;
if (JSON.stringify(parsed) !== JSON.stringify(ex.surveys)) fail("parseText(example) differs from Python parse");
const okInputs = [
  ["Azimuth (deg)\tMD (ft)\tTool\tInclination\n10\t0\tMWD\t0\n\n20\t100\tMWD\t3.5\n", [[0, 0, 10], [100, 3.5, 20]]],
  ["# c\n0,0,0\n100, 1.5 ,200\n200;3;210\n300 4.5 220\n", [[0, 0, 0], [100, 1.5, 200], [200, 3, 210], [300, 4.5, 220]]],
  ['[{"md":0,"inc":0,"azi":0},[100,2,3]]', [[0, 0, 0], [100, 2, 3]]],
];
for (const [text, want] of okInputs) {
  checks++;
  const got = C.parseText(text);
  if (JSON.stringify(got) !== JSON.stringify(want)) fail(`parseText ${JSON.stringify(text).slice(0, 30)}: got ${JSON.stringify(got)}`);
}
const badInputs = ["", "\n\n", "MD,Inc\n0,0", "foo,bar,baz\n1,2,3", "0,0,0\n100,abc,0", "0,0,0\n100,NaN,0", "0,0", "[1,2",
  "[".repeat(100000), "[[0,0,0],[100,1," + "9".repeat(400) + "]]"];
checks++;
if (JSON.stringify(C.parseText("\ufeff0,0,0\n100,1,1")) !== "[[0,0,0],[100,1,1]]") fail("parseText BOM before numeric row");
for (const text of badInputs) {
  checks++;
  try {
    C.parseText(text);
    fail(`parseText should reject ${JSON.stringify(text)}`);
  } catch (e) {
    if (!e.isSurveyError) fail(`parseText ${JSON.stringify(text)} threw non-survey error ${e.message}`);
  }
}

for (const d of vectors.detect_units) {
  checks++;
  const got = C.detectUnits(d.text);
  if (got.units !== d.units || got.why !== d.why) fail(`detectUnits ${JSON.stringify(d.text).slice(0, 30)}: got ${JSON.stringify(got)}, want ${d.units} ${d.why}`);
}

if (failures) {
  console.error(`${failures} of ${checks} checks failed`);
  process.exit(1);
}
console.log(`parity ok: ${checks} checks across ${vectors.cases.length} vector cases (tolerance rel 1e-9, abs 1e-9)`);
