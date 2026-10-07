"""Tests for the usage helper in src/contents/code/ (stdlib unittest, no network beyond 127.0.0.1).

The helper runs as a subprocess so exit code and stdout are asserted for real. The one HTTP source, ChatGPT
(Codex), is served by a local http.server (USAGE_URL overridden) with a fake auth.json in a temp dir; the shared
HTTP code (usage_common.get_json) is tested through it. Claude's rows (usage_claude.rows_from_body, shared by
the two Claude sources) are tested as a function: since 2026-10-08 this helper never reads Claude's login or
asks Anthropic (ARCHITECTURE D18). A direct run that defaults to Claude either gets no login (so Claude Code is
never started) or a fake ``claude`` on a sandbox PATH; the real one is never run here.
"""
from __future__ import annotations

import base64
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from email.utils import formatdate
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent / "src"
CODE = PKG / "contents" / "code"
SCRIPT = CODE / "fetch_usage.py"
sys.path.insert(0, str(CODE))
sys.dont_write_bytecode = True  # a test run must not leave a __pycache__ in the package
import usage_claude  # noqa: E402
import usage_codex  # noqa: E402
import usage_common  # noqa: E402
import test_claudecode  # noqa: E402  (beside this file: the fake claude and its answer)

# The fake Codex token is a JWT; its signature part is unique enough to grep the output for.
CODEX_SIGNATURE = "FAKE-CODEX-SIGNATURE-FOR-TESTS"

# Runs the helper's real entry point with the Codex endpoint pointed at the local server.
LAUNCHER = (
    "import sys; sys.dont_write_bytecode = True; sys.path.insert(0, sys.argv[1]); "
    "import usage_common, usage_codex, fetch_usage; "
    "usage_codex.USAGE_URL = sys.argv[2]; usage_common.TIMEOUT_S = float(sys.argv[3]); "
    "sys.argv = ['fetch_usage.py'] + sys.argv[4:]; fetch_usage.run()"
)
META_VERSION = json.loads((PKG / "metadata.json").read_text(encoding="utf-8"))["KPlugin"]["Version"]


class Handler(http.server.BaseHTTPRequestHandler):
    """Answers every GET from ``server.script`` and records the Authorization headers."""

    protocol_version = "HTTP/1.0"

    def do_GET(self) -> None:  # noqa: N802
        try:
            self.answer()
        except (BrokenPipeError, ConnectionResetError):
            pass  # the helper hung up on purpose (timeout, refused redirect)

    def answer(self) -> None:
        """Write the scripted answer."""
        script = self.server.script
        self.server.seen.append(self.headers.get("Authorization"))
        self.server.headers.append({k.lower(): v for k, v in self.headers.items()})  # names are case-insensitive
        mode = script.get("mode", "normal")
        if mode == "garbage":
            self.wfile.write(b"GARBAGE\r\n\r\n")
            return
        if mode == "truncated":
            self.wfile.write(b"HTTP/1.1 200 OK\r\nContent-Length: 1000\r\n\r\nshort")
            return
        if mode == "slow":
            time.sleep(script["delay"])
        self.send_response(script.get("status", 200))
        for key, value in script.get("headers", {}).items():
            self.send_header(key, value)
        body = script.get("body", b"")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass


def start_server() -> http.server.ThreadingHTTPServer:
    """Start a local server on a free port; the caller sets ``.script`` and calls shutdown."""
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.script = {}
    server.seen = []
    server.headers = []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def stop_server(server: http.server.ThreadingHTTPServer) -> None:
    """Stop a server started by start_server and release its socket."""
    if not getattr(server, "stopped", False):
        server.shutdown()
        server.server_close()
        server.stopped = True


def url_of(server: http.server.ThreadingHTTPServer) -> str:
    """The server's base URL."""
    return f"http://127.0.0.1:{server.server_address[1]}/limits"


