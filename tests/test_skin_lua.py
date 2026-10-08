"""Tests for the Rainmeter skin's script under lua5.1 (the Lua Rainmeter embeds), through tests/skin_harness.lua,
which stands in for Rainmeter: the JSON reader, the reset texts, the layout of rows and sections, the parameters
the script hands the helper, and the bangs an answer produces. Skipped without lua5.1 (or a 5.1-compatible luajit)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "rainmeter/AiSessionUsage/@Resources/Scripts/AiSessionUsage.lua"
HARNESS = HERE / "skin_harness.lua"
LUA = shutil.which("lua5.1") or shutil.which("luajit")
NOW = 1_760_000_000  # 2025-10-09T08:53:20+00:00


def lua(*args: str, env: dict | None = None) -> str:
    done = subprocess.run([LUA, str(HARNESS), str(SCRIPT), *args], capture_output=True, text=True, timeout=30,
                          env=dict(os.environ, TZ="Europe/Istanbul", **(env or {})))
    if done.returncode != 0:
        raise AssertionError(f"lua failed: {done.stderr}")
    return done.stdout.rstrip("\n")


def answer(provider: str, at: int, rows: list[dict], ok: bool = True, **extra: object) -> str:
    body = {"ok": ok, "rows": rows} if ok else {"ok": False, **extra}
    return f"answer:{provider}:{at}:{json.dumps(body)}"


def layout(*args: str) -> list[list[str]]:
    return [line.split("\t") for line in lua("layout", f"var:now={NOW}", *args).splitlines()]


CLAUDE_ROWS = [{"id": "claude:session", "label": "Session (5hr)", "percent": 34, "resets_at": "2025-10-09T10:53:20+00:00"},
               {"id": "claude:weekly_all", "label": "Weekly (7 day)", "percent": 86.4, "resets_at": "2025-10-12T08:53:20+00:00"},
               {"id": "claude:weekly_scoped:Fable", "label": "Weekly (Fable)", "percent": 97, "resets_at": None}]
CODEX_ROWS = [{"id": "codex:primary", "label": "Monthly (30 day)", "percent": 12, "resets_at": "2025-11-01T00:00:00+00:00"}]


@unittest.skipUnless(LUA, "SKIPPED: no lua5.1 or luajit, the skin's script was not run")
class TestJson(unittest.TestCase):
    def test_the_helpers_shape_round_trips(self) -> None:
        text = json.dumps({"ok": True, "rows": [{"label": "Weekly (\u015eiir)", "percent": 12.5, "resets_at": None}],
                           "plan": "free", "n": -3e2, "t": True, "f": False, "e": [], "o": {}})
        self.assertTrue(text.isascii())
        out = lua("json", text)
        self.assertEqual(out, "{e={},f=false,n=-300,o={},ok=true,plan=free,rows={1={label=Weekly (\u015eiir),percent=12.5,resets_at=null}},t=true}")

    def test_escapes_and_surrogate_pairs(self) -> None:
        self.assertEqual(lua("json", r'"a\"b\\c\n\u00e7\ud83d\ude00"'), 'a"b\\c\n\u00e7\U0001F600')

    def test_garbage_fails_loudly(self) -> None:
        done = subprocess.run([LUA, str(HARNESS), str(SCRIPT), "json", "{\"a\": }"], capture_output=True, text=True)
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("json:", done.stderr)


@unittest.skipUnless(LUA, "SKIPPED: no lua5.1 or luajit, the skin's script was not run")
class TestResetText(unittest.TestCase):
    def test_hours_minutes_and_the_clock_time(self) -> None:
        # now is 11:53:20 in Istanbul (UTC+3); the reset at 13:53:20 local
        self.assertEqual(lua("reset", "2025-10-09T10:53:20+00:00", str(NOW)), "Resets in 2h 0m \u00b7 13:53")

    def test_days_show_the_weekday_then_the_date(self) -> None:
        self.assertEqual(lua("reset", "2025-10-12T08:53:20+00:00", str(NOW)), "Resets in 3d 0h \u00b7 Sun 11:53")
        self.assertEqual(lua("reset", "2025-11-01T00:00:00+00:00", str(NOW)), "Resets in 22d 15h \u00b7 01 Nov")

    def test_now_past_and_missing(self) -> None:
        self.assertEqual(lua("reset", "2025-10-09T08:53:30+00:00", str(NOW)), "Resets now")
        self.assertEqual(lua("reset", "2025-10-09T08:00:00+00:00", str(NOW)), "Reset passed")
        self.assertEqual(lua("reset", "junk", str(NOW)), "")

    def test_a_fractional_second_and_a_z_suffix_are_read(self) -> None:
        self.assertEqual(lua("reset", "2025-10-09T10:53:20.123456Z", str(NOW)), "Resets in 2h 0m \u00b7 13:53")


@unittest.skipUnless(LUA, "SKIPPED: no lua5.1 or luajit, the skin's script was not run")
class TestLayout(unittest.TestCase):
    def test_two_sections_with_rows_bars_and_colours(self) -> None:
        items = layout(answer("claude", NOW - 60, CLAUDE_ROWS), answer("codex", NOW - 30, CODEX_ROWS))
        kinds = [i[0] for i in items]
        self.assertEqual(kinds[:1], ["show"])
        self.assertEqual(items[0][1:4], ["Head1", "38", "Claude"])
        rows = [i for i in items if i[0] == "row"]
        self.assertEqual([r[1] for r in rows], ["Row1", "Row2", "Row3", "Row4"])
        self.assertEqual([r[3] for r in rows], ["Session (5hr)", "Weekly (7 day)", "Weekly (Fable)", "Monthly (30 day)"])
        self.assertEqual([r[4] for r in rows], ["34%", "86%", "97%", "12%"])
        self.assertEqual([r[6] for r in rows], ["61,174,233", "246,116,0", "218,68,83", "61,174,233"], "accent, warn, critical")
        self.assertEqual(rows[2][8], "", "no reset time: empty text")
        self.assertTrue(rows[0][8].startswith("Resets in 2h 0m"))
        self.assertEqual([r[10] for r in rows], ["false"] * 4, "nothing dimmed")
        self.assertEqual([i[1] for i in items if i[0] == "hiderow"], ["Row5", "Row6", "Row7", "Row8"])
        footer = [i for i in items if i[0] == "footer"][0]
        self.assertTrue(footer[2].startswith("Updated 11:52 \u00b7 click to refresh"), footer)
        self.assertEqual(int(items[-1][1]), int(footer[1]) + 22)
        second = [i for i in items if i[0] == "show"][1]
        self.assertEqual(second[1:4][0], "Head2")
        self.assertGreater(int(second[2]), int(rows[2][2]), "ChatGPT's header below Claude's last row")

    def test_a_provider_without_a_login_is_left_out(self) -> None:
        items = layout(answer("claude", NOW, CLAUDE_ROWS), answer("codex", NOW, [], ok=False, error="nologin", message="x"))
        self.assertIn(["hide", "Head2"], items)
        self.assertEqual(len([i for i in items if i[0] == "row"]), 3)

    def test_an_error_keeps_the_last_good_rows_dimmed_and_says_why(self) -> None:
        items = layout(answer("claude", NOW - 400, CLAUDE_ROWS), answer("claude", NOW, [], ok=False, error="cli", message="exit 3"))
        rows = [i for i in items if i[0] == "row"]
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0][10], "true", "dimmed")
        status = [i for i in items if i[0] == "status"][0]
        self.assertEqual(status[1:4][0], "Status1")
        self.assertEqual(status[3], "Claude Code could not tell the usage: exit 3")

    def test_old_numbers_turn_stale(self) -> None:
        items = layout(answer("claude", NOW - 20 * 60, CLAUDE_ROWS))
        rows = [i for i in items if i[0] == "row"]
        self.assertEqual(rows[0][7], "253,188,75", "the percentage in the stale colour")
        self.assertEqual(rows[0][6], "61,174,233", "the bar keeps the level colour")

    def test_nothing_yet_and_no_login_anywhere(self) -> None:
        self.assertEqual([i for i in layout() if i[0] == "footer"][0][2], "Loading")
        items = layout(answer("claude", NOW, [], ok=False, error="nologin", message="x"),
                       answer("codex", NOW, [], ok=False, error="nologin", message="x"))
        self.assertEqual([i for i in items if i[0] == "footer"][0][2], "No Claude Code or Codex login found")

    def test_a_hidden_provider_is_not_shown(self) -> None:
        items = layout("var:ShowCodex=0", answer("claude", NOW, CLAUDE_ROWS), answer("codex", NOW, CODEX_ROWS))
        self.assertEqual(len([i for i in items if i[0] == "row"]), 3)

    def test_more_rows_than_meters_are_cut_at_eight(self) -> None:
        many = [{"label": f"L{i}", "percent": i} for i in range(12)]
        self.assertEqual(len([i for i in layout(answer("claude", NOW, many)) if i[0] == "row"]), 8)


@unittest.skipUnless(LUA, "SKIPPED: no lua5.1 or luajit, the skin's script was not run")
class TestRainmeterSide(unittest.TestCase):
    def test_initialize_hands_the_helper_its_arguments(self) -> None:
        out = lua("init", "var:ClaudeSource=statusline", "var:CodexProgram=C:\\tools\\codex.cmd").splitlines()
        self.assertEqual(out, [
            'BANG\t!SetOption\tmClaude\tParameter\t-B "C:\\Skins\\AiSessionUsage\\@Resources\\code\\fetch_usage.py" --provider claude --source statusline',
            'BANG\t!SetOption\tmCodex\tParameter\t-B "C:\\Skins\\AiSessionUsage\\@Resources\\code\\fetch_usage.py" --provider codex --codex "C:\\tools\\codex.cmd"'])

    def test_an_answer_sets_the_meters_and_redraws(self) -> None:
        out = lua("answer", "mClaude", json.dumps({"ok": True, "rows": CLAUDE_ROWS})).splitlines()
        self.assertIn("BANG\t!SetOption\tRow1Label\tText\tSession (5hr)", out)
        self.assertIn("BANG\t!SetOption\tmRow1\tFormula\t34", out)
        self.assertIn("BANG\t!UpdateMeasure\tmRow1", out)
        self.assertIn("BANG\t!ShowMeter\tRow3Bar", out)
        self.assertIn("BANG\t!HideMeter\tRow4Bar", out)
        self.assertEqual(out[-2:], ["BANG\t!UpdateMeter\t*", "BANG\t!Redraw"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
