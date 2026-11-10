using System.Text;
using NavinUsb.Core;
using Xunit;

public class SafetyRulesTests
{
    private static DiskCandidate Disk(int bus = 7, bool system = false, bool boot = false, bool ro = false, long size = 16_000_000_000, params string[] letters) =>
        new(2, "SanDisk Ultra", "ABC", size, bus, system, boot, ro, letters, 0);

    [Fact] public void UsbDriveIsOffered() => Assert.Null(SafetyRules.ExclusionReason(Disk(letters: "E:"), "C:"));
    [Fact] public void InternalSataDiskIsHidden() => Assert.NotNull(SafetyRules.ExclusionReason(Disk(bus: 11), "C:"));
    [Fact] public void SystemDiskIsHidden() => Assert.NotNull(SafetyRules.ExclusionReason(Disk(system: true), "C:"));
    [Fact] public void BootDiskIsHidden() => Assert.NotNull(SafetyRules.ExclusionReason(Disk(boot: true), "C:"));
    [Fact] public void UsbDiskHoldingWindowsIsHidden() => Assert.NotNull(SafetyRules.ExclusionReason(Disk(letters: "C:"), "C:"));
    [Fact] public void WriteProtectedIsHidden() => Assert.NotNull(SafetyRules.ExclusionReason(Disk(ro: true), "C:"));
    [Fact] public void EmptyCardReaderIsHidden() => Assert.NotNull(SafetyRules.ExclusionReason(Disk(size: 0), "C:"));

    [Fact]
    public void ReplacedDriveIsNotTheSameDrive()
    {
        var a = Disk();
        Assert.True(SafetyRules.IsSameDrive(a, a));
        Assert.False(SafetyRules.IsSameDrive(a, a with { Serial = "XYZ" }));
        Assert.False(SafetyRules.IsSameDrive(a, null));
    }

    [Fact] public void ImageLargerThanDriveIsRejected() => Assert.False(SafetyRules.ImageFits(2_000, 1_000));
    [Fact] public void Fat32IsCappedAt32GB() => Assert.Equal(32768, SafetyRules.Fat32PartitionMegabytes(64L << 30));
    [Fact] public void SmallDriveUsesWholeDisk() => Assert.Null(SafetyRules.Fat32PartitionMegabytes(16L << 30));
    [Fact] public void LabelIsFat32Safe() => Assert.Equal("NAVIN OS 10", SafetyRules.SanitizeFatLabel("navin os 10 build"));
}

public class ImageInspectorTests
{
    private static byte[] Blank() => new byte[ImageInspector.MinimumReadBytes];

    [Fact]
    public void HybridIsoBootsUefiAndLegacy()
    {
        var b = Blank();
        b[0] = 0xEB; b[510] = 0x55; b[511] = 0xAA; b[446 + 16 + 4] = 0xEF;
        Encoding.ASCII.GetBytes("CD001").CopyTo(b, 0x8001);
        var i = ImageInspector.Inspect(b, 100);
        Assert.True(i.IsHybridIso);
        Assert.Equal("UEFI + Legacy BIOS", i.RawTargetDescription);
    }

    [Fact]
    public void PlainIsoCannotBeRawWritten()
    {
        var b = Blank();
        Encoding.ASCII.GetBytes("CD001").CopyTo(b, 0x8001);
        var i = ImageInspector.Inspect(b, 100);
        Assert.True(i.IsIso9660);
        Assert.False(i.SupportsRawWrite);
    }

    [Fact]
    public void GptImageIsUefi()
    {
        var b = Blank();
        b[510] = 0x55; b[511] = 0xAA; b[446 + 4] = 0xEE;
        Encoding.ASCII.GetBytes("EFI PART").CopyTo(b, 512);
        Assert.Equal("GPT (from image)", ImageInspector.Inspect(b, 100).PartitionSchemeFromImage);
    }
}

public class ReleaseTests
{
    [Fact] public void ParsesCreatorTag() => Assert.Equal(new Version(1, 2, 3), Releases.CreatorVersion("usb-creator-v1.2.3"));
    [Fact] public void IgnoresOsTags() => Assert.Null(Releases.CreatorVersion("v1.0-build.10"));
    [Fact] public void NewerVersionDetected() => Assert.True(Releases.IsNewer(new Version(1, 0, 1), new Version(1, 0, 0)));
    [Fact] public void SameVersionIsNotNewer() => Assert.False(Releases.IsNewer(new Version(1, 0), new Version(1, 0, 0)));

    [Fact]
    public void FindsChecksumsInReleaseNotes()
    {
        var sha = new string('a', 64);
        Assert.Equal(new[] { sha }, Releases.Sha256s($"SHA-256: {sha.ToUpperInvariant()}"));
    }
}

public class DiskpartTests
{
    [Fact]
    public void MbrScriptMarksPartitionActive()
    {
        var s = DiskpartScript.Fat32(3, false, 16L << 30, "navin", 4096, true, 'Z');
        Assert.Contains("select disk 3", s);
        Assert.Contains("convert mbr", s);
        Assert.Contains("format fs=fat32 label=\"NAVIN\" unit=4096 quick", s);
        Assert.Contains("active", s);
    }

    [Fact]
    public void GptScriptLimitsLargeDrivesTo32GB()
    {
        var s = DiskpartScript.Fat32(3, true, 128L << 30, "NAVIN", 0, false, 'Z');
        Assert.Contains("convert gpt", s);
        Assert.Contains("size=32768", s);
        Assert.DoesNotContain("active", s);
        Assert.DoesNotContain("quick", s);
    }

    [Fact] public void RejectsUnknownClusterSize() => Assert.Throws<ArgumentOutOfRangeException>(() => DiskpartScript.Fat32(1, true, 1L << 30, "X", 1234, true, 'Z'));
}

public class TransferStatsTests
{
    [Fact]
    public void ComputesSpeedAndEta()
    {
        var s = new TransferStats(100_000_000);
        s.Update(0, 0);
        s.Update(10_000_000, 1);
        Assert.Equal(10, s.Percent, 3);
        Assert.Equal(10_000_000, s.BytesPerSecond, 0);
        Assert.Equal(9, s.Remaining!.Value.TotalSeconds, 0);
    }
}
