"""Demo pictures of the widget with fixed English values, for the README.

Each example runs the real package on a real Plasma desktop in a throwaway plasmashell (tests/shell_harness.py:
a headless KWin, a private D-Bus, HOME and every XDG dir in a temp folder), with a stub helper that answers
fixed rows, the clock frozen at FIXED_NOW (UTC, US English), and a gradient made here as the wallpaper (no
third-party image, so the pictures carry no other licence). The desktop is grabbed and cropped around the
widget; the pictures go to ``--out`` as ``NN-slug.png`` (Projects/CLAUDE.md O7), each checked against O8's ~500 KB.

    python3 scripts/demo_shots.py [--out docs] [--scale 1.5] [--only 03-claude-reordered]
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "tests"))
import shell_harness as sh  # noqa: E402  (the tests folder holds the harness)

# The moment every picture shows: the reset countdowns and "Updated" are computed from it.
FIXED_NOW = datetime(2026, 10, 7, 14, 0, tzinfo=timezone.utc)
SCREEN = (1920, 1200)
# Space kept around the widget in the crop, in logical pixels.
MARGIN = 28
# O8: a picture over this is a release asset, not a docs picture.
MAX_BYTES = 500 * 1024
GRADIENT = ((27, 40, 56), (42, 93, 110))


def row(provider: str, rid: str, label: str, group: str, percent: float, minutes: int | None) -> dict:
    """One helper row, reset ``minutes`` after FIXED_NOW (None: no reset time)."""
    reset = None if minutes is None else (FIXED_NOW + timedelta(minutes=minutes)).isoformat()
    return {"id": f"{provider}:{rid}", "provider": provider, "kind": rid.split(":")[0], "group": group,
            "label": label, "percent": percent, "resets_at": reset}


def claude(session: float, weekly: float, fable: float) -> list[dict]:
    """Claude's three rows: the 5-hour session, the weekly limit, the weekly Fable cap."""
    return [row("claude", "session", "Session (5hr)", "session", session, 134),
            row("claude", "weekly_all", "Weekly (7 day)", "weekly", weekly, 3 * 1440 + 300),
            row("claude", "weekly_scoped:Fable", "Weekly (Fable)", "weekly", fable, 3 * 1440 + 300)]


def chatgpt(session: float, weekly: float) -> list[dict]:
    """ChatGPT's two rows on a Plus plan: the 5-hour window and the weekly one."""
    return [row("codex", "primary", "Session (5hr)", "session", session, 211),
            row("codex", "secondary", "Weekly (7 day)", "weekly", weekly, 5 * 1440 + 90)]


# name -> the rows of each provider (None: not logged in), settings defaults, the widget's size (logical px)
EXAMPLES: dict[str, dict] = {
    # numbered in the order the README shows them (O7); 05 is for store listings
    "01-claude-and-chatgpt": dict(claude=claude(34, 61, 18), codex=chatgpt(22, 47), size=(400, 384)),
    "02-mixed-order": dict(claude=claude(34, 61, 18), codex=chatgpt(22, 47), size=(400, 384),
                           defaults={"rowOrder": "claude:session,codex:primary,claude:weekly_all,codex:secondary"}),
    "03-claude-reordered": dict(claude=claude(34, 61, 18), size=(400, 240),
                                defaults={"rowOrder": "claude:weekly_scoped:Fable,claude:weekly_all,claude:session"}),
    "04-claude-levels": dict(claude=claude(86, 97, 42), size=(400, 240)),
    "05-claude": dict(claude=claude(34, 61, 18), size=(400, 240)),
}

NOLOGIN = {"ok": False, "error": "nologin", "message": "not found"}

STUB = """#!/usr/bin/env python3
import json, sys
provider = sys.argv[sys.argv.index('--provider') + 1] if '--provider' in sys.argv else 'claude'
answers = json.loads(%r)
print(json.dumps(answers.get(provider)))
"""

PROBE = """
    Timer {
        interval: 400; repeat: true; running: true
        property int tick: -1
        onTriggered: {
            const f = root.fullRepresentationItem
            const c = root.__container()  // from the harness (shell_harness.PROBE_HELPERS)
            if (tick < 0) {
                if (!f || f.width <= 0 || !c || root.anyBusy || root.sections.length < %(sections)d) {
                    return
                }
                tick = 0
            }
            tick++
            // freeze the clock: countdowns from FIXED_NOW, and "Updated" at it
            root.nowMs = %(now)d
            for (const s of root.sources) {
                // only a source with an answer: one never answered (no login) must stay hidden
                if (s.usage !== null) {
                    s.lastSuccessMs = %(now)d
                }
            }
            if (tick === 4) {
                running = false
                // the desktop itself: its wallpaper and the widgets on it
                const scene = c.layout.containmentItem
                const r = c.mapToItem(scene, 0, 0)
                const started = scene.grabToImage(img => {
                    img.saveToFile(%(shot)s)
                    console.log("CU-DEMO " + JSON.stringify({ rect: [r.x, r.y, c.width, c.height],
                                                             scene: [scene.width, scene.height] }))
                })
                if (!started) {
                    console.log("CU-DEMO " + JSON.stringify({ error: "grabToImage refused" }))
                }
            }
        }
    }
"""


