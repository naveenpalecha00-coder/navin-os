namespace NavinUsb.Core;

/// <summary>Progress, smoothed speed and time remaining for a long copy.</summary>
public sealed class TransferStats
{
    private readonly long _total;
    private double _speed; // bytes per second, smoothed
    private long _lastBytes;
    private double _lastSeconds;

    public TransferStats(long totalBytes) => _total = Math.Max(1, totalBytes);

    public long Done { get; private set; }
    public double Percent => Math.Min(100.0, Done * 100.0 / _total);
    public double BytesPerSecond => _speed;

    public TimeSpan? Remaining => _speed > 1 ? TimeSpan.FromSeconds((_total - Done) / _speed) : null;

    /// <summary>Records progress; <paramref name="elapsedSeconds"/> is time since the copy began.</summary>
    public void Update(long doneBytes, double elapsedSeconds)
    {
        Done = Math.Clamp(doneBytes, 0, _total);
        var dt = elapsedSeconds - _lastSeconds;
        if (dt < 0.25) return;
        var instant = (Done - _lastBytes) / dt;
        _speed = _speed <= 0 ? instant : _speed * 0.7 + instant * 0.3;
        _lastBytes = Done;
        _lastSeconds = elapsedSeconds;
    }

    public static string FormatEta(TimeSpan? t) =>
        t is null ? "calculating…" : t.Value.TotalHours >= 1 ? t.Value.ToString(@"h\:mm\:ss") : t.Value.ToString(@"m\:ss");
}
