# NAVIN OS — ISO build

Debian 12 Bookworm `live-build` recipe that produces `navin-os-1.0-x86_64.iso` (hybrid: UEFI + Legacy BIOS, USB + DVD).

## Build locally (Debian 12 host, as root)
```bash
sudo ./build-iso/build.sh
```

## Build with Docker (any Linux)
```bash
docker run --rm --privileged -v "$PWD:/work" -w /work/build-iso debian:bookworm bash ./build.sh
```

## Build on GitHub
Push to `main` or run **Actions → Build NAVIN OS ISO → Run workflow**. The ISO and its `.sha256` are attached to a new GitHub Release.

## What's inside
- XFCE 4.18 + picom compositor, Arc-Dark / Papirus theme, NAVIN wallpaper
- Latest Mozilla Firefox from Mozilla's official signed APT repo (falls back to firefox-esr)
- NetworkManager, PipeWire, BlueZ, CUPS, UFW, non-free firmware (Intel/Realtek/Atheros/Broadcom/AMD)
- Calamares installer branded "Install NAVIN OS" (erase disk, dual boot, manual, USB target)
- ZRAM swap (50% RAM, zstd), trimmed background services
- Plymouth spinner splash with NAVIN logo, LightDM GTK greeter theme

## Test in QEMU
```bash
qemu-system-x86_64 -enable-kvm -m 4096 -smp 2 -cdrom navin-os-1.0-x86_64.iso -boot d
# UEFI: add -bios /usr/share/ovmf/OVMF.fd
```

<!-- build trigger: 2026-11-07 -->

## Build 8 source status (2026-11-08)
- Source syntax checks and rule tests pass; this is not a successful ISO build or hardware test.
- Build 8 release tag is explicit (`v1.0-build.8`); workflow packages ISO, checksum and configuration/tools OTA.
- OTA trusts the publisher repository and requires GitHub's asset SHA-256 digest; it does not accept an arbitrary caller checksum as authorization. It backs up files and rolls back caught write errors; power-loss atomicity is not guaranteed.
- NAVIN AI has five client endpoints but service `/v1/models` currently returns HTTP 404; root-owned per-device authorization is required and no shared secret is shipped.
- Idle RAM and compatibility targets need VM and physical hardware measurements. Calamares storage/password safety is retained, not replaced by a forced five-step/blank-password installer.
