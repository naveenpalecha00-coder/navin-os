using System.Diagnostics;
using System.Security.Cryptography;
using System.Text.RegularExpressions;
using DiscUtils.Iso9660;
using NavinUsb.Core;

namespace NavinUsbCreator;

internal sealed record IsoFiles(List<(string Source, string Target, long Size)> Files, long TotalBytes, bool HasUefiLoader, string? TooLargeFile);

/// <summary>
/// "Extract files" mode: makes one FAT32 partition (GPT or MBR) and copies the ISO's files onto it.
/// The result boots on UEFI PCs through \EFI\BOOT\BOOTX64.EFI. Legacy BIOS boot is not offered in this mode.
/// </summary>
internal static class IsoExtractWriter
{
    public static IsoFiles Scan(string isoPath)
    {
        using var stream = File.OpenRead(isoPath);
        using var cd = new CDReader(stream, true);
        var files = new List<(string, string, long)>();
        long total = 0;
        string? tooLarge = null;
        bool uefi = false;
        foreach (var src in cd.GetFiles("", "*.*", SearchOption.AllDirectories))
        {
            string target = Regex.Replace(src.TrimStart('\\'), @";\d+$", "").TrimEnd('.');
            long size = cd.GetFileLength(src);
            if (size > SafetyRules.Fat32MaxFileSize) tooLarge ??= target;
            if (target.Equals(@"EFI\BOOT\BOOTX64.EFI", StringComparison.OrdinalIgnoreCase)) uefi = true;
            files.Add((src, target, size));
            total += size;
        }
        return new IsoFiles(files, total, uefi, tooLarge);
    }

    public static async Task<WriteResult> WriteAsync(DiskCandidate disk, string isoPath, IsoFiles plan, bool gpt, string label, int cluster, bool quick, bool verify,
        IProgress<WriteProgress> progress, CancellationToken token)
    {
        if (plan.TooLargeFile is not null) throw new IOException($"\"{plan.TooLargeFile}\" is larger than 4 GB, which FAT32 cannot store. Use disk image mode.");
        if (!plan.HasUefiLoader) throw new IOException("This ISO has no UEFI boot loader (EFI\\BOOT\\BOOTX64.EFI). Use disk image mode instead.");
        char letter = FreeLetter();
        progress.Report(new WriteProgress(quick ? "Formatting (quick)" : "Formatting (full — this can take a long time)", 0, 0, null, 0, 0));
        await Diskpart.RunAsync(DiskpartScript.Fat32(disk.Number, gpt, disk.SizeBytes, label, cluster, quick, letter), CancellationToken.None);
        string root = $"{letter}:\\";
        for (int i = 0; i < 20 && !Directory.Exists(root); i++) await Task.Delay(500, CancellationToken.None);
        if (!Directory.Exists(root)) throw new IOException("Windows formatted the drive but did not give it a drive letter.");
        return await Task.Run(() => Copy(isoPath, plan, root, verify, progress, token), CancellationToken.None);
    }

    private static WriteResult Copy(string isoPath, IsoFiles plan, string root, bool verify, IProgress<WriteProgress> progress, CancellationToken token)
    {
        var clock = Stopwatch.StartNew();
        using var stream = File.OpenRead(isoPath);
        using var cd = new CDReader(stream, true);
        var stats = new TransferStats(plan.TotalBytes);
        var buf = new byte[4 * 1024 * 1024];
        long done = 0;
        var hashes = new Dictionary<string, byte[]>();
        foreach (var (src, target, _) in plan.Files)
        {
            token.ThrowIfCancellationRequested();
            string dest = Path.Combine(root, target);
            Directory.CreateDirectory(Path.GetDirectoryName(dest)!);
            using var input = cd.OpenFile(src, FileMode.Open);
            using var output = new FileStream(dest, FileMode.Create, FileAccess.Write, FileShare.None, 1 << 20, FileOptions.WriteThrough);
            using var sha = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
            int n;
            while ((n = input.Read(buf, 0, buf.Length)) > 0)
            {
                token.ThrowIfCancellationRequested();
                output.Write(buf, 0, n);
                sha.AppendData(buf, 0, n);
                done += n;
                stats.Update(done, clock.Elapsed.TotalSeconds);
                progress.Report(new WriteProgress($"Copying {target}", stats.Percent, stats.BytesPerSecond, stats.Remaining, done, plan.TotalBytes));
            }
            output.Flush(true);
            hashes[dest] = sha.GetHashAndReset();
        }

        bool verified = false;
        if (verify)
        {
            var vstats = new TransferStats(plan.TotalBytes);
            var vclock = Stopwatch.StartNew();
            long checkedBytes = 0;
            foreach (var (dest, expected) in hashes)
            {
                token.ThrowIfCancellationRequested();
                using var f = new FileStream(dest, FileMode.Open, FileAccess.Read, FileShare.Read, 1 << 20, FileOptions.SequentialScan);
                using var sha = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
                int n;
                while ((n = f.Read(buf, 0, buf.Length)) > 0)
                {
                    sha.AppendData(buf, 0, n);
                    checkedBytes += n;
                    vstats.Update(checkedBytes, vclock.Elapsed.TotalSeconds);
                    progress.Report(new WriteProgress("Verifying files", vstats.Percent, vstats.BytesPerSecond, vstats.Remaining, checkedBytes, plan.TotalBytes));
                }
                if (!sha.GetHashAndReset().AsSpan().SequenceEqual(expected))
                    throw new IOException($"Verification failed for {dest}. The USB drive may be faulty — try another drive.");
            }
            verified = true;
        }
        stream.Position = 0;
        string isoHash = Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
        return new WriteResult(isoHash, verified, clock.Elapsed);
    }

    private static char FreeLetter()
    {
        var used = DriveInfo.GetDrives().Select(d => char.ToUpperInvariant(d.Name[0])).ToHashSet();
        for (char c = 'Z'; c >= 'D'; c--) if (!used.Contains(c)) return c;
        throw new IOException("No free drive letter is available. Disconnect another drive and try again.");
    }
}
