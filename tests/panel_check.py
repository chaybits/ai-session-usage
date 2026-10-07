"""Manual check: the widget inside a real Plasma panel, in a throwaway plasmashell.

Starts plasmashell inside a headless KWin (shell_harness.py) whose Plasma config holds one bottom panel with
only this widget in it. The widget copy answers from a stub helper (no login is read, no request is made) and
logs, once it sits in the panel, its compact size and two pictures: the panel form, and the popup a click
opens.

Not part of run_all.sh: it takes about 20 s and its result is the pictures. Run it after a change to the
compact form:  python3 tests/panel_check.py [output-dir]   (default: a new temp dir; the pictures and the
log stay)
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import shell_harness as sh
import test_qml_load as q

PANEL_THICKNESS = 44

APPLETSRC = """[Containments][1]
activityId=
formfactor=0
immutability=1
lastScreen=0
location=0
plugin=org.kde.desktopcontainment
wallpaperplugin=org.kde.color

[Containments][2]
activityId=
formfactor=2
immutability=1
lastScreen=0
location=4
plugin=org.kde.panel

[Containments][2][Applets][3]
immutability=1
plugin=%(plugin)s

[Containments][2][General]
AppletOrder=3
"""

PLASMASHELLRC = """[PlasmaViews][Panel 2]
floating=0

[PlasmaViews][Panel 2][Defaults]
thickness=%(thickness)d
"""

PROBE = """
    Timer {
        interval: 1500; repeat: true; running: true
        property int step: 0
        onTriggered: {
            if (Plasmoid.formFactor !== PlasmaCore.Types.Horizontal || !root.compactRepresentationItem) {
                return
            }
            step++
            const c = root.compactRepresentationItem
            if (step === 1) {
                c.grabToImage(r => {
                    r.saveToFile(%(panel_png)s)
                    console.log("CU-PANEL " + JSON.stringify({ width: c.width, height: c.height,
                        minWidth: c.Layout.minimumWidth, compact: Logic.compactText(root.sections.map(x => ({ rows: x.rows }))) }))
                    root.expanded = true
                })
            } else if (step === 3 && root.fullRepresentationItem) {
                const f = root.fullRepresentationItem
                f.grabToImage(r => {
                    r.saveToFile(%(popup_png)s)
                    console.log("CU-POPUP " + JSON.stringify({ width: f.width, height: f.height, zoom: f.zoom }))
                })
            }
        }
    }
"""


def main() -> int:
    """Run the check; prints where the pictures are and what the widget reported."""
    why_not = sh.missing()
    if why_not:
        print(f"SKIPPED: {why_not}")
        return 0
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp(prefix="cu-panel-"))
    out.mkdir(parents=True, exist_ok=True)
    probe = PROBE % {"panel_png": json.dumps(str(out / "panel.png")), "popup_png": json.dumps(str(out / "popup.png"))}
    sandbox = sh.prepare(out, APPLETSRC % {"plugin": q.PLUGIN_ID}, probe, q.stub(q.CLAUDE_HOT, q.CODEX_OK),
                         plasmashellrc=PLASMASHELLRC % {"thickness": PANEL_THICKNESS})
    log_path = out / "shell.log"
    result = sh.run(sandbox, log_path, "POPUP", deadline_s=40)
    report = {key.lower(): items[-1] for key, items in result["reports"].items()}
    print(json.dumps({"report": report, "widget_errors": result["errors"][:sh.SHOWN_ERRORS], "pictures": str(out),
                      "log": str(log_path)}, indent=1))
    return 0 if "panel" in report and not result["errors"] else 1


if __name__ == "__main__":
    sys.exit(main())
