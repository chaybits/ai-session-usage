// One fetcher for the process: both providers asked in parallel, their states kept, a timer every five minutes
// while any widget is active, and an event for the widgets to redraw. A refresh is one at a time; one asked for
// within a minute of the last is skipped unless forced (the Refresh button).
using AiSessionUsage.Core;

namespace AiSessionUsage;

/// <summary>Holds the providers' states and refreshes them.</summary>
internal sealed class UsageService
{
    /// <summary>How often the numbers are asked for while a widget is shown (the other front ends' default).</summary>
    internal static readonly TimeSpan Interval = TimeSpan.FromMinutes(5);

    /// <summary>A refresh asked for sooner than this after the last one is skipped unless forced.</summary>
    internal static readonly TimeSpan MinGap = TimeSpan.FromSeconds(60);

    /// <summary>The process's one service.</summary>
    internal static UsageService Instance { get; } = new();

    private readonly SemaphoreSlim _gate = new(1, 1);
    private readonly object _lock = new();
    // The widgets the host is showing, by id: a set, not a counter, so an Activate the host repeats for one widget
    // cannot leave the timer running after the Board closes.
    private readonly HashSet<string> _activeIds = new();
    private Timer? _timer;

    private UsageService()
    {
        Providers = new ProviderState[]
        {
            new() { Id = "claude", Name = "Claude", Cli = "Claude Code" },
            new() { Id = "codex", Name = "ChatGPT", Cli = "Codex" },
        };
    }

    /// <summary>The providers in display order.</summary>
    internal IReadOnlyList<ProviderState> Providers { get; }

    /// <summary>When the last refresh finished, or null before the first.</summary>
    internal DateTimeOffset? LastFetch { get; private set; }

    /// <summary>True while a refresh the user asked for (a click) runs; the card says "Updating" meanwhile.</summary>
    internal bool IsUpdating { get; private set; }

    /// <summary>Raised after a refresh changed the states.</summary>
    internal event Action? Changed;

    /// <summary>Mark a widget as shown (the host said Activate) or not (Deactivate, DeleteWidget); the timer runs while any is.</summary>
    internal void SetActive(string widgetId, bool active)
    {
        lock (_lock)
        {
            if (active)
            {
                _activeIds.Add(widgetId);
            }
            else
            {
                _activeIds.Remove(widgetId);
            }
            if (_activeIds.Count > 0 && _timer is null)
            {
                _timer = new Timer(_ => RequestRefresh(force: false), null, Interval, Interval);
            }
            else if (_activeIds.Count == 0 && _timer is not null)
            {
                _timer.Dispose();
                _timer = null;
            }
        }
    }

    /// <summary>Refresh in the background; returns at once.</summary>
    internal void RequestRefresh(bool force)
    {
        _ = Task.Run(() => RefreshAsync(force));
    }

    private async Task RefreshAsync(bool force)
    {
        if (!await _gate.WaitAsync(0).ConfigureAwait(false))
        {
            return;  // one is running; it will raise Changed
        }
        try
        {
            DateTimeOffset now = DateTimeOffset.Now;
            if (!force && LastFetch is not null && now - LastFetch.Value < MinGap)
            {
                return;
            }
            if (force)
            {
                IsUpdating = true;
                RaiseChanged();  // the click shows at once; the numbers follow in a few seconds
            }
            Task<(ProviderState, string?)>[] runs = Providers
                .Select(p => Task.Run(() => (p, HelperRunner.Run(p.Id))))
                .ToArray();
            (ProviderState, string?)[] results = await Task.WhenAll(runs).ConfigureAwait(false);
            DateTimeOffset fetched = DateTimeOffset.Now;
            foreach ((ProviderState p, string? text) in results)
            {
                Answer answer = Answer.Parse(text);
                p.Take(answer, fetched);
                Log.Write($"{p.Id}: {(answer.Ok ? $"ok, {answer.Rows.Count} rows" : $"error {answer.Error}")}");
            }
            LastFetch = fetched;
        }
        catch (Exception exc)
        {
            Log.Write($"refresh failed: {exc.GetType().Name}: {exc.Message}");
        }
        finally
        {
            IsUpdating = false;
            _gate.Release();
        }
        RaiseChanged();
    }

    private void RaiseChanged()
    {
        try
        {
            Changed?.Invoke();
        }
        catch (Exception exc)
        {
            Log.Write($"redraw failed: {exc.GetType().Name}: {exc.Message}");
        }
    }
}
