import re
BUILD = 9
VOICES = ("Kore", "Puck", "Charon", "Aoede", "Fenrir", "Leda")
IMAGE_SIZES = ("1024x1024", "1536x1024")
HOLD_SECONDS = 5
REPO = "naveenpalecha00-coder/navin-os"
def release_build(tag):
 match = re.fullmatch(r"v1\.0-build\.(\d+)", tag)
 return int(match[1]) if match else None
def automation(text):
 t = text.strip().lower()
 return {"mute volume":"mute", "increase brightness":"brightness", "boost ram":"ram-boost", "test microphone":"mic"}.get(t)
def package_name(value):
 return bool(re.fullmatch(r"[a-z0-9][a-z0-9+.-]+", value))
def safe_patch_path(value):
 from pathlib import PurePosixPath
 p=PurePosixPath(value)
 allowed=("usr/local/bin/", "usr/local/lib/navin/", "usr/share/navin/", "usr/share/applications/navin-", "etc/navin/build", "etc/X11/xorg.conf.d/40-navin-", "etc/sysctl.d/98-navin-", "etc/xdg/picom.conf")
 exact=("etc/navin/build", "etc/xdg/picom.conf")
 return not p.is_absolute() and ".." not in p.parts and (value in exact or any(value.startswith(a) for a in allowed if a not in exact))
