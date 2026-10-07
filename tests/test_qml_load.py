"""Load tests for the plasmoid's QML (main.qml, UsageSource.qml, UsageRow.qml, UsageLogic.js) in an
isolated plasmawindowed.

Each scenario copies the package into a sandbox under the temp dir, swaps the helper for a stub that
answers per provider (or keeps the real helper, which then finds only the sandbox's fake login files),
can change setting defaults in the copy's main.xml, injects a probe Timer into the copy's main.qml, and
runs plasmawindowed offscreen on a private D-Bus, with HOME, every XDG dir, CLAUDE_CONFIG_DIR and
CODEX_HOME inside the sandbox: the real login files are never in reach, and no scenario makes a network
call. The probe logs the widget's state as one JSON line; the run is stopped once it appears.

The Plasma scenarios are skipped, loudly, where plasmawindowed or dbus-run-session is missing; the static
check at the end runs everywhere. Set CU_KEEP_SANDBOX=1 to keep the sandboxes (each has its out.log), and
CU_SHOTS=<dir> to save a PNG of every scenario's card there.
"""
from __future__ import annotations

import json
import os
import queue
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent / "src"
PLUGIN_ID = json.loads((PKG / "metadata.json").read_text(encoding="utf-8"))["KPlugin"]["Id"]
TOOLS = shutil.which("plasmawindowed") and shutil.which("dbus-run-session")
SHOTS = os.environ.get("CU_SHOTS")
# Where the probe is inserted; the test fails loudly if main.qml no longer has exactly one.
ANCHOR = "    function collectSources() {\n"
# A line from the widget's own files that means the QML misbehaved.
QML_ERROR = re.compile(r"TypeError|ReferenceError|error when loading applet|/contents/ui/\w+\.qml:\d+")
# The PATH every scenario runs with: system folders only, so the real Claude Code (in ~/.local/bin) can never
# be started by a test; a scenario that needs a `claude` brings its fake in `bin/` (put first).
SAFE_PATH = "/usr/local/bin:/usr/bin:/bin"
# Long enough for a load plus one helper run on a busy machine; a stuck run gives up here.
DEADLINE_S = 25
# Each run is its own sandbox and bus; four at once keep the whole file near 15 s on an 8-core CPU.
PARALLEL_RUNS = 4
# The window size every scenario is measured at unless it sets its own: the 400 x 256 slot the widget
# was designed for, so the default width is the 100 % zoom.
SLOT = (400, 256)

