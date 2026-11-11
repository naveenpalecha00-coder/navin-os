"""NAVIN 2.0 hardware detection (Debian 13).

Pure parsing/decision functions (unit-tested) plus collect() which reads the
running system (DMI, /proc, /sys, ACPI, PCI, USB, input, hwmon). Nothing here
installs packages: recommendations are applied only after the user confirms in
NAVIN Driver Manager. The only automatic action is loading in-kernel modules
from SAFE_MODULES when matching hardware is present but its driver is not.
"""
import json, os, pathlib, re, subprocess

BUS = {"0003": "USB", "0005": "Bluetooth", "0011": "PS/2", "0018": "I2C", "0019": "Platform", "001e": "RMI"}
SAFE_MODULES = ("i2c_hid_acpi", "hid_multitouch", "psmouse", "elan_i2c", "hid_generic",
                "i2c_designware_platform", "btusb", "thinkpad_acpi", "dell_smm_hwmon", "coretemp", "k10temp")
TOUCHPAD_ACPI = {"PNP0C50": "HID-over-I2C", "ACPI0C50": "HID-over-I2C", "MSFT0001": "Precision touchpad (HID-over-I2C)",
                 "ELAN": "ELAN", "SYNA": "Synaptics", "ALPS": "ALPS", "DLL": "ALPS (Dell)", "FTCS": "FocalTech", "GXTP": "Goodix"}
VENDORS_BY_ID = {"04f3": "ELAN", "06cb": "Synaptics", "044e": "ALPS", "0488": "Cirque", "05ac": "Apple", "2808": "FocalTech", "27c6": "Goodix", "093a": "PixArt"}
GPU_VENDORS = {"8086": "Intel", "1002": "AMD", "10de": "NVIDIA", "1af4": "Virtio", "15ad": "VMware", "1234": "QEMU"}


def parse_input_devices(text):
    """Parse /proc/bus/input/devices into dicts."""
    out = []
    for block in text.strip().split("\n\n"):
        d = {"name": "", "bus": "", "vendor": "", "product": "", "handlers": [], "prop": 0, "abs": 0, "phys": "", "sysfs": ""}
        for line in block.splitlines():
            if line.startswith("I:"):
                m = dict(re.findall(r"(\w+)=([0-9a-fA-F]+)", line))
                d["bus"], d["vendor"], d["product"] = m.get("Bus", "").lower(), m.get("Vendor", "").lower(), m.get("Product", "").lower()
            elif line.startswith("N:"):
                d["name"] = line.split("=", 1)[1].strip().strip('"')
            elif line.startswith("P:"):
                d["phys"] = line.split("=", 1)[1].strip()
            elif line.startswith("S:"):
                d["sysfs"] = line.split("=", 1)[1].strip()
            elif line.startswith("H:"):
                d["handlers"] = line.split("=", 1)[1].split()
            elif line.startswith("B: PROP="):
                d["prop"] = int(line.split("=", 1)[1].split()[-1] or "0", 16)
            elif line.startswith("B: ABS="):
                d["abs"] = int(line.split("=", 1)[1].replace(" ", "") or "0", 16)
        if d["name"]:
            out.append(d)
    return out


def is_touchpad(dev):
    name = dev["name"].lower()
    if any(w in name for w in ("touchpad", "trackpad", "glidepoint", "synps/2", "alpsps/2", "elantech")):
        return True
    # INPUT_PROP_POINTER(0) + multitouch ABS_MT_POSITION_X (bit 53) and not a touchscreen (PROP_DIRECT bit 1)
    return bool(dev["prop"] & 0x1) and not (dev["prop"] & 0x2) and bool(dev["abs"] >> 53 & 1)


def touchpad_vendor(dev):
    name = dev["name"].lower()
    for key, vendor in (("elan", "ELAN"), ("synaptics", "Synaptics"), ("syna", "Synaptics"), ("synps/2", "Synaptics"),
                        ("alps", "ALPS"), ("dll", "ALPS"), ("focaltech", "FocalTech"), ("ftcs", "FocalTech"),
                        ("goodix", "Goodix"), ("gxtp", "Goodix"), ("glidepoint", "Cirque"), ("apple", "Apple")):
        if key in name:
            return vendor
    return VENDORS_BY_ID.get(dev["vendor"], "Generic")


