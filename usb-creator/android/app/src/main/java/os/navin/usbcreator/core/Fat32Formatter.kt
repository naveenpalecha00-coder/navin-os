package os.navin.usbcreator.core

import java.io.IOException
import kotlin.random.Random

/** Where everything goes on a freshly formatted FAT32 drive (one MBR partition at 1 MiB). */
data class Fat32Layout(
    val partitionStart: Long,
    val partitionSectors: Long,
    val sectorsPerCluster: Int,
    val reservedSectors: Int,
    val fatSectors: Long,
    val clusterCount: Long,
) {
    val fatStart get() = partitionStart + reservedSectors
    val dataStart get() = fatStart + 2 * fatSectors
    val clusterBytes get() = sectorsPerCluster * 512
}

/**
 * A real FAT32 formatter (Microsoft FAT specification) that writes an MBR partition table
 * and an empty FAT32 file system straight to the USB drive.
 */
object Fat32Formatter {
    const val SECTOR = 512
    const val START = 2048L
    const val RESERVED = 32
    const val MIN_CLUSTERS = 65525L
    private const val MAX_MBR_SECTORS = 0xFFFFFFFFL

    /** Cluster size (in sectors) Windows uses for each FAT32 volume size. */
    fun defaultSectorsPerCluster(partitionSectors: Long): Int {
        val bytes = partitionSectors * SECTOR
        return when {
            bytes <= 260L * 1024 * 1024 -> 1
            bytes <= 8L shl 30 -> 8
            bytes <= 16L shl 30 -> 16
            bytes <= 32L shl 30 -> 32
            else -> 64
        }
    }

    fun layout(totalSectors: Long, sectorsPerCluster: Int = 0): Fat32Layout {
        val partSectors = minOf(totalSectors - START, MAX_MBR_SECTORS)
        if (partSectors * SECTOR < 64L * 1024 * 1024) throw IOException("The drive is too small for FAT32 (minimum 64 MB).")
        val spc = if (sectorsPerCluster > 0) sectorsPerCluster else defaultSectorsPerCluster(partSectors)
        require(spc in listOf(1, 2, 4, 8, 16, 32, 64, 128)) { "Invalid cluster size" }
        // FAT size formula from the Microsoft FAT32 specification (RootDirSectors = 0).
        val tmp1 = partSectors - RESERVED
        val tmp2 = (256L * spc + 2) / 2
        val fatSz = (tmp1 + (tmp2 - 1)) / tmp2
        val clusters = (partSectors - RESERVED - 2 * fatSz) / spc
        if (clusters < MIN_CLUSTERS) throw IOException("This cluster size is too large for a FAT32 drive this small. Choose a smaller cluster size.")
        if (clusters > 0x0FFFFFF5L) throw IOException("This cluster size is too small for a drive this large. Choose a larger cluster size.")
        return Fat32Layout(START, partSectors, spc, RESERVED, fatSz, clusters)
    }

    fun sanitizeLabel(label: String): String {
        val bad = "\"*+,./:;<=>?[\\]|"
        val clean = label.uppercase().filter { it.code in 32..126 && it !in bad }.trim().take(11)
        return clean.ifEmpty { "NAVIN" }
    }

