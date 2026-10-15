// A small log for seeing what the provider did, since it has no window: %LOCALAPPDATA%\ai-session-usage\
// widgets-board.log (a packaged app's writes there land under its own LocalCache folder). Holds timings, error
// kinds and exception names only; the helper prints no token, so none can reach here.
namespace AiSessionUsage;

internal static class Log
{
    private const long MaxBytes = 200_000;
    private static readonly object Lock = new();
    private static readonly string? Path = Locate();

    private static readonly DateTime Started = StartTime();

    private static DateTime StartTime()
    {
        try
        {
            return System.Diagnostics.Process.GetCurrentProcess().StartTime;
        }
        catch (Exception exc) when (exc is InvalidOperationException or System.ComponentModel.Win32Exception or NotSupportedException)
        {
            return DateTime.Now;  // the log's "+N s" then counts from the first line instead of the process start
        }
    }

    private static string? Locate()
    {
        // The user's local app data first (a packaged app's writes there land under its own LocalCache folder); the
        // temp folder when that cannot be made.
        foreach (string? root in new[] { Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), System.IO.Path.GetTempPath() })
        {
            try
            {
                if (string.IsNullOrEmpty(root))
                {
                    continue;
                }
                string dir = System.IO.Path.Combine(root, "ai-session-usage");
                Directory.CreateDirectory(dir);
                string path = System.IO.Path.Combine(dir, "widgets-board.log");
                File.AppendAllText(path, "");
                return path;
            }
            catch (Exception)
            {
                continue;  // this folder cannot be made or written (no profile, a policy): try the next
            }
        }
        return null;
    }

    /// <summary>Append one line; never throws.</summary>
    internal static void Write(string message)
    {
        if (Path is null)
        {
            return;
        }
        lock (Lock)
        {
            try
            {
                var info = new FileInfo(Path);
                if (info.Exists && info.Length > MaxBytes)
                {
                    File.WriteAllText(Path, "");
                }
                double sinceStart = (DateTime.Now - Started).TotalSeconds;
                File.AppendAllText(Path, $"{DateTimeOffset.Now:yyyy-MM-dd HH:mm:ss} +{sinceStart:F1}s {message}\n");
            }
            catch (Exception)
            {
                // a log that cannot be written is not a reason to fail the widget
            }
        }
    }
}