PROBE = """
    function __labelColors(item, out) {
        if (item.objectName && item.objectName.indexOf("percent:") === 0) {
            out[item.objectName.slice(8)] = String(item.color)
        }
        for (let i = 0; i < item.children.length; i++) {
            __labelColors(item.children[i], out)
        }
        if (item.contentItem && item.contentItem !== item && item.contentItem.parent !== item) {
            __labelColors(item.contentItem, out)
        }
        return out
    }
    function __barColors(item, out) {
        if (item.objectName && item.objectName.indexOf("bar:") === 0 && !item.Kirigami.Theme.inherit) {
            out[item.objectName.slice(4)] = String(item.Kirigami.Theme.highlightColor)
        }
        for (let i = 0; i < item.children.length; i++) {
            __barColors(item.children[i], out)
        }
        if (item.contentItem && item.contentItem !== item && item.contentItem.parent !== item) {
            __barColors(item.contentItem, out)
        }
        return out
    }
    // The colours of the panel form's percentages (its bold labels), in order.
    function __compactColors(item, out) {
        if (item.font !== undefined && item.font.bold && item.text !== undefined && item.visible) {
            out.push(String(item.color))
        }
        for (let i = 0; i < item.children.length; i++) {
            __compactColors(item.children[i], out)
        }
        return out
    }
    // The card's content height, from its scroll area (the preferred height is what the desktop is asked for).
    function __contentHeight(item) {
        if (item.objectName === "scroll") {
            return item.contentHeight
        }
        for (let i = 0; i < item.children.length; i++) {
            const h = __contentHeight(item.children[i])
            if (h >= 0) {
                return h
            }
        }
        return -1
    }
    // How many text items use each render type (0 Qt's default, 1 native, 2 curves), keyed by its number.
    function __renderTypes(item, out) {
        if (item.renderType !== undefined && item.text !== undefined && item.font !== undefined) {
            out[item.renderType] = (out[item.renderType] || 0) + 1
        }
        for (let i = 0; i < item.children.length; i++) {
            __renderTypes(item.children[i], out)
        }
        if (item.contentItem && item.contentItem !== item && item.contentItem.parent !== item) {
            __renderTypes(item.contentItem, out)
        }
        return out
    }
    // The texts of the panel form's visible labels, in order.
    function __compactTexts(item, out) {
        if (item.text !== undefined && item.font !== undefined && item.visible) {
            out.push(item.text)
        }
        for (let i = 0; i < item.children.length; i++) {
            __compactTexts(item.children[i], out)
        }
        return out
    }
    // The texts of the visible labels whose objectName starts with `prefix`, in the order they are shown.
    function __texts(item, prefix, out) {
        if (item.objectName && item.objectName.indexOf(prefix) === 0 && item.visible) {
            out.push(item.text)
        }
        for (let i = 0; i < item.children.length; i++) {
            __texts(item.children[i], prefix, out)
        }
        if (item.contentItem && item.contentItem !== item && item.contentItem.parent !== item) {
            __texts(item.contentItem, prefix, out)
        }
        return out
    }
    function __probeState() {
        const full = root.fullRepresentationItem
        return {
            sources: root.sources.map(s => ({ id: s.providerId, kind: s.errorKind, interval: s.scheduledMs,
                                              busy: s.busy, status: root.sectionStatus(s) })),
            sections: root.sections.map(x => x.source.providerId),
            rows: root.sections.map(x => x.rows.map(r => r.id)),
            title: root.titleText(), footer: root.footerText(), tip: root.toolTipSubText,
            compact: Logic.compactText(Logic.rowsByProvider(root.layout)),
            mixed: root.layout.mixed,
            titles: full ? __texts(full, "title:", []) : [],
            headers: full ? __texts(full, "header", []) : [],
            statuses: full ? __texts(full, "status", []) : [],
            compactWidth: root.compactRepresentationItem ? root.compactRepresentationItem.Layout.minimumWidth : -1,
            resets: [].concat(...root.sections.map(x => x.rows.map(r => root.resetText(r.resets_at, r.group !== "session")))),
            known: Logic.parseKnownRows(Plasmoid.configuration.knownRows).map(k => k.id),
            outdated: root.sections.map(x => root.isOutdated(x.source)),
            zoom: full ? full.zoom : -1, minHeight: full ? full.Layout.minimumHeight : -1,
            gridUnit: Kirigami.Units.gridUnit, width: full ? full.width : -1, height: full ? full.height : -1,
            contentHeight: full ? __contentHeight(full) : -1,
            preferredHeight: full ? full.Layout.preferredHeight : -1,
            fonts: { dp: Kirigami.Theme.defaultFont.pointSize, dpx: Kirigami.Theme.defaultFont.pixelSize,
                     sp: Kirigami.Theme.smallFont.pointSize, spx: Kirigami.Theme.smallFont.pixelSize },
            colors: full ? __labelColors(full, {}) : {},
            barColors: full ? __barColors(full, {}) : {},
            compactColors: root.compactRepresentationItem ? __compactColors(root.compactRepresentationItem, []) : [],
            compactTexts: root.compactRepresentationItem ? __compactTexts(root.compactRepresentationItem, []) : [],
            renderTypes: full ? __renderTypes(full, {}) : {},
            compactRenderTypes: root.compactRepresentationItem ? __renderTypes(root.compactRepresentationItem, {}) : {},
            theme: { text: String(Kirigami.Theme.textColor), neutral: String(Kirigami.Theme.neutralTextColor),
                     negative: String(Kirigami.Theme.negativeTextColor) }
        }
    }
    Timer {
        interval: %(ms)d; running: true
        onTriggered: {
            const win = root.fullRepresentationItem ? root.fullRepresentationItem.Window.window : null
            if (win) {
                win.width = %(width)d
                win.height = %(height)d
            }
            %(advance)s
            %(script)s
            __settle.start()
        }
    }
    // One layout pass after the resize before anything is measured or drawn.
    Timer {
        id: __settle
        interval: 400
        onTriggered: {
            // Always draw a frame first: layouts are measured when a frame is prepared, so only then are the
            // sizes read below current.
            const shot = %(shot)s
            if (!root.fullRepresentationItem) {
                console.log("CU-PROBE " + JSON.stringify(__probeState()))
                return
            }
            root.fullRepresentationItem.grabToImage(function (r) {
                if (shot) {
                    r.saveToFile(shot)
                }
                console.log("CU-PROBE " + JSON.stringify(__probeState()))
            })
        }
    }
"""


def probe_code(spec: dict, name: str) -> str:
    """The QML injected before ANCHOR."""
    advance = f"root.nowMs = Date.now() + {spec['advance_ms']}" if spec.get("advance_ms") else ""
    shot = json.dumps(str(Path(SHOTS) / f"{name}.png")) if SHOTS else "null"
    width, height = spec.get("size", SLOT)
    return PROBE % {"ms": spec.get("probe_ms", 2500), "advance": advance, "shot": shot, "width": width, "height": height,
                    "script": spec.get("script", "")}


NOLOGIN = "json.dumps({'ok': False, 'error': 'nologin', 'message': 'not found'})"