def claude_body(**extra: object) -> dict:
    """A Claude usage body (Claude Code's ``get_usage`` answer): three limits in the server's order."""
    body = {"limits": [
        {"kind": "session", "group": "session", "percent": 12.5, "resets_at": "2026-10-03T10:00:00+00:00"},
        {"kind": "weekly_all", "group": "weekly", "percent": 40, "resets_at": "2026-10-08T10:00:00.123456+00:00"},
        {"kind": "weekly_scoped", "group": "weekly", "percent": 7,
         "scope": {"model": {"display_name": "Fable"}}, "resets_at": "2026-10-08T10:00:00+00:00"},
    ]}
    body.update(extra)
    return body


def codex_token(exp: float | None) -> str:
    """A fake Codex access token shaped like a JWT, with ``exp`` (epoch seconds) when given."""
    def part(obj: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")
    payload = {"sub": "fake"} if exp is None else {"sub": "fake", "exp": exp}
    return f"{part({'alg': 'none'})}.{part(payload)}.{CODEX_SIGNATURE}"


def codex_body(**extra: object) -> bytes:
    """A /wham/usage answer: the plan's two windows and one additional per-model limit."""
    now = int(time.time())
    body = {"plan_type": "plus",
            "rate_limit": {"allowed": True, "limit_reached": False,
                           "primary_window": {"used_percent": 12, "limit_window_seconds": 18000,
                                              "reset_after_seconds": 3600, "reset_at": now + 3600},
                           "secondary_window": {"used_percent": 30, "limit_window_seconds": 604800,
                                                "reset_after_seconds": 86400, "reset_at": now + 86400}},
            "additional_rate_limits": [{"limit_name": "GPT-Codex-Mini", "metered_feature": "codex_mini",
                                        "rate_limit": {"primary_window": {"used_percent": 3, "limit_window_seconds": 18000,
                                                                          "reset_after_seconds": 60, "reset_at": now + 60}}}],
            "account_id": "acct-FAKE", "user_id": "user-FAKE"}
    body.update(extra)
    return json.dumps(body).encode()


class HelperCase(unittest.TestCase):
    """Base: a temp dir for a fake Codex login, one local server, and a subprocess runner."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.server = start_server()
        self.addCleanup(stop_server, self.server)

    def creds(self, content: bytes | str | None = None, *, exp: float | None = time.time() + 86400,
              account: str | None = "acct-FAKE", token: str | None = None, name: str = "auth.json") -> Path:
        """Write a Codex auth.json (default: a valid ChatGPT login) and return its path."""
        path = Path(self.tmp.name) / name
        if content is None:
            tokens: dict = {"id_token": "id-FAKE", "access_token": token if token is not None else codex_token(exp),
                            "refresh_token": "codex-refresh-FAKE"}
            if account is not None:
                tokens["account_id"] = account
            content = json.dumps({"auth_mode": "chatgpt", "OPENAI_API_KEY": None, "tokens": tokens,
                                  "last_refresh": "2026-10-05T00:00:00Z"})
        path.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
        return path

    def run_helper(self, creds: Path | str, *, url: str | None = None, timeout_s: float = 5,
                   env: dict | None = None) -> dict:
        """Run the helper for Codex; assert the contract (exit 0, one pure-ASCII JSON line, no secrets)."""
        full_env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        full_env.update(env or {})
        proc = subprocess.run(
            [sys.executable, "-c", LAUNCHER, str(CODE), url or url_of(self.server), str(timeout_s),
             "--provider", "codex", str(creds)],
            capture_output=True, cwd=self.tmp.name, env=full_env, timeout=30)
        out, err = proc.stdout.decode("utf-8"), proc.stderr.decode("utf-8", "replace")
        self.assertEqual(proc.returncode, 0, f"exit code; stderr={err!r}")
        self.assertEqual(err, "", "nothing on stderr")
        lines = out.splitlines()
        self.assertEqual(len(lines), 1, f"exactly one stdout line, got {out!r}")
        self.assertTrue(out.isascii(), "stdout is pure ASCII")
        for secret in (CODEX_SIGNATURE, "codex-refresh-FAKE", "sk-proj-FAKE"):
            self.assertNotIn(secret, out + err, "a token leaked into the output")
        return json.loads(lines[0])

    def serve(self, **script: object) -> None:
        """Set what the local server answers next."""
        self.server.script = script


class TestClaudeRows(unittest.TestCase):
    """``usage_claude.rows_from_body``: the body both Claude sources hand over, as display rows."""

    def test_limits_in_server_order_with_scoped_label(self) -> None:
        rows, source = usage_claude.rows_from_body(claude_body())
        self.assertEqual(source, "limits")
        self.assertEqual([r["label"] for r in rows], ["Session (5hr)", "Weekly (7 day)", "Weekly (Fable)"])
        self.assertEqual([r["id"] for r in rows], ["claude:session", "claude:weekly_all", "claude:weekly_scoped:Fable"])
        self.assertEqual(rows[1]["resets_at"], "2026-10-08T10:00:00.123456+00:00")
        self.assertEqual({r["provider"] for r in rows}, {"claude"})

    def test_scoped_without_group_and_junk_entries(self) -> None:
        body = {"limits": [
            "junk", None, {"kind": "session"}, {"percent": "12"},
            {"kind": "weekly_scoped", "percent": 3, "scope": {"surface": {"display_name": "Cowork"}}},
            {"kind": "session", "percent": 5, "scope": {}, "resets_at": 17},
            {"percent": 9},
        ]}
        rows, _ = usage_claude.rows_from_body(body)
        self.assertEqual([(r["label"], r["percent"], r["resets_at"]) for r in rows],
                         [("Weekly Scoped (Cowork)", 3.0, None), ("Session (5hr)", 5.0, None), ("Unknown", 9.0, None)])

    def test_fallback_windows_when_no_limits(self) -> None:
        body = {"five_hour": {"utilization": 33, "resets_at": "2026-10-03T10:00:00Z"},
                "seven_day": {"utilization": 1.5}, "seven_day_opus": None}
        rows, source = usage_claude.rows_from_body(body)
        self.assertEqual(source, "windows")
        self.assertEqual([(r["kind"], r["group"], r["percent"]) for r in rows],
                         [("five_hour", "session", 33.0), ("seven_day", "weekly", 1.5)])

    def test_non_numbers_and_non_finite_percents_are_skipped(self) -> None:
        # Python's json reads NaN and Infinity; bool is an int subclass; 1e400 as an int overflows a float
        body = json.loads('{"limits": [{"kind": "session", "percent": NaN}, {"kind": "session", "percent": true},'
                          ' {"kind": "session", "percent": Infinity}, {"kind": "session", "percent": 1' + "0" * 400 + '},'
                          ' {"kind": "weekly_all", "group": "weekly", "percent": 40}]}')
        rows, _ = usage_claude.rows_from_body(body)
        self.assertEqual([(r["kind"], r["percent"]) for r in rows], [("weekly_all", 40.0)])

    def test_non_finite_window_utilization_gives_no_rows(self) -> None:
        body = json.loads('{"five_hour": {"utilization": -Infinity}, "seven_day": {"utilization": false}}')
        self.assertEqual(usage_claude.rows_from_body(body), ([], "windows"))

    def test_repeated_ids_are_made_unique(self) -> None:
        body = {"limits": [{"kind": "session", "percent": 1}, {"kind": "session", "percent": 2}]}
        self.assertEqual([r["id"] for r in usage_claude.rows_from_body(body)[0]], ["claude:session", "claude:session#2"])

    def test_emit_refuses_nan_instead_of_printing_invalid_json(self) -> None:
        with self.assertRaises(ValueError):
            usage_common.emit({"ok": True, "x": float("nan")})


class TestCodex(HelperCase):
    def test_rows_from_both_windows_and_an_additional_limit(self) -> None:
        self.serve(body=codex_body())
        out = self.run_helper(self.creds())
        self.assertEqual((out["ok"], out["provider"], out["plan"]), (True, "codex", "plus"))
        self.assertEqual([(r["id"], r["label"], r["group"], r["percent"]) for r in out["rows"]],
                         [("codex:primary", "Session (5hr)", "session", 12.0),
                          ("codex:secondary", "Weekly (7 day)", "weekly", 30.0),
                          ("codex:codex_mini:primary", "Session (5hr) (GPT-Codex-Mini)", "session", 3.0)])
        for row in out["rows"]:
            self.assertRegex(row["resets_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00$")
        sent = self.server.headers[0]
        self.assertTrue(sent["authorization"].startswith("Bearer ") and sent["authorization"].endswith(CODEX_SIGNATURE))
        self.assertEqual(sent["chatgpt-account-id"], "acct-FAKE")
        self.assertEqual(sent["user-agent"], f"ai-session-usage/{META_VERSION}")

    def test_turkish_names_round_trip_as_ascii(self) -> None:
        # run_helper asserts the stdout line is pure ASCII; the label must still come back whole
        name = "Şiir ğüş ıİ öç"
        body = json.loads(codex_body())
        body["additional_rate_limits"][0]["limit_name"] = name
        self.serve(body=json.dumps(body, ensure_ascii=False).encode("utf-8"))
        out = self.run_helper(self.creds())
        self.assertEqual(out["rows"][2]["label"], f"Session (5hr) ({name})")

    def test_reset_after_seconds_when_reset_at_is_missing(self) -> None:
        body = {"rate_limit": {"primary_window": {"used_percent": 50, "limit_window_seconds": 18000,
                                                  "reset_after_seconds": 600}}}
        self.serve(body=json.dumps(body).encode())
        out = self.run_helper(self.creds())
        from datetime import datetime
        delta = datetime.fromisoformat(out["rows"][0]["resets_at"]).timestamp() - time.time()
        self.assertTrue(590 <= delta <= 600, delta)

    def test_no_account_id_sends_no_account_header(self) -> None:
        self.serve(body=codex_body())
        self.assertTrue(self.run_helper(self.creds(account=None))["ok"])
        self.assertNotIn("chatgpt-account-id", self.server.headers[0])

    def test_no_usable_window_is_a_format_error(self) -> None:
        self.serve(body=json.dumps({"plan_type": "plus", "rate_limit": None}).encode())
        self.assertEqual(self.run_helper(self.creds())["error"], "format")

    def test_window_lengths_name_the_rows(self) -> None:
        self.assertEqual(usage_codex.window_label(18000), ("session", "Session (5hr)"))
        self.assertEqual(usage_codex.window_label(604800), ("weekly", "Weekly (7 day)"))
        self.assertEqual(usage_codex.window_label(86400), ("weekly", "1-day"))
        self.assertEqual(usage_codex.window_label(2592000), ("weekly", "Monthly (30 day)"))
        self.assertEqual(usage_codex.window_label(1800), ("session", "Session (30min)"))
        self.assertEqual(usage_codex.window_label(None), ("", "Limit"))

    def test_token_that_is_not_a_jwt_still_fetches(self) -> None:
        self.serve(body=codex_body())
        content = json.dumps({"tokens": {"access_token": "opaque-" + CODEX_SIGNATURE}})
        self.assertTrue(self.run_helper(self.creds(content))["ok"])

    def test_codex_home_is_used_without_a_path(self) -> None:
        proc = subprocess.run([sys.executable, str(SCRIPT), "--provider", "codex"], capture_output=True, text=True,
                              env=dict(os.environ, CODEX_HOME=self.tmp.name, PYTHONDONTWRITEBYTECODE="1"))
        out = json.loads(proc.stdout)
        self.assertEqual((proc.returncode, out["error"]), (0, "nologin"))
        self.assertIn(self.tmp.name, out["message"])


class TestBadResponses(HelperCase):
    def check(self, expected: dict, **script: object) -> dict:
        """Serve ``script`` and assert the JSON carries every key of ``expected``."""
        self.serve(**script)
        out = self.run_helper(self.creds())
        for key, value in expected.items():
            self.assertEqual(out.get(key), value, f"{key} in {out}")
        self.assertFalse(out["ok"])
        return out

    def test_list_body(self) -> None:
        self.check({"error": "badjson"}, body=b"[1,2]")

    def test_empty_object_is_format_error(self) -> None:
        self.check({"error": "format"}, body=b"{}")

    def test_html_200(self) -> None:
        self.check({"error": "badjson"}, body=b"<html>captive portal</html>")

    def test_invalid_utf8_body(self) -> None:
        self.check({"error": "badjson"}, body=b"\xff\xfe{")

    def test_deeply_nested_json_is_reported_not_a_traceback(self) -> None:
        self.check({"error": "internal", "message": "RecursionError"}, body=b"[" * 200000)

    def test_401_and_403_are_auth(self) -> None:
        self.check({"error": "auth", "status": 401}, status=401, body=b"{}")
        self.check({"error": "auth", "status": 403}, status=403, body=b"{}")

    def test_500_is_http(self) -> None:
        self.check({"error": "http", "status": 500}, status=500, body=b"x")

    def test_truncated_body_is_network(self) -> None:
        out = self.check({"error": "network"}, mode="truncated")
        self.assertEqual(out["message"], "IncompleteRead")

    def test_garbage_status_line_is_network(self) -> None:
        out = self.check({"error": "network"}, mode="garbage")
        self.assertEqual(out["message"], "BadStatusLine")

    def test_timeout_is_network(self) -> None:
        self.serve(mode="slow", delay=3, body=codex_body())
        started = time.time()
        out = self.run_helper(self.creds(), timeout_s=1)
        self.assertLess(time.time() - started, 3)
        self.assertEqual(out["error"], "network")

    def test_connection_refused_is_network(self) -> None:
        port = self.server.server_address[1]
        stop_server(self.server)
        out = self.run_helper(self.creds(), url=f"http://127.0.0.1:{port}/x")
        self.assertEqual(out["error"], "network")
        self.assertTrue(out["message"])


class TestRateLimit(HelperCase):
    def test_numeric_retry_after(self) -> None:
        self.serve(status=429, headers={"Retry-After": "120"}, body=b"{}")
        out = self.run_helper(self.creds())
        self.assertEqual((out["error"], out["status"], out["retry_after"]), ("ratelimited", 429, 120))

    def test_http_date_retry_after(self) -> None:
        self.serve(status=429, headers={"Retry-After": formatdate(time.time() + 300, usegmt=True)}, body=b"{}")
        out = self.run_helper(self.creds())
        self.assertIn(out["retry_after"], range(290, 301))

    def test_huge_retry_after_is_clamped(self) -> None:
        self.serve(status=429, headers={"Retry-After": "86400"}, body=b"{}")
        self.assertEqual(self.run_helper(self.creds())["retry_after"], 3600)

    def test_missing_or_garbage_retry_after_is_null(self) -> None:
        self.serve(status=429, body=b"{}")
        self.assertIsNone(self.run_helper(self.creds())["retry_after"])
        self.serve(status=429, headers={"Retry-After": "soon"}, body=b"{}")
        self.assertIsNone(self.run_helper(self.creds())["retry_after"])

    def test_non_ascii_digits_in_retry_after_do_not_crash(self) -> None:
        # str.isdigit() is true for "²" and int("²") raises
        self.assertIsNone(usage_common.retry_seconds("²"))

    def test_past_http_date_is_zero(self) -> None:
        self.assertEqual(usage_common.retry_seconds(formatdate(time.time() - 500, usegmt=True)), 0)


class TestRedirect(HelperCase):
    def test_redirect_is_refused_and_token_does_not_follow(self) -> None:
        other = start_server()
        self.addCleanup(stop_server, other)
        other.script = {"body": codex_body()}
        self.serve(status=302, headers={"Location": url_of(other)}, body=b"")
        out = self.run_helper(self.creds())
        self.assertEqual((out["ok"], out["error"], out["status"]), (False, "http", 302))
        self.assertEqual(other.seen, [], "the second host must receive no request at all")


class TestLoginFile(HelperCase):
    """Codex's auth.json: every way it can be unusable answers without a request and without the token."""

    def expect(self, path: Path | str, error: str) -> dict:
        out = self.run_helper(path)
        self.assertEqual((out["ok"], out["error"]), (False, error), out)
        self.assertEqual(self.server.seen, [], "no request may be made")
        return out

    def test_missing_is_nologin(self) -> None:
        self.expect(Path(self.tmp.name) / "absent.json", "nologin")

    def test_api_key_login_is_nologin(self) -> None:
        self.expect(self.creds(json.dumps({"auth_mode": "apikey", "OPENAI_API_KEY": "sk-proj-FAKE", "tokens": None})),
                    "nologin")

    def test_no_tokens_section_is_nologin(self) -> None:
        self.expect(self.creds('{"auth_mode": "chatgpt"}'), "nologin")

    def test_empty_token_is_nologin(self) -> None:
        self.expect(self.creds(token="  "), "nologin")

    def test_top_level_list_is_nologin(self) -> None:
        self.expect(self.creds("[1]"), "nologin")

    def test_corrupt_json_is_unreadable_with_message(self) -> None:
        out = self.expect(self.creds('{"tokens": {"access_to'), "unreadable")
        self.assertIn("JSONDecodeError", out["message"])

    def test_empty_file_is_unreadable(self) -> None:
        self.expect(self.creds(""), "unreadable")

    def test_directory_is_unreadable(self) -> None:
        self.expect(self.tmp.name, "unreadable")

    def test_invalid_utf8_file_is_unreadable(self) -> None:
        out = self.expect(self.creds(b'{"a": "\xff\xfe"}'), "unreadable")
        self.assertIn("UnicodeDecodeError", out["message"])

    def test_token_with_newline_is_refused_without_leaking(self) -> None:
        # a trailing newline is stripped and works; an embedded one is an injection attempt
        self.serve(body=codex_body())
        self.assertTrue(self.run_helper(self.creds(token=codex_token(None) + "\n"))["ok"])
        self.assertEqual(self.server.seen[-1], f"Bearer {codex_token(None)}")
        self.server.seen.clear()
        out = self.expect(self.creds(token=codex_token(None) + "\nX-Injected: 1"), "unreadable")
        self.assertIn("invalid character", out["message"])

    def test_non_ascii_token_or_account_is_refused(self) -> None:
        self.expect(self.creds(token="opaque-ş-" + CODEX_SIGNATURE), "unreadable")
        self.expect(self.creds(account="a\nb"), "unreadable")

    def test_expired_and_in_margin_make_no_request(self) -> None:
        past = self.expect(self.creds(exp=time.time() - 3600), "expired")
        self.assertIn("expires_at", past)
        self.expect(self.creds(exp=time.time() + 10), "expired")

    def test_no_expiry_claim_still_fetches(self) -> None:
        self.serve(body=codex_body())
        self.assertTrue(self.run_helper(self.creds(exp=None))["ok"])

    def test_non_ascii_path_in_message_is_ascii_and_survives_a_latin1_stdout(self) -> None:
        path = Path(self.tmp.name) / "şüı dir" / "auth.json"
        out = self.run_helper(path, env={"PYTHONIOENCODING": "latin-1"})
        self.assertEqual(out["error"], "nologin")
        self.assertIn("şüı dir", out["message"])

    def test_read_auth_raises_instead_of_exiting(self) -> None:
        with self.assertRaises(usage_common.CredentialError) as ctx:
            usage_codex.read_auth(self.creds('{"tokens": {}}'))
        self.assertEqual(ctx.exception.kind, "nologin")
        token, account, expires = usage_codex.read_auth(self.creds(exp=1_800_000_000))
        self.assertEqual((token.endswith(CODEX_SIGNATURE), account, expires), (True, "acct-FAKE", 1_800_000_000_000))


class TestNoTokenAnywhere(HelperCase):
    """F04: every failure path's stdout and stderr are searched for the fake token."""

    def test_every_failure_path(self) -> None:
        scripts = [dict(status=401), dict(status=500), dict(status=429, headers={"Retry-After": "5"}),
                   dict(status=302, headers={"Location": "http://127.0.0.1:9/"}), dict(mode="truncated"),
                   dict(mode="garbage"), dict(body=b"nope"), dict(body=b"{}"), dict(body=b"[" * 200000)]
        creds = [self.creds(), self.creds(exp=1, name="old.json"),
                 self.creds('{"tokens": {"access_token": "x\\n' + CODEX_SIGNATURE + '"}}', name="bad.json")]
        ran = 0
        for script in scripts:
            self.serve(**script)
            for path in creds:
                self.assertIn("error", self.run_helper(path))  # asserts no token in stdout or stderr
                ran += 1
        self.assertEqual(ran, len(scripts) * len(creds))
        # control: the same check must be able to fail, so confirm the token really was sent
        self.assertTrue(any(h and h.endswith(CODEX_SIGNATURE) for h in self.server.seen), "the token was really sent")


class TestDirectScript(unittest.TestCase):
    """The script run the way the widget runs it (python3 file.py ...), no network needed.

    Claude is the default provider and Claude Code its default source (D18): these runs give it either no login,
    so Claude Code is never started, or a fake ``claude`` on a sandbox PATH with HOME in the sandbox (the real
    one is also looked for under ~/.local/bin).
    """

    def test_missing_file_exits_zero_with_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run([sys.executable, str(SCRIPT), str(Path(tmp) / "none.json")],
                                  capture_output=True, text=True,
                                  env=dict(os.environ, HOME=tmp, PYTHONDONTWRITEBYTECODE="1"))
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)["error"], "nologin")

    def test_claude_config_dir_is_used_without_argument(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, HOME=tmp, CLAUDE_CONFIG_DIR=tmp, PYTHONDONTWRITEBYTECODE="1")
            proc = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, env=env)
        out = json.loads(proc.stdout)
        self.assertEqual(out["error"], "nologin")
        self.assertIn(tmp, out["message"])

    def test_claude_without_source_asks_claude_code(self) -> None:
        # no --source: the default is Claude Code itself (a hand run, or a QML older than the --source flag)
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            (home / ".claude").mkdir(parents=True)
            (home / ".claude/.credentials.json").write_text("{}", encoding="utf-8")  # only checked to exist
            fake = Path(tmp) / "bin/claude"
            fake.parent.mkdir()
            fake.write_text(test_claudecode.FAKE, encoding="utf-8")
            fake.chmod(0o755)
            env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CONFIG_DIR"}
            env.update(HOME=str(home), CLAUDE_CONFIG_DIR=str(home / ".claude"), PATH=f"{fake.parent}:/usr/bin:/bin",
                       PYTHONDONTWRITEBYTECODE="1", FAKE_CLAUDE_RECORD=str(Path(tmp) / "record.jsonl"),
                       FAKE_CLAUDE_ANSWER=json.dumps(test_claudecode.ANSWER))
            proc = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, env=env, timeout=30)
            asked = (Path(tmp) / "record.jsonl").exists()
        out = json.loads(proc.stdout)
        self.assertEqual((proc.returncode, out.get("ok"), out.get("source"), asked), (0, True, "claudecode", True), out)
        self.assertEqual([r["id"] for r in out["rows"]], ["claude:session", "claude:weekly_all", "claude:weekly_scoped:Fable"])


class TestArguments(unittest.TestCase):
    def test_unknown_or_extra_arguments_are_a_usage_error_with_exit_0(self) -> None:
        for args in (["--provider", "gemini"], ["--provider"], ["a.json", "b.json"],
                     ["--source", "endpoint"],  # gone since D18: this helper never reads Claude's login
                     ["--source"], ["--provider", "codex", "--source", "statusline"],
                     ["--provider", "codex", "--claude", "x"]):
            with tempfile.TemporaryDirectory() as tmp:
                proc = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True,
                                      env=dict(os.environ, HOME=tmp, CLAUDE_CONFIG_DIR=tmp, PYTHONDONTWRITEBYTECODE="1"))
            self.assertEqual(proc.returncode, 0, args)
            self.assertEqual(json.loads(proc.stdout)["error"], "usage", args)


if __name__ == "__main__":
    unittest.main()
