package os.navin.usbcreator.core

import java.io.IOException
import java.io.InputStream
import java.security.MessageDigest

data class Progress(val phase: String, val percent: Double, val bytesPerSecond: Double, val remainingSeconds: Long?, val done: Long, val total: Long)

data class WriteResult(val imageSha256: String, val verified: Boolean, val seconds: Long)

/**
 * Copies a disk image byte-for-byte onto the USB drive. The first MiB (partition tables)
 * is written last, so an interrupted write never looks like a valid drive.
 */
class ImageWriter(private val dev: BlockDevice, private val clock: () -> Double = { System.nanoTime() / 1e9 }) {
    private val chunk = 1024 * 1024
    private val head = 1024 * 1024

    fun write(image: InputStream, length: Long, verify: Boolean, onProgress: (Progress) -> Unit, isCancelled: () -> Boolean): WriteResult {
        val bs = dev.blockSize
        if (length <= 0) throw IOException("The image is empty.")
        if (length > dev.sizeBytes) throw IOException("The image (${TransferStats.formatBytes(length)}) is larger than the drive (${TransferStats.formatBytes(dev.sizeBytes)}).")
        if (chunk % bs != 0) throw IOException("Unsupported block size ${bs}.")
        val start = clock()
        val padded = roundUp(length, bs)
        val sha = MessageDigest.getInstance("SHA-256")
        val stats = TransferStats(padded)

        val headBuf = ByteArray(head)
        val headLen = fill(image, headBuf)
        sha.update(headBuf, 0, headLen)
        val headBlocks = (roundUp(headLen.toLong(), bs) / bs).toInt()

        val buf = ByteArray(chunk)
        var offset = head.toLong()
        while (offset < padded) {
            if (isCancelled()) throw InterruptedException()
            val n = fill(image, buf)
            if (n == 0) break
            sha.update(buf, 0, n)
            if (n < buf.size) buf.fill(0, n, buf.size)
            val blocks = (roundUp(n.toLong(), bs) / bs).toInt()
            dev.write(offset / bs, buf, 0, blocks)
            offset += blocks.toLong() * bs
            stats.update(offset - head, clock() - start)
            onProgress(Progress("Writing", stats.percent, stats.bytesPerSecond, stats.remainingSeconds, stats.done, padded))
        }
        if (offset - head < length - headLen) throw IOException("The image ended early — it may be incomplete. Download it again.")
        if (isCancelled()) throw InterruptedException()
        if (headLen < headBuf.size) headBuf.fill(0, headLen, headBuf.size)
        dev.write(0, headBuf, 0, headBlocks)
        dev.flush()
        onProgress(Progress("Writing", 100.0, stats.bytesPerSecond, 0, padded, padded))
        val imageHash = hex(sha.digest())

        var verified = false
        if (verify) {
            val vStart = clock()
            val v = TransferStats(length)
            var done = 0L
            while (done < length) {
                if (isCancelled()) throw InterruptedException()
                val want = minOf(chunk.toLong(), roundUp(length - done, bs)).toInt()
                dev.read(done / bs, buf, 0, want / bs)
                val useful = minOf(want.toLong(), length - done).toInt()
                sha.update(buf, 0, useful)
                done += useful
                v.update(done, clock() - vStart)
                onProgress(Progress("Verifying", v.percent, v.bytesPerSecond, v.remainingSeconds, done, length))
            }
            if (hex(sha.digest()) != imageHash) throw IOException("Verification failed: the data read back does not match the image. The drive may be faulty or counterfeit — try another drive.")
            verified = true
        }
        return WriteResult(imageHash, verified, (clock() - start).toLong())
    }

    private fun fill(s: InputStream, b: ByteArray): Int {
        var total = 0
        while (total < b.size) {
            val n = s.read(b, total, b.size - total)
            if (n < 0) break
            total += n
        }
        return total
    }

    companion object {
        fun roundUp(v: Long, m: Int) = (v + m - 1) / m * m
        fun hex(b: ByteArray) = b.joinToString("") { "%02x".format(it) }
    }
}
