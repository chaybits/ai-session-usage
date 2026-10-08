"""The settings pages (configGeneral.qml, configRows.qml, configAppearance.qml) in a real Qt Quick window.

Plasma's settings dialog creates a page with one ``cfg_<key>`` property per setting and saves what the page
leaves in them; nothing else connects the two. Each scenario does the same in Qt's own ``qml`` runtime: a
small harness window loads one page file from the package with the scenario's settings, provides the
``i18n`` functions plasmashell gives every page (English, with the %1 filled in), drives the page with real
mouse events from Qt's test module (QtTest's TestEvent, the path a mouse click travels), and logs what the
page then holds as one JSON line, with a picture of the page when CU_SHOTS=<dir> is set.

The page is the real file in the real style (KDE's desktop style, as the dialog uses); the frame around it
is not Plasma's dialog. The colour dialog itself is Qt's: a scenario calls the colour button's ``accepted``
signal as the dialog does, rather than clicking inside a modal window. Skipped, loudly, without the qml
runtime or the KDE modules. About 10 s.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
UI = HERE.parent / "src/contents/ui"


def qt_path(name: str) -> Path | None:
    """One of Qt 6's install paths (QT_INSTALL_QML, QT_INSTALL_BINS), asked of whichever Qt tool is installed;
    distributions put Qt in different places (/usr/lib/qt6 on Arch, /usr/lib/<triplet>/qt6 on Debian)."""
    for tool in (["qtpaths6", "--query"], ["qtpaths", "--query"], ["qmake6", "-query"], ["qmake", "-query"]):
        if shutil.which(tool[0]):
            try:
                answer = subprocess.run(tool + [name], capture_output=True, text=True, timeout=10).stdout.strip()
            except subprocess.TimeoutExpired:
                continue
            if answer and Path(answer).is_dir():
                return Path(answer)
    return None


QT_QML, QT_BINS = qt_path("QT_INSTALL_QML"), qt_path("QT_INSTALL_BINS")
QML = shutil.which("qml6") or (str(QT_BINS / "qml") if QT_BINS and (QT_BINS / "qml").exists() else None)
KDE_MODULES = bool(QT_QML and (QT_QML / "org/kde/kcmutils").is_dir())
SHOTS = os.environ.get("CU_SHOTS")
DEADLINE_S = 30
PARALLEL_RUNS = 4
# A line that means a page misbehaved: a script error, or a warning from one of the package's own files.
PAGE_ERROR = re.compile(r"TypeError|ReferenceError|SyntaxError|Cannot assign|is not a type|/contents/ui/\w+\.qml:\d+")

HARNESS = """import QtQuick
import QtQuick.Controls
import QtTest

ApplicationWindow {
    id: harness
    width: 640
    height: %(height)d
    visible: true

    // What plasmashell's localized context gives every page: here English, with %%1, %%2 ... filled in.
    function __fill(text, args) {
        return String(text).replace(/%%(\\d+)/g, (all, n) => args[n - 1] !== undefined ? String(args[n - 1]) : all)
    }
    function i18n(text, ...args) { return __fill(text, args) }
    function i18nc(context, text, ...args) { return __fill(text, args) }
    function i18np(singular, plural, n, ...args) { return __fill(n === 1 ? singular : plural, [n, ...args]) }

    TestEvent { id: ev }

    // Every item under `item` (children, and what a Flickable or a control holds) for which `test` is true.
    function findAll(item, test, out) {
        if (!item) {
            return out
        }
        if (test(item)) {
            out.push(item)
        }
        for (let i = 0; i < item.children.length; i++) {
            findAll(item.children[i], test, out)
        }
        if (item.contentItem && item.contentItem !== item && item.contentItem.parent !== item) {
            findAll(item.contentItem, test, out)
        }
        return out
    }
    function find(item, test) {
        return findAll(item, test, [])[0] || null
    }
    function click(item) {
        ev.mouseClick(item, item.width / 2, item.height / 2, Qt.LeftButton, Qt.NoModifier, -1)
    }
    function buttons(text) {
        return findAll(page.item, i => i.text === text && i.clicked !== undefined && i.visible, [])
    }

    Loader {
        id: page
        anchors.fill: parent
    }
    Component.onCompleted: page.setSource(%(page)s, %(props)s)

    // The scenario's steps, one per tick, each returning the function that reads its result on the next.
    property var results: ({})
    property var steps: [%(steps)s]
    Timer {
        interval: 300
        repeat: true
        running: true
        property int step: -1
        property var pending: null
        onTriggered: {
            if (step < 0) {
                if (page.status !== Loader.Ready || page.item.width <= 0) {
                    return
                }
                step = 0
                return
            }
            if (pending) {
                const read = pending
                pending = null
                read()
                return
            }
            if (step < harness.steps.length) {
                pending = harness.steps[step++](harness.results) || null
                return
            }
            running = false
            const shot = %(shot)s
            page.item.grabToImage(r => {
                if (shot) {
                    r.saveToFile(shot)
                }
                console.log("CU-PAGE " + JSON.stringify(harness.results))
                Qt.quit()
            })
        }
    }
}
"""

# Read what a page holds: every cfg_ property the scenario names.
READ_CFG = """results => {
        for (const key of %s) {
            results[key] = page.item["cfg_" + key]
        }
    }"""


def read_cfg(*keys: str) -> str:
    """A step recording the page's cfg_ values of ``keys`` (as Plasma would save them)."""
    return READ_CFG % json.dumps(list(keys))


