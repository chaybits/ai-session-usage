"""Tests for the status-line source: statusline_tap.py (Claude Code's status-line command) and
``fetch_usage.py --source statusline`` (the widget's reader).

Both run as subprocesses with HOME, XDG_CACHE_HOME and CLAUDE_CONFIG_DIR in a temporary folder, so no real file
is read or written. The status-line inputs are shaped like the documented one
(https://code.claude.com/docs/en/statusline), with session fields the tap must not keep.
publish-safe:path-placeholders: the /home/someone paths below are made up, part of that documented shape.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
CODE = HERE.parent / "src/contents/code"
TAP = CODE / "statusline_tap.py"
HELPER = CODE / "fetch_usage.py"
NOW = int(time.time())

# A status-line input as Claude Code sends it: session details the tap must drop, and the usage windows.
SESSION = {
    "session_id": "4f2c-secret-session", "transcript_path": "/home/someone/.claude/projects/x/4f2c.jsonl",
    "cwd": "/home/someone/private-project", "model": {"id": "claude-x", "display_name": "X"},
    "cost": {"total_cost_usd": 1.25}, "workspace": {"current_dir": "/home/someone/private-project"},
}
LIMITS = {"five_hour": {"used_percentage": 23.5, "resets_at": NOW + 3600},
          "seven_day": {"used_percentage": 41.2, "resets_at": NOW + 3 * 86400}}


class Sandbox(unittest.TestCase):
    """A temporary HOME and cache folder for each test."""

    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="cu-statusline-"))
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(self.dir)], check=False))
        self.env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CONFIG_DIR", "XDG_CACHE_HOME", "LOCALAPPDATA")}
        self.env.update(HOME=str(self.dir / "home"), XDG_CACHE_HOME=str(self.dir / "cache"),
                        CLAUDE_CONFIG_DIR=str(self.dir / "home/.claude"), PYTHONDONTWRITEBYTECODE="1")
        (self.dir / "home/.claude").mkdir(parents=True)
        self.status = self.dir / "cache/ai-session-usage/claude-statusline.json"

    def tap(self, stdin: str, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(TAP), *args], input=stdin, capture_output=True, text=True,
                              env=self.env, timeout=30)

    def helper(self, *args: str) -> dict:
        done = subprocess.run([sys.executable, str(HELPER), "--provider", "claude", "--source", "statusline", *args],
                              capture_output=True, text=True, env=self.env, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        lines = done.stdout.strip().split("\n")
        self.assertEqual(len(lines), 1, done.stdout)
        self.assertTrue(lines[0].isascii(), lines[0])
        return json.loads(lines[0])

    def login(self, content: str = "{}") -> Path:
        path = self.dir / "home/.claude/.credentials.json"
        path.write_text(content, encoding="utf-8")
        return path


class TestTap(Sandbox):
    def test_keeps_only_the_usage_windows(self) -> None:
        done = self.tap(json.dumps(dict(SESSION, rate_limits=LIMITS)))
        self.assertEqual((done.returncode, done.stdout), (0, "5h 24% · 7d 41%\n"))
        data = json.loads(self.status.read_text(encoding="utf-8"))
        self.assertEqual(set(data), {"captured_at", "rate_limits"})
        self.assertEqual(data["rate_limits"], LIMITS)
        self.assertAlmostEqual(data["captured_at"], time.time(), delta=30)
        text = self.status.read_text(encoding="utf-8")
        for private in ("secret-session", "private-project", "/home/someone", "cost", "claude-x"):
            self.assertNotIn(private, text)

    def test_before_the_first_answer_nothing_is_written(self) -> None:
        # rate_limits appears only after the session's first answer from the server
        done = self.tap(json.dumps(SESSION))
        self.assertEqual((done.returncode, done.stdout), (0, ""))
        self.assertFalse(self.status.exists())

    def test_an_input_without_limits_keeps_the_last_ones(self) -> None:
        self.tap(json.dumps(dict(SESSION, rate_limits=LIMITS)))
        before = self.status.read_text(encoding="utf-8")
        done = self.tap(json.dumps(SESSION))
        self.assertEqual(done.stdout, "5h 24% · 7d 41%\n", "the status bar still shows the last numbers")
        self.assertEqual(self.status.read_text(encoding="utf-8"), before)

    def test_a_window_dropped_after_its_reset_is_kept_then_forgotten(self) -> None:
        # Claude Code drops a window once its reset passes; it is kept (shown as "Reset at"), until 8 days later
        old = {"five_hour": {"used_percentage": 90, "resets_at": NOW - 600},
               "seven_day_opus": {"used_percentage": 5, "resets_at": NOW - 9 * 86400},
               "seven_day": {"used_percentage": 40, "resets_at": NOW + 86400}}
        self.status.parent.mkdir(parents=True)
        self.status.write_text(json.dumps({"captured_at": NOW - 700, "rate_limits": old}), encoding="utf-8")
        self.tap(json.dumps(dict(SESSION, rate_limits={"seven_day": {"used_percentage": 42, "resets_at": NOW + 86400}})))
        kept = json.loads(self.status.read_text(encoding="utf-8"))["rate_limits"]
        self.assertEqual(set(kept), {"five_hour", "seven_day"})
        self.assertEqual(kept["seven_day"]["used_percentage"], 42)

    def test_garbage_never_fails_the_status_line(self) -> None:
        for junk in ("", "not json", "[1, 2]", '{"rate_limits": 5}', '{"rate_limits": {"five_hour": 3}}'):
            done = self.tap(junk)
            self.assertEqual((done.returncode, done.stdout), (0, ""), junk)
        self.assertFalse(self.status.exists())

    def test_an_unwritable_cache_still_prints_the_line(self) -> None:
        (self.dir / "cache").write_text("a file where the folder should be", encoding="utf-8")
        done = self.tap(json.dumps(dict(SESSION, rate_limits=LIMITS)))
        self.assertEqual(done.returncode, 0)
        self.assertIn("statusline_tap:", done.stderr, "the problem is named")

    def test_then_runs_an_earlier_status_line_with_the_same_input(self) -> None:
        done = self.tap(json.dumps(dict(SESSION, rate_limits=LIMITS)), "--quiet", "--then",
                        f"{sys.executable} -c \"import json,sys; print('cwd=' + json.load(sys.stdin)['cwd'])\"")
        self.assertEqual(done.stdout, "cwd=/home/someone/private-project\n")
        self.assertTrue(self.status.exists())

    def test_no_temporary_file_is_left(self) -> None:
        for _ in range(3):
            self.tap(json.dumps(dict(SESSION, rate_limits=LIMITS)))
        self.assertEqual(sorted(p.name for p in self.status.parent.iterdir()), ["claude-statusline.json"])


class TestHelperSource(Sandbox):
    def test_rows_with_the_shared_claude_ids(self) -> None:
        self.login()
        self.tap(json.dumps(dict(SESSION, rate_limits=dict(LIMITS, seven_day_opus={"used_percentage": 7, "resets_at": NOW + 86400}))))
        r = self.helper()
        self.assertTrue(r["ok"], r)
        self.assertEqual([(x["id"], x["label"], x["group"], x["percent"]) for x in r["rows"]],
                         [("claude:session", "Session (5hr)", "session", 23.5),
                          ("claude:weekly_all", "Weekly (7 day)", "weekly", 41.2),
                          ("claude:weekly_scoped:Opus", "Weekly (Opus)", "weekly", 7.0)])
        self.assertEqual(r["rows"][0]["resets_at"][:19],
                         time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(LIMITS["five_hour"]["resets_at"])))
        self.assertAlmostEqual(r["captured_at"], time.time(), delta=30)
        self.assertEqual(r["source"], "statusline")

    def test_an_unknown_window_is_shown_under_its_own_name(self) -> None:
        self.login()
        self.tap(json.dumps(dict(SESSION, rate_limits={"seven_day_cowork": {"used_percentage": 3, "resets_at": NOW + 99}})))
        self.assertEqual([(x["id"], x["label"]) for x in self.helper()["rows"]],
                         [("claude:weekly_scoped:cowork", "Weekly (cowork)")])

    def test_no_claude_code_login_leaves_the_provider_out(self) -> None:
        self.assertEqual(self.helper()["error"], "nologin")

    def test_a_login_but_no_status_line_yet_says_so(self) -> None:
        self.login()
        r = self.helper()
        self.assertEqual(r["error"], "nostatusline")

    def test_the_login_file_is_never_read(self) -> None:
        # only its existence matters: a file Claude Code could not parse changes nothing here
        self.login("not json at all, and no token")
        self.tap(json.dumps(dict(SESSION, rate_limits=LIMITS)))
        self.assertTrue(self.helper()["ok"])

    def test_a_damaged_status_file_is_reported(self) -> None:
        self.login()
        self.status.parent.mkdir(parents=True)
        for junk in ("{", "[]", '{"rate_limits": {}}', '{"captured_at": 1}'):
            self.status.write_text(junk, encoding="utf-8")
            self.assertEqual(self.helper()["error"], "unreadable", junk)

    def test_only_claude_has_this_source(self) -> None:
        done = subprocess.run([sys.executable, str(HELPER), "--provider", "codex", "--source", "statusline"],
                              capture_output=True, text=True, env=self.env, timeout=30)
        self.assertEqual(json.loads(done.stdout)["error"], "usage")


if __name__ == "__main__":
    unittest.main(verbosity=1)
