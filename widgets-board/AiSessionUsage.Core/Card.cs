// The card's data: what the Adaptive Card template binds to, built from the providers' answers with the rules of the
// Plasma widget and the skin (a provider with no login is left out, D4; levels at 80 and 95 judged on the printed
// number; numbers older than 15 minutes are outdated; an erroring provider keeps its last good rows, dimmed, with the
// message under them). Every decision that depends on the widget's size is made here, where the tests see it, so the
// template only binds fields: which rows show, what a row's label and reset text say, whether names, notes and the
// footer appear.
using System.Globalization;
using System.Text;
using System.Text.Json.Nodes;

namespace AiSessionUsage.Core;

/// <summary>The Widgets Board's three sizes: one column wide (about 214 px of content), about 75, 205 and 330 px tall.</summary>
public enum CardSize
{
    Small,
    Medium,
    Large,
}

/// <summary>One provider's standing: the last answer, the last good one, and the time of the numbers shown.</summary>
public sealed class ProviderState
{
    /// <summary>The helper's provider name: <c>claude</c> or <c>codex</c>.</summary>
    public required string Id { get; init; }

    /// <summary>The service as the card names it: Claude, ChatGPT.</summary>
    public required string Name { get; init; }

    /// <summary>The CLI as the messages name it: Claude Code, Codex.</summary>
    public required string Cli { get; init; }

    /// <summary>Whether the user wants this provider shown.</summary>
    public bool Enabled { get; set; } = true;

    /// <summary>The last answer, or null before the first one.</summary>
    public Answer? Last { get; private set; }

    /// <summary>The last answer that carried rows, kept under an error.</summary>
    public Answer? LastGood { get; private set; }

    /// <summary>The time of the numbers shown: the status line's capture time, else when they were fetched.</summary>
    public DateTimeOffset? At { get; private set; }

    /// <summary>Record an answer fetched at <paramref name="fetchedAt"/>.</summary>
    public void Take(Answer answer, DateTimeOffset fetchedAt)
    {
        Last = answer;
        if (answer.Ok)
        {
            LastGood = answer;
            At = answer.CapturedAt ?? fetchedAt;
        }
    }
}

/// <summary>The thresholds, the same defaults as the other front ends.</summary>
/// <param name="WarnPercent">From this printed percentage a row is in the warning colour (0: never).</param>
/// <param name="CriticalPercent">From this printed percentage a row is in the critical colour (0: never).</param>
/// <param name="StaleMinutes">Numbers older than this are marked outdated.</param>
public sealed record CardOptions(int WarnPercent = 80, int CriticalPercent = 95, int StaleMinutes = 15);

/// <summary>What a card is drawn for.</summary>
/// <param name="Size">The widget's size, which decides the rows per service and what each row says.</param>
/// <param name="Now">The current time.</param>
/// <param name="Zone">The zone clock times are shown in.</param>
/// <param name="Options">The thresholds.</param>
/// <param name="Updating">True while a refresh the user asked for runs; the large card's footer says so.</param>
public sealed record CardRequest(CardSize Size, DateTimeOffset Now, TimeZoneInfo Zone, CardOptions Options, bool Updating = false);

/// <summary>Builds the data JSON the card template binds to.</summary>
public static class Card
{
    private const string MiddleDot = "·";

    /// <summary>The text when no provider has a login.</summary>
    public const string NoLoginNotice = "No Claude Code or Codex login found";

    /// <summary>The text before the first answer.</summary>
    public const string LoadingNotice = "Loading";

    /// <summary>What to do when no provider has a login: someone who installed the widget from the Store may not know.</summary>
    public const string NoLoginHint = "Sign in to Claude Code or the Codex CLI on this PC; the limits appear at the next refresh.";

    /// <summary>The large card's footer while a refresh the user asked for runs.</summary>
    public const string UpdatingFooter = "Updating…";