# The steps of the Appearance scenario: the three colours shown, and a new warning colour stored.
APPEARANCE_STEPS = [
    """results => {
        const colourButtons = harness.findAll(page.item, i => i.showAlphaChannel !== undefined, [])
        results.colourButtonTitles = colourButtons.map(b => b.dialogTitle)
        results.shownAtStart = colourButtons.map(b => String(b.color))
        // what the colour dialog does when the user picks a colour and presses OK: it sets the button's colour
        colourButtons[1].color = "#ff0000"
        return () => {
            results.warnAfterPick = String(page.item.cfg_warnColor)
            results.criticalAfterPick = String(page.item.cfg_criticalColor)
        }
    }""",
]

# The steps of the Rows scenario: a row hidden, moved with the arrows into a mixed order, and the order reset.
ROWS_STEPS = [
    """results => {
        results.orderAtStart = harness.findAll(page.item, i => i.checkState !== undefined, []).map(c => c.text)
        const fable = harness.find(page.item, i => i.text === "Claude · Weekly (Fable)" && i.checkState !== undefined)
        harness.click(fable)
        return () => { results.hiddenAfterUntick = page.item.cfg_hiddenRows }
    }""",
    """results => {
        results.firstUpEnabled = harness.find(page.item, i => i.objectName === "up:claude:session").enabled
        results.lastDownEnabled = harness.find(page.item, i => i.objectName === "down:codex:secondary").enabled
        harness.click(harness.find(page.item, i => i.objectName === "up:codex:primary"))
        return () => { results.orderAfterOneUp = page.item.cfg_rowOrder }
    }""",
    """results => {
        harness.click(harness.find(page.item, i => i.objectName === "up:codex:primary"))
        return () => {
            results.orderAfterTwoUps = page.item.cfg_rowOrder
            results.defaultButtons = harness.buttons("Default order").length
        }
    }""",
    """results => {
        harness.click(harness.buttons("Default order")[0])
        return () => {
            results.orderAfterReset = page.item.cfg_rowOrder
            results.defaultButtonsAfterReset = harness.buttons("Default order").length
        }
    }""",
    # Leave a mixed order on the page for the picture: both 5-hour rows first.
    """results => {
        harness.click(harness.find(page.item, i => i.objectName === "up:codex:primary"))
        return () => {}
    }""",
    """results => {
        harness.click(harness.find(page.item, i => i.objectName === "up:codex:primary"))
        return () => {}
    }""",
    """results => {
        harness.click(harness.find(page.item, i => i.objectName === "down:claude:session"))
        return () => {
            results.orderShown = harness.findAll(page.item, i => i.checkState !== undefined, []).map(c => c.text)
        }
    }""",
]

# The steps of the General scenario: Claude Code asked (the default, with its program field), then the status
# line chosen (its snippet shown); the usage endpoint is no longer offered (D18).
GENERAL_STEPS = [
    """results => {
        const snippet = () => harness.find(page.item, i => i.objectName === "statusLineSnippet")
        const program = () => harness.find(page.item, i => i.placeholderText === "claude, found on the PATH")
        results.atStart = [page.item.cfg_claudeSource, program().visible, snippet().visible]
        results.sources = harness.findAll(page.item, i => i.autoExclusive === true && i.text !== undefined, []).map(r => r.text)
        results.codexProgram = !!harness.find(page.item, i => i.placeholderText === "codex, found on the PATH")
        harness.click(harness.find(page.item, i => i.text === "Claude Code's status line (no login is read; 5-hour and weekly only)"))
        return () => {
            results.afterStatusLine = [page.item.cfg_claudeSource, program().visible, snippet().visible]
            results.snippet = snippet().text
        }
    }""",
]

