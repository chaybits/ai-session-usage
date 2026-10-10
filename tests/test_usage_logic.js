// Tests for contents/ui/UsageLogic.js (run: node tests/test_usage_logic.js).
"use strict";
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const assert = require("node:assert/strict");

const here = __dirname;
const parent = path.dirname(here);
const pkg = path.join(parent, "src");
const source = fs.readFileSync(path.join(pkg, "contents", "ui", "UsageLogic.js"), "utf8")
    .split("\n").filter(l => !/^\s*\.(pragma|import)/.test(l)).join("\n");
const ctx = vm.createContext({});
vm.runInContext(source + "\nthis.L = { TAP_THROTTLE_MS, WATCHDOG_MS, FAST_RETRY_MS, MIN_ZOOM, MAX_ZOOM, MIN_SHRINK, COMPACT_ROWS, "
    + "scriptPath, parseOutput, nextPoll, resetInfo, resetStyle, visibleRows, isOutdated, levelOf, zoomFor, shrinkStep, displayPercent, shellQuote, "
    + "mergeKnownRows, parseKnownRows, compactParts, compactText, levelColor, applyOrder, arrangeRows, "
    + "rowsByProvider, defaultKnownOrder, moveId, preferredSize };", ctx);
const L = ctx.L;

let failed = 0;
function test(name, fn) {
    try { fn(); console.log("ok   " + name); } catch (e) { failed++; console.log("FAIL " + name + "\n" + e.message); }
}

const POLL = 300000;
const NOW = Date.parse("2026-10-03T12:00:00Z");

test("F11 scriptPath undoes URL escaping", () => {
    assert.equal(L.scriptPath("file:///tmp/a%20b/s%C3%BC dir%231/code/x.py"), "/tmp/a b/sü dir#1/code/x.py");
    assert.equal(L.scriptPath("file:///plain/x.py"), "/plain/x.py");
});

test("F20 parseOutput keeps the TAIL of a failed run's output", () => {
    const stderr = "Traceback (most recent call last):\n" + "  File x\n".repeat(40) + "ValueError: the real reason";
    const r = L.parseOutput("", stderr);
    assert.equal(r.error, "badoutput");
    assert.ok(r.message.endsWith("ValueError: the real reason"), r.message);
    assert.ok(r.message.length <= 160);
});

test("parseOutput reads the last JSON line", () => {
    assert.deepEqual(JSON.parse(JSON.stringify(L.parseOutput('noise\n{"ok": true, "rows": []}\n', ""))), { ok: true, rows: [] });
});

test("F23 parseOutput: valid JSON that is not the helper's shape is badoutput", () => {
    for (const line of ["null", "5", "true", '"text"', "[]", "{}", '{"ok": "yes"}', '{"ok": true}', '{"ok": true, "rows": 3}']) {
        const r = L.parseOutput(line + "\n", "");
        assert.equal(r.error, "badoutput", line);
        assert.equal(r.ok, false, line);
        assert.equal(r.message, line, "the output is shown");
    }
    assert.equal(L.parseOutput('{"ok": false, "error": "nocli"}', "").error, "nocli", "an error result passes");
});

test("B-06 parseOutput: a row that is not a row is badoutput, not a healthy answer", () => {
    for (const rows of ["[null]", "[5]", '[{"id": "claude:session"}]', '[{"percent": 5}]',
                        '[{"id": "x", "label": "y", "percent": "5"}]', '[{"id": "x", "label": 3, "percent": 5}]']) {
        const r = L.parseOutput('{"ok": true, "rows": ' + rows + '}\n', "");
        assert.equal(r.error, "badoutput", rows);
    }
    assert.equal(L.parseOutput('{"ok": true, "rows": [{"id": "x", "label": "y", "percent": 5, "resets_at": null}]}', "").ok, true);
});

test("B-01 a CLI that gave no usable answer retries fast, doubling up to the poll interval", () => {
    // the one transient failure the helper can report since the CLIs are asked directly (D16, D20): offline,
    // a server error, a crash, all `cli`; a helper the watchdog ended is `timeout`
    for (const kind of ["cli", "timeout"]) {
        const fail = { ok: false, error: kind };
        let p = L.nextPoll(fail, 0, POLL);
        assert.deepEqual([p.intervalMs, p.step], [30000, 30000], kind);
        p = L.nextPoll(fail, p.step, POLL);
        assert.deepEqual([p.intervalMs, p.step], [60000, 60000], kind);
        let step = p.step;
        for (let i = 0; i < 6; i++) { step = L.nextPoll(fail, step, POLL).step; }
        assert.equal(step, POLL, "bounded by the poll interval");
        assert.equal(L.nextPoll(fail, POLL, POLL).intervalMs, POLL);
    }
});

