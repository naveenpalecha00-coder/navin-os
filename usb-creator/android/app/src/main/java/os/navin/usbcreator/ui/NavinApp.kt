package os.navin.usbcreator.ui

import android.content.Intent
import android.net.Uri
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import os.navin.usbcreator.BuildConfig
import os.navin.usbcreator.Confirm
import os.navin.usbcreator.MainViewModel
import os.navin.usbcreator.TaskState
import os.navin.usbcreator.UiState
import os.navin.usbcreator.core.Fat32Formatter
import os.navin.usbcreator.core.TransferStats

@Composable
fun NavinApp(vm: MainViewModel) {
    val s by vm.state.collectAsState()
    val pick = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri: Uri? -> vm.selectImage(uri) }
    BackHandler(enabled = s.busy) { /* writing: ignore back so the write is not interrupted */ }

    Column(
        Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background).statusBarsPadding().navigationBarsPadding()
            .verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Header(s)
        when (val t = s.task) {
            is TaskState.Running -> ProgressPanel(t, vm)
            is TaskState.Done -> Completion(t, vm)
            is TaskState.Failed -> Notice("Could not finish", t.message, Palette.Danger) { vm.dismissResult() }
            TaskState.Cancelled -> Notice("Stopped safely", "The drive is incomplete and will not boot. Write it again, or format it to use it for files.", Palette.Muted) { vm.dismissResult() }
            TaskState.Idle -> {}
        }
        if (!s.usbHost) Notice("USB OTG not supported", "This phone does not report USB host (OTG) support, so it cannot talk to USB drives. Use NAVIN USB Creator for Windows instead.", Palette.Danger, null)
        DeviceSection(s, vm)
        BootSection(s, onPick = { pick.launch(arrayOf("application/x-iso9660-image", "application/octet-stream", "*/*")) })
        OptionsSection(s, vm)
        Button(
            onClick = { vm.ask(Confirm.WRITE) },
            enabled = !s.busy && s.drive?.writeProtected == false && s.image != null && s.imageError == null,
            modifier = Modifier.fillMaxWidth().height(52.dp),
            shape = RoundedCornerShape(12.dp),
        ) { Text("START — ERASE & MAKE BOOTABLE", fontWeight = FontWeight.SemiBold, fontSize = 16.sp) }
        FormatSection(s, vm)
        Compatibility()
    }

    s.confirm?.let { c -> ConfirmErase(s, c, onConfirm = { if (c == Confirm.WRITE) vm.startWrite() else vm.startFormat() }, onDismiss = { vm.ask(null) }) }
}

@Composable
private fun Header(s: UiState) {
    val ctx = LocalContext.current
    Column {
        Text("NAVIN USB Creator", fontSize = 24.sp, fontWeight = FontWeight.Bold, color = Palette.Primary)
        Text("Version ${BuildConfig.VERSION_NAME} · Create bootable NAVIN OS USB drives", color = Palette.Muted, fontSize = 13.sp)
        s.update?.takeIf { it.newer }?.let { u ->
            TextButton(onClick = { ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(u.url))) }) { Text("Update available: ${u.version} — open download page", color = Palette.Success) }
        }
    }
}

@Composable
private fun SectionCard(title: String, content: @Composable () -> Unit) {
    Card(
        colors = CardDefaults.cardColors(containerColor = Palette.Panel),
        shape = RoundedCornerShape(16.dp),
        border = BorderStroke(1.dp, Palette.Border),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(title, fontWeight = FontWeight.SemiBold, fontSize = 16.sp, color = Palette.Text)
            content()
        }
    }
}

@Composable
private fun KeyValue(k: String, v: String) {
    Row(Modifier.fillMaxWidth()) {
        Text(k, color = Palette.Muted, fontSize = 14.sp, modifier = Modifier.weight(0.42f))
        Text(v, color = Palette.Text, fontSize = 14.sp, modifier = Modifier.weight(0.58f))
    }
}

