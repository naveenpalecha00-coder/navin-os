package os.navin.usbcreator.core

import kotlin.math.max
import kotlin.math.min

/** Progress percentage, smoothed speed and time remaining. */
class TransferStats(total: Long) {
    private val total = max(1L, total)
    private var lastBytes = 0L
    private var lastSeconds = 0.0
    var done = 0L; private set
    var bytesPerSecond = 0.0; private set
    val percent get() = min(100.0, done * 100.0 / total)
    val remainingSeconds: Long? get() = if (bytesPerSecond > 1) ((total - done) / bytesPerSecond).toLong() else null

    fun update(doneBytes: Long, elapsedSeconds: Double) {
        done = doneBytes.coerceIn(0, total)
        val dt = elapsedSeconds - lastSeconds
        if (dt < 0.25) return
        val instant = (done - lastBytes) / dt
        bytesPerSecond = if (bytesPerSecond <= 0) instant else bytesPerSecond * 0.7 + instant * 0.3
        lastBytes = done
        lastSeconds = elapsedSeconds
    }

    companion object {
        fun formatEta(s: Long?): String = when {
            s == null -> "calculating…"
            s >= 3600 -> "%d:%02d:%02d".format(s / 3600, s % 3600 / 60, s % 60)
            else -> "%d:%02d".format(s / 60, s % 60)
        }

        fun formatBytes(b: Long): String = when {
            b >= 1L shl 30 -> "%.1f GB".format(b / (1L shl 30).toDouble())
            b >= 1L shl 20 -> "%.1f MB".format(b / (1L shl 20).toDouble())
            b >= 1024 -> "${b / 1024} KB"
            else -> "$b B"
        }
    }
}
