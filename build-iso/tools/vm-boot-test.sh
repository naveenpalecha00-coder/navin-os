#!/bin/bash
# NAVIN OS 1.2 automated VM tests in QEMU/KVM (GitHub Actions). Usage: vm-boot-test.sh ISO OUTDIR
# Live boots of the real ISO through its own boot menu (default entry = Live Mode):
#   bios-2g   : legacy BIOS, 2 GB RAM (lite profile)
#   uefi-4g   : UEFI, 4 GB RAM (balanced profile)
#   uefi-sb   : UEFI with Secure Boot ON and Microsoft keys enrolled (q35 + SMM)
#   Pass = the booted system printed NAVIN_BOOT_OK on the serial port (navin-boot-ok.service, after
#   LightDM + Xorg + Xfce are up). A screenshot of each desktop is saved.
# Install tests (no network, so the boot loader must come from the ISO):
#   install-sb   : Secure Boot UEFI live session opens Calamares + Alt+Tab previews (screenshots), then
#                  navin-autotest installs to a blank disk; boot-installed-sb starts that disk alone with
#                  FRESH Secure Boot NVRAM (only the \EFI\BOOT fallback loader can start it).
#   install-bios : same install on legacy BIOS; boot-installed-bios starts that disk alone.
#   Installed pass = NAVIN_BOOT_OK with desktop=up, installed=yes, live packages removed, no live-only sudo.
set -u
ISO=$1; OUT=$2; mkdir -p "$OUT"; R="$OUT/results.env"
[ -e /dev/kvm ] || { echo "result_all=skipped-no-kvm" >> "$R"; exit 0; }
ACCEL="-enable-kvm -cpu host"
CODE=/usr/share/OVMF/OVMF_CODE_4M.fd; SBCODE=/usr/share/OVMF/OVMF_CODE_4M.secboot.fd; SBVARS=/usr/share/OVMF/OVMF_VARS_4M.ms.fd
key(){ echo "${1//-/_}"; }
shot(){ echo "screendump $1.ppm" | socat - "UNIX-CONNECT:$2" >/dev/null 2>&1; sleep 2
        command -v convert >/dev/null && [ -f "$1.ppm" ] && convert "$1.ppm" "$1.png" && rm -f "$1.ppm"; }
# vm NAME MEM LIMIT_S PASS_REGEX [qemu args...]
vm(){
  local name=$1 mem=$2 limit=$3 want=$4; shift 4
  local mon=/tmp/navin-mon-$name serial="$OUT/serial-$name.log" k; k=$(key "$name"); : > "$serial"
  timeout $((limit + 60)) qemu-system-x86_64 $ACCEL -m "$mem" -smp 2 -vga std -display none \
    -serial "file:$serial" -monitor "unix:$mon,server,nowait" "$@" &
  local pid=$! t=0 res=fail shots=""
  while [ $t -lt "$limit" ]; do
    sleep 5; t=$((t+5))
    for s in $(grep -a -o 'NAVIN_SHOT [a-z]*' "$serial" | awk '{print $2}'); do
      case " $shots " in *" $s "*) ;; *) shots="$shots $s"; shot "$OUT/screen-$name-$s" "$mon"; echo "$name: screenshot $s";; esac
    done
    if grep -a -qE "$want" "$serial"; then res=pass; sleep 5; break; fi
    grep -a -q "NAVIN_INSTALL_FAIL" "$serial" && break
    case $want in NAVIN_BOOT_OK?*) grep -a -q NAVIN_BOOT_OK "$serial" && { sleep 5; grep -a -qE "$want" "$serial" && res=pass; break; };; esac
    kill -0 $pid 2>/dev/null || break
  done
  kill -0 $pid 2>/dev/null && shot "$OUT/screen-$name" "$mon"
  kill $pid 2>/dev/null; wait $pid 2>/dev/null
  echo "result_$k=$res" >> "$R"; echo "time_$k=$t" >> "$R"
  grep -a -E "NAVIN_BOOT_OK|NAVIN_INSTALL_(OK|FAIL)" "$serial" | tail -1 | tr -d "\r'" | sed "s/^/detail_$k=/" >> "$R"
  echo "$name: $res after ${t}s"
}
cfgdisk(){ rm -f "$1"; truncate -s 4M "$1"; mkfs.vfat -n NAVINTEST "$1" >/dev/null; echo "$2" > /tmp/navin-mode; mcopy -i "$1" /tmp/navin-mode ::mode; }
DISK_ARGS(){ echo "-drive file=$1,format=raw,if=none,id=tgt -device virtio-blk-pci,drive=tgt,serial=NAVINTARGET"; }