def describe_touchpad(dev):
    bus = BUS.get(dev["bus"], dev["bus"] or "unknown")
    kind = "Precision/HID multitouch" if bus in ("I2C", "USB", "Bluetooth") else ("RMI4/SMBus" if bus == "RMI" else "PS/2")
    return {"name": dev["name"], "vendor": touchpad_vendor(dev), "bus": bus, "protocol": kind,
            "event": next((h for h in dev["handlers"] if h.startswith("event")), None)}


def touchpad_plan(devices, acpi_ids, loaded_modules, laptop=True):
    """Decide touchpad state and safe actions.

    Returns {"touchpads": [...], "modules": [...], "kernel_params": [...], "notes": [...]}
    kernel_params are suggestions only (shown in Driver Manager), never applied automatically.
    """
    pads = [describe_touchpad(d) for d in devices if is_touchpad(d)]
    plan = {"touchpads": pads, "modules": [], "kernel_params": [], "notes": []}
    acpi = sorted({TOUCHPAD_ACPI[k] for a in acpi_ids for k in TOUCHPAD_ACPI if a.upper().startswith(k)})
    hid_i2c = any(a.upper() in ("PNP0C50", "ACPI0C50", "MSFT0001") for a in acpi_ids)
    if not pads:
        if hid_i2c or acpi:
            for m in ("i2c_designware_platform", "i2c_hid_acpi", "hid_multitouch"):
                if m not in loaded_modules:
                    plan["modules"].append(m)
            if any("ELAN" == x for x in acpi) and "elan_i2c" not in loaded_modules:
                plan["modules"].append("elan_i2c")
            plan["notes"].append("ACPI reports a touchpad (" + ", ".join(acpi or ["HID-over-I2C"]) + ") but no input device exists; loading I2C-HID drivers.")
        elif laptop:
            if "psmouse" not in loaded_modules:
                plan["modules"].append("psmouse")
            plan["notes"].append("No touchpad detected. If this laptop has one, try Safe Graphics/ACPI options in the boot menu and report the model.")
    for p in pads:
        if p["bus"] == "PS/2" and p["vendor"] == "Synaptics":
            plan["kernel_params"].append("psmouse.synaptics_intertouch=1")
            plan["notes"].append("Synaptics on PS/2: SMBus/RMI4 mode may give smoother multitouch (suggested kernel option).")
        if p["bus"] == "PS/2" and p["vendor"] == "ELAN":
            plan["kernel_params"].append("psmouse.elantech_smbus=1")
        if p["bus"] in ("I2C", "USB") and "hid_multitouch" not in loaded_modules:
            plan["modules"].append("hid_multitouch")
    plan["modules"] = [m for i, m in enumerate(plan["modules"]) if m in SAFE_MODULES and m not in plan["modules"][:i]]
    plan["kernel_params"] = sorted(set(plan["kernel_params"]))
    return plan


def classify_pci(class_code):
    """class_code like '0x030000' -> category."""
    c = class_code.lower().replace("0x", "")[:4]
    return {"0300": "gpu", "0302": "gpu", "0380": "gpu", "0280": "wifi", "0200": "ethernet", "0403": "audio",
            "0401": "audio", "0106": "storage", "0108": "storage", "0104": "storage", "0c03": "usb",
            "0d11": "bluetooth", "0c80": "thunderbolt", "0c05": "smbus"}.get(c, "other")


def gpu_plan(gpus, secure_boot, installed, nvidia_detect=""):
    """gpus: [{'vendor':'8086','device':'..','driver':'i915'}] -> recommendations."""
    rec = []
    def want(pkg, why, confirm=False):
        if pkg not in installed and pkg not in [r["package"] for r in rec]:
            rec.append({"package": pkg, "reason": why, "needs_confirmation": confirm})
    for g in gpus:
        v = GPU_VENDORS.get(g["vendor"], "Other")
        if v == "Intel":
            want("intel-media-va-driver", "Intel video decode/encode (Broadwell and newer)")
            want("i965-va-driver", "Intel video decode for older GPUs (before Broadwell)")
        elif v == "AMD":
            want("firmware-amd-graphics", "AMD GPU firmware")
            want("mesa-va-drivers", "AMD VA-API video acceleration")
            if g.get("driver") == "radeon":
                rec.append({"package": None, "reason": "Older AMD GPU on 'radeon' driver: Vulkan is not available on this hardware.", "needs_confirmation": False})
        elif v == "NVIDIA":
            text = nvidia_detect.lower()
            m = re.search(r"install the\s+(nvidia-[a-z0-9-]*driver[a-z0-9-]*)", text)
            if m:
                note = "NVIDIA proprietary driver supported by nvidia-detect"
                if secure_boot:
                    note += "; Secure Boot is ON — the DKMS module must be signed with an enrolled MOK key before it loads"
                want(m.group(1), note, confirm=True)
                want("firmware-nvidia-gsp", "Firmware used by newer NVIDIA GPUs", confirm=True)
            else:
                rec.append({"package": None, "reason": "NVIDIA: no compatible proprietary driver reported; the open-source Nouveau driver stays in use.", "needs_confirmation": False})
                want("firmware-nvidia-graphics", "Firmware for Nouveau on newer NVIDIA GPUs")
    return rec


