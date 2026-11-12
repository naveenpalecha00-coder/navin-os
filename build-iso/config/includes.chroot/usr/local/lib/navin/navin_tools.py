"""NAVIN 2.1 + 2.2 Toolbox logic (pure Python, no GTK, unit-tested in build-iso/tests/test_v21.py and test_v22.py).

Every function here either computes a result directly or builds the exact command line that the
NAVIN Toolbox window runs (ffmpeg, qpdf, ghostscript, shred, qrencode, systemctl, journalctl ...).
Nothing is simulated: if a tool or device is missing the window shows the real error."""
import hashlib
import os
import pathlib
import re
import socket
import struct
import time

TIME_RE = re.compile(r"^\d{1,2}:[0-5]\d:[0-5]\d(\.\d{1,3})?$")
# Never shred or reorganise anything outside the user's own files.
PROTECTED = ("/bin", "/boot", "/dev", "/etc", "/lib", "/lib64", "/proc", "/run", "/sbin", "/sys", "/usr", "/var", "/opt", "/root", "/srv")

CATEGORIES = {
    "Images": {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg", ".heic", ".tif", ".tiff"},
    "Videos": {".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".3gp"},
    "Music": {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac", ".opus"},
    "Documents": {".pdf", ".doc", ".docx", ".odt", ".txt", ".rtf", ".xls", ".xlsx", ".ods", ".ppt", ".pptx", ".odp", ".csv", ".md"},
    "Archives": {".zip", ".rar", ".7z", ".tar", ".gz", ".xz", ".bz2", ".zst"},
    "Programs": {".deb", ".appimage", ".exe", ".msi", ".flatpakref", ".sh"},
}


def human_size(n):
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def safe_user_path(path, home):
    """True only for real paths inside the user's home (or removable media) and not the home itself."""
    p = os.path.realpath(path)
    home = os.path.realpath(home)
    if p == home or any(p == d or p.startswith(d + "/") for d in PROTECTED if not home.startswith(d + "/")):
        return False
    return p.startswith(home + "/") or p.startswith("/media/") or p.startswith("/mnt/")


# ---------------- Files ----------------

def walk_files(root, walker=os.walk, stat=os.stat):
    for d, dirs, files in walker(root):
        dirs[:] = [x for x in dirs if not x.startswith(".")]
        for f in files:
            p = os.path.join(d, f)
            try:
                st = stat(p)
            except OSError:
                continue
            yield p, st.st_size


def large_files(entries, min_bytes=100 * 1024 * 1024, limit=50):
    """entries: (path, size). Biggest first."""
    big = [(s, p) for p, s in entries if s >= min_bytes]
    return [(p, s) for s, p in sorted(big, reverse=True)[:limit]]


def file_hash(path, algo="sha256", chunk=1 << 20):
    h = hashlib.new(algo)
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def duplicate_groups(entries, hasher=file_hash, min_bytes=1):
    """Same size first (cheap), then same SHA-256. Returns groups of 2+ identical files, biggest first."""
    by_size = {}
    for p, s in entries:
        if s >= min_bytes:
            by_size.setdefault(s, []).append(p)
    groups = []
    for size, paths in by_size.items():
        if len(paths) < 2:
            continue
        by_hash = {}
        for p in paths:
            try:
                by_hash.setdefault(hasher(p), []).append(p)
            except OSError:
                pass
        groups += [(size, sorted(g)) for g in by_hash.values() if len(g) > 1]
    return sorted(groups, key=lambda g: -g[0])


def folder_sizes(root, entries):
    """Total size of each direct child of root (files directly in root count as '(files here)')."""
    root = root.rstrip("/")
    out = {}
    for p, s in entries:
        rel = p[len(root) + 1:]
        key = rel.split("/", 1)[0] if "/" in rel else "(files here)"
        out[key] = out.get(key, 0) + s
    return sorted(out.items(), key=lambda kv: -kv[1])


def category_of(name):
    ext = os.path.splitext(name)[1].lower()
    for cat, exts in CATEGORIES.items():
        if ext in exts:
            return cat
    return None


def organize_plan(names, existing=()):
    """Downloads organiser: file name -> 'Category/name'. Unknown types stay; never overwrites."""
    taken = set(existing)
    plan = []
    for n in sorted(names):
        cat = category_of(n)
        if not cat:
            continue
        target = f"{cat}/{n}"
        base, ext = os.path.splitext(n)
        i = 1
        while target in taken:
            target = f"{cat}/{base} ({i}){ext}"
            i += 1
        taken.add(target)
        plan.append((n, target))
    return plan


def batch_rename_plan(names, pattern, start=1):
    """pattern uses {n} (number), {name} (old name without extension), {ext} (with dot).
    Raises ValueError on an empty/invalid pattern or when two files would get the same name."""
    if not pattern or "/" in pattern or ("{n}" not in pattern and "{name}" not in pattern):
        raise ValueError("pattern must contain {n} or {name} and no '/'")
    width = len(str(start + len(names) - 1))
    plan, seen = [], set()
    for i, old in enumerate(sorted(names)):
        base, ext = os.path.splitext(old)
        new = pattern.replace("{n}", str(start + i).zfill(width)).replace("{name}", base).replace("{ext}", ext)
        if "{ext}" not in pattern and not new.endswith(ext):
            new += ext
        if new in seen:
            raise ValueError(f"two files would be named {new}")
        seen.add(new)
        plan.append((old, new))
    return plan


def content_search_cmd(root, text):
    return ["grep", "-rIl", "--exclude-dir=.*", "-F", "--", text, root]


def shred_cmd(path):
    return ["shred", "-u", "-z", "-n", "2", "--", path]


# ---------------- Media / PDF ----------------

def valid_time(t):
    return bool(TIME_RE.match(t or ""))


def image_convert_cmd(src, dst, width=None):
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", src]
    if width:
        w = int(width)
        if not 16 <= w <= 16384:
            raise ValueError("width 16..16384")
        cmd += ["-vf", f"scale={w}:-2"]
    return cmd + ["-frames:v", "1", dst]


def video_trim_cmd(src, dst, start, end):
    if not (valid_time(start) and valid_time(end)):
        raise ValueError("times must be HH:MM:SS")
    return ["ffmpeg", "-y", "-loglevel", "error", "-ss", start, "-to", end, "-i", src, "-c", "copy", dst]


def audio_record_cmd(dst, seconds):
    s = int(seconds)
    if not 1 <= s <= 3 * 3600:
        raise ValueError("1 second .. 3 hours")
    return ["ffmpeg", "-y", "-loglevel", "error", "-f", "pulse", "-i", "default", "-t", str(s), dst]


def pdf_merge_cmd(files, out):
    if len(files) < 2:
        raise ValueError("choose at least two PDF files")
    return ["qpdf", "--empty", "--pages", *files, "--", out]


def pdf_split_cmd(src, outdir):
    return ["qpdf", "--split-pages", src, os.path.join(outdir, pathlib.Path(src).stem + "-page-%d.pdf")]


PDF_LEVELS = {"small": "/screen", "medium": "/ebook", "print": "/printer"}


def pdf_compress_cmd(src, out, level="medium"):
    return ["gs", "-q", "-dNOPAUSE", "-dBATCH", "-dSAFER", "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.5",
            f"-dPDFSETTINGS={PDF_LEVELS[level]}", f"-sOutputFile={out}", src]


# ---------------- Network ----------------

def wifi_qr_payload(ssid, password, security="WPA"):
    """Standard Wi-Fi QR text (phones join by scanning)."""
    esc = lambda s: re.sub(r'([\\;,:"])', r"\\\1", s)
    if not ssid:
        raise ValueError("no Wi-Fi name")
    if not password:
        return f"WIFI:T:nopass;S:{esc(ssid)};;"
    return f"WIFI:T:{security};S:{esc(ssid)};P:{esc(password)};;"


def dns_query_packet(name, qid=0x4E41):
    labels = [p for p in name.strip(".").split(".") if p]
    if not labels or any(len(p) > 63 for p in labels):
        raise ValueError("bad host name")
    q = b"".join(bytes([len(p)]) + p.encode("idna") for p in labels) + b"\x00"
    return struct.pack(">HHHHHH", qid, 0x0100, 1, 0, 0, 0) + q + struct.pack(">HH", 1, 1)


def dns_answer_ok(packet, qid=0x4E41):
    """True when the reply belongs to our query, has no error code and at least one answer."""
    if len(packet) < 12:
        return False
    rid, flags, _, ancount = struct.unpack(">HHHH", packet[:8])
    return rid == qid and flags & 0x8000 and (flags & 0x000F) == 0 and ancount > 0


def dns_time_ms(server, name="debian.org", timeout=2.0):
    """Real UDP DNS lookup against one server; milliseconds or None on failure."""
    s = socket.socket(socket.AF_INET6 if ":" in server else socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    try:
        t = time.monotonic()
        s.sendto(dns_query_packet(name), (server, 53))
        data, _ = s.recvfrom(1500)
        return round((time.monotonic() - t) * 1000, 1) if dns_answer_ok(data) else None
    except OSError:
        return None
    finally:
        s.close()


DNS_SERVERS = (("Cloudflare", "1.1.1.1"), ("Google", "8.8.8.8"), ("Quad9", "9.9.9.9"), ("OpenDNS", "208.67.222.222"))


def rate(prev, now, seconds):
    return max(0, now - prev) / seconds if seconds > 0 else 0


# ---------------- System ----------------

def battery_health(full, design):
    """Percent of original capacity, or None when the battery does not report it."""
    try:
        full, design = float(full), float(design)
    except (TypeError, ValueError):
        return None
    return round(min(100.0, full * 100 / design), 1) if design > 0 and full > 0 else None


def parse_blame(text, limit=15):
    """`systemd-analyze blame` -> [(seconds, unit)], slowest first."""
    out = []
    for line in text.splitlines():
        m = re.match(r"\s*((?:\d+min )?[\d.]+(?:ms|s|us|µs))\s+(\S+)", line)
        if not m:
            continue
        t, unit = m.groups()
        secs = 0.0
        mm = re.match(r"(\d+)min ", t)
        if mm:
            secs += int(mm[1]) * 60
            t = t[mm.end():]
        v = float(re.match(r"[\d.]+", t)[0])
        secs += v / 1000 if t.endswith("ms") else (v / 1e6 if t.endswith(("us", "µs")) else v)
        out.append((round(secs, 3), unit))
    return sorted(out, reverse=True)[:limit]


def parse_services(text):
    """`systemctl list-units --type=service --all --no-legend --plain` -> [(unit, active, sub, description)]."""
    out = []
    for line in text.splitlines():
        parts = line.split(None, 4)
        if len(parts) >= 4 and parts[0].endswith(".service"):
            out.append((parts[0], parts[2], parts[3], parts[4] if len(parts) > 4 else ""))
    return out


SERVICE_RE = re.compile(r"^[A-Za-z0-9@._:-]+\.service$")


def service_cmd(action, unit):
    if action not in ("start", "stop", "restart", "enable", "disable") or not SERVICE_RE.match(unit):
        raise ValueError("bad service action")
    return ["pkexec", "systemctl", action, unit]


def health_report(sections):
    """sections: [(title, text)] -> one plain-text report."""
    lines = ["NAVIN OS 2.2 - System Health Report", time.strftime("Created %Y-%m-%d %H:%M"), ""]
    for title, text in sections:
        lines += [f"== {title} ==", (text or "(no data)").rstrip(), ""]
    return "\n".join(lines)


POMODORO = (("Focus", 25 * 60), ("Short break", 5 * 60), ("Focus", 25 * 60), ("Short break", 5 * 60),
            ("Focus", 25 * 60), ("Short break", 5 * 60), ("Focus", 25 * 60), ("Long break", 15 * 60))


def pomodoro_step(index):
    return POMODORO[index % len(POMODORO)]


def workspace_count(current, action):
    """Win+Ctrl+D adds a desktop, Win+Ctrl+F4 removes one (1..12)."""
    return min(12, current + 1) if action == "add" else max(1, current - 1)


# =====================================================================================
# NAVIN 2.2 — the rest of the 1001–1100 list. Same rule: pure logic or exact command lines.
# =====================================================================================
import html
import ipaddress
from urllib.parse import unquote, urlparse

# ---------------- Smart desktop ----------------

XBEL_RE = re.compile(r'<bookmark href="([^"]+)"[^>]*?modified="([^"]+)"(.*?)</bookmark>', re.S)
XBEL_APP_RE = re.compile(r'<bookmark:application name="([^"]+)"[^>]*?count="(\d+)"')


def parse_recent(xbel_text):
    """~/.local/share/recently-used.xbel -> [(path, modified-iso, {app: count})], newest first."""
    out = []
    for href, mod, body in XBEL_RE.findall(xbel_text):
        if not href.startswith("file://"):
            continue
        apps = {html.unescape(a): int(c) for a, c in XBEL_APP_RE.findall(body)}
        out.append((unquote(urlparse(html.unescape(href)).path), mod, apps))
    return sorted(out, key=lambda r: r[1], reverse=True)


def app_suggestions(recent, limit=8):
    """Apps the user really opens files with, most used first."""
    total = {}
    for _p, _m, apps in recent:
        for a, c in apps.items():
            total[a] = total.get(a, 0) + c
    return sorted(total.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]


def tile_layout(n, width, height, top=0, gap=6):
    """Grid for n windows inside the work area -> [(x, y, w, h)]."""
    if n <= 0:
        return []
    cols = 1 if n == 1 else 2 if n <= 4 else 3 if n <= 9 else 4
    rows = -(-n // cols)
    w, h = (width - gap * (cols + 1)) // cols, (height - gap * (rows + 1)) // rows
    cells = []
    for i in range(n):
        r, c = divmod(i, cols)
        last_row_cols = n - (rows - 1) * cols if r == rows - 1 else cols
        cw = (width - gap * (last_row_cols + 1)) // last_row_cols if r == rows - 1 else w
        cells.append((gap + c * (cw + gap), top + gap + r * (h + gap), cw, h))
    return cells


def parse_wmctrl(text):
    """`wmctrl -lpG` -> [(win_id, desktop, pid, title)] for normal windows on a desktop."""
    out = []
    for line in text.splitlines():
        p = line.split(None, 8)
        if len(p) >= 8 and p[1].lstrip("-").isdigit() and p[1] != "-1":
            out.append((p[0], int(p[1]), int(p[2]), p[8] if len(p) > 8 else ""))
    return out


SESSION_SKIP = ("xfce4-panel", "xfdesktop", "navin-toolbox", "xfwm4", "Thunar --daemon")


def session_from_windows(windows, cmdline_of):
    """Workspace saver: [(win, desktop, pid, title)] + pid -> argv  => unique [{desktop, argv}]."""
    seen, out = set(), []
    for _w, desk, pid, _t in windows:
        argv = cmdline_of(pid)
        if not argv or any(s in " ".join(argv) for s in SESSION_SKIP):
            continue
        key = (desk, tuple(argv))
        if key not in seen:
            seen.add(key)
            out.append({"desktop": desk, "argv": list(argv)})
    return out


PROFILE_RE = re.compile(r"^[A-Za-z0-9 _-]{1,40}$")
PROFILE_CHANNELS = ("xfce4-desktop.xml", "xfce4-panel.xml", "xsettings.xml", "xfwm4.xml", "xfce4-keyboard-shortcuts.xml")


def profile_name_ok(name):
    return bool(PROFILE_RE.match(name or "")) and name.strip() == name


CLIP_SLOTS = 9


def clip_slot_path(base, slot):
    s = int(slot)
    if not 1 <= s <= CLIP_SLOTS:
        raise ValueError("slot 1..9")
    return os.path.join(base, f"slot-{s}.txt")


def voice_query(pocketsphinx_json_lines):
    """pocketsphinx `single` prints one JSON object per utterance; join the recognised text."""
    import json
    words = []
    for line in pocketsphinx_json_lines.splitlines():
        try:
            t = json.loads(line).get("t", "")
        except ValueError:
            continue
        if t:
            words.append(t.strip())
    return " ".join(words).strip()


# ---------------- Files ----------------

MODE_RE = re.compile(r"^[0-7]{3,4}$")


def chmod_cmd(path, mode, recursive=False):
    if not MODE_RE.match(mode or ""):
        raise ValueError("mode like 644 or 755")
    if int(mode, 8) & 0o002 and not int(mode, 8) & 0o1000:
        raise ValueError("refusing world-writable mode (anyone could change the file)")
    return ["chmod", *(["-R"] if recursive else []), mode, "--", path]


def mode_text(mode):
    """0o754 -> 'rwxr-xr--  (owner: read write run · group: read run · others: read)'."""
    bits = "rwxrwxrwx"
    s = "".join(b if mode & (1 << (8 - i)) else "-" for i, b in enumerate(bits))
    word = lambda t: " ".join(w for w, c in zip(("read", "write", "run"), t) if c != "-") or "nothing"
    return f"{s}  (owner: {word(s[0:3])} · group: {word(s[3:6])} · others: {word(s[6:9])})"


CONVERT_TO = {"jpg", "png", "webp", "bmp", "mp3", "ogg", "wav", "flac", "mp4", "mkv", "webm"}


def batch_convert_plan(names, fmt, existing=()):
    """Folder converter: every image/audio/video file -> same name with the new extension, never overwriting."""
    if fmt not in CONVERT_TO:
        raise ValueError("unsupported format")
    want = "Images" if fmt in {"jpg", "png", "webp", "bmp"} else "Music" if fmt in {"mp3", "ogg", "wav", "flac"} else "Videos"
    taken, plan = set(existing) | set(names), []
    for n in sorted(names):
        base, ext = os.path.splitext(n)
        if category_of(n) != want or ext.lower() == "." + fmt:
            continue
        new, i = f"{base}.{fmt}", 1
        while new in taken:
            new, i = f"{base} ({i}).{fmt}", i + 1
        taken.add(new)
        plan.append((n, new))
    return plan


def media_convert_cmd(src, dst):
    return ["ffmpeg", "-n", "-loglevel", "error", "-i", src, dst]


def video_join_list(files):
    """ffmpeg concat-demuxer list (screen-recording editor: join clips)."""
    if len(files) < 2:
        raise ValueError("choose at least two videos")
    return "".join("file '" + f.replace("'", "'\\''") + "'\n" for f in files)


def video_join_cmd(listfile, dst):
    return ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", listfile, "-c", "copy", dst]


def sync_plan(src, dst):
    """Notes sync: src/dst are {relative_name: mtime}. Newer side wins; nothing is ever deleted.
    -> (copy_to_dst, copy_to_src)"""
    to_dst = sorted(n for n, t in src.items() if n not in dst or t > dst[n] + 1)
    to_src = sorted(n for n, t in dst.items() if n not in src or t > src[n] + 1)
    return to_dst, to_src


def media_library(entries):
    """[(path, size)] -> {category: (count, bytes)} for Images/Videos/Music/Documents."""
    out = {}
    for p, s in entries:
        c = category_of(p)
        if c in ("Images", "Videos", "Music", "Documents"):
            n, b = out.get(c, (0, 0))
            out[c] = (n + 1, b + s)
    return out


def old_cache_files(entries, now, days=30):
    """Automatic cache clean: [(path, size, mtime)] older than `days` -> [(path, size)]."""
    limit = now - days * 86400
    return [(p, s) for p, s, m in entries if m < limit]


# ---------------- Laptop / history ----------------

HISTORY_FIELDS = ("time", "battery", "status", "ram", "cpu", "wifi")


def history_line(t, battery, status, ram, cpu, wifi):
    f = lambda v: "" if v is None else str(v)
    return ",".join((str(int(t)), f(battery), f(status), f(ram), f(cpu), f(wifi))) + "\n"


def parse_history(text):
    rows = []
    for line in text.splitlines():
        p = line.split(",")
        if len(p) != len(HISTORY_FIELDS) or not p[0].isdigit():
            continue
        num = lambda v: float(v) if v not in ("", None) else None
        try:
            rows.append({"time": int(p[0]), "battery": num(p[1]), "status": p[2] or None,
                         "ram": num(p[3]), "cpu": num(p[4]), "wifi": num(p[5])})
        except ValueError:
            continue
    return rows


def summarize_history(rows, key):
    vals = [r[key] for r in rows if r.get(key) is not None]
    if not vals:
        return None
    return {"min": min(vals), "max": max(vals), "avg": round(sum(vals) / len(vals), 1), "samples": len(vals)}


def battery_drain_per_hour(rows):
    """Average % lost per hour while discharging (consecutive samples only)."""
    lost = secs = 0
    for a, b in zip(rows, rows[1:]):
        if a["status"] == b["status"] == "Discharging" and a["battery"] is not None and b["battery"] is not None \
                and 0 < b["time"] - a["time"] <= 1800 and b["battery"] <= a["battery"]:
            lost += a["battery"] - b["battery"]; secs += b["time"] - a["time"]
    return round(lost * 3600 / secs, 1) if secs >= 600 else None


def trim_history(lines, keep_days, now):
    limit = now - keep_days * 86400
    return [l for l in lines if l.split(",", 1)[0].isdigit() and int(l.split(",", 1)[0]) >= limit]


def wifi_signal(proc_net_wireless):
    """/proc/net/wireless -> link quality in percent (0..100) or None."""
    for line in proc_net_wireless.splitlines()[2:]:
        p = line.split()
        if len(p) > 3:
            try:
                return max(0, min(100, round(float(p[2].rstrip(".")) * 100 / 70)))
            except ValueError:
                pass
    return None


USB_ERR_RE = re.compile(r"usb \S+: (device descriptor read.*|device not accepting address.*|unable to enumerate.*|"
                        r"over-current.*|reset (?:high|full|low|super)-speed.*|Cannot enable.*|USB disconnect.*)", re.I)


def usb_problems(kernel_log):
    """Kernel messages that mean a bad cable/port/device (counted by message)."""
    out = {}
    for line in kernel_log.splitlines():
        m = USB_ERR_RE.search(line)
        if m and "disconnect" not in m.group(1).lower():
            k = re.sub(r"\d+", "N", m.group(1))
            out[k] = out.get(k, 0) + 1
    return sorted(out.items(), key=lambda kv: -kv[1])


def parse_xrandr(text):
    """`xrandr --query` -> [(output, connected, mode-or-None, primary)]."""
    out = []
    for line in text.splitlines():
        m = re.match(r"^(\S+) (connected|disconnected)( primary)?(?: (\d+x\d+)\+\d+\+\d+)?", line)
        if m:
            out.append((m[1], m[2] == "connected", m[4], bool(m[3])))
    return out


def parse_pactl_short(text):
    """`pactl list short sinks|sources` -> [(name, state)] (monitors skipped)."""
    out = []
    for line in text.splitlines():
        p = line.split("\t")
        if len(p) >= 5 and not p[1].endswith(".monitor"):
            out.append((p[1], p[-1].strip()))
    return out


# ---------------- Network ----------------

def subnet_hosts(cidr, limit=254):
    """Addresses to look at for Network Devices. Big networks (offices, /16) are narrowed to the /24 around
    this PC so a scan stays a few seconds."""
    iface = ipaddress.ip_interface(cidr)
    if iface.version != 4:
        raise ValueError("only IPv4 networks")
    net = iface.network if iface.network.prefixlen >= 24 else ipaddress.ip_network(f"{iface.ip}/24", strict=False)
    return [str(h) for h in list(net.hosts())[:limit] if h != iface.ip]


def parse_neigh(text):
    """`ip neigh` -> [(ip, mac)] of devices that answered."""
    out = []
    for line in text.splitlines():
        m = re.match(r"^(\d+\.\d+\.\d+\.\d+) .*lladdr ([0-9a-f:]{17}) (REACHABLE|STALE|DELAY|PROBE|PERMANENT)", line)
        if m:
            out.append((m[1], m[2]))
    return out


URL_RE = re.compile(r"^https?://[^\s/$.?#][^\s]*$", re.I)


def download_cmd(url, folder):
    """Download Resume Manager: wget -c continues a broken download from where it stopped."""
    if not URL_RE.match(url or ""):
        raise ValueError("enter a link starting with http:// or https://")
    return ["wget", "-c", "--tries=20", "--retry-connrefused", "--waitretry=5", "--progress=dot:giga", "-P", folder, "--", url]


def nm_name_ok(name):
    return bool(name) and len(name) <= 200 and "\n" not in name


def priority_cmd(name, prio):
    p = int(prio)
    if not nm_name_ok(name) or not -999 <= p <= 999:
        raise ValueError("bad connection or priority")
    return ["nmcli", "connection", "modify", name, "connection.autoconnect", "yes", "connection.autoconnect-priority", str(p)]


def reconnect_cmd(name):
    if not nm_name_ok(name):
        raise ValueError("bad connection name")
    # retries 0 = try forever; NetworkManager reconnects as soon as the network is back
    return ["nmcli", "connection", "modify", name, "connection.autoconnect", "yes", "connection.autoconnect-retries", "0"]


# ---------------- Security ----------------

RISKY_EXT = {".exe", ".scr", ".pif", ".com", ".bat", ".cmd", ".vbs", ".vbe", ".js", ".jse", ".wsf", ".lnk", ".hta", ".ps1", ".msi"}


def usb_risks(rel_paths):
    """USB scanner: [(path, reason)] for autorun files, hidden programs, double extensions, shortcut worms."""
    out = []
    for p in rel_paths:
        name = os.path.basename(p)
        low = name.lower()
        ext = os.path.splitext(low)[1]
        if low == "autorun.inf":
            out.append((p, "autorun file (starts programs automatically on Windows)"))
        elif ext in RISKY_EXT and re.search(r"\.(pdf|docx?|xlsx?|jpe?g|png|mp[34]|txt)\.[a-z0-9]+$", low):
            out.append((p, "program disguised as a document (double extension)"))
        elif ext in RISKY_EXT and name.startswith("."):
            out.append((p, "hidden program"))
        elif ext == ".lnk" and "/" not in p.strip("/"):
            out.append((p, "shortcut on the top level (typical USB shortcut virus)"))
    return out


FAIL_RE = re.compile(r"^(\S+ +\d+ [\d:]+|\S+T[\d:.+-]+) .*(authentication failure|FAILED (?:SU|su)|Failed password|incorrect password).*?(?:user[= ](\w+))?", re.I)


def failed_logins(journal_text):
    """[(when, user-or-?)] from `journalctl` auth lines."""
    out = []
    for line in journal_text.splitlines():
        m = FAIL_RE.search(line)
        if m:
            u = re.search(r"(?:user|ruser|logname)=(\w+)", line) or re.search(r"for (\w+)", line)
            out.append((m[1], u[1] if u else "?"))
    return out


def parse_dpkg_verify(text):
    """`dpkg --verify` -> [(path, what)] for changed program files (config files are expected to change)."""
    out = []
    for line in text.splitlines():
        m = re.match(r"^(\S+) +(?:(c) +)?(/.*)$", line)
        if not m or m[2]:
            continue
        flags, path = m[1], m[3]
        what = "missing" if flags.startswith("missing") else "content changed" if "5" in flags else "changed"
        out.append((path, what))
    return out


def perm_snapshot(entries):
    """[(path, mode, uid)] -> {path: 'mode:uid'}."""
    return {p: f"{oct(m & 0o7777)}:{u}" for p, m, u in entries}


def perm_diff(old, new):
    """Permission change history between two snapshots -> [(path, before, after)]."""
    out = []
    for p in sorted(set(old) | set(new)):
        if old.get(p) != new.get(p):
            out.append((p, old.get(p, "(new)"), new.get(p, "(removed)")))
    return out


def startup_risks(entries, owned):
    """Suspicious start-up detection. entries: [(source, name, command)]; owned(path) -> True when a Debian
    package owns it. Flags commands from /tmp, hidden folders, downloads, or programs no package installed."""
    out = []
    for src, name, cmd in entries:
        prog = (cmd or "").split()[0] if cmd else ""
        reason = None
        if re.search(r"(^|/)(tmp|var/tmp|dev/shm)/", prog):
            reason = "runs from a temporary folder"
        elif re.search(r"/\.[^/]+/", prog) and "/.local/bin/" not in prog:
            reason = "runs from a hidden folder"
        elif "/Downloads/" in prog:
            reason = "runs straight from Downloads"
        elif re.search(r"(curl|wget)[^|]*\|\s*(ba)?sh", cmd or ""):
            reason = "downloads and runs a script"
        elif prog.startswith("/") and not prog.startswith(("/usr/local/bin/navin", "/usr/local/lib/navin")) and not owned(prog):
            reason = "program not installed by any package"
        if reason:
            out.append((src, name, reason))
    return out


UFW_RE = re.compile(r"\[UFW BLOCK\].*?SRC=(\S+).*?PROTO=(\S+)(?:.*?DPT=(\d+))?")


def parse_ufw_blocks(text):
    """Firewall dashboard: blocked attempts grouped by (source, protocol, port), most first."""
    out = {}
    for line in text.splitlines():
        m = UFW_RE.search(line)
        if m:
            k = (m[1], m[2], m[3] or "-")
            out[k] = out.get(k, 0) + 1
    return sorted(out.items(), key=lambda kv: -kv[1])


AUDIT_CHECKS = (("firewall", 20, "Firewall (UFW) is on"), ("updates", 15, "Automatic security updates"),
                ("secureboot", 10, "Secure Boot"), ("lock", 15, "Screen locks automatically"),
                ("nopass", 20, "Every account has a password"), ("ports", 10, "No unexpected open network ports"),
                ("homeperm", 10, "Home folder is private"))


def audit_score(results):
    """results: {check: True/False/None(unknown)} -> (score 0..100, [(ok, text)])."""
    score, lines = 0, []
    for key, pts, text in AUDIT_CHECKS:
        r = results.get(key)
        if r:
            score += pts
        lines.append((r, text))
    return score, lines


def parse_listening(ss_text):
    """`ss -tulnH` -> [(proto, address, port)] that are reachable from the network (not localhost)."""
    out = []
    for line in ss_text.splitlines():
        p = line.split()
        if len(p) >= 5:
            addr, _, port = p[4].rpartition(":")
            if addr.strip("[]") not in ("127.0.0.1", "::1", "127.0.0.53", "127.0.0.54") and not addr.startswith("127."):
                out.append((p[0], addr, port))
    return out


GUEST = "guest"


def guest_cmds(action):
    """Secure guest account: no admin rights, files wiped with 'reset'."""
    if action == "create":
        return [["pkexec", "useradd", "-m", "-s", "/bin/bash", "-c", "Guest", GUEST],
                ["pkexec", "passwd", "-d", GUEST]]
    if action == "reset":
        return [["pkexec", "sh", "-c", f"pkill -KILL -u {GUEST}; rm -rf /home/{GUEST} && mkhomedir_helper {GUEST} 2>/dev/null || (cp -rT /etc/skel /home/{GUEST} && chown -R {GUEST}: /home/{GUEST})"]]
    if action == "remove":
        return [["pkexec", "sh", "-c", f"pkill -KILL -u {GUEST}; userdel -r {GUEST}"]]
    raise ValueError("create, reset or remove")


def lock_delay_cmds(minutes):
    """Automatic screen lock after N idle minutes (light-locker locks when the X screensaver starts)."""
    m = int(minutes)
    if not 1 <= m <= 120:
        raise ValueError("1..120 minutes")
    return [["xset", "s", str(m * 60), str(m * 60)],
            ["xfconf-query", "-c", "xfce4-power-manager", "-p", "/xfce4-power-manager/lock-screen-suspend-hibernate", "-n", "-t", "bool", "-s", "true"],
            ["xfconf-query", "-c", "xfce4-session", "-p", "/general/LockCommand", "-n", "-t", "string", "-s", "light-locker-command -l"]]


# ---------------- Performance ----------------

def rank_processes(procs, my_uid, limit=25):
    """Background app analyzer. procs: [{pid, name, uid, rss, cpu_time, has_window}] ->
    the user's own programs without a window, heaviest (memory, then CPU time) first."""
    bg = [p for p in procs if p["uid"] == my_uid and not p["has_window"]]
    return sorted(bg, key=lambda p: (-p["rss"], -p["cpu_time"]))[:limit]


NICE_LEVELS = {"high": -5, "above normal": -2, "normal": 0, "below normal": 5, "low": 10}


def renice_cmd(pid, level):
    n = NICE_LEVELS[level]
    pid = int(pid)
    if pid <= 1:
        raise ValueError("bad process id")
    base = ["renice", "-n", str(n), "-p", str(pid)]
    return ["pkexec", *base] if n < 0 else base


ZRAM_PROFILES = ("auto", "lite", "balanced", "standard")


def zram_profile_cmd(profile):
    """Smart ZRAM controller: auto picks by RAM (<=2.6 GB lite = 100 %, <=6.5 GB balanced = 75 %, else 50 %)
    and LZ4 on CPUs without AVX (navin-memprofile applies it before zramswap starts)."""
    if profile not in ZRAM_PROFILES:
        raise ValueError("auto, lite, balanced or standard")
    return ["pkexec", "sh", "-c", f"mkdir -p /etc/navin && echo {profile} > /etc/navin/memprofile && "
            "systemctl restart navin-memprofile.service && systemctl restart zramswap.service"]


def parse_zramctl(text):
    """`zramctl --raw --noheadings --output NAME,ALGORITHM,DISKSIZE,DATA,COMPR` -> [(dev, algo, size, data, compr)]."""
    return [tuple(l.split()) for l in text.splitlines() if len(l.split()) == 5]


def emergency_targets(procs, free_bytes, need_bytes=400 << 20, protect=("Xorg", "xfwm4", "xfce4-panel", "lightdm", "pipewire", "wireplumber", "xfce4-session", "systemd")):
    """Low-RAM emergency: which of the user's apps to close (biggest first) to get `need_bytes` free."""
    if free_bytes >= need_bytes:
        return []
    out, got = [], free_bytes
    for p in sorted(procs, key=lambda p: -p["rss"]):
        if p["name"] in protect:
            continue
        out.append(p)
        got += p["rss"]
        if got >= need_bytes:
            break
    return out


# ---------------- System administration ----------------

def parse_lspci_k(text):
    """`lspci -k` -> [(device, driver-in-use or None)]."""
    out, cur = [], None
    for line in text.splitlines():
        if line and not line[0].isspace():
            if cur:
                out.append(tuple(cur))
            cur = [line.split(" ", 1)[1] if " " in line else line, None]
        elif cur and "Kernel driver in use:" in line:
            cur[1] = line.split(":", 1)[1].strip()
    if cur:
        out.append(tuple(cur))
    return out


PKG_RE = re.compile(r"^[a-z0-9][a-z0-9+.-]{1,80}(:[a-z0-9]+)?$")


def pkg_name_ok(name):
    return bool(PKG_RE.match(name or ""))


def parse_sources(text):
    """deb822 .sources -> [{'URIs', 'Suites', 'Components', 'Enabled'}]."""
    out, cur = [], {}
    for line in text.splitlines() + [""]:
        if not line.strip():
            if cur:
                out.append(cur)
            cur = {}
        elif ":" in line and not line.startswith(("#", " ")):
            k, v = line.split(":", 1)
            cur[k.strip()] = v.strip()
    return out


def grub_set(text, timeout=None, quiet=None):
    """Bootloader config: change GRUB_TIMEOUT and quiet/splash, keep every other line."""
    lines = text.splitlines()
    if timeout is not None:
        t = int(timeout)
        if not 0 <= t <= 30:
            raise ValueError("0..30 seconds")
        found = False
        for i, l in enumerate(lines):
            if l.startswith("GRUB_TIMEOUT="):
                lines[i] = f"GRUB_TIMEOUT={t}"; found = True
        if not found:
            lines.append(f"GRUB_TIMEOUT={t}")
    if quiet is not None:
        for i, l in enumerate(lines):
            m = re.match(r'^GRUB_CMDLINE_LINUX_DEFAULT="(.*)"$', l)
            if m:
                opts = [o for o in m[1].split() if o not in ("quiet", "splash")]
                lines[i] = 'GRUB_CMDLINE_LINUX_DEFAULT="' + " ".join((["quiet", "splash"] if quiet else []) + opts) + '"'
    return "\n".join(lines) + "\n"


# ---------------- NAVIN exclusive ----------------

def pe_arch(head):
    """First bytes of a Windows program -> '64-bit' / '32-bit' / None (not a Windows program)."""
    if len(head) < 64 or head[:2] != b"MZ":
        return None
    off = struct.unpack_from("<I", head, 0x3C)[0]
    if off + 6 > len(head) or head[off:off + 4] != b"PE\x00\x00":
        return None
    machine = struct.unpack_from("<H", head, off + 4)[0]
    return {0x8664: "64-bit", 0x14C: "32-bit", 0xAA64: "ARM64"}.get(machine, "unknown")


def compat_verdict(name, head=b"", host_arch="amd64"):
    """NAVIN App Compatibility Checker: how a file can run on NAVIN."""
    low = name.lower()
    if low.endswith((".exe", ".msi")):
        arch = pe_arch(head) if low.endswith(".exe") else "installer"
        if low.endswith(".exe") and arch is None:
            return ("no", "Not a valid Windows program.")
        if arch == "ARM64":
            return ("no", "ARM Windows program - cannot run on this PC.")
        return ("maybe", f"Windows program ({arch}). Runs with Wine: double-click it. Games use DXVK when Vulkan works.")
    if low.endswith(".deb"):
        return ("yes", "Debian package: double-click to install with GDebi (it checks dependencies first).")
    if low.endswith(".appimage"):
        return ("yes", "AppImage: right-click > Properties > allow running, then double-click.")
    if low.endswith(".flatpakref"):
        return ("yes", "Flatpak: opens in the App Store (Flathub).")
    if low.endswith((".apk", ".dmg", ".pkg", ".ipa")):
        return ("no", "Phone/Mac app - these do not run on a PC with NAVIN.")
    if low.endswith((".sh", ".run")):
        return ("maybe", "Linux script/installer: run it from a terminal only if you trust where it came from.")
    return ("unknown", "Not a program. Open it with its normal app.")


def maintenance_plan(free_bytes, total_bytes, failed_units, cache_bytes, updates):
    """Smart Maintenance Center: what needs doing, most important first."""
    todo = []
    if total_bytes and free_bytes / total_bytes < 0.10:
        todo.append(("disk", f"Only {human_size(free_bytes)} free - clean caches and old files"))
    if failed_units:
        todo.append(("services", f"{len(failed_units)} service(s) failed: " + ", ".join(failed_units[:5])))
    if updates:
        todo.append(("updates", f"{updates} update(s) waiting"))
    if cache_bytes > 500 << 20:
        todo.append(("cache", f"{human_size(cache_bytes)} of cache can be cleaned"))
    return todo


# ---------------- 2.2 extras (filled gaps of the 1–1000 list) ----------------

DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
HOSTS_BEGIN, HOSTS_END = "# NAVIN parental controls BEGIN", "# NAVIN parental controls END"


def hosts_block(hosts_text, domains):
    """Parental controls / website blocker: rewrite only NAVIN's block in /etc/hosts (empty list = unblock all)."""
    clean = []
    for d in domains:
        d = d.strip().lower().removeprefix("https://").removeprefix("http://").split("/")[0].removeprefix("www.")
        if not d:
            continue
        if not DOMAIN_RE.match(d):
            raise ValueError(f"not a website name: {d}")
        clean += [d, f"www.{d}"]
    lines, inside = [], False
    for l in hosts_text.splitlines():
        if l.strip() == HOSTS_BEGIN:
            inside = True; continue
        if l.strip() == HOSTS_END:
            inside = False; continue
        if not inside:
            lines.append(l)
    if clean:
        lines += [HOSTS_BEGIN] + [f"{ip} {d}" for d in dict.fromkeys(clean) for ip in ("0.0.0.0", "::")] + [HOSTS_END]
    return "\n".join(lines) + "\n"


def blocked_sites(hosts_text):
    inside, out = False, []
    for l in hosts_text.splitlines():
        if l.strip() == HOSTS_BEGIN:
            inside = True
        elif l.strip() == HOSTS_END:
            inside = False
        elif inside and l.startswith("0.0.0.0 ") and not l.split()[1].startswith("www."):
            out.append(l.split()[1])
    return out


SPEED_URL = "https://speed.cloudflare.com/__down?bytes={}"


def mbit_per_s(nbytes, seconds):
    return round(nbytes * 8 / seconds / 1e6, 1) if seconds > 0 else 0.0


CAPTIVE_URL = "http://nmcheck.gnome.org/check_network_status.txt"


def captive_portal(body):
    """True when the connectivity check was answered by a Wi-Fi login page instead of the real server."""
    return "NetworkManager is online" not in (body or "")


CAL_RE = re.compile(r"^(daily|weekly|monthly|hourly|\*-\*-\* \d{2}:\d{2}(:\d{2})?|(Mon|Tue|Wed|Thu|Fri|Sat|Sun) \d{2}:\d{2})$")
TIMER_NAME_RE = re.compile(r"^[a-z0-9-]{1,30}$")


def user_timer_units(name, command, when, description):
    """Backup scheduling / automation: systemd *user* timer (no root, survives restarts, catches up if missed).
    -> {filename: text} for ~/.config/systemd/user"""
    if not TIMER_NAME_RE.match(name) or not CAL_RE.match(when) or not command or "\n" in command:
        raise ValueError("name a-z0-9-, time like daily / weekly / *-*-* 20:00 / Mon 09:00")
    unit = f"navin-auto-{name}"
    return {f"{unit}.service": f"[Unit]\nDescription={description}\n\n[Service]\nType=oneshot\nNice=10\nExecStart=/bin/sh -c {shell_quote(command)}\n",
            f"{unit}.timer": f"[Unit]\nDescription={description}\n\n[Timer]\nOnCalendar={when}\nPersistent=true\n\n[Install]\nWantedBy=timers.target\n"}


def shell_quote(s):
    return "'" + s.replace("'", "'\\''") + "'"


def backup_command(src_dirs, dest):
    """Copy new/changed files only (cp -u keeps older copies, never deletes)."""
    if not src_dirs or not dest:
        raise ValueError("choose what and where")
    return " && ".join(f"mkdir -p {shell_quote(os.path.join(dest, os.path.basename(s.rstrip('/'))))} && "
                       f"cp -ru --preserve=timestamps {shell_quote(s.rstrip('/') + '/.')} {shell_quote(os.path.join(dest, os.path.basename(s.rstrip('/'))))}"
                       for s in src_dirs)


AVATAR_EXT = (".png", ".jpg", ".jpeg")
USER_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")


def avatar_cmds(image, user, tmp_png):
    """User picture on the login screen: a 256 px square PNG made with ffmpeg, installed as the
    AccountsService icon (LightDM shows it) and as ~/.face."""
    if not image.lower().endswith(AVATAR_EXT):
        raise ValueError("choose a PNG or JPG picture")
    if not USER_RE.match(user):
        raise ValueError("bad user name")
    icon = f"/var/lib/AccountsService/icons/{user}"
    return [["ffmpeg", "-y", "-loglevel", "error", "-i", image, "-vf",
             "scale=256:256:force_original_aspect_ratio=increase,crop=256:256", "-frames:v", "1", tmp_png],
            ["pkexec", "sh", "-c", f"install -D -m 644 {shell_quote(tmp_png)} {icon} && mkdir -p /var/lib/AccountsService/users && "
             f"f=/var/lib/AccountsService/users/{user}; touch $f; grep -q '^\\[User\\]' $f || echo '[User]' >> $f; "
             f"sed -i '/^Icon=/d' $f; sed -i 's|^\\[User\\]$|[User]\\nIcon={icon}|' $f"]]
