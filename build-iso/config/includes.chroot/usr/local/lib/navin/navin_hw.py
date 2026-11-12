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
I8042_SAMSUNG = ("i8042.nomux=1", "i8042.reset=1", "i8042.nopnp=1", "i8042.noloop=1")
# NAVIN 2.2.1: legacy-BIOS boots (where Samsung RV411-class laptops start) also probe the PS/2 touchpad
# port directly instead of trusting the BIOS ACPI list, which on these laptops can leave the port out.
I8042_BIOS_EXTRA = ("i8042.nopnp=1", "i8042.noloop=1")
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
        q["notes"].append("Samsung laptop: touchpad controller fix (i8042 nomux/reset/nopnp/noloop) is used. If the cursor still does not move, press Fn+F5 once — Samsung turns the touchpad off in hardware with that key.")
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


# ---------------- NAVIN 2.2.1: touchpad diagnosis + repair plan, touchpad settings, fan diagnosis ----------------
# Everything here is pure (unit-tested in tests/test_v221.py). navin-touchpad-repair.sh collects the real
# data (/proc/bus/input/devices, /sys/bus/serio, kernel log, /proc/modules, DMI, ACPI ids, cmdline) and only
# runs actions from REPAIR_ACTIONS; every action is verified by a fresh scan before success is reported.

REPAIR_ACTIONS = ("load-modules", "aux-reconnect", "psmouse-reload", "psmouse-fallback", "i2c-reload", "boot-fix")

KERNEL_LOG_ISSUES = (
    ("lost_sync", r"psmouse serio\d+: .*(lost synchroni[sz]ation|issuing reconnect request)",
     "The touchpad loses contact with the driver (lost sync / reconnects).", "Touchpad controller timing problem (common on Samsung/old laptops).",
     "Use the i8042 controller fix (nomux/reset) and restart."),
    ("elantech_fail", r"elantech: .*(fail|unknown|error|timeout|not supported)",
     "ELAN (Elantech) touchpad was found but its driver could not start.", "The ELAN chip did not answer the driver's setup commands.",
     "Reload psmouse; if it fails again NAVIN uses the basic PS/2 mode (move, click, tap, wheel)."),
    ("synaptics_fail", r"synaptics: .*(fail|unable|error|timeout)",
     "Synaptics touchpad was found but its driver could not start.", "The Synaptics chip did not answer the driver's setup commands.",
     "Reload psmouse; if it fails again NAVIN uses the basic PS/2 mode."),
    ("alps_fail", r"alps: .*(fail|unknown|error|timeout)",
     "ALPS touchpad was found but its driver could not start.", "The ALPS chip did not answer the driver's setup commands.",
     "Reload psmouse; if it fails again NAVIN uses the basic PS/2 mode."),
    ("smbus_fail", r"(rmi4_smbus|rmi4_f\d+|psmouse).*(smbus|intertouch).*(fail|error)",
     "SMBus (InterTouch) mode of the touchpad failed.", "The fast SMBus link is not supported on this laptop.",
     "NAVIN never forces SMBus; reload psmouse so the PS/2 link is used."),
    ("i8042_no_controller", r"i8042: (PNP: No PS/2 controller found|No controller found|Can't read CTR)",
     "The keyboard/touchpad (i8042) controller was not found.", "The BIOS ACPI table did not list the PS/2 controller.",
     "Boot with i8042.nopnp=1 so Linux checks the controller directly."),
    ("i8042_kbd_only", r"i8042: PNP: PS/2 Controller \[[^\]]+\] at 0x60,0x64 irq 1\s*$",
     "BIOS ACPI reports only the keyboard port, not the touchpad port.", "Samsung RV411-class BIOS bug: the touchpad (AUX) port is missing from the ACPI list.",
     "Boot with i8042.nopnp=1 i8042.noloop=1 so Linux probes the touchpad port directly."),
    ("i2c_hid_fail", r"i2c_hid(_acpi)? .*(failed|error|unexpected|can't|incomplete report)",
     "The I2C touchpad did not answer.", "I2C-HID driver could not talk to the touchpad.", "Reload i2c_hid_acpi and hid_multitouch."),
    ("firmware_missing", r"(Direct firmware load for \S+ failed|firmware: failed to load \S+)",
     "A driver could not find its firmware file.", "Firmware package missing for a device.", "Install firmware-misc-nonfree / firmware-linux-nonfree."),
    ("acpi_error", r"ACPI (BIOS )?Error",
     "The BIOS ACPI tables report errors.", "BIOS bug (usually harmless; can affect hot keys or fan).", "Update the BIOS if the maker offers an update."),
)


