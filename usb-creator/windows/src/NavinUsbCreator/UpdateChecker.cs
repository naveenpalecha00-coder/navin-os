using System.Net.Http.Headers;
using System.Reflection;
using System.Text.Json;
using NavinUsb.Core;

namespace NavinUsbCreator;

internal sealed record UpdateInfo(Version Latest, string Url, bool IsNewer);

/// <summary>Reads public GitHub release information. Sends no personal data.</summary>
internal static class UpdateChecker
{
    private static readonly HttpClient Http = CreateClient();

    public static Version Current =>
        Assembly.GetExecutingAssembly().GetName().Version is { } v ? new Version(v.Major, v.Minor, Math.Max(0, v.Build)) : new Version(1, 0, 0);

    private static HttpClient CreateClient()
    {
        var c = new HttpClient { Timeout = TimeSpan.FromSeconds(15) };
        c.DefaultRequestHeaders.UserAgent.Add(new ProductInfoHeaderValue("NavinUsbCreator", Current.ToString()));
        c.DefaultRequestHeaders.Accept.ParseAdd("application/vnd.github+json");
        return c;
    }

    private static async Task<JsonElement> ReleasesAsync(CancellationToken t)
    {
        var json = await Http.GetStringAsync($"https://api.github.com/repos/{Releases.Repo}/releases?per_page=50", t);
        return JsonDocument.Parse(json).RootElement;
    }

    public static async Task<UpdateInfo?> CheckAsync(CancellationToken t = default)
    {
        UpdateInfo? best = null;
        foreach (var r in (await ReleasesAsync(t)).EnumerateArray())
        {
            if (r.GetProperty("draft").GetBoolean()) continue;
            var v = Releases.CreatorVersion(r.GetProperty("tag_name").GetString() ?? "");
            if (v is null || (best is not null && !Releases.IsNewer(v, best.Latest))) continue;
            best = new UpdateInfo(v, r.GetProperty("html_url").GetString() ?? "", Releases.IsNewer(v, Current));
        }
        return best;
    }

    /// <summary>Maps official NAVIN OS ISO checksums to their release tag (e.g. v1.0-build.10).</summary>
    public static async Task<Dictionary<string, string>> OfficialIsoHashesAsync(CancellationToken t = default)
    {
        var map = new Dictionary<string, string>();
        foreach (var r in (await ReleasesAsync(t)).EnumerateArray())
        {
            var tag = r.GetProperty("tag_name").GetString() ?? "";
            if (!tag.StartsWith(Releases.OsTagPrefix, StringComparison.Ordinal)) continue;
            var body = r.TryGetProperty("body", out var b) ? b.GetString() : null;
            foreach (var sha in Releases.Sha256s(body)) map.TryAdd(sha, tag);
        }
        return map;
    }
}
