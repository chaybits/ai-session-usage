// The out-of-process COM server side: a class factory that hands the Widgets Board the provider object, registered
// with CoRegisterClassObject under the CLSID the package manifest names. The same calls the official widget sample
// makes, written out here (CLSCTX_LOCAL_SERVER, REGCLS_MULTIPLEUSE).
using System.Runtime.InteropServices;
using Microsoft.Windows.Widgets.Providers;
using WinRT;

namespace AiSessionUsage;

/// <summary>Registers a widget provider class with COM.</summary>
internal static class ComServer
{
    private const string IidIClassFactory = "00000001-0000-0000-C000-000000000046";
    private const string IidIUnknown = "00000000-0000-0000-C000-000000000046";
    private const string IidIInspectable = "AF86E2E0-B12D-4c6a-9C5A-D7AA65101E90";
    private const int ClassENoAggregation = unchecked((int)0x80040110);
    private const int ENoInterface = unchecked((int)0x80004002);
    private const uint ClsctxLocalServer = 0x4;
    private const uint RegclsMultipleUse = 0x1;

    [ComImport]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    [Guid(IidIClassFactory)]
    private interface IClassFactory
    {
        [PreserveSig]
        int CreateInstance(IntPtr pUnkOuter, ref Guid riid, out IntPtr ppvObject);

        [PreserveSig]
        int LockServer(bool fLock);
    }

    [DllImport("ole32.dll")]
    private static extern int CoRegisterClassObject(
        [MarshalAs(UnmanagedType.LPStruct)] Guid rclsid,
        [MarshalAs(UnmanagedType.IUnknown)] object pUnk,
        uint dwClsContext,
        uint flags,
        out uint lpdwRegister);

    [DllImport("ole32.dll")]
    private static extern int CoRevokeClassObject(uint dwRegister);

    /// <summary>The registration; disposing it revokes the class object.</summary>
    internal sealed class Registration : IDisposable
    {
        private uint _cookie;

        internal Registration(uint cookie)
        {
            _cookie = cookie;
        }

        public void Dispose()
        {
            if (_cookie != 0)
            {
                _ = CoRevokeClassObject(_cookie);
                _cookie = 0;
            }
        }
    }

    private sealed class Factory<T> : IClassFactory
        where T : IWidgetProvider, new()
    {
        private static readonly Guid Unknown = Guid.Parse(IidIUnknown);
        private static readonly Guid Inspectable = Guid.Parse(IidIInspectable);
        private readonly Guid _classId;

        internal Factory(Guid classId)
        {
            _classId = classId;
        }

        public int CreateInstance(IntPtr pUnkOuter, ref Guid riid, out IntPtr ppvObject)
        {
            ppvObject = IntPtr.Zero;
            if (pUnkOuter != IntPtr.Zero)
            {
                return ClassENoAggregation;
            }
            if (riid == _classId || riid == Unknown || riid == Inspectable || riid == typeof(IWidgetProvider).GUID)
            {
                ppvObject = MarshalInspectable<IWidgetProvider>.FromManaged(new T());
                return 0;
            }
            return ENoInterface;
        }

        public int LockServer(bool fLock)
        {
            return 0;
        }
    }

    /// <summary>Register the class object for <paramref name="classId"/>; the host creates <typeparamref name="T"/> through it.</summary>
    internal static Registration Register<T>(Guid classId)
        where T : IWidgetProvider, new()
    {
        int result = CoRegisterClassObject(classId, new Factory<T>(classId), ClsctxLocalServer, RegclsMultipleUse, out uint cookie);
        if (result != 0)
        {
            Marshal.ThrowExceptionForHR(result);
        }
        return new Registration(cookie);
    }
}