test("B-01 the kinds that do not change in 30 s wait the poll interval, success resets", () => {
    for (const kind of ["nologin", "nocli", "format", "nostatusline", "unreadable", "usage", "badoutput", "internal"]) {
        assert.deepEqual({ ...L.nextPoll({ ok: false, error: kind }, 0, POLL) }, { intervalMs: POLL, step: 0 }, kind);
    }
    assert.deepEqual({ ...L.nextPoll({ ok: true }, 120000, POLL) }, { intervalMs: POLL, step: 0 });
});

test("B-01 a poll interval shorter than the fast retry is never exceeded", () => {
    assert.equal(L.nextPoll({ ok: false, error: "cli" }, 0, 60000 / 2).intervalMs, 30000);
    assert.equal(L.nextPoll({ ok: false, error: "cli" }, 0, 20000).intervalMs, 20000);
});

test("B-02 shellQuote: a path with a space, a quote and a hash survives the shell", () => {
    assert.equal(L.shellQuote("/home/jo hn/it's a #dir/x.py"), "'/home/jo hn/it'\\''s a #dir/x.py'");
    assert.equal(L.shellQuote("plain"), "'plain'");
});

test("F07 resetInfo: future, now, long past", () => {
    assert.deepEqual({ ...L.resetInfo("2026-10-03T14:05:00Z", NOW) }, { kind: "future", mins: 125 });
    assert.equal(L.resetInfo("2026-10-03T12:00:10Z", NOW).kind, "now");
    assert.equal(L.resetInfo("2026-10-03T11:59:30Z", NOW).kind, "now");
    assert.equal(L.resetInfo("2026-10-03T08:00:00Z", NOW).kind, "past", "4 h after the reset is not 'now'");
    assert.equal(L.resetInfo("2026-10-03T12:00:30Z", NOW).kind, "future");
    assert.equal(L.resetInfo("2026-10-03T12:00:30Z", NOW).mins, 1);
});

test("resetInfo: empty and unparseable", () => {
    for (const bad of [null, undefined, "", "not a date"]) {
        assert.equal(L.resetInfo(bad, NOW).kind, "none");
    }
    assert.equal(L.resetInfo("2026-10-08T10:00:00.123456+00:00", NOW).kind, "future");
});

test("compactText: two rows per provider, a dot between rows and a bar between providers", () => {
    assert.equal(L.compactText(null), "--");
    assert.equal(L.compactText([{ rows: [] }]), "--");
    assert.equal(L.compactText([{ rows: [{ percent: 12.5 }, { percent: 40 }, { percent: 7 }] }]), "13% · 40%");
    assert.equal(L.compactText([{ rows: [{ percent: 12.5 }, { percent: 40 }] }, { rows: [] }, { rows: [{ percent: 2 }] }]),
                 "13% · 40% | 2%");
    const parts = L.compactParts([{ rows: [{ percent: 90 }] }]);
    assert.deepEqual(JSON.parse(JSON.stringify(parts)), [{ kind: "value", text: "90%", percent: 90 }]);
});

test("resetStyle: time for a session row, weekday within six days, date beyond", () => {
    assert.equal(L.resetStyle(false, 99999), "time");
    assert.equal(L.resetStyle(true, 6 * 1440), "weekday");
    assert.equal(L.resetStyle(true, 6 * 1440 + 1), "date");
});

test("visibleRows hides by id and tolerates no list", () => {
    const rows = [{ id: "claude:session" }, { id: "claude:weekly_scoped:Fable" }];
    assert.deepEqual(L.visibleRows(rows, ["claude:weekly_scoped:Fable"]).map(r => r.id), ["claude:session"]);
    assert.equal(L.visibleRows(rows, null).length, 2);
    assert.equal(L.visibleRows(null, []).length, 0);
});

test("isOutdated: older than the threshold only; 0 minutes or no success is never outdated", () => {
    assert.equal(L.isOutdated(NOW - 16 * 60000, NOW, 15), true);
    assert.equal(L.isOutdated(NOW - 14 * 60000, NOW, 15), false);
    assert.equal(L.isOutdated(NOW - 999 * 60000, NOW, 0), false);
    assert.equal(L.isOutdated(0, NOW, 15), false);
});

test("levelOf: warning and critical thresholds, 0 is off", () => {
    assert.equal(L.levelOf(79, 80, 95), "normal");
    assert.equal(L.levelOf(80, 80, 95), "warning");
    assert.equal(L.levelOf(95, 80, 95), "critical");
    assert.equal(L.levelOf(100, 0, 0), "normal");
});

