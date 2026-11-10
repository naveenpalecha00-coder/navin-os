package os.navin.usbcreator.ui

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

/** White, light gray and pale blue — the NAVIN USB Creator palette. */
object Palette {
    val Primary = Color(0xFF1D6FE0)
    val PaleBlue = Color(0xFFE8F1FF)
    val Panel = Color(0xFFF4F6F9)
    val Border = Color(0xFFDDE3EC)
    val Text = Color(0xFF1F2937)
    val Muted = Color(0xFF64748B)
    val Success = Color(0xFF16A34A)
    val Danger = Color(0xFFDC2626)
}

@Composable
fun NavinTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = lightColorScheme(
            primary = Palette.Primary,
            onPrimary = Color.White,
            primaryContainer = Palette.PaleBlue,
            onPrimaryContainer = Palette.Primary,
            background = Color.White,
            onBackground = Palette.Text,
            surface = Color.White,
            onSurface = Palette.Text,
            surfaceVariant = Palette.Panel,
            onSurfaceVariant = Palette.Muted,
            outline = Palette.Border,
            error = Palette.Danger,
        ),
        content = content,
    )
}
