"""A throwaway plasmashell inside a headless KWin, for the checks that need a real containment.

KWin's virtual backend (no screen, no input devices; plasmashell crashes on the offscreen platform) runs
plasmashell on a private D-Bus, with HOME, every XDG dir, CLAUDE_CONFIG_DIR and CODEX_HOME inside a sandbox
folder whose Plasma config the caller writes: a panel, or a desktop with the widget placed on it. The widget
copy answers from a stub helper (no login is read, no request is made), and a probe the caller injects into its
main.qml prints tagged JSON lines (``CU-<TAG> {...}``). A run ends when the caller's last tag appears, or at
its deadline.

Shared by panel_check.py (the panel form), test_desktop.py (mouse input on the desktop) and demo_shots.py
(pictures over a wallpaper).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import time
from pathlib import Path

import test_qml_load as q  # the package path, the stubs and the sandbox helpers are shared with the load tests

TOOLS = ("plasmashell", "kwin_wayland", "dbus-run-session")
# The D-Bus service whose program plasmashell needs running before it loads (see session_command()).
ACTIVITY_SERVICE = "org.kde.ActivityManager.service"
# KWin's virtual output. Its --scale flag only multiplies the mode, and with no saved output config KWin picks
# scale 1 itself; the scale is set the way KWin keeps it, in kwinoutputconfig.json, written before it starts.
OUTPUT = "Virtual-0"
# A healthy run ends as soon as its last tag is printed; this only bounds a run that hangs.
DEADLINE_S = 60
# How often the log is read for the tags while the shell runs.
POLL_S = 0.5
TAG = re.compile(r"CU-([A-Z0-9-]+) (\{.*\})")
# A summary shows this many of a run's error lines; the full list is in its shell log.
SHOWN_ERRORS = 5
# QML a probe needs on the desktop, inserted with it: the desktop's container around the widget (it owns the
# edit mode and the resize handles; found by what it has, as the desktop's QML does not name it), and a search
# of an item tree. Probes use them as root.__container() and root.__findAll(item, test, []).
PROBE_HELPERS = """
    function __container() {
        for (let p = root.parent; p; p = p.parent) {
            if (typeof p.editMode === "boolean" && p.configOverlayItem !== undefined) {
                return p
            }
        }
        return null
    }
    function __findAll(item, test, out) {
        if (!item) {
            return out
        }
        if (test(item)) {
            out.push(item)
        }
        for (let i = 0; i < item.children.length; i++) {
            __findAll(item.children[i], test, out)
        }
        return out
    }
"""
# The applet's id inside the sandbox's Plasma config; any number works, the callers' probes do not read it.
APPLET = 3
# Plasma shows a desktop only for an activity: with an empty activityId it makes a desktop of its own and never
# loads the one written here. The sandbox's activity daemon is given this one activity as the current one.
ACTIVITY = "6f0c2a4e-0b1d-4c3e-9a7f-5d2b8e1c4a90"
KACTIVITYMANAGERDRC = f"""[activities]
{ACTIVITY}=Default

[main]
currentActivity={ACTIVITY}
"""

# A desktop (the Folder View containment, as on a stock Plasma desktop) holding only this widget, at a
# position and size of the caller's choosing.
# The geometry keys sit in the containment's own group (as Plasma writes them), not in its [General].
GEOMETRY_KEYS = """ItemGeometries-%(screen_w)dx%(screen_h)d=Applet-%(applet)d:%(x)d,%(y)d,%(w)d,%(h)d,0;
ItemGeometriesHorizontal=Applet-%(applet)d:%(x)d,%(y)d,%(w)d,%(h)d,0;
ItemGeometriesVertical=Applet-%(applet)d:%(x)d,%(y)d,%(w)d,%(h)d,0;
"""
DESKTOP = """[Containments][1]
%(geometry)sactivityId=%(activity)s
formfactor=0
immutability=1
lastScreen=0
location=0
plugin=org.kde.plasma.folder
wallpaperplugin=%(wallpaper_plugin)s
%(wallpaper)s
[Containments][1][Applets][%(applet)d]
immutability=1
plugin=%(plugin)s
%(applet_config)s"""


def activity_daemon() -> str | None:
    """The activity daemon's program, from its D-Bus service file (/usr/lib on Arch, /usr/libexec elsewhere)."""
    dirs = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    for base in dirs.split(":"):
        service = Path(base) / "dbus-1/services" / ACTIVITY_SERVICE
        if service.is_file():
            for line in service.read_text(encoding="utf-8").splitlines():
                if line.startswith("Exec="):
                    return line[len("Exec="):].strip()
    return None


