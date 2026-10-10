"""Investigation: what the widget's text looks like while it is resized by dragging, after it, and how the
way Qt draws text changes it at a large size.

Reproduces the reported action in a throwaway plasmashell (shell_harness.py): the widget on a desktop at the
tablet's scale with the shadow background, put in edit mode by a press-and-hold, the mouse moved over it (the
resize handles show while it hovers), and its bottom-right handle dragged in steps with real Qt mouse
events. The widget's container is grabbed after every step, the mouse still held; after the release edit mode
is left and it is grabbed again. Then the references, each a fresh widget loaded at the size to compare:

- ``held``: in edit mode at the last step's size, against the last mid-drag frame. A difference would mean
  Plasma draws something else while dragging (a scaled copy, say).
- ``fresh``: at the released size, against the widget after the drag. A difference would mean the drag
  leaves something behind.
- ``render-*``: at ``--big`` size, the widget as it is (native text, D10) beside copies switched to Qt's two
  other ways of drawing text: its default (distance field, what Plasma's own labels use) and curves.

Prints a JSON summary and leaves every picture in the output folder, with 3x enlargements of a text crop
(``zoom-*.png``) and a side-by-side of the render types (``compare-render.png``).

    python3 tests/resize_check.py [--out DIR] [--scale 1.5] [--steps 4] [--grow-x 256] [--grow-y 128] [--big 800x512]
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import shell_harness as sh
import test_qml_load as q

START = (100, 100, 400, 256)
SCREEN = (1920, 1200)
APPLET_CONFIG = {"": {"UserBackgroundHints": "ShadowBackground"}}
# Where the text crops are taken, as fractions of a picture: the title and the first row.
TEXT_BOX = (0.0, 0.0, 0.6, 0.34)

COMMON = """
    TestEvent { id: __ev }
    // __container() and __findAll() come with the harness (shell_harness.PROBE_HELPERS).
    function __scene(item) {
        return item.mapToItem(null, item.width / 2, item.height / 2)
    }
    function __grab(name, then) {
        // grabToImage answers false (and never calls back) for an item with no size or no window: say so and go
        // on, or the script waits for the callback until the deadline
        const started = __container().grabToImage(r => {
            r.saveToFile(%(out)s + "/" + name + ".png")
            then()
        })
        if (!started) {
            console.log("CU-ERROR grab refused: " + name)
            then()
        }
    }
    function __state() {
        const c = __container(), f = root.fullRepresentationItem
        return { container: [c.x, c.y, c.width, c.height], zoom: f.zoom, editMode: c.editMode,
                 screen: [Screen.width, Screen.height] }
    }
    // Ticks of a script, one function per tick; a function returning false is called again on the next tick.
    property var __script: []
    property var __log: []
    Timer {
        interval: 350; repeat: true; running: true
        property int at: -1
        onTriggered: {
            const f = root.fullRepresentationItem, c = root.__container()
            if (at < 0) {
                if (!f || f.width <= 0 || root.sections.length < 1 || !c || root.__script.length === 0) {
                    return
                }
                at = 0
            }
            if (at >= root.__script.length) {
                running = false
                return
            }
            if (root.__script[at]() !== false) {
                at++
            }
        }
    }
    // Press and hold for 1.4 s (edit mode starts after the press-and-hold time, 0.8 s by default), then hover
    // (the handles show while the mouse is over the widget).
    function __enterEditMode() {
        return [
            () => { __ev.mousePress(root.fullRepresentationItem, 20, 8, Qt.LeftButton, Qt.NoModifier, -1) },
            () => {},
            () => {},
            () => {},
            () => { __ev.mouseRelease(root.fullRepresentationItem, 20, 8, Qt.LeftButton, Qt.NoModifier, -1) },
            () => {
                const centre = __scene(__container())
                __ev.mouseMove(root.Window.window.contentItem, centre.x, centre.y, -1, Qt.NoButton, Qt.NoModifier)
            },
            () => {},
            () => {},
        ]
    }
    // Grab the container, then go on (the grab is asynchronous).
    function __grabStep(name, extra) {
        let state = 0
        return () => {
            if (state === 0) {
                state = 1
                __grab(name, () => { state = 2 })
                return false
            }
            if (state === 1) {
                return false
            }
            const entry = { step: name, state: __state() }
            Object.assign(entry, extra ? extra() : {})
            __log.push(entry)
        }
    }
