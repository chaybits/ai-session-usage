// The reset wording of a row, in the widget's own words (the Plasma widget and the skin say "Resets in 2h 13m · 14:05"):
// the countdown "2h 13m" the small and medium widget show beside the percentage, and "2h 13m · 14:05", the countdown
// with its clock time, which the large one shows. The Board's column is about 214 px wide, too narrow for the full sentence.
using System.Globalization;

namespace AiSessionUsage.Core;

/// <summary>The "Resets in ..." text of a row.</summary>
public static class ResetText
{
    private const string MiddleDot = "·";

    // A reset more than a minute ago has passed; one within half a minute either way is "now" (the skin's thresholds).
    private const double PassedAfterSeconds = -60;
    private const double NowWithinSeconds = 30;

    /// <summary>
    /// The countdown with the clock time of the reset, "2h 13m · 14:05" ("3d 4h · Thu 16:00" within six days, the
    /// date after that); the bare countdown ("reset", "now") when there is no time to show, and an empty string when
    /// no reset time is known.
    /// </summary>
    /// <param name="resetsAt">When the window resets.</param>
    /// <param name="now">The current time.</param>
    /// <param name="zone">The zone the clock time is shown in (the user's local zone).</param>
    public static string WithClock(DateTimeOffset? resetsAt, DateTimeOffset now, TimeZoneInfo zone)
    {
        if (resetsAt is null)
        {
            return "";
        }
        double diff = (resetsAt.Value - now).TotalSeconds;
        if (diff <= NowWithinSeconds)
        {
            return Countdown(resetsAt, now);
        }
        DateTimeOffset local = TimeZoneInfo.ConvertTime(resetsAt.Value, zone);
        string clock;
        if (diff < 6 * 86400)
        {
            clock = local.ToString(diff >= 86400 ? "ddd HH:mm" : "HH:mm", CultureInfo.InvariantCulture);
        }
        else
        {
            clock = local.ToString("dd MMM", CultureInfo.InvariantCulture);
        }
        return $"{Left(diff)} {MiddleDot} {clock}";
    }

    /// <summary>
    /// The short countdown of a compact row: "2h 13m", "3d 4h", "45m", "now", or "reset" once the time has passed;
    /// an empty string when no reset time is known.
    /// </summary>
    /// <param name="resetsAt">When the window resets.</param>
    /// <param name="now">The current time.</param>
    public static string Countdown(DateTimeOffset? resetsAt, DateTimeOffset now)
    {
        if (resetsAt is null)
        {
            return "";
        }
        double diff = (resetsAt.Value - now).TotalSeconds;
        if (diff < PassedAfterSeconds)
        {
            return "reset";
        }
        if (diff <= NowWithinSeconds)
        {
            return "now";
        }
        return Left(diff);
    }

    /// <summary>The time left, rounded to the minute: days and hours from a day on, hours and minutes, or minutes.</summary>
    private static string Left(double seconds)
    {
        long mins = (long)Math.Floor(seconds / 60 + 0.5);
        long hours = mins / 60;
        long minutes = mins % 60;
        if (hours >= 24)
        {
            return $"{hours / 24}d {hours % 24}h";
        }
        return hours > 0 ? $"{hours}h {minutes}m" : $"{minutes}m";
    }
}
