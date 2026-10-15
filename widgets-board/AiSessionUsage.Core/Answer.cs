// The helper's one JSON line, read into an answer. Never throws: a missing, broken or unexpected line becomes an
// answer with an error kind, the way the Plasma widget and the Rainmeter skin treat it (D2: one output contract).
using System.Text.Json;
using System.Text.Json.Nodes;

namespace AiSessionUsage.Core;

/// <summary>One usage row as the helper reports it.</summary>
/// <param name="Id">Stable id, <c>provider:kind</c>, kept for the row order of the other front ends.</param>
/// <param name="Label">Display text, built by the helper.</param>
/// <param name="Group"><c>session</c> (reset shown as a time) or anything else (shown with the weekday).</param>
/// <param name="Percent">Used percentage; may be a fraction.</param>
/// <param name="ResetsAt">When the window resets, or null when unknown.</param>
public sealed record UsageRow(string Id, string Label, string Group, double Percent, DateTimeOffset? ResetsAt);

/// <summary>The helper's answer for one provider.</summary>
public sealed class Answer
{
    /// <summary>Error kind when the helper gave nothing at all within its time.</summary>
    public const string TimeoutKind = "timeout";

    /// <summary>Error kind when the helper's output was not a usable JSON object.</summary>
    public const string BadOutputKind = "badoutput";

    /// <summary>Error kind when the helper found no login file for the provider (its section is left out, D4).</summary>
    public const string NoLoginKind = "nologin";

    /// <summary>True when the helper answered with rows.</summary>
    public bool Ok { get; init; }

    /// <summary>The error kind when not ok (<c>nologin</c>, <c>nocli</c>, <c>cli</c>, <c>format</c>, ...); empty when ok.</summary>
    public string Error { get; init; } = "";

    /// <summary>The helper's message for the error, possibly empty.</summary>
    public string Message { get; init; } = "";

    /// <summary>The plan type the service reported, when known.</summary>
    public string? Plan { get; init; }

    /// <summary>Which source answered (<c>claudecode</c>, <c>statusline</c>, <c>codex</c>), when given.</summary>
    public string? Source { get; init; }

    /// <summary>When the numbers were seen, for the status-line source; null means now.</summary>
    public DateTimeOffset? CapturedAt { get; init; }

    /// <summary>The rows; empty when not ok.</summary>
    public IReadOnlyList<UsageRow> Rows { get; init; } = Array.Empty<UsageRow>();

    /// <summary>Read the helper's output. Only the last non-empty line is the answer (a stray line before it is ignored).</summary>
    public static Answer Parse(string? text)
    {
        if (string.IsNullOrWhiteSpace(text))
        {
            return new Answer { Ok = false, Error = TimeoutKind };
        }
        string line = LastLine(text);
        JsonNode? node;
        try
        {
            node = JsonNode.Parse(line);
        }
        catch (JsonException)
        {
            return BadOutput(line);
        }
        if (node is not JsonObject obj)
        {
            return BadOutput(line);
        }
        bool ok = obj["ok"] is JsonValue okValue && okValue.TryGetValue<bool>(out bool okBool) && okBool;
        if (!ok)
        {
            return new Answer
            {
                Ok = false,
                Error = AsString(obj["error"]) ?? BadOutputKind,
                Message = AsString(obj["message"]) ?? "",
            };
        }
        if (obj["rows"] is not JsonArray rowsNode)
        {
            return new Answer { Ok = false, Error = BadOutputKind, Message = "no rows in the answer" };
        }
        var rows = new List<UsageRow>();
        foreach (JsonNode? rowNode in rowsNode)
        {
            if (rowNode is not JsonObject row)
            {
                continue;
            }
            string? label = AsString(row["label"]);
            double? percent = AsNumber(row["percent"]);
            if (label is null || percent is null)
            {
                continue;  // not a row; the helper never writes one, but the contract is checked, not trusted
            }
            rows.Add(new UsageRow(
                AsString(row["id"]) ?? "",
                label,
                AsString(row["group"]) ?? "",
                percent.Value,
                ParseIso(AsString(row["resets_at"]))));
        }
        double? captured = AsNumber(obj["captured_at"]);
        return new Answer
        {
            Ok = true,
            Plan = AsString(obj["plan"]),
            Source = AsString(obj["source"]),
            CapturedAt = captured is null ? null : FromEpoch(captured.Value),
            Rows = rows,
        };
    }

    private static Answer BadOutput(string line)
    {
        string shown = line.Length > 80 ? line[..80] : line;
        return new Answer { Ok = false, Error = BadOutputKind, Message = shown };
    }

    private static string LastLine(string text)
    {
        string[] lines = text.Split('\n');
        for (int i = lines.Length - 1; i >= 0; i--)
        {
            string candidate = lines[i].Trim();
            if (candidate.Length > 0)
            {
                return candidate;
            }
        }
        return "";
    }

    private static string? AsString(JsonNode? node)
    {
        return node is JsonValue value && value.TryGetValue<string>(out string? s) ? s : null;
    }

    private static double? AsNumber(JsonNode? node)
    {
        if (node is not JsonValue value)
        {
            return null;
        }
        // A JSON true is not a number; TryGetValue<double> refuses it, as it refuses strings.
        return value.TryGetValue<double>(out double d) && double.IsFinite(d) ? d : null;
    }

    private static DateTimeOffset? FromEpoch(double seconds)
    {
        try
        {
            return DateTimeOffset.FromUnixTimeSeconds((long)seconds);
        }
        catch (ArgumentOutOfRangeException)
        {
            return null;
        }
    }

    /// <summary>An ISO 8601 time with an offset (the helper writes <c>+00:00</c>), or null.</summary>
    public static DateTimeOffset? ParseIso(string? iso)
    {
        if (iso is null)
        {
            return null;
        }
        return DateTimeOffset.TryParse(iso, System.Globalization.CultureInfo.InvariantCulture,
                                       System.Globalization.DateTimeStyles.AssumeUniversal, out DateTimeOffset t)
            ? t
            : null;
    }
}
