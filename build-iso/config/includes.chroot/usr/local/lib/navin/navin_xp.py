"""NAVIN XP 3.1 pure logic (no GTK, unit-tested in build-iso/tests/test_xp31.py).

Task Manager (/proc parsing, safe End task, XDG startup toggles), NAVIN Defender (ufw/clamscan
parsing, whitelisted root actions), Battery & Thermal (sysfs battery health, temperatures, fan RPM),
Backup & Restore (Timeshift plans), adaptive glass tiers (picom blur by RAM) and the en/hi texts
of these apps. GUIs and the pkexec helper only call into this module."""
import os
import re

# ---------------------------------------------------------------- Task Manager
def cpu_times(stat_text):
    """'/proc/stat' -> (busy, total) jiffies of the 'cpu' line."""
    for line in stat_text.splitlines():
        if line.startswith("cpu "):
            v = [int(x) for x in line.split()[1:]]
            idle = v[3] + (v[4] if len(v) > 4 else 0)
            total = sum(v[:8])
            return total - idle, total
    raise ValueError("no cpu line")


def cpu_percent(prev, cur):
    """Two cpu_times() samples -> CPU use in percent (0..100)."""
    busy, total = cur[0] - prev[0], cur[1] - prev[1]
    return 0.0 if total <= 0 else round(max(0.0, min(100.0, busy * 100.0 / total)), 1)


