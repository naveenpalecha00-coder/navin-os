package os.navin.usbcreator

import android.annotation.SuppressLint
import android.app.Application
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbManager
import android.net.Uri
import android.os.Build
import android.provider.OpenableColumns
import androidx.core.content.ContextCompat
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import os.navin.usbcreator.core.Fat32Formatter
import os.navin.usbcreator.core.ImageInfo
import os.navin.usbcreator.core.ImageInspector
import os.navin.usbcreator.core.ImageWriter
import os.navin.usbcreator.core.Progress
import os.navin.usbcreator.core.TransferStats
import os.navin.usbcreator.usb.UsbMassStorage
import java.io.IOException

data class DriveEntry(val id: Int, val name: String, val hasPermission: Boolean)
data class OpenDrive(val id: Int, val label: String, val sizeBytes: Long, val blockSize: Int, val removable: Boolean, val writeProtected: Boolean = false)
data class ImageSel(val uri: Uri, val name: String, val size: Long, val info: ImageInfo)

sealed interface TaskState {
    data object Idle : TaskState
    data class Running(val title: String, val progress: Progress?) : TaskState
    data class Done(val title: String, val lines: List<String>) : TaskState
    data class Failed(val message: String) : TaskState
    data object Cancelled : TaskState
}

enum class Confirm { WRITE, FORMAT }

data class UiState(
    val usbHost: Boolean = true,
    val drives: List<DriveEntry> = emptyList(),
    val drive: OpenDrive? = null,
    val connecting: Boolean = false,
    val driveError: String? = null,
    val image: ImageSel? = null,
    val imageError: String? = null,
    val verify: Boolean = true,
    val label: String = "NAVIN",
    val clusterSectors: Int = 0,
    val confirm: Confirm? = null,
    val task: TaskState = TaskState.Idle,
    val update: UpdateInfo? = null,
) {
    val busy get() = task is TaskState.Running
}

class MainViewModel(app: Application) : AndroidViewModel(app) {
    private val ctx: Context get() = getApplication()
    private val usb = app.getSystemService(Context.USB_SERVICE) as UsbManager
    private val _state = MutableStateFlow(UiState(usbHost = app.packageManager.hasSystemFeature(PackageManager.FEATURE_USB_HOST)))
    val state: StateFlow<UiState> = _state

    private var storage: UsbMassStorage? = null
    private var job: Job? = null
    @Volatile private var cancel = false
    @Volatile private var removed = false

    private val action = "${app.packageName}.USB_PERMISSION"

    private val permissionReceiver = object : BroadcastReceiver() {
        override fun onReceive(c: Context, i: Intent) {
            val device = i.usbDevice() ?: return
            if (i.getBooleanExtra(UsbManager.EXTRA_PERMISSION_GRANTED, false)) connect(device)
            else _state.update { it.copy(connecting = false, driveError = "Access to the USB drive was not allowed. Tap Connect and choose Allow.") }
            refresh()
        }
    }

    private val attachReceiver = object : BroadcastReceiver() {
        override fun onReceive(c: Context, i: Intent) {
            if (i.action == UsbManager.ACTION_USB_DEVICE_DETACHED) {
                val gone = i.usbDevice()
                if (gone != null && gone.deviceId == _state.value.drive?.id) {
                    removed = true
                    cancel = true
                    closeStorage()
                    _state.update { it.copy(drive = null, driveError = "The USB drive was disconnected.") }
                }
            }
            refresh()
        }
    }

    init {
        ContextCompat.registerReceiver(app, permissionReceiver, IntentFilter(action), ContextCompat.RECEIVER_NOT_EXPORTED)
        // Attach/detach are protected system broadcasts that only Android itself can send.
        ContextCompat.registerReceiver(app, attachReceiver, IntentFilter().apply {
            addAction(UsbManager.ACTION_USB_DEVICE_ATTACHED)
            addAction(UsbManager.ACTION_USB_DEVICE_DETACHED)
        }, ContextCompat.RECEIVER_EXPORTED)
        refresh()
        viewModelScope.launch(Dispatchers.IO) {
            runCatching { Network.checkUpdate() }.getOrNull()?.let { u -> _state.update { it.copy(update = u) } }
        }
    }

    @Suppress("DEPRECATION")
    private fun Intent.usbDevice(): UsbDevice? =
        if (Build.VERSION.SDK_INT >= 33) getParcelableExtra(UsbManager.EXTRA_DEVICE, UsbDevice::class.java) else getParcelableExtra(UsbManager.EXTRA_DEVICE)

