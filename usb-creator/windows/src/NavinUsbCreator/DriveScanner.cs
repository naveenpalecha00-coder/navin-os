using System.Management;
using NavinUsb.Core;

namespace NavinUsbCreator;

/// <summary>Lists USB/SD disks through Windows Storage Management (MSFT_Disk), hiding any system disk.</summary>
internal static class DriveScanner
{
    private const string Scope = @"\\.\root\Microsoft\Windows\Storage";

    public static List<DiskCandidate> All()
    {
        var result = new List<DiskCandidate>();
        using var disks = new ManagementObjectSearcher(Scope, "SELECT Number, FriendlyName, SerialNumber, Size, BusType, IsSystem, IsBoot, IsReadOnly FROM MSFT_Disk");
        foreach (ManagementObject d in disks.Get())
        {
            using (d)
            {
                int number = Convert.ToInt32(d["Number"]);
                var letters = new List<string>();
                long free = 0;
                using (var parts = new ManagementObjectSearcher(Scope, $"SELECT DriveLetter FROM MSFT_Partition WHERE DiskNumber = {number}"))
                {
                    foreach (ManagementObject p in parts.Get())
                    {
                        using (p)
                        {
                            var raw = p["DriveLetter"];
                            int code = raw is null ? 0 : Convert.ToInt32(raw);
                            if (code is >= 'A' and <= 'Z')
                            {
                                var letter = $"{(char)code}:";
                                letters.Add(letter);
                                try { free += new DriveInfo(letter).AvailableFreeSpace; } catch (IOException) { } catch (UnauthorizedAccessException) { }
                            }
                        }
                    }
                }
                result.Add(new DiskCandidate(
                    number,
                    (d["FriendlyName"]?.ToString() ?? "USB drive").Trim(),
                    (d["SerialNumber"]?.ToString() ?? "").Trim(),
                    d["Size"] is null ? 0 : Convert.ToInt64(d["Size"]),
                    d["BusType"] is null ? 0 : Convert.ToInt32(d["BusType"]),
                    d["IsSystem"] is true,
                    d["IsBoot"] is true,
                    d["IsReadOnly"] is true,
                    letters,
                    free));
            }
        }
        return result;
    }

    /// <summary>Only drives that are safe to offer: USB/SD, not the Windows disk, writable, with media.</summary>
    public static List<DiskCandidate> Safe()
    {
        var sys = Environment.GetEnvironmentVariable("SystemDrive") ?? "C:";
        return All().Where(d => SafetyRules.ExclusionReason(d, sys) is null).OrderBy(d => d.Number).ToList();
    }

    public static DiskCandidate? Find(int number) => Safe().FirstOrDefault(d => d.Number == number);

    public static string Describe(DiskCandidate d)
    {
        var letters = d.Letters.Count > 0 ? $" ({string.Join(", ", d.Letters)})" : "";
        return $"{d.Name}{letters} — {SafetyRules.FormatBytes(d.SizeBytes)} [Disk {d.Number}]";
    }
}
