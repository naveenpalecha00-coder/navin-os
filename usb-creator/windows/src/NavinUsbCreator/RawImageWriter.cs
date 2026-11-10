using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using NavinUsb.Core;

namespace NavinUsbCreator;

internal sealed record WriteProgress(string Phase, double Percent, double BytesPerSecond, TimeSpan? Remaining, long Done, long Total);

internal sealed record WriteResult(string ImageSha256, bool Verified, TimeSpan Duration);

/// <summary>
/// Writes a disk image byte-for-byte to a physical USB drive (like "DD image mode").
/// The first 1 MiB (partition tables) is written last so Windows never mounts a half-written drive.
/// </summary>
internal static class RawImageWriter
{
    private const int Chunk = 4 * 1024 * 1024;
    private const int Head = 1024 * 1024;

    public static async Task<WriteResult> WriteAsync(DiskCandidate disk, string imagePath, bool verify, IProgress<WriteProgress> progress, CancellationToken token)
    {
        progress.Report(new WriteProgress("Preparing drive", 0, 0, null, 0, 0));
        // Remove all partitions first so no Windows volume is mounted on the drive while we write.
        await Diskpart.RunAsync(DiskpartScript.Clean(disk.Number), CancellationToken.None);
        await Task.Delay(1500, CancellationToken.None);
        return await Task.Run(() => Write(disk, imagePath, verify, progress, token), CancellationToken.None);
    }

    private static unsafe WriteResult Write(DiskCandidate disk, string imagePath, bool verify, IProgress<WriteProgress> progress, CancellationToken token)
    {
        var clock = Stopwatch.StartNew();
        using var image = new FileStream(imagePath, FileMode.Open, FileAccess.Read, FileShare.Read, 1 << 20, FileOptions.SequentialScan);
        long length = image.Length;
        using var drive = Native.OpenPhysicalDrive(disk.Number);
        var (sector, size) = Native.Geometry(drive);
        if (!SafetyRules.ImageFits(length, size))
            throw new IOException($"The image ({SafetyRules.FormatBytes(length)}) is larger than the drive ({SafetyRules.FormatBytes(size)}).");

        long padded = RoundUp(length, sector);
        byte* buf = (byte*)NativeMemory.AlignedAlloc(Chunk, 4096);
        byte* head = (byte*)NativeMemory.AlignedAlloc(Head, 4096);
        try
        {
            using var sha = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
            var stats = new TransferStats(padded);

            // 1. Keep the first MiB in memory; it goes to the drive last.
            int headLen = Fill(image, head, Head);
            sha.AppendData(new ReadOnlySpan<byte>(head, headLen));
            int headWrite = (int)RoundUp(headLen, sector);

            // 2. Everything after the first MiB, in order.
            long offset = Head;
            while (offset < padded)
            {
                token.ThrowIfCancellationRequested();
                int n = Fill(image, buf, Chunk);
                if (n == 0) break;
                sha.AppendData(new ReadOnlySpan<byte>(buf, n));
                int w = (int)RoundUp(n, sector);
                Native.Seek(drive, offset);
                Native.Write(drive, buf, w);
                offset += w;
                stats.Update(offset - Head, clock.Elapsed.TotalSeconds);
                progress.Report(new WriteProgress("Writing", stats.Percent, stats.BytesPerSecond, stats.Remaining, stats.Done, padded));
            }

            // 3. Partition tables last, then let Windows re-read them.
            token.ThrowIfCancellationRequested();
            Native.Seek(drive, 0);
            Native.Write(drive, head, headWrite);
            Native.FlushFileBuffers(drive);
            Native.RefreshPartitions(drive);
            stats.Update(padded, clock.Elapsed.TotalSeconds);
            progress.Report(new WriteProgress("Writing", 100, stats.BytesPerSecond, TimeSpan.Zero, padded, padded));
            string imageHash = Convert.ToHexString(sha.GetHashAndReset()).ToLowerInvariant();

            bool verified = false;
            if (verify)
            {
                // 4. Read the drive back and hash exactly as many bytes as the image holds.
                var vstats = new TransferStats(length);
                var vclock = Stopwatch.StartNew();
                long done = 0;
                Native.Seek(drive, 0);
                while (done < length)
                {
                    token.ThrowIfCancellationRequested();
                    int want = (int)Math.Min(Chunk, RoundUp(length - done, sector));
                    Native.Read(drive, buf, want);
                    int useful = (int)Math.Min(want, length - done);
                    sha.AppendData(new ReadOnlySpan<byte>(buf, useful));
                    done += useful;
                    vstats.Update(done, vclock.Elapsed.TotalSeconds);
                    progress.Report(new WriteProgress("Verifying", vstats.Percent, vstats.BytesPerSecond, vstats.Remaining, done, length));
                }
                string driveHash = Convert.ToHexString(sha.GetHashAndReset()).ToLowerInvariant();
                if (driveHash != imageHash)
                    throw new IOException("Verification failed: the data read back from the USB drive does not match the image. The drive may be faulty or counterfeit — try another drive.");
                verified = true;
            }
            return new WriteResult(imageHash, verified, clock.Elapsed);
        }
        finally
        {
            NativeMemory.AlignedFree(buf);
            NativeMemory.AlignedFree(head);
        }
    }

    /// <summary>Reads up to <paramref name="max"/> bytes; zero-fills the sector tail after the last byte.</summary>
    private static unsafe int Fill(Stream s, byte* dst, int max)
    {
        var span = new Span<byte>(dst, max);
        int total = 0;
        while (total < max)
        {
            int n = s.Read(span[total..]);
            if (n == 0) break;
            total += n;
        }
        if (total < max) span[total..Math.Min(max, (int)RoundUp(total, 4096))].Clear();
        return total;
    }

    private static long RoundUp(long v, int m) => (v + m - 1) / m * m;
}
