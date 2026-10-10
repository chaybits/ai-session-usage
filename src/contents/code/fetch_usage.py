#!/usr/bin/env python3
"""Fetch one provider's usage limits for the AI Session Usage widget and print one JSON object.

Usage: fetch_usage.py [--provider claude|codex] [--source claudecode|statusline] [--claude PROGRAM]
                      [--codex PROGRAM] [login-file]

No login is read here and nothing is asked of Anthropic or OpenAI by this program: each CLI is asked for its own
usage, with its own login, over its own protocol. ``claude`` (the default provider): with ``--source claudecode``
(the default) Claude Code itself is asked, headless (``usage_claudecode``; ``--claude`` names the program when it
is not ``claude`` on the PATH); with ``--source statusline`` the limits come from the file ``statusline_tap.py``
writes from Claude Code's own status line (``usage_statusline``). ``codex``: Codex's app server is asked
(``usage_codex``; ``--codex`` names the program). Either login file is only checked for existence: with none,
the provider is left out. No login is ever refreshed by anyone but its own CLI.

Exit status is always 0 and stdout is always one pure-ASCII JSON line; the outcome is in the JSON
(``ok``, ``error``, ``message``). No token appears in any output, on any path: none is ever read.

The output also carries fields the widget does not read (``fetched_at``, ``source``, ``plan``,
per-row ``kind`` and ``provider``); they are there for running this by hand.
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
# Claude's sources; the first is the default. Codex has one way. Asking either service's usage endpoint with the
# CLI's login is gone (D18, D20).
SOURCES = ("claudecode", "statusline")
PROGRAM_OPTIONS = {"--claude": "claude", "--codex": "codex"}


def parse_args(argv: list[str]) -> tuple[str, str | None, str | None, Path | None]:
    """
    Read ``[--provider NAME] [--source NAME] [--claude PROGRAM] [--codex PROGRAM] [login-file]`` by hand
    (argparse would exit 2 and break the contract).

    Args:
        argv: The arguments after the script name.

    Returns:
        ``(provider, source_or_None, program_or_None, path_or_None)``: the source is None for Codex, and the
        default one for Claude when none was given; the program is the CLI setting for that provider.

    Raises:
        ValueError: An unknown provider or source, a missing name, a source or a program for the wrong
            provider, or an extra argument.
    """
    provider, source, program, rest = "claude", None, None, list(argv)
    if rest[:1] == ["--provider"]:
        if len(rest) < 2 or rest[1] not in PROVIDERS:
            raise ValueError(f"unknown provider {rest[1] if len(rest) > 1 else ''!r}; use claude or codex")
        provider, rest = rest[1], rest[2:]
    if rest[:1] == ["--source"]:
        if len(rest) < 2 or rest[1] not in SOURCES:
            raise ValueError(f"unknown source {rest[1] if len(rest) > 1 else ''!r}; use one of {', '.join(SOURCES)}")
        if provider != "claude":
            raise ValueError("only Claude Code has a source")
        source, rest = rest[1], rest[2:]
    if rest[:1] and rest[0] in PROGRAM_OPTIONS:
        if len(rest) < 2 or not rest[1]:
            raise ValueError(f"{rest[0]} needs a program")
        if PROGRAM_OPTIONS[rest[0]] != provider:
            raise ValueError(f"{rest[0]} names the program of another provider than {provider}")
        program, rest = rest[1], rest[2:]
    if len(rest) > 1:
        raise ValueError("too many arguments")
    path = Path(os.path.expanduser(rest[0])) if rest and rest[0] else None
    if provider == "claude" and source is None:
        source = SOURCES[0]
    return provider, source, program, path


def main() -> None:
    """Fetch the usage once and print the JSON result."""
    try:
        provider, source, program, path = parse_args(sys.argv[1:])
    except ValueError as exc:
        emit({"ok": False, "error": "usage", "message": str(exc)})
    if provider == "codex":
        result = usage_codex.run(path, program)
    elif source == "statusline":
        result = usage_statusline.run(path)
    else:
        result = usage_claudecode.run(path, program)
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
