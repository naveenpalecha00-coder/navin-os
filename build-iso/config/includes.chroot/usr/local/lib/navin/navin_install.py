"""NAVIN OS 1.2 pre-install checks (no GTK; unit-tested in build-iso/tests).

Pure functions turn what the live system sees (firmware mode, disks, other operating systems,
BitLocker, RAM, power, internet) into plain-language advice shown before Calamares opens.
collect() reads the running system; it never writes to any disk."""
import json, os, pathlib, socket, subprocess

MIN_RAM_MB = 1536      # same limit as Calamares welcome.conf requiredRam (1.5 GiB)
MIN_DISK_GB = 20       # same limit as Calamares welcome.conf requiredStorage


def parse_os_prober(text):
    """os-prober lines 'device:long name:short label:type' -> list of dicts."""
    out = []
    for line in (text or "").splitlines():
        parts = line.strip().split(":")
        if len(parts) >= 4 and parts[0].startswith("/dev/"):
            out.append({"device": parts[0].split("@", 1)[0], "name": parts[1], "label": parts[2], "type": parts[3]})
    return out


def parse_lsblk(text, live_disk=None):
    """lsblk -J -b -o NAME,PATH,SIZE,TYPE,RM,TRAN,MODEL,PTTYPE,FSTYPE,LABEL,MOUNTPOINT -> disks."""
    try:
        data = json.loads(text or "{}")
    except ValueError:
        return []
    disks = []
    for dev in data.get("blockdevices", []):
        if dev.get("type") != "disk" or str(dev.get("name", "")).startswith(("loop", "sr", "zram", "ram")):
            continue
        parts = [{"name": c.get("path") or "/dev/" + c.get("name", ""), "fstype": c.get("fstype") or "",
                  "label": c.get("label") or "", "size_gb": round(int(c.get("size") or 0) / 1e9, 1)}
                 for c in dev.get("children") or [] if c.get("type") == "part"]
        path = dev.get("path") or "/dev/" + dev.get("name", "")
        rm = dev.get("rm") in (True, 1, "1")
        disks.append({"name": path, "model": (dev.get("model") or "").strip(), "size_gb": round(int(dev.get("size") or 0) / 1e9, 1),
                      "removable": rm or dev.get("tran") == "usb", "table": dev.get("pttype") or None,
                      "live": path == live_disk, "parts": parts})
    return disks


