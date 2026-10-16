"""Do the two undocumented requests the widget reads still exist, with the same shape? Asked with no login.

Claude Code's ``get_usage`` control request and Codex's ``account/rateLimits/read`` app-server request are not
documented interfaces, so a release can rename or reshape either without notice. Both are asked here in a throwaway
HOME with no login: a request that still exists answers differently from one that does not (Claude Code even answers
it, with ``rate_limits_available`` false), and each check first sends a made-up request to prove it can tell the two
apart. Codex also exports its protocol's JSON Schema with no login; the rate-limit answer's part of it is compared
with the copy in ``tests/fixtures/``, so a renamed or retyped field shows as a diff before any widget says
"Unexpected answer". Claude Code's inner numbers cannot be seen without a login; its answer's outer keys are checked.

Run every day by ``.github/workflows/watch.yml`` against the newest releases, and by hand:

    python3 -B tests/watch_upstream.py [--claude PATH] [--codex PATH] [--update-schema]

Exit 0 when everything holds, 1 with one line per failure. A missing CLI is a failure, never a skip. No login is read
or needed. ``--update-schema`` rewrites the stored schema from the Codex given, after a change has been reviewed.
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src/contents/code"))

import usage_claudecode  # noqa: E402  (the helper's own request: what the widget sends is what is checked)
import usage_codex  # noqa: E402
from usage_common import ask_cli  # noqa: E402

FIXTURE = HERE / "fixtures/codex-rate-limits.schema.json"
# The schema file of the answer the widget reads, in the bundle `codex app-server generate-json-schema` writes.
SCHEMA_FILE = "v2/GetAccountRateLimitsResponse.json"
REAL_METHOD = "account/rateLimits/read"
# Requests no version will ever have: the controls that prove a check can fail.
MADE_UP_SUBTYPE = "watch_upstream_made_up"
MADE_UP_METHOD = "account/rateLimits/watchUpstreamMadeUp"
# Keys of Claude Code's get_usage answer that the widget reads (usage_claudecode.run).
CLAUDE_KEYS = ("rate_limits_available", "rate_limits")
SCHEMA_TIMEOUT_S = 60


def sandbox_env(box: Path) -> dict[str, str]:
    """The environment for both CLIs: every home and config folder inside ``box``, so no login can be found."""
    env = dict(os.environ)
    for name in ("home", "claude", "codex", "config", "cache", "data", "state"):
        (box / name).mkdir(parents=True, exist_ok=True)
    env.update(HOME=str(box / "home"), CLAUDE_CONFIG_DIR=str(box / "claude"), CODEX_HOME=str(box / "codex"),
               XDG_CONFIG_HOME=str(box / "config"), XDG_CACHE_HOME=str(box / "cache"),
               XDG_DATA_HOME=str(box / "data"), XDG_STATE_HOME=str(box / "state"))
    for secret in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "CODEX_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"):
        env.pop(secret, None)
    return env


def ask_claude(exe: str, subtype: str) -> dict | None:
    """Send one control request to Claude Code; its ``response`` object, or None when it never answered."""
    request = json.dumps({"type": "control_request", "request_id": usage_claudecode.REQUEST_ID,
                          "request": {"subtype": subtype}})
    done = ask_cli([exe, *usage_claudecode.ARGS], [request], usage_claudecode.is_our_answer,
                   usage_claudecode.TIMEOUT_S, close_stdin_first=True)
    return None if done.answer is None else done.answer.get("response")


def check_claude(exe: str) -> list[str]:
    """The made-up subtype must be refused and ``get_usage`` answered with the keys the widget reads."""
    control = ask_claude(exe, MADE_UP_SUBTYPE)
    if not isinstance(control, dict) or control.get("subtype") != "error":
        return [f"claude: the made-up request was not refused, so this check cannot tell (answer: {control})"]
    real = ask_claude(exe, "get_usage")
    if not isinstance(real, dict):
        return ["claude: get_usage got no answer"]
    if real.get("subtype") != "success":
        return [f"claude: get_usage refused: {real.get('error')!r} (the made-up one said {control.get('error')!r})"]
    body = real.get("response") if isinstance(real.get("response"), dict) else {}
    missing = [key for key in CLAUDE_KEYS if key not in body]
    if missing:
        return [f"claude: get_usage answers without {missing}; its keys now: {sorted(body)}"]
    print(f"ok    claude get_usage answers, keys {sorted(body)}")
    return []


def ask_codex(exe: str, method: str) -> dict | None:
    """Initialize Codex's app server and send ``method``; the answer to it, or None when it never answered."""
    requests = [json.dumps({"id": 1, "method": "initialize",
                            "params": {"clientInfo": {"name": usage_codex.CLIENT_NAME, "version": "0.0.0"}}}),
                json.dumps({"method": "initialized"}),
                json.dumps({"id": usage_codex.REQUEST_ID, "method": method})]
    done = ask_cli([exe, "app-server"], requests, lambda message: message.get("id") == usage_codex.REQUEST_ID,
                   usage_codex.TIMEOUT_S, close_stdin_first=False)
    return done.answer