@Composable
private fun DeviceSection(s: UiState, vm: MainViewModel) {
    SectionCard("Device Selection") {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(if (s.drives.isEmpty()) "No USB drive found. Connect one with an OTG adapter." else "${s.drives.size} USB drive(s) connected", color = Palette.Muted, fontSize = 14.sp, modifier = Modifier.weight(1f))
            IconButton(onClick = { vm.refresh() }, enabled = !s.busy) { Icon(Icons.Filled.Refresh, contentDescription = "Refresh drives", tint = Palette.Primary) }
        }
        s.drives.forEach { d ->
            val selected = s.drive?.id == d.id
            Card(
                colors = CardDefaults.cardColors(containerColor = if (selected) Palette.PaleBlue else MaterialTheme.colorScheme.surface),
                border = BorderStroke(1.dp, if (selected) Palette.Primary else Palette.Border),
                shape = RoundedCornerShape(12.dp),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Row(Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text(d.name, fontWeight = FontWeight.Medium)
                        if (selected) s.drive?.let { Text("${TransferStats.formatBytes(it.sizeBytes)} · ${it.blockSize}-byte sectors · ${it.label}", fontSize = 12.sp, color = Palette.Muted) }
                    }
                    if (!selected) OutlinedButton(onClick = { vm.requestDrive(d.id) }, enabled = !s.busy && !s.connecting) { Text(if (s.connecting) "…" else "Connect") }
                    else Icon(Icons.Filled.CheckCircle, contentDescription = "Selected", tint = Palette.Primary)
                }
            }
        }
        s.driveError?.let { Text(it, color = Palette.Danger, fontSize = 13.sp) }
        if (s.drive?.writeProtected == true) Text("This drive reports that it is write-protected, so it cannot be erased. Slide the lock switch on the card or adapter to unlocked, then unplug and reconnect it.", color = Palette.Danger, fontSize = 13.sp)
        Text("Only external USB drives are listed. The phone's own storage can never be selected or erased.", color = Palette.Muted, fontSize = 12.sp)
    }
}

@Composable
private fun BootSection(s: UiState, onPick: () -> Unit) {
    SectionCard("Boot Selection") {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(s.image?.name ?: "No ISO selected", modifier = Modifier.weight(1f), fontWeight = if (s.image != null) FontWeight.Medium else FontWeight.Normal)
            Button(onClick = onPick, enabled = !s.busy, colors = ButtonDefaults.buttonColors(containerColor = Palette.PaleBlue, contentColor = Palette.Primary)) { Text("SELECT") }
        }
        s.image?.let { i ->
            KeyValue("Size", TransferStats.formatBytes(i.size))
            KeyValue("Type", if (i.info.isHybridIso) "Hybrid ISO" else if (i.info.isIso9660) "ISO 9660" else "Disk image")
        }
        s.imageError?.let { Text(it, color = Palette.Danger, fontSize = 13.sp) }
        Text("The file is read once through Android's file picker. No permanent storage access is requested.", color = Palette.Muted, fontSize = 12.sp)
    }
}

@Composable
private fun OptionsSection(s: UiState, vm: MainViewModel) {
    SectionCard("Drive Options") {
        val info = s.image?.info
        KeyValue("Partition scheme", info?.partitionScheme ?: "—")
        KeyValue("Target system", info?.targetSystem ?: "—")
        KeyValue("File system", if (info != null) "Set by the image" else "—")
        KeyValue("Cluster size", if (info != null) "Set by the image" else "—")
        KeyValue("Write mode", "Erase drive, then disk image (byte-for-byte)")
        Row(verticalAlignment = Alignment.CenterVertically) {
            Checkbox(checked = s.verify, onCheckedChange = { vm.setVerify(it) }, enabled = !s.busy)
            Text("Verify the drive after writing (recommended)", fontSize = 14.sp)
        }
    }
}

@Composable
private fun FormatSection(s: UiState, vm: MainViewModel) {
    SectionCard("Format Options") {
        Text("Turn the USB drive back into normal storage (erases it).", color = Palette.Muted, fontSize = 13.sp)
        OutlinedTextField(value = s.label, onValueChange = { vm.setLabel(it) }, label = { Text("Volume label") }, singleLine = true, enabled = !s.busy, modifier = Modifier.fillMaxWidth())
        KeyValue("File system", "FAT32 · MBR")
        Text("Cluster size", color = Palette.Muted, fontSize = 14.sp)
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            listOf(0 to "Auto", 8 to "4K", 16 to "8K", 32 to "16K", 64 to "32K").forEach { (v, l) ->
                FilterChip(selected = s.clusterSectors == v, onClick = { vm.setCluster(v) }, label = { Text(l) }, enabled = !s.busy)
            }
        }
        OutlinedButton(onClick = { vm.ask(Confirm.FORMAT) }, enabled = !s.busy && s.drive?.writeProtected == false, modifier = Modifier.fillMaxWidth()) { Text("Format drive as FAT32") }
        if (s.drive != null && s.drive.blockSize != Fat32Formatter.SECTOR) Text("This drive uses ${s.drive.blockSize}-byte sectors; formatting is not supported for it.", color = Palette.Danger, fontSize = 12.sp)
    }
}

