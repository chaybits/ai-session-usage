"""Shared parts of the usage helper: the output contract, how a CLI is found and asked, and value checks.

Each source module (``usage_claudecode``, ``usage_statusline``, ``usage_codex``) returns a result dict;
``fetch_usage.py`` prints it with ``emit``. Since 2026-10-08 (D18, D20) nothing here talks to a server or reads
a login: Claude Code and Codex are started and asked over their own protocols, and the login files are only
checked to exist. ``ask_cli`` is the one place a CLI is spawned: it bounds the run and, on a timeout, ends the
whole process group, since either CLI may be installed as a launcher script that starts the real program as a
child (a plain kill of the launcher would leave that child running).
"""
from __future__ import annotations

import json
import math
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from queue import Empty, Queue
from typing import Callable

# Display cap on an error message, so one odd reason cannot flood the status line.
MAX_MESSAGE_CHARS = 200
# After the answer, how long a CLI gets to exit by itself once its stdin is closed, before its group is ended.
EXIT_GRACE_S = 3


def package_version() -> str:
    """
    Return the package version, read from the package's ``metadata.json`` (the one place it is written).

    Returns:
        The version, or ``unknown`` when no copy can be read, which the tests would catch. In the Plasma package
        the file is two levels up (``src/metadata.json``); the Rainmeter package carries a copy beside the helper
        (``@Resources/code/metadata.json``, written by ``build_rmskin.py``).
    """
    here = Path(__file__).resolve().parent
    for meta in (here / "metadata.json", here.parents[1] / "metadata.json"):
        try:
            return str(json.loads(meta.read_text(encoding="utf-8"))["KPlugin"]["Version"])
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return "unknown"


def emit(payload: dict) -> None:
    """
    Print the result as one pure-ASCII JSON line and exit 0.

    Args:
        payload: Result object; ``fetched_at`` (epoch seconds) is added when missing.
    """
    payload.setdefault("fetched_at", int(time.time()))
    # ensure_ascii keeps stdout ASCII whatever the locale; QML's JSON.parse reads the escapes.
    # allow_nan=False: NaN and Infinity are not JSON; one slipping through raises, and the caller reports it.
    print(json.dumps(payload, ensure_ascii=True, allow_nan=False))
    sys.exit(0)


