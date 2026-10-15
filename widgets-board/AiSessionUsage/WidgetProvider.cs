// The provider the Widgets Board talks to: one object per activation, static state shared across them (the host
// may create several). Each pinned widget is remembered with its size; the card is drawn from the service's
// states; a refresh is asked for on pin, on Activate when the numbers are a minute old, every five minutes while
// any widget is shown, and on the Refresh button.
using System.Runtime.InteropServices;
using AiSessionUsage.Core;
using Microsoft.Windows.Widgets;
using Microsoft.Windows.Widgets.Providers;

namespace AiSessionUsage;

/// <summary>The widget provider.</summary>
[ComVisible(true)]
[ComDefaultInterface(typeof(IWidgetProvider))]
[Guid(ClassId)]
public sealed class WidgetProvider : IWidgetProvider
{
    /// <summary>The COM class id, the same as in Package.appxmanifest (com:Class and CreateInstance).</summary>
    public const string ClassId = "7B9E2C6A-5D41-4F8B-9C33-2A1F6E0D8B57";

    /// <summary>The one widget definition in Package.appxmanifest.</summary>
    public const string DefinitionId = "AiSessionUsage";

    /// <summary>The verb of the card's Refresh button.</summary>
    public const string RefreshVerb = "refresh";

    /// <summary><see cref="ClassId"/> as a Guid.</summary>
    public static readonly Guid ClassGuid = Guid.Parse(ClassId);

    private static readonly object Lock = new();
    private static readonly Dictionary<string, CardSize> Widgets = new();
    private static readonly ManualResetEvent NoWidgets = new(false);
    private static readonly CardOptions Options = new();
    private static bool _recovered;
    private static bool _subscribed;
    private static string? _template;

    /// <summary>Set once the last widget is unpinned; the process waits on it.</summary>
    public static WaitHandle NoWidgetsLeft => NoWidgets;

    /// <summary>Creates a provider object (the class factory calls this).</summary>
    public WidgetProvider()
    {
        lock (Lock)
        {
            if (!_subscribed)
            {
                UsageService.Instance.Changed += RenderAll;
                _subscribed = true;
            }
        }
    }

    /// <summary>The widgets pinned before this process started, read back from the host.</summary>
    public static void RecoverPinnedWidgets()
    {
        lock (Lock)
        {
            if (_recovered)
            {
                return;
            }
            _recovered = true;
            try
            {
                WidgetManager manager = WidgetManager.GetDefault();
                // Null when the host has nothing for this provider (seen when the process was started by hand).
                WidgetInfo[]? infos = manager.GetWidgetInfos();
                foreach (WidgetInfo info in infos ?? Array.Empty<WidgetInfo>())
                {
                    WidgetContext context = info.WidgetContext;
                    if (context.DefinitionId != DefinitionId)
                    {
                        manager.DeleteWidget(context.Id);  // not one of ours (any more)
                        continue;
                    }
                    Widgets[context.Id] = SizeOf(context.Size);
                }
                Log.Write($"recovered {Widgets.Count} pinned widget(s)");
            }
            catch (Exception exc)
            {
                Log.Write($"recovery failed: {exc.GetType().Name}: {exc.Message}");
            }
        }
    }

    /// <inheritdoc />
    public void CreateWidget(WidgetContext widgetContext)
    {
        Log.Write($"CreateWidget {widgetContext.Id} {widgetContext.DefinitionId} {widgetContext.Size}");
        if (widgetContext.DefinitionId != DefinitionId)
        {
            throw new ArgumentException($"unknown widget definition {widgetContext.DefinitionId}");
        }
        lock (Lock)
        {
            Widgets[widgetContext.Id] = SizeOf(widgetContext.Size);
            NoWidgets.Reset();
        }
        Render(widgetContext.Id);
        UsageService.Instance.RequestRefresh(force: false);
    }

    /// <inheritdoc />
    public void DeleteWidget(string widgetId, string customState)
    {
        Log.Write($"DeleteWidget {widgetId}");
        UsageService.Instance.SetActive(widgetId, false);
        lock (Lock)
        {
            Widgets.Remove(widgetId);
            if (Widgets.Count == 0)
            {
                NoWidgets.Set();
            }
        }
    }

    /// <inheritdoc />
    public void OnActionInvoked(WidgetActionInvokedArgs actionInvokedArgs)
    {
        Log.Write($"OnActionInvoked {actionInvokedArgs.WidgetContext.Id} verb {actionInvokedArgs.Verb}");
        if (actionInvokedArgs.Verb == RefreshVerb)
        {
            UsageService.Instance.RequestRefresh(force: true);
        }
    }

    /// <inheritdoc />
    public void OnWidgetContextChanged(WidgetContextChangedArgs contextChangedArgs)
    {
        WidgetContext context = contextChangedArgs.WidgetContext;
        Log.Write($"OnWidgetContextChanged {context.Id} {context.Size}");
        lock (Lock)
        {
            Widgets[context.Id] = SizeOf(context.Size);
        }
        Render(context.Id);
    }

    /// <inheritdoc />
    public void Activate(WidgetContext widgetContext)
    {
        Log.Write($"Activate {widgetContext.Id}");
        lock (Lock)
        {
            Widgets[widgetContext.Id] = SizeOf(widgetContext.Size);
            NoWidgets.Reset();
        }
        UsageService.Instance.SetActive(widgetContext.Id, true);
        // The card is redrawn from the states at once (countdowns move on) and again when the refresh answers.
        if (UsageService.Instance.LastFetch is not null)
        {
            Render(widgetContext.Id);
        }
        UsageService.Instance.RequestRefresh(force: false);
    }

    /// <inheritdoc />
    public void Deactivate(string widgetId)
    {
        Log.Write($"Deactivate {widgetId}");
        UsageService.Instance.SetActive(widgetId, false);
    }

    private static CardSize SizeOf(WidgetSize size)
    {
        return size switch
        {
            WidgetSize.Small => CardSize.Small,
            WidgetSize.Medium => CardSize.Medium,
            _ => CardSize.Large,
        };
    }

    private static string Template()
    {
        lock (Lock)
        {
            // Read once per process: the template is a file of the package, which cannot change while the process runs
            // (S4: nothing to invalidate).
            _template ??= File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Templates", "card.json"));
            return _template;
        }
    }

    private static void RenderAll()
    {
        string[] ids;
        lock (Lock)
        {
            ids = Widgets.Keys.ToArray();
        }
        foreach (string id in ids)
        {
            Render(id);
        }
    }

    private static void Render(string widgetId)
    {
        CardSize size;
        lock (Lock)
        {
            if (!Widgets.TryGetValue(widgetId, out size))
            {
                return;
            }
        }
        try
        {
            var options = new WidgetUpdateRequestOptions(widgetId)
            {
                Template = Template(),
                Data = Card.BuildData(UsageService.Instance.Providers,
                                      new CardRequest(size, DateTimeOffset.Now, TimeZoneInfo.Local, Options, UsageService.Instance.IsUpdating)),
            };
            WidgetManager.GetDefault().UpdateWidget(options);
        }
        catch (Exception exc)
        {
            Log.Write($"UpdateWidget {widgetId} failed: {exc.GetType().Name}: {exc.Message}");
        }
    }
}