def stub(claude: str, codex: str = NOLOGIN, sleep_s: float = 0) -> str:
    """A helper printing the Python expression for the provider it is asked about (``now`` is UTC now)."""
    return ("#!/usr/bin/env python3\nimport json, sys, time\nfrom datetime import datetime, timedelta, timezone\n"
            "provider = sys.argv[sys.argv.index('--provider') + 1] if '--provider' in sys.argv else 'claude'\n"
            f"time.sleep({sleep_s})\nnow = datetime.now(timezone.utc)\n"
            f"print({claude} if provider == 'claude' else {codex})\n")


def ok_rows(provider: str, rows: list[tuple]) -> str:
    """A stub answer with ``rows`` = [(row_id, label, group, percent, reset_offset_minutes or None)]."""
    items = ", ".join(
        f"{{'id': '{provider}:{rid}', 'provider': '{provider}', 'kind': '{rid}', 'group': '{group}', 'label': '{label}', "
        f"'percent': {pct}, 'resets_at': {'None' if off is None else f'(now + timedelta(minutes={off})).isoformat()'}}}"
        for rid, label, group, pct, off in rows)
    return f"json.dumps({{'ok': True, 'status': 200, 'provider': '{provider}', 'rows': [{items}]}})"


CLAUDE_OK = ok_rows("claude", [("session", "Session (5hr)", "session", 12.5, -120),
                               ("weekly_all", "Weekly (7 day)", "weekly", 40.0, 2 * 1440 + 1),
                               ("weekly_scoped:Fable", "Weekly (Fable)", "weekly", 7.0, None)])
CODEX_OK = ok_rows("codex", [("primary", "Session (5hr)", "session", 12.0, 61),
                             ("secondary", "Monthly (30 day)", "weekly", 30.0, 20 * 1440)])
CLAUDE_HOT = ok_rows("claude", [("session", "Session (5hr)", "session", 85.0, 30),
                                ("weekly_all", "Weekly (7 day)", "weekly", 97.0, 1440)])

# A status file as statusline_tap.py writes it, its numbers seen 20 minutes ago (older than the 15-minute
# "outdated" default), the session window resetting in an hour.
SEEN_S = int(time.time()) - 20 * 60
STATUS_FILE = json.dumps({"captured_at": SEEN_S, "rate_limits": {
    "five_hour": {"used_percentage": 31, "resets_at": SEEN_S + 80 * 60},
    "seven_day": {"used_percentage": 52, "resets_at": SEEN_S + 3 * 86400}}})
CLAUDE_LOGIN = {"home/.claude/.credentials.json": "{}"}
# A fake Claude Code answering the usage request (test_claudecode.py's, with the live 2026-10-07 shape).
import test_claudecode  # noqa: E402  (beside this file)