def ram_profile(mem_total_kb):
    """Return (profile, zram_percent)."""
    gb = mem_total_kb / 1048576
    if gb <= 2.6:
        return "lite", 100
    if gb <= 6.5:
        return "balanced", 75
    return "standard", 50


def thermal_level(temp_c):
    if temp_c is None:
        return "unknown"
    if temp_c >= 98:
        return "critical"
    if temp_c >= 90:
        return "hot"
    if temp_c >= 80:
        return "warm"
    return "ok"


# ---------------- NAVIN 2.0: old-laptop quirks (Samsung RV411 class) ----------------

# Intel GMA 4500 (gen4) and Ironlake "HD Graphics" (gen5, 1st-gen Core i3/i5/Pentium P6xxx) device ids.
OLD_INTEL_GPU = {"2a42", "2e02", "2e12", "2e22", "2e32", "2e42", "2e92", "0042", "0046"}
I8042_SAMSUNG = ("i8042.nomux=1", "i8042.reset=1")
# Tried in order by navin-touchpad-rescue when a laptop shows no touchpad: native protocol first,
# then plain IntelliMouse modes that every PS/2 touchpad understands (cursor + tap, no multitouch).
PSMOUSE_FALLBACKS = ("", "proto=exps", "proto=imps", "proto=bare")


def is_samsung(dmi):
    return (dmi.get("sys_vendor") or "").strip().upper().startswith("SAMSUNG")


def is_old_intel(gpu):
    return gpu.get("vendor") == "8086" and (gpu.get("device") or "").lower() in OLD_INTEL_GPU


def is_old_cpu(flags):
    """CPUs before Sandy Bridge (no AVX), e.g. 1st-gen Core i3 M 3xx / Pentium P6xxx."""
    return "avx" not in set(flags)


def laptop_quirks(dmi, gpus, cpu_flags, mem_kb, rotational=False):
    """Decide NAVIN 2.0 compatibility settings for one computer (pure, unit-tested).

    kernel_params are written to the installed boot menu only for Samsung laptops (i8042 controller
    quirk that makes PS/2 touchpads disappear); everything else is applied at runtime."""
    old_gpu = any(is_old_intel(g) for g in gpus)
    old_cpu = is_old_cpu(cpu_flags)
    q = {"samsung": is_samsung(dmi), "old_gpu": old_gpu, "old_cpu": old_cpu,
         "old_laptop": old_gpu or old_cpu, "kernel_params": [], "notes": [],
         "xorg_driver": "intel-sna" if old_gpu else "modesetting",
         "compositor": "lite" if (old_gpu or mem_kb <= 2726297) else "xfwm",
         "zram_algo": "lz4" if old_cpu else "zstd",
         "chrome_gpu": "safe" if old_gpu else "full",
         "io_scheduler": "bfq" if rotational else "mq-deadline",
         "sata_alpm": "max_performance" if (old_cpu or old_gpu) else "default",
         "battery_turbo": not old_cpu}
    if q["samsung"]:
        q["kernel_params"] += list(I8042_SAMSUNG)
        q["notes"].append("Samsung laptop: touchpad controller fix (i8042.nomux/reset) is used. If the cursor still does not move, press Fn+F5 once — Samsung turns the touchpad off in hardware with that key.")
    if old_gpu:
        q["notes"].append("1st-gen Intel graphics: NAVIN uses the Intel SNA driver, the light compositor and Chrome's safe GPU mode (no forced GPU raster) to stop screen freezes.")
    if old_cpu:
        q["notes"].append("Older CPU: LZ4 memory compression (faster than zstd on this CPU) and no turbo boost on battery to keep temperatures down.")
    return q