test("B-04 the level follows the number the card prints, not the raw fraction", () => {
    // 94.6 prints as 95%: it must wear 95's colour; 79.4 prints as 79% and stays normal
    assert.equal(L.displayPercent(94.6), 95);
    assert.equal(L.levelOf(94.6, 80, 95), "critical");
    assert.equal(L.levelOf(94.4, 80, 95), "warning");
    assert.equal(L.levelOf(79.5, 80, 95), "warning");
    assert.equal(L.levelOf(79.4, 80, 95), "normal");
    assert.equal(L.compactText([{ rows: [{ percent: 94.6 }] }]), "95%");
});

test("zoomFor: fit follows the width, fixed follows the percent, both bounded", () => {
    assert.equal(L.zoomFor("fit", 400, 400, 100), 1);
    assert.equal(L.zoomFor("fit", 600, 400, 100), 1.5);
    assert.equal(L.zoomFor("fixed", 600, 400, 125), 1.25);
    assert.equal(L.zoomFor("fit", 10, 400, 100), L.MIN_ZOOM);
    assert.equal(L.zoomFor("fixed", 0, 0, 1000), L.MAX_ZOOM);
    assert.equal(L.zoomFor("fit", 400, 0, 100), 1, "no base width falls back to 100 %");
});

test("shrinkStep: shrinks under the fit, grows back only with room to spare, has a floor", () => {
    assert.equal(L.shrinkStep(1, 200, 400), 0.49, "aims 2 % under the fit");
    assert.equal(L.shrinkStep(0.49, 200, 199), 0.49, "fits: unchanged");
    assert.equal(L.shrinkStep(0.49, 200, 195), 0.49, "under 5 % of room: no growth (hysteresis)");
    assert.equal(L.shrinkStep(0.5, 400, 200), 0.98, "room again: grows toward the fit");
    assert.equal(L.shrinkStep(0.9, 400, 100), 1, "never above 1");
    assert.equal(L.shrinkStep(0.8, 200, 201) < 0.8, true, "any overflow shrinks");
    assert.equal(L.shrinkStep(1, 10, 1000), L.MIN_SHRINK);
    assert.equal(L.shrinkStep(0.7, 0, 100), 0.7, "no size yet: unchanged");
    assert.equal(L.shrinkStep(0.5, 200, 180, 0.52), 0.52, "growth stops at the ceiling");
    assert.equal(L.shrinkStep(0.52, 200, 180, 0.52), 0.52, "at the ceiling: no further growth");
});

test("mergeKnownRows: appends new rows, refreshes labels, and reports no change as null", () => {
    const rows = [{ id: "claude:session", provider: "claude", label: "Session (5hr)" }];
    const first = L.mergeKnownRows("", rows);
    assert.deepEqual(JSON.parse(first), rows);
    assert.equal(L.mergeKnownRows(first, rows), null, "same rows: no config write");
    const renamed = L.mergeKnownRows(first, [{ id: "claude:session", provider: "claude", label: "Session" }]);
    assert.equal(JSON.parse(renamed)[0].label, "Session");
    const added = JSON.parse(L.mergeKnownRows(first, [{ id: "codex:primary", provider: "codex", label: "Weekly" }]));
    assert.deepEqual(added.map(k => k.id), ["claude:session", "codex:primary"], "first-seen order kept");
});

test("parseKnownRows: a damaged value restarts empty", () => {
    for (const bad of ["{", "5", "null", '{"a": 1}', '[1, null, {"id": 3}]']) {
        assert.equal(JSON.stringify(L.parseKnownRows(bad)), "[]", bad);
    }
});

test("levelColor: each level its own colour", () => {
    const colors = { normal: "n", warning: "w", critical: "c" };
    assert.deepEqual(["normal", "warning", "critical", "other"].map(l => L.levelColor(l, colors)), ["n", "w", "c", "n"]);
});

// Rows as the helper sends them, by id; per provider in display order (Claude, then ChatGPT).
const row = id => ({ id: id, label: id.split(":")[1] });
const CLAUDE = ["claude:session", "claude:weekly_all", "claude:weekly_scoped:Fable"].map(row);
const CODEX = ["codex:primary", "codex:secondary"].map(row);
// Values made inside the vm context have its own Array prototype; a JSON round-trip compares the data only.
const plain = x => JSON.parse(JSON.stringify(x));
const shape = arranged => plain(arranged.blocks.map(b => [b.section, b.rows.map(e => e.row.id)]));

