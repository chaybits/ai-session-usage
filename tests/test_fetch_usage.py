"""Tests for the usage helper's entry point and the shared row logic in src/contents/code/ (stdlib unittest).

The helper runs as a subprocess so exit code and stdout are asserted for real. Since 2026-10-08 it talks to no
server and reads no login (ARCHITECTURE D18, D20): each CLI is asked over its own protocol, covered by
test_claudecode.py and test_codex.py with fake programs. Here: Claude's rows as a function, the arguments, and
direct runs of the script that either get no login (so no CLI is started) or a fake ``claude`` on a sandbox
PATH with HOME in the sandbox (the real one is also looked for under ~/.local/bin); the real CLIs never run.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PKG = HERE.parent / "src"
CODE = PKG / "contents" / "code"
SCRIPT = CODE / "fetch_usage.py"
sys.path.insert(0, str(CODE))
sys.dont_write_bytecode = True  # a test run must not leave a __pycache__ in the package
import usage_claude  # noqa: E402
import usage_common  # noqa: E402
import test_claudecode  # noqa: E402  (beside this file: the fake claude and its answer)


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


class TestCommon(unittest.TestCase):
    def test_emit_refuses_nan_instead_of_printing_invalid_json(self) -> None:
        with self.assertRaises(ValueError):
            usage_common.emit({"ok": True, "x": float("nan")})

    def test_turkish_text_survives_the_ascii_output(self) -> None:
        # emit writes pure ASCII (the widget's JSON.parse reads the escapes); the label must come back whole
        label = "Haftalık (Şiir ğüş ıİ öç)"
        line = json.dumps({"label": label}, ensure_ascii=True)
        self.assertTrue(line.isascii())
        self.assertEqual(json.loads(line)["label"], label)

    def test_package_version_is_the_one_in_metadata(self) -> None:
        version = json.loads((PKG / "metadata.json").read_text(encoding="utf-8"))["KPlugin"]["Version"]
        self.assertEqual(usage_common.package_version(), version)

    def test_a_reset_time_outside_the_platform_range_is_unknown(self) -> None:
        self.assertIsNone(usage_common.iso_from_epoch(1e30))
        self.assertIsNone(usage_common.iso_from_epoch("1760000000"))
        self.assertEqual(usage_common.iso_from_epoch(1_760_000_000), "2025-10-09T08:53:20+00:00")


class TestDirectScript(unittest.TestCase):
    """The script run the way the widget runs it (python3 file.py ...)."""

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

    def test_codex_home_is_used_without_a_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, HOME=tmp, CODEX_HOME=tmp, PYTHONDONTWRITEBYTECODE="1")
            proc = subprocess.run([sys.executable, str(SCRIPT), "--provider", "codex"], capture_output=True, text=True, env=env)
        out = json.loads(proc.stdout)
        self.assertEqual((proc.returncode, out["error"]), (0, "nologin"))
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
    def test_unknown_or_misplaced_arguments_are_a_usage_error_with_exit_0(self) -> None:
        for args in (["--provider", "gemini"], ["--provider"], ["a.json", "b.json"],
                     ["--source", "endpoint"],  # gone since D18: this helper never reads Claude's login
                     ["--source"], ["--provider", "codex", "--source", "statusline"],
                     ["--provider", "codex", "--claude", "x"], ["--provider", "claude", "--codex", "x"], ["--codex"]):
            with tempfile.TemporaryDirectory() as tmp:
                proc = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True,
                                      env=dict(os.environ, HOME=tmp, CLAUDE_CONFIG_DIR=tmp, CODEX_HOME=tmp,
                                               PYTHONDONTWRITEBYTECODE="1"))
            self.assertEqual(proc.returncode, 0, args)
            self.assertEqual(json.loads(proc.stdout)["error"], "usage", args)


if __name__ == "__main__":
    unittest.main()
