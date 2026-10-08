"""Claude Code's usage limits, asked of Claude Code itself: no login read here, no model request.

Claude Code answers an Agent SDK control request, ``get_usage``, with the full usage it fetches from Anthropic
with its own login: the session and weekly windows and every per-model cap (the same request the Claude Code
extension for VS Code sends for its usage panel; the SDK calls it
``usage_EXPERIMENTAL_MAY_CHANGE_DO_NOT_RELY_ON_THIS_API_YET``, so its shape may change, and a change shows as
"Unexpected answer"). This module starts Claude Code headless with that one request on stdin and nothing else:
no prompt (no usage is spent), hooks off, no MCP server, nothing saved as a session, in the temp folder. The
token never leaves Claude Code.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import usage_claude
from usage_common import ask_cli, find_program, str_or

PROVIDER = "claude"
# Bounds the whole Claude Code run (it takes about 2 s); the widget's watchdog (60 s) bounds the helper.
TIMEOUT_S = 40
REQUEST_ID = "ai-session-usage"
# Headless, one control request in and its answer out; no hooks (a SessionStart hook must not fire for a
# usage read), no MCP server started, no session written, no skills.
ARGS = ["-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
        "--no-session-persistence", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
        "--settings", '{"disableAllHooks":true}', "--disable-slash-commands"]
# Where Claude Code's installers put it, for a desktop whose PATH lacks ~/.local/bin (on Windows, claude.exe there).
FALLBACKS = (Path.home() / ".local/bin/claude", Path.home() / ".claude/local/claude",
             Path.home() / ".local/bin/claude.exe")


def is_our_answer(message: dict) -> bool:
    """Whether a decoded output line is the ``control_response`` to our request."""
    response = message.get("response")
    return (message.get("type") == "control_response" and isinstance(response, dict)
            and response.get("request_id") == REQUEST_ID)


def run(credentials: Path | None, command: str | None = None) -> dict:
    """
    Produce the result for the widget by asking Claude Code.

    Args:
        credentials: Claude Code's credentials file (or None for its default). Only whether it exists is
            checked, never its content: with no Claude Code login the provider is left out of the widget, and
            Claude Code is not started.
        command: The Claude Code program setting, or None.

    Returns:
        The result object for ``emit``.
    """
    login = credentials or usage_claude.default_credentials()
    if not login.exists():
        return {"ok": False, "error": "nologin", "message": f"{login} not found"}
    exe = find_program(command, "claude", FALLBACKS)
    if exe is None:
        return {"ok": False, "error": "nocli", "message": command or "claude"}
    request = json.dumps({"type": "control_request", "request_id": REQUEST_ID, "request": {"subtype": "get_usage"}})
    try:
        done = ask_cli([exe, *ARGS], [request], is_our_answer, TIMEOUT_S, close_stdin_first=True)
    except OSError as exc:
        return {"ok": False, "error": "nocli", "message": f"{exe}: {type(exc).__name__}"}
    if done.timed_out:
        return {"ok": False, "error": "cli", "message": f"no answer within {TIMEOUT_S} s"}
    if done.answer is None:
        return {"ok": False, "error": "cli", "message": f"exit {done.returncode}: {done.tail()}".strip()}
    response = done.answer["response"]
    if response.get("subtype") != "success":
        return {"ok": False, "error": "cli", "message": (str_or(response.get("error"), None) or "error")[:200]}
    body = response.get("response") if isinstance(response.get("response"), dict) else {}
    limits = body.get("rate_limits")
    if body.get("rate_limits_available") is False or not isinstance(limits, dict):
        # logged in without a subscription (an API key): there are no subscription limits to show
        return {"ok": False, "error": "nologin", "message": "Claude Code reports no subscription limits"}
    rows, shape = usage_claude.rows_from_body(limits)
    if not rows:
        return {"ok": False, "error": "format", "message": "no limits or usage windows in Claude Code's answer"}
    return {"ok": True, "status": 200, "source": "claudecode", "shape": shape, "fetched_at": int(time.time()),
            "plan": str_or(body.get("subscription_type"), None), "rows": rows}