    fun refresh() {
        val list = usb.deviceList.values.filter { UsbMassStorage.findInterface(it) != null }.map {
            val name = listOfNotNull(it.manufacturerNameSafe(), it.productNameSafe()).joinToString(" ").ifBlank { "USB drive %04X:%04X".format(it.vendorId, it.productId) }
            DriveEntry(it.deviceId, name, usb.hasPermission(it))
        }
        _state.update { s -> s.copy(drives = list, drive = s.drive?.takeIf { d -> list.any { it.id == d.id } }) }
    }

    private fun UsbDevice.manufacturerNameSafe() = try { manufacturerName?.trim()?.takeIf { it.isNotEmpty() } } catch (_: SecurityException) { null }
    private fun UsbDevice.productNameSafe() = try { productName?.trim()?.takeIf { it.isNotEmpty() } } catch (_: SecurityException) { null }

    /** Asks Android's normal USB permission dialog for this one drive (no permanent access). */
    @SuppressLint("UnspecifiedImmutableFlag")
    fun requestDrive(id: Int) {
        if (_state.value.busy) return
        val device = usb.deviceList.values.firstOrNull { it.deviceId == id } ?: return refresh()
        _state.update { it.copy(connecting = true, driveError = null) }
        if (usb.hasPermission(device)) return connect(device)
        val flags = if (Build.VERSION.SDK_INT >= 31) PendingIntent.FLAG_MUTABLE else 0
        val pi = PendingIntent.getBroadcast(ctx, id, Intent(action).setPackage(ctx.packageName), flags)
        usb.requestPermission(device, pi)
    }

    private fun connect(device: UsbDevice) {
        viewModelScope.launch(Dispatchers.IO) {
            closeStorage()
            try {
                val s = UsbMassStorage.open(usb, device)
                storage = s
                removed = false
                val label = listOf(s.vendor, s.product).filter { it.isNotBlank() }.joinToString(" ").ifBlank { "USB drive" }
                _state.update { it.copy(connecting = false, driveError = null, drive = OpenDrive(device.deviceId, label, s.sizeBytes, s.blockSize, s.removable, s.writeProtected)) }
            } catch (e: IOException) {
                _state.update { it.copy(connecting = false, drive = null, driveError = e.message) }
            } catch (e: SecurityException) {
                _state.update { it.copy(connecting = false, drive = null, driveError = "Android did not allow access to the drive.") }
            }
        }
    }