    // The bar's colours: the Plasma widget's defaults (D13) for warning and critical, the skin's accent for the rest,
    // and a grey track that reads on both the light and the dark Board.
    private static readonly Dictionary<string, string> BarColours = new()
    {
        ["accent"] = "#3daee9",
        ["warning"] = "#f67400",
        ["attention"] = "#da4453",
    };

    // The bar is an SVG picture, 200 x 6 units: the Board stretches it to the column (about 214 px), keeping the
    // ratio, so it is about 6 px tall. Styled containers draw no background on the Board, and an SVG data URI renders
    // there (seen 2026-10-12, D22); a PNG would too, if a later Board stops drawing SVG.
    private const int BarUnits = 200;

    // The messages of the Plasma widget and the skin, by error kind. {0} is the CLI's name, {1} the helper's message.
    private static readonly Dictionary<string, string> Messages = new()
    {
        ["nologin"] = "No {0} subscription login found",
        ["nocli"] = "{0} not found: install it and sign in",
        ["cli"] = "{0} could not tell the usage: {1}",
        ["nostatusline"] = "No numbers from {0}'s status line yet",
        ["unreadable"] = "Cannot use the status file: {1}",
        ["format"] = "Unexpected answer; {0} may have changed what it reports",
        ["timeout"] = "No answer from the helper; will retry",
        ["badoutput"] = "The helper gave no usable answer: {1}",
        ["usage"] = "The helper refused its arguments: {1}",
        ["internal"] = "The helper failed: {1}",
    };

    /// <summary>How many rows of each service a size shows: the first, the first two, or all.</summary>
    public static int RowsFor(CardSize size)
    {
        return size switch
        {
            CardSize.Small => 1,
            CardSize.Medium => 2,
            _ => int.MaxValue,
        };
    }

    /// <summary>The message for an error kind, worded like the other front ends.</summary>
    public static string MessageFor(string kind, string cli, string message)
    {
        if (Messages.TryGetValue(kind, out string? format))
        {
            return string.Format(CultureInfo.InvariantCulture, format, cli, message).TrimEnd(':', ' ');
        }
        return $"Error: {kind} {message}".TrimEnd();
    }

    /// <summary>The number the card prints for a percentage (the helper may pass a fraction).</summary>
    public static int ShownPercent(double percent)
    {
        return (int)Math.Floor(percent + 0.5);
    }

    /// <summary>A row's level, judged on the printed number like the Plasma widget: accent, warning or attention (the bar's colour).</summary>
    public static string Level(double percent, CardOptions options)
    {
        int shown = ShownPercent(percent);
        if (options.CriticalPercent > 0 && shown >= options.CriticalPercent)
        {
            return "attention";
        }
        if (options.WarnPercent > 0 && shown >= options.WarnPercent)
        {
            return "warning";
        }
        return "accent";
    }

    /// <summary>
    /// The bar as an SVG data URI: a grey track, and over it the used part in the level's colour (none at 0 %).
    /// </summary>
    /// <param name="used">The printed percentage, 0 to 100.</param>
    /// <param name="level">accent, warning or attention.</param>
    public static string BarImage(int used, string level)
    {
        int clamped = Math.Clamp(used, 0, 100);
        string colour = BarColours.TryGetValue(level, out string? c) ? c : BarColours["accent"];
        var svg = new StringBuilder();
        svg.Append($"<svg xmlns='http://www.w3.org/2000/svg' width='{BarUnits}' height='6' viewBox='0 0 {BarUnits} 6'>");
        svg.Append($"<rect width='{BarUnits}' height='6' rx='3' fill='#808080' fill-opacity='0.35'/>");
        if (clamped > 0)
        {
            int width = clamped * BarUnits / 100;
            svg.Append($"<rect width='{width}' height='6' rx='3' fill='{colour}'/>");
        }
        svg.Append("</svg>");
        return "data:image/svg+xml;base64," + Convert.ToBase64String(Encoding.ASCII.GetBytes(svg.ToString()));
    }