def kernel_log_issues(text):
    """Kernel log -> {issue_key: [matching lines]} (first 3 lines each)."""
    found = {}
    for line in text.splitlines():
        for key, rx, *_ in KERNEL_LOG_ISSUES:
            if re.search(rx, line, re.I):
                found.setdefault(key, [])
                if len(found[key]) < 3:
                    found[key].append(line.strip()[-200:])
    return found


def parse_serio(entries):
    """entries: [{'port': 'serio1', 'description': 'i8042 AUX port', 'driver': 'psmouse'}] -> AUX ports only."""
    return [e for e in entries if "AUX" in (e.get("description") or "").upper()]


def is_internal_pointer(dev):
    """A pointer on the built-in PS/2 AUX port (isa0060/serio1+) that the kernel did not name as a touchpad,
    e.g. 'ImPS/2 Generic Wheel Mouse' when the vendor driver failed. It is the laptop touchpad in basic mode."""
    return bool(re.search(r"isa0060/serio[1-9]", dev.get("phys", ""))) and any(h.startswith("mouse") for h in dev.get("handlers", [])) and not is_touchpad(dev)


def touchpad_driver(dev, aux_driver=""):
    bus = BUS.get(dev["bus"], dev["bus"])
    if bus == "PS/2":
        return "psmouse (" + ("native " + touchpad_vendor(dev) if is_touchpad(dev) else "basic PS/2 mode") + ")"
    if bus == "RMI":
        return "rmi4_smbus (SMBus/InterTouch)"
    if bus in ("I2C", "USB"):
        return "hid_multitouch (i2c_hid_acpi)" if bus == "I2C" else "hid_multitouch (usbhid)"
    return aux_driver or "unknown"


def _p(problem, cause, fix, action=None):
    return {"problem": problem, "cause": cause, "fix": fix, "action": action}