def parse_meminfo(text):
    """'/proc/meminfo' -> dict in MiB: total, available, used, percent, swap_total, swap_used."""
    kb = {}
    for line in text.splitlines():
        m = re.match(r"(\w+):\s+(\d+)", line)
        if m:
            kb[m[1]] = int(m[2])
    total = kb.get("MemTotal", 0)
    avail = kb.get("MemAvailable", kb.get("MemFree", 0))
    st, sf = kb.get("SwapTotal", 0), kb.get("SwapFree", 0)
    used = total - avail
    return {"total": total // 1024, "available": avail // 1024, "used": used // 1024,
            "percent": round(used * 100.0 / total, 1) if total else 0.0,
            "swap_total": st // 1024, "swap_used": (st - sf) // 1024}


def net_bytes(netdev_text):
    """'/proc/net/dev' -> (rx, tx) bytes summed over all interfaces except lo."""
    rx = tx = 0
    for line in netdev_text.splitlines():
        if ":" not in line:
            continue
        name, data = line.split(":", 1)
        if name.strip() == "lo":
            continue
        f = data.split()
        if len(f) >= 9:
            rx += int(f[0]); tx += int(f[8])
    return rx, tx


_WHOLE_DISK = re.compile(r"^(sd[a-z]+|vd[a-z]+|hd[a-z]+|nvme\d+n\d+|mmcblk\d+)$")


def disk_bytes(diskstats_text):
    """'/proc/diskstats' -> (read, written) bytes of whole disks (partitions are not counted twice)."""
    r = w = 0
    for line in diskstats_text.splitlines():
        f = line.split()
        if len(f) >= 10 and _WHOLE_DISK.match(f[2]):
            r += int(f[5]) * 512; w += int(f[9]) * 512
    return r, w


def rate(prev, cur, seconds):
    """Counter samples -> bytes per second (never negative, e.g. after an interface reset)."""
    return 0 if seconds <= 0 else max(0, int((cur - prev) / seconds))


def human_bytes(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return (f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}")
        n /= 1024.0


def parse_pid_stat(text):
    """'/proc/<pid>/stat' -> dict pid, name, state, ppid, ticks (utime+stime), rss_pages.
    The name may contain spaces and ')' so it is cut at the LAST ')'."""
    head, _, rest = text.rpartition(")")
    pid, _, name = head.partition(" (")
    f = rest.split()
    return {"pid": int(pid), "name": name, "state": f[0], "ppid": int(f[1]),
            "ticks": int(f[11]) + int(f[12]), "rss_pages": int(f[21])}


# Ending these freezes or logs out the desktop: Task Manager refuses, the user is told why.
PROTECTED = {"systemd", "Xorg", "X", "lightdm", "xfwm4", "xfce4-session", "xfce4-panel", "xfdesktop",
             "dbus-daemon", "dbus-broker", "pipewire", "wireplumber", "NetworkManager", "polkitd",
             "systemd-logind", "systemd-journald", "udevd", "systemd-udevd", "navin-task-manager"}


def kill_allowed(proc, my_uid, proc_uid, my_pid=None):
    """(allowed, reason). Only the user's own, non-critical, non-kernel processes can be ended."""
    if proc["pid"] <= 1 or proc["pid"] == 2 or proc["ppid"] == 2:
        return False, "system/kernel process"
    if my_pid is not None and proc["pid"] == my_pid:
        return False, "this is Task Manager itself"
    if proc_uid != my_uid:
        return False, "belongs to another user (root/system)"
    if proc["name"] in PROTECTED:
        return False, "ending it would freeze or close the desktop"
    return True, ""


def process_rows(samples_prev, samples_cur, total_delta, page_kb=4):
    """{pid: stat} twice + total CPU jiffies between them -> rows sorted by CPU then RAM."""
    rows = []
    for pid, cur in samples_cur.items():
        prev = samples_prev.get(pid)
        d = cur["ticks"] - prev["ticks"] if prev else 0
        cpu = round(max(0.0, d * 100.0 / total_delta), 1) if total_delta > 0 else 0.0
        rows.append({"pid": pid, "name": cur["name"], "cpu": cpu, "ram_mb": round(cur["rss_pages"] * page_kb / 1024.0, 1)})
    rows.sort(key=lambda r: (-r["cpu"], -r["ram_mb"], r["pid"]))
    return rows


def parse_desktop_entry(text):
    """Key=value pairs of the [Desktop Entry] group (localized keys kept as-is)."""
    out, group = {}, None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("["):
            group = line
        elif group == "[Desktop Entry]" and "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            out.setdefault(k.strip(), v.strip())
    return out


def autostart_enabled(entry, desktop="XFCE"):
    if entry.get("Hidden", "").lower() == "true":
        return False
    if entry.get("X-GNOME-Autostart-enabled", "true").lower() == "false":
        return False
    only = [x for x in entry.get("OnlyShowIn", "").split(";") if x]
    if only and desktop not in only:
        return False
    if desktop in [x for x in entry.get("NotShowIn", "").split(";") if x]:
        return False
    return True


def startup_apps(system, user, desktop="XFCE"):
    """system/user: {file_name: entry}. A user file overrides the system file (XDG autostart spec).
    -> sorted rows file, name, command, enabled."""
    merged = dict(system); merged.update(user)
    rows = []
    for fn, e in merged.items():
        only = [x for x in e.get("OnlyShowIn", "").split(";") if x]
        if only and desktop not in only and fn not in user:
            continue  # never shown on this desktop, nothing to toggle
        rows.append({"file": fn, "name": e.get("Name", fn), "command": e.get("Exec", ""), "enabled": autostart_enabled(e, desktop)})
    return sorted(rows, key=lambda r: r["name"].lower())


def autostart_override(system_text, enabled):
    """Text of the user's ~/.config/autostart/<same file> that turns a startup app on/off."""
    lines = [l for l in (system_text or "[Desktop Entry]\nType=Application\n").splitlines()
             if not re.match(r"\s*(Hidden|X-GNOME-Autostart-enabled)\s*=", l)]
    i = next((n for n, l in enumerate(lines) if l.strip() == "[Desktop Entry]"), None)
    flag = ["Hidden=" + ("false" if enabled else "true"), "X-GNOME-Autostart-enabled=" + ("true" if enabled else "false")]
    if i is None:
        lines = ["[Desktop Entry]"] + flag + lines
    else:
        lines[i + 1:i + 1] = flag
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- NAVIN Defender
def parse_ufw_status(text):
    """'ufw status verbose' -> active, incoming, outgoing, rules."""
    active = bool(re.search(r"^Status:\s*active", text, re.M))
    d = re.search(r"Default:\s*(\w+)\s*\(incoming\),\s*(\w+)\s*\(outgoing\)", text)
    rules, in_rules = [], False
    for line in text.splitlines():
        if line.startswith("--"):
            in_rules = True; continue
        if in_rules and line.strip():
            rules.append(re.sub(r"\s{2,}", "  ", line.strip()))
    return {"active": active, "incoming": d[1] if d else None, "outgoing": d[2] if d else None, "rules": rules}


DEFENDER_ACTIONS = {
    "fw-status": [["ufw", "status", "verbose"]],
    "fw-enable": [["ufw", "default", "deny", "incoming"], ["ufw", "default", "allow", "outgoing"], ["ufw", "--force", "enable"], ["ufw", "status", "verbose"]],
    "fw-disable": [["ufw", "disable"], ["ufw", "status", "verbose"]],
    "sig-update": [["freshclam", "--stdout"]],
}


def defender_plan(action):
    """Whitelisted root commands of NAVIN Defender. Anything else -> ValueError."""
    if action not in DEFENDER_ACTIONS:
        raise ValueError("unknown action: " + str(action))
    return [list(c) for c in DEFENDER_ACTIONS[action]]


def clamscan_command(paths, remove=False):
    """User-level ClamAV scan of real folders (no root, never deletes unless asked)."""
    paths = [p for p in paths if p and os.path.isabs(p) and ".." not in p.split("/")]
    if not paths:
        raise ValueError("no folder to scan")
    cmd = ["clamscan", "-r", "-i", "--stdout", "--max-filesize=200M", "--max-scansize=400M"]
    if remove:
        cmd.append("--move=" + os.path.expanduser("~/.local/share/navin/quarantine"))
    return cmd + ["--"] + paths


def parse_clamscan(text):
    """clamscan output -> infected [(path, signature)], scanned files, infected count, signatures loaded, ok."""
    infected = [(m[1], m[2]) for m in re.finditer(r"^(.+): (\S+) FOUND$", text, re.M)]
    def num(label):
        m = re.search(r"^" + label + r":\s*(\d+)", text, re.M)
        return int(m[1]) if m else None
    count = num("Infected files")
    return {"infected": infected, "scanned": num("Scanned files"), "infected_count": count if count is not None else len(infected),
            "signatures": num("Known viruses"), "finished": "SCAN SUMMARY" in text}


def removable_mounts(proc_mounts_text):
    """'/proc/mounts' -> mount points of USB drives/SD cards the desktop mounted (/media, /run/media)."""
    out = []
    for line in proc_mounts_text.splitlines():
        f = line.split()
        if len(f) >= 3 and f[0].startswith("/dev/") and re.match(r"^/(media|run/media)/", f[1]):
            out.append(f[1].replace("\\040", " "))
    return out


# ---------------------------------------------------------------- Battery & Thermal
def battery_health(props):
    """Values of /sys/class/power_supply/BAT*/ files -> design/full (Wh or mAh), wear %, cycles, label.
    Missing values stay None (many old batteries do not report cycle_count) - nothing is guessed."""
    def val(k):
        try:
            return int(str(props[k]).strip())
        except (KeyError, ValueError):
            return None
    full, design, now, unit = val("energy_full"), val("energy_full_design"), val("energy_now"), "Wh"
    if full is None or design is None:
        full, design, now, unit = val("charge_full"), val("charge_full_design"), val("charge_now"), "mAh"
    cycles = val("cycle_count")
    cycles = cycles if cycles and cycles > 0 else None
    wear = health = None
    if full and design:
        health = round(min(100.0, full * 100.0 / design), 1)
        wear = round(100.0 - health, 1)
    scale = 1e6 if unit == "Wh" else 1e3
    label = None if health is None else ("Good" if health >= 80 else "Fair" if health >= 60 else "Replace soon")
    return {"unit": unit, "design": round(design / scale, 1) if design else None, "full": round(full / scale, 1) if full else None,
            "now": round(now / scale, 1) if now else None, "health": health, "wear": wear, "cycles": cycles,
            "status": str(props.get("status", "")).strip() or None, "capacity": val("capacity"), "label": label}


def temperatures(zones):
    """[(type, millidegree text)] from thermal_zone*/ or hwmon temp*_input -> [(name, celsius)] (bad values dropped)."""
    out = []
    for name, raw in zones:
        try:
            c = int(str(raw).strip()) / 1000.0
        except ValueError:
            continue
        if -40 < c < 150:
            out.append((name, round(c, 1)))
    return out


def fan_rpms(fans):
    """[(label, fan*_input text)] -> [(label, rpm)]; 0 rpm is kept (fan really stopped)."""
    out = []
    for name, raw in fans:
        try:
            out.append((name, int(str(raw).strip())))
        except ValueError:
            pass
    return out


FAN_PROFILES = ("silent", "balanced", "cooling", "auto")  # = navin-fan commands (real fan/EC/CPU-limit control)


def fan_profile_command(profile):
    if profile not in FAN_PROFILES:
        raise ValueError("unknown fan profile")
    return ["pkexec", "/usr/local/lib/navin/navin-fan", profile]


# ---------------------------------------------------------------- Backup & Restore (Timeshift)
_DEV = re.compile(r"^/dev/(sd[a-z]+\d+|nvme\d+n\d+p\d+|mmcblk\d+p\d+|vd[a-z]+\d+)$")


def backup_plan(action, device=None, comment=None):
    """Whitelisted Timeshift commands (run by the root helper)."""
    if action == "list":
        cmd = ["timeshift", "--list", "--scripted"]
    elif action == "create":
        note = re.sub(r"[^\w .:-]", "", comment or "NAVIN restore point")[:60] or "NAVIN restore point"
        cmd = ["timeshift", "--create", "--scripted", "--comments", note, "--tags", "O"]
    elif action == "devices":
        cmd = ["timeshift", "--list-devices", "--scripted"]
    else:
        raise ValueError("unknown backup action")
    if device is not None:
        if not _DEV.match(device):
            raise ValueError("not a partition: " + str(device))
        cmd += ["--snapshot-device", device]
    return cmd


def parse_timeshift_list(text):
    """'timeshift --list' -> [{name, tags, comment}] newest first."""
    rows = []
    for line in text.splitlines():
        m = re.match(r"^\s*\d+\s+>\s+(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})\s+(\S*)\s*(.*)$", line)
        if m:
            rows.append({"name": m[1], "tags": m[2], "comment": m[3].strip()})
    return sorted(rows, key=lambda r: r["name"], reverse=True)


def parse_timeshift_devices(text):
    """'timeshift --list-devices' -> [{device, size, type, label}]."""
    rows = []
    for line in text.splitlines():
        m = re.match(r"^\s*\d+\s+>\s+(/dev/\S+)\s+([\d.]+\s*[KMGT]?B)\s+(\S+)\s*(.*)$", line)
        if m:
            rows.append({"device": m[1], "size": m[2], "type": m[3], "label": m[4].strip()})
    return rows


# ---------------------------------------------------------------- Adaptive glass tiers
GLASS_TIERS = (  # (max RAM MiB, name, blur strength for picom dual_kawase)
    (3 * 1024, "Ultra Light", 2),   # 2 GB class: ~5-8 px blur
    (7 * 1024, "Balanced", 5),      # 4 GB class: ~15-20 px blur
    (None, "Premium Glass", 8),     # 8 GB+: ~25-30 px blur
)


def glass_tier(ram_mib, forced=None):
    """RAM -> (tier name, blur strength). forced='Ultra Light'|'Balanced'|'Premium Glass' wins."""
    for limit, name, strength in GLASS_TIERS:
        if forced == name:
            return name, strength
    for limit, name, strength in GLASS_TIERS:
        if limit is None or ram_mib <= limit:
            return name, strength


def glass_picom_conf(base_text, tier):
    """picom.conf with the tier's real background blur (panel, menus, notifications, terminal)."""
    name, strength = glass_tier(0, tier) if isinstance(tier, str) else tier
    body = re.sub(r"(?ms)^# NAVIN XP glass begin.*?# NAVIN XP glass end\n?", "", base_text).rstrip() + "\n"
    return body + (
        "# NAVIN XP glass begin (tier: %s)\n"
        "blur-method = \"dual_kawase\";\n"
        "blur-strength = %d;\n"
        "blur-background-fixed = false;\n"
        "blur-background-exclude = [ \"window_type = 'desktop'\", \"_GTK_FRAME_EXTENTS@:c\", \"class_g = 'Plank'\" ];\n"
        "# NAVIN XP glass end\n") % (name, strength)


# ---------------------------------------------------------------- English / Hindi texts
TEXT = {
    "en": {
        "tm_title": "NAVIN Task Manager", "performance": "Performance", "processes": "Processes", "startup": "Startup apps",
        "cpu": "CPU", "memory": "Memory", "disk": "Disk", "network": "Network", "end_task": "End task",
        "force_end": "Force end", "refused": "Cannot end this process", "on": "On", "off": "Off",
        "def_title": "NAVIN Defender", "firewall": "Firewall", "fw_on": "Firewall is ON (incoming blocked)",
        "fw_off": "Firewall is OFF", "turn_on": "Turn on", "turn_off": "Turn off", "scan": "Virus scan",
        "quick_scan": "Scan Downloads", "home_scan": "Scan home folder", "usb_scan": "Scan USB drive",
        "update_sigs": "Update virus definitions", "no_threats": "No threats found", "threats": "Threats found",
        "no_clam": "ClamAV is not installed - install 'clamav' from App Store", "no_usb": "No USB drive is mounted", "no_sigs": "No virus definitions yet - press 'Update virus definitions' first (needs internet)",
        "bat_title": "Battery & Thermal", "battery": "Battery", "health": "Health", "wear": "Wear", "cycles": "Cycles",
        "temps": "Temperatures", "fans": "Fans", "fan_profile": "Fan profile", "no_battery": "No battery found (desktop PC or battery removed)",
        "not_reported": "not reported by this battery", "bk_title": "Backup & Restore", "create": "Create restore point",
        "restore": "Restore...", "snapshots": "Restore points", "target": "Save to", "live_only": "Backups work after NAVIN XP is installed to a disk",
        "no_timeshift": "Timeshift is not installed - install 'timeshift' from App Store", "working": "Working...", "done": "Done", "failed": "Failed",
        "glass": "Glass effect", "language": "Language",
    },
    "hi": {
        "tm_title": "NAVIN टास्क मैनेजर", "performance": "परफ़ॉर्मेंस", "processes": "प्रोसेस", "startup": "स्टार्टअप ऐप्स",
        "cpu": "CPU", "memory": "मेमोरी", "disk": "डिस्क", "network": "नेटवर्क", "end_task": "टास्क बंद करें",
        "force_end": "ज़बरदस्ती बंद करें", "refused": "यह प्रोसेस बंद नहीं किया जा सकता", "on": "चालू", "off": "बंद",
        "def_title": "NAVIN डिफ़ेंडर", "firewall": "फ़ायरवॉल", "fw_on": "फ़ायरवॉल चालू है (बाहर से आने वाले कनेक्शन बंद)",
        "fw_off": "फ़ायरवॉल बंद है", "turn_on": "चालू करें", "turn_off": "बंद करें", "scan": "वायरस स्कैन",
        "quick_scan": "डाउनलोड्स स्कैन करें", "home_scan": "होम फ़ोल्डर स्कैन करें", "usb_scan": "USB ड्राइव स्कैन करें",
        "update_sigs": "वायरस डेटाबेस अपडेट करें", "no_threats": "कोई ख़तरा नहीं मिला", "threats": "ख़तरे मिले",
        "no_clam": "ClamAV इंस्टॉल नहीं है - App Store से 'clamav' इंस्टॉल करें", "no_usb": "कोई USB ड्राइव लगी नहीं है", "no_sigs": "वायरस डेटाबेस अभी नहीं है - पहले 'वायरस डेटाबेस अपडेट करें' दबाएँ (इंटरनेट चाहिए)",
        "bat_title": "बैटरी और तापमान", "battery": "बैटरी", "health": "सेहत", "wear": "घिसाव", "cycles": "चार्ज साइकिल",
        "temps": "तापमान", "fans": "पंखे", "fan_profile": "पंखा प्रोफ़ाइल", "no_battery": "बैटरी नहीं मिली (डेस्कटॉप PC या बैटरी निकली हुई)",
        "not_reported": "यह बैटरी नहीं बताती", "bk_title": "बैकअप और रिस्टोर", "create": "रिस्टोर पॉइंट बनाएँ",
        "restore": "रिस्टोर करें...", "snapshots": "रिस्टोर पॉइंट", "target": "यहाँ सेव करें", "live_only": "बैकअप NAVIN XP को डिस्क पर इंस्टॉल करने के बाद काम करता है",
        "no_timeshift": "Timeshift इंस्टॉल नहीं है - App Store से 'timeshift' इंस्टॉल करें", "working": "काम चल रहा है...", "done": "पूरा हुआ", "failed": "नहीं हो पाया",
        "glass": "ग्लास इफ़ेक्ट", "language": "भाषा",
    },
}


def lang(env=None, saved=None):
    """Saved NAVIN choice (~/.config/navin/lang) first, then LANG/LANGUAGE; default English."""
    env = os.environ if env is None else env
    if saved and saved.strip() in TEXT:
        return saved.strip()
    for k in ("LANGUAGE", "LC_ALL", "LANG"):
        if (env.get(k) or "").startswith("hi"):
            return "hi"
    return "en"


def t(key, language="en"):
    return TEXT.get(language, TEXT["en"]).get(key) or TEXT["en"][key]
