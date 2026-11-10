#!/bin/bash
# Build NAVIN OS ISO. Run as root on Debian 12 (or inside `debian:bookworm` docker with --privileged).
set -euo pipefail
cd "$(dirname "$0")"

apt-get update
apt-get install -y live-build debootstrap squashfs-tools xorriso grub-pc-bin grub-efi-amd64-bin \
  mtools dosfstools syslinux syslinux-common isolinux ca-certificates wget

chmod +x auto/* config/hooks/live/* config/includes.chroot/usr/local/bin/* config/includes.chroot/usr/local/sbin/* config/includes.chroot/usr/local/lib/navin/*
lb clean --purge || true
lb config
# Build 9 size guard: 1 MiB xz blocks + x86 BCJ filter shrink the squashfs (Build 8 was 2.06 GB of a 2.147 GB limit).
export MKSQUASHFS_OPTIONS="-b 1M -Xbcj x86"
lb build

ISO=$(find . -maxdepth 1 -type f -name "*.iso" -print -quit)
[ -f "$ISO" ] || { echo "ISO not produced"; exit 1; }
if [ "$ISO" != "./navin-os-1.0-x86_64.iso" ]; then mv -f "$ISO" navin-os-1.0-x86_64.iso; fi
sha256sum navin-os-1.0-x86_64.iso | tee navin-os-1.0-x86_64.iso.sha256
ls -lh navin-os-1.0-x86_64.iso
