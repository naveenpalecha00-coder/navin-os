package os.navin.usbcreator.usb

import android.hardware.usb.UsbConstants
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbDeviceConnection
import android.hardware.usb.UsbEndpoint
import android.hardware.usb.UsbInterface
import android.hardware.usb.UsbManager
import os.navin.usbcreator.core.BlockDevice
import java.io.Closeable
import java.io.IOException
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * Talks to a USB flash drive directly with SCSI commands over USB Bulk-Only Transport,
 * using only Android's public USB Host API (no root).
 */
class UsbMassStorage private constructor(
    private val connection: UsbDeviceConnection,
    private val iface: UsbInterface,
    private val inEp: UsbEndpoint,
    private val outEp: UsbEndpoint,
) : BlockDevice, Closeable {

    override var blockSize = 512; private set
    override var blockCount = 0L; private set
    var vendor = ""; private set
    var product = ""; private set
    var removable = false; private set
    /** The drive reports its write-protect switch/lock as on. */
    var writeProtected = false; private set

    private var tag = 1
    private val csw = ByteArray(13)
    // Android before 9 limits a single bulk transfer to 16 KiB.
    private val maxTransfer = 16 * 1024
    private val scratch = ByteArray(16 * 1024)
    // Bytes per READ/WRITE command. 120 KiB matches Linux's default for USB drives; shrinks automatically for drives that stall.
    private var rwBytes = DEFAULT_RW_BYTES

    companion object {
        private const val TIMEOUT = 5_000
        private const val IO_TIMEOUT = 30_000
        private const val FLUSH_TIMEOUT = 60_000
        const val DEFAULT_RW_BYTES = 120 * 1024
        const val MIN_RW_BYTES = 16 * 1024

        /** The mass-storage (SCSI, bulk-only) interface of a device, or null if it has none. */
        fun findInterface(device: UsbDevice): UsbInterface? =
            (0 until device.interfaceCount).map { device.getInterface(it) }.firstOrNull {
                it.interfaceClass == UsbConstants.USB_CLASS_MASS_STORAGE && it.interfaceSubclass == 6 && it.interfaceProtocol == 0x50
            }

        fun open(manager: UsbManager, device: UsbDevice): UsbMassStorage {
            val iface = findInterface(device) ?: throw IOException("This USB device is not a supported storage drive.")
            var inEp: UsbEndpoint? = null
            var outEp: UsbEndpoint? = null
            for (i in 0 until iface.endpointCount) {
                val e = iface.getEndpoint(i)
                if (e.type != UsbConstants.USB_ENDPOINT_XFER_BULK) continue
                if (e.direction == UsbConstants.USB_DIR_IN) inEp = e else outEp = e
            }
            if (inEp == null || outEp == null) throw IOException("The drive does not expose bulk endpoints.")
            val conn = manager.openDevice(device) ?: throw IOException("Android did not allow access to the drive. Unplug it, plug it back in and allow access.")
            // force = true detaches Android's own storage driver so nothing else uses the drive while we write.
            if (!conn.claimInterface(iface, true)) {
                conn.close()
                throw IOException("Another app or the system is using the drive. Close other file apps and try again.")
            }
            val dev = UsbMassStorage(conn, iface, inEp, outEp)
            try {
                dev.init()
            } catch (e: IOException) {
                dev.close()
                throw e
            }
            return dev
        }
    }

    private fun init() {
        val inq = ByteArray(36)
        // The drive may still be settling after Android detached its own driver: give it a few tries.
        var inquiryError: IOException? = null
        for (attempt in 0 until 3) {
            try { command(Scsi.inquiry(), inq, 0, 36, dataIn = true); inquiryError = null; break }
            catch (e: IOException) { inquiryError = e; Thread.sleep(400) }
        }
        inquiryError?.let { throw it }
        if (inq[0].toInt() and 0x1F != 0) throw IOException("This USB device is not a disk (SCSI type ${inq[0].toInt() and 0x1F}).")
        removable = inq[1].toInt() and 0x80 != 0
        vendor = String(inq, 8, 8, Charsets.US_ASCII).trim()
        product = String(inq, 16, 16, Charsets.US_ASCII).trim()

        var ready = false
        for (attempt in 0 until 10) {
            if (tryCommand(Scsi.testUnitReady(), null, 0, 0, false)) { ready = true; break }
            Thread.sleep(300)
        }
        if (!ready) throw IOException("The drive is not ready. Check that a card is inserted or try another port/adapter.")

        val cap = ByteArray(8)
        command(Scsi.readCapacity10(), cap, 0, 8, dataIn = true)
        val bb = ByteBuffer.wrap(cap).order(ByteOrder.BIG_ENDIAN)
        var last = bb.getInt(0).toLong() and 0xFFFFFFFFL
        blockSize = bb.getInt(4)
        if (last == 0xFFFFFFFFL) {
            val cap16 = ByteArray(32)
            command(Scsi.readCapacity16(), cap16, 0, 32, dataIn = true)
            val b16 = ByteBuffer.wrap(cap16).order(ByteOrder.BIG_ENDIAN)
            last = b16.getLong(0)
            blockSize = b16.getInt(8)
        }
        if (blockSize !in listOf(512, 1024, 2048, 4096)) throw IOException("Unsupported sector size $blockSize bytes.")
        blockCount = last + 1

        // Optional: many drives report a write-protect switch here. A drive that does not answer is treated as writable.
        val ms = ByteArray(192)
        try {
            val n = command(Scsi.modeSense6(), ms, 0, ms.size, dataIn = true)
            writeProtected = Scsi.isWriteProtected(ms, n)
        } catch (_: IOException) {}
    }

    override fun read(lba: Long, buf: ByteArray, offset: Int, count: Int) = transfer(false, lba, buf, offset, count)
    override fun write(lba: Long, buf: ByteArray, offset: Int, count: Int) = transfer(true, lba, buf, offset, count)

    override fun flush() {
        // Optional on many drives; committing a large write cache can take a while.
        tryCommand(Scsi.synchronizeCache(), null, 0, 0, false, FLUSH_TIMEOUT)
    }

    private fun transfer(write: Boolean, lba: Long, buf: ByteArray, offset: Int, count: Int) {
        if (lba < 0 || lba + count > blockCount) throw IOException("Request outside the drive (LBA $lba).")
        var done = 0
        var failures = 0
        while (done < count) {
            val n = minOf(Scsi.blocksPerCommand(blockSize, rwBytes), count - done)
            try {
                command(Scsi.rw(write, lba + done, n), buf, offset + done * blockSize, n * blockSize, dataIn = !write, timeout = IO_TIMEOUT)
                done += n
                failures = 0
            } catch (e: UsbTransportException) {
                // Many cheap drives and OTG adapters stall on large transfers. Repeat the same blocks
                // (safe: same data, same place) with smaller commands before giving up.
                if (++failures > 4) throw e
                rwBytes = maxOf(MIN_RW_BYTES, rwBytes / 2)
                Thread.sleep(250L * failures)
            }
        }
    }

    private fun tryCommand(cdb: ByteArray, data: ByteArray?, off: Int, len: Int, dataIn: Boolean, timeout: Int = TIMEOUT): Boolean =
        try { command(cdb, data, off, len, dataIn, timeout); true } catch (e: IOException) { false }

    /** Runs one SCSI command; handles CHECK CONDITION with REQUEST SENSE and retries conditions that clear by themselves. Returns bytes moved. */
    @Synchronized
    private fun command(cdb: ByteArray, data: ByteArray?, off: Int, len: Int, dataIn: Boolean, timeout: Int = TIMEOUT): Int {
        var attempt = 0
        while (true) {
            val r = once(cdb, data, off, len, dataIn, timeout)
            when (r.status) {
                0 -> {
                    // Judge by the bytes actually moved: many drives report a wrong residue (Linux has a quirk list for this).
                    if (isReadWrite(cdb) && r.moved != len) throw UsbTransportException("The drive transferred less data than requested.")
                    return r.moved
                }
                1 -> {
                    val sense = requestSense()
                    if (Scsi.isRetryable(sense) && attempt < 4) {
                        attempt++
                        Thread.sleep(150L * attempt)
                        continue
                    }
                    throw IOException(Scsi.describe(sense, cdb[0].toInt() and 0xFF))
                }
                else -> {
                    resetRecovery()
                    if (attempt++ < 1) continue
                    throw UsbTransportException("The drive reported a protocol error.")
                }
            }
        }
    }

    private fun requestSense(): Scsi.Sense? {
        val b = ByteArray(18)
        return try {
            val r = once(Scsi.requestSense(), b, 0, b.size, true, TIMEOUT)
            if (r.status == 0) Scsi.parseSense(b) else null
        } catch (_: IOException) { null }
    }

    private class Result(val status: Int, val moved: Int)

    /** One Bulk-Only Transport exchange: command block, data phase, status block. */
    private fun once(cdb: ByteArray, data: ByteArray?, off: Int, len: Int, dataIn: Boolean, timeout: Int): Result {
        val t = tag++
        val cbw = Scsi.cbw(t, len, dataIn, cdb)
        if (connection.bulkTransfer(outEp, cbw, cbw.size, timeout) != cbw.size) {
            resetRecovery()
            throw disconnected()
        }
        var moved = 0
        if (len > 0 && data != null) {
            val ep = if (dataIn) inEp else outEp
            while (moved < len) {
                val piece = minOf(maxTransfer, len - moved)
                if (!dataIn) System.arraycopy(data, off + moved, scratch, 0, piece)
                val n = connection.bulkTransfer(ep, scratch, piece, timeout)
                if (n <= 0) {
                    clearHalt(ep)
                    break
                }
                if (dataIn) System.arraycopy(scratch, 0, data, off + moved, n)
                moved += n
                if (n < piece) break // short packet: the drive sent all it had
            }
        }
        var got = connection.bulkTransfer(inEp, csw, 13, timeout)
        if (got != 13) {
            clearHalt(inEp)
            got = connection.bulkTransfer(inEp, csw, 13, timeout)
        }
        val status = Scsi.parseCsw(csw)
        if (got != 13 || status == null || status.tag != t) {
            resetRecovery()
            throw disconnected()
        }
        return Result(status.status, moved)
    }

    private fun isReadWrite(cdb: ByteArray) = (cdb[0].toInt() and 0xFF) in setOf(0x28, 0x2A, 0x88, 0x8A)

    private fun disconnected() = UsbTransportException("The USB drive stopped responding or was disconnected. The drive is incomplete — reconnect it and write again.")

    private fun clearHalt(ep: UsbEndpoint) {
        connection.controlTransfer(0x02, 0x01, 0, ep.address, null, 0, TIMEOUT)
    }

    private fun resetRecovery() {
        connection.controlTransfer(0x21, 0xFF, 0, iface.id, null, 0, TIMEOUT)
        clearHalt(inEp)
        clearHalt(outEp)
        try { Thread.sleep(100) } catch (_: InterruptedException) {}
    }

    override fun close() {
        try { connection.releaseInterface(iface) } catch (_: Exception) {}
        connection.close()
    }
}

/** The USB link itself failed (stall, timeout, unplug) — as opposed to the drive refusing a command. */
class UsbTransportException(message: String) : IOException(message)
