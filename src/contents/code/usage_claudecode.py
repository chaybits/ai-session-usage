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
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import usage_claude
from usage_common import MAX_MESSAGE_CHARS, str_or

PROVIDER = "claude"
# Bounds the whole Claude Code run (it takes about 2 s); the widget's watchdog (60 s) bounds the helper.
TIMEOUT_S = 40
REQUEST_ID = "ai-session-usage"
# Headless, one control request in and its answer out; no hooks (a SessionStart hook must not fire for a
# usage read), no MCP server started, no session written, no skills.
ARGS = ["-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
        "--no-session-persistence", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
        "--settings", '{"disableAllHooks":true}', "--disable-slash-commands"]


def find_claude(command: str | None) -> str | None:
    """
    The Claude Code program to run.

    Args:
        command: The user's setting (a path or a program name), or None to look for ``claude``.

    Returns:
        Its path, or None when it cannot be found. Without a setting: ``claude`` on the PATH, then the places
        Claude Code's installers use, since a desktop's PATH may lack ``~/.local/bin``.
    """
    if command:
        path = Path(os.path.expanduser(command))
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
        return shutil.which(command)
    found = shutil.which("claude")
    if found:
        return found
    for candidate in (Path.home() / ".local/bin/claude", Path.home() / ".claude/local/claude"):
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def find_response(stdout: str) -> dict | None:
    """
    The answer to our control request among Claude Code's output lines.

    Args:
        stdout: Claude Code's stream-json output.

    Returns:
        The ``response`` object of the ``control_response`` carrying our request id, or None.
    """
    for line in stdout.splitlines():
        try:
            message = json.loads(line)
        except ValueError:
            continue
        if not isinstance(message, dict) or message.get("type") != "control_response":
            continue
        response = message.get("response")
        if isinstance(response, dict) and response.get("request_id") == REQUEST_ID:
            return response
    return None


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
    exe = find_claude(command)
    if exe is None:
        return {"ok": False, "error": "noclaude", "message": command or "claude"}
    request = json.dumps({"type": "control_request", "request_id": REQUEST_ID, "request": {"subtype": "get_usage"}})
    try:
        done = subprocess.run([exe, *ARGS], input=request + "\n", capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=TIMEOUT_S, cwd=tempfile.gettempdir())
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "claudecode", "message": f"no answer within {TIMEOUT_S} s"}
    except OSError as exc:
        return {"ok": False, "error": "noclaude", "message": f"{exe}: {type(exc).__name__}"}
    response = find_response(done.stdout)
    if response is None:
        tail = (done.stderr or done.stdout).strip()[-MAX_MESSAGE_CHARS:]
        return {"ok": False, "error": "claudecode", "message": f"exit {done.returncode}: {tail}".strip()}
    if response.get("subtype") != "success":
        return {"ok": False, "error": "claudecode",
                "message": str_or(response.get("error"), "error")[:MAX_MESSAGE_CHARS]}
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
