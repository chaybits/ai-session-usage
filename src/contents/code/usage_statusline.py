"""Claude Code's usage limits as Claude Code itself received them: no login read, no request made.

Claude Code hands its status-line command a JSON description of the session, which for Pro and Max subscribers
includes ``rate_limits``: ``five_hour`` and ``seven_day``, each with ``used_percentage`` (0 to 100) and
``resets_at`` (Unix seconds), after the session's first answer from the server
(https://code.claude.com/docs/en/statusline). ``statusline_tap.py``, set as that command, keeps only
``rate_limits`` and the time it saw them, in one small file; this module turns the file into rows. The numbers
are as fresh as Claude Code's last answer: with no session running they stay where they were, and the result
says when they were seen (``captured_at``) so the widget can show their age.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import usage_claude
from usage_common import is_number, iso_from_epoch, make_row, unique_ids

PROVIDER = "claude"
APP_DIR = "ai-session-usage"
FILE_NAME = "claude-statusline.json"
# A window Claude Code stops mentioning (it drops one once its reset time passes) is kept in the file, shown
# with "Reset at", until this long after that reset; then it is forgotten (a limit that no longer applies).
FORGET_AFTER_S = 8 * 86400
# Known windows -> (row id, group, label), in display order. The ids are usage_claude's (the ones Claude Code's
# answer gives), so a row hidden or moved in the settings stays that row whichever source the widget uses.
WINDOWS = {
    "five_hour": ("session", "session", "Session (5hr)"),
    "seven_day": ("weekly_all", "weekly", "Weekly (7 day)"),
    "seven_day_opus": ("weekly_scoped:Opus", "weekly", "Weekly (Opus)"),
    "seven_day_sonnet": ("weekly_scoped:Sonnet", "weekly", "Weekly (Sonnet)"),
    "spend_limit": ("spend_limit", "weekly", "Spend limit"),
}


def status_file() -> Path:
    """
    The file the tap writes and the widget reads, in the user's cache folder.

    Returns:
        ``$XDG_CACHE_HOME`` (or ``%LOCALAPPDATA%`` on Windows, else ``~/.cache``) ``/ai-session-usage/
        claude-statusline.json``.
    """
    base = os.environ.get("XDG_CACHE_HOME") or (os.environ.get("LOCALAPPDATA") if sys.platform == "win32" else None)
    root = Path(base) if base else Path.home() / ".cache"
    return root / APP_DIR / FILE_NAME


def describe(key: str) -> tuple[str, str, str]:
    """
    The row id, group and label of a window.

    Args:
        key: The window's name in ``rate_limits`` (``five_hour``, ``seven_day``, ``seven_day_opus``, ...).

    Returns:
        ``(row_id, group, label)``; a window not in WINDOWS is shown under its own name.
    """
    if key in WINDOWS:
        return WINDOWS[key]
    if key.startswith("seven_day_"):
        name = key[len("seven_day_"):].replace("_", " ")
        return f"weekly_scoped:{name}", "weekly", f"Weekly ({name})"
    return key, "session" if key.startswith("five_hour") else "weekly", key.replace("_", " ").capitalize()


def rows_from(windows: dict) -> list[dict]:
    """
    Turn the kept windows into display rows: the known ones in WINDOWS order, then any other.

    Args:
        windows: The file's ``rate_limits``.

    Returns:
        Rows; a window without a numeric ``used_percentage`` is skipped.
    """
    order = list(WINDOWS)
    keys = sorted(windows, key=lambda k: order.index(k) if k in order else len(order))
    rows = []
    for key in keys:
        w = windows[key]
        if not isinstance(w, dict) or not is_number(w.get("used_percentage")):
            continue
        row_id, group, label = describe(key)
        rows.append(make_row(PROVIDER, row_id, key, group, label, w["used_percentage"],
                             iso_from_epoch(w.get("resets_at"))))
    return unique_ids(rows)


def merge(previous: dict, new: dict, now: float) -> dict:
    """
    The windows to keep after Claude Code reported ``new``.

    Args:
        previous: The windows already in the file.
        new: The windows Claude Code just reported.
        now: Unix seconds.

    Returns:
        ``new``, plus each earlier window it no longer mentions until FORGET_AFTER_S after that window's reset.
    """
    kept = {}
    for key, w in previous.items():
        if key in new or not isinstance(w, dict):
            continue
        reset = w.get("resets_at")
        if is_number(reset) and now - reset > FORGET_AFTER_S:
            continue
        kept[key] = w
    kept.update({key: w for key, w in new.items() if isinstance(w, dict)})
    return kept


def read_file(path: Path) -> dict:
    """
    Read the status file.

    Args:
        path: The file.

    Returns:
        ``{"rate_limits": dict, "captured_at": number}``.

    Raises:
        OSError, UnicodeDecodeError, ValueError: The file cannot be read, or is not a status file.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("rate_limits"), dict) or not is_number(data.get("captured_at")):
        raise ValueError("not a status file")
    return data


def run(credentials: Path | None, path: Path | None = None) -> dict:
    """
    Produce the result for the widget from the status file.

    Args:
        credentials: Claude Code's credentials file (or None for its default). Only whether it exists is
            checked, never its content: with no Claude Code login the provider is left out of the widget.
        path: The status file, or None for ``status_file()``.

    Returns:
        The result object for ``emit``.
    """
    path = path or status_file()
    if not path.is_file():
        login = credentials or usage_claude.default_credentials()
        if not login.exists():
            return {"ok": False, "error": "nologin", "message": f"{login} not found"}
        return {"ok": False, "error": "nostatusline", "message": str(path)}
    try:
        data = read_file(path)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return {"ok": False, "error": "unreadable", "message": f"{path}: {type(exc).__name__}"}
    rows = rows_from(data["rate_limits"])
    if not rows:
        return {"ok": False, "error": "nostatusline", "message": f"{path}: no limits yet"}
    return {"ok": True, "status": 200, "source": "statusline", "captured_at": int(data["captured_at"]),
            "fetched_at": int(time.time()), "rows": rows}
