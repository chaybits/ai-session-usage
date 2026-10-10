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
from usage_claude import WINDOWS, describe
from usage_common import is_number, iso_from_epoch, make_row, unique_ids

PROVIDER = "claude"
APP_DIR = "ai-session-usage"
FILE_NAME = "claude-statusline.json"
# A window Claude Code stops mentioning (it drops one once its reset time passes) is kept in the file, shown
# with "Reset at" and 0 % (effective_percent), until this long after that reset; then it is forgotten (a limit
# that no longer applies). The window table (key -> row id, group, label) is usage_claude.WINDOWS, shared with
# the Claude Code source so a row keeps its id whichever source the widget uses.
FORGET_AFTER_S = 8 * 86400


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


def effective_percent(w: dict, now: float) -> float:
    """
    The percentage a kept window stands at now.

    Args:
        w: A window with a numeric ``used_percentage`` (and ``resets_at`` in Unix seconds, when known).
        now: Unix seconds.

    Returns:
        What Claude Code last reported, or 0 once the window's reset time has passed: the window is kept so the
        row still shows "Reset at", but its old number is no longer true (the limit has reset).
    """
    reset = w.get("resets_at")
    if is_number(reset) and reset <= now:
        return 0.0
    return float(w["used_percentage"])


def rows_from(windows: dict, now: float | None = None) -> list[dict]:
    """
    Turn the kept windows into display rows: the known ones in WINDOWS order, then any other.

    Args:
        windows: The file's ``rate_limits``.
        now: Unix seconds (the clock, when None); a window whose reset has passed is a row at 0 %.

    Returns:
        Rows; a window without a numeric ``used_percentage`` is skipped.
    """
    now = time.time() if now is None else now
    order = list(WINDOWS)
    keys = sorted(windows, key=lambda k: order.index(k) if k in order else len(order))
    rows = []
    for key in keys:
        w = windows[key]
        if not isinstance(w, dict) or not is_number(w.get("used_percentage")):
            continue
        row_id, group, label = describe(key)
        rows.append(make_row(PROVIDER, row_id, key, group, label, effective_percent(w, now),
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
    # the login first: a status file left behind by /logout must not keep the section alive (D4)
    login = credentials or usage_claude.default_credentials()
    if not login.exists():
        return {"ok": False, "error": "nologin", "message": f"{login} not found"}
    path = path or status_file()
    if not path.is_file():
        return {"ok": False, "error": "nostatusline", "message": str(path)}
    try:
        data = read_file(path)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return {"ok": False, "error": "unreadable", "message": f"{path}: {type(exc).__name__}"}
    now = time.time()
    rows = rows_from(data["rate_limits"], now)
    if not rows:
        return {"ok": False, "error": "nostatusline", "message": f"{path}: no limits yet"}
    return {"ok": True, "source": "statusline", "captured_at": int(data["captured_at"]), "fetched_at": int(now),
            "rows": rows}