    /// <summary>
    /// The data JSON for the template.
    /// </summary>
    /// <param name="providers">The providers in display order.</param>
    /// <param name="request">What the card is drawn for.</param>
    public static string BuildData(IReadOnlyList<ProviderState> providers, CardRequest request)
    {
        var sections = new JsonArray();
        int shown = 0;
        bool anyAnswer = false;
        DateTimeOffset? oldest = null;
        CardSize size = request.Size;
        foreach (ProviderState p in providers)
        {
            Answer? last = p.Last;
            if (last is not null)
            {
                anyAnswer = true;
            }
            IReadOnlyList<UsageRow>? rows = last is { Ok: true } ? last.Rows : p.LastGood?.Rows;
            bool hiddenLogin = last is { Ok: false, Error: Answer.NoLoginKind } && rows is null;
            if (!p.Enabled || last is null || hiddenLogin)
            {
                continue;
            }
            shown++;
            sections.Add(Section(p, last, rows ?? Array.Empty<UsageRow>(), request));
            if (p.At is not null && (oldest is null || p.At < oldest))
            {
                oldest = p.At;
            }
        }
        string notice = "";
        string hint = "";
        if (shown == 0)
        {
            notice = anyAnswer ? NoLoginNotice : LoadingNotice;
            hint = anyAnswer ? NoLoginHint : "";
        }
        string footer = "";
        if (size == CardSize.Large)
        {
            if (request.Updating)
            {
                footer = UpdatingFooter;
            }
            else if (shown > 0 && oldest is not null)
            {
                string at = TimeZoneInfo.ConvertTime(oldest.Value, request.Zone).ToString("HH:mm", CultureInfo.InvariantCulture);
                footer = $"Updated {at} {MiddleDot} click to refresh";
            }
        }
        var data = new JsonObject
        {
            ["sections"] = sections,
            ["notice"] = notice,
            ["hasNotice"] = notice.Length > 0,
            ["hint"] = hint,
            ["hasHint"] = hint.Length > 0,
            ["footer"] = footer,
            ["hasFooter"] = footer.Length > 0,
        };
        return data.ToJsonString();
    }

    private static JsonObject Section(ProviderState p, Answer last, IReadOnlyList<UsageRow> rows, CardRequest request)
    {
        CardSize size = request.Size;
        bool stale = p.At is not null && (request.Now - p.At.Value).TotalSeconds > request.Options.StaleMinutes * 60;
        bool dimmed = !last.Ok;
        var rowNodes = new JsonArray();
        foreach (UsageRow r in rows.Take(RowsFor(size)))
        {
            int used = Math.Clamp(ShownPercent(r.Percent), 0, 100);
            string level = Level(r.Percent, request.Options);
            rowNodes.Add(new JsonObject
            {
                // The small widget has no room for the service's name above its one row, so the row carries it.
                ["label"] = size == CardSize.Small ? p.Name : r.Label,
                ["when"] = size == CardSize.Large
                    ? ResetText.WithClock(r.ResetsAt, request.Now, request.Zone)
                    : ResetText.Countdown(r.ResetsAt, request.Now),
                // The level shows in the bar's colour only: the Board's text colours are its theme's, and its "warning"
                // is yellow in the dark theme, the colour the other front ends give outdated numbers (D13).
                ["percent"] = $"{used}%",
                ["pctSubtle"] = stale || dimmed,
                ["dim"] = dimmed,
                ["bar"] = BarImage(used, level),
                ["alt"] = $"{used} percent used",
            });
        }
        string note = "";
        if (stale && p.At is not null && size != CardSize.Small)
        {
            string seen = TimeZoneInfo.ConvertTime(p.At.Value, request.Zone).ToString("HH:mm", CultureInfo.InvariantCulture);
            note = $"Numbers from {seen}, outdated";
        }
        string message = last.Ok ? "" : MessageFor(last.Error, p.Cli, last.Message);
        return new JsonObject
        {
            ["name"] = p.Name,
            ["showName"] = size != CardSize.Small || rowNodes.Count == 0,
            ["rows"] = rowNodes,
            ["note"] = note,
            ["hasNote"] = note.Length > 0,
            ["message"] = message,
            ["hasMessage"] = message.Length > 0,
        };
    }
}
