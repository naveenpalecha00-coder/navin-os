using System.Diagnostics;
using NavinUsb.Core;

namespace NavinUsbCreator;

internal sealed class MainForm : Form
{
    private sealed record DriveItem(DiskCandidate Disk)
    {
        public override string ToString() => DriveScanner.Describe(Disk);
    }

    private const string ModeRaw = "Disk image (DD) — recommended for NAVIN OS";
    private const string ModeExtract = "Extract files to FAT32 (UEFI)";

    private readonly ComboBox _device = Combo();
    private readonly Label _deviceInfo = Hint("");
    private readonly TextBox _isoPath = new() { ReadOnly = true, Dock = DockStyle.Fill, Font = Theme.Body, BackColor = Theme.Window, PlaceholderText = "No image selected" };
    private readonly Label _imageInfo = Hint("Choose the NAVIN OS ISO (or another bootable Linux ISO).");
    private readonly ComboBox _mode = Combo();
    private readonly ComboBox _scheme = Combo();
    private readonly ComboBox _target = Combo();
    private readonly TextBox _label = new() { Text = "NAVIN", Dock = DockStyle.Fill, Font = Theme.Body, MaxLength = 11, CharacterCasing = CharacterCasing.Upper };
    private readonly ComboBox _fs = Combo();
    private readonly ComboBox _cluster = Combo();
    private readonly CheckBox _quick = new() { Text = "Quick format", Checked = true, AutoSize = true, Font = Theme.Body };
    private readonly CheckBox _verify = new() { Text = "Verify the drive after writing (recommended)", Checked = true, AutoSize = true, Font = Theme.Body };
    private readonly ProgressBar _bar = new() { Dock = DockStyle.Fill, Height = 22, Maximum = 1000 };
    private readonly Label _status = new() { Text = "Ready", AutoSize = true, Font = Theme.Section, ForeColor = Theme.Text };
    private readonly Label _details = Hint("");
    private readonly ListBox _log = new() { Dock = DockStyle.Fill, Height = 90, Font = Theme.Mono, BorderStyle = BorderStyle.FixedSingle, IntegralHeight = false };
    private readonly Button _start = Theme.PrimaryButton("START");
    private readonly Button _cancel = Theme.SecondaryButton("CANCEL");
    private readonly LinkLabel _update = new() { AutoSize = true, Font = Theme.Small, Text = "Check for updates", LinkColor = Theme.Primary };
    private readonly Panel _done = new() { Dock = DockStyle.Fill, BackColor = Theme.Window, Visible = false, Padding = new Padding(28) };
    private readonly Label _doneText = new() { AutoSize = true, Font = Theme.Body, ForeColor = Theme.Text, MaximumSize = new Size(470, 0) };
    private readonly System.Windows.Forms.Timer _deviceTimer = new() { Interval = 1200 };

    private ImageInfo? _image;
    private IsoFiles? _iso;
    private CancellationTokenSource? _cts;
    private bool _busy;

    public MainForm()
    {
        Text = $"NAVIN USB Creator {UpdateChecker.Current}";
        BackColor = Theme.Window;
        ForeColor = Theme.Text;
        Font = Theme.Body;
        ClientSize = new Size(560, 860);
        MinimumSize = new Size(560, 640);
        StartPosition = FormStartPosition.CenterScreen;

        var root = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, AutoScroll = true, Padding = new Padding(18, 14, 18, 14) };
        root.Controls.Add(BuildHeader());
        root.Controls.Add(BuildDriveSection());
        root.Controls.Add(BuildFormatSection());
        root.Controls.Add(BuildStatusSection());
        root.Controls.Add(BuildButtons());
        Controls.Add(_done);
        Controls.Add(root);
        BuildCompletion();

