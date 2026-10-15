namespace AiSessionUsage.Core.Tests;

[TestClass]
public sealed class AnswerTests
{
    private const string Good = """
        {"ok": true, "source": "claudecode", "fetched_at": 1791700000, "plan": "max", "rows": [
          {"id": "claude:session", "provider": "claude", "kind": "session", "group": "session", "label": "Session", "percent": 75, "resets_at": "2026-10-11T16:05:00+00:00"},
          {"id": "claude:weekly_all", "provider": "claude", "kind": "weekly_all", "group": "weekly", "label": "Weekly", "percent": 44.4, "resets_at": null}
        ]}
        """;

    // The helper prints its answer as one line; the fixture above is spread over four for reading.
    private static string OneLine(string json) => json.ReplaceLineEndings("");

    [TestMethod]
    public void Good_answer_gives_rows_in_order()
    {
        Answer a = Answer.Parse(OneLine(Good));
        Assert.IsTrue(a.Ok);
        Assert.AreEqual("", a.Error);
        Assert.AreEqual("max", a.Plan);
        Assert.AreEqual("claudecode", a.Source);
        Assert.IsNull(a.CapturedAt);
        Assert.AreEqual(2, a.Rows.Count);
        Assert.AreEqual("claude:session", a.Rows[0].Id);
        Assert.AreEqual("Session", a.Rows[0].Label);
        Assert.AreEqual("session", a.Rows[0].Group);
        Assert.AreEqual(75.0, a.Rows[0].Percent);
        Assert.AreEqual(new DateTimeOffset(2026, 10, 11, 16, 5, 0, TimeSpan.Zero), a.Rows[0].ResetsAt);
        Assert.AreEqual(44.4, a.Rows[1].Percent);
        Assert.IsNull(a.Rows[1].ResetsAt);
    }

    [TestMethod]
    public void Only_the_last_line_is_the_answer()
    {
        Answer a = Answer.Parse("some stray line\n" + OneLine(Good) + "\n\n");
        Assert.IsTrue(a.Ok);
        Assert.AreEqual(2, a.Rows.Count);
    }

    [TestMethod]
    public void A_line_broken_answer_is_bad_output_not_a_guess()
    {
        // Only the last line is read: a multi-line object is not the helper's contract and must not pass as an answer.
        Assert.AreEqual(Answer.BadOutputKind, Answer.Parse(Good).Error);
    }

    [TestMethod]
    public void Error_answer_keeps_kind_and_message()
    {
        Answer a = Answer.Parse("""{"ok": false, "error": "nocli", "message": "codex"}""");
        Assert.IsFalse(a.Ok);
        Assert.AreEqual("nocli", a.Error);
        Assert.AreEqual("codex", a.Message);
        Assert.AreEqual(0, a.Rows.Count);
    }

    [TestMethod]
    public void Nothing_is_a_timeout()
    {
        Assert.AreEqual(Answer.TimeoutKind, Answer.Parse(null).Error);
        Assert.AreEqual(Answer.TimeoutKind, Answer.Parse("  \n").Error);
    }

    [TestMethod]
    public void Garbage_is_bad_output_with_a_short_message()
    {
        Answer a = Answer.Parse("Traceback (most recent call last): " + new string('x', 200));
        Assert.AreEqual(Answer.BadOutputKind, a.Error);
        Assert.AreEqual(80, a.Message.Length);
        Assert.AreEqual(Answer.BadOutputKind, Answer.Parse("[1, 2]").Error);
        Assert.AreEqual(Answer.BadOutputKind, Answer.Parse("""{"ok": true}""").Error);
        Assert.AreEqual(Answer.BadOutputKind, Answer.Parse("""{"ok": "yes", "rows": []}""").Error);
    }

    [TestMethod]
    public void Rows_without_label_or_number_are_skipped()
    {
        Answer a = Answer.Parse("""{"ok": true, "rows": [{"label": "A", "percent": "9"}, {"percent": 1}, {"label": "B", "percent": true}, {"label": "C", "percent": 3}, 7]}""");
        Assert.IsTrue(a.Ok);
        Assert.AreEqual(1, a.Rows.Count);
        Assert.AreEqual("C", a.Rows[0].Label);
    }

    [TestMethod]
    public void Status_line_capture_time_is_read()
    {
        Answer a = Answer.Parse("""{"ok": true, "source": "statusline", "captured_at": 1791700000, "rows": []}""");
        Assert.AreEqual(DateTimeOffset.FromUnixTimeSeconds(1791700000), a.CapturedAt);
    }

    [TestMethod]
    public void Iso_times_with_offsets_become_instants()
    {
        Assert.AreEqual(new DateTimeOffset(2026, 10, 11, 13, 5, 0, TimeSpan.Zero),
                        Answer.ParseIso("2026-10-11T16:05:00+03:00")!.Value.ToUniversalTime());
        Assert.IsNull(Answer.ParseIso("soon"));
        Assert.IsNull(Answer.ParseIso(null));
    }

    [TestMethod]
    public void Turkish_letters_survive_the_helpers_escaped_json()
    {
        // The helper prints pure ASCII (ensure_ascii), so non-ASCII text arrives as \uXXXX escapes and must come back whole (D2).
        string line = """{"ok": true, "rows": [{"label": "Haftal\u0131k (7 g\u00fcn) \u015f\u011f\u00f6\u00e7 \u0130\u015e\u011e\u00d6\u00dc\u00c7", "percent": 5}]}""";
        Answer a = Answer.Parse(line);
        Assert.IsTrue(a.Ok);
        Assert.AreEqual("Haftalık (7 gün) şğöç İŞĞÖÜÇ", a.Rows[0].Label);
    }
}
