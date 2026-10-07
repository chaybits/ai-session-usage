#!/usr/bin/env python3
"""Claude Code status-line command that hands the subscription's usage limits to the AI Session Usage widget.

Set it as Claude Code's status line, in ``~/.claude/settings.json``:

    "statusLine": {"type": "command", "command": "python3 /path/to/statusline_tap.py"}

Claude Code runs it with a JSON description of the session on stdin. This keeps **only** ``rate_limits``
(the usage windows Claude Code received from the server) and the time it saw them, in a small file the widget
reads (``usage_statusline.status_file()``); nothing else of the session is written. It prints one short line
for the status bar ("5h 34% · 7d 61%").

Usage: statusline_tap.py [--quiet] [--then COMMAND]
    --quiet         print nothing (the file is still written)
    --then COMMAND  also run another status-line command with the same input and print its output, to keep
                    a status line set before

It never fails Claude Code's status line: on any problem it prints what it can, names the problem on stderr,
and exits 0.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import usage_statusline as sl  # noqa: E402  (the helper modules sit beside this file)

# A command given with --then may take this long; Claude Code cancels a slow status line anyway.
THEN_TIMEOUT_S = 5


def summary(windows: dict) -> str:
    """The status bar's text: the 5-hour and weekly percentages ("5h 34% · 7d 61%"), or "" when unknown."""
    parts = []
    for key, short in (("five_hour", "5h"), ("seven_day", "7d")):
        w = windows.get(key)
        if isinstance(w, dict) and sl.is_number(w.get("used_percentage")):
            parts.append(f"{short} {round(w['used_percentage'])}%")
    return " · ".join(parts)


def write_atomic(path: Path, data: dict) -> None:
    """Write ``data`` as JSON to ``path`` through a temporary file in the same folder, then rename it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tap-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def record(raw: str, path: Path, now: float) -> dict:
    """
    Keep the usage windows of one status-line input.

    Args:
        raw: What Claude Code wrote to stdin.
        path: The status file.
        now: Unix seconds.

    Returns:
        The windows now known (the file's, updated when the input carried any).
    """
    try:
        previous = sl.read_file(path)["rate_limits"] if path.is_file() else {}
    except (OSError, UnicodeDecodeError, ValueError):
        previous = {}
    try:
        incoming = json.loads(raw).get("rate_limits")
    except (ValueError, AttributeError):
        incoming = None
    if not isinstance(incoming, dict) or not any(isinstance(w, dict) for w in incoming.values()):
        return previous  # before the session's first answer there is nothing to keep
    windows = sl.merge(previous, incoming, now)
    write_atomic(path, {"captured_at": int(now), "rate_limits": windows})
    return windows


def parse_args(argv: list[str]) -> tuple[bool, str | None]:
    """Read ``[--quiet] [--then COMMAND]``; anything else is ignored (a status line must not fail on it)."""
    quiet, then, i = False, None, 0
    while i < len(argv):
        if argv[i] == "--quiet":
            quiet = True
        elif argv[i] == "--then" and i + 1 < len(argv):
            then = argv[i + 1]
            i += 1
        i += 1
    return quiet, then


def main() -> None:
    """Record the windows, print the status bar's line, and run the --then command if given."""
    quiet, then = parse_args(sys.argv[1:])
    raw = sys.stdin.read()
    windows = {}
    try:
        windows = record(raw, sl.status_file(), time.time())
    except OSError as exc:  # the file could not be written: the line is still printed
        print(f"statusline_tap: {type(exc).__name__}", file=sys.stderr)
    if not quiet:
        line = summary(windows)
        if line:
            print(line)
    if then:
        try:
            done = subprocess.run(then, shell=True, input=raw, capture_output=True, text=True, timeout=THEN_TIMEOUT_S)
            sys.stdout.write(done.stdout)
        except subprocess.TimeoutExpired:
            print("statusline_tap: --then timed out", file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # reported on stderr, not swallowed; a status line must not break Claude Code's
        print(f"statusline_tap: {type(exc).__name__}", file=sys.stderr)
    sys.exit(0)