# name -> stub (None = the real helper) and optional knobs: defaults (main.xml), locale, files, ...
SCENARIOS: dict[str, dict] = {
    # the real helper through a path that needs quoting, with the default source (a fake claude in the sandbox's bin/)
    "real-helper-quoted-path": dict(stub=None, subdir="it's a #dir", files=CLAUDE_LOGIN,
                                    executables={"bin/claude": test_claudecode.FAKE},
                                    env={"FAKE_CLAUDE_ANSWER": json.dumps(test_claudecode.ANSWER)}, record="record.jsonl"),
    # the status-line source: Claude Code logged in, nothing passed to its status line yet
    "real-helper-statusline-waiting": dict(stub=None, files=CLAUDE_LOGIN, defaults={"claudeSource": "statusline"}),
    # ...and with numbers Claude Code saw 20 minutes ago (the login file is only checked for existence)
    "real-helper-statusline": dict(stub=None, locale="en_US.UTF-8", defaults={"claudeSource": "statusline"}, files=dict(
        CLAUDE_LOGIN, **{"cache/ai-session-usage/claude-statusline.json": STATUS_FILE})),
    # the default source: Claude Code asked for its usage (a fake claude in the sandbox's bin/)
    # (this one alone lets Python write bytecode, so that the card's -B is what keeps __pycache__ away)
    "real-helper-claudecode": dict(stub=None, files=CLAUDE_LOGIN, executables={"bin/claude": test_claudecode.FAKE},
                                   env={"FAKE_CLAUDE_ANSWER": json.dumps(test_claudecode.ANSWER),
                                        "PYTHONDONTWRITEBYTECODE": ""}, record="record.jsonl"),
    "real-helper-no-login": dict(stub=None),
    "unreadable": dict(stub=stub("json.dumps({'ok': False, 'error': 'unreadable', 'message': '/x/c.json: JSONDecodeError'})")),
    # a request's failures, with the default source (Claude Code asked; the status-line source makes no request)
    "ratelimited-600": dict(stub=stub("json.dumps({'ok': False, 'error': 'ratelimited', 'status': 429, 'retry_after': 600})")),
    "ratelimited-120": dict(stub=stub("json.dumps({'ok': False, 'error': 'ratelimited', 'status': 429, 'retry_after': 120})")),
    "network": dict(stub=stub("json.dumps({'ok': False, 'error': 'network', 'message': 'name resolution failed'})")),
    "both-providers-en": dict(stub=stub(CLAUDE_OK, CODEX_OK), locale="en_US.UTF-8"),
    "claude-only-tr": dict(stub=stub(CLAUDE_OK), locale="tr_TR.UTF-8"),
    "hidden-row": dict(stub=stub(CLAUDE_OK, CODEX_OK), defaults={"hiddenRows": "claude:weekly_scoped:Fable"}),
    "codex-off": dict(stub=stub(CLAUDE_OK, CODEX_OK), defaults={"showCodex": "false"}),
    "outdated": dict(stub=stub(CLAUDE_OK), advance_ms=20 * 60000),
    "levels": dict(stub=stub(CLAUDE_HOT)),
    "levels-own-colours": dict(stub=stub(CLAUDE_HOT, CODEX_OK),
                               defaults={"warnColor": "#123456", "criticalColor": "#abcdef"}),
    "sections-reordered": dict(stub=stub(CLAUDE_OK, CODEX_OK), size=(400, 420),
                               defaults={"rowOrder": "codex:secondary,codex:primary"}),
    "mixed-order": dict(stub=stub(CLAUDE_OK, CODEX_OK), size=(400, 420),
                        defaults={"rowOrder": "claude:session,codex:primary,claude:weekly_all,codex:secondary"}),
    # ChatGPT's next fetch fails after a good one: its rows stay (dimmed) and its line follows the mixed list
    "mixed-order-error": dict(stub=stub(CLAUDE_OK, CODEX_OK), size=(400, 420),
                              defaults={"rowOrder": "claude:session,codex:primary,claude:weekly_all,codex:secondary"},
                              script="root.sources[1].handleOutput(JSON.stringify({ ok: false, error: 'network', "
                                     "message: 'no route' }), '')"),
    "compact-reordered": dict(stub=stub(CLAUDE_OK, CODEX_OK), force_compact=True,
                              defaults={"rowOrder": "codex:secondary,codex:primary,claude:weekly_all"}),
    "compact-own-colours": dict(stub=stub(CLAUDE_HOT, CODEX_OK), force_compact=True,
                                defaults={"warnColor": "#123456", "criticalColor": "#abcdef"}),
    "grow": dict(stub=stub(CLAUDE_OK, CODEX_OK), defaults={"overflowMode": "grow"}),
    "wide": dict(stub=stub(CLAUDE_OK, CODEX_OK), size=(800, 256)),
    "fixed-zoom": dict(stub=stub(CLAUDE_OK, CODEX_OK), size=(800, 256),
                       defaults={"sizeMode": "fixed", "zoomPercent": "150"}),
    "shrink": dict(stub=stub(CLAUDE_OK, CODEX_OK), size=(400, 200), defaults={"overflowMode": "shrink"}),
    "watchdog": dict(stub=stub("'{}'", "'{}'", sleep_s=30), watchdog_ms=1500, probe_ms=4000),
    "null-output": dict(stub=stub("'null'")),
    "ok-without-rows": dict(stub=stub("json.dumps({'ok': True})")),
    "compact": dict(stub=stub(CLAUDE_OK, CODEX_OK), force_compact=True),
    "control-broken-qml": dict(stub=None, break_qml=True),
}


def _replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise AssertionError(f"{path.name}: expected exactly one {old!r}")
    path.write_text(text.replace(old, new), encoding="utf-8")


def _set_default(main_xml: Path, entry: str, value: str) -> None:
    """Change one setting's default in the sandbox copy's main.xml (the widget then starts with it)."""
    text = main_xml.read_text(encoding="utf-8")
    pattern = re.compile(r'(<entry name="%s"[^>]*>.*?<default>)[^<]*(</default>)' % re.escape(entry), re.S)
    new, n = pattern.subn(lambda m: m.group(1) + value + m.group(2), text)
    if n != 1:
        raise AssertionError(f"main.xml: no single entry {entry!r}")
    main_xml.write_text(new, encoding="utf-8")


