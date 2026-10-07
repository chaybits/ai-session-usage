"""ChatGPT (Codex) usage: the 5-hour and weekly limits a ChatGPT plan gives the Codex agent.

Reads the ChatGPT access token and account id the Codex CLI keeps in ``auth.json`` and asks the
endpoint Codex's own ``/status`` reads (``GET /backend-api/wham/usage``, found in the Codex source,
``codex-rs/backend-client``). The refresh token in the same file is never used or printed.
"""
from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path

from usage_common import (CredentialError, check_header_value, get_json, is_expired, is_number,
                          iso_from_epoch, make_row, str_or, unique_ids)

PROVIDER = "codex"
USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"
# The two windows a plan carries, in the order Codex shows them.
WINDOW_SLOTS = (("primary_window", "primary"), ("secondary_window", "secondary"))
SECONDS_PER_DAY = 86_400


def default_auth() -> Path:
    """
    Return the login file Codex uses.

    Returns:
        ``$CODEX_HOME/auth.json``, or ``~/.codex/auth.json``.
    """
    base = os.environ.get("CODEX_HOME") or os.path.expanduser("~/.codex")
    return Path(base) / "auth.json"


def jwt_expiry_ms(token: str) -> int | None:
    """
    Read the ``exp`` claim of a JWT without verifying it (only to skip a call bound to fail).

    Args:
        token: The access token.

    Returns:
        The expiry in epoch milliseconds, or None when the token is not a JWT with a numeric ``exp``.
    """
    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
    except ValueError:  # bad base64 (binascii.Error), bad UTF-8 or bad JSON
        return None
    exp = payload.get("exp") if isinstance(payload, dict) else None
    return int(exp * 1000) if is_number(exp) else None


def read_auth(path: Path) -> tuple[str, str | None, int | None]:
    """
    Read the access token, the account id and the token's expiry from Codex's ``auth.json``.

    Args:
        path: The login file.

    Returns:
        ``(access_token, account_id_or_None, expires_at_ms_or_None)``.

    Raises:
        CredentialError: ``nologin`` when there is no file or no ChatGPT login in it (an API-key
            login has none); ``unreadable`` when the file or a value in it cannot be used. Messages
            never contain the token.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        raise CredentialError("nologin", f"{path} not found") from None
    except (OSError, ValueError) as exc:  # ValueError: bad JSON and bad UTF-8
        raise CredentialError("unreadable", f"{path}: {type(exc).__name__}") from None

    tokens = data.get("tokens") if isinstance(data, dict) else None
    token = tokens.get("access_token") if isinstance(tokens, dict) else None
    if not isinstance(token, str) or not token.strip():
        raise CredentialError("nologin", "no ChatGPT login (tokens.access_token) in the Codex login file")
    token = check_header_value(token, "access token", path)
    account = tokens.get("account_id")
    account = check_header_value(account, "account id", path) if isinstance(account, str) and account.strip() else None
    return token, account, jwt_expiry_ms(token)


def window_label(seconds: object) -> tuple[str, str]:
    """
    Name a limit window by its length, matching the Claude rows' wording.

    Args:
        seconds: ``limit_window_seconds`` from the response.

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
    if 28 <= days <= 31:  # the free plan's window (30 days, seen 2026-10-05)
        return "weekly", f"Monthly ({days} day)"
    return "weekly", f"{days}-day"


def window_rows(details: object, id_prefix: str, suffix: str | None) -> list[dict]:
    """
    Turn one ``rate_limit`` object (a primary and a secondary window) into rows.

    Args:
        details: The ``rate_limit`` value: ``{primary_window: {used_percent, limit_window_seconds,
            reset_after_seconds, reset_at}, secondary_window: {...}}``.
        id_prefix: Prefix of the row ids ("" for the plan's own limits).
        suffix: Text added to the label in parentheses (the model of an additional limit), or None.

    Returns:
        Zero to two rows.
    """
    rows: list[dict] = []
    if not isinstance(details, dict):
        return rows
    for key, short in WINDOW_SLOTS:
        w = details.get(key)
        if not isinstance(w, dict) or not is_number(w.get("used_percent")):
            continue
        group, label = window_label(w.get("limit_window_seconds"))
        if suffix:
            label = f"{label} ({suffix})"
        resets_at = iso_from_epoch(w.get("reset_at"))
        if resets_at is None and is_number(w.get("reset_after_seconds")):
            resets_at = iso_from_epoch(time.time() + w["reset_after_seconds"])
        rows.append(make_row(PROVIDER, f"{id_prefix}{short}", short, group, label, w["used_percent"], resets_at))
    return rows


def limit_rows(body: dict) -> list[dict]:
    """
    Rows for the plan's limits, then for each additional (per-model) limit, in the server's order.

    Args:
        body: Decoded response body.

    Returns:
        Rows; empty when the response carries no usable window.
    """
    rows = window_rows(body.get("rate_limit"), "", None)
    extra = body.get("additional_rate_limits")
    for item in extra if isinstance(extra, list) else []:
        if not isinstance(item, dict):
            continue
        name = str_or(item.get("limit_name"), None) or str_or(item.get("metered_feature"), None) or "extra"
        feature = str_or(item.get("metered_feature"), None) or name
        rows.extend(window_rows(item.get("rate_limit"), f"{feature}:", name))
    return unique_ids(rows)


def fetch(token: str, account: str | None) -> dict:
    """
    Call the usage endpoint once.

    Args:
        token: Access token (already validated as a plain header value).
        account: The ChatGPT account id, sent the way Codex sends it, or None.

    Returns:
        The result object for ``emit``.
    """
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if account:
        headers["ChatGPT-Account-Id"] = account
    body, error = get_json(USAGE_URL, headers)
    if error is not None:
        return error
    rows = limit_rows(body)
    if not rows:
        return {"ok": False, "error": "format", "message": "no rate_limit windows in response"}
    return {"ok": True, "status": 200, "source": "rate_limit", "plan": str_or(body.get("plan_type"), None),
            "rows": rows}


def run(path: Path | None) -> dict:
    """
    Produce the result for the widget: read the login, skip the call when it has expired, fetch.

    Args:
        path: The login file, or None for Codex's default.

    Returns:
        The result object for ``emit``.
    """
    path = path or default_auth()
    try:
        token, account, expires_ms = read_auth(path)
    except CredentialError as exc:
        return {"ok": False, "error": exc.kind, "message": exc.message}
    if is_expired(expires_ms):
        return {"ok": False, "error": "expired", "expires_at": expires_ms // 1000}
    return fetch(token, account)