def grub_quirks_cfg(params):
    """Text for /etc/default/grub.d/90-navin-quirks.cfg (empty string = remove the file)."""
    params = [p for p in params if re.fullmatch(r"[a-z0-9_.]+=[a-z0-9_.,-]+", p)]
    if not params:
        return ""
    return ("# NAVIN 2.0 hardware quirks (written by navin-hwdetect; remove with: navin-touchpad quirks off)\n"
            f'GRUB_CMDLINE_LINUX_DEFAULT="$GRUB_CMDLINE_LINUX_DEFAULT {" ".join(params)}"\n')


def touchpad_missing(devices, laptop, has_aux_port):
    """True when a laptop with a PS/2 AUX port shows no touchpad input device (rescue needed)."""
    return bool(laptop and has_aux_port and not any(is_touchpad(d) for d in devices))


# ---------------- NAVIN 2.0: real fan speed slider ----------------

PWM_FLOOR = 77  # 30 % of 255: a manual setting never runs the fan slower than this


def fan_pwm_target(percent, current_auto_pwm=0):
    """Slider 1..100 -> PWM 0..255. Never below 30 % and never below what the BIOS was already
    running (so the slider can only make cooling stronger than firmware automatic control)."""
    percent = max(1, min(100, int(percent)))
    value = round(PWM_FLOOR + (255 - PWM_FLOOR) * (percent - 1) / 99)
    return max(value, min(255, int(current_auto_pwm or 0)))


