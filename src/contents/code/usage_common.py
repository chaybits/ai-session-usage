"""Shared parts of the usage helper: the output contract, the one HTTP call, and value checks.

Each source module (``usage_claudecode``, ``usage_statusline``, ``usage_codex``) returns a result dict;
``fetch_usage.py`` prints it with ``emit``. The HTTP call and the login checks serve Codex alone since
2026-10-08 (D18): Claude's login is never read here. No module refreshes a login: ``usage_codex`` reads the
access token Codex keeps and leaves refreshing to Codex, because it rotates its refresh token and a second
client doing the same can log it out.
"""
from __future__ import annotations

import functools
import http.client
import json
import math
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

# Bounds each network step (connect, TLS, each read), not the whole run; the widget's watchdog bounds the run.
TIMEOUT_S = 15
# A token this close to its expiry is treated as expired, so no request is made that would fail anyway.
EXPIRY_MARGIN_MS = 30_000
# A Retry-After beyond this would idle the widget for hours on one odd header; a click still works.
MAX_RETRY_S = 3600
# Display cap on a network error message, so one odd reason cannot flood the status line.
MAX_MESSAGE_CHARS = 200


class CredentialError(Exception):
    """The login file cannot be used; ``kind`` is the error code the widget shows."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message


@functools.cache
def user_agent() -> str:
    """
    Return the User-Agent sent to every endpoint, carrying the package version.

    Returns:
        ``ai-session-usage/<version>``, the version read from the package's ``metadata.json`` (the one
        place it is written); ``unknown`` when that file cannot be read, which the tests would catch.
    """
    meta = Path(__file__).resolve().parents[2] / "metadata.json"
    try:
        version = str(json.loads(meta.read_text(encoding="utf-8"))["KPlugin"]["Version"])
    except (OSError, ValueError, KeyError, TypeError):
        version = "unknown"
    return f"ai-session-usage/{version}"


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


def check_header_value(value: str, what: str, path: Path) -> str:
    """
    Return ``value`` stripped, or refuse it when it cannot be sent as an HTTP header value.

    Args:
        value: The token or id read from a login file.
        what: Its name, for the message.
        path: The file it came from, for the message.

    Raises:
        CredentialError: ``unreadable`` when the value has a character a header cannot carry;
            http.client would echo the whole value, token included, in its error text.
    """
    value = value.strip()
    if not (value.isascii() and value.isprintable() and " " not in value):
        raise CredentialError("unreadable", f"{path}: {what} has an invalid character (length {len(value)})")
    return value


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


def is_expired(expires_ms: int | None) -> bool:
    """Return True when a token expiry (epoch ms) is past or within the margin; None means unknown."""
    return expires_ms is not None and expires_ms <= time.time() * 1000 + EXPIRY_MARGIN_MS


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects: urllib would copy the Authorization header to the new host."""

    def redirect_request(self, *args, **kwargs):  # noqa: D102
        return None


def retry_seconds(header: str) -> int | None:
    """
    Read a ``Retry-After`` header (delta-seconds or an HTTP date) as seconds from now.

    Args:
        header: The raw header value, possibly empty.

    Returns:
        Whole seconds, between 0 and ``MAX_RETRY_S``; None when absent or unparseable.
    """
    header = header.strip()
    if header.isascii() and header.isdigit():
        return min(int(header), MAX_RETRY_S)
    try:
        when = parsedate_to_datetime(header)
    except (TypeError, ValueError):
        return None
    return max(0, min(int(when.timestamp() - time.time()), MAX_RETRY_S))


def get_json(url: str, headers: dict[str, str]) -> tuple[dict | None, dict | None]:
    """
    GET ``url`` once and decode a JSON object.

    Args:
        url: The endpoint.
        headers: Request headers (the token among them; already checked by ``check_header_value``).

    Returns:
        ``(body, None)`` on success, or ``(None, result)`` where ``result`` is the error object to emit.
    """
    request = urllib.request.Request(url, headers={**headers, "User-Agent": user_agent()})
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=TIMEOUT_S) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            return None, {"ok": False, "error": "ratelimited", "status": 429,
                          "retry_after": retry_seconds(exc.headers.get("retry-after", ""))}
        return None, {"ok": False, "error": "auth" if exc.code in (401, 403) else "http", "status": exc.code}
    except http.client.HTTPException as exc:  # cut-short body, garbage status line
        return None, {"ok": False, "error": "network", "message": type(exc).__name__}
    except (urllib.error.URLError, OSError) as exc:  # TimeoutError is an OSError
        reason = getattr(exc, "reason", exc)
        return None, {"ok": False, "error": "network", "message": str(reason)[:MAX_MESSAGE_CHARS]}
    except ValueError:  # bad JSON and bad UTF-8
        return None, {"ok": False, "error": "badjson"}
    if not isinstance(body, dict):
        return None, {"ok": False, "error": "badjson"}
    return body, None
