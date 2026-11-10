package os.navin.usbcreator

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import os.navin.usbcreator.core.BlockDevice
import os.navin.usbcreator.core.Fat32Formatter
import os.navin.usbcreator.core.ImageInspector
import os.navin.usbcreator.core.ImageWriter
import os.navin.usbcreator.core.Releases
import os.navin.usbcreator.usb.Scsi
import java.io.ByteArrayInputStream
import java.io.IOException
import java.nio.ByteBuffer
import java.nio.ByteOrder

/** Sparse in-memory drive: only written blocks use memory. */
class FakeDrive(override val blockCount: Long, override val blockSize: Int = 512) : BlockDevice {
    val blocks = HashMap<Long, ByteArray>()
    override fun read(lba: Long, buf: ByteArray, offset: Int, count: Int) {
        for (i in 0 until count) (blocks[lba + i] ?: ByteArray(blockSize)).copyInto(buf, offset + i * blockSize)
    }
    override fun write(lba: Long, buf: ByteArray, offset: Int, count: Int) {
        if (lba + count > blockCount) throw IOException("out of range")
        for (i in 0 until count) blocks[lba + i] = buf.copyOfRange(offset + i * blockSize, offset + (i + 1) * blockSize)
    }
    fun block(lba: Long) = blocks[lba] ?: ByteArray(blockSize)
}

private fun le32(b: ByteArray, off: Int) = ByteBuffer.wrap(b).order(ByteOrder.LITTLE_ENDIAN).getInt(off).toLong() and 0xFFFFFFFFL
private fun le16(b: ByteArray, off: Int) = ByteBuffer.wrap(b).order(ByteOrder.LITTLE_ENDIAN).getShort(off).toInt() and 0xFFFF

class Fat32Test {
    private val eightGb = 8L * 1024 * 1024 * 1024 / 512

    @Test fun eightGbDriveUses4kClusters() = assertEquals(8, Fat32Formatter.layout(eightGb).sectorsPerCluster)
    @Test fun largeDriveUses32kClusters() = assertEquals(64, Fat32Formatter.layout(64L * 1024 * 1024 * 1024 / 512).sectorsPerCluster)
    @Test(expected = IOException::class) fun tinyDriveIsRejected() { Fat32Formatter.layout(20_000) }
    @Test(expected = IOException::class) fun clusterTooLargeForSmallDriveIsRejected() { Fat32Formatter.layout(300L * 1024 * 1024 / 512, 128) }

    @Test fun labelIsFat32Safe() = assertEquals("NAVIN OS 10", Fat32Formatter.sanitizeLabel("navin os 10 build"))

    @Test fun formatWritesValidMbrAndFat32() {
        val d = FakeDrive(eightGb)
        val l = Fat32Formatter.format(d, "navin")
        val mbr = d.block(0)
        assertEquals(0x55.toByte(), mbr[510]); assertEquals(0xAA.toByte(), mbr[511])
        assertEquals(0x0C.toByte(), mbr[446 + 4])
        assertEquals(2048L, le32(mbr, 446 + 8))
        val vbr = d.block(2048)
        assertEquals(512, le16(vbr, 11))
        assertEquals(8, vbr[13].toInt())
        assertEquals(l.fatSectors, le32(vbr, 36))
        assertEquals("FAT32   ", String(vbr, 82, 8, Charsets.US_ASCII))
        assertEquals("NAVIN      ", String(vbr, 71, 11, Charsets.US_ASCII))
        assertArrayEquals(vbr, d.block(2048 + 6))
        val info = d.block(2049)
        assertEquals(0x41615252L, le32(info, 0)); assertEquals(0x61417272L, le32(info, 484))
        val fat = d.block(l.fatStart)
        assertEquals(0x0FFFFFF8L, le32(fat, 0)); assertEquals(0x0FFFFFFFL, le32(fat, 8))
        assertArrayEquals(fat, d.block(l.fatStart + l.fatSectors))
        assertTrue(l.clusterCount >= Fat32Formatter.MIN_CLUSTERS)
        // FATs must be large enough to map every cluster (4 bytes per entry).
        assertTrue(l.fatSectors * 512 / 4 >= l.clusterCount + 2)
    }