def run_scenario(base: Path, name: str, spec: dict) -> dict:
    """Run one scenario; returns ``{"probe": dict | None, "errors": [lines], "log": Path}``."""
    sandbox = base / spec.get("subdir", "") / name
    for sub in ("config", "cache", "state", "data/plasma/plasmoids", "home/.codex"):
        (sandbox / sub).mkdir(parents=True)
    (sandbox / "run").mkdir(mode=0o700)
    (sandbox / "home").chmod(0o700)
    for rel, content in spec.get("files", {}).items():
        (sandbox / rel).parent.mkdir(parents=True, exist_ok=True)
        (sandbox / rel).write_text(content, encoding="utf-8")
    for rel, content in spec.get("executables", {}).items():
        (sandbox / rel).parent.mkdir(parents=True, exist_ok=True)
        (sandbox / rel).write_text(content, encoding="utf-8")
        (sandbox / rel).chmod(0o755)
    pkg = sandbox / "data/plasma/plasmoids" / PLUGIN_ID
    shutil.copytree(PKG, pkg, ignore=shutil.ignore_patterns("__pycache__"))
    ui = pkg / "contents/ui"
    _replace_once(ui / "main.qml", ANCHOR, probe_code(spec, name) + ANCHOR)
    for entry, value in spec.get("defaults", {}).items():
        _set_default(pkg / "contents/config/main.xml", entry, value)
    if spec.get("watchdog_ms"):
        _replace_once(ui / "UsageLogic.js", "var WATCHDOG_MS = 60000", f"var WATCHDOG_MS = {spec['watchdog_ms']}")
    if spec.get("force_compact"):
        _replace_once(ui / "main.qml", "? fullRepresentation : null", "? compactRepresentation : null")
    if spec.get("break_qml"):
        _replace_once(ui / "UsageRow.qml", "    opacity: stale ? 0.55 : 1\n", "    opacity: stale ? 0.55 : 1 }\n")
    if spec["stub"] is not None:
        (pkg / "contents/code/fetch_usage.py").write_text(spec["stub"], encoding="utf-8")

    env = {k: v for k, v in os.environ.items()
           if k not in ("DBUS_SESSION_BUS_ADDRESS", "DISPLAY", "WAYLAND_DISPLAY") and not k.startswith("LC_")}
    env.update(HOME=str(sandbox / "home"), CLAUDE_CONFIG_DIR=str(sandbox / "home/.claude"),
               CODEX_HOME=str(sandbox / "home/.codex"),
               XDG_RUNTIME_DIR=str(sandbox / "run"), XDG_DATA_HOME=str(sandbox / "data"),
               XDG_CONFIG_HOME=str(sandbox / "config"), XDG_CACHE_HOME=str(sandbox / "cache"),
               XDG_STATE_HOME=str(sandbox / "state"), QT_QPA_PLATFORM="offscreen", QT_QPA_PLATFORMTHEME="kde", QT_QUICK_BACKEND="software",
               QT_FORCE_STDERR_LOGGING="1", QML_DISABLE_DISK_CACHE="1", PYTHONDONTWRITEBYTECODE="1",
               LANG=spec.get("locale", "en_GB.UTF-8"), PATH=f"{sandbox / 'bin'}:{SAFE_PATH}")
    env.update(spec.get("env", {}))
    if "record" in spec:
        env["FAKE_CLAUDE_RECORD"] = str(sandbox / spec["record"])
    if "locale" in spec:
        env["LC_ALL"] = spec["locale"]

    proc = subprocess.Popen(["dbus-run-session", "--", "plasmawindowed", PLUGIN_ID], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
    lines: queue.Queue[str] = queue.Queue()

    def pump() -> None:
        for raw in proc.stdout:
            lines.put(raw.decode("utf-8", "replace").rstrip("\n"))

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()
    seen: list[str] = []
    found = None
    deadline = time.monotonic() + DEADLINE_S
    try:
        while found is None and time.monotonic() < deadline:
            try:
                line = lines.get(timeout=0.2)
            except queue.Empty:
                continue
            seen.append(line)
            match = re.search(r"CU-PROBE (\{.*\})", line)
            if match:
                found = json.loads(match.group(1))
            elif "error when loading applet" in line:
                break
    finally:
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=10)
        reader.join(timeout=10)  # EOF once the process group is gone
        proc.stdout.close()
    log = sandbox / "out.log"
    log.write_text("\n".join(seen), encoding="utf-8")
    return {"probe": found, "errors": [line for line in seen if QML_ERROR.search(line)], "log": log}


