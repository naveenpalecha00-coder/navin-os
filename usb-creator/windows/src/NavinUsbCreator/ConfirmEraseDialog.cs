using NavinUsb.Core;

namespace NavinUsbCreator;

/// <summary>Explicit erase confirmation: shows the exact drive and requires typing ERASE.</summary>
internal sealed class ConfirmEraseDialog : Form
{
    private readonly TextBox _typed = new() { Width = 200, Font = Theme.Body, CharacterCasing = CharacterCasing.Upper };
    private readonly Button _ok = Theme.PrimaryButton("Erase and write");

    public ConfirmEraseDialog(DiskCandidate d, string imageName)
    {
        Text = "Confirm — all data will be erased";
        FormBorderStyle = FormBorderStyle.FixedDialog;
        StartPosition = FormStartPosition.CenterParent;
        MaximizeBox = MinimizeBox = false;
        BackColor = Theme.Window;
        Font = Theme.Body;
        AutoSize = true;
        AutoSizeMode = AutoSizeMode.GrowAndShrink;
        Padding = new Padding(18);

        var layout = new FlowLayoutPanel { FlowDirection = FlowDirection.TopDown, AutoSize = true, WrapContents = false };
        layout.Controls.Add(new Label { Text = "⚠ Everything on this drive will be permanently erased", Font = Theme.Section, ForeColor = Theme.Danger, AutoSize = true });
        var box = new Label
        {
            AutoSize = true,
            BackColor = Theme.PaleBlue,
            Padding = new Padding(10),
            Margin = new Padding(0, 10, 0, 10),
            MaximumSize = new Size(460, 0),
            Text = $"Drive: {d.Name}\nCapacity: {SafetyRules.FormatBytes(d.SizeBytes)} (Disk {d.Number})\n" +
                   $"Letters: {(d.Letters.Count > 0 ? string.Join(", ", d.Letters) : "none")}\nSerial: {(d.Serial.Length > 0 ? d.Serial : "not reported")}\nImage: {imageName}",
        };
        layout.Controls.Add(box);
        layout.Controls.Add(new Label { Text = "Back up any files you need first. Type ERASE to continue:", AutoSize = true });
        layout.Controls.Add(_typed);
        var buttons = new FlowLayoutPanel { AutoSize = true, Margin = new Padding(0, 12, 0, 0) };
        _ok.Enabled = false;
        _ok.Width = 170;
        _ok.DialogResult = DialogResult.OK;
        var cancel = Theme.SecondaryButton("Cancel");
        cancel.DialogResult = DialogResult.Cancel;
        buttons.Controls.Add(_ok);
        buttons.Controls.Add(cancel);
        layout.Controls.Add(buttons);
        Controls.Add(layout);
        AcceptButton = _ok;
        CancelButton = cancel;
        _typed.TextChanged += (_, _) => _ok.Enabled = _typed.Text.Trim() == "ERASE";
    }
}
