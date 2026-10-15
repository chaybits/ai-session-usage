using System.Text;
using System.Text.Json.Nodes;

namespace AiSessionUsage.Core.Tests;

[TestClass]
public sealed class CardTests
{
    private static readonly DateTimeOffset Now = new(2026, 10, 11, 12, 0, 0, TimeSpan.Zero);
    private static readonly TimeZoneInfo Utc = TimeZoneInfo.Utc;
    private static readonly CardOptions Options = new();

    private static ProviderState Claude() => new() { Id = "claude", Name = "Claude", Cli = "Claude Code" };
    private static ProviderState Codex() => new() { Id = "codex", Name = "ChatGPT", Cli = "Codex" };

    private static Answer Rows(params (string label, double percent)[] rows)
    {
        string items = string.Join(",", rows.Select(r =>
            $$"""{"id": "x:{{r.label}}", "label": "{{r.label}}", "group": "session", "percent": {{r.percent.ToString(System.Globalization.CultureInfo.InvariantCulture)}}, "resets_at": "2026-10-11T14:13:00+00:00"}"""));
        return Answer.Parse($$"""{"ok": true, "rows": [{{items}}]}""");
    }

    private static JsonObject Build(IReadOnlyList<ProviderState> providers, CardSize size = CardSize.Large,
                                    DateTimeOffset? now = null, bool updating = false)
    {
        var request = new CardRequest(size, now ?? Now, Utc, Options, updating);
        return (JsonObject)JsonNode.Parse(Card.BuildData(providers, request))!;
    }

    private static string Svg(string dataUri)
    {
        const string prefix = "data:image/svg+xml;base64,";
        Assert.IsTrue(dataUri.StartsWith(prefix, StringComparison.Ordinal), dataUri);
        return Encoding.ASCII.GetString(Convert.FromBase64String(dataUri[prefix.Length..]));
    }

    [TestMethod]
    public void Nothing_answered_yet_is_loading()
    {
        JsonObject d = Build([Claude(), Codex()]);
        Assert.AreEqual(0, d["sections"]!.AsArray().Count);
        Assert.AreEqual(Card.LoadingNotice, (string)d["notice"]!);
        Assert.IsTrue((bool)d["hasNotice"]!);
        Assert.IsFalse((bool)d["hasHint"]!);
        Assert.IsFalse((bool)d["hasFooter"]!);
    }

    [TestMethod]
    public void A_provider_with_no_login_is_left_out_and_both_give_the_notice()
    {
        ProviderState claude = Claude();
        ProviderState codex = Codex();
        claude.Take(Rows(("Session", 75)), Now);
        codex.Take(Answer.Parse("""{"ok": false, "error": "nologin", "message": "auth.json not found"}"""), Now);
        JsonObject d = Build([claude, codex]);
        JsonArray sections = d["sections"]!.AsArray();
        Assert.AreEqual(1, sections.Count);
        Assert.AreEqual("Claude", (string)sections[0]!["name"]!);
        Assert.IsFalse((bool)d["hasNotice"]!);
        Assert.AreEqual("Updated 12:00 · click to refresh", (string)d["footer"]!);

        ProviderState claude2 = Claude();
        claude2.Take(Answer.Parse("""{"ok": false, "error": "nologin", "message": "x"}"""), Now);
        JsonObject e = Build([claude2, codex]);
        Assert.AreEqual(0, e["sections"]!.AsArray().Count);
        Assert.AreEqual(Card.NoLoginNotice, (string)e["notice"]!);
        Assert.AreEqual(Card.NoLoginHint, (string)e["hint"]!);
        Assert.IsTrue((bool)e["hasHint"]!);
        Assert.IsFalse((bool)d["hasHint"]!);
    }

    [TestMethod]
    public void Levels_are_judged_on_the_printed_number()
    {
        ProviderState claude = Claude();
        claude.Take(Rows(("A", 79.4), ("B", 79.5), ("C", 94.4), ("D", 94.5), ("E", 100)), Now);
        JsonArray rows = Build([claude])["sections"]![0]!["rows"]!.AsArray();
        Assert.AreEqual("79%", (string)rows[0]!["percent"]!);
        Assert.AreEqual("80%", (string)rows[1]!["percent"]!);
        Assert.AreEqual("100 percent used", (string)rows[4]!["alt"]!);
        StringAssert.Contains(Svg((string)rows[0]!["bar"]!), "fill='#3daee9'");
        StringAssert.Contains(Svg((string)rows[1]!["bar"]!), "fill='#f67400'");
        StringAssert.Contains(Svg((string)rows[2]!["bar"]!), "fill='#f67400'");
        StringAssert.Contains(Svg((string)rows[3]!["bar"]!), "fill='#da4453'");
        Assert.AreEqual("attention", Card.Level(94.5, Options));
        Assert.AreEqual("warning", Card.Level(94.4, Options));
        Assert.AreEqual("accent", Card.Level(79.4, Options));
    }

