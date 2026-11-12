#!/bin/bash
# NAVIN 2.x over-the-air patch builder. Usage: build-iso/tools/make-update.sh NUMBER
# Packs only files that navin-apply-update is allowed to install (navin_logic.safe_patch_path:
# NAVIN tools, NAVIN settings, NAVIN app entries) from build-iso/config/includes.chroot.
# Kernel, package or boot changes are NOT patchable: they need APT or a new ISO.
set -euo pipefail
N=${1:?patch number (greater than 20)}
[[ "$N" =~ ^[0-9]+$ ]] && [ "$N" -gt 40 ] || { echo "patch number must be > 40 (NAVIN 2.2 ISO is build 40)" >&2; exit 2; }
cd "$(dirname "$0")/../.."
python3 - "$N" <<'PY'
import importlib.util, io, pathlib, sys, tarfile
n = int(sys.argv[1]); root = pathlib.Path("build-iso/config/includes.chroot")
spec = importlib.util.spec_from_file_location("navin_logic", root / "usr/local/lib/navin/navin_logic.py")
logic = importlib.util.module_from_spec(spec); spec.loader.exec_module(logic)
files = [f for f in sorted(root.rglob("*")) if f.is_file() and not f.is_symlink() and "__pycache__" not in f.parts
         and logic.safe_patch_path(f.relative_to(root).as_posix()) and f.relative_to(root).as_posix() != "etc/navin/build"]
with tarfile.open("navin-update.tar.gz", "w:gz") as t:
    for f in files:
        info = t.gettarinfo(str(f), arcname=f.relative_to(root).as_posix()); info.uid = info.gid = 0; info.uname = info.gname = "root"
        with open(f, "rb") as body:
            t.addfile(info, body)
    data = f"{n}\n".encode(); info = tarfile.TarInfo("etc/navin/build"); info.size = len(data); info.mode = 0o644
    t.addfile(info, io.BytesIO(data))
print(f"navin-update.tar.gz: {len(files) + 1} files for {logic.update_tag(n)}")
PY
size=$(stat -c %s navin-update.tar.gz); [ "$size" -lt 104857600 ] || { echo "patch over 100 MB limit" >&2; exit 1; }
sha256sum navin-update.tar.gz | cut -d' ' -f1 > navin-update.tar.gz.sha256
echo "sha256 $(cat navin-update.tar.gz.sha256)"