# ---------- live boots ----------
vm bios-2g 2048 840 NAVIN_BOOT_OK -cdrom "$ISO" -boot d -nic user,model=virtio-net-pci
cp /usr/share/OVMF/OVMF_VARS_4M.fd /tmp/vars.fd
vm uefi-4g 4096 840 NAVIN_BOOT_OK -cdrom "$ISO" -boot d -nic user,model=virtio-net-pci -machine q35 \
  -drive if=pflash,format=raw,unit=0,file="$CODE",readonly=on -drive if=pflash,format=raw,unit=1,file=/tmp/vars.fd
cp "$SBVARS" /tmp/sbvars.fd
SBM="-machine q35,smm=on -global driver=cfi.pflash01,property=secure,value=on -drive if=pflash,format=raw,unit=0,file=$SBCODE,readonly=on"
vm uefi-sb 4096 840 NAVIN_BOOT_OK -cdrom "$ISO" -boot d -nic user,model=virtio-net-pci $SBM -drive if=pflash,format=raw,unit=1,file=/tmp/sbvars.fd

# ---------- install tests ----------
INST='NAVIN_BOOT_OK.*desktop=up.*installed=yes.*live_pkgs=removed.*nopasswd_sudo=absent'
truncate -s 24G /tmp/disk-sb.img; cfgdisk /tmp/cfg-sb.img install-ui; cp "$SBVARS" /tmp/sbvars-inst.fd
vm install-sb 4096 2400 NAVIN_INSTALL_OK -cdrom "$ISO" -boot d -nic none $SBM -drive if=pflash,format=raw,unit=1,file=/tmp/sbvars-inst.fd \
  -drive file=/tmp/cfg-sb.img,format=raw,if=none,id=cfg -device virtio-blk-pci,drive=cfg,serial=NAVINCFG $(DISK_ARGS /tmp/disk-sb.img)
if grep -q '^result_install_sb=pass' "$R"; then
  cp "$SBVARS" /tmp/sbvars-fresh.fd
  vm boot-installed-sb 4096 600 "$INST" -nic user,model=virtio-net-pci $SBM -drive if=pflash,format=raw,unit=1,file=/tmp/sbvars-fresh.fd $(DISK_ARGS /tmp/disk-sb.img)
else echo "result_boot_installed_sb=skipped" >> "$R"; fi
rm -f /tmp/disk-sb.img
truncate -s 24G /tmp/disk-bios.img; cfgdisk /tmp/cfg-bios.img install
vm install-bios 4096 2400 NAVIN_INSTALL_OK -cdrom "$ISO" -boot d -nic none \
  -drive file=/tmp/cfg-bios.img,format=raw,if=none,id=cfg -device virtio-blk-pci,drive=cfg,serial=NAVINCFG $(DISK_ARGS /tmp/disk-bios.img)
if grep -q '^result_install_bios=pass' "$R"; then
  vm boot-installed-bios 4096 600 "$INST" -nic user,model=virtio-net-pci -boot c $(DISK_ARGS /tmp/disk-bios.img)
else echo "result_boot_installed_bios=skipped" >> "$R"; fi
rm -f /tmp/disk-bios.img
exit 0