        _mode.SelectedIndexChanged += (_, _) => ApplyMode();
        _device.SelectedIndexChanged += (_, _) => ShowDeviceInfo();
        _start.Click += async (_, _) => await StartAsync();
        _cancel.Click += (_, _) => CancelWrite();
        _update.LinkClicked += async (_, _) => await CheckUpdatesAsync(interactive: true);
        _deviceTimer.Tick += async (_, _) => { _deviceTimer.Stop(); if (!_busy) await RefreshDrivesAsync(); };
        _cancel.Enabled = false;
        SetOptions(_fs, "FAT32");
        SetOptions(_cluster, "Default", "4096 bytes", "8192 bytes", "16 kilobytes", "32 kilobytes");
        ApplyMode();

        Shown += async (_, _) =>
        {
            Log("NAVIN USB Creator started. Only USB/SD drives are listed; the Windows disk is always hidden.");
            await RefreshDrivesAsync();
            await CheckUpdatesAsync(interactive: false);
        };
        FormClosing += (_, e) =>
        {
            if (!_busy) return;
            e.Cancel = true;
            MessageBox.Show(this, "A write is in progress. Press CANCEL and wait for it to stop before closing.", "NAVIN USB Creator", MessageBoxButtons.OK, MessageBoxIcon.Warning);
        };
    }

    // ---------- layout ----------

    private static ComboBox Combo() => new() { DropDownStyle = ComboBoxStyle.DropDownList, Dock = DockStyle.Fill, Font = Theme.Body, FlatStyle = FlatStyle.Flat };
    private static Label Hint(string t) => new() { Text = t, AutoSize = true, Font = Theme.Small, ForeColor = Theme.Muted, MaximumSize = new Size(500, 0) };

    private Control BuildHeader()
    {
        var p = new TableLayoutPanel { Dock = DockStyle.Top, AutoSize = true, ColumnCount = 2, Margin = new Padding(0, 0, 0, 8) };
        p.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        p.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        var title = new Label { Text = "NAVIN USB Creator", Font = Theme.Title, ForeColor = Theme.Primary, AutoSize = true };
        var sub = Hint($"Version {UpdateChecker.Current} · Creates bootable NAVIN OS USB drives");
        var left = new FlowLayoutPanel { FlowDirection = FlowDirection.TopDown, AutoSize = true, WrapContents = false };
        left.Controls.Add(title);
        left.Controls.Add(sub);
        p.Controls.Add(left, 0, 0);
        p.Controls.Add(_update, 1, 0);
        return p;
    }

    private static TableLayoutPanel Section(string title, out TableLayoutPanel grid)
    {
        var outer = new TableLayoutPanel { Dock = DockStyle.Top, AutoSize = true, ColumnCount = 1, BackColor = Theme.Panel, Padding = new Padding(12), Margin = new Padding(0, 6, 0, 6) };
        outer.Controls.Add(new Label { Text = title, Font = Theme.Section, ForeColor = Theme.Text, AutoSize = true, Margin = new Padding(0, 0, 0, 6) });
        grid = new TableLayoutPanel { Dock = DockStyle.Top, AutoSize = true, ColumnCount = 2 };
        grid.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 130));
        grid.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        outer.Controls.Add(grid);
        return outer;
    }

    private static void Row(TableLayoutPanel g, string label, Control c)
    {
        int r = g.RowCount++;
        g.Controls.Add(new Label { Text = label, AutoSize = true, Anchor = AnchorStyles.Left, Font = Theme.Body, ForeColor = Theme.Muted, Margin = new Padding(0, 8, 6, 4) }, 0, r);
        c.Margin = new Padding(0, 4, 0, 4);
        g.Controls.Add(c, 1, r);
    }

    private static void Full(TableLayoutPanel g, Control c)
    {
        int r = g.RowCount++;
        g.Controls.Add(c, 0, r);
        g.SetColumnSpan(c, 2);
    }

    private Control BuildDriveSection()
    {
        var s = Section("Drive Properties", out var g);
        var refresh = Theme.SecondaryButton("↻");
        refresh.Click += async (_, _) => await RefreshDrivesAsync();
        var devRow = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 2, AutoSize = true, Margin = Padding.Empty };
        devRow.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        devRow.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        devRow.Controls.Add(_device, 0, 0);
        devRow.Controls.Add(refresh, 1, 0);
        Row(g, "Device", devRow);
        Full(g, _deviceInfo);

        var select = Theme.SecondaryButton("SELECT");
        select.Click += async (_, _) => await SelectImageAsync();
        var bootRow = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 2, AutoSize = true, Margin = Padding.Empty };
        bootRow.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        bootRow.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        bootRow.Controls.Add(_isoPath, 0, 0);
        bootRow.Controls.Add(select, 1, 0);
        Row(g, "Boot selection", bootRow);
        Full(g, _imageInfo);
        Row(g, "Write mode", _mode);
        Row(g, "Partition scheme", _scheme);
        Row(g, "Target system", _target);
        return s;
    }

    private Control BuildFormatSection()
    {
        var s = Section("Format Options", out var g);
        Row(g, "Volume label", _label);
        Row(g, "File system", _fs);
        Row(g, "Cluster size", _cluster);
        Full(g, _quick);
        Full(g, _verify);
        return s;
    }

    private Control BuildStatusSection()
    {
        var s = Section("Status", out var g);
        Full(g, _status);
        Full(g, _bar);
        Full(g, _details);
        Full(g, _log);
        return s;
    }

    private Control BuildButtons()
    {
        var p = new TableLayoutPanel { Dock = DockStyle.Top, AutoSize = true, ColumnCount = 2, Margin = new Padding(0, 8, 0, 0) };
        p.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        p.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        _start.Dock = DockStyle.Fill;
        _cancel.Height = 40;
        _cancel.Margin = new Padding(8, 3, 0, 3);
        p.Controls.Add(_start, 0, 0);
        p.Controls.Add(_cancel, 1, 0);
        return p;
    }

    private void BuildCompletion()
    {
        var flow = new FlowLayoutPanel { FlowDirection = FlowDirection.TopDown, Dock = DockStyle.Fill, WrapContents = false, BackColor = Theme.PaleBlue, Padding = new Padding(24) };
        flow.Controls.Add(new Label { Text = "✓", Font = new Font("Segoe UI", 40f), ForeColor = Theme.Success, AutoSize = true });
        flow.Controls.Add(new Label { Text = "Your bootable USB is ready", Font = Theme.Title, ForeColor = Theme.Text, AutoSize = true });
        flow.Controls.Add(_doneText);
        var again = Theme.PrimaryButton("Write another drive");
        again.Width = 220;
        again.Margin = new Padding(0, 16, 0, 0);
        again.Click += (_, _) => { _done.Visible = false; ResetProgress(); };
        flow.Controls.Add(again);
        _done.Controls.Add(flow);
    }

    private static void SetOptions(ComboBox c, params string[] items)
    {
        c.Items.Clear();
        c.Items.AddRange(items);
        if (items.Length > 0) c.SelectedIndex = 0;
    }

    // ---------- behaviour ----------

    protected override void WndProc(ref Message m)
    {
        const int WM_DEVICECHANGE = 0x0219;
        if (m.Msg == WM_DEVICECHANGE) { _deviceTimer.Stop(); _deviceTimer.Start(); }
        base.WndProc(ref m);
    }

    private void Log(string text)
    {
        _log.Items.Add($"{DateTime.Now:HH:mm:ss}  {text}");
        _log.TopIndex = Math.Max(0, _log.Items.Count - 1);
    }

    private async Task RefreshDrivesAsync()
    {
        var keep = (_device.SelectedItem as DriveItem)?.Disk;
        List<DiskCandidate> drives;
        try { drives = await Task.Run(DriveScanner.Safe); }
        catch (Exception ex) { Log($"Could not list drives: {ex.Message}"); return; }
        _device.Items.Clear();
        foreach (var d in drives) _device.Items.Add(new DriveItem(d));
        var again = drives.FindIndex(d => keep is not null && d.Number == keep.Number && d.Serial == keep.Serial);
        if (_device.Items.Count > 0) _device.SelectedIndex = again >= 0 ? again : 0;
        ShowDeviceInfo();
        Log(drives.Count == 0 ? "No USB drive found. Plug one in — the list refreshes automatically." : $"Found {drives.Count} USB drive(s).");
    }

    private void ShowDeviceInfo()
    {
        if (_device.SelectedItem is not DriveItem { Disk: var d })
        {
            _deviceInfo.Text = "No USB drive detected. Plug one in.";
            return;
        }
        var free = d.Letters.Count > 0 ? $"{SafetyRules.FormatBytes(d.FreeBytes)} free on {string.Join(", ", d.Letters)}" : "no mounted volume";
        _deviceInfo.Text = $"Capacity {SafetyRules.FormatBytes(d.SizeBytes)} · {free} · Bus: {(d.BusType == 7 ? "USB" : "SD/MMC")}";
    }

    private async Task SelectImageAsync()
    {
        using var dlg = new OpenFileDialog { Filter = "Disk images (*.iso;*.img)|*.iso;*.img|All files (*.*)|*.*", Title = "Choose a bootable image" };
        if (dlg.ShowDialog(this) != DialogResult.OK) return;
        string path = dlg.FileName;
        _imageInfo.Text = "Reading image…";
        try
        {
            var (info, iso) = await Task.Run(() =>
            {
                long len = new FileInfo(path).Length;
                var head = new byte[ImageInspector.MinimumReadBytes];
                using (var f = File.OpenRead(path)) f.ReadAtLeast(head, Math.Min(head.Length, (int)Math.Min(len, head.Length)), false);
                var i = ImageInspector.Inspect(head, len);
                IsoFiles? files = null;
                if (i.IsIso9660) { try { files = IsoExtractWriter.Scan(path); } catch (Exception) { files = null; } }
                return (i, files);
            });
            _image = info;
            _iso = iso;
            _isoPath.Text = path;
            var modes = new List<string>();
            if (info.SupportsRawWrite) modes.Add(ModeRaw);
            if (iso is { HasUefiLoader: true, TooLargeFile: null }) modes.Add(ModeExtract);
            SetOptions(_mode, modes.ToArray());
            if (modes.Count == 0)
            {
                _imageInfo.Text = "This image cannot be made bootable: it has no partition table and no UEFI boot loader.";
                _imageInfo.ForeColor = Theme.Danger;
            }
            else
            {
                _imageInfo.ForeColor = Theme.Muted;
                _imageInfo.Text = $"{Path.GetFileName(path)} · {SafetyRules.FormatBytes(info.Length)} · " +
                                  (info.IsHybridIso ? $"Hybrid ISO, boots {info.RawTargetDescription}" : info.IsIso9660 ? "ISO (UEFI files)" : $"Disk image, boots {info.RawTargetDescription}");
                if (_label.Text == "NAVIN" && Path.GetFileName(path).StartsWith("navin", StringComparison.OrdinalIgnoreCase)) _label.Text = "NAVIN OS";
            }
            Log($"Selected {Path.GetFileName(path)} ({SafetyRules.FormatBytes(info.Length)}).");
            ApplyMode();
        }
        catch (Exception ex)
        {
            _image = null;
            _imageInfo.Text = $"Could not read the image: {ex.Message}";
            _imageInfo.ForeColor = Theme.Danger;
        }
    }

    private bool RawMode => (_mode.SelectedItem as string) == ModeRaw;

    private void ApplyMode()
    {
        if (_mode.Items.Count == 0 || _image is null)
        {
            SetOptions(_scheme, "—");
            SetOptions(_target, "—");
            foreach (Control c in new Control[] { _mode, _scheme, _target, _label, _fs, _cluster, _quick }) c.Enabled = false;
            return;
        }
        _mode.Enabled = _mode.Items.Count > 1;
        if (RawMode)
        {
            SetOptions(_scheme, _image.PartitionSchemeFromImage);
            SetOptions(_target, _image.RawTargetDescription);
            SetOptions(_fs, "Set by the image");
            SetOptions(_cluster, "Set by the image");
            foreach (Control c in new Control[] { _scheme, _target, _label, _fs, _cluster, _quick }) c.Enabled = false;
        }
        else
        {
            SetOptions(_scheme, "GPT", "MBR");
            SetOptions(_target, "UEFI (non-CSM)");
            SetOptions(_fs, "FAT32");
            SetOptions(_cluster, "Default", "4096 bytes", "8192 bytes", "16 kilobytes", "32 kilobytes");
            _scheme.Enabled = _label.Enabled = _cluster.Enabled = _quick.Enabled = true;
            _target.Enabled = _fs.Enabled = false;
        }
    }

    private void ResetProgress()
    {
        _bar.Value = 0;
        _status.Text = "Ready";
        _status.ForeColor = Theme.Text;
        _details.Text = "";
    }

    private void SetBusy(bool busy)
    {
        _busy = busy;
        _start.Enabled = !busy;
        _cancel.Enabled = busy;
        foreach (Control c in new Control[] { _device, _mode, _verify }) c.Enabled = !busy;
        if (!busy) ApplyMode();
        else foreach (Control c in new Control[] { _scheme, _label, _cluster, _quick }) c.Enabled = false;
        UseWaitCursor = false;
    }

    private void OnProgress(WriteProgress p)
    {
        _status.Text = $"{p.Phase} — {p.Percent:0.0}%";
        _bar.Value = (int)Math.Clamp(p.Percent * 10, 0, 1000);
        _details.Text = p.Total > 0
            ? $"{SafetyRules.FormatBytes(p.Done)} of {SafetyRules.FormatBytes(p.Total)} · {SafetyRules.FormatBytes((long)p.BytesPerSecond)}/s · {TransferStats.FormatEta(p.Remaining)} left"
            : "";
    }

    private async Task StartAsync()
    {
        if (_device.SelectedItem is not DriveItem { Disk: var chosen }) { MessageBox.Show(this, "Plug in a USB drive and select it under Device.", "No drive"); return; }
        if (_image is null || _mode.Items.Count == 0) { MessageBox.Show(this, "Select a bootable ISO first.", "No image"); return; }
        string path = _isoPath.Text;
        if (RawMode && !SafetyRules.ImageFits(_image.Length, chosen.SizeBytes)) { MessageBox.Show(this, "This drive is too small for the image.", "Drive too small"); return; }
        if (!RawMode && _iso is not null && _iso.TotalBytes > Math.Min(chosen.SizeBytes, SafetyRules.Fat32PartitionLimit)) { MessageBox.Show(this, "This drive is too small for the ISO files.", "Drive too small"); return; }

        // The list may be stale: confirm the drive is still exactly the one shown.
        var now = await Task.Run(() => DriveScanner.Find(chosen.Number));
        if (!SafetyRules.IsSameDrive(chosen, now)) { MessageBox.Show(this, "The drive list changed. Check the selected device and try again.", "Drive changed"); await RefreshDrivesAsync(); return; }
        using (var confirm = new ConfirmEraseDialog(now!, Path.GetFileName(path)))
            if (confirm.ShowDialog(this) != DialogResult.OK) { Log("Cancelled before erasing — nothing was changed."); return; }
        now = await Task.Run(() => DriveScanner.Find(chosen.Number));
        if (!SafetyRules.IsSameDrive(chosen, now)) { MessageBox.Show(this, "The drive was removed or replaced. Nothing was written.", "Drive changed"); await RefreshDrivesAsync(); return; }

        _cts = new CancellationTokenSource();
        SetBusy(true);
        var progress = new Progress<WriteProgress>(OnProgress);
        Log($"Writing {Path.GetFileName(path)} to {DriveScanner.Describe(chosen)} ({(RawMode ? "disk image mode" : "extract mode, " + _scheme.SelectedItem)}).");
        try
        {
            WriteResult result;
            if (RawMode)
                result = await RawImageWriter.WriteAsync(chosen, path, _verify.Checked, progress, _cts.Token);
            else
            {
                int cluster = SafetyRules.Fat32ClusterSizes[Math.Max(0, _cluster.SelectedIndex)];
                result = await IsoExtractWriter.WriteAsync(chosen, path, _iso!, (_scheme.SelectedItem as string) == "GPT", _label.Text, cluster, _quick.Checked, _verify.Checked, progress, _cts.Token);
            }
            string official = "";
            try
            {
                var hashes = await UpdateChecker.OfficialIsoHashesAsync();
                if (hashes.TryGetValue(result.ImageSha256, out var tag)) official = $"\n✓ Matches the official NAVIN OS release {tag}.";
            }
            catch (Exception) { official = "\n(Offline: could not compare with the official NAVIN OS checksums.)"; }
            _status.Text = "Done";
            _status.ForeColor = Theme.Success;
            _bar.Value = 1000;
            Log($"Finished in {result.Duration:m\\:ss}. SHA-256 {result.ImageSha256}");
            _doneText.Text = $"Drive: {DriveScanner.Describe(chosen)}\nImage: {Path.GetFileName(path)}\nTime: {result.Duration:m\\:ss}\n" +
                             $"Verification: {(result.Verified ? "passed — every byte matched" : "skipped")}\nImage SHA-256:\n{result.ImageSha256}{official}\n\n" +
                             "Safely eject the drive, plug it into the PC, and choose it from the boot menu (often F12, F11, F9 or Esc).";
            _done.Visible = true;
            _done.BringToFront();
        }
        catch (OperationCanceledException)
        {
            _status.Text = "Cancelled";
            _status.ForeColor = Theme.Danger;
            Log("Cancelled. The drive is incomplete — write it again or format it before using it.");
            MessageBox.Show(this, "Writing was stopped safely. The drive is incomplete and will not boot. Write it again, or format it in File Explorer to use it for files.", "Cancelled", MessageBoxButtons.OK, MessageBoxIcon.Information);
        }
        catch (Exception ex)
        {
            _status.Text = "Failed";
            _status.ForeColor = Theme.Danger;
            Log($"Error: {ex.Message}");
            MessageBox.Show(this, ex.Message, "Could not create the USB drive", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
        finally
        {
            _cts.Dispose();
            _cts = null;
            SetBusy(false);
            await RefreshDrivesAsync();
        }
    }

    private void CancelWrite()
    {
        if (_cts is null) return;
        if (MessageBox.Show(this, "Stop writing? The drive will be left incomplete and will not boot until written again.", "Cancel", MessageBoxButtons.YesNo, MessageBoxIcon.Question) == DialogResult.Yes)
        {
            _cts.Cancel();
            _status.Text = "Stopping safely…";
        }
    }

    private async Task CheckUpdatesAsync(bool interactive)
    {
        try
        {
            var info = await UpdateChecker.CheckAsync();
            if (info is { IsNewer: true })
            {
                _update.Text = $"Update available: {info.Latest}";
                _update.LinkColor = Theme.Success;
                if (interactive || _update.Tag is null)
                {
                    _update.Tag = info.Url;
                    if (interactive && MessageBox.Show(this, $"Version {info.Latest} is available (you have {UpdateChecker.Current}). Open the download page?", "Update available", MessageBoxButtons.YesNo) == DialogResult.Yes)
                        Process.Start(new ProcessStartInfo(info.Url) { UseShellExecute = true });
                }
            }
            else if (interactive) MessageBox.Show(this, $"You have the latest version ({UpdateChecker.Current}).", "No updates");
        }
        catch (Exception ex)
        {
            if (interactive) MessageBox.Show(this, $"Could not check for updates: {ex.Message}", "Offline");
        }
    }
}
