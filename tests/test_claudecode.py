"""Tests for ``fetch_usage.py --source claudecode``: Claude Code asked for its usage, headless.

A fake ``claude`` (a small Python program in the sandbox's PATH) stands in for Claude Code: it records how it
was started and what it was sent, then answers the ``get_usage`` control request the way Claude Code does (the
shape seen live on 2026-10-07). The real Claude Code is never run here. HOME, CLAUDE_CONFIG_DIR and PATH point
into a temporary folder.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
CODE = HERE.parent / "src/contents/code"
HELPER = CODE / "fetch_usage.py"
RESET = "2026-10-09T19:00:00.339564+00:00"

# What Claude Code answered on 2026-10-07, trimmed to the parts the helper reads plus a few it ignores.
ANSWER = {"subscription_type": "max", "rate_limits_available": True, "behaviors": {}, "session": {},
          "rate_limits": {
              "five_hour": {"utilization": 75, "resets_at": "2026-10-07T21:30:00.339545+00:00"},
              "seven_day": {"utilization": 44, "resets_at": RESET},
              "seven_day_opus": None,
              "limits": [
                  {"kind": "session", "group": "session", "percent": 75, "resets_at": "2026-10-07T21:30:00.339545+00:00",
                   "scope": None},
                  {"kind": "weekly_all", "group": "weekly", "percent": 44, "resets_at": RESET, "scope": None},
                  {"kind": "weekly_scoped", "group": "weekly", "percent": 34, "resets_at": RESET,
                   "scope": {"model": {"id": None, "display_name": "Fable"}, "surface": None}}],
              "model_scoped": [{"display_name": "Fable", "utilization": 34, "resets_at": RESET}]}}

FAKE = r'''#!/usr/bin/env python3
import json, os, sys, time
record = os.environ["FAKE_CLAUDE_RECORD"]
mode = os.environ.get("FAKE_CLAUDE_MODE", "ok")
stdin = sys.stdin.read()
with open(record, "a", encoding="utf-8") as f:
    f.write(json.dumps({"argv": sys.argv[1:], "stdin": stdin, "cwd": os.getcwd()}) + "\n")
answer = json.loads(os.environ["FAKE_CLAUDE_ANSWER"])
rid = json.loads(stdin.splitlines()[0])["request_id"] if stdin.strip() else ""
print(json.dumps({"type": "system", "subtype": "init", "session_id": "x"}))
if mode == "ok":
    print(json.dumps({"type": "control_response", "response": {"subtype": "success", "request_id": rid, "response": answer}}))
elif mode == "error":
    print(json.dumps({"type": "control_response", "response": {"subtype": "error", "request_id": rid, "error": "Not logged in"}}))
elif mode == "other-id":
    print(json.dumps({"type": "control_response", "response": {"subtype": "success", "request_id": "someone-else", "response": answer}}))
elif mode == "garbage":
    print("this is not json")
    print("Error: something broke", file=sys.stderr)
    sys.exit(3)
elif mode == "hang":
    time.sleep(60)
'''


class Sandbox(unittest.TestCase):
    """A temporary HOME with a fake ``claude`` on the PATH."""

    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="cu-claudecode-"))
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.bin = self.dir / "bin"
        self.bin.mkdir()
        self.fake = self.bin / "claude"
        self.fake.write_text(FAKE, encoding="utf-8")
        self.fake.chmod(0o755)
        # the PATH holds only this folder, so a real claude installed on the machine can never be started by a
        # test; the fake's "env python3" line needs python3 there
        (self.bin / "python3").symlink_to(sys.executable)
        self.record = self.dir / "record.jsonl"
        (self.dir / "home/.claude").mkdir(parents=True)
        self.env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CONFIG_DIR",)}
        self.env.update(HOME=str(self.dir / "home"), CLAUDE_CONFIG_DIR=str(self.dir / "home/.claude"),
                        PATH=str(self.bin), PYTHONDONTWRITEBYTECODE="1",
                        FAKE_CLAUDE_RECORD=str(self.record), FAKE_CLAUDE_ANSWER=json.dumps(ANSWER))

    def login(self) -> None:
        (self.dir / "home/.claude/.credentials.json").write_text("not read", encoding="utf-8")

    def helper(self, *extra: str, mode: str = "ok") -> dict:
        env = dict(self.env, FAKE_CLAUDE_MODE=mode)
        done = subprocess.run([sys.executable, str(HELPER), "--provider", "claude", "--source", "claudecode", *extra],
                              capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        lines = done.stdout.strip().split("\n")
        self.assertEqual(len(lines), 1, done.stdout)
        self.assertTrue(lines[0].isascii(), lines[0])
        return json.loads(lines[0])

    def runs(self) -> list[dict]:
        if not self.record.exists():
            return []
        return [json.loads(line) for line in self.record.read_text(encoding="utf-8").splitlines()]


class TestClaudeCodeSource(Sandbox):
    def test_the_full_usage_with_the_per_model_cap(self) -> None:
        self.login()
        r = self.helper()
        self.assertTrue(r["ok"], r)
        self.assertEqual([(x["id"], x["label"], x["percent"]) for x in r["rows"]],
                         [("claude:session", "Session (5hr)", 75.0), ("claude:weekly_all", "Weekly (7 day)", 44.0),
                          ("claude:weekly_scoped:Fable", "Weekly (Fable)", 34.0)])
        self.assertEqual((r["source"], r["plan"]), ("claudecode", "max"))

    def test_claude_code_is_started_headless_with_no_side_effects(self) -> None:
        self.login()
        self.helper()
        [run] = self.runs()
        argv = run["argv"]
        for flag in ("-p", "--no-session-persistence", "--strict-mcp-config", "--disable-slash-commands"):
            self.assertIn(flag, argv)
        self.assertEqual(argv[argv.index("--settings") + 1], '{"disableAllHooks":true}', "no hook may fire")
        self.assertEqual(argv[argv.index("--mcp-config") + 1], '{"mcpServers":{}}', "no MCP server may start")
        self.assertEqual(argv[argv.index("--input-format") + 1], "stream-json")
        sent = [json.loads(line) for line in run["stdin"].splitlines() if line.strip()]
        self.assertEqual(sent, [{"type": "control_request", "request_id": "ai-session-usage",
                                 "request": {"subtype": "get_usage"}}], "one usage request and no prompt")
        self.assertEqual(Path(run["cwd"]).resolve(), Path(tempfile.gettempdir()).resolve(), "not in a project folder")

    def test_no_login_leaves_the_provider_out_without_starting_claude_code(self) -> None:
        self.assertEqual(self.helper()["error"], "nologin")
        self.assertEqual(self.runs(), [])

    def test_claude_code_not_found(self) -> None:
        self.login()
        self.fake.unlink()
        r = self.helper()
        self.assertEqual((r["error"], r["message"]), ("nocli", "claude"))

    def test_the_program_setting_is_used(self) -> None:
        self.login()
        other = self.dir / "elsewhere/my-claude"
        other.parent.mkdir()
        self.fake.rename(other)
        self.assertTrue(self.helper("--claude", str(other))["ok"])
        self.assertEqual(self.helper("--claude", str(self.dir / "nope"))["error"], "nocli")

    def test_an_error_answer_is_shown(self) -> None:
        self.login()
        r = self.helper(mode="error")
        self.assertEqual((r["error"], r["message"]), ("cli", "Not logged in"))

    def test_an_answer_to_another_request_is_not_taken(self) -> None:
        self.login()
        self.assertEqual(self.helper(mode="other-id")["error"], "cli")

    def test_output_that_is_not_the_protocol_names_the_failure(self) -> None:
        self.login()
        r = self.helper(mode="garbage")
        self.assertEqual(r["error"], "cli")
        self.assertRegex(r["message"], r"^exit 3: Error: something broke$")

    def test_no_subscription_means_no_limits(self) -> None:
        # logged in with an API key: Claude Code says rate limits are not available
        self.login()
        self.env["FAKE_CLAUDE_ANSWER"] = json.dumps({"rate_limits_available": False, "rate_limits": None})
        self.assertEqual(self.helper()["error"], "nologin")

    def test_an_answer_without_rate_limits_is_an_unexpected_answer(self) -> None:
        # a shape change (the key renamed, say) must read "Unexpected answer", not hide the section as "no login"
        self.login()
        self.env["FAKE_CLAUDE_ANSWER"] = json.dumps({"rate_limits_available": True, "limits_v2": {}})
        r = self.helper()
        self.assertEqual(r["error"], "format", r)

    def test_without_a_limits_list_the_classic_windows_are_used(self) -> None:
        self.login()
        self.env["FAKE_CLAUDE_ANSWER"] = json.dumps({"rate_limits_available": True, "rate_limits": {
            "five_hour": {"utilization": 10, "resets_at": RESET}, "seven_day": {"utilization": 20, "resets_at": RESET}}})
        r = self.helper()
        # the same ids as the limits list and the status line give, so a hidden or moved row stays that row
        self.assertEqual([(x["id"], x["percent"]) for x in r["rows"]], [("claude:session", 10.0), ("claude:weekly_all", 20.0)])

    def test_a_hanging_claude_code_is_cut_off(self) -> None:
        # in-process, with a short bound, so the test does not wait the full 40 s
        self.login()
        sys.path.insert(0, str(CODE))
        self.addCleanup(sys.path.remove, str(CODE))
        sys.dont_write_bytecode = True  # an in-process import must not leave a __pycache__ in the package (D17)
        import usage_claudecode
        saved = (usage_claudecode.TIMEOUT_S, dict(os.environ))
        self.addCleanup(lambda: (setattr(usage_claudecode, "TIMEOUT_S", saved[0]), os.environ.clear(), os.environ.update(saved[1])))
        usage_claudecode.TIMEOUT_S = 1
        os.environ.update(dict(self.env, FAKE_CLAUDE_MODE="hang"))
        started = time.time()
        r = usage_claudecode.run(self.dir / "home/.claude/.credentials.json", str(self.fake))
        self.assertEqual(r["error"], "cli")
        self.assertLess(time.time() - started, 10)


if __name__ == "__main__":
    unittest.main(verbosity=1)
