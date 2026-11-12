"""NAVIN 2.1 Toolbox logic (pure Python, no GTK, unit-tested in build-iso/tests/test_v21.py).

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
    lines = ["NAVIN OS 2.1 - System Health Report", time.strftime("Created %Y-%m-%d %H:%M"), ""]
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