def touchpad_diagnose(devices, aux_ports, kernel_log, loaded_modules, dmi, acpi_ids, cmdline, live=False, uefi=False,
                      laptop=True, saved_fallback="", xinput_disabled=False):
    """Real touchpad state -> {"state", "summary", "devices", "problems", "actions", "kernel_params"}.

    state: ok | basic | disabled | missing-port | no-port | i2c-missing | not-laptop
    actions: ordered subset of REPAIR_ACTIONS, only those that are safe for this exact state."""
    pads = [describe_touchpad(d) for d in devices if is_touchpad(d)]
    basic = [d for d in devices if is_internal_pointer(d)]
    for d in basic:
        pads.append({**describe_touchpad(d), "vendor": "Generic PS/2 (basic mode)", "protocol": "PS/2 basic"})
    for p, d in zip(pads, [d for d in devices if is_touchpad(d)] + basic):
        p["driver"] = touchpad_driver(d, aux_ports[0].get("driver", "") if aux_ports else "")
        p["phys"], p["id"] = d.get("phys", ""), f"{d.get('vendor', '')}:{d.get('product', '')}"
    issues = kernel_log_issues(kernel_log)
    args = set(cmdline.split())
    samsung = is_samsung(dmi)
    model = ((dmi.get("sys_vendor") or "") + " " + (dmi.get("product_name") or "")).strip()
    rv411 = samsung and "RV411" in model.upper().replace(" ", "")
    hid_i2c = any(a.upper() in ("PNP0C50", "ACPI0C50", "MSFT0001") for a in acpi_ids)
    problems, actions, params = [], [], []
    native = [p for p in pads if p["protocol"] != "PS/2 basic"]
    if native:
        state = "disabled" if xinput_disabled else "ok"
        summary = f"Touchpad found: {native[0]['name']} ({native[0]['vendor']}, {native[0]['bus']}, driver {native[0]['driver']})."
        if xinput_disabled:
            problems.append(_p("The touchpad is switched off in NAVIN.", "It was turned off (Touchpad toggle key or setting).", "Switch it on in Touchpad settings."))
    elif basic:
        state = "basic"
        summary = f"Touchpad works in basic PS/2 mode ({basic[0]['name']}): move, click, tap and wheel; no two-finger gestures."
        vendor_fail = [k for k in ("elantech_fail", "synaptics_fail", "alps_fail") if k in issues]
        problems.append(_p("The touchpad maker's driver did not start.",
                           ("Kernel log: " + issues[vendor_fail[0]][0]) if vendor_fail else (f"Saved fallback: {saved_fallback}" if saved_fallback else "The touchpad answered only basic PS/2 commands."),
                           "Basic mode is used so the touchpad still works." + (" Undo the saved fallback to try the native driver again." if saved_fallback else "")))
    elif not laptop and not aux_ports:
        state, summary = "not-laptop", "No touchpad: this computer is not a laptop (USB mouse/keyboard are not touched)."
    elif hid_i2c:
        state, summary = "i2c-missing", "BIOS lists an I2C touchpad, but no touchpad device is running."
        missing = [m for m in ("i2c_designware_platform", "i2c_hid_acpi", "hid_multitouch") if m not in loaded_modules]
        problems.append(_p("I2C touchpad is not running.", "Driver modules missing: " + ", ".join(missing) if missing else "Driver loaded but the device did not answer.",
                           "Load/reload the I2C-HID touchpad drivers.", "load-modules" if missing else "i2c-reload"))
        actions += ["load-modules"] if missing else []
        actions.append("i2c-reload")
    elif aux_ports:
        state, summary = "missing-port", "The PS/2 touchpad port exists, but no touchpad answered on it."
        problems.append(_p("Touchpad not detected on the PS/2 port.", "The touchpad did not answer at boot (controller timing or a failed vendor driver).",
                           "Reset the port, reload psmouse, then try the basic PS/2 modes.", "aux-reconnect"))
        if "psmouse" not in loaded_modules:
            actions.append("load-modules")
        actions += ["aux-reconnect", "psmouse-reload", "psmouse-fallback"]
    else:
        state = "no-port"
        have = all(p in args for p in I8042_BIOS_EXTRA)
        if not have:
            summary = "Linux did not get a touchpad (PS/2 AUX) port from the BIOS."
            problems.append(_p("No touchpad port.", "The BIOS ACPI table does not list the touchpad port (known Samsung RV411-class BIOS behaviour)" +
                               (": " + issues["i8042_kbd_only"][0] if "i8042_kbd_only" in issues else "."),
                               "Start with i8042.nopnp=1 i8042.noloop=1 (Linux probes the port directly). " +
                               ("Live Mode: start from the legacy-BIOS boot menu (it has this option) or press e/Tab and add it." if live else "NAVIN writes it to the boot menu; restart once."),
                               None if live else "boot-fix"))
            params = list(I8042_BIOS_EXTRA)
            if not live:
                actions.append("boot-fix")
        else:
            summary = "No touchpad port even with direct probing (i8042.nopnp)."
            problems.append(_p("The touchpad is not visible to the computer.",
                               "Hardware level: the touchpad is disabled in BIOS setup, switched off by the firmware Fn key, or its cable is disconnected/faulty.",
                               "Check BIOS setup (Internal pointing device = Enabled), press the touchpad Fn key once (Samsung: Fn+F5), then restart. A USB mouse keeps working."))
    for key, rx, problem, cause, fix in KERNEL_LOG_ISSUES:
        if key in issues and not (state in ("ok", "basic") and key in ("i8042_kbd_only", "i8042_no_controller")):
            if not any(p["cause"].endswith(issues[key][0]) for p in problems):
                problems.append(_p(problem, cause + " Log: " + issues[key][0], fix))
    if samsung and state not in ("ok", "not-laptop"):
        problems.append(_p("Samsung touchpad key.", "Samsung laptops can switch the touchpad off with Fn+F5 (some models keep that state after restart).",
                           "Press Fn+F5 once, wait 3 seconds, then run Auto Detect & Repair again."))
    return {"state": state, "summary": summary, "devices": pads, "problems": problems,
            "actions": [a for i, a in enumerate(actions) if a in REPAIR_ACTIONS and a not in actions[:i]],
            "kernel_params": params, "samsung": samsung, "rv411": rv411, "model": model, "log_issues": sorted(issues)}


