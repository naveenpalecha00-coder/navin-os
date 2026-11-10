package os.navin.usbcreator.core

/** What a disk image can boot, read straight from its first sectors. */
data class ImageInfo(
    val length: Long,
    val isIso9660: Boolean,
    val hasMbrSignature: Boolean,
    val hasMbrBootCode: Boolean,
    val hasGpt: Boolean,
    val hasEfiPartition: Boolean,
) {
    /** A raw copy boots only when the image already contains its own partition table (isohybrid). */
    val supportsRawWrite get() = hasMbrSignature || hasGpt
    val isHybridIso get() = isIso9660 && supportsRawWrite
    val bootsUefi get() = hasGpt || hasEfiPartition
    val bootsLegacy get() = hasMbrSignature && hasMbrBootCode
    val partitionScheme get() = when {
        hasGpt -> "GPT (from image)"
        hasMbrSignature -> "MBR (from image)"
        else -> "None"
    }
    val targetSystem get() = when {
        bootsUefi && bootsLegacy -> "UEFI + Legacy BIOS"
        bootsUefi -> "UEFI only"
        bootsLegacy -> "Legacy BIOS only"
        else -> "Not bootable as a disk image"
    }
}

object ImageInspector {
    const val HEAD_BYTES = 0x8800 + 2048

    fun inspect(head: ByteArray, length: Long): ImageInfo {
        val mbr = head.size >= 512 && head[510] == 0x55.toByte() && head[511] == 0xAA.toByte()
        var bootCode = false
        var efi = false
        if (mbr) {
            bootCode = (0 until 440).any { head[it] != 0.toByte() }
            for (p in 0 until 4) {
                val type = head[446 + p * 16 + 4].toInt() and 0xFF
                if (type == 0xEF || type == 0xEE) efi = true
            }
        }
        return ImageInfo(
            length = length,
            isIso9660 = ascii(head, 0x8001, "CD001"),
            hasMbrSignature = mbr,
            hasMbrBootCode = bootCode,
            hasGpt = ascii(head, 512, "EFI PART"),
            hasEfiPartition = efi,
        )
    }

    private fun ascii(b: ByteArray, off: Int, s: String): Boolean {
        if (off + s.length > b.size) return false
        return s.indices.all { b[off + it] == s[it].code.toByte() }
    }
}
