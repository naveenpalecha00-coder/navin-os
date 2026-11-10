package os.navin.usbcreator.usb

import java.nio.ByteBuffer
import java.nio.ByteOrder

/** SCSI command blocks and USB Bulk-Only Transport wrappers (pure, testable). */
object Scsi {
    const val CBW_SIGNATURE = 0x43425355
    const val CSW_SIGNATURE = 0x53425355

    fun cbw(tag: Int, dataLength: Int, dataIn: Boolean, cdb: ByteArray): ByteArray {
        require(cdb.size in 1..16)
        val b = ByteBuffer.allocate(31).order(ByteOrder.LITTLE_ENDIAN)
        b.putInt(CBW_SIGNATURE).putInt(tag).putInt(dataLength)
        b.put(if (dataIn) 0x80.toByte() else 0)
        b.put(0.toByte()) // LUN 0
        b.put(cdb.size.toByte())
        b.put(cdb)
        return b.array()
    }

    data class Csw(val tag: Int, val residue: Int, val status: Int)

    fun parseCsw(b: ByteArray): Csw? {
        if (b.size < 13) return null
        val bb = ByteBuffer.wrap(b).order(ByteOrder.LITTLE_ENDIAN)
        if (bb.getInt(0) != CSW_SIGNATURE) return null
        return Csw(bb.getInt(4), bb.getInt(8), b[12].toInt() and 0xFF)
    }

    fun inquiry() = byteArrayOf(0x12, 0, 0, 0, 36, 0)
    fun testUnitReady() = ByteArray(6)
    fun requestSense() = byteArrayOf(0x03, 0, 0, 0, 18, 0)
    fun readCapacity10() = ByteArray(10).also { it[0] = 0x25 }
    fun readCapacity16() = ByteArray(16).also { it[0] = 0x9E.toByte(); it[1] = 0x10; it[13] = 32 }
    fun synchronizeCache() = ByteArray(10).also { it[0] = 0x35 }
    /** MODE SENSE(6), all pages, 192 bytes — the same request Linux sends to read the write-protect bit. */
    fun modeSense6() = byteArrayOf(0x1A, 0, 0x3F, 0, 0xC0.toByte(), 0)

    /** Write-protect (WP) bit in the MODE SENSE(6) header. */
    fun isWriteProtected(header: ByteArray, length: Int = header.size) = length >= 4 && header.size >= 4 && header[2].toInt() and 0x80 != 0

    /** How many blocks fit in one READ/WRITE command of at most [maxBytes]. */
    fun blocksPerCommand(blockSize: Int, maxBytes: Int) = maxOf(1, maxBytes / blockSize)

    data class Sense(val key: Int, val asc: Int, val ascq: Int)

    /** Fixed-format sense data (response code 0x70/0x71), or null. */
    fun parseSense(b: ByteArray): Sense? {
        if (b.size < 14) return null
        val code = b[0].toInt() and 0x7F
        if (code != 0x70 && code != 0x71) return null
        return Sense(b[2].toInt() and 0x0F, b[12].toInt() and 0xFF, b[13].toInt() and 0xFF)
    }

    /**
     * Conditions a drive clears by itself: UNIT ATTENTION (reset / medium changed, very common
     * right after Android hands the drive to the app), "becoming ready", ABORTED COMMAND, or no sense.
     */
    fun isRetryable(s: Sense?): Boolean = s == null || s.key == 0x0 || s.key == 0x6 || s.key == 0xB ||
        (s.key == 0x2 && s.asc == 0x04 && s.ascq in setOf(0x00, 0x01, 0x07))

    fun isWriteProtectSense(s: Sense?) = s != null && (s.key == 0x7 || (s.asc == 0x27))

    /** Plain-language message for a command the drive refused. */
    fun describe(s: Sense?, opcode: Int): String {
        val code = if (s == null) "" else " (code %X/%02X/%02X)".format(s.key, s.asc, s.ascq)
        return when {
            isWriteProtectSense(s) -> "The drive is write-protected$code. If it is an SD card or adapter with a lock switch, slide it to unlocked, reconnect and try again. Otherwise the drive's memory may be locked or worn out — use another drive."
            s != null && s.key == 0x2 && s.asc == 0x3A -> "No card or medium in the reader$code. Insert the card, reconnect and try again."
            s != null && (s.key == 0x3 || s.key == 0x4) -> "The drive reported a hardware or memory error$code. It may be failing or counterfeit — try another drive."
            s != null && s.key == 0x5 && s.asc == 0x21 -> "The drive refused an address outside its real size$code. It may be a fake-capacity drive — try another drive."
            else -> "The drive refused a command (SCSI 0x%02X)$code. Unplug the drive, plug it back in and try again; if it repeats, try another drive or OTG adapter.".format(opcode)
        }
    }

    /** READ/WRITE (10) for LBAs under 2^32, (16) above. */
    fun rw(write: Boolean, lba: Long, blocks: Int): ByteArray {
        if (lba + blocks <= 0xFFFFFFFFL && blocks <= 0xFFFF) {
            val c = ByteBuffer.allocate(10).order(ByteOrder.BIG_ENDIAN)
            c.put((if (write) 0x2A else 0x28).toByte()).put(0.toByte()).putInt(lba.toInt()).put(0.toByte()).putShort(blocks.toShort()).put(0.toByte())
            return c.array()
        }
        val c = ByteBuffer.allocate(16).order(ByteOrder.BIG_ENDIAN)
        c.put(if (write) 0x8A.toByte() else 0x88.toByte()).put(0.toByte()).putLong(lba).putInt(blocks).put(0.toByte()).put(0.toByte())
        return c.array()
    }
}