test("applyOrder: listed ids first in their order, the rest after in the default order", () => {
    const ids = ["a", "b", "c", "d"];
    assert.deepEqual(plain(L.applyOrder(ids, ["c", "a"], x => x)), ["c", "a", "b", "d"]);
    assert.deepEqual(plain(L.applyOrder(ids, [], x => x)), ids, "no order: unchanged");
    assert.deepEqual(plain(L.applyOrder(ids, ["gone", "d", "d"], x => x)), ["d", "a", "b", "c"], "unknown and repeated ids ignored");
});

test("arrangeRows: no order keeps one section per provider, as before", () => {
    const a = L.arrangeRows([CLAUDE, CODEX], []);
    assert.equal(a.mixed, false);
    assert.deepEqual(shape(a), [[0, CLAUDE.map(r => r.id)], [1, CODEX.map(r => r.id)]]);
});

test("arrangeRows: providers reordered but each kept together stays in sections, ChatGPT first", () => {
    const a = L.arrangeRows([CLAUDE, CODEX], ["codex:secondary", "codex:primary", "claude:weekly_scoped:Fable"]);
    assert.equal(a.mixed, false);
    assert.deepEqual(shape(a), [[1, ["codex:secondary", "codex:primary"]],
                                [0, ["claude:weekly_scoped:Fable", "claude:session", "claude:weekly_all"]]]);
});

test("arrangeRows: both 5-hour rows first mixes the providers into one list", () => {
    const a = L.arrangeRows([CLAUDE, CODEX], ["claude:session", "codex:primary", "claude:weekly_all", "codex:secondary"]);
    assert.equal(a.mixed, true);
    assert.deepEqual(shape(a), [[-1, ["claude:session", "codex:primary", "claude:weekly_all", "codex:secondary",
                                      "claude:weekly_scoped:Fable"]]], "an unlisted row goes to the end");
    assert.deepEqual(plain(a.blocks[0].rows.map(e => e.section)), [0, 1, 0, 1, 0], "each row keeps its provider");
});

test("arrangeRows: a provider with no rows yet keeps its default place", () => {
    assert.deepEqual(shape(L.arrangeRows([[], CODEX], [])), [[0, []], [1, CODEX.map(r => r.id)]],
                     "Claude still loading: its section stays first");
    assert.deepEqual(shape(L.arrangeRows([CLAUDE, []], ["claude:weekly_all"])).map(b => b[0]), [0, 1]);
});

test("arrangeRows: hidden rows are judged out (the card passes only visible rows)", () => {
    // the user's order mixes providers only through a hidden row: what is left stays in sections
    const a = L.arrangeRows([[CLAUDE[0]], CODEX], ["claude:session", "codex:primary", "claude:weekly_all", "codex:secondary"]);
    assert.equal(a.mixed, false);
});

test("rowsByProvider: providers by their first row, rows in the user's order", () => {
    const a = L.arrangeRows([CLAUDE, CODEX], ["codex:primary", "claude:session", "codex:secondary", "claude:weekly_all"]);
    assert.deepEqual(plain(L.rowsByProvider(a).map(g => [g.section, g.rows.map(r => r.id)])),
                     [[1, ["codex:primary", "codex:secondary"]],
                      [0, ["claude:session", "claude:weekly_all", "claude:weekly_scoped:Fable"]]]);
});

test("defaultKnownOrder: Claude's rows, then ChatGPT's, each in first-seen order", () => {
    const known = [{ id: "codex:primary", provider: "codex" }, { id: "claude:session", provider: "claude" },
                   { id: "x:y", provider: "x" }, { id: "claude:weekly_all", provider: "claude" }];
    assert.deepEqual(plain(L.defaultKnownOrder(known).map(k => k.id)),
                     ["claude:session", "claude:weekly_all", "codex:primary", "x:y"]);
});

test("moveId: one place up or down, never off the list", () => {
    assert.deepEqual(plain(L.moveId(["a", "b", "c"], 0, 1)), ["b", "a", "c"]);
    assert.deepEqual(plain(L.moveId(["a", "b", "c"], 2, -1)), ["a", "c", "b"]);
    assert.equal(L.moveId(["a", "b", "c"], 0, -1), null);
    assert.equal(L.moveId(["a", "b", "c"], 2, 1), null);
});

test("preferredSize: the design size until placed, then never more than the size the widget has", () => {
    assert.equal(L.preferredSize(396, 0), 396, "not placed yet: the design size");
    assert.equal(L.preferredSize(396, 400), 396, "a larger slot: the design size, below it");
    assert.equal(L.preferredSize(396, 300), 300, "a slot made narrower: its own size, nothing to grow to");
});

process.exit(failed ? 1 : 0);