@Composable
private fun ProgressPanel(t: TaskState.Running, vm: MainViewModel) {
    Card(colors = CardDefaults.cardColors(containerColor = Palette.PaleBlue), shape = RoundedCornerShape(16.dp), modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            val p = t.progress
            Text(t.title, fontWeight = FontWeight.SemiBold)
            Text("${p?.phase ?: "Starting"} — ${"%.1f".format(p?.percent ?: 0.0)}%", fontSize = 20.sp, fontWeight = FontWeight.Bold, color = Palette.Primary)
            LinearProgressIndicator(progress = { ((p?.percent ?: 0.0) / 100).toFloat() }, modifier = Modifier.fillMaxWidth().height(8.dp))
            if (p != null && p.total > 0) {
                Text("${TransferStats.formatBytes(p.done)} of ${TransferStats.formatBytes(p.total)} · ${TransferStats.formatBytes(p.bytesPerSecond.toLong())}/s · ${TransferStats.formatEta(p.remainingSeconds)} left", fontSize = 13.sp, color = Palette.Muted)
            }
            Text("Keep the app open and the drive connected.", fontSize = 12.sp, color = Palette.Muted)
            OutlinedButton(onClick = { vm.cancelTask() }) { Text("CANCEL") }
        }
    }
}

@Composable
private fun Completion(t: TaskState.Done, vm: MainViewModel) {
    Card(colors = CardDefaults.cardColors(containerColor = Palette.PaleBlue), shape = RoundedCornerShape(16.dp), modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Icon(Icons.Filled.CheckCircle, contentDescription = null, tint = Palette.Success, modifier = Modifier.size(48.dp))
            Text(t.title, fontSize = 20.sp, fontWeight = FontWeight.Bold)
            t.lines.forEach { line ->
                Text(line, fontSize = 13.sp, fontFamily = if (line.startsWith("SHA-256")) FontFamily.Monospace else FontFamily.Default)
            }
            Spacer(Modifier.height(4.dp))
            Button(onClick = { vm.dismissResult() }) { Text("Done") }
        }
    }
}

@Composable
private fun Notice(title: String, text: String, color: androidx.compose.ui.graphics.Color, onClose: (() -> Unit)?) {
    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface), border = BorderStroke(1.dp, color), shape = RoundedCornerShape(16.dp), modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Filled.Warning, contentDescription = null, tint = color)
                Text("  $title", fontWeight = FontWeight.SemiBold, color = color)
            }
            Text(text, fontSize = 14.sp)
            onClose?.let { TextButton(onClick = it) { Text("OK") } }
        }
    }
}

@Composable
private fun Compatibility() {
    SectionCard("Compatibility") {
        Row(verticalAlignment = Alignment.Top) {
            Icon(Icons.Filled.Info, contentDescription = null, tint = Palette.Primary)
            Column(Modifier.padding(start = 8.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                listOf(
                    "Needs Android 7.0+ with USB OTG (host) support and an OTG adapter or USB-C drive.",
                    "Works with USB flash drives and card readers that use the standard USB mass-storage protocol. USB hubs, phones and cameras are not supported.",
                    "Writes hybrid ISOs (NAVIN OS, Debian, Ubuntu, Fedora…) byte-for-byte; they boot on UEFI and Legacy BIOS PCs. ISOs without a partition table need the Windows app.",
                    "Drives over 2 TB, or with non-512-byte sectors, can be written but not formatted.",
                    "Some phones cannot power large USB hard drives. Use a flash drive or a powered adapter.",
                    "No root needed. Android only allows external USB devices here, so the phone's own storage is never touched.",
                ).forEach { Text("• $it", fontSize = 13.sp, color = Palette.Text) }
            }
        }
    }
}

@Composable
private fun ConfirmErase(s: UiState, c: Confirm, onConfirm: () -> Unit, onDismiss: () -> Unit) {
    AlertDialog(
        onDismissRequest = onDismiss,
        icon = { Icon(Icons.Filled.Warning, contentDescription = null, tint = Palette.Danger) },
        title = { Text("Erase this drive?") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Everything on this drive will be permanently erased:", color = Palette.Danger)
                Card(colors = CardDefaults.cardColors(containerColor = Palette.PaleBlue)) {
                    Column(Modifier.padding(10.dp)) {
                        Text("Drive: ${s.drive?.label}", fontWeight = FontWeight.Medium)
                        Text("Capacity: ${TransferStats.formatBytes(s.drive?.sizeBytes ?: 0)}")
                        Text(if (c == Confirm.WRITE) "Image: ${s.image?.name}" else "Format: FAT32, label ${Fat32Formatter.sanitizeLabel(s.label)}")
                    }
                }
                Text(
                    if (c == Confirm.WRITE) "One tap erases the drive, writes NAVIN OS${if (s.verify) ", checks every byte" else ""} and makes it bootable. Back up any files first."
                    else "One tap erases the drive and formats it as FAT32. Back up any files first."
                )
            }
        },
        confirmButton = {
            Button(onClick = onConfirm, colors = ButtonDefaults.buttonColors(containerColor = Palette.Danger)) {
                Text(if (c == Confirm.WRITE) "Erase & make bootable" else "Erase and format")
            }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Cancel") } },
    )
}