# name -> page file, its settings (as the dialog passes them), steps, window height
SCENARIOS: dict[str, dict] = {
    "appearance": dict(page="configAppearance.qml", height=760, steps=APPEARANCE_STEPS, props={
        "cfg_sizeMode": "fit", "cfg_zoomPercent": 100, "cfg_overflowMode": "scroll", "cfg_staleMinutes": 15,
        "cfg_staleColor": "#fdbc4b", "cfg_warnPercent": 80, "cfg_criticalPercent": 95,
        "cfg_warnColor": "#f67400", "cfg_criticalColor": "#abcdef"}),
    "rows": dict(page="configRows.qml", height=420, steps=ROWS_STEPS, props={
        "cfg_hiddenRows": [], "cfg_rowOrder": [], "cfg_knownRows": '[{"id": "codex:primary", "provider": "codex", "label": "Session (5hr)"}, {"id": "claude:session", "provider": "claude", "label": "Session (5hr)"}, {"id": "claude:weekly_all", "provider": "claude", "label": "Weekly (7 day)"}, {"id": "claude:weekly_scoped:Fable", "provider": "claude", "label": "Weekly (Fable)"}, {"id": "codex:secondary", "provider": "codex", "label": "Weekly (7 day)"}]'}),
    "general": dict(page="configGeneral.qml", height=640, steps=GENERAL_STEPS, props={
        "cfg_refreshMinutes": 5, "cfg_showClaude": True, "cfg_claudeSource": "claudecode", "cfg_claudeCommand": "",
        "cfg_credentialsPath": "",
        "cfg_showCodex": True, "cfg_codexCommand": "", "cfg_codexAuthPath": ""}),
}


def run_page(base: Path, name: str, spec: dict) -> dict:
    """Run one scenario; returns ``{"report": dict | None, "errors": [lines], "log": Path}``."""
    work = base / name
    work.mkdir(parents=True)
    for sub in ("config", "cache", "state", "data", "run"):
        (work / sub).mkdir()
    (work / "run").chmod(0o700)
    shot = json.dumps(str(Path(SHOTS) / f"page-{name}.png")) if SHOTS else "null"
    harness = HARNESS % {"page": json.dumps((UI / spec["page"]).as_uri()), "props": json.dumps(spec["props"]),
                         "steps": ",\n".join(spec["steps"]), "shot": shot, "height": spec["height"]}
    (work / "harness.qml").write_text(harness, encoding="utf-8")
    env = {k: v for k, v in os.environ.items()
           if k not in ("DBUS_SESSION_BUS_ADDRESS", "DISPLAY", "WAYLAND_DISPLAY") and not k.startswith("LC_")}
    env.update(HOME=str(work), XDG_CONFIG_HOME=str(work / "config"), XDG_CACHE_HOME=str(work / "cache"),
               XDG_STATE_HOME=str(work / "state"), XDG_DATA_HOME=str(work / "data"), XDG_RUNTIME_DIR=str(work / "run"),
               QT_QPA_PLATFORM="offscreen", QT_QPA_PLATFORMTHEME="kde", QT_QUICK_CONTROLS_STYLE="org.kde.desktop",
               QT_FORCE_STDERR_LOGGING="1", QML_DISABLE_DISK_CACHE="1", LANG="en_US.UTF-8", LC_ALL="en_US.UTF-8")
    try:
        proc = subprocess.run([QML, str(work / "harness.qml")], env=env, capture_output=True, text=True,
                              timeout=DEADLINE_S)
        output = proc.stdout + proc.stderr
    except subprocess.TimeoutExpired as exc:
        # on a timeout Python hands back bytes even with text=True; keep what the page printed
        output = "".join(part.decode("utf-8", "replace") if isinstance(part, bytes) else (part or "")
                         for part in (exc.stdout, exc.stderr)) + f"\n(timed out after {DEADLINE_S} s)"
    log = work / "out.log"
    log.write_text(output, encoding="utf-8")
    match = re.search(r"CU-PAGE (\{.*\})", output)
    errors = [line for line in output.splitlines() if PAGE_ERROR.search(line) and "harness.qml" not in line]
    return {"report": json.loads(match.group(1)) if match else None, "errors": errors, "log": log}