def gradient(path: Path) -> None:
    """A plain diagonal gradient the size of the screen, made here (no third-party image)."""
    from PIL import Image
    w, h = SCREEN
    img = Image.new("RGB", (w, h))
    (r0, g0, b0), (r1, g1, b1) = GRADIENT
    px = img.load()
    for y in range(h):
        for x in range(w):
            t = (x / w + y / h) / 2
            px[x, y] = (round(r0 + (r1 - r0) * t), round(g0 + (g1 - g0) * t), round(b0 + (b1 - b0) * t))
    img.save(path)


def shoot(name: str, spec: dict, out: Path, work: Path, scale: float, wallpaper: Path) -> dict:
    """Run one example; save ``out/<name>.png`` cropped around the widget. Returns what happened."""
    from PIL import Image
    folder = work / name
    folder.mkdir(parents=True)
    answers = {"claude": {"ok": True, "status": 200, "provider": "claude", "rows": spec["claude"]} if spec.get("claude") else NOLOGIN,
               "codex": {"ok": True, "status": 200, "provider": "codex", "rows": spec["codex"]} if spec.get("codex") else NOLOGIN}
    w, h = spec["size"]
    geometry = (96, 96, w, h)
    full_shot = folder / "screen.png"
    probe = PROBE % {"sections": sum(1 for p in ("claude", "codex") if spec.get(p)),
                     "now": int(FIXED_NOW.timestamp() * 1000), "shot": json.dumps(str(full_shot))}
    sandbox = sh.prepare(folder, sh.desktop_appletsrc(geometry, sh.logical_size(SCREEN, scale), wallpaper=str(wallpaper)),
                         probe, STUB % json.dumps(answers), defaults=spec.get("defaults", {}))
    result = sh.run(sandbox, folder / "shell.log", "DEMO", size=SCREEN, scale=scale, locale="en_US.UTF-8",
                    extra_env={"TZ": "UTC"})
    reports = result["reports"].get("DEMO", [])
    if not reports or result["errors"] or not full_shot.exists():
        return {"error": "no picture", "errors": result["errors"][:sh.SHOWN_ERRORS], "log": str(folder / "shell.log")}
    if "error" in reports[-1]:
        return {"error": reports[-1]["error"], "log": str(folder / "shell.log")}
    x, y, cw, ch = reports[-1]["rect"]
    img = Image.open(full_shot)
    k = img.width / reports[-1]["scene"][0]  # device pixels per logical pixel
    box = [round((x - MARGIN) * k), round((y - MARGIN) * k), round((x + cw + MARGIN) * k), round((y + ch + MARGIN) * k)]
    target = out / f"{name}.png"
    img.crop(box).save(target, optimize=True)
    size = target.stat().st_size
    return {"picture": str(target), "pixels": list(Image.open(target).size), "bytes": size, "over_o8": size > MAX_BYTES}


def main() -> int:
    """Shoot every example (or ``--only`` one); print what was written."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=HERE.parent / "docs", help="where the pictures go (default: docs/)")
    parser.add_argument("--scale", type=float, default=1.5, help="screen scale (sharper pictures above 1)")
    parser.add_argument("--only", action="append", default=[], help="one example's name; repeat for several")
    args = parser.parse_args()
    why_not = sh.missing()
    if why_not:
        print(f"SKIPPED: {why_not}")
        return 0
    names = args.only or list(EXAMPLES)
    unknown = [n for n in names if n not in EXAMPLES]
    if unknown:
        parser.error(f"unknown example(s): {', '.join(unknown)}; known: {', '.join(EXAMPLES)}")
    args.out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="cu-demo-"))
    wallpaper = work / "gradient.png"
    gradient(wallpaper)
    done = {name: shoot(name, EXAMPLES[name], args.out, work, args.scale, wallpaper) for name in names}
    print(json.dumps({"work": str(work), "results": done}, indent=1))
    return 0 if all("picture" in r and not r["over_o8"] for r in done.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