TOUCHPAD_DEFAULTS = {"enabled": "on", "speed": "0.3", "accel": "adaptive", "tap": "on", "drag": "on", "natural": "off",
                     "scrollmethod": "twofinger", "click": "areas", "dwt": "off", "middle": "off", "lefthanded": "off", "scroll": "15"}


def parse_list_props(text):
    """`xinput list-props ID` -> {name: [values]}."""
    out = {}
    for line in text.splitlines():
        m = re.match(r"\s*(.+?) \(\d+\):\s*(.*)$", line)
        if m:
            out[m.group(1)] = [v.strip() for v in m.group(2).split(",")] if m.group(2) else []
    return out


def _onehot(n, i):
    return ["1" if k == i else "0" for k in range(n)]


def touchpad_props(settings, available):
    """Saved settings + device's real props -> [(prop, [values])] for `xinput set-prop`. Props the device
    does not have are skipped (e.g. edge scrolling on a touchpad that only supports two-finger)."""
    s = {**TOUCHPAD_DEFAULTS, **{k: v for k, v in settings.items() if v not in (None, "")}}
    b = lambda k: "1" if s[k] == "on" else "0"
    out = []
    def put(name, values):
        if name in available:
            out.append((name, values))
    put("Device Enabled", [b("enabled")])
    try:
        speed = max(-1.0, min(1.0, float(s["speed"])))
    except ValueError:
        speed = 0.3
    put("libinput Accel Speed", [f"{speed:.2f}"])
    if "libinput Accel Profile Enabled" in available:
        n = len(available["libinput Accel Profile Enabled"]) or 2
        put("libinput Accel Profile Enabled", _onehot(n, 1 if s["accel"] == "flat" else 0))
    put("libinput Tapping Enabled", [b("tap")])
    put("libinput Tapping Drag Enabled", [b("drag")])
    put("libinput Natural Scrolling Enabled", [b("natural")])
    put("libinput Disable While Typing Enabled", [b("dwt")])
    put("libinput Middle Emulation Enabled", [b("middle")])
    put("libinput Left Handed Enabled", [b("lefthanded")])
    avail_sm = available.get("libinput Scroll Methods Available", [])
    want = {"twofinger": 0, "edge": 1, "none": -1}.get(s["scrollmethod"], 0)
    if "libinput Scroll Method Enabled" in available and (want < 0 or (len(avail_sm) > want and avail_sm[want] == "1") or not avail_sm):
        put("libinput Scroll Method Enabled", _onehot(len(available["libinput Scroll Method Enabled"]) or 3, want))
    avail_cm = available.get("libinput Click Methods Available", [])
    cwant = 1 if s["click"] == "fingers" else 0
    if "libinput Click Method Enabled" in available and (not avail_cm or (len(avail_cm) > cwant and avail_cm[cwant] == "1")):
        put("libinput Click Method Enabled", _onehot(len(available["libinput Click Method Enabled"]) or 2, cwant))
    if s["scroll"].isdigit():
        put("libinput Scrolling Pixel Distance", [str(max(5, min(50, int(s["scroll"]))))])
    return out


PERFORMANCE_PRESETS = {
    "fast": {"accel": "flat", "speed": "0.5", "scroll": "12"},       # fast response: no acceleration curve
    "smooth": {"accel": "adaptive", "speed": "0.2", "scroll": "18"},  # smooth movement
    "optimal": {"accel": "adaptive", "speed": "0.3", "scroll": "15"},  # NAVIN default
}