"""

DRAG = COMMON + """
    Component.onCompleted: {
        let handle = null, start = null
        const steps = root.__enterEditMode()
        steps.push(() => {
            const handles = __findAll(__container().configOverlayItem, i => i.resizeCorner !== undefined && i.visible, [])
            handles.sort((a, b) => (__scene(b).x + __scene(b).y) - (__scene(a).x + __scene(a).y))
            handle = handles[0]
            if (!handle) {
                console.log("CU-RESIZE " + JSON.stringify({ error: "no resize handle", state: __state() }))
                root.__script = []
                return
            }
            start = __scene(handle)
            __log.push({ step: "edit", state: __state(), corner: handle.resizeCorner })
            __ev.mousePress(handle, handle.width / 2, handle.height / 2, Qt.LeftButton, Qt.NoModifier, -1)
        })
        for (let k = 1; k <= %(steps)d; k++) {
            const n = k
            steps.push(() => {
                const dx = %(grow_x)d * n / %(steps)d, dy = %(grow_y)d * n / %(steps)d
                __ev.mouseMove(root.Window.window.contentItem, start.x + dx, start.y + dy, -1, Qt.LeftButton, Qt.NoModifier)
            })
            steps.push(__grabStep("10-drag-" + n, () => ({ pressed: handle.pressed })))
        }
        steps.push(() => {
            __ev.mouseRelease(root.Window.window.contentItem, start.x + %(grow_x)d, start.y + %(grow_y)d,
                              Qt.LeftButton, Qt.NoModifier, -1)
        })
        steps.push(() => {})
        steps.push(() => {
            // leave edit mode everywhere it is kept: the desktop, its layout and the widget's container
            Plasmoid.containment.corona.editMode = false
            __container().layout.editMode = false
            __container().editMode = false
        })
        steps.push(() => {})
        steps.push(() => {})
        steps.push(__grabStep("20-after"))
        steps.push(() => { console.log("CU-RESIZE " + JSON.stringify({ log: __log })) })
        root.__script = steps
    }
"""

# A fresh widget, grabbed as it is, or after entering edit mode the same way the drag does.
FRESH = COMMON + """
    Component.onCompleted: {
        const steps = %(edit)s ? root.__enterEditMode() : [() => {}, () => {}]
        steps.push(() => {})
        steps.push(__grabStep(%(name)s))
        steps.push(() => { console.log("CU-FRESH " + JSON.stringify({ log: __log })) })
        root.__script = steps
    }
"""


def run(out: Path, name: str, geometry: tuple[int, int, int, int], probe: str, tag: str, scale: float, *,
        render: str = "") -> dict:
    """One shell run in ``out/name``; returns its last ``tag`` report, or what went wrong. ``render`` names
    another render type for every label of the package copy (QtRendering, CurveRendering)."""
    folder = out / name
    folder.mkdir(parents=True, exist_ok=True)
    sandbox = sh.prepare(folder, sh.desktop_appletsrc(geometry, sh.logical_size(SCREEN, scale), applet_config=APPLET_CONFIG),
                         probe, q.stub(q.CLAUDE_OK), imports=("import QtTest", "import QtQuick.Window"))
    if render:
        q._replace_once(sandbox / "data/plasma/plasmoids" / q.PLUGIN_ID / "contents/ui/CardLabel.qml",
                        "renderType: Text.NativeRendering", f"renderType: Text.{render}")
    result = sh.run(sandbox, folder / "shell.log", tag, size=SCREEN, scale=scale)
    reports = result["reports"].get(tag, [])
    if not reports or result["errors"]:
        return {"error": "no report" if not reports else "QML errors", "errors": result["errors"][:sh.SHOWN_ERRORS],
                "log": str(folder / "shell.log")}
    return reports[-1]


def compare(a: Path, b: Path) -> dict:
    """Pixel difference of two pictures: mean and max absolute difference, and the share of pixels that
    differ at all; or their sizes when they differ."""
    import numpy as np
    from PIL import Image
    x = np.asarray(Image.open(a).convert("RGBA"), dtype=np.int16)
    y = np.asarray(Image.open(b).convert("RGBA"), dtype=np.int16)
    if x.shape != y.shape:
        return {"sizes": [list(x.shape), list(y.shape)]}
    d = np.abs(x - y)
    return {"mean": round(float(d.mean()), 3), "max": int(d.max()), "differing": round(float((d.max(axis=2) > 0).mean()), 4)}


def crop(src: Path, box: tuple[float, float, float, float] = TEXT_BOX):
    """The text crop of a picture, over a mid-grey ground (the grabs are transparent around the text)."""
    from PIL import Image
    img = Image.open(src).convert("RGBA")
    w, h = img.size
    part = img.crop((int(w * box[0]), int(h * box[1]), int(w * box[2]), int(h * box[3])))
    ground = Image.new("RGBA", part.size, (96, 104, 112, 255))
    ground.alpha_composite(part)
    return ground.convert("RGB")


def enlarge(src: Path, dst: Path, factor: int = 3) -> None:
    """Save a nearest-neighbour enlargement of the text crop, to look at single pixels."""
    from PIL import Image
    part = crop(src)
    part.resize((part.width * factor, part.height * factor), Image.NEAREST).save(dst)


def side_by_side(sources: list[tuple[str, Path]], dst: Path) -> None:
    """The text crops of several pictures one under another, each 2x, with its name above it."""
    from PIL import Image, ImageDraw
    parts = [(name, crop(path)) for name, path in sources]
    parts = [(name, p.resize((p.width * 2, p.height * 2), Image.NEAREST)) for name, p in parts]
    label_h = 22
    width = max(p.width for _, p in parts)
    sheet = Image.new("RGB", (width, sum(p.height + label_h for _, p in parts)), (255, 255, 255))
    draw = ImageDraw.Draw(sheet)
    y = 0
    for name, part in parts:
        draw.text((4, y + 4), name, fill=(0, 0, 0))
        sheet.paste(part, (0, y + label_h))
        y += part.height + label_h
    sheet.save(dst)


def sharpness(path: Path) -> float:
    """Mean gradient magnitude over the text crop's edge pixels (higher = crisper edges)."""
    import numpy as np
    g = np.asarray(crop(path).convert("L"), dtype=np.float64)
    gx, gy = np.abs(np.diff(g, axis=1))[:-1, :], np.abs(np.diff(g, axis=0))[:, :-1]
    mag = np.hypot(gx, gy)
    edges = mag[mag > 8]
    return round(float(edges.mean()), 2) if edges.size else 0.0


