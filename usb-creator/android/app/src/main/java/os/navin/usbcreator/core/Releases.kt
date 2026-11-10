package os.navin.usbcreator.core

/** Pure helpers for reading GitHub release information. */
object Releases {
    const val REPO = "naveenpalecha00-coder/navin-os"
    const val CREATOR_PREFIX = "usb-creator-v"
    const val OS_PREFIX = "v1.0-build."
    private val SHA = Regex("\\b[a-fA-F0-9]{64}\\b")

    /** "usb-creator-v1.2.3" → [1, 2, 3]; null for other tags. */
    fun creatorVersion(tag: String): List<Int>? {
        if (!tag.startsWith(CREATOR_PREFIX)) return null
        val p = tag.removePrefix(CREATOR_PREFIX).split(".")
        if (p.isEmpty() || p.size > 3) return null
        val nums = p.map { it.toIntOrNull() ?: return null }
        return nums + List(3 - nums.size) { 0 }
    }

    fun parseVersion(v: String): List<Int> = (v.split(".").map { it.toIntOrNull() ?: 0 } + listOf(0, 0, 0)).take(3)

    fun isNewer(latest: List<Int>, current: List<Int>): Boolean {
        for (i in 0 until 3) if (latest[i] != current[i]) return latest[i] > current[i]
        return false
    }

    fun sha256s(body: String?): List<String> = body?.let { b -> SHA.findAll(b).map { it.value.lowercase() }.toList() } ?: emptyList()
}