    fun format(dev: BlockDevice, label: String, sectorsPerCluster: Int = 0, onProgress: (Double) -> Unit = {}, isCancelled: () -> Boolean = { false }): Fat32Layout {
        if (dev.blockSize != SECTOR) throw IOException("This drive uses ${dev.blockSize}-byte sectors. Formatting is only supported for 512-byte sector drives.")
        val l = layout(dev.blockCount, sectorsPerCluster)
        val name = sanitizeLabel(label).padEnd(11, ' ')
        val zeros = ByteArray(1024 * 1024)
        val zeroBlocks = zeros.size / SECTOR

        fun zero(from: Long, count: Long, progressFrom: Double, progressTo: Double) {
            var done = 0L
            while (done < count) {
                if (isCancelled()) throw InterruptedException()
                val n = minOf(zeroBlocks.toLong(), count - done).toInt()
                dev.write(from + done, zeros, 0, n)
                done += n
                onProgress(progressFrom + (progressTo - progressFrom) * done / count)
            }
        }

        // 1. Wipe old partition tables (start of disk and backup GPT at the end) and the FAT32 area.
        zero(0, START + l.reservedSectors, 0.0, 5.0)
        zero(dev.blockCount - 34, 34, 5.0, 6.0)
        zero(l.fatStart, 2 * l.fatSectors, 6.0, 95.0)
        zero(l.dataStart, l.sectorsPerCluster.toLong(), 95.0, 96.0)

        // 2. FAT tables: media descriptor, reserved entry and end-of-chain for the root directory.
        val fat = ByteArray(SECTOR)
        le32(fat, 0, 0x0FFFFFF8); le32(fat, 4, 0x0FFFFFFF); le32(fat, 8, 0x0FFFFFFF)
        dev.write(l.fatStart, fat, 0, 1)
        dev.write(l.fatStart + l.fatSectors, fat, 0, 1)

        // 3. Root directory with the volume label.
        val root = ByteArray(SECTOR)
        name.forEachIndexed { i, c -> root[i] = c.code.toByte() }
        root[11] = 0x08
        dev.write(l.dataStart, root, 0, 1)

        // 4. Boot sector + FSInfo, and their backups at sectors 6 and 7.
        val vbr = bootSector(l, name)
        val info = fsInfo(l)
        dev.write(l.partitionStart, vbr, 0, 1)
        dev.write(l.partitionStart + 1, info, 0, 1)
        dev.write(l.partitionStart + 6, vbr, 0, 1)
        dev.write(l.partitionStart + 7, info, 0, 1)

        // 5. MBR last, so the drive only looks formatted once everything else is in place.
        dev.write(0, mbr(l), 0, 1)
        dev.flush()
        onProgress(100.0)
        return l
    }

    fun mbr(l: Fat32Layout): ByteArray {
        val b = ByteArray(SECTOR)
        le32(b, 440, Random.nextInt().toLong() and 0xFFFFFFFFL)
        val e = 446
        b[e] = 0x80.toByte()
        b[e + 1] = 0xFE.toByte(); b[e + 2] = 0xFF.toByte(); b[e + 3] = 0xFF.toByte()
        b[e + 4] = 0x0C // FAT32 (LBA)
        b[e + 5] = 0xFE.toByte(); b[e + 6] = 0xFF.toByte(); b[e + 7] = 0xFF.toByte()
        le32(b, e + 8, l.partitionStart)
        le32(b, e + 12, l.partitionSectors)
        b[510] = 0x55; b[511] = 0xAA.toByte()
        return b
    }

    fun bootSector(l: Fat32Layout, label11: String): ByteArray {
        val b = ByteArray(SECTOR)
        b[0] = 0xEB.toByte(); b[1] = 0x58; b[2] = 0x90.toByte()
        "MSWIN4.1".forEachIndexed { i, c -> b[3 + i] = c.code.toByte() }
        le16(b, 11, SECTOR)
        b[13] = l.sectorsPerCluster.toByte()
        le16(b, 14, l.reservedSectors)
        b[16] = 2
        b[21] = 0xF8.toByte()
        le16(b, 24, 63); le16(b, 26, 255)
        le32(b, 28, l.partitionStart)
        le32(b, 32, l.partitionSectors)
        le32(b, 36, l.fatSectors)
        le32(b, 44, 2) // root directory cluster
        le16(b, 48, 1) // FSInfo sector
        le16(b, 50, 6) // backup boot sector
        b[64] = 0x80.toByte()
        b[66] = 0x29
        le32(b, 67, Random.nextInt().toLong() and 0xFFFFFFFFL)
        label11.forEachIndexed { i, c -> b[71 + i] = c.code.toByte() }
        "FAT32   ".forEachIndexed { i, c -> b[82 + i] = c.code.toByte() }
        // Boot code: tell the BIOS this is not a system disk (INT 18h).
        b[90] = 0xCD.toByte(); b[91] = 0x18
        b[510] = 0x55; b[511] = 0xAA.toByte()
        return b
    }

    fun fsInfo(l: Fat32Layout): ByteArray {
        val b = ByteArray(SECTOR)
        le32(b, 0, 0x41615252)
        le32(b, 484, 0x61417272)
        le32(b, 488, l.clusterCount - 1)
        le32(b, 492, 3)
        le32(b, 508, 0xAA550000L)
        return b
    }

    private fun le16(b: ByteArray, off: Int, v: Int) {
        b[off] = v.toByte(); b[off + 1] = (v shr 8).toByte()
    }

    fun le32(b: ByteArray, off: Int, v: Long) {
        for (i in 0 until 4) b[off + i] = (v shr (8 * i)).toByte()
    }
}
