#!/usr/bin/python3
"""NAVIN 2.2.1 touchpad I/O (no GTK). Reads the real system and applies real libinput properties.
  navin_tp.py diagnose [--json]   touchpad state, driver, problems -> cause -> fix (uses navin_hw.touchpad_diagnose)
  navin_tp.py actions             safe repair actions for the current state, one per line (used by the root repair script)
  navin_tp.py apply [--login]     apply saved settings (~/.config/navin/touchpad.conf) through xinput to the real device
  navin_tp.py info                hardware + driver report (name, vendor, bus, IDs, driver, kernel modules, libinput)
  navin_tp.py fan [--json]        fan/thermal diagnosis (navin_hw.fan_diagnose)
Decisions are pure functions in navin_hw.py; this file only collects data and calls xinput."""
import json, os, pathlib, re, subprocess, sys
sys.path.insert(0, "/usr/local/lib/navin")
import navin_hw as hw

CONF = pathlib.Path.home() / ".config/navin/touchpad.conf"
STATUS = pathlib.Path("/run/navin/touchpad-status.json")
SAVED_FALLBACK = pathlib.Path("/etc/modprobe.d/navin-touchpad-rescue.conf")
INTERNAL = re.compile(r"touchpad|trackpad|glidepoint|synps/2|alpsps/2|elantech|ps/2 generic|imps/2|exps/2|ps/2 logitech", re.I)


def run(args, timeout=8):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def read(p, d=""):
    try:
        return pathlib.Path(p).read_text(errors="replace").strip()
    except OSError:
        return d


def serio_ports():
    out = []
    for s in sorted(pathlib.Path("/sys/bus/serio/devices").glob("serio*")):
        drv = s / "driver"
        out.append({"port": s.name, "description": read(s / "description"),
                    "driver": os.path.basename(os.readlink(drv)) if drv.is_symlink() else "", "protocol": read(s / "protocol")})
    return out


def kernel_log():
    text = run(["journalctl", "-k", "-b", "0", "--no-pager", "-q", "-o", "cat"], 10) or run(["dmesg"], 5)
    return text


def collect_diag():
    devices = hw.parse_input_devices(read("/proc/bus/input/devices"))
    loaded = {l.split()[0] for l in read("/proc/modules").splitlines() if l}
    dmi = {k: read("/sys/class/dmi/id/" + k) for k in ("sys_vendor", "product_name", "product_version", "board_name", "bios_version", "chassis_type")}
    laptop = dmi.get("chassis_type") in ("8", "9", "10", "11", "14", "30", "31", "32")
    acpi = [read(p) for p in pathlib.Path("/sys/bus/acpi/devices").glob("*/hid")]
    log = kernel_log()
    if not log and STATUS.exists():  # normal users may not read the kernel log; reuse the root scan's lines
        try:
            log = "\n".join(json.loads(STATUS.read_text()).get("log_lines", []))
        except ValueError:
            log = ""
    disabled = False
    for i in xinput_ids():
        props = hw.parse_list_props(run(["xinput", "list-props", i]))
        if props.get("Device Enabled") == ["0"]:
            disabled = True
    d = hw.touchpad_diagnose(devices, hw.parse_serio(serio_ports()), log, loaded, dmi, acpi, read("/proc/cmdline"),
                             live=pathlib.Path("/run/live").exists(), uefi=pathlib.Path("/sys/firmware/efi").exists(),
                             laptop=laptop, saved_fallback=read(SAVED_FALLBACK).splitlines()[-1] if SAVED_FALLBACK.exists() else "",
                             xinput_disabled=disabled)
    d["log_lines"] = [l for l in log.splitlines() if re.search(r"i8042|psmouse|serio|elantech|synaptics|alps|i2c_hid|hid-multitouch|rmi4|touchpad", l, re.I)][-40:]
    d["modules"] = sorted(m for m in loaded if m in ("psmouse", "i2c_hid", "i2c_hid_acpi", "hid_multitouch", "hid_generic", "serio_raw", "elan_i2c", "rmi_smbus", "rmi_core", "samsung_laptop"))
    d["serio"] = serio_ports()
    d["cmdline_i8042"] = [a for a in read("/proc/cmdline").split() if a.startswith(("i8042.", "psmouse."))]
    return d


def xinput_ids():
    """xinput ids of the built-in touchpad; the basic-mode PS/2 pointer only when no named touchpad exists."""
    if not os.environ.get("DISPLAY"):
        return []
    lines = [l for l in run(["xinput", "list"]).splitlines() if "slave  pointer" in l or "slave pointer" in l.replace("  ", " ")]
    named = [l for l in lines if re.search(r"touchpad|trackpad|glidepoint", l, re.I)]
    pick = named or [l for l in lines if INTERNAL.search(l) and "TrackPoint" not in l]
    return [m.group(1) for l in pick for m in [re.search(r"id=(\d+)", l)] if m]


