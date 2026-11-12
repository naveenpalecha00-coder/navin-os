#!/bin/bash
# Build NAVIN XP 3.1 ISO. Run as root on Debian 13 (or inside `debian:trixie` docker with --privileged).
set -euo pipefail
cd "$(dirname "$0")"

apt-get update
apt-get install -y live-build debootstrap squashfs-tools xorriso grub-pc-bin grub-efi-amd64-bin \
  grub-efi-amd64-signed shim-signed mtools dosfstools syslinux syslinux-common isolinux ca-certificates wget python3

chmod +x auto/* config/hooks/live/* config/includes.chroot/usr/local/bin/* config/includes.chroot/usr/local/sbin/* config/includes.chroot/usr/local/lib/navin/* config/includes.chroot/usr/lib/systemd/system-sleep/*
lb clean --purge || true
lb config
# 1 MiB xz blocks + x86 BCJ filter keep the squashfs under GitHub's 2 GiB asset limit.
export MKSQUASHFS_OPTIONS="-b 1M -Xbcj x86"
lb build

ISO=$(find . -maxdepth 1 -type f -name "*.iso" -print -quit)
[ -f "$ISO" ] || { echo "ISO not produced"; exit 1; }
if [ "$ISO" != "./navin-xp-3.1-x86_64.iso" ]; then mv -f "$ISO" navin-xp-3.1-x86_64.iso; fi
sha256sum navin-xp-3.1-x86_64.iso | tee navin-xp-3.1-x86_64.iso.sha256
# Reports produced inside the image (package manifest, kernel, missing optional packages, base)
mkdir -p reports; cp -a chroot/usr/share/navin/reports/. reports/ 2>/dev/null || true
ls -lh navin-xp-3.1-x86_64.iso
