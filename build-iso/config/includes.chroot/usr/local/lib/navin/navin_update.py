"""NAVIN XP Update Center logic (pure: no GTK, no root, unit-tested in build-iso/tests/test_xp.py).

The GTK window (navin-update-center) and the root helper (/usr/lib/navin-os/navin-update-helper) only call
these functions. Every command line comes from plan(); nothing downloads or runs scripts from the internet:
packages come from the signed Debian/Flatpak repositories, NAVIN releases are new ISOs from GitHub."""
import re

# Packages whose removal would break the desktop. apt "upgrade --with-new-pkgs" never removes packages;
# a full upgrade that would remove one of these (or anything) is shown to the user first.
IMPORTANT = ("xfce4-session", "xfwm4", "xfce4-panel", "lightdm", "network-manager", "sudo", "systemd", "grub-pc",
             "grub-efi-amd64", "grub-efi-amd64-signed", "shim-signed", "linux-image-amd64", "python3", "python3-gi",
             "policykit-1", "polkitd", "pkexec", "dbus", "xserver-xorg-core", "calamares")
DRIVER_PREFIXES = ("firmware-", "xserver-xorg-video-", "xserver-xorg-input-", "nvidia-", "libgl1-mesa-dri", "mesa-",
                   "intel-microcode", "amd64-microcode", "bluez", "libinput")
ACTIONS = ("refresh", "preview", "upgrade", "security", "download", "flatpak", "auto")
MODES = ("manual", "notify", "security-auto")
LOW_BANDWIDTH_KBPS = 200   # APT Acquire::http::Dl-Limit (kB/s) in low-bandwidth mode
MIN_FREE_BYTES = 500 * 1024 * 1024  # always keep this much free on / besides the update itself

_UP = re.compile(r"^(?P<name>[a-z0-9][a-z0-9+.-]*)/(?P<suites>\S+)\s+(?P<new>\S+)\s+(?P<arch>\S+)\s+\[upgradable from: (?P<old>[^\]]+)\]")


def kind_of(name):
    if name.startswith(("linux-image", "linux-headers", "linux-kbuild")):
        return "kernel"
    if name.startswith(DRIVER_PREFIXES):
        return "driver"
    return "app"


def parse_upgradable(text):
    """Rows of `apt list --upgradable`: name, versions, security flag (from a *-security suite), kind."""
    out = []
    for line in text.splitlines():
        m = _UP.match(line.strip())
        if not m:
            continue
        suites = m["suites"].split(",")
        out.append({"name": m["name"], "new": m["new"], "old": m["old"], "arch": m["arch"], "suites": suites,
                    "security": any(s.endswith("-security") for s in suites), "kind": kind_of(m["name"])})
    return out


def summary(rows):
    return {"total": len(rows), "security": sum(r["security"] for r in rows),
            "kernel": sum(r["kind"] == "kernel" for r in rows), "driver": sum(r["kind"] == "driver" for r in rows)}


def is_major(rows):
    """Ask before installing: kernel updates, bootloader/desktop core packages or many packages at once."""
    names = {r["name"] for r in rows}
    return any(r["kind"] == "kernel" for r in rows) or bool(names & set(IMPORTANT)) or len(rows) >= 40


def parse_apt_status(line):
    """One line of APT's machine status (-o APT::Status-Fd): real download / install percentages."""
    parts = line.rstrip("\n").split(":", 3)
    if len(parts) != 4 or parts[0] not in ("dlstatus", "pmstatus", "pmerror", "pmconffile", "media-change"):
        return None
    kind = {"dlstatus": "download", "pmstatus": "install", "pmerror": "error", "pmconffile": "conffile",
            "media-change": "media"}[parts[0]]
    try:
        pct = max(0.0, min(100.0, float(parts[2])))
    except ValueError:
        pct = None
    return {"kind": kind, "package": parts[1], "percent": pct, "message": parts[3]}


def overall_percent(status, download_share=0.4):
    """APT reports download and install separately (each 0-100); the bar shows both as one real 0-100."""
    if not status or status.get("percent") is None:
        return None
    if status["kind"] == "download":
        return round(status["percent"] * download_share, 1)
    if status["kind"] == "install":
        return round(download_share * 100 + status["percent"] * (1 - download_share), 1)
    return None


_UNITS = {"B": 1, "kB": 1000, "KB": 1000, "MB": 1000 ** 2, "GB": 1000 ** 3}


def _bytes(num, unit):
    return int(float(num.replace(",", "")) * _UNITS[unit])


def parse_sizes(text):
    """(download bytes, extra disk bytes) from apt's 'Need to get' / 'After this operation' lines."""
    dl = re.search(r"Need to get ([\d.,]+) ([kKMG]?B)(?:/[\d.,]+ [kKMG]?B)? of archives", text)
    disk = re.search(r"After this operation, ([\d.,]+) ([kKMG]?B) (?:of )?additional disk space", text)
    freed = re.search(r"After this operation, ([\d.,]+) ([kKMG]?B) disk space will be freed", text)
    return (_bytes(*dl.groups()) if dl else 0,
            _bytes(*disk.groups()) if disk else (-_bytes(*freed.groups()) if freed else 0))


def parse_simulation(text):
    """`apt-get -s ...` output: packages that would be installed/upgraded and removed."""
    inst = re.findall(r"^Inst (\S+)", text, re.M)
    remv = re.findall(r"^Remv (\S+)", text, re.M)
    return {"install": inst, "remove": remv, "important_removed": [p for p in remv if p in IMPORTANT]}


