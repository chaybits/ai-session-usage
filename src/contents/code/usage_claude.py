"""Claude Code usage rows: the usage body (a ``limits`` list, or the classic windows) as display rows.

Shared by the two Claude sources: ``usage_claudecode`` (Claude Code asked for its usage; the body is the
``rate_limits`` of its ``get_usage`` answer) and ``usage_statusline`` (the same row ids, so a row hidden or
moved in the settings stays that row whichever source is used). Also Claude Code's default login path, which
those sources only check for existence. Until 2026-10-08 this module also read the login token and asked
Anthropic's usage endpoint itself; that source is gone (docs/ARCHITECTURE.md D18; the git tag
``endpoint-source-last`` and ``archive/endpoint-source-20261008/`` keep it).
"""
from __future__ import annotations

import os
from pathlib import Path

from usage_common import is_number, make_row, str_or, unique_ids

PROVIDER = "claude"
# Fallback when the body has no ``limits`` list: the two classic windows and the old per-model weekly caps
# (null on most plans).
WINDOW_LABELS = {
    "five_hour": "Session (5hr)",
    "seven_day": "Weekly (7 day)",
    "seven_day_opus": "Weekly (Opus)",
    "seven_day_sonnet": "Weekly (Sonnet)",
}
# ``limits[].kind`` -> label. Claude Code's schema says to classify rows on ``kind``, never on a label, and to
# keep the server's order. Scoped rows (e.g. the Fable cap) are named after ``scope.model.display_name`` or
# ``scope.surface.display_name``.
KIND_LABELS = {"session": "Session (5hr)", "weekly_all": "Weekly (7 day)"}


def default_credentials() -> Path:
    """
    Return the login file Claude Code uses (only ever checked for existence here).

    Returns:
        ``$CLAUDE_CONFIG_DIR/.credentials.json``, or ``~/.claude/.credentials.json``.
    """
    base = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    return Path(base) / ".credentials.json"


def window(data: dict, key: str) -> dict | None:
    """
    Extract one classic usage window (``five_hour``, ``seven_day``, ...) as a row.

    Args:
        data: Decoded usage body.
        key: Window name, e.g. ``five_hour``.

    Returns:
        A row, or None when absent.
    """
    w = data.get(key)
    if not isinstance(w, dict) or not is_number(w.get("utilization")):
        return None
    return make_row(PROVIDER, key, key, "session" if key == "five_hour" else "weekly",
                    WINDOW_LABELS.get(key, key), w["utilization"], w.get("resets_at"))


def scope_name(scope: object) -> str | None:
    """
    Return the display name of a scoped limit (a model such as Fable, or a surface).

    Args:
        scope: The row's ``scope`` value.

    Returns:
        The server's display label, or None when the row has no usable scope.
    """
    if not isinstance(scope, dict):
        return None
    for part in ("model", "surface"):
        name = scope.get(part, {}).get("display_name") if isinstance(scope.get(part), dict) else None
        if isinstance(name, str) and name:
            return name
    return None


def limit_rows(data: dict) -> list[dict]:
    """
    Turn the body's ``limits`` list into display rows, in the server's order.

    Args:
        data: Decoded usage body.

    Returns:
        Rows; empty when ``limits`` is absent. A row's id is its kind, plus the scope name for a
        scoped row, so "Weekly (Fable)" can be hidden without hiding another model's cap.
    """
    rows: list[dict] = []
    limits = data.get("limits")
    if not isinstance(limits, list):
        return rows
    for item in limits:
        if not isinstance(item, dict) or not is_number(item.get("percent")):
            continue
        kind = str_or(item.get("kind"), "unknown")
        group = str_or(item.get("group"), "")
        scoped = scope_name(item.get("scope"))
        if kind in KIND_LABELS and not scoped:
            label = KIND_LABELS[kind]
        elif scoped:
            label = f"{'Weekly' if group == 'weekly' else kind.replace('_', ' ').title()} ({scoped})"
        else:
            label = kind.replace("_", " ").title()
        row_id = f"{kind}:{scoped}" if scoped else kind
        rows.append(make_row(PROVIDER, row_id, kind, group, label, item["percent"], item.get("resets_at")))
    return unique_ids(rows)


def rows_from_body(body: dict) -> tuple[list[dict], str]:
    """
    Turn a usage body into display rows: its ``limits`` list, or else its classic windows.

    Args:
        body: The ``rate_limits`` Claude Code answers ``get_usage`` with (the shape of Anthropic's usage body).

    Returns:
        ``(rows, source)``: ``source`` is ``limits`` or ``windows``; ``rows`` is empty when neither is there.
    """
    rows = limit_rows(body)
    if rows:
        return rows, "limits"
    return unique_ids([w for key in WINDOW_LABELS if (w := window(body, key)) is not None]), "windows"
