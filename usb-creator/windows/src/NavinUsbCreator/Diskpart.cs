using System.Diagnostics;

namespace NavinUsbCreator;

/// <summary>Runs a Windows diskpart script and fails loudly when any step fails.</summary>
internal static class Diskpart
{
    public static async Task RunAsync(string script, CancellationToken token)
    {
        var file = Path.Combine(Path.GetTempPath(), $"navin-diskpart-{Guid.NewGuid():N}.txt");
        await File.WriteAllTextAsync(file, script, token);
        try
        {
            var psi = new ProcessStartInfo("diskpart.exe", $"/s \"{file}\"")
            {
                CreateNoWindow = true,
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
            };
            using var p = Process.Start(psi) ?? throw new IOException("Could not start Windows diskpart.");
            var output = await p.StandardOutput.ReadToEndAsync(token);
            await p.WaitForExitAsync(token);
            if (p.ExitCode != 0)
            {
                var tail = string.Join(" ", output.Split('\n').Select(l => l.Trim()).Where(l => l.Length > 0).TakeLast(3));
                throw new IOException($"Windows could not prepare the drive (diskpart error {p.ExitCode}). {tail}");
            }
        }
        finally
        {
            try { File.Delete(file); } catch (IOException) { }
        }
    }
}