def parse_history(text, limit=50):
    """/var/log/apt/history.log -> newest first: date, command, upgraded/installed/removed counts, error."""
    entries, cur = [], None
    for line in text.splitlines():
        if line.startswith("Start-Date:"):
            cur = {"date": line.split(":", 1)[1].strip(), "command": "", "upgraded": 0, "installed": 0, "removed": 0,
                   "packages": [], "error": ""}
        elif cur is None:
            continue
        elif line.startswith("Commandline:"):
            cur["command"] = line.split(":", 1)[1].strip()
        elif line.startswith(("Upgrade:", "Install:", "Remove:", "Purge:")):
            key, val = line.split(":", 1)
            pkgs = re.findall(r"(?:^|\),\s*)([a-z0-9][a-z0-9+.-]*):", val.strip())
            field = {"Upgrade": "upgraded", "Install": "installed", "Remove": "removed", "Purge": "removed"}[key]
            cur[field] += len(pkgs); cur["packages"] += pkgs
        elif line.startswith("Error:"):
            cur["error"] = line.split(":", 1)[1].strip()
        elif line.startswith("End-Date:"):
            entries.append(cur); cur = None
    return list(reversed(entries))[:limit]


REPO_ERRORS = (
    (r"NO_PUBKEY|is not signed|The following signatures couldn't be verified|EXPKEYSIG",
     "A package source has a missing or invalid signature - updates from it are refused (this protects you)."),
    (r"Temporary failure resolving|Could not resolve|Failed to fetch.*(?:Connection|timed out)|Network is unreachable",
     "No internet connection to the update servers."),
    (r"Hash Sum mismatch|File has unexpected size", "A downloaded file did not match its signed checksum - try again later."),
    (r"Could not get lock|Unable to acquire the dpkg frontend lock", "Another program is installing software right now."),
    (r"dpkg was interrupted", "A previous installation was interrupted - NAVIN repairs it first (dpkg --configure -a)."),
    (r"have unmet dependencies|Unmet dependencies|held broken packages", "Dependency conflict - some packages cannot be upgraded together."),
    (r"No space left on device|You don't have enough free space", "Not enough free disk space."),
)


def diagnose(text):
    """Plain-language causes found in apt output (empty list = no known problem)."""
    return [msg for pat, msg in REPO_ERRORS if re.search(pat, text)]


def preflight(free_bytes, need_bytes, online, dpkg_busy, battery_percent=None, on_ac=True):
    """Problems that block installing now (empty list = safe to start)."""
    out = []
    if not online:
        out.append("No internet connection.")
    if need_bytes + MIN_FREE_BYTES > free_bytes:
        out.append(f"Not enough free space: {max(0, need_bytes + MIN_FREE_BYTES - free_bytes) // (1024 * 1024)} MB more needed.")
    if dpkg_busy:
        out.append("Another installation is running - wait for it to finish.")
    if battery_percent is not None and not on_ac and battery_percent < 30:
        out.append("Battery below 30 % - connect the charger so the computer cannot switch off during the update.")
    return out


def reboot_needed(reboot_required_exists, running_kernel, installed_kernels):
    """True when Debian flagged a restart or a newer kernel is installed than the one running."""
    def key(v):
        return [int(x) if x.isdigit() else x for x in re.split(r"[.+~-]", v)]
    newer = [k for k in installed_kernels if k != running_kernel]
    return bool(reboot_required_exists) or any(key(k) > key(running_kernel) for k in newer if k.endswith("-amd64"))


def parse_flatpak_updates(text):
    """`flatpak remote-ls --updates --columns=application,version,branch` rows."""
    rows = []
    for line in text.splitlines():
        cols = line.split("\t")
        if cols and re.fullmatch(r"[A-Za-z0-9_.-]+\.[A-Za-z0-9_.-]+", cols[0].strip()):
            rows.append({"name": cols[0].strip(), "version": cols[1].strip() if len(cols) > 1 else ""})
    return rows


def plan(action, packages=(), low_bandwidth=False):
    """Command lines (lists) the root helper runs for one action. Only whitelisted actions/packages."""
    if action not in ACTIONS:
        raise ValueError("unknown update action")
    if any(not re.fullmatch(r"[a-z0-9][a-z0-9+.-]+", p) for p in packages):
        raise ValueError("bad package name")
    env = ["env", "DEBIAN_FRONTEND=noninteractive", "LC_ALL=C"]
    opts = ["-o", "APT::Status-Fd=1", "-o", "Dpkg::Options::=--force-confdef", "-o", "Dpkg::Options::=--force-confold"]
    if low_bandwidth:
        opts += ["-o", f"Acquire::http::Dl-Limit={LOW_BANDWIDTH_KBPS}", "-o", "Acquire::Queue-Mode=access"]
    fix = env + ["dpkg", "--configure", "-a"]
    if action == "refresh":
        return [env + ["apt-get", "update"]]
    if action == "preview":
        return [env + ["apt-get", "-s", "--with-new-pkgs", "upgrade"]]
    if action == "download":  # "pause" = stop this, "resume" = run again: apt keeps partial files and continues them
        return [env + ["apt-get", "-y"] + opts + ["--download-only", "--with-new-pkgs", "upgrade"]]
    if action == "upgrade":  # never removes packages (--with-new-pkgs upgrade, not dist-upgrade)
        return [fix, env + ["apt-get", "-y"] + opts + ["--with-new-pkgs", "upgrade"]]
    if action in ("security", "auto"):
        if not packages:
            return []
        return [fix, env + ["apt-get", "-y"] + opts + ["install", "--only-upgrade"] + list(packages)]
    if action == "flatpak":
        return [["flatpak", "update", "-y", "--noninteractive"]]
    return []