    /** Reads the image through the system file picker's one-time grant; nothing is kept afterwards. */
    fun selectImage(uri: Uri?) {
        if (uri == null) return
        viewModelScope.launch(Dispatchers.IO) {
            try {
                val cr = ctx.contentResolver
                var name = "image.iso"
                var size = -1L
                cr.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE), null, null, null)?.use { c ->
                    if (c.moveToFirst()) {
                        c.getString(0)?.let { name = it }
                        if (!c.isNull(1)) size = c.getLong(1)
                    }
                }
                if (size <= 0) size = cr.openAssetFileDescriptor(uri, "r")?.use { it.length } ?: -1
                if (size <= 0) throw IOException("Android could not report the file size. Move the ISO to Downloads and pick it again.")
                val head = ByteArray(ImageInspector.HEAD_BYTES)
                cr.openInputStream(uri)?.use { s ->
                    var n = 0
                    while (n < head.size) { val r = s.read(head, n, head.size - n); if (r < 0) break; n += r }
                } ?: throw IOException("Could not open the file.")
                val info = ImageInspector.inspect(head, size)
                val err = if (!info.supportsRawWrite) "This image has no partition table, so it cannot boot when copied to USB from Android. Use NAVIN USB Creator for Windows (extract mode) instead." else null
                _state.update { it.copy(image = ImageSel(uri, name, size, info), imageError = err, label = if (name.startsWith("navin", true)) "NAVIN OS" else it.label) }
            } catch (e: Exception) {
                _state.update { it.copy(image = null, imageError = e.message ?: "Could not read the file.") }
            }
        }
    }

    fun setVerify(v: Boolean) = _state.update { it.copy(verify = v) }
    fun setLabel(v: String) = _state.update { it.copy(label = v.take(11)) }
    fun setCluster(v: Int) = _state.update { it.copy(clusterSectors = v) }
    fun ask(c: Confirm?) = _state.update { it.copy(confirm = c) }
    fun dismissResult() = _state.update { it.copy(task = TaskState.Idle) }
    fun cancelTask() { cancel = true }

    fun startWrite() {
        val s = _state.value
        val dev = storage ?: return
        val img = s.image ?: return
        if (s.busy || s.imageError != null) return
        ask(null)
        cancel = false
        _state.update { it.copy(task = TaskState.Running("Erasing and writing ${img.name}", null)) }
        job = viewModelScope.launch(Dispatchers.IO) {
            try {
                val result = ctx.contentResolver.openInputStream(img.uri)?.use { input ->
                    var last = 0L
                    ImageWriter(dev).write(input, img.size, s.verify, { p -> last = post(p, last, "Erasing and writing ${img.name}") }, { cancel })
                } ?: throw IOException("Could not open the image file.")
                val official = try {
                    Network.officialIsoHashes()[result.imageSha256]?.let { "✓ Matches the official NAVIN OS release $it" }
                } catch (_: Exception) { "Offline — could not compare with the official NAVIN OS checksums." }
                _state.update {
                    it.copy(task = TaskState.Done("Your bootable USB is ready", listOfNotNull(
                        "Drive: ${s.drive?.label} (${TransferStats.formatBytes(s.drive?.sizeBytes ?: 0)})",
                        "Image: ${img.name}",
                        "Time: ${TransferStats.formatEta(result.seconds)}",
                        "Verification: " + if (result.verified) "passed — every byte matched" else "skipped",
                        "SHA-256: ${result.imageSha256}",
                        official,
                        "Unplug the drive, connect it to the PC and choose it in the boot menu (often F12, F11, F9 or Esc).",
                    )))
                }
            } catch (e: InterruptedException) {
                _state.update { it.copy(task = if (removed) TaskState.Failed("The USB drive was disconnected while writing. It is incomplete — reconnect it and write again.") else TaskState.Cancelled) }
            } catch (e: Exception) {
                _state.update { it.copy(task = TaskState.Failed(if (removed) "The USB drive was disconnected while writing. It is incomplete — reconnect it and write again." else e.message ?: "Writing failed.")) }
                reopenAfterFailure()
            }
        }
    }

    fun startFormat() {
        val s = _state.value
        val dev = storage ?: return
        if (s.busy) return
        ask(null)
        cancel = false
        _state.update { it.copy(task = TaskState.Running("Formatting as FAT32", null)) }
        job = viewModelScope.launch(Dispatchers.IO) {
            try {
                var last = 0L
                val l = Fat32Formatter.format(dev, s.label, s.clusterSectors, { pct -> last = post(Progress("Formatting", pct, 0.0, null, 0, 0), last, "Formatting as FAT32") }, { cancel })
                _state.update {
                    it.copy(task = TaskState.Done("Drive formatted", listOf(
                        "Drive: ${s.drive?.label}",
                        "File system: FAT32 · MBR · label ${Fat32Formatter.sanitizeLabel(s.label)}",
                        "Cluster size: ${TransferStats.formatBytes(l.clusterBytes.toLong())}",
                        "Usable space: ${TransferStats.formatBytes(l.clusterCount * l.clusterBytes)}",
                        "Unplug and reconnect the drive to use it for files.",
                    )))
                }
            } catch (e: InterruptedException) {
                _state.update { it.copy(task = TaskState.Cancelled) }
            } catch (e: Exception) {
                _state.update { it.copy(task = TaskState.Failed(e.message ?: "Formatting failed.")) }
                reopenAfterFailure()
            }
        }
    }

    /** After a failed erase/write the USB link may be stuck: reopen the same drive so START works again without replugging. */
    private fun reopenAfterFailure() {
        if (removed) return
        val id = _state.value.drive?.id ?: return
        val device = usb.deviceList.values.firstOrNull { it.deviceId == id } ?: return
        if (usb.hasPermission(device)) connect(device)
    }

    /** Throttles progress updates to about 5 per second. */
    private fun post(p: Progress, last: Long, title: String): Long {
        val now = System.currentTimeMillis()
        if (now - last < 200 && p.percent < 100) return last
        _state.update { it.copy(task = TaskState.Running(title, p)) }
        return now
    }

    private fun closeStorage() {
        try { storage?.close() } catch (_: Exception) {}
        storage = null
    }

    override fun onCleared() {
        cancel = true
        job?.cancel()
        closeStorage()
        runCatching { ctx.unregisterReceiver(permissionReceiver) }
        runCatching { ctx.unregisterReceiver(attachReceiver) }
    }
}