def missing() -> str | None:
    """Why a shell cannot be started on this machine, or None when it can."""
    absent = [tool for tool in TOOLS if not shutil.which(tool)]
    if absent:
        return "not found: " + ", ".join(absent)
    if activity_daemon() is None:
        return f"no {ACTIVITY_SERVICE} D-Bus service file, so plasmashell cannot load"
    return None


def session_command(daemon: str) -> str:
    """The session KWin runs. The activity daemon is started here, inside the compositor: started by D-Bus
    on demand it would lack the compositor socket, fail to open a display, and plasmashell would abort."""
    return f"sh -c '{daemon} & sleep 1; exec plasmashell --no-respawn'"


def config_groups(prefix: str, groups: dict[str, dict[str, str]]) -> str:
    """Plasma config text for nested groups: ``{"": {...}, "Appearance": {...}}`` under ``prefix``."""
    out = []
    for name, entries in groups.items():
        out.append(prefix + (f"[{name}]" if name else ""))
        out.extend(f"{key}={value}" for key, value in entries.items())
        out.append("")
    return "\n".join(out)


def desktop_appletsrc(geometry: tuple[int, int, int, int] | None, screen: tuple[int, int], *,
                      applet_config: dict[str, dict[str, str]] | None = None, wallpaper: str | None = None) -> str:
    """The Plasma config of a desktop with only this widget, at ``geometry`` = (x, y, width, height) in
    logical pixels on a ``screen`` of that logical size (the desktop reads the geometry stored for its own
    size first), or with no saved geometry (None), as a widget just added is. ``wallpaper`` is an image file
    (the image wallpaper), or None for a plain colour."""
    x, y, w, h = geometry or (0, 0, 0, 0)
    prefix = f"[Containments][1][Applets][{APPLET}][Configuration]"
    if wallpaper:
        plugin = "org.kde.image"
        paper = config_groups("[Containments][1][Wallpaper][org.kde.image]", {"General": {"Image": f"file://{wallpaper}"}})
    else:
        plugin, paper = "org.kde.color", ""
    keys = GEOMETRY_KEYS % {"applet": APPLET, "x": x, "y": y, "w": w, "h": h, "screen_w": screen[0],
                            "screen_h": screen[1]} if geometry else ""
    return DESKTOP % {"applet": APPLET, "activity": ACTIVITY, "plugin": q.PLUGIN_ID, "geometry": keys,
                      "wallpaper_plugin": plugin, "wallpaper": paper,
                      "applet_config": config_groups(prefix, applet_config or {})}


def prepare(out: Path, appletsrc: str, probe: str, stub: str, *, plasmashellrc: str = "",
            imports: tuple[str, ...] = (), defaults: dict[str, str] | None = None,
            replace: tuple[tuple[str, str, str], ...] = ()) -> Path:
    """Write a fresh sandbox under ``out``: the Plasma config, and a copy of the package with the probe
    injected, ``imports`` added to main.qml, setting ``defaults`` changed, each ``replace`` = (file under
    contents/, old, new) applied once, and ``stub`` as its helper. Returns the sandbox folder."""
    sandbox = out / "sandbox"
    shutil.rmtree(sandbox, ignore_errors=True)
    for sub in ("config", "cache", "state", "data/plasma/plasmoids", "home/.codex", "home/Desktop"):
        (sandbox / sub).mkdir(parents=True)
    (sandbox / "run").mkdir(mode=0o700)
    (sandbox / "home").chmod(0o700)
    (sandbox / "config/plasma-org.kde.plasma.desktop-appletsrc").write_text(appletsrc, encoding="utf-8")
    (sandbox / "config/kactivitymanagerdrc").write_text(KACTIVITYMANAGERDRC, encoding="utf-8")
    if plasmashellrc:
        (sandbox / "config/plasmashellrc").write_text(plasmashellrc, encoding="utf-8")
    pkg = sandbox / "data/plasma/plasmoids" / q.PLUGIN_ID
    shutil.copytree(q.PKG, pkg, ignore=shutil.ignore_patterns("__pycache__"))
    main = pkg / "contents/ui/main.qml"
    q._replace_once(main, q.ANCHOR, PROBE_HELPERS + probe + q.ANCHOR)
    for line in imports:
        q._replace_once(main, "import QtQuick\n", f"import QtQuick\n{line}\n")
    for entry, value in (defaults or {}).items():
        q._set_default(pkg / "contents/config/main.xml", entry, value)
    for rel, old, new in replace:
        q._replace_once(pkg / "contents" / rel, old, new)
    (pkg / "contents/code/fetch_usage.py").write_text(stub, encoding="utf-8")
    return sandbox


