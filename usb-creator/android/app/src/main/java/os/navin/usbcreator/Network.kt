package os.navin.usbcreator

import org.json.JSONArray
import os.navin.usbcreator.core.Releases
import java.net.HttpURLConnection
import java.net.URL

data class UpdateInfo(val version: String, val url: String, val newer: Boolean)

/** Reads public GitHub release data only. Sends no personal or device data. */
object Network {
    private fun releases(): JSONArray {
        val c = URL("https://api.github.com/repos/${Releases.REPO}/releases?per_page=50").openConnection() as HttpURLConnection
        c.connectTimeout = 10_000
        c.readTimeout = 15_000
        c.setRequestProperty("Accept", "application/vnd.github+json")
        c.setRequestProperty("User-Agent", "NavinUsbCreator-Android/${BuildConfig.VERSION_NAME}")
        try {
            if (c.responseCode != 200) throw java.io.IOException("GitHub returned ${c.responseCode}")
            return JSONArray(c.inputStream.bufferedReader().readText())
        } finally {
            c.disconnect()
        }
    }

    fun checkUpdate(): UpdateInfo? {
        val current = Releases.parseVersion(BuildConfig.VERSION_NAME)
        var best: Pair<List<Int>, String>? = null
        val arr = releases()
        for (i in 0 until arr.length()) {
            val r = arr.getJSONObject(i)
            if (r.optBoolean("draft")) continue
            val v = Releases.creatorVersion(r.optString("tag_name")) ?: continue
            if (best == null || Releases.isNewer(v, best.first)) best = v to r.optString("html_url")
        }
        return best?.let { UpdateInfo(it.first.joinToString("."), it.second, Releases.isNewer(it.first, current)) }
    }

    /** Official NAVIN OS ISO checksum → release tag. */
    fun officialIsoHashes(): Map<String, String> {
        val map = HashMap<String, String>()
        val arr = releases()
        for (i in 0 until arr.length()) {
            val r = arr.getJSONObject(i)
            val tag = r.optString("tag_name")
            if (!tag.startsWith(Releases.OS_PREFIX)) continue
            Releases.sha256s(r.optString("body")).forEach { map.putIfAbsent(it, tag) }
        }
        return map
    }
}
