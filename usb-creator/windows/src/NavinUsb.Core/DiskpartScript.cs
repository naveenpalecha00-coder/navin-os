namespace NavinUsb.Core;

/// <summary>Builds the Windows diskpart scripts used to wipe and partition the chosen USB disk.</summary>
public static class DiskpartScript
{
    /// <summary>Removes every partition so Windows releases all volumes before a raw write.</summary>
    public static string Clean(int disk) => $"select disk {disk}\r\nattributes disk clear readonly\r\nclean\r\nrescan\r\nexit\r\n";

    /// <summary>One FAT32 partition on GPT or MBR, given a drive letter.</summary>
    public static string Fat32(int disk, bool gpt, long diskBytes, string label, int clusterBytes, bool quick, char letter)
    {
        if (clusterBytes != 0 && !SafetyRules.Fat32ClusterSizes.Contains(clusterBytes))
            throw new ArgumentOutOfRangeException(nameof(clusterBytes));
        var size = SafetyRules.Fat32PartitionMegabytes(diskBytes);
        var lines = new List<string>
        {
            $"select disk {disk}",
            "attributes disk clear readonly",
            "clean",
            gpt ? "convert gpt" : "convert mbr",
            size is null ? "create partition primary" : $"create partition primary size={size}",
            $"format fs=fat32 label=\"{SafetyRules.SanitizeFatLabel(label)}\"" + (clusterBytes > 0 ? $" unit={clusterBytes}" : "") + (quick ? " quick" : ""),
            $"assign letter={letter}",
        };
        if (!gpt) lines.Add("active");
        lines.Add("exit");
        return string.Join("\r\n", lines) + "\r\n";
    }
}