def thinkpad_level(percent):
    """Slider 1..100 -> ThinkPad fan level 1..7 (0 = stopped is never used)."""
    return max(1, min(7, -(-max(1, min(100, int(percent))) * 7 // 100)))


def fan_plan(control, percent, current_auto_pwm=0):
    """What `navin-fan set PERCENT` does on each fan interface. 0 = hand control back to the BIOS."""
    percent = int(percent)
    if not 0 <= percent <= 100:
        raise ValueError("percent must be 0..100")
    if percent == 0:
        return {"action": "auto"}
    if control == "thinkpad":
        return {"action": "thinkpad", "level": thinkpad_level(percent)}
    if control == "hwmon-pwm":
        return {"action": "pwm", "pwm": fan_pwm_target(percent, current_auto_pwm)}
    if control == "platform-profile":
        return {"action": "profile", "profile": "quiet" if percent < 34 else ("balanced" if percent < 67 else "performance")}
    # No fan interface (many older laptops, e.g. Samsung RV411): the slider limits CPU heat instead.
    return {"action": "heat-limit", "cpu_max_percent": max(50, 100 - (percent // 2))}


# ---------------- live system collection ----------------

def _read(path, default=""):
    try:
        return pathlib.Path(path).read_text(errors="replace").strip()
    except OSError:
        return default


def _run(args, timeout=8):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def secure_boot_state():
    out = _run(["mokutil", "--sb-state"])
    if "enabled" in out.lower():
        return True
    if "disabled" in out.lower():
        return False
    for f in pathlib.Path("/sys/firmware/efi/efivars").glob("SecureBoot-*"):
        try:
            return f.read_bytes()[-1] == 1
        except OSError:
            pass
    return None if pathlib.Path("/sys/firmware/efi").exists() else False


def hwmon():
    sensors = []
    for h in sorted(pathlib.Path("/sys/class/hwmon").glob("hwmon*")):
        s = {"name": _read(h / "name"), "path": str(h), "temps": [], "fans": [], "pwm": []}
        for t in sorted(h.glob("temp*_input")):
            try:
                s["temps"].append({"label": _read(str(t).replace("_input", "_label"), t.name[:-6]), "c": int(_read(t, "0")) / 1000})
            except ValueError:
                pass
        for f in sorted(h.glob("fan*_input")):
            s["fans"].append({"label": _read(str(f).replace("_input", "_label"), f.name[:-6]), "rpm": int(_read(f, "0") or 0)})
        for p in sorted(h.glob("pwm[0-9]")):
            s["pwm"].append({"path": str(p), "value": _read(p), "enable": _read(str(p) + "_enable"), "writable": os.access(p, os.W_OK)})
        sensors.append(s)
    return sensors


def collect():
    dmi = {k: _read("/sys/class/dmi/id/" + k) for k in ("sys_vendor", "product_name", "product_version", "board_name", "bios_version", "chassis_type")}
    laptop = dmi.get("chassis_type") in ("8", "9", "10", "11", "14", "30", "31", "32")
    cpuinfo = _read("/proc/cpuinfo")
    model = next((l.split(":", 1)[1].strip() for l in cpuinfo.splitlines() if l.startswith("model name")), "unknown")
    flags = next((l.split(":", 1)[1].split() for l in cpuinfo.splitlines() if l.startswith("flags")), [])
    mem_kb = int(re.search(r"MemTotal:\s+(\d+)", _read("/proc/meminfo", "MemTotal: 0")).group(1))
    loaded = {l.split()[0] for l in _read("/proc/modules").splitlines() if l}
    acpi_ids = [_read(p) for p in pathlib.Path("/sys/bus/acpi/devices").glob("*/hid")]
    devices = parse_input_devices(_read("/proc/bus/input/devices"))
    pci = []
    for d in sorted(pathlib.Path("/sys/bus/pci/devices").glob("*")):
        drv = d / "driver"
        pci.append({"slot": d.name, "class": classify_pci(_read(d / "class")), "vendor": _read(d / "vendor").replace("0x", ""),
                    "device": _read(d / "device").replace("0x", ""), "driver": os.path.basename(os.readlink(drv)) if drv.is_symlink() else None})
    lspci = {l.split()[0]: l for l in _run(["lspci", "-D"]).splitlines() if l}
    for p in pci:
        p["description"] = lspci.get(p["slot"], "").split(" ", 1)[-1]
    gpus = [p for p in pci if p["class"] == "gpu"]
    installed = {l.split("\t")[0] for l in _run(["dpkg-query", "-W", "-f=${Package}\t${db:Status-Status}\n"]).splitlines() if l.endswith("\tinstalled")}
    sb = secure_boot_state()
    batteries = []
    for b in pathlib.Path("/sys/class/power_supply").glob("BAT*"):
        full = _read(b / "energy_full") or _read(b / "charge_full"); design = _read(b / "energy_full_design") or _read(b / "charge_full_design")
        health = round(int(full) * 100 / int(design)) if full.isdigit() and design.isdigit() and int(design) else None
        batteries.append({"name": b.name, "capacity": _read(b / "capacity"), "status": _read(b / "status"), "health_percent": health})
    net = []
    for n in pathlib.Path("/sys/class/net").glob("*"):
        if n.name == "lo":
            continue
        drv = n / "device/driver"
        net.append({"iface": n.name, "wireless": (n / "wireless").exists(), "driver": os.path.basename(os.readlink(drv)) if drv.is_symlink() else None})
    profile, zram = ram_profile(mem_kb)
    root_rota = _run(["lsblk", "-dno", "ROTA", _run(["findmnt", "-no", "SOURCE", "/"]).strip() or "/dev/sda"]).strip() == "1"
    aux = any("AUX" in _read(p / "description") for p in pathlib.Path("/sys/bus/serio/devices").glob("serio*"))
    report = {
        "dmi": dmi, "laptop": laptop, "cpu": {"model": model, "arch": os.uname().machine, "cores": os.cpu_count()},
        "memory": {"total_kb": mem_kb, "profile": profile, "zram_percent": zram},
        "secure_boot": sb, "uefi": pathlib.Path("/sys/firmware/efi").exists(), "kernel": os.uname().release,
        "gpus": [{**g, "vendor_name": GPU_VENDORS.get(g["vendor"], "Other")} for g in gpus],
        "pci": pci, "usb": [l for l in _run(["lsusb"]).splitlines() if l],
        "network": net, "bluetooth": [p.name for p in pathlib.Path("/sys/class/bluetooth").glob("hci*")],
        "audio": [l for l in _read("/proc/asound/cards").splitlines() if re.match(r"\s*\d+ \[", l)],
        "storage": [l for l in _run(["lsblk", "-dno", "NAME,TRAN,ROTA,SIZE,MODEL"]).splitlines() if l and not l.startswith(("loop", "zram", "sr"))],
        "batteries": batteries, "sensors": hwmon(),
        "touchpad": touchpad_plan(devices, acpi_ids, loaded, laptop),
        "touchpad_missing": touchpad_missing(devices, laptop, aux),
        "quirks": laptop_quirks(dmi, gpus, flags, mem_kb, root_rota),
        "drivers": gpu_plan(gpus, bool(sb), installed, _run(["nvidia-detect"], 20) if any(g["vendor"] == "10de" for g in gpus) else ""),
    }
    if "navin.oldlaptop=1" in _read("/proc/cmdline").split():  # "Old Laptop Mode" boot entry
        report["quirks"].update(old_laptop=True, compositor="lite", chrome_gpu="safe")
    return report


def apply(report, log):
    """Root only: load safe in-kernel modules from the touchpad plan, then NAVIN 2.0 quirks."""
    for m in report["touchpad"]["modules"]:
        rc = subprocess.run(["modprobe", m], capture_output=True, text=True)
        log(f"modprobe {m}: {'ok' if rc.returncode == 0 else rc.stderr.strip()}")
    apply_quirks(report.get("quirks") or {}, log)


def apply_quirks(q, log, root="/"):
    """Write the NAVIN 2.0 compatibility files chosen by laptop_quirks(). Root only. Idempotent."""
    r = pathlib.Path(root)
    run = pathlib.Path(root, "run/navin"); run.mkdir(parents=True, exist_ok=True)
    (run / "quirks.json").write_text(json.dumps(q))
    (run / "compositor-default").write_text(q.get("compositor", "xfwm") + "\n")
    (run / "zram-algo").write_text(q.get("zram_algo", "zstd") + "\n")
    (run / "chrome-gpu").write_text(q.get("chrome_gpu", "full") + "\n")
    xorg = r / "etc/X11/xorg.conf.d/10-navin-oldintel.conf"
    if q.get("xorg_driver") == "intel-sna" and (r / "usr/lib/xorg/modules/drivers/intel_drv.so").exists():
        xorg.parent.mkdir(parents=True, exist_ok=True)
        xorg.write_text('# NAVIN 2.0: 1st-gen Intel graphics (gen4/gen5) - Intel SNA driver, TearFree, no screen freezes\n'
                        'Section "Device"\n  Identifier "NAVIN old Intel"\n  Driver "intel"\n  Option "AccelMethod" "sna"\n'
                        '  Option "TearFree" "true"\n  Option "TripleBuffer" "false"\nEndSection\n')
        log("old Intel graphics: Intel SNA driver configured")
    elif xorg.exists():
        xorg.unlink(); log("removed old-Intel X driver config (not needed on this computer)")
    tlp = r / "etc/tlp.d/60-navin-oldlaptop.conf"
    if q.get("sata_alpm") == "max_performance":
        tlp.parent.mkdir(parents=True, exist_ok=True)
        tlp.write_text("# NAVIN 2.0: older laptop - no SATA link power saving (stops disk freezes), quiet audio, no USB input autosuspend\n"
                       "SATA_LINKPWR_ON_AC=\"max_performance\"\nSATA_LINKPWR_ON_BAT=\"max_performance\"\n"
                       "AHCI_RUNTIME_PM_ON_AC=on\nAHCI_RUNTIME_PM_ON_BAT=on\nSOUND_POWER_SAVE_ON_AC=0\nSOUND_POWER_SAVE_ON_BAT=0\n"
                       "USB_EXCLUDE_BTUSB=1\nUSB_EXCLUDE_PHONE=1\n"
                       + ("" if q.get("battery_turbo", True) else "CPU_BOOST_ON_BAT=0\n"))
    elif tlp.exists():
        tlp.unlink()
    live = (r / "run/live").exists()
    cfg = r / "etc/default/grub.d/90-navin-quirks.cfg"
    off = (r / "etc/navin/quirks-off").exists()
    text = "" if off else grub_quirks_cfg(q.get("kernel_params", []))
    if not live and (r / "etc/default/grub.d").is_dir():
        old = cfg.read_text() if cfg.exists() else ""
        if text != old:
            if text:
                cfg.write_text(text)
            elif cfg.exists():
                cfg.unlink()
            if root == "/":
                rc = subprocess.run(["update-grub"], capture_output=True, text=True)
                log("boot menu quirks " + ("updated" if rc.returncode == 0 else "update failed: " + rc.stderr.strip()[-200:]))


if __name__ == "__main__":
    print(json.dumps(collect(), indent=1))