def fan_diagnose(sensors, cooling, zones, samsung_level, control, loaded_modules, samsung=False, uefi=False):
    """Why the fan may not speed up when hot. sensors = hwmon(); cooling = [{'type','cur','max','writable'}];
    zones = [{'type','temp_c','mode','policy','trips':[{'type','c'}]}]; samsung_level = '' | 'silent' | 'normal' | ...
    -> {"control", "rpm", "max_temp", "problems": [...], "actions": [...]}  actions ⊂ FAN_REPAIR_ACTIONS."""
    temps = [t["c"] for s in sensors for t in s["temps"] if 0 < t["c"] < 130] + [z["temp_c"] for z in zones if 0 < z.get("temp_c", 0) < 130]
    rpm = [f["rpm"] for s in sensors for f in s["fans"]]
    max_t = max(temps) if temps else None
    acpi_fans = [c for c in cooling if c.get("type", "").lower() in ("fan", "acpi fan")]
    problems, actions = [], []
    if samsung_level == "silent":
        problems.append(_p("Samsung silent mode is on.", "The Samsung embedded controller keeps the fan slow in 'silent' performance level.",
                           "Switch Samsung performance level to 'normal' (fan speeds up with heat again).", "samsung-normal"))
        actions.append("samsung-normal")
    if samsung and not uefi and not samsung_level and "samsung_laptop" not in loaded_modules:
        problems.append(_p("Samsung laptop driver is not loaded.", "samsung_laptop gives Linux the Samsung fan/performance mode.",
                           "Load samsung_laptop.", "load-samsung"))
        actions.append("load-samsung")
    for z in zones:
        if z.get("mode") == "disabled":
            problems.append(_p(f"Thermal zone {z.get('type', '?')} is disabled.", "The kernel is not watching this temperature, so ACPI fan steps never start.",
                               "Enable the thermal zone.", "enable-zones"))
            if "enable-zones" not in actions:
                actions.append("enable-zones")
    if any(z.get("trips") and any(t["type"] == "active" for t in z["trips"]) for z in zones) and not acpi_fans:
        problems.append(_p("BIOS has fan steps but no fan device.", "The ACPI 'fan' driver is not loaded.", "Load the fan module.", "load-fan"))
        actions.append("load-fan")
    if not temps:
        problems.append(_p("No temperature reading.", "The CPU temperature driver is not loaded.", "Load coretemp (Intel) / k10temp (AMD).", "load-sensors"))
        actions.append("load-sensors")
    if not rpm and control == "none" and not acpi_fans:
        problems.append(_p("Fan speed cannot be read or set.", "This laptop's BIOS/EC controls the fan by itself and exposes no RPM or speed control to Linux (normal for Samsung RV411-class laptops).",
                           "Nothing to force: NAVIN keeps BIOS automatic control, watches temperature and lowers CPU speed at high heat (Cooling mode)."))
    if max_t is not None and max_t >= 85:
        problems.append(_p(f"Overheating: {max_t:.0f} °C.", "Dust in the fan/heatsink, a blocked air vent or a heavy program.",
                           "Use Cooling mode, keep the vents free, clean the fan. NAVIN forces full cooling at 90 °C.", "cooling"))
    if rpm and max_t is not None and max_t >= 75 and max(rpm) < 1500:
        problems.append(_p("Fan is slow while the CPU is hot.", f"Fan {max(rpm)} RPM at {max_t:.0f} °C.", "Cooling mode raises the fan where hardware allows.", "cooling"))
    return {"control": control, "rpm": rpm, "max_temp": max_t, "acpi_fans": len(acpi_fans), "samsung_level": samsung_level or None,
            "problems": problems, "actions": [a for i, a in enumerate(actions) if a not in actions[:i]]}


FAN_REPAIR_ACTIONS = ("samsung-normal", "load-samsung", "enable-zones", "load-fan", "load-sensors")


