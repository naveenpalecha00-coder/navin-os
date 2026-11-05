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
lb build

ISO=$(ls -1 navin-os-amd64.hybrid.iso *.iso 2>/dev/null | head -n1)
[ -f "$ISO" ] || { echo "ISO not produced"; exit 1; }
mv -f "$ISO" navin-os-1.0-x86_64.iso
sha256sum navin-os-1.0-x86_64.iso | tee navin-os-1.0-x86_64.iso.sha256
ls -lh navin-os-1.0-x86_64.iso