    @Test(expected = IOException::class) fun refuses4kSectorDrives() { Fat32Formatter.format(FakeDrive(2_000_000, 4096), "X") }
}

class ImageWriterTest {
    private fun hybridImage(size: Int): ByteArray {
        val b = ByteArray(size) { (it * 31 + 7).toByte() }
        b[510] = 0x55; b[511] = 0xAA.toByte()
        return b
    }

    @Test fun writesExactBytesAndVerifies() {
        val img = hybridImage(3 * 1024 * 1024 + 700) // not a multiple of the sector size
        val d = FakeDrive(16_384)
        val r = ImageWriter(d).write(ByteArrayInputStream(img), img.size.toLong(), true, {}, { false })
        assertTrue(r.verified)
        val back = ByteArray(img.size + 512)
        d.read(0, back, 0, back.size / 512)
        assertArrayEquals(img, back.copyOf(img.size))
        assertEquals(64, r.imageSha256.length)
    }

    @Test(expected = IOException::class) fun refusesImageLargerThanDrive() {
        val img = hybridImage(2 * 1024 * 1024)
        ImageWriter(FakeDrive(1024)).write(ByteArrayInputStream(img), img.size.toLong(), false, {}, { false })
    }

    @Test fun cancelLeavesPartitionTableUnwritten() {
        val img = hybridImage(4 * 1024 * 1024)
        val d = FakeDrive(16_384)
        var calls = 0
        try {
            ImageWriter(d).write(ByteArrayInputStream(img), img.size.toLong(), false, {}, { ++calls > 1 })
        } catch (_: InterruptedException) {}
        assertNull(d.blocks[0L]) // the first MiB is written last, so a cancelled drive never looks bootable
    }
}

class InspectorTest {
    @Test fun detectsHybridIso() {
        val b = ByteArray(ImageInspector.HEAD_BYTES)
        b[0] = 0x33; b[510] = 0x55; b[511] = 0xAA.toByte(); b[446 + 4] = 0xEF.toByte()
        "CD001".forEachIndexed { i, c -> b[0x8001 + i] = c.code.toByte() }
        val i = ImageInspector.inspect(b, 100)
        assertTrue(i.isHybridIso)
        assertEquals("UEFI + Legacy BIOS", i.targetSystem)
    }

    @Test fun plainIsoIsNotRawWritable() {
        val b = ByteArray(ImageInspector.HEAD_BYTES)
        "CD001".forEachIndexed { i, c -> b[0x8001 + i] = c.code.toByte() }
        assertFalse(ImageInspector.inspect(b, 100).supportsRawWrite)
    }
}

class ScsiTest {
    @Test fun cbwHasSignatureAndDirection() {
        val c = Scsi.cbw(7, 512, true, Scsi.rw(false, 100, 1))
        assertEquals(31, c.size)
        assertEquals(0x43425355L, le32(c, 0))
        assertEquals(7L, le32(c, 4))
        assertEquals(0x80.toByte(), c[12])
        assertEquals(0x28.toByte(), c[15])
    }

    @Test fun largeLbaUses16ByteCommand() = assertEquals(0x8A.toByte(), Scsi.rw(true, 0x1_0000_0000L, 8)[0])
    @Test fun write10EncodesLbaBigEndian() {
        val c = Scsi.rw(true, 0x01020304, 2)
        assertEquals(0x2A.toByte(), c[0]); assertEquals(0x01.toByte(), c[2]); assertEquals(0x04.toByte(), c[5]); assertEquals(2.toByte(), c[8])
    }
}

class ReleasesTest {
    @Test fun parsesCreatorTag() = assertEquals(listOf(1, 2, 0), Releases.creatorVersion("usb-creator-v1.2"))
    @Test fun ignoresOsTag() = assertNull(Releases.creatorVersion("v1.0-build.10"))
    @Test fun detectsNewer() = assertTrue(Releases.isNewer(listOf(1, 0, 1), listOf(1, 0, 0)))
    @Test fun sameIsNotNewer() = assertFalse(Releases.isNewer(listOf(1, 0, 0), listOf(1, 0, 0)))
}