def load_conf():
    s = {}
    for line in read(CONF).splitlines():
        if "=" in line:
            k, v = line.split("=", 1); s[k.strip()] = v.strip()
    return s


def apply(login=False):
    s = load_conf()
    if login and s.get("enabled") == "off":  # NAVIN rule: the touchpad is always ON again after restart/login
        s["enabled"] = "on"
        CONF.parent.mkdir(parents=True, exist_ok=True)
        CONF.write_text("".join(f"{k}={v}\n" for k, v in s.items()))
    ids = xinput_ids()
    for i in ids:
        props = hw.parse_list_props(run(["xinput", "list-props", i]))
        for name, values in hw.touchpad_props(s, props):
            subprocess.run(["xinput", "set-prop", i, name, *values], capture_output=True)
    return ids


def info():
    d = collect_diag()
    out = [f"Computer : {d['model'] or 'unknown'}" + ("  (Samsung RV411 profile)" if d["rv411"] else ""), f"State    : {d['state']} — {d['summary']}"]
    for p in d["devices"]:
        out.append(f"Touchpad : {p['name']} · {p['vendor']} · bus {p['bus']} · id {p['id']} · driver {p['driver']} · {p.get('event') or ''}")
    for s in d["serio"]:
        out.append(f"PS/2 port: {s['port']} {s['description']} → driver {s['driver'] or 'none'}")
    out.append("Modules  : " + (", ".join(d["modules"]) or "none of the touchpad drivers"))
    out.append("Boot opts: " + (" ".join(d["cmdline_i8042"]) or "none"))
    li = run(["libinput", "list-devices"], 10)
    for block in li.split("\n\n"):
        if re.search(r"touchpad|Capabilities:\s+pointer", block, re.I) and re.search(INTERNAL, block):
            out.append("libinput : " + " | ".join(l.strip() for l in block.splitlines() if l.split(":")[0].strip() in ("Device", "Kernel", "Capabilities", "Tap-to-click", "Scroll methods", "Click methods", "Disable-w-typing", "Accel profiles")))
    for p in d["problems"]:
        out += [f"Problem  : {p['problem']}", f"  Cause  : {p['cause']}", f"  Fix    : {p['fix']}"]
    return "\n".join(out)


def fan():
    sensors = hw.hwmon()
    cooling = []
    for c in sorted(pathlib.Path("/sys/class/thermal").glob("cooling_device*")):
        cooling.append({"type": read(c / "type"), "cur": read(c / "cur_state"), "max": read(c / "max_state"), "writable": os.access(c / "cur_state", os.W_OK)})
    zones = []
    for z in sorted(pathlib.Path("/sys/class/thermal").glob("thermal_zone*")):
        trips = []
        for t in sorted(z.glob("trip_point_*_type")):
            try:
                trips.append({"type": read(t), "c": int(read(str(t).replace("_type", "_temp"), "0")) / 1000})
            except ValueError:
                pass
        try:
            temp = int(read(z / "temp", "0")) / 1000
        except ValueError:
            temp = 0
        zones.append({"type": read(z / "type"), "temp_c": temp, "mode": read(z / "mode"), "policy": read(z / "policy"), "trips": trips})
    loaded = {l.split()[0] for l in read("/proc/modules").splitlines() if l}
    level = read("/sys/devices/platform/samsung/performance_level")
    control = run(["/usr/local/lib/navin/navin-fan", "capability"]).strip() or "none"
    d = hw.fan_diagnose(sensors, cooling, zones, level, control, loaded, hw.is_samsung({"sys_vendor": read("/sys/class/dmi/id/sys_vendor")}),
                        pathlib.Path("/sys/firmware/efi").exists())
    d.update(sensors=sensors, cooling=cooling, zones=zones)
    return d


if __name__ == "__main__":
    a = sys.argv[1:] or ["info"]
    if a[0] == "diagnose":
        d = collect_diag()
        print(json.dumps(d, indent=1) if "--json" in a else d["state"] + ": " + d["summary"])
    elif a[0] == "actions":
        print("\n".join(collect_diag()["actions"]))
    elif a[0] == "apply":
        ids = apply("--login" in a)
        print("applied to xinput id " + ", ".join(ids) if ids else "no touchpad in X")
        sys.exit(0 if ids else 1)
    elif a[0] == "info":
        print(info())
    elif a[0] == "fan":
        d = fan()
        if "--json" in a:
            print(json.dumps(d, indent=1))
        else:
            print(f"Fan control: {d['control']} · fan RPM: {d['rpm'] or 'not reported'} · hottest: {d['max_temp']} °C · Samsung level: {d['samsung_level'] or 'n/a'}")
            for p in d["problems"]:
                print(f"Problem: {p['problem']}\n  Cause: {p['cause']}\n  Fix  : {p['fix']}")
    else:
        print(__doc__); sys.exit(2)