def samsung_level_for(mode, choices):
    """NAVIN fan mode -> Samsung performance_level ('silent'/'normal'/'overclock'); never 'overclock'."""
    want = "silent" if mode in ("silent", "quiet") else "normal"
    return want if want in choices else None


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
        if not text and not off and "NAVIN touchpad" in old:
            text = old  # touchpad port fix written by the repair engine / carried over from Live Mode: keep it
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


# ---------------- NAVIN XP: display guard (desktop must start; NAVIN 2.2.1 stopped at the tty1 text screen) ----------------
DISPLAY_LEVELS = ("default", "modesetting", "noaccel", "fbdev", "vesa")
DISPLAY_FALLBACK_CONF = "etc/X11/xorg.conf.d/05-navin-display-fallback.conf"


def xorg_errors(text):
    """Meaningful (EE) lines of /var/log/Xorg.0.log (backtrace noise removed)."""
    out = []
    for line in text.splitlines():
        if "(EE)" not in line:
            continue
        msg = line.split("(EE)", 1)[1].strip()
        if msg and not re.match(r"^\d+:|^Backtrace|^Please consult|^Fatal server error:$|^$", msg) and msg not in out:
            out.append(msg)
    return out[:12]


def display_next_level(level, cmdline="", errors=(), uefi=True):
    """Next fallback after the X server did not start at `level` (pure). None = nothing left to try.

    default -> modesetting (drops the Intel SNA driver) -> noaccel (modesetting without glamor) -> fbdev -> vesa (BIOS only).
    With nomodeset (Safe Graphics) there is no kernel modesetting, so it goes straight to fbdev/vesa."""
    i = DISPLAY_LEVELS.index(level) if level in DISPLAY_LEVELS else 0
    text = " ".join(errors).lower()
    nxt = i + 1
    if "nomodeset" in cmdline.split():
        nxt = max(nxt, DISPLAY_LEVELS.index("fbdev"))
    elif nxt == 1 and "glamor" in text:
        nxt = 2
    if nxt < len(DISPLAY_LEVELS) and DISPLAY_LEVELS[nxt] == "vesa" and uefi:
        return None  # the VESA BIOS driver cannot work on UEFI firmware
    return DISPLAY_LEVELS[nxt] if nxt < len(DISPLAY_LEVELS) else None


def display_fallback_conf(level):
    """Text of 05-navin-display-fallback.conf for a level ('' = remove the file). 05- sorts first, so its
    Device section wins over 10-navin-oldintel.conf / 20-navin-gpu.conf."""
    if level not in DISPLAY_LEVELS or level == "default":
        return ""
    body = {"modesetting": '  Driver "modesetting"\n  Option "AccelMethod" "glamor"\n',
            "noaccel": '  Driver "modesetting"\n  Option "AccelMethod" "none"\n  Option "PageFlip" "off"\n',
            "fbdev": '  Driver "fbdev"\n', "vesa": '  Driver "vesa"\n'}[level]
    return (f"# NAVIN XP display guard: the desktop did not start with the previous driver, using '{level}'.\n"
            f"# Reset: sudo navin-display-guard reset\nSection \"Device\"\n  Identifier \"NAVIN display fallback\"\n{body}EndSection\n")


def boot_hw_summary(cpu_model, mem_kb, gpus, wifi, bluetooth, audio, touchpad):
    """One honest line for the boot splash, built from what the kernel actually found (missing = 'not found')."""
    cpu = re.sub(r"\s+", " ", re.sub(r"\((R|TM)\)|CPU|@.*$", "", cpu_model or "")).strip() or "CPU"
    parts = [cpu, f"{round(mem_kb / 1048576, 1):g} GB RAM" if mem_kb else "RAM ?",
             (GPU_VENDORS.get(gpus[0].get("vendor"), "GPU") + " graphics") if gpus else "graphics not found",
             "Wi-Fi" if wifi else "no Wi-Fi", "Bluetooth" if bluetooth else "no Bluetooth",
             "audio" if audio else "no audio", "touchpad" if touchpad else "no touchpad yet"]
    return " · ".join(parts)