@unittest.skipUnless(QML and KDE_MODULES, "SKIPPED: the qml runtime or the KDE QML modules are missing")
class TestConfigPages(unittest.TestCase):
    """Every scenario runs once, in parallel, in setUpClass; each test reads its result."""

    results: dict[str, dict] = {}

    @classmethod
    def setUpClass(cls) -> None:
        cls.base = Path(tempfile.mkdtemp(prefix="cu-pages-"))
        if not os.environ.get("CU_KEEP_SANDBOX"):
            cls.addClassCleanup(shutil.rmtree, cls.base, ignore_errors=True)
        if SHOTS:
            Path(SHOTS).mkdir(parents=True, exist_ok=True)
        with ThreadPoolExecutor(PARALLEL_RUNS) as pool:
            futures = {name: pool.submit(run_page, cls.base, name, spec) for name, spec in SCENARIOS.items()}
            cls.results = {name: future.result() for name, future in futures.items()}

    def report(self, name: str) -> dict:
        """The scenario's report, after asserting the page loaded and ran with no error."""
        result = self.results[name]
        self.assertEqual(result["errors"], [], f"errors in {name}; log: {result['log']}")
        self.assertIsNotNone(result["report"], f"no report from {name}; log: {result['log']}")
        return result["report"]

    def test_general_page_offers_the_two_claude_sources(self) -> None:
        r = self.report("general")
        self.assertEqual(r["atStart"], ["claudecode", True, False], "Claude Code asked: its program field shown")
        self.assertEqual(r["sources"], ["Claude Code itself (asked for its usage; no login is read here)",
                                        "Claude Code's status line (no login is read; 5-hour and weekly only)"],
                         "the two sources, and no usage endpoint (D18)")
        self.assertTrue(r["codexProgram"], "the Codex program field (D20)")
        self.assertEqual(r["afterStatusLine"], ["statusline", False, True], "the status line: its snippet shown")
        snippet = json.loads(r["snippet"])
        self.assertEqual(snippet["statusLine"]["type"], "command")
        self.assertRegex(snippet["statusLine"]["command"], r"^python3 -B /\S+/contents/code/statusline_tap\.py$")

    def test_rows_are_hidden_moved_and_reset(self) -> None:
        r = self.report("rows")
        self.assertEqual(r["orderAtStart"], ["Claude · Session (5hr)", "Claude · Weekly (7 day)", "Claude · Weekly (Fable)",
                                             "ChatGPT · Session (5hr)", "ChatGPT · Weekly (7 day)"],
                         "default order: Claude's rows, then ChatGPT's, though ChatGPT's was seen first")
        self.assertEqual(r["hiddenAfterUntick"], ["claude:weekly_scoped:Fable"])
        self.assertEqual((r["firstUpEnabled"], r["lastDownEnabled"]), (False, False))
        self.assertEqual(r["orderAfterOneUp"], ["claude:session", "claude:weekly_all", "codex:primary",
                                                "claude:weekly_scoped:Fable", "codex:secondary"])
        self.assertEqual(r["orderAfterTwoUps"], ["claude:session", "codex:primary", "claude:weekly_all",
                                                 "claude:weekly_scoped:Fable", "codex:secondary"])
        self.assertEqual(r["defaultButtons"], 1)
        self.assertEqual((r["orderAfterReset"], r["defaultButtonsAfterReset"]), ([], 0))
        self.assertEqual(r["orderShown"], ["ChatGPT · Session (5hr)", "Claude · Session (5hr)", "Claude · Weekly (7 day)",
                                           "Claude · Weekly (Fable)", "ChatGPT · Weekly (7 day)"])

    def test_the_three_colours_are_shown_and_a_pick_is_stored(self) -> None:
        r = self.report("appearance")
        self.assertEqual(r["colourButtonTitles"], ["Colour of outdated numbers", "Colour from the warning level up",
                                                   "Colour from the critical level up"])
        self.assertEqual(r["shownAtStart"], ["#fdbc4b", "#f67400", "#abcdef"])
        self.assertEqual((r["warnAfterPick"], r["criticalAfterPick"]), ("#ff0000", "#abcdef"))

if __name__ == "__main__":
    unittest.main(verbosity=2)
