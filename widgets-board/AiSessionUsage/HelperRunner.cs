// Runs the helper the way the Plasma widget and the skin do: python -B fetch_usage.py --provider X, in the temp
// folder, and hands back its stdout. The package carries its own Python (python\python.exe, the embeddable
// package) and the helper (code\), both staged in by scripts/build_msix.py.
using System.Diagnostics;

namespace AiSessionUsage;

/// <summary>One run of the helper.</summary>
internal static class HelperRunner
{
    /// <summary>Bound on one run; the helper itself gives each CLI less.</summary>
    internal static readonly TimeSpan Timeout = TimeSpan.FromSeconds(90);

    private static readonly string Base = AppContext.BaseDirectory;
    private static readonly string Python = Path.Combine(Base, "python", "python.exe");
    private static readonly string Script = Path.Combine(Base, "code", "fetch_usage.py");

    /// <summary>
    /// Run the helper for a provider.
    /// </summary>
    /// <returns>Its stdout, or null when it could not be started or gave nothing within <see cref="Timeout"/>.</returns>
    internal static string? Run(string provider)
    {
        var start = new ProcessStartInfo
        {
            FileName = Python,
            WorkingDirectory = Path.GetTempPath(),
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            StandardOutputEncoding = System.Text.Encoding.UTF8,
            StandardErrorEncoding = System.Text.Encoding.UTF8,
        };
        start.ArgumentList.Add("-B");
        start.ArgumentList.Add(Script);
        start.ArgumentList.Add("--provider");
        start.ArgumentList.Add(provider);
        start.Environment["PYTHONDONTWRITEBYTECODE"] = "1";
        start.Environment["PYTHONIOENCODING"] = "utf-8";
        var watch = Stopwatch.StartNew();
        try
        {
            using Process proc = Process.Start(start) ?? throw new InvalidOperationException("no process");
            Task<string> stdout = proc.StandardOutput.ReadToEndAsync();
            Task<string> stderr = proc.StandardError.ReadToEndAsync();
            if (!proc.WaitForExit(Timeout))
            {
                Log.Write($"helper {provider}: no answer within {Timeout.TotalSeconds} s; ending it and its children");
                try
                {
                    proc.Kill(entireProcessTree: true);
                }
                catch (Exception exc) when (exc is InvalidOperationException or System.ComponentModel.Win32Exception)
                {
                    // already gone
                }
                return null;
            }
            string text = stdout.GetAwaiter().GetResult();
            string errors = stderr.GetAwaiter().GetResult();
            Log.Write($"helper {provider}: exit {proc.ExitCode} in {watch.Elapsed.TotalSeconds:F1} s, {text.Length} chars" +
                      (errors.Length > 0 ? $", stderr {errors.Length} chars" : ""));
            return text;
        }
        catch (Exception exc) when (exc is System.ComponentModel.Win32Exception or InvalidOperationException or IOException)
        {
            Log.Write($"helper {provider}: could not start: {exc.GetType().Name}");
            return null;
        }
    }
}
