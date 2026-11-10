using System.ComponentModel;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;

namespace NavinUsbCreator;

/// <summary>Direct Win32 disk access used for raw writes and read-back verification.</summary>
internal static unsafe class Native
{
    public const uint GENERIC_READ = 0x80000000, GENERIC_WRITE = 0x40000000;
    public const uint FILE_SHARE_READ = 1, FILE_SHARE_WRITE = 2, OPEN_EXISTING = 3;
    public const uint FILE_FLAG_NO_BUFFERING = 0x20000000, FILE_FLAG_WRITE_THROUGH = 0x80000000;
    public const uint IOCTL_DISK_GET_DRIVE_GEOMETRY_EX = 0x000700A0;
    public const uint IOCTL_DISK_UPDATE_PROPERTIES = 0x00070140;

    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    public static extern SafeFileHandle CreateFileW(string name, uint access, uint share, IntPtr security, uint disposition, uint flags, IntPtr template);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern bool WriteFile(SafeFileHandle h, byte* buffer, uint count, out uint written, IntPtr overlapped);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern bool ReadFile(SafeFileHandle h, byte* buffer, uint count, out uint read, IntPtr overlapped);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern bool SetFilePointerEx(SafeFileHandle h, long distance, out long newPosition, uint method);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern bool FlushFileBuffers(SafeFileHandle h);

    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern bool DeviceIoControl(SafeFileHandle h, uint code, IntPtr inBuf, uint inSize, IntPtr outBuf, uint outSize, out uint returned, IntPtr overlapped);

    public static SafeFileHandle OpenPhysicalDrive(int number)
    {
        var h = CreateFileW($@"\\.\PhysicalDrive{number}", GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE,
            IntPtr.Zero, OPEN_EXISTING, FILE_FLAG_NO_BUFFERING | FILE_FLAG_WRITE_THROUGH, IntPtr.Zero);
        if (h.IsInvalid) throw Fail("open the USB drive");
        return h;
    }

    /// <summary>Returns (bytes per sector, disk size) from the drive itself.</summary>
    public static (int Sector, long Size) Geometry(SafeFileHandle h)
    {
        var buf = Marshal.AllocHGlobal(256);
        try
        {
            if (!DeviceIoControl(h, IOCTL_DISK_GET_DRIVE_GEOMETRY_EX, IntPtr.Zero, 0, buf, 256, out _, IntPtr.Zero))
                throw Fail("read the drive size");
            int sector = Marshal.ReadInt32(buf, 20);
            long size = Marshal.ReadInt64(buf, 24);
            return (sector is 512 or 1024 or 2048 or 4096 ? sector : 512, size);
        }
        finally { Marshal.FreeHGlobal(buf); }
    }

    public static void Seek(SafeFileHandle h, long offset)
    {
        if (!SetFilePointerEx(h, offset, out _, 0)) throw Fail("move to a position on the drive");
    }

    public static void Write(SafeFileHandle h, byte* buf, int count)
    {
        if (!WriteFile(h, buf, (uint)count, out var n, IntPtr.Zero) || n != count) throw Fail("write to the USB drive");
    }

    public static void Read(SafeFileHandle h, byte* buf, int count)
    {
        if (!ReadFile(h, buf, (uint)count, out var n, IntPtr.Zero) || n != count) throw Fail("read back from the USB drive");
    }

    public static void RefreshPartitions(SafeFileHandle h) =>
        DeviceIoControl(h, IOCTL_DISK_UPDATE_PROPERTIES, IntPtr.Zero, 0, IntPtr.Zero, 0, out _, IntPtr.Zero);

    /// <summary>Turns a Win32 error into a message a user can act on.</summary>
    public static IOException Fail(string action)
    {
        int code = Marshal.GetLastWin32Error();
        string why = code switch
        {
            1167 or 2 or 3 or 55 => "The USB drive was disconnected. Plug it back in and start again — the drive is incomplete and must be rewritten.",
            21 => "The drive is not ready. Check that it is plugged in firmly.",
            19 => "The drive is write-protected. Slide its lock switch off or use another drive.",
            5 or 32 or 33 => "Windows or another program is using the drive. Close File Explorer windows and other disk tools, then try again.",
            23 or 31 or 1117 => "The drive reported a hardware error. It may be failing — try another USB drive.",
            112 => "The drive is too small for this image.",
            _ => new Win32Exception(code).Message,
        };
        return new IOException($"Could not {action}: {why} (Windows error {code})");
    }
}