@unittest.skipUnless(TOOLS, "SKIPPED: plasmawindowed or dbus-run-session not found, the QML was not loaded")
class TestQmlLoad(unittest.TestCase):
    """Every scenario runs once, in parallel, in setUpClass; each test reads its result."""

    results: dict[str, dict] = {}

    @classmethod
    def setUpClass(cls) -> None:
        cls.base = Path(tempfile.mkdtemp(prefix="cu-qml-"))
        if not os.environ.get("CU_KEEP_SANDBOX"):
            cls.addClassCleanup(shutil.rmtree, cls.base, ignore_errors=True)  # also when a run below raises
        if SHOTS:
            Path(SHOTS).mkdir(parents=True, exist_ok=True)
        with ThreadPoolExecutor(PARALLEL_RUNS) as pool:
            futures = {name: pool.submit(run_scenario, cls.base, name, spec) for name, spec in SCENARIOS.items()}
            cls.results = {name: future.result() for name, future in futures.items()}

    def probe(self, name: str) -> dict:
        """The scenario's probe, after asserting it loaded with no QML error."""
        result = self.results[name]
        self.assertEqual(result["errors"], [], f"QML errors in {name}; log: {result['log']}")
        self.assertIsNotNone(result["probe"], f"no probe line in {name}; log: {result['log']}")
        return result["probe"]

    def source(self, probe: dict, provider: str) -> dict:
        return next(s for s in probe["sources"] if s["id"] == provider)

    def test_control_a_broken_copy_reports_an_error(self) -> None:
        # proves the harness can see a load failure at all (without a private bus it prints nothing)
        result = self.results["control-broken-qml"]
        self.assertIsNone(result["probe"])
        self.assertTrue(any("error when loading applet" in e for e in result["errors"]), result["log"])

    def test_real_helper_through_a_quoted_path(self) -> None:
        # the real helper, its path quoted for the shell, asks the fake Claude Code and finds no Codex login
        p = self.probe("real-helper-quoted-path")
        self.assertEqual(p["sections"], ["claude"], "no Codex login: no ChatGPT section")
        self.assertEqual(p["rows"], [["claude:session", "claude:weekly_all", "claude:weekly_scoped:Fable"]])
        self.assertEqual(p["title"], "Claude usage")

    def test_claude_code_asked_brings_the_per_model_cap(self) -> None:
        # the card passes --source claudecode (the default); the real helper asks the fake Claude Code
        p = self.probe("real-helper-claudecode")
        self.assertEqual(p["rows"], [["claude:session", "claude:weekly_all", "claude:weekly_scoped:Fable"]])
        self.assertEqual(self.source(p, "claude")["interval"], 300000, "a request: the user's interval, not 30 s")

    def test_the_helper_leaves_no_bytecode_beside_itself(self) -> None:
        # the card runs the helper with python3 -B: a __pycache__ beside it would hold this machine's paths and
        # ship with src/**. Only this scenario lets Python write bytecode (PYTHONDONTWRITEBYTECODE unset).
        self.probe("real-helper-claudecode")
        pkg = self.results["real-helper-claudecode"]["log"].parent / "data/plasma/plasmoids" / PLUGIN_ID
        self.assertFalse((pkg / "contents/code/__pycache__").exists(), "the helper wrote bytecode beside itself")

    def test_status_line_source_waiting_for_claude_code(self) -> None:
        p = self.probe("real-helper-statusline-waiting")
        self.assertEqual(p["sections"], ["claude"])
        self.assertEqual(self.source(p, "claude")["status"],
                         "No numbers from Claude Code's status line yet: set it up in the settings (General), "
                         "then send Claude Code a message")

    def test_status_line_numbers_show_when_they_were_seen(self) -> None:
        # the real helper, given --source statusline by the card, reads the status file (without the flag it
        # would read the login file, which holds no token here)
        p = self.probe("real-helper-statusline")
        self.assertEqual(p["rows"], [["claude:session", "claude:weekly_all"]])
        seen = time.strftime("%-I:%M", time.localtime(SEEN_S))
        self.assertRegex(p["footer"], rf"^Updated {seen}\s?[AP]M · click to refresh$", "the time Claude Code saw them")
        self.assertEqual(p["outdated"], [True], "20 minutes old: past the 15-minute default")
        self.assertEqual(self.source(p, "claude")["interval"], 30000, "a local file is read every 30 s")

    def test_no_login_anywhere_says_so(self) -> None:
        p = self.probe("real-helper-no-login")
        self.assertEqual(p["sections"], [])
        self.assertEqual(p["footer"], "No Claude Code or Codex login found")
        self.assertEqual(p["title"], "AI session usage")

    def test_unreadable_shows_the_helper_message(self) -> None:
        self.assertEqual(self.source(self.probe("unreadable"), "claude")["status"],
                         "Cannot use the login file: /x/c.json: JSONDecodeError")

    def test_rate_limit_text_matches_the_schedule(self) -> None:
        s = self.source(self.probe("ratelimited-600"), "claude")
        self.assertEqual((s["status"], s["interval"]), ("Rate limited; will retry in 10 min", 600000))
        # a Retry-After shorter than the poll interval waits the interval, and says so
        s = self.source(self.probe("ratelimited-120"), "claude")
        self.assertEqual((s["status"], s["interval"]), ("Rate limited; will retry in 5 min", 300000))

    def test_network_failure_retries_after_30_s(self) -> None:
        s = self.source(self.probe("network"), "claude")
        self.assertEqual((s["status"], s["interval"]), ("Offline: name resolution failed", 30000))

    def test_both_providers_in_one_card_en_us(self) -> None:
        p = self.probe("both-providers-en")
        self.assertEqual(p["sections"], ["claude", "codex"])
        self.assertEqual(p["title"], "AI session usage")
        self.assertEqual(p["rows"], [["claude:session", "claude:weekly_all", "claude:weekly_scoped:Fable"],
                                     ["codex:primary", "codex:secondary"]])
        self.assertRegex(p["footer"], r"^Updated \d{1,2}:\d{2}\s?[AP]M · click to refresh$")
        self.assertEqual(p["tip"], "Claude Session (5hr) 13% · Claude Weekly (7 day) 40% · Claude Weekly (Fable) 7% · "
                                   "ChatGPT Session (5hr) 12% · ChatGPT Monthly (30 day) 30%")
        self.assertEqual(p["compact"], "13% · 40% | 12% · 30%")
        self.assertRegex(p["resets"][0], r"^Reset at \d{1,2}:\d{2}\s?[AP]M$", "a passed reset (12-hour locale)")
        self.assertRegex(p["resets"][1], r"^Resets in 2d 0h · [A-Z][a-z]{2} \d{1,2}:\d{2}\s?[AP]M$", "weekday within a week")
        self.assertEqual(p["resets"][2], "")
        self.assertRegex(p["resets"][4], r"^Resets in 20d 0h · \d{1,2}/\d{1,2}/\d{2,4} \d{1,2}:\d{2}\s?[AP]M$", "a date beyond")
        # first-seen order depends on which helper answers first; the settings page sorts by service itself
        self.assertEqual(sorted(p["known"]), ["claude:session", "claude:weekly_all", "claude:weekly_scoped:Fable",
                                              "codex:primary", "codex:secondary"], "rows recorded for the settings page")
        self.assertAlmostEqual(p["zoom"], 400 / (18 * 22), places=2, msg="the 400 px slot is about 100 %")

    def test_turkish_locale_is_24_hour(self) -> None:
        p = self.probe("claude-only-tr")
        self.assertEqual(p["title"], "Claude usage")
        self.assertRegex(p["footer"], r"^Updated \d{2}:\d{2} · click to refresh$")
        self.assertRegex(p["resets"][0], r"^Reset at \d{2}:\d{2}$")
        self.assertRegex(p["resets"][1], r"^Resets in 2d 0h · \S+ \d{2}:\d{2}$")

    def test_a_hidden_row_is_left_out_everywhere(self) -> None:
        p = self.probe("hidden-row")
        self.assertEqual(p["rows"][0], ["claude:session", "claude:weekly_all"])
        self.assertNotIn("Fable", p["tip"])
        self.assertIn("claude:weekly_scoped:Fable", p["known"], "still offered in the settings")

    def test_a_provider_turned_off_is_not_asked(self) -> None:
        p = self.probe("codex-off")
        self.assertEqual([s["id"] for s in p["sources"]], ["claude"])
        self.assertEqual(p["title"], "Claude usage")

    def test_outdated_numbers_take_the_outdated_colour(self) -> None:
        p = self.probe("outdated")
        self.assertEqual(p["outdated"], [True])
        self.assertEqual(set(p["colors"].values()), {"#fdbc4b"}, p["colors"])

    def test_warning_and_critical_colours(self) -> None:
        # the defaults: orange from 80 %, red from 95 % (outdated numbers are yellow, so all three differ)
        p = self.probe("levels")
        self.assertEqual(p["colors"], {"claude:session": "#f67400", "claude:weekly_all": "#da4453"})
        self.assertEqual(p["outdated"], [False])

    def test_the_users_own_level_colours(self) -> None:
        # the rows, their bars and the panel form take the colours set in Appearance
        p = self.probe("levels-own-colours")
        self.assertEqual(p["colors"], {"claude:session": "#123456", "claude:weekly_all": "#abcdef",
                                       "codex:primary": p["theme"]["text"], "codex:secondary": p["theme"]["text"]})
        self.assertEqual(p["barColors"], {"claude:session": "#123456", "claude:weekly_all": "#abcdef"})
        compact = self.probe("compact-own-colours")["compactColors"]
        self.assertEqual(compact[:2], ["#123456", "#abcdef"], "the panel form uses the same colours")
        self.assertEqual(len(compact), 4, compact)

    def test_every_text_is_drawn_natively(self) -> None:
        # D10: Qt's default text rendering made text growing with the width look stretched; every label of the
        # card and the panel form draws its font at its own size
        card = self.probe("both-providers-en")["renderTypes"]
        self.assertEqual(set(card), {"1"}, card)
        self.assertGreaterEqual(card["1"], 12, "title, two headers, five rows' three labels, footer")
        panel = self.probe("compact")["compactRenderTypes"]
        self.assertEqual(set(panel), {"1"}, panel)

    def test_no_order_keeps_the_services_in_sections(self) -> None:
        p = self.probe("both-providers-en")
        self.assertEqual((p["mixed"], p["headers"]), (False, ["Claude", "ChatGPT"]))
        self.assertEqual(p["titles"], ["Session (5hr)", "Weekly (7 day)", "Weekly (Fable)", "Session (5hr)",
                                       "Monthly (30 day)"])

    def test_services_reordered_but_kept_together_stay_in_sections(self) -> None:
        p = self.probe("sections-reordered")
        self.assertEqual((p["mixed"], p["headers"]), (False, ["ChatGPT", "Claude"]))
        self.assertEqual(p["titles"], ["Monthly (30 day)", "Session (5hr)", "Session (5hr)", "Weekly (7 day)",
                                       "Weekly (Fable)"])
        self.assertEqual(p["tip"], "ChatGPT Monthly (30 day) 30% · ChatGPT Session (5hr) 12% · Claude Session (5hr) 13% · "
                                   "Claude Weekly (7 day) 40% · Claude Weekly (Fable) 7%")

    def test_a_mixed_order_is_one_list_naming_the_service_in_each_row(self) -> None:
        p = self.probe("mixed-order")
        self.assertEqual((p["mixed"], p["headers"], p["statuses"]), (True, [], []))
        self.assertEqual(p["titles"], ["Claude · Session (5hr)", "ChatGPT · Session (5hr)", "Claude · Weekly (7 day)",
                                       "ChatGPT · Monthly (30 day)", "Claude · Weekly (Fable)"],
                         "the unlisted Fable row goes to the end")
        self.assertEqual(p["tip"], "Claude Session (5hr) 13% · ChatGPT Session (5hr) 12% · Claude Weekly (7 day) 40% · "
                                   "ChatGPT Monthly (30 day) 30% · Claude Weekly (Fable) 7%")
        self.assertEqual(p["compact"], "13% · 40% | 12% · 30%", "the panel form: two per service, in the user's order")

    def test_a_mixed_list_keeps_a_failing_services_line_under_it(self) -> None:
        p = self.probe("mixed-order-error")
        self.assertEqual(p["mixed"], True)
        self.assertEqual(len(p["titles"]), 5, "the failing service's rows stay, dimmed")
        self.assertEqual(len(p["statuses"]), 1, p["statuses"])
        self.assertRegex(p["statuses"][0], r"^ChatGPT: Offline: no route · last good \d{1,2}:\d{2}")

    def test_the_panel_form_follows_the_order(self) -> None:
        texts = self.probe("compact-reordered")["compactTexts"]
        self.assertEqual(texts, ["30%", "·", "12%", "|", "40%", "·", "13%"])

    def test_grow_asks_for_the_whole_height(self) -> None:
        grow, scroll = self.probe("grow"), self.probe("both-providers-en")
        self.assertAlmostEqual(grow["minHeight"], grow["contentHeight"], delta=1)
        self.assertGreater(grow["contentHeight"], grow["height"], "five rows do not fit 256 px: Plasma must grow it")
        self.assertLess(scroll["minHeight"], scroll["contentHeight"], "scroll mode asks for little")

    def test_fit_to_width_zooms_with_the_width(self) -> None:
        self.assertAlmostEqual(self.probe("wide")["zoom"], 800 / (18 * 22), places=2)

    def test_fixed_zoom_ignores_the_width(self) -> None:
        self.assertAlmostEqual(self.probe("fixed-zoom")["zoom"], 1.5, places=2)

    def test_shrink_to_fit_makes_everything_fit(self) -> None:
        p = self.probe("shrink")
        self.assertLess(p["zoom"], 1)
        self.assertLessEqual(p["contentHeight"], p["height"] + 1, (p["contentHeight"], p["height"]))

    def test_watchdog_reports_a_hung_helper(self) -> None:
        s = self.source(self.probe("watchdog"), "claude")
        self.assertEqual((s["kind"], s["status"], s["busy"]), ("timeout", "No answer from the helper; will retry", False))

    def test_non_contract_output_is_an_error_not_a_healthy_status(self) -> None:
        s = self.source(self.probe("null-output"), "claude")
        self.assertEqual((s["kind"], s["status"]), ("badoutput", "Error: badoutput null"))
        self.assertEqual(self.source(self.probe("ok-without-rows"), "claude")["kind"], "badoutput")

    def test_compact_representation_has_a_width_and_both_providers(self) -> None:
        # a panel sizes the applet from these hints; plasmawindowed only shows it when forced
        p = self.probe("compact")
        self.assertGreater(p["compactWidth"], 0)
        self.assertEqual(p["compact"], "13% · 40% | 12% · 30%")


class TestStatic(unittest.TestCase):
    def test_no_em_or_en_dash_in_the_package_or_the_tests(self) -> None:
        # the publish gate refuses an em dash (W10), and an en dash is not an allowed substitute;
        # both folders are publish candidates
        files = [path for root in (PKG, HERE) for path in sorted(root.rglob("*"))
                 if path.is_file() and "__pycache__" not in path.parts]
        hits = [f"{path.relative_to(HERE.parent)}:{n}" for path in files
                for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
                if "\u2014" in line or "\u2013" in line]
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main(verbosity=1)
