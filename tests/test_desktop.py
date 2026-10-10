"""Mouse input on the widget placed on a real Plasma desktop: a throwaway plasmashell in a headless KWin.

The checks a sandboxed plasmawindowed cannot make, because they need the containment around the widget. A
right-click must open the widget's menu, which the desktop opens only when no item inside the widget took
the press; a left click must still refresh, the wheel must still scroll, and a press-and-hold must still
enter edit mode (how the widget is moved and resized). The events are real QMouseEvent and QWheelEvent
objects sent to plasmashell's window by Qt's own test module (QtTest's TestEvent), so they travel the
delivery path a mouse's events travel. The menu is detected by the applet's contextualActionsAboutToShow
signal, which the desktop emits just before it shows a widget's menu.

The desktop also resizes the widget's slot by itself: whenever the widget's size hints change it grows the
slot to the preferred size, and never shrinks it back (plasma-workspace, gridlayoutmanager.cpp,
adjustToItemSizeHints). Two more runs check that a slot the user set keeps its size when the card grows after
it was placed (the answers arriving late, then a status line), and what size a widget just added gets.

Skipped, loudly, where KWin, plasmashell or the activity daemon is missing. About 25 s (the runs are parallel).
"""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import shell_harness as sh
import test_qml_load as q

WHY_NOT = sh.missing()
# The tablet's slot, at the tablet's scale: the size and scale the defect was reported at.
GEOMETRY = (100, 100, 400, 256)
# The helper answers this late in the growth runs, so the card grows after the desktop placed the widget.
LATE_S = 4
# A slot smaller than the design size (about 400 x 256), as a user may make it; on the desktop's 16 px grid.
NARROW = (100, 100, 320, 208)
SCALE = 1.5
SCREEN = (1920, 1200)

PROBE = """
    TestEvent { id: __ev }
    property int __menus: 0
    Connections {
        target: Plasmoid
        function onContextualActionsAboutToShow() { root.__menus++ }
    }
    // __container() and __findAll() come with the harness (shell_harness.PROBE_HELPERS).
    function __find(item, test) {
        return __findAll(item, test, [])[0] || null
    }
    function __rightClick(name, item, x, y) {
        return results => {
            const before = root.__menus
            __ev.mouseClick(item, x, y, Qt.RightButton, Qt.NoModifier, -1)
            return () => { results[name] = root.__menus > before }
        }
    }
    function __actions(full) {
        const bar = __find(full, i => i.objectName === "bar:claude:session")
        const percent = __find(full, i => i.objectName === "percent:claude:session")
        const flick = __find(full, i => i.contentY !== undefined && i.flickableDirection !== undefined)
        const scrollBar = __find(full, i => i.orientation === Qt.Vertical && i.policy !== undefined && i.visible)
        const source = root.sources[0]
        return [
            __rightClick("rightOnBar", bar, bar.width / 2, bar.height / 2),
            __rightClick("rightOnPercent", percent, percent.width / 2, percent.height / 2),
            __rightClick("rightOnTitle", full, 20, 8),
            __rightClick("rightOnBottom", full, full.width / 2, full.height - 6),
            results => {
                results.scrollBarFound = scrollBar !== null
                return () => {}
            },
            __rightClick("rightOnScrollBar", scrollBar || full, scrollBar ? scrollBar.width / 2 : -1,
                         scrollBar ? scrollBar.height / 2 : -1),
            results => {
                const before = source.lastAttemptMs
                __ev.mouseClick(full, 20, 8, Qt.LeftButton, Qt.NoModifier, -1)
                return () => { results.leftClickRefreshes = source.lastAttemptMs > before }
            },
            results => {
                const before = flick ? flick.contentY : -1
                __ev.mouseWheel(full, full.width / 2, full.height / 2, Qt.NoButton, Qt.NoModifier, 0, -120, -1)
                return () => {
                    results.wheelScrolls = flick !== null && flick.contentY > before
                    results.overflows = flick !== null && flick.contentHeight > flick.height
                }
            },
            results => {
                __ev.mousePress(full, 20, 8, Qt.LeftButton, Qt.NoModifier, -1)
                return () => {
                    results.holdEntersEditMode = root.__container().editMode
                    __ev.mouseRelease(full, 20, 8, Qt.LeftButton, Qt.NoModifier, -1)
                }
            },
        ]
    }
    // One action per tick, its result read on the next one; a press-and-hold needs the tick's length.
    Timer {
        interval: 900; repeat: true; running: true
        property int step: -1
        property var results: ({})
        property var pending: null
        onTriggered: {
            const full = root.fullRepresentationItem
            if (step < 0) {
                if (!full || full.width <= 0 || root.sections.length < 2 || !root.__container()) {
                    return
                }
                step = 0
                results.size = [full.width, full.height]
                const c = root.__container()
                results.container = [c.x, c.y, c.width, c.height]
                results.padding = [c.leftPadding, c.topPadding, c.rightPadding, c.bottomPadding]
                results.screen = [c.layout.containmentItem.width, c.layout.containmentItem.height]
                results.hints = [full.Layout.minimumHeight, full.Layout.preferredHeight]
            }
            if (pending) {
                const read = pending
                pending = null
                read()
                return
            }
            const actions = root.__actions(full)
            if (step >= actions.length) {
                console.log("CU-DESKTOP " + JSON.stringify(results))
                running = false
                return
            }
            pending = actions[step++](results)
        }
    }
"""