def error_text(answer: dict | None) -> str:
    """The error message of a JSON-RPC answer, or an empty string."""
    error = (answer or {}).get("error")
    return str(error.get("message", "")) if isinstance(error, dict) else str(error or "")


def check_codex(exe: str) -> list[str]:
    """The made-up method must be refused as unknown, naming every method; the real one must be among them."""
    control = error_text(ask_codex(exe, MADE_UP_METHOD))
    if "unknown variant" not in control:
        return [f"codex: the made-up method was not refused as unknown, so this check cannot tell ({control[:200]!r})"]
    known = set(re.findall(r"`([^`]+)`", control.split("expected one of", 1)[-1]))
    if REAL_METHOD not in known:
        return [f"codex: {REAL_METHOD} is no longer among the methods Codex knows "
                f"(rate-limit methods now: {sorted(m for m in known if 'ateLimit' in m)})"]
    real = ask_codex(exe, REAL_METHOD)
    if real is None:
        return [f"codex: {REAL_METHOD} got no answer"]
    if "unknown variant" in error_text(real):
        return [f"codex: {REAL_METHOD} refused as unknown: {error_text(real)[:200]!r}"]
    print(f"ok    codex {REAL_METHOD} is known (no login: {error_text(real)[:80]!r})")
    return []


def without_descriptions(node: object) -> object:
    """The schema with every ``description`` dropped: reworded prose is not a change of format."""
    if isinstance(node, dict):
        return {key: without_descriptions(value) for key, value in node.items() if key != "description"}
    if isinstance(node, list):
        return [without_descriptions(item) for item in node]
    return node


def codex_schema(exe: str, env: dict[str, str], box: Path) -> dict:
    """The rate-limit answer's JSON Schema from this Codex, descriptions dropped. Raises RuntimeError if not made."""
    out = box / "schema"
    proc = subprocess.run([exe, "app-server", "generate-json-schema", "--out", str(out)], env=env,
                          capture_output=True, encoding="utf-8", errors="replace", timeout=SCHEMA_TIMEOUT_S, check=False)
    path = out / SCHEMA_FILE
    if proc.returncode != 0 or not path.is_file():
        raise RuntimeError(f"generate-json-schema exit {proc.returncode}, {SCHEMA_FILE} "
                           f"{'present' if path.is_file() else 'missing'}: {proc.stderr.strip()[-200:]}")
    return without_descriptions(json.loads(path.read_text(encoding="utf-8")))


def cli_version(exe: str, env: dict[str, str]) -> str:
    """The first line ``--version`` prints, for the report."""
    proc = subprocess.run([exe, "--version"], env=env, capture_output=True, encoding="utf-8", errors="replace",
                          timeout=SCHEMA_TIMEOUT_S, check=False)
    return (proc.stdout.strip().splitlines() or ["unknown"])[0]


def check_schema(exe: str, env: dict[str, str], box: Path, update: bool) -> list[str]:
    """Compare the rate-limit schema with the stored copy, or store it with ``update``."""
    try:
        schema = codex_schema(exe, env, box)
    except (RuntimeError, OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        return [f"codex schema: {exc}"]
    version = cli_version(exe, env)
    text = json.dumps(schema, indent=1, sort_keys=True) + "\n"
    if update:
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(json.dumps({"codex": version, "schema": schema}, indent=1, sort_keys=True) + "\n",
                           encoding="utf-8")
        print(f"wrote {FIXTURE.name} from {version}")
        return []
    stored = json.loads(FIXTURE.read_text(encoding="utf-8"))
    before = json.dumps(stored["schema"], indent=1, sort_keys=True) + "\n"
    if before == text:
        print(f"ok    codex rate-limit schema unchanged ({version}; stored from {stored['codex']})")
        return []
    diff = "".join(difflib.unified_diff(before.splitlines(True), text.splitlines(True),
                                        f"stored ({stored['codex']})", f"now ({version})"))
    print(diff)
    return [f"codex schema: the rate-limit answer changed between {stored['codex']} and {version} (diff above)"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--claude", default=shutil.which("claude"), help="the claude program (default: on PATH)")
    parser.add_argument("--codex", default=shutil.which("codex"), help="the codex program (default: on PATH)")
    parser.add_argument("--update-schema", action="store_true", help="store the schema of this Codex instead")
    args = parser.parse_args()
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="watch-upstream-") as tmp:
        box = Path(tmp)
        env = sandbox_env(box)
        os.environ.update(env)  # ask_cli starts the CLIs with this process's environment
        if args.codex is None:
            failures.append("codex: not found")
        else:
            if not args.update_schema:
                failures += check_codex(args.codex)
            failures += check_schema(args.codex, env, box, args.update_schema)
        if args.update_schema:
            return 1 if failures else 0
        failures += ["claude: not found"] if args.claude is None else check_claude(args.claude)
    for failure in failures:
        print(f"FAIL  {failure}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
