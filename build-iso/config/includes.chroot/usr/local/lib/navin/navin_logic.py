import re
BUILD = 20
VERSION = "2.0"
VOICES = ("Kore", "Puck", "Charon", "Aoede", "Fenrir", "Leda")
IMAGE_SIZES = ("1024x1024", "1536x1024")
HOLD_SECONDS = 5
REPO = "naveenpalecha00-coder/navin-os"
def update_tag(build):
 """GitHub tag of a NAVIN 2.0 over-the-air patch (tools/config only, same Debian 13 base)."""
 return "v2.0-update." + str(int(build))
def release_build(tag):
 """Patch number of a NAVIN 2.0 OTA release. Debian 12 'v1.0-build.N' patches are a different base
 and are never applied to NAVIN 2.0 (and 2.0 patches are invisible to Debian 12 systems)."""
 match = re.fullmatch(r"v2\.0-update\.(\d+)", tag)
 return int(match[1]) if match and int(match[1]) > 0 else None
def os_version(tag):
 """'v2.1' -> (2, 1). Full NAVIN versions (new ISO / new Debian base); test tags return None."""
 match = re.fullmatch(r"v(\d+)\.(\d+)", tag)
 return (int(match[1]), int(match[2])) if match else None
def newer_os_release(releases, current=VERSION):
 """Newest stable full NAVIN version above `current` (needs a new ISO, not an OTA patch), or None."""
 cur = tuple(int(x) for x in current.split("."))
 found = [(os_version(r["tag_name"]), r) for r in releases if not r.get("draft") and not r.get("prerelease") and os_version(r.get("tag_name", ""))]
 found = [(v, r) for v, r in found if v > cur]
 return max(found, key=lambda x: x[0])[1] if found else None
def newer_patch(releases, current_build):
 """Highest stable NAVIN 2.0 OTA patch above the installed build that has its archive + checksum."""
 ok = [r for r in releases if not r.get("draft") and not r.get("prerelease") and (release_build(r.get("tag_name", "")) or 0) > current_build
       and {"navin-update.tar.gz", "navin-update.tar.gz.sha256"} <= {a.get("name") for a in r.get("assets", [])}]
 return max(ok, key=lambda r: release_build(r["tag_name"])) if ok else None
def automation(text):
 t = text.strip().lower()
 return {"mute volume":"mute", "increase brightness":"brightness", "boost ram":"ram-boost", "test microphone":"mic"}.get(t)
def package_name(value):
 return bool(re.fullmatch(r"[a-z0-9][a-z0-9+.-]+", value))
def safe_patch_path(value):
 from pathlib import PurePosixPath
 p=PurePosixPath(value)
 allowed=("usr/local/bin/", "usr/local/lib/navin/", "usr/share/navin/", "usr/share/applications/navin-", "etc/navin/build", "etc/X11/xorg.conf.d/40-navin-", "etc/sysctl.d/98-navin-", "etc/xdg/picom.conf", "etc/skel/.config/gtk-3.0/gtk.css", "usr/lib/systemd/system-sleep/navin-")
 exact=("etc/navin/build", "etc/xdg/picom.conf", "etc/skel/.config/gtk-3.0/gtk.css")
 return not p.is_absolute() and ".." not in p.parts and (value in exact or any(value.startswith(a) for a in allowed if a not in exact))
