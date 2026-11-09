# NAVIN OS

**Your PC. Your OS. Your Freedom.** — by Navin Palecha

A lightweight Debian 12 (Bookworm) based Linux distribution for 4 GB RAM PCs, with an XFCE desktop, the latest Mozilla Firefox, and the Calamares graphical installer. Boots on UEFI and Legacy BIOS.

## Download
Latest ISO: https://github.com/naveenpalecha00-coder/navin-os/releases/latest/download/navin-os-1.0-x86_64.iso

The SHA-256 checksum is published in each release. Verify:
- Linux/macOS: `sha256sum navin-os-1.0-x86_64.iso`
- Windows: `Get-FileHash .\navin-os-1.0-x86_64.iso -Algorithm SHA256`

## Build it yourself
See [build-iso/README.md](build-iso/README.md). Every push to `main` touching `build-iso/` rebuilds the ISO via GitHub Actions.

## Status
- [Implemented in Code] live-build recipe, hook, branding, workflow
- [Build Passed] — see the Actions tab
- [Tested in VM / QEMU] — pending
- [Validated on Physical Hardware] — pending

## License
NAVIN OS custom configuration: MIT. Bundled software keeps its own licenses (Linux kernel GPLv2, Debian, Calamares GPLv3, XFCE GPL/LGPL, Firefox MPL 2.0).