# Once both answers are in: optionally a failed fetch (a status line appears under ChatGPT's rows), then a
# wait longer than the desktop's size-hint timer, then the slot's geometry. The heights seen on the way too.
SLOT_PROBE = """
    Timer {
        interval: 300; repeat: true; running: true
        property int tick: -1
        property var heights: []
        onTriggered: {
            const c = root.__container(), f = root.fullRepresentationItem
            if (c) {
                const h = Math.round(c.height)
                if (heights.length === 0 || heights[heights.length - 1] !== h) {
                    heights.push(h)
                }
            }
            if (tick < 0) {
                if (!f || !c || root.anyBusy || root.sections.length < 2 || root.sections[1].rows.length === 0) {
                    return
                }
                tick = 0
            }
            tick++
            if (tick === 1 && %(fail)s) {
                root.sources[1].handleOutput(JSON.stringify({ ok: false, error: "cli", message: "no route" }), "")
            }
            if (tick === 1) {
                %(then)s
            }
            if (tick === 10) {
                running = false
                console.log("CU-SLOT " + JSON.stringify({ container: [c.x, c.y, c.width, c.height], heights: heights,
                    hints: [f.Layout.minimumWidth, f.Layout.minimumHeight, f.Layout.preferredWidth, f.Layout.preferredHeight],
                    status: root.sectionStatus(root.sources[1]), placed: Plasmoid.configuration.placedAtDesignSize }))
            }
        }
    }
"""


def run_shell(name: str, geometry: tuple[int, int, int, int] | None, probe: str, stub: str, tag: str,
              replace: tuple = (), defaults: dict[str, str] | None = None) -> dict:
    """One plasmashell run; returns its last ``tag`` report (or {}), its errors and its folder."""
    out = Path(tempfile.mkdtemp(prefix=f"cu-desktop-{name}-"))
    sandbox = sh.prepare(out, sh.desktop_appletsrc(geometry, sh.logical_size(SCREEN, SCALE)), probe, stub,
                         imports=("import QtTest",), replace=replace, defaults=defaults)
    result = sh.run(sandbox, out / "shell.log", tag, size=SCREEN, scale=SCALE)
    reports = result["reports"].get(tag, [])
    return {"report": reports[-1] if reports else {}, "errors": result["errors"], "out": out}


