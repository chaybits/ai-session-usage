#!/usr/bin/env python3
"""Fetch one provider's usage limits for the AI Session Usage widget and print one JSON object.

Usage: fetch_usage.py [--provider claude|codex] [--source claudecode|statusline] [--claude PROGRAM] [login-file]

``claude`` (the default provider) never reads its login here. With ``--source claudecode`` (the default) Claude
Code itself is asked, headless, for its usage (``usage_claudecode``; ``--claude`` names the program when it is
not ``claude`` on the PATH). With ``--source statusline`` the limits come from the file ``statusline_tap.py``
writes from Claude Code's own status line (``usage_statusline``). Either way the login file is only checked for
existence: with none, the provider is left out. ``codex`` reads the Codex CLI's ``auth.json`` (ChatGPT login)
and asks the endpoint Codex's own ``/status`` reads (``usage_codex``); it has no ``--source``. No login is ever
refreshed here: each CLI refreshes its own, and a second client doing so can log it out. An expired Codex token
is reported as ``expired`` without a request.

Exit status is always 0 and stdout is always one pure-ASCII JSON line; the outcome is in the JSON
(``ok``, ``error``, ``status``). No token appears in any output, on any path.

The output also carries fields the widget does not read (``fetched_at``, ``expires_at``, ``source``,
``status``, ``plan``, per-row ``kind`` and ``provider``); they are there for running this by hand.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import usage_claudecode
import usage_codex
import usage_statusline
from usage_common import emit

PROVIDERS = ("claude", "codex")
# Claude's sources; the first is the default. Asking the usage endpoint with Claude Code's login is gone (D18).
SOURCES = ("claudecode", "statusline")


def parse_args(argv: list[str]) -> tuple[str, str | None, str | None, Path | None]:
    """
    Read ``[--provider NAME] [--source NAME] [--claude PROGRAM] [login-file]`` by hand (argparse would exit 2
    and break the contract).

    Args:
        argv: The arguments after the script name.

    Returns:
        ``(provider, source_or_None, claude_program_or_None, path_or_None)``: the source is None for Codex, and
        the default one for Claude when none was given.

    Raises:
        ValueError: An unknown provider or source, a missing name, a source or a program for another provider
            than Claude, or an extra argument.
    """
    provider, source, claude, rest = "claude", None, None, list(argv)
    if rest[:1] == ["--provider"]:
        if len(rest) < 2 or rest[1] not in PROVIDERS:
            raise ValueError(f"unknown provider {rest[1] if len(rest) > 1 else ''!r}; use claude or codex")
        provider, rest = rest[1], rest[2:]
    if rest[:1] == ["--source"]:
        if len(rest) < 2 or rest[1] not in SOURCES:
            raise ValueError(f"unknown source {rest[1] if len(rest) > 1 else ''!r}; use one of {', '.join(SOURCES)}")
        source, rest = rest[1], rest[2:]
    if rest[:1] == ["--claude"]:
        if len(rest) < 2 or not rest[1]:
            raise ValueError("--claude needs a program")
        claude, rest = rest[1], rest[2:]
    if provider != "claude" and (source is not None or claude is not None):
        raise ValueError("only Claude Code has a source or a program")
    if len(rest) > 1:
        raise ValueError("too many arguments")
    path = Path(os.path.expanduser(rest[0])) if rest and rest[0] else None
    if provider == "claude" and source is None:
        source = SOURCES[0]
    return provider, source, claude, path


def main() -> None:
    """Fetch the usage once and print the JSON result."""
    try:
        provider, source, claude, path = parse_args(sys.argv[1:])
    except ValueError as exc:
        emit({"ok": False, "error": "usage", "message": str(exc)})
    if provider == "codex":
        result = usage_codex.run(path)
    elif source == "statusline":
        result = usage_statusline.run(path)
    else:
        result = usage_claudecode.run(path, claude)
    result["provider"] = provider
    emit(result)


def run() -> None:
    """Run ``main`` so the exit-0, one-JSON-line contract holds for any exception."""
    try:
        main()
    except Exception as exc:  # reported, not swallowed; the type name only, never str(exc)
        emit({"ok": False, "error": "internal", "message": type(exc).__name__})


if __name__ == "__main__":
    run()
