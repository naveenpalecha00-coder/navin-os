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
