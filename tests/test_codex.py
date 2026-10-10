"""Tests for ``fetch_usage.py --provider codex``: Codex asked for its usage over its own app-server protocol.

A fake ``codex`` (a small Python program in the sandbox's PATH) stands in for Codex: it records how it was
started and what it was sent, answers ``initialize`` and then ``account/rateLimits/read`` the way Codex's app
server does (the shape seen live on 2026-10-08, Codex 0.153.1), line by line as a real server does, and exits
on EOF. The real Codex is never run here. HOME, CODEX_HOME and PATH point into a temporary folder.
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
RESET = 1_760_000_000  # epoch seconds; the answer carries reset times as numbers

# What Codex answered on 2026-10-08 (the free plan: one 30-day window), with a second metered limit added the way
# the protocol defines it (``rateLimitsByLimitId``), so the mapping of several limits is covered too.
ANSWER = {"rateLimits": {"limitId": "codex", "limitName": None,
                         "primary": {"usedPercent": 12, "windowDurationMins": 43200, "resetsAt": RESET},
                         "secondary": None, "credits": {"hasCredits": False, "unlimited": False, "balance": None},
                         "individualLimit": None, "spendControlReached": False, "planType": "free",
                         "rateLimitReachedType": None},
          "rateLimitsByLimitId": {
              "codex": {"limitId": "codex", "limitName": None,
                        "primary": {"usedPercent": 12, "windowDurationMins": 43200, "resetsAt": RESET},
                        "secondary": None, "planType": "free"},
              "codex_mini": {"limitId": "codex_mini", "limitName": "GPT-Codex-Mini",
                             "primary": {"usedPercent": 3, "windowDurationMins": 300, "resetsAt": RESET + 60},
                             "secondary": None}},
          "rateLimitResetCredits": None}
# A paid plan's shape: a 5-hour and a weekly window (from the protocol; not seen live).
PLUS = {"rateLimits": {"limitId": "codex", "planType": "plus",
                       "primary": {"usedPercent": 12, "windowDurationMins": 300, "resetsAt": RESET},
                       "secondary": {"usedPercent": 30, "windowDurationMins": 10080, "resetsAt": RESET + 86400}}}

FAKE = r'''#!/usr/bin/env python3
import json, os, subprocess, sys, time
record = os.environ["FAKE_CODEX_RECORD"]
mode = os.environ.get("FAKE_CODEX_MODE", "ok")
answer = json.loads(os.environ["FAKE_CODEX_ANSWER"])
received = []
def log(**extra):
    with open(record, "a", encoding="utf-8") as f:
        f.write(json.dumps(dict(argv=sys.argv[1:], stdin=received, cwd=os.getcwd(), pid=os.getpid(), **extra)) + "\n")
def say(obj):
    print(json.dumps(obj), flush=True)
if mode == "garbage":
    print("this is not json", flush=True)
    print("Error: something broke", file=sys.stderr, flush=True)
    log()
    sys.exit(3)
for line in sys.stdin:  # one line at a time, as a server does; never waits for EOF before answering
    if not line.strip():
        continue
    msg = json.loads(line)
    received.append(msg)
    if msg.get("method") == "initialize":
        say({"id": msg.get("id"), "result": {"userAgent": "fake", "codexHome": os.environ.get("CODEX_HOME", ""),
                                             "platformFamily": "unix", "platformOs": "linux"}})
    elif msg.get("method") == "account/rateLimits/read":
        if mode == "ok":
            log()
            say({"id": msg.get("id"), "result": answer})
        elif mode == "error":
            log()
            say({"id": msg.get("id"), "error": {"code": -32000, "message": "Not logged in"}})
        elif mode == "other-id":
            log()
            say({"id": 99, "result": answer})
            sys.exit(0)
        elif mode == "hang":
            # a launcher script's real program: a child that must die with its parent
            child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
            log(child_pid=child.pid)
            time.sleep(60)
# EOF: the server exits, like the real one
'''


class Sandbox(unittest.TestCase):
    """A temporary HOME with a fake ``codex`` on the PATH."""

    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="cu-codex-"))
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.bin = self.dir / "bin"
        self.bin.mkdir()
        self.fake = self.bin / "codex"
        self.fake.write_text(FAKE, encoding="utf-8")
        self.fake.chmod(0o755)
        # the PATH holds only this folder, so a real codex installed on the machine can never be started by a
        # test; the fake's "env python3" line needs python3 there
        (self.bin / "python3").symlink_to(sys.executable)
        self.record = self.dir / "record.jsonl"
        (self.dir / "home/.codex").mkdir(parents=True)
        self.env = {k: v for k, v in os.environ.items() if k not in ("CODEX_HOME",)}
        self.env.update(HOME=str(self.dir / "home"), CODEX_HOME=str(self.dir / "home/.codex"),
                        PATH=str(self.bin), PYTHONDONTWRITEBYTECODE="1",
                        FAKE_CODEX_RECORD=str(self.record), FAKE_CODEX_ANSWER=json.dumps(ANSWER))

    def login(self) -> None:
        (self.dir / "home/.codex/auth.json").write_text("not read", encoding="utf-8")

    def helper(self, *extra: str, mode: str = "ok") -> dict:
        env = dict(self.env, FAKE_CODEX_MODE=mode)
        done = subprocess.run([sys.executable, str(HELPER), "--provider", "codex", *extra],
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


class TestCodexSource(Sandbox):
    def test_the_plan_window_and_another_metered_limit(self) -> None:
        self.login()
        r = self.helper()
        self.assertTrue(r["ok"], r)
        self.assertEqual([(x["id"], x["label"], x["group"], x["percent"]) for x in r["rows"]],
                         [("codex:primary", "Monthly (30 day)", "weekly", 12.0),
                          ("codex:codex_mini:primary", "Session (5hr) (GPT-Codex-Mini)", "session", 3.0)])
        self.assertEqual((r["source"], r["plan"], r["provider"]), ("codex", "free", "codex"))
        self.assertEqual(r["rows"][0]["resets_at"], "2025-10-09T08:53:20+00:00")

    def test_a_paid_plan_has_two_windows(self) -> None:
        self.login()
        self.env["FAKE_CODEX_ANSWER"] = json.dumps(PLUS)
        r = self.helper()
        self.assertEqual([(x["id"], x["label"], x["percent"]) for x in r["rows"]],
                         [("codex:primary", "Session (5hr)", 12.0), ("codex:secondary", "Weekly (7 day)", 30.0)])
        self.assertEqual(r["plan"], "plus")

    def test_codex_is_started_as_its_app_server_and_sent_three_messages(self) -> None:
        self.login()
        self.helper()
        [run] = self.runs()
        self.assertEqual(run["argv"], ["app-server"])
        sent = run["stdin"]
        self.assertEqual([m.get("method") for m in sent], ["initialize", "initialized", "account/rateLimits/read"])
        self.assertEqual([m.get("id") for m in sent], [1, None, 2], "requests carry ids, the notification none")
        version = json.loads((CODE.parent.parent / "metadata.json").read_text(encoding="utf-8"))["KPlugin"]["Version"]
        self.assertEqual(sent[0]["params"]["clientInfo"], {"name": "ai-session-usage", "version": version})
        self.assertEqual(Path(run["cwd"]).resolve(), Path(tempfile.gettempdir()).resolve(), "not in a project folder")

    def test_no_login_leaves_the_provider_out_without_starting_codex(self) -> None:
        self.assertEqual(self.helper()["error"], "nologin")
        self.assertEqual(self.runs(), [])

    def test_codex_not_found(self) -> None:
        self.login()
        self.fake.unlink()
        r = self.helper()
        self.assertEqual((r["error"], r["message"]), ("nocli", "codex"))

    def test_the_program_setting_is_used(self) -> None:
        self.login()
        other = self.dir / "elsewhere/my-codex"
        other.parent.mkdir()
        self.fake.rename(other)
        self.assertTrue(self.helper("--codex", str(other))["ok"])
        self.assertEqual(self.helper("--codex", str(self.dir / "nope"))["error"], "nocli")

    def test_an_error_answer_is_shown(self) -> None:
        self.login()
        r = self.helper(mode="error")
        self.assertEqual((r["error"], r["message"]), ("cli", "Not logged in"))

    def test_an_answer_to_another_request_is_not_taken(self) -> None:
        self.login()
        r = self.helper(mode="other-id")
        self.assertEqual(r["error"], "cli")
        self.assertTrue(r["message"].startswith("exit 0"), r["message"])

    def test_output_that_is_not_the_protocol_names_the_failure(self) -> None:
        self.login()
        r = self.helper(mode="garbage")
        self.assertEqual(r["error"], "cli")
        self.assertRegex(r["message"], r"^exit 3: Error: something broke$")

    def test_no_windows_in_the_answer_is_a_format_error(self) -> None:
        self.login()
        self.env["FAKE_CODEX_ANSWER"] = json.dumps({"rateLimits": {"limitId": "codex", "planType": "free",
                                                                   "primary": None, "secondary": None}})
        self.assertEqual(self.helper()["error"], "format")

    def test_a_hanging_codex_is_cut_off_with_its_child(self) -> None:
        # in-process, with a short bound, so the test does not wait the full 30 s; the fake stands in for a
        # launcher script whose real program is a child: both must be gone afterwards
        self.login()
        sys.path.insert(0, str(CODE))
        self.addCleanup(sys.path.remove, str(CODE))
        sys.dont_write_bytecode = True  # an in-process import must not leave a __pycache__ in the package (D17)
        import usage_codex
        saved = (usage_codex.TIMEOUT_S, dict(os.environ))
        self.addCleanup(lambda: (setattr(usage_codex, "TIMEOUT_S", saved[0]), os.environ.clear(), os.environ.update(saved[1])))
        usage_codex.TIMEOUT_S = 1
        os.environ.update(dict(self.env, FAKE_CODEX_MODE="hang"))
        started = time.time()
        r = usage_codex.run(self.dir / "home/.codex/auth.json", str(self.fake))
        self.assertEqual(r["error"], "cli")
        self.assertLess(time.time() - started, 10)
        [run] = self.runs()
        for pid in (run["pid"], run["child_pid"]):
            for _ in range(20):
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.1)
            else:
                os.kill(pid, 9)
                self.fail(f"process {pid} survived the timeout")


class TestRows(unittest.TestCase):
    def setUp(self) -> None:
        sys.path.insert(0, str(CODE))
        self.addCleanup(sys.path.remove, str(CODE))
        sys.dont_write_bytecode = True

    def test_the_windows_npm_fallback_is_only_tried_with_appdata_set(self) -> None:
        # without APPDATA (always, off Windows) the candidate must not become a relative path, which Popen
        # would resolve against the helper's working folder
        import usage_codex
        saved = os.environ.pop("APPDATA", None)
        self.addCleanup(lambda: os.environ.update({"APPDATA": saved}) if saved is not None else None)
        self.assertTrue(all(p.is_absolute() for p in usage_codex.fallbacks()), usage_codex.fallbacks())

    def test_without_the_by_id_map_the_plan_limit_alone_is_used(self) -> None:
        import usage_codex
        rows, plan = usage_codex.rows_from_answer({"rateLimits": ANSWER["rateLimits"]})
        self.assertEqual([r["id"] for r in rows], ["codex:primary"])
        self.assertEqual(plan, "free")

    def test_the_plan_limit_comes_first_whatever_the_order(self) -> None:
        import usage_codex
        by_id = {"codex_mini": ANSWER["rateLimitsByLimitId"]["codex_mini"], "codex": ANSWER["rateLimitsByLimitId"]["codex"]}
        rows, _ = usage_codex.rows_from_answer({"rateLimits": ANSWER["rateLimits"], "rateLimitsByLimitId": by_id})
        self.assertEqual([r["id"] for r in rows], ["codex:primary", "codex:codex_mini:primary"])

    def test_junk_windows_are_skipped(self) -> None:
        import usage_codex
        rows, _ = usage_codex.rows_from_answer({"rateLimits": {"limitId": "codex", "primary": "junk",
                                                               "secondary": {"usedPercent": "40"}}})
        self.assertEqual(rows, [])

    def test_window_lengths_name_the_rows(self) -> None:
        import usage_codex
        self.assertEqual(usage_codex.window_label(18000), ("session", "Session (5hr)"))
        self.assertEqual(usage_codex.window_label(604800), ("weekly", "Weekly (7 day)"))
        self.assertEqual(usage_codex.window_label(86400), ("weekly", "1-day"))
        self.assertEqual(usage_codex.window_label(2592000), ("weekly", "Monthly (30 day)"))
        self.assertEqual(usage_codex.window_label(1800), ("session", "Session (30min)"))
        self.assertEqual(usage_codex.window_label(None), ("", "Limit"))


if __name__ == "__main__":
    unittest.main(verbosity=1)