def logical_size(size: tuple[int, int], scale: float) -> tuple[int, int]:
    """The desktop's size in logical pixels on a screen of ``size`` device pixels at ``scale``."""
    return round(size[0] / scale), round(size[1] / scale)


def run(sandbox: Path, log_path: Path, until: str, *, size: tuple[int, int] = (1280, 800), scale: float = 1.0,
        deadline_s: float = DEADLINE_S, locale: str = "en_GB.UTF-8", extra_env: dict[str, str] | None = None) -> dict:
    """Run the shell in ``sandbox`` until a line tagged ``CU-<until>`` is printed, or the deadline.

    ``size`` is the virtual screen in device pixels and ``scale`` its scale factor (1.5 gives a 1280 x 800
    desktop on a 1920 x 1200 screen; ``logical_size()`` says which). Returns ``{"reports": {tag: [dict, ...]}, "errors": [lines],
    "finished": bool}``: every tagged line in order, and the lines naming this widget that mean its QML failed.
    ``extra_env`` is added to the shell's environment (a Qt switch for an experiment, say).
    """
    daemon = activity_daemon()
    if daemon is None:
        raise RuntimeError(f"no {ACTIVITY_SERVICE}; call missing() first")
    env = {k: v for k, v in os.environ.items()
           if k not in ("DBUS_SESSION_BUS_ADDRESS", "DISPLAY", "WAYLAND_DISPLAY", "QT_QPA_PLATFORM")
           and not k.startswith("LC_")}
    env.update(HOME=str(sandbox / "home"), CLAUDE_CONFIG_DIR=str(sandbox / "home/.claude"),
               CODEX_HOME=str(sandbox / "home/.codex"), XDG_RUNTIME_DIR=str(sandbox / "run"),
               XDG_DATA_HOME=str(sandbox / "data"), XDG_CONFIG_HOME=str(sandbox / "config"),
               XDG_CACHE_HOME=str(sandbox / "cache"), XDG_STATE_HOME=str(sandbox / "state"),
               QT_QPA_PLATFORMTHEME="kde", QT_FORCE_STDERR_LOGGING="1", QML_DISABLE_DISK_CACHE="1",
               PYTHONDONTWRITEBYTECODE="1", LANG=locale, LC_ALL=locale,
               # system folders only: nothing a test starts can find the real Claude Code (~/.local/bin)
               PATH="/usr/local/bin:/usr/bin:/bin")
    env.update(extra_env or {})
    width, height = size
    output_config = [
        {"name": "outputs", "data": [{"connectorName": OUTPUT, "scale": scale,
                                      "mode": {"width": width, "height": height, "refreshRate": 60000, "flags": 1}}]},
        {"name": "setups", "data": [{"lidClosed": False, "outputs": [
            {"enabled": True, "outputIndex": 0, "position": {"x": 0, "y": 0}, "priority": 1, "replicationSource": ""}]}]},
    ]
    (sandbox / "config/kwinoutputconfig.json").write_text(json.dumps(output_config, indent=1), encoding="utf-8")
    marker = re.compile(rf"CU-{re.escape(until)} ")
    finished = False
    with open(log_path, "w", encoding="utf-8") as log:
        proc = subprocess.Popen(["dbus-run-session", "--", "kwin_wayland", "--virtual", "--no-lockscreen",
                                 "--width", str(width), "--height", str(height),
                                 "--socket", "ai-session-usage-check", "--exit-with-session", session_command(daemon)],
                                env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        deadline = time.monotonic() + deadline_s
        try:
            while time.monotonic() < deadline and proc.poll() is None:
                time.sleep(POLL_S)
                if marker.search(log_path.read_text(encoding="utf-8", errors="replace")):
                    finished = True
                    break
        finally:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=10)
    text = log_path.read_text(encoding="utf-8", errors="replace")
    reports: dict[str, list[dict]] = {}
    for match in TAG.finditer(text):
        reports.setdefault(match.group(1), []).append(json.loads(match.group(2)))
    errors = [line for line in text.splitlines() if q.QML_ERROR.search(line) and q.PLUGIN_ID in line]
    return {"reports": reports, "errors": errors, "finished": finished}