    [TestMethod]
    public void The_bar_fills_its_share_and_draws_no_fill_at_zero()
    {
        string half = Svg(Card.BarImage(50, "accent"));
        StringAssert.Contains(half, "<rect width='200' height='6' rx='3' fill='#808080' fill-opacity='0.35'/>");
        StringAssert.Contains(half, "<rect width='100' height='6' rx='3' fill='#3daee9'/>");
        string empty = Svg(Card.BarImage(0, "accent"));
        Assert.AreEqual(1, empty.Split("<rect").Length - 1, empty);
        StringAssert.Contains(Svg(Card.BarImage(150, "warning")), "<rect width='200' height='6' rx='3' fill='#f67400'/>");
        StringAssert.Contains(Svg(Card.BarImage(-5, "warning")), "fill-opacity");
        StringAssert.Contains(Svg(Card.BarImage(40, "nonsense")), "fill='#3daee9'");
    }

    [TestMethod]
    public void Sizes_decide_rows_labels_and_the_reset_text()
    {
        ProviderState claude = Claude();
        ProviderState codex = Codex();
        claude.Take(Rows(("Session", 1), ("Weekly", 2), ("Fable", 3)), Now);
        codex.Take(Rows(("Session", 4), ("Weekly", 5)), Now);

        JsonObject small = Build([claude, codex], CardSize.Small);
        JsonObject smallClaude = (JsonObject)small["sections"]![0]!;
        Assert.AreEqual(1, smallClaude["rows"]!.AsArray().Count);
        Assert.AreEqual("Claude", (string)smallClaude["rows"]![0]!["label"]!);
        Assert.IsFalse((bool)smallClaude["showName"]!);
        Assert.AreEqual("2h 13m", (string)smallClaude["rows"]![0]!["when"]!);
        Assert.IsFalse((bool)small["hasFooter"]!);

        JsonObject medium = Build([claude, codex], CardSize.Medium);
        JsonObject mediumClaude = (JsonObject)medium["sections"]![0]!;
        Assert.AreEqual(2, mediumClaude["rows"]!.AsArray().Count);
        Assert.AreEqual("Weekly", (string)mediumClaude["rows"]![1]!["label"]!);
        Assert.IsTrue((bool)mediumClaude["showName"]!);
        Assert.AreEqual("2h 13m", (string)mediumClaude["rows"]![0]!["when"]!);
        Assert.IsFalse((bool)medium["hasFooter"]!);

        JsonObject large = Build([claude, codex], CardSize.Large);
        Assert.AreEqual(3, large["sections"]![0]!["rows"]!.AsArray().Count);
        Assert.AreEqual(2, large["sections"]![1]!["rows"]!.AsArray().Count);
        Assert.AreEqual("2h 13m · 14:13", (string)large["sections"]![0]!["rows"]![0]!["when"]!);
        Assert.IsTrue((bool)large["hasFooter"]!);
    }

    [TestMethod]
    public void Outdated_numbers_are_subtle_with_a_note_where_there_is_room()
    {
        ProviderState claude = Claude();
        // captured_at 1791715200 is 2026-10-11 10:40:00 UTC, 80 minutes before Now (12:00 is 1791720000)
        claude.Take(Answer.Parse("""{"ok": true, "source": "statusline", "captured_at": 1791715200, "rows": [{"label": "Session", "percent": 96, "resets_at": null}]}"""), Now);
        JsonObject section = (JsonObject)Build([claude])["sections"]![0]!;
        JsonObject row = (JsonObject)section["rows"]![0]!;
        Assert.IsTrue((bool)row["pctSubtle"]!);
        StringAssert.Contains(Svg((string)row["bar"]!), "fill='#da4453'");
        Assert.AreEqual("Numbers from 10:40, outdated", (string)section["note"]!);
        Assert.IsTrue((bool)section["hasNote"]!);
        Assert.AreEqual("", (string)row["when"]!);
        Assert.AreEqual("Updated 10:40 · click to refresh", (string)Build([claude])["footer"]!);
        Assert.IsTrue((bool)Build([claude], CardSize.Medium)["sections"]![0]!["hasNote"]!);
        Assert.IsFalse((bool)Build([claude], CardSize.Small)["sections"]![0]!["hasNote"]!);

        JsonObject fresh = (JsonObject)Build([claude], now: DateTimeOffset.FromUnixTimeSeconds(1791715200).AddMinutes(14))["sections"]![0]!;
        Assert.IsFalse((bool)fresh["hasNote"]!);
        Assert.IsFalse((bool)fresh["rows"]![0]!["pctSubtle"]!);
    }