def is_number(value: object) -> bool:
    """Return True for a finite int or float; bools (an int subclass) and NaN or Infinity are refused."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:  # an int too large for a float
        return False


def str_or(value: object, default: str | None) -> str | None:
    """Return ``value`` when it is a string, else ``default``."""
    return value if isinstance(value, str) else default


def iso_from_epoch(seconds: object) -> str | None:
    """Return an ISO 8601 UTC time for epoch seconds, or None when the value is not a usable time."""
    if not is_number(seconds):
        return None
    try:
        return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):  # outside the platform's time range
        return None


def make_row(provider: str, row_id: str, kind: str, group: str, label: str, percent: float,
             resets_at: object) -> dict:
    """
    Build one display row; the single place the row shape is defined.

    Args:
        provider: ``claude`` or ``codex``.
        row_id: Stable id within the provider; the widget hides rows by ``<provider>:<row_id>``.
        kind: The server's own name for the limit.
        group: ``session`` (reset shown as a time) or anything else (shown with the weekday).
        label: Display text.
        percent: Used percentage.
        resets_at: ISO 8601 string, or anything else for "unknown".
    """
    return {"id": f"{provider}:{row_id}", "provider": provider, "kind": kind, "group": group,
            "label": label, "percent": float(percent), "resets_at": str_or(resets_at, None)}


def unique_ids(rows: list[dict]) -> list[dict]:
    """Make every row id unique by suffixing repeats (``#2``, ``#3``), so hiding one row hides only it."""
    seen: dict[str, int] = {}
    for row in rows:
        n = seen.get(row["id"], 0) + 1
        seen[row["id"]] = n
        if n > 1:
            row["id"] = f"{row['id']}#{n}"
    return rows


def find_program(command: str | None, name: str, fallbacks: tuple[Path, ...]) -> str | None:
    """
    Find the CLI to run.

    Args:
        command: The user's setting (a path or a program name), or None to look for ``name``.
        name: The program's name on the PATH.
        fallbacks: Places its installers use, tried when the PATH has nothing (a desktop's PATH may lack
            ``~/.local/bin``).

    Returns:
        Its path, or None when it cannot be found.
    """
    if command:
        path = Path(os.path.expanduser(command))
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
        return shutil.which(command)
    found = shutil.which(name)
    if found:
        return found
    for candidate in fallbacks:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


@dataclass
class CliRun:
    """What came back from a CLI: the awaited answer, and everything else for an error message."""

    answer: dict | None = None
    lines: list[str] = field(default_factory=list)
    stderr: str = ""
    returncode: int | None = None
    timed_out: bool = False

    def tail(self) -> str:
        """The last part of what the CLI said (stderr first), for an error message."""
        return (self.stderr or "\n".join(self.lines)).strip()[-MAX_MESSAGE_CHARS:]


def end_group(proc: subprocess.Popen) -> None:
    """End the CLI and anything it started (a launcher script's real program), on either platform."""
    try:
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, check=False)
    except OSError:  # already gone
        pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def ask_cli(argv: list[str], requests: list[str], is_answer: Callable[[dict], bool], timeout_s: float,
            close_stdin_first: bool) -> CliRun:
    """
    Start a CLI in the temp folder, send it JSON lines, and read its JSON lines until one is the answer.

    Args:
        argv: The program and its arguments.
        requests: The lines to send; this function adds the newlines.
        is_answer: ``is_answer(message)`` says whether a decoded line is the awaited one.
        timeout_s: Bound on the whole run; past it the CLI's process group is ended.
        close_stdin_first: Close stdin right after sending (Claude Code answers, then exits on the EOF);
            otherwise stdin stays open until the answer arrives (Codex's server exits on EOF without answering)
            and is closed then, on which the CLI is given ``EXIT_GRACE_S`` to exit by itself.

    Returns:
        The run; ``answer`` is None when the CLI exited or timed out without one.

    Raises:
        OSError: The program could not be started.
    """
    group = {"start_new_session": True} if os.name == "posix" else {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace", cwd=tempfile.gettempdir(), **group)
    lines: Queue = Queue()
    errors: list[str] = []

    def pump_stdout() -> None:
        for line in proc.stdout:
            lines.put(line)
        lines.put(None)  # EOF

    threading.Thread(target=pump_stdout, daemon=True).start()
    stderr_thread = threading.Thread(target=lambda: errors.append(proc.stderr.read()), daemon=True)
    stderr_thread.start()
    run = CliRun()
    try:
        proc.stdin.write("".join(request + "\n" for request in requests))
        proc.stdin.flush()
        if close_stdin_first:
            proc.stdin.close()
    except OSError:  # it exited at once; what it said is read below
        pass
    deadline = time.monotonic() + timeout_s
    while run.answer is None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            run.timed_out = True
            break
        try:
            line = lines.get(timeout=min(remaining, 0.5))
        except Empty:
            continue
        if line is None:  # EOF: the CLI is done talking
            break
        run.lines.append(line.rstrip("\n"))
        try:
            message = json.loads(line)
        except ValueError:
            continue
        if isinstance(message, dict) and is_answer(message):
            run.answer = message
    if not close_stdin_first:
        try:
            proc.stdin.close()
        except OSError:
            pass
    try:
        proc.wait(timeout=0 if run.timed_out else EXIT_GRACE_S)
    except subprocess.TimeoutExpired:
        end_group(proc)
    stderr_thread.join(timeout=1)
    run.returncode = proc.returncode
    run.stderr = errors[0] if errors else ""
    return run
