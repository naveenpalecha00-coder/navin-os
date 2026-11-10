namespace NavinUsbCreator;

/// <summary>NAVIN USB Creator palette: white, light gray and pale blue.</summary>
internal static class Theme
{
    public static readonly Color Window = Color.White;
    public static readonly Color Panel = Color.FromArgb(244, 246, 249);
    public static readonly Color PaleBlue = Color.FromArgb(232, 241, 255);
    public static readonly Color Border = Color.FromArgb(221, 227, 236);
    public static readonly Color Primary = Color.FromArgb(29, 111, 224);
    public static readonly Color PrimaryDark = Color.FromArgb(21, 88, 184);
    public static readonly Color Text = Color.FromArgb(31, 41, 55);
    public static readonly Color Muted = Color.FromArgb(100, 116, 139);
    public static readonly Color Success = Color.FromArgb(22, 163, 74);
    public static readonly Color Danger = Color.FromArgb(220, 38, 38);

    public static readonly Font Body = new("Segoe UI", 9.5f);
    public static readonly Font Small = new("Segoe UI", 8.5f);
    public static readonly Font Section = new("Segoe UI Semibold", 11f);
    public static readonly Font Title = new("Segoe UI Semibold", 15f);
    public static readonly Font Mono = new("Consolas", 9f);

    public static Button PrimaryButton(string text)
    {
        var b = new Button { Text = text, BackColor = Primary, ForeColor = Color.White, FlatStyle = FlatStyle.Flat, Font = Section, Height = 40, Cursor = Cursors.Hand };
        b.FlatAppearance.BorderSize = 0;
        b.FlatAppearance.MouseOverBackColor = PrimaryDark;
        return b;
    }

    public static Button SecondaryButton(string text)
    {
        var b = new Button { Text = text, BackColor = PaleBlue, ForeColor = Primary, FlatStyle = FlatStyle.Flat, Font = Body, Height = 32, Cursor = Cursors.Hand, AutoSize = true, Padding = new Padding(8, 0, 8, 0) };
        b.FlatAppearance.BorderColor = Border;
        return b;
    }
}
