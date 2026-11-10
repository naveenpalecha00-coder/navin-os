using System.Text.RegularExpressions;

namespace NavinUsb.Core;

public static partial class Releases
{
    public const string Repo = "naveenpalecha00-coder/navin-os";
    public const string CreatorTagPrefix = "usb-creator-v";
    public const string OsTagPrefix = "v1.0-build.";

    /// <summary>"usb-creator-v1.2.3" → 1.2.3; null when the tag is not a USB Creator release.</summary>
    public static Version? CreatorVersion(string tag)
    {
        if (!tag.StartsWith(CreatorTagPrefix, StringComparison.Ordinal)) return null;
        return Version.TryParse(tag[CreatorTagPrefix.Length..], out var v) ? v : null;
    }

    public static bool IsNewer(Version latest, Version current) =>
        Normalize(latest).CompareTo(Normalize(current)) > 0;

    private static Version Normalize(Version v) => new(v.Major, Math.Max(0, v.Minor), Math.Max(0, v.Build));

    /// <summary>Every SHA-256 in a release body (lower case).</summary>
    public static IEnumerable<string> Sha256s(string? body) =>
        body is null ? Enumerable.Empty<string>() : ShaRegex().Matches(body).Select(m => m.Value.ToLowerInvariant());

    [GeneratedRegex(@"\b[a-fA-F0-9]{64}\b")]
    private static partial Regex ShaRegex();
}