@unittest.skipUnless(WHY_NOT is None, f"SKIPPED: no Plasma shell can run here ({WHY_NOT})")
class TestDesktopMouse(unittest.TestCase):
    """One shell run in setUpClass; each test reads its part of the report."""

    report: dict = {}

    @classmethod
    def setUpClass(cls) -> None:
        runs = {
            # a click within 10 s of the first fetch is throttled; the left-click check needs it to count
            "mouse": (GEOMETRY, PROBE, q.stub(q.CLAUDE_OK, q.CODEX_OK), "DESKTOP",
                      (("ui/UsageLogic.js", "var TAP_THROTTLE_MS = 10000", "var TAP_THROTTLE_MS = 0"),)),
            "late-growth": (GEOMETRY, SLOT_PROBE % {"fail": "true", "then": ""},
                            q.stub(q.CLAUDE_OK, q.CODEX_OK, sleep_s=LATE_S), "SLOT", ()),
            "fresh": (None, SLOT_PROBE % {"fail": "false", "then": ""}, q.stub(q.CLAUDE_OK, q.CODEX_OK), "SLOT", ()),
            # a widget placed before (its flag set), in a slot the user made smaller than the design size
            "narrow": (NARROW, SLOT_PROBE % {"fail": "true", "then": ""}, q.stub(q.CLAUDE_OK, q.CODEX_OK, sleep_s=LATE_S),
                       "SLOT", (), {"placedAtDesignSize": "true"}),
            # the same, switched to "make the widget taller": new size hints, the height grows (that mode's point),
            # the width the user set stays
            "narrow-taller": (NARROW, SLOT_PROBE % {"fail": "false", "then": 'Plasmoid.configuration.overflowMode = "grow"'},
                              q.stub(q.CLAUDE_OK, q.CODEX_OK), "SLOT", (), {"placedAtDesignSize": "true"}),
        }
        with ThreadPoolExecutor(len(runs)) as pool:
            futures = {name: pool.submit(run_shell, name, *spec) for name, spec in runs.items()}
            cls.runs = {name: future.result() for name, future in futures.items()}
        if not os.environ.get("CU_KEEP_SANDBOX"):  # as the load tests: kept only when asked
            for run in cls.runs.values():
                cls.addClassCleanup(shutil.rmtree, run["out"], ignore_errors=True)
        cls.report = cls.runs["mouse"]["report"]

    def run_report(self, name: str) -> dict:
        """A run's report, after asserting it loaded with no QML error and reported."""
        run = self.runs[name]
        self.assertEqual(run["errors"], [], f"QML errors in {name}; log: {run['out'] / 'shell.log'}")
        self.assertTrue(run["report"], f"the {name} probe never reported; log: {run['out'] / 'shell.log'}")
        return run["report"]

    def setUp(self) -> None:
        self.run_report("mouse")

    def test_the_widget_sits_in_the_tablets_slot(self) -> None:
        # the checks below are meant at the reported size and scale; a sandbox that ignored the geometry or the
        # scale would quietly test another case (it did, until the geometry keys and the output config were right)
        self.assertEqual(self.report["screen"], list(sh.logical_size(SCREEN, SCALE)), "the 1.5 scale applies")
        self.assertEqual(self.report["container"][2:], [GEOMETRY[2], GEOMETRY[3]])

    def test_a_right_click_anywhere_opens_the_widgets_menu(self) -> None:
        self.assertTrue(self.report["scrollBarFound"], "the scrollbar shows: two providers in 400 x 256 overflow")
        clicks = {k: v for k, v in self.report.items() if k.startswith("rightOn")}
        self.assertEqual(clicks, {"rightOnBar": True, "rightOnPercent": True, "rightOnTitle": True,
                                  "rightOnBottom": True, "rightOnScrollBar": True}, self.report)

    def test_a_left_click_still_refreshes(self) -> None:
        self.assertTrue(self.report["leftClickRefreshes"], self.report)

    def test_the_wheel_still_scrolls(self) -> None:
        self.assertTrue(self.report["overflows"], "two providers in 400 x 256 must need scrolling")
        self.assertTrue(self.report["wheelScrolls"], self.report)

    def test_a_slot_the_user_set_keeps_its_size_when_the_card_grows(self) -> None:
        r = self.run_report("late-growth")
        self.assertRegex(r["status"], "could not tell the usage: no route", "the status line appeared")
        self.assertEqual(r["container"][2:], [GEOMETRY[2], GEOMETRY[3]], f"heights seen: {r['heights']}")

    def test_a_widget_just_added_opens_at_the_design_size(self) -> None:
        # about 400 x 256 (22 x 14 grid units, on the desktop's 16 px grid), then it remembers it was placed
        r = self.run_report("fresh")
        self.assertEqual(r["container"][2:], [400, 256], f"heights seen: {r['heights']}, hints: {r['hints']}")
        self.assertTrue(r["placed"], "the flag is set once it has been shown")

    def test_a_slot_smaller_than_the_design_size_is_kept(self) -> None:
        r = self.run_report("narrow")
        self.assertRegex(r["status"], "could not tell the usage: no route", "the status line appeared")
        self.assertEqual(r["container"][2:], [NARROW[2], NARROW[3]], f"heights seen: {r['heights']}, hints: {r['hints']}")

    def test_make_the_widget_taller_keeps_the_width_the_user_set(self) -> None:
        r = self.run_report("narrow-taller")
        self.assertEqual(r["container"][2], NARROW[2], f"hints: {r['hints']}")
        self.assertGreater(r["container"][3], NARROW[3], "taller: the slot grew to the rows")

    def test_a_press_and_hold_still_enters_edit_mode(self) -> None:
        self.assertTrue(self.report["holdEntersEditMode"], self.report)


if __name__ == "__main__":
    unittest.main(verbosity=2)
