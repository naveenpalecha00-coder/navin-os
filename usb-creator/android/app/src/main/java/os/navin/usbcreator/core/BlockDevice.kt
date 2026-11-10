package os.navin.usbcreator.core

import java.io.IOException

/** A raw block device (the USB drive). LBAs are in units of [blockSize]. */
interface BlockDevice {
    val blockSize: Int
    val blockCount: Long
    val sizeBytes: Long get() = blockSize.toLong() * blockCount

    /** Reads [count] blocks starting at [lba] into [buf] at [offset]. */
    @Throws(IOException::class)
    fun read(lba: Long, buf: ByteArray, offset: Int, count: Int)

    /** Writes [count] blocks from [buf] at [offset] starting at [lba]. */
    @Throws(IOException::class)
    fun write(lba: Long, buf: ByteArray, offset: Int, count: Int)

    /** Asks the drive to commit its write cache. */
    @Throws(IOException::class)
    fun flush() {}
}