    [TestMethod]
    public void An_error_keeps_the_last_good_rows_dimmed_under_its_message()
    {
        ProviderState codex = Codex();
        codex.Take(Rows(("Session", 12)), Now.AddMinutes(-5));
        codex.Take(Answer.Parse("""{"ok": false, "error": "cli", "message": "exit 1: boom"}"""), Now);
        JsonObject section = (JsonObject)Build([codex])["sections"]![0]!;
        Assert.AreEqual(1, section["rows"]!.AsArray().Count);
        Assert.IsTrue((bool)section["rows"]![0]!["dim"]!);
        Assert.IsTrue((bool)section["rows"]![0]!["pctSubtle"]!);
        Assert.AreEqual("Codex could not tell the usage: exit 1: boom", (string)section["message"]!);
        Assert.IsTrue((bool)section["hasMessage"]!);
        Assert.AreEqual("Updated 11:55 · click to refresh", (string)Build([codex])["footer"]!);
    }

    [TestMethod]
    public void Messages_by_kind()
    {
        Assert.AreEqual("Codex not found: install it and sign in", Card.MessageFor("nocli", "Codex", "codex"));
        Assert.AreEqual("No Claude Code subscription login found", Card.MessageFor("nologin", "Claude Code", "x"));
        Assert.AreEqual("Cannot use the status file: boom", Card.MessageFor("unreadable", "Claude Code", "boom"));
        Assert.AreEqual("Unexpected answer; Claude Code may have changed what it reports", Card.MessageFor("format", "Claude Code", "no rate_limits"));
        Assert.AreEqual("No answer from the helper; will retry", Card.MessageFor("timeout", "Codex", ""));
        Assert.AreEqual("The helper gave no usable answer: Traceback", Card.MessageFor("badoutput", "Codex", "Traceback"));
        Assert.AreEqual("Error: weird", Card.MessageFor("weird", "Codex", ""));
    }

    [TestMethod]
    public void A_disabled_provider_is_not_shown()
    {
        ProviderState claude = Claude();
        claude.Take(Rows(("Session", 1)), Now);
        claude.Enabled = false;
        JsonObject d = Build([claude]);
        Assert.AreEqual(0, d["sections"]!.AsArray().Count);
        Assert.AreEqual(Card.NoLoginNotice, (string)d["notice"]!);
    }

    [TestMethod]
    public void An_error_before_any_good_answer_shows_the_message_under_the_name()
    {
        ProviderState claude = Claude();
        claude.Take(Answer.Parse("""{"ok": false, "error": "nocli", "message": "claude"}"""), Now);
        JsonObject section = (JsonObject)Build([claude])["sections"]![0]!;
        Assert.AreEqual(0, section["rows"]!.AsArray().Count);
        Assert.AreEqual("Claude Code not found: install it and sign in", (string)section["message"]!);
        Assert.IsFalse((bool)Build([claude])["hasFooter"]!);
        // In the small widget the rows carry the service's name; with no row, the name is shown above the message.
        Assert.IsTrue((bool)Build([claude], CardSize.Small)["sections"]![0]!["showName"]!);
    }

    [TestMethod]
    public void A_refresh_the_user_asked_for_shows_in_the_large_footer()
    {
        ProviderState claude = Claude();
        claude.Take(Rows(("Session", 1)), Now);
        Assert.AreEqual(Card.UpdatingFooter, (string)Build([claude], updating: true)["footer"]!);
        Assert.IsFalse((bool)Build([claude], CardSize.Medium, updating: true)["hasFooter"]!);
    }

    [TestMethod]
    public void Turkish_letters_survive_the_data_json_round_trip()
    {
        // A label or a message can carry Turkish letters (a plan name, a Windows path). The data is written as JSON and
        // read back the way the Board's renderer reads it: nothing may change on the way (D2).
        const string label = "Haftalık (7 gün) şğöç İŞĞÖÜÇ";
        ProviderState claude = Claude();
        claude.Take(Rows((label, 10)), Now);
        ProviderState codex = Codex();
        codex.Take(Answer.Parse("""{"ok": false, "error": "cli", "message": "exit 1: İşlem başarısız"}"""), Now);
        string json = Card.BuildData([claude, codex], new CardRequest(CardSize.Large, Now, Utc, Options));
        Assert.IsTrue(json.All(c => c < 128), "the data is pure ASCII (escapes), so no encoding between here and the Board can change it");
        var data = (JsonObject)JsonNode.Parse(json)!;
        Assert.AreEqual(label, (string)data["sections"]![0]!["rows"]![0]!["label"]!);
        Assert.AreEqual("Codex could not tell the usage: exit 1: İşlem başarısız", (string)data["sections"]![1]!["message"]!);
    }
}
