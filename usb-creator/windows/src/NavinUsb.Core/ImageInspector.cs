using System.Text;

namespace NavinUsb.Core;

/// <summary>What a disk image can boot, read straight from its first sectors.</summary>
public sealed record ImageInfo(
    long Length,
    bool IsIso9660,
    bool HasElTorito,
    bool HasMbrSignature,
    bool HasMbrBootCode,
    bool HasGpt,
    bool HasEfiPartition)
{
    /// <summary>A raw (DD) copy boots only if the image already carries its own partition table.</summary>
    public bool SupportsRawWrite => HasMbrSignature || HasGpt;

    /// <summary>ISO 9660 with an MBR/GPT = "isohybrid" (Debian, NAVIN OS, Ubuntu, Fedora...).</summary>
    public bool IsHybridIso => IsIso9660 && SupportsRawWrite;

    public bool RawBootsUefi => HasGpt || HasEfiPartition;
    public bool RawBootsLegacy => HasMbrSignature && HasMbrBootCode;

    public string PartitionSchemeFromImage => HasGpt ? "GPT (from image)" : HasMbrSignature ? "MBR (from image)" : "None";

    public string RawTargetDescription => (RawBootsUefi, RawBootsLegacy) switch
    {
        (true, true) => "UEFI + Legacy BIOS",
        (true, false) => "UEFI only",
        (false, true) => "Legacy BIOS only",
        _ => "Not bootable as a disk image",
    };
}

public static class ImageInspector
{
    public const int Iso9660DescriptorOffset = 0x8000; // sector 16 of 2048 bytes
    public const int MinimumReadBytes = 0x8800 + 2048;

    /// <summary>Inspects the image header. <paramref name="head"/> must hold at least the first 36 KiB.</summary>
    public static ImageInfo Inspect(ReadOnlySpan<byte> head, long length)
    {
        bool mbrSig = head.Length >= 512 && head[510] == 0x55 && head[511] == 0xAA;
        bool bootCode = false;
        bool efiPart = false;
        if (mbrSig)
        {
            for (int i = 0; i < 440; i++) if (head[i] != 0) { bootCode = true; break; }
            for (int p = 0; p < 4; p++)
            {
                byte type = head[446 + p * 16 + 4];
                if (type == 0xEF || type == 0xEE) efiPart = true;
            }
        }
        bool gpt = HasAscii(head, 512, "EFI PART");
        bool iso = HasAscii(head, Iso9660DescriptorOffset + 1, "CD001");
        bool torito = HasAscii(head, 0x8800 + 1, "CD001") && head.Length > 0x8800 && head[0x8800] == 0
                      && HasAscii(head, 0x8800 + 7, "EL TORITO SPECIFICATION");
        return new ImageInfo(length, iso, torito, mbrSig, bootCode, gpt, efiPart);
    }

    private static bool HasAscii(ReadOnlySpan<byte> data, int offset, string text)
    {
        if (offset < 0 || offset + text.Length > data.Length) return false;
        return data.Slice(offset, text.Length).SequenceEqual(Encoding.ASCII.GetBytes(text));
    }
}