def missing_packages() -> str | None:
    """The Python package the comparisons need but the harness's own check does not cover, or None."""
    for name in ("PIL", "numpy"):
        try:
            __import__(name)
        except ImportError:
            return f"python package {name} (pillow or numpy) is not installed"
    return None


def main() -> int:
    """Run the drag, the references and the render types; print the summary."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=None, help="output folder (default: a new temp folder)")
    parser.add_argument("--scale", type=float, default=1.5, help="screen scale (the tablet's is 1.5)")
    parser.add_argument("--steps", type=int, default=4, help="drag steps")
    # 256 x 128 in four steps keeps every step on the desktop's 16 px grid, where a fresh widget can sit too
    parser.add_argument("--grow-x", type=int, default=256, help="how far right the corner is dragged, logical px")
    parser.add_argument("--grow-y", type=int, default=128, help="how far down the corner is dragged, logical px")
    parser.add_argument("--big", default="800x512", help="size of the render-type comparison, WxH logical px")
    args = parser.parse_args()
    why_not = sh.missing() or missing_packages()
    if why_not:
        print(f"SKIPPED: {why_not}")
        return 0
    out = args.out or Path(tempfile.mkdtemp(prefix="cu-resize-"))
    out.mkdir(parents=True, exist_ok=True)
    marks = {"out": json.dumps(str(out)), "steps": args.steps, "grow_x": args.grow_x, "grow_y": args.grow_y}
    summary: dict = {"out": str(out)}
    problems: list[str] = []  # what went wrong, so the exit code says so (a run that drew nothing is not a pass)

    drag = run(out, "drag", START, DRAG % marks, "RESIZE", args.scale)
    entries = drag.get("log") if isinstance(drag.get("log"), list) else []
    summary["drag"] = entries or drag
    if not entries:
        problems.append(f"drag: {drag.get('error', 'no log')}")
    states = {e["step"]: e["state"] for e in entries}
    after = states.get("20-after")
    # every mid-drag frame against a fresh widget of the same size, also in edit mode
    for n in range(1, args.steps + 1):
        held = states.get(f"10-drag-{n}")
        if not held:
            continue
        x, y, w, h = (round(v) for v in held["container"])
        name = f"30-held-{n}"
        ref = run(out, f"held-{n}", (x, y, w, h), FRESH % dict(marks, edit="true", name=json.dumps(name)), "FRESH",
                  args.scale)
        summary[f"held_reference_{n}"] = ref.get("log", ref)
        pair = (out / f"10-drag-{n}.png", out / f"{name}.png")
        if all(p.exists() for p in pair):
            summary[f"mid_drag_{n}_vs_fresh_in_edit_mode"] = compare(*pair)
        else:
            problems.append(f"missing screenshot: {[p.name for p in pair if not p.exists()]}")
    if after:
        x, y, w, h = (round(v) for v in after["container"])
        ref = run(out, "fresh", (x, y, w, h), FRESH % dict(marks, edit="false", name=json.dumps("31-fresh")), "FRESH", args.scale)
        summary["fresh_reference"] = ref.get("log", ref)
        pair = (out / "20-after.png", out / "31-fresh.png")
        if all(p.exists() for p in pair):
            summary["after_drag_vs_fresh"] = compare(*pair)
        else:
            problems.append(f"missing screenshot: {[p.name for p in pair if not p.exists()]}")

    bw, bh = (int(v) for v in args.big.split("x"))
    big = (START[0], START[1], bw, bh)
    renders = {"native (the widget)": "", "distance (Qt's default)": "QtRendering", "curve": "CurveRendering"}
    shots = []
    for kind, render in renders.items():
        name = f"40-render-{kind.split()[0]}"
        ref = run(out, f"render-{kind.split()[0]}", big, FRESH % dict(marks, edit="false", name=json.dumps(name)), "FRESH",
                  args.scale, render=render)
        summary[f"render_{kind}"] = ref.get("log", ref)
        if (out / f"{name}.png").exists():
            shots.append((kind, out / f"{name}.png"))
            summary[f"sharpness_{kind.split()[0]}"] = sharpness(out / f"{name}.png")
        else:
            problems.append(f"render {kind}: {ref.get('error', 'no picture')}")
    if shots:
        side_by_side(shots, out / "compare-render.png")
    for png in sorted(out.glob("[0-9]*.png")):
        enlarge(png, out / f"zoom-{png.stem}.png")
    summary["problems"] = problems
    print(json.dumps(summary, indent=1))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
