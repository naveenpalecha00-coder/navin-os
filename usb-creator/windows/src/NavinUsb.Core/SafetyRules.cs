namespace NavinUsb.Core;

/// <summary>A disk as reported by Windows storage management.</summary>
public sealed record DiskCandidate(
    int Number,
    string Name,
    string Serial,
    long SizeBytes,
    int BusType,
    bool IsSystem,
    bool IsBoot,
    bool IsReadOnly,
    IReadOnlyList<string> Letters,
    long FreeBytes);

public static class SafetyRules
{
    // MSFT_Disk.BusType values: 7 = USB, 12 = SD, 13 = MMC.
    public static readonly int[] RemovableBusTypes = { 7, 12, 13 };
    public const long Fat32PartitionLimit = 32L * 1024 * 1024 * 1024; // what Windows will format as FAT32
    public const long Fat32MaxFileSize = 4L * 1024 * 1024 * 1024 - 1;

    /// <summary>Returns null when the disk may be offered, otherwise the reason it is hidden.</summary>
    public static string? ExclusionReason(DiskCandidate d, string systemDrive)
    {
        if (!RemovableBusTypes.Contains(d.BusType)) return "not a USB or SD drive";
        if (d.IsSystem || d.IsBoot) return "Windows runs from this disk";
        var sys = systemDrive.TrimEnd('\\').ToUpperInvariant();
        if (d.Letters.Any(l => l.TrimEnd('\\').Equals(sys, StringComparison.OrdinalIgnoreCase))) return "holds the Windows system drive";
        if (d.IsReadOnly) return "write-protected";
        if (d.SizeBytes <= 0) return "no media inserted";
        return null;
    }

    /// <summary>True when the drive at write time is still the exact drive the user confirmed.</summary>
    public static bool IsSameDrive(DiskCandidate confirmed, DiskCandidate? now) =>
        now is not null && now.Number == confirmed.Number && now.SizeBytes == confirmed.SizeBytes
        && now.Serial == confirmed.Serial && now.Name == confirmed.Name;

    public static bool ImageFits(long imageBytes, long diskBytes) => imageBytes > 0 && imageBytes <= diskBytes;

    /// <summary>FAT32 partition size in MB for extract mode, or null to use the whole drive.</summary>
    public static long? Fat32PartitionMegabytes(long diskBytes) =>
        diskBytes > Fat32PartitionLimit ? Fat32PartitionLimit / (1024 * 1024) : null;

    public static readonly int[] Fat32ClusterSizes = { 0, 4096, 8192, 16384, 32768 };

    /// <summary>Volume labels on FAT32: max 11 characters, upper case, no reserved characters.</summary>
    public static string SanitizeFatLabel(string label)
    {
        var bad = "\"*+,./:;<=>?[\\]|";
        var clean = new string(label.ToUpperInvariant().Where(c => c >= 32 && c < 127 && !bad.Contains(c)).ToArray()).Trim();
        if (clean.Length > 11) clean = clean[..11];
        return clean.Length == 0 ? "NAVIN" : clean;
    }

    public static string FormatBytes(long b) => b switch
    {
        >= 1L << 30 => $"{b / (double)(1L << 30):0.0} GB",
        >= 1L << 20 => $"{b / (double)(1L << 20):0.0} MB",
        >= 1L << 10 => $"{b / 1024.0:0} KB",
        _ => $"{b} B",
    };
}