def assess(info):
    """Return list of (level, title, text); level is 'block', 'warn' or 'ok'."""
    out = []
    fw = info.get("firmware")
    ram = info.get("ram_mb") or 0
    if ram and ram < MIN_RAM_MB:
        out.append(("block", "Not enough memory", f"This computer has {ram} MB RAM. NAVIN OS needs at least {MIN_RAM_MB} MB to install."))
    elif ram and ram < 3500:
        out.append(("ok", "Light mode", f"{ram} MB RAM: NAVIN OS will use its 2 GB profile (no window effects) to stay fast."))
    disks = [d for d in info.get("disks", []) if not d.get("live")]
    targets = [d for d in disks if d["size_gb"] >= MIN_DISK_GB]
    if not targets:
        out.append(("block", "No disk large enough", f"Install needs a disk with at least {MIN_DISK_GB} GB. Connect one and press Check again."))
    elif not [d for d in targets if not d["removable"]]:
        out.append(("warn", "Only USB disks found", "No internal disk was found. NAVIN OS can still be installed on an external drive."))
    oses = info.get("oses", [])
    windows = [o for o in oses if "windows" in (o["name"] + o["label"]).lower()]
    others = [o for o in oses if o not in windows]
    bitlocker = [p for d in disks for p in d["parts"] if p["fstype"].lower() == "bitlocker"]
    by_part = {p["name"]: d for d in disks for p in d["parts"]}
    if windows:
        w = windows[0]
        out.append(("ok", "Windows found — keep it",
                    f"{w['name']} is on {w['device']}. In the installer choose \"Install alongside\" to keep Windows; "
                    "after installing, the NAVIN boot menu lets you pick Windows or NAVIN OS every time you start."))
        disk = by_part.get(w["device"])
        win_uefi = w["type"] == "efi" or (disk is not None and disk["table"] == "gpt")
        if fw == "bios" and win_uefi:
            out.append(("warn", "Wrong start mode for dual boot",
                        "Windows starts in UEFI mode but this USB started in Legacy BIOS mode. Restart, open the boot menu "
                        "and pick the USB entry that starts with \"UEFI\", otherwise Windows will not appear in the boot menu."))
        elif fw == "uefi" and disk is not None and disk["table"] == "dos" and w["type"] != "efi":
            out.append(("warn", "Wrong start mode for dual boot",
                        "Windows on this disk uses Legacy BIOS mode but this USB started in UEFI mode. Restart and pick the "
                        "non-UEFI (Legacy) USB entry so both systems can share one boot menu."))
        out.append(("ok", "Before shrinking Windows",
                    "In Windows turn off Fast Startup (Control Panel > Power Options > Choose what the power buttons do) "
                    "and shut down fully. Back up important files first."))
    if bitlocker:
        out.append(("warn", "BitLocker encryption is on",
                    f"{', '.join(p['name'] for p in bitlocker)} is BitLocker-encrypted. The installer cannot shrink it. "
                    "In Windows, save your recovery key and turn BitLocker off (or shrink the partition in Windows Disk "
                    "Management) before installing alongside."))
    for o in others:
        out.append(("ok", f"{o['name']} found", f"{o['name']} on {o['device']} will also be listed in the NAVIN boot menu."))
    if not oses and targets:
        out.append(("ok", "No other system found",
                    "\"Erase disk\" in the installer deletes everything on the disk you choose. Back up your files first."))
    sb = info.get("secure_boot")
    if fw == "uefi" and sb:
        out.append(("ok", "Secure Boot is on", "Supported: NAVIN OS starts through Microsoft-signed shim and Debian-signed GRUB and kernel. "
                    "Extra drivers such as NVIDIA ask for a one-time key enrolment."))
    if info.get("on_battery"):
        out.append(("warn", "Running on battery", "Connect the charger. If the battery runs out during installation the disk can be left unusable."))
    if info.get("online") is False:
        out.append(("ok", "No internet", "Installation works offline. Updates and some drivers download later when you connect."))
    return out


def can_install(advice):
    return not any(level == "block" for level, _, _ in advice)


# ---------------- live system collection ----------------

def _run(args, timeout=60):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _live_disk():
    for line in _run(["findmnt", "-n", "-o", "SOURCE", "/run/live/medium"]).splitlines():
        pk = _run(["lsblk", "-n", "-o", "PKNAME", "-p", line.strip()]).strip()
        return pk or line.strip()
    return None


def _online():
    try:
        socket.create_connection(("deb.debian.org", 80), timeout=3).close()
        return True
    except OSError:
        return False


def _on_battery():
    supplies = list(pathlib.Path("/sys/class/power_supply").glob("*"))
    bats = [s for s in supplies if (s / "type").exists() and (s / "type").read_text().strip() == "Battery"]
    mains = [s for s in supplies if (s / "type").exists() and (s / "type").read_text().strip() in ("Mains", "USB")]
    if not bats:
        return False
    return not any((m / "online").exists() and (m / "online").read_text().strip() == "1" for m in mains)


def collect():
    import navin_hw
    fw = "uefi" if os.path.isdir("/sys/firmware/efi") else "bios"
    mem_kb = 0
    for line in pathlib.Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemTotal:"):
            mem_kb = int(line.split()[1])
    prober = _run(["sudo", "-n", "/usr/bin/os-prober"], timeout=120)
    lsblk = _run(["lsblk", "-J", "-b", "-o", "NAME,PATH,SIZE,TYPE,RM,TRAN,MODEL,PTTYPE,FSTYPE,LABEL,MOUNTPOINT"])
    return {"firmware": fw, "secure_boot": navin_hw.secure_boot_state() if fw == "uefi" else False,
            "ram_mb": mem_kb // 1024, "disks": parse_lsblk(lsblk, _live_disk()), "oses": parse_os_prober(prober),
            "on_battery": _on_battery(), "online": _online()}
