"""ChatGPT (Codex) usage limits, asked of Codex itself: no login read here, nothing asked of OpenAI by this program.

Codex's app server (``codex app-server``: JSON lines over stdio, the protocol its own editor extension speaks)
answers ``account/rateLimits/read`` with the plan's windows, per metered limit: the numbers Codex's own
``/status`` shows. This module starts it headless, sends ``initialize``, ``initialized`` and that one request,
reads the answer and closes the connection, on which the server exits. OpenAI marks the app server experimental
(``codex app-server --help``), so its shape may change; a change shows as "Unexpected answer". The token never
leaves Codex. Until 2026-10-08 this module read the token from ``auth.json`` and asked OpenAI's usage endpoint
itself; that source is gone (docs/ARCHITECTURE.md D20; the git tag ``codex-endpoint-source-last`` and
``archive/codex-endpoint-source-20261008/`` keep it).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from usage_common import (MAX_MESSAGE_CHARS, ask_cli, find_program, is_number, iso_from_epoch, make_row,
                          package_version, str_or, unique_ids)
PROVIDER = "codex"
# Bounds the whole Codex run (it answers in well under a second); the widget's watchdog (60 s) bounds the helper.
TIMEOUT_S = 30
CLIENT_NAME = "ai-session-usage"
# The id of our one request; the server echoes it on the answer.
REQUEST_ID = 2
SECONDS_PER_DAY = 86_400
# The plan's own limit carries this id in the answer. Its rows keep the ids the widget has always used for the
# plan's windows (codex:primary, codex:secondary), so hidden or moved rows carry over from earlier versions.
PLAN_LIMIT_ID = "codex"
# The two windows a limit carries, in the order Codex shows them.
WINDOW_SLOTS = (("primary", "primary"), ("secondary", "secondary"))


def default_auth() -> Path:
    """
    Return the login file Codex uses (only ever checked for existence here).

    Returns:
        ``$CODEX_HOME/auth.json``, or ``~/.codex/auth.json``.
    """
    base = os.environ.get("CODEX_HOME") or os.path.expanduser("~/.codex")
    return Path(base) / "auth.json"


def window_label(seconds: object) -> tuple[str, str]:
    """
    Name a limit window by its length, matching the Claude rows' wording.

    Args:
        seconds: The window's length in seconds.

    Returns:
        ``(group, label)``: ``session`` and "Session (5hr)" under a day; ``weekly`` and "Weekly (7 day)"
        or "N-day" from a day up; ``("", "Limit")`` when the length is unknown.
    """
    if not is_number(seconds) or seconds <= 0:
        return "", "Limit"
    if seconds < 3600:
        return "session", f"Session ({round(seconds / 60)}min)"
    if seconds < SECONDS_PER_DAY:
        return "session", f"Session ({round(seconds / 3600)}hr)"
    days = round(seconds / SECONDS_PER_DAY)
    if days == 7:
        return "weekly", "Weekly (7 day)"
    if 28 <= days <= 31:  # the free plan's window (30 days, seen 2026-10-05 and 2026-10-08)
        return "weekly", f"Monthly ({days} day)"
    return "weekly", f"{days}-day"


def window_rows(snapshot: dict, id_prefix: str, suffix: str | None) -> list[dict]:
    """
    Turn one limit's snapshot (a primary and a secondary window) into rows.

    Args:
        snapshot: ``{primary: {usedPercent, windowDurationMins, resetsAt}, secondary: {...} | null, ...}``.
        id_prefix: Prefix of the row ids ("" for the plan's own limit).
        suffix: Text added to the label in parentheses (the name of another metered limit), or None.

    Returns:
        Zero to two rows.
    """
    rows: list[dict] = []
    for key, short in WINDOW_SLOTS:
        window = snapshot.get(key)
        if not isinstance(window, dict) or not is_number(window.get("usedPercent")):
            continue
        minutes = window.get("windowDurationMins")
        group, label = window_label(minutes * 60 if is_number(minutes) else None)
        if suffix:
            label = f"{label} ({suffix})"
        rows.append(make_row(PROVIDER, f"{id_prefix}{short}", short, group, label, window["usedPercent"],
                             iso_from_epoch(window.get("resetsAt"))))
    return rows


def rows_from_answer(result: dict) -> tuple[list[dict], str | None]:
    """
    Turn the ``account/rateLimits/read`` result into display rows, and read the plan type.

    Args:
        result: The answer's ``result``: ``rateLimits`` (the plan's own limit, with ``planType``) and, when
            present, ``rateLimitsByLimitId`` (every metered limit, keyed by its id, the plan's among them).

    Returns:
        ``(rows, plan)``: the plan's own windows first, then each other limit's in the server's order, named
        after it; ``rows`` is empty when no window has a number.
    """
    main = result.get("rateLimits") if isinstance(result.get("rateLimits"), dict) else {}
    by_id = result.get("rateLimitsByLimitId")
    if isinstance(by_id, dict) and by_id:
        snapshots = {str(limit_id): snap for limit_id, snap in by_id.items() if isinstance(snap, dict)}
    elif main:
        snapshots = {str_or(main.get("limitId"), None) or PLAN_LIMIT_ID: main}
    else:
        snapshots = {}
    rows: list[dict] = []
    for limit_id in sorted(snapshots, key=lambda key: key != PLAN_LIMIT_ID):  # stable: the plan first
        snapshot = snapshots[limit_id]
        if limit_id == PLAN_LIMIT_ID:
            rows.extend(window_rows(snapshot, "", None))
        else:
            rows.extend(window_rows(snapshot, f"{limit_id}:", str_or(snapshot.get("limitName"), None) or limit_id))
    return unique_ids(rows), str_or(main.get("planType"), None)


def fallbacks() -> tuple[Path, ...]:
    """
    Where Codex's installers put it, for a PATH that lacks it.

    Returns:
        ``~/.local/bin/codex``, npm's global ``codex``, and on Windows npm's ``codex.cmd`` under APPDATA, the last
        only when APPDATA is set, so that no candidate is ever a relative path (Popen would resolve one against
        the helper's working folder).
    """
    home = Path.home()
    found = [home / ".local/bin/codex", home / ".npm-global/bin/codex"]
    appdata = os.environ.get("APPDATA")
    if appdata:
        found.append(Path(appdata) / "npm/codex.cmd")
    return tuple(found)


def run(auth: Path | None, command: str | None = None) -> dict:
    """
    Produce the result for the widget by asking Codex.

    Args:
        auth: Codex's login file (or None for its default). Only whether it exists is checked, never its
            content: with no Codex login the provider is left out of the widget, and Codex is not started.
        command: The Codex program setting, or None.

    Returns:
        The result object for ``emit``.
    """
    login = auth or default_auth()
    if not login.exists():
        return {"ok": False, "error": "nologin", "message": f"{login} not found"}
    exe = find_program(command, "codex", fallbacks())
    if exe is None:
        return {"ok": False, "error": "nocli", "message": command or "codex"}
    requests = [
        json.dumps({"id": 1, "method": "initialize",
                    "params": {"clientInfo": {"name": CLIENT_NAME, "version": package_version()}}}),
        json.dumps({"method": "initialized"}),
        json.dumps({"id": REQUEST_ID, "method": "account/rateLimits/read"}),
    ]
    try:
        done = ask_cli([exe, "app-server"], requests, lambda message: message.get("id") == REQUEST_ID, TIMEOUT_S,
                       close_stdin_first=False)
    except OSError as exc:
        return {"ok": False, "error": "nocli", "message": f"{exe}: {type(exc).__name__}"}
    if done.timed_out:
        return {"ok": False, "error": "cli", "message": f"no answer within {TIMEOUT_S} s"}
    if done.answer is None:
        return {"ok": False, "error": "cli", "message": f"exit {done.returncode}: {done.tail()}".strip()}
    if "error" in done.answer:
        error = done.answer["error"]
        message = error.get("message") if isinstance(error, dict) else error
        return {"ok": False, "error": "cli", "message": (str_or(message, None) or "error")[:MAX_MESSAGE_CHARS]}
    result = done.answer.get("result") if isinstance(done.answer.get("result"), dict) else {}
    rows, plan = rows_from_answer(result)
    if not rows:
        return {"ok": False, "error": "format", "message": "no rate limit windows in Codex's answer"}
    return {"ok": True, "source": "codex", "fetched_at": int(time.time()), "plan": plan, "rows": rows}
