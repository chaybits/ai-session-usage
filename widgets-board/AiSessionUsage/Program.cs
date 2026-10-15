// The entry point. Started by the Widgets Board with -RegisterProcessAsComServer, the process registers the widget
// provider's class object and lives until the last widget is unpinned (or Windows ends it). Started any other way
// (the Start menu, the Store's Open button) it has no window of its own, so it says where the widget is and exits.
using System.Runtime.InteropServices;

namespace AiSessionUsage;

/// <summary>Main.</summary>
public static class Program
{
    private const string ComServerFlag = "-RegisterProcessAsComServer";

    private const string FirstRunText =
        "AI Session Usage is a widget for the Widgets Board.\n\n" +
        "Open the Widgets Board (Win+W), click the + (Add widgets) button, and pick AI Session Usage.\n\n" +
        "It shows the subscription limits of Claude Code and of the Codex CLI: sign in to either tool on this PC, " +
        "and the widget asks it for its usage. The widget itself opens no connection and reads no login.";

    [DllImport("user32.dll", CharSet = CharSet.Unicode, ExactSpelling = true)]
    private static extern int MessageBoxW(IntPtr hWnd, string text, string caption, uint type);

    /// <summary>Serve the widget, or explain where it is.</summary>
    [MTAThread]
    public static int Main(string[] args)
    {
        Log.Write($"main: {args.Length} argument(s){(args.Length > 0 ? " " + args[0] : "")}");
        if (args.Length > 0 && args[0] == ComServerFlag)
        {
            return Serve();
        }
        const uint MB_OK = 0x0;
        const uint MB_ICONINFORMATION = 0x40;
        const uint MB_SETFOREGROUND = 0x10000;
        MessageBoxW(IntPtr.Zero, FirstRunText, "AI Session Usage", MB_OK | MB_ICONINFORMATION | MB_SETFOREGROUND);
        return 0;
    }

    private static int Serve()
    {
        Log.Write("provider process starting");
        try
        {
            WinRT.ComWrappersSupport.InitializeComWrappers();
            Log.Write("COM wrappers ready");
            using ComServer.Registration registration = ComServer.Register<WidgetProvider>(WidgetProvider.ClassGuid);
            Log.Write("class object registered");
            WidgetProvider.RecoverPinnedWidgets();
            // The host may ask for the provider at any time; the process stays until no widget is left.
            WidgetProvider.NoWidgetsLeft.WaitOne();
            Log.Write("no widget left; exiting");
            return 0;
        }
        catch (Exception exc)
        {
            Log.Write($"provider process failed: {exc.GetType().Name}: {exc.Message}");
            return 1;
        }
    }
}
