#!/bin/bash
# NAVIN OS 1.2 automated boot test in QEMU/KVM (GitHub Actions). Usage: vm-boot-test.sh ISO OUTDIR
# Boots the real ISO through its own boot menu (default entry = Live Mode) in three machines:
#   bios-2g   : legacy BIOS, 2 GB RAM (lite profile)
#   uefi-4g   : UEFI, 4 GB RAM (balanced profile)
#   uefi-sb   : UEFI with Secure Boot ON and Microsoft keys enrolled (q35 + SMM)
# Pass = the booted system printed NAVIN_BOOT_OK on the serial port (written by navin-boot-ok.service
# after LightDM + Xorg + Xfce are up). A screenshot of each desktop is saved.
set -u
ISO=$1; OUT=$2; mkdir -p "$OUT"
[ -e /dev/kvm ] || { echo "result_all=skipped-no-kvm" >> "$OUT/results.env"; exit 0; }
ACCEL="-enable-kvm -cpu host"
CODE=/usr/share/OVMF/OVMF_CODE_4M.fd; SBCODE=/usr/share/OVMF/OVMF_CODE_4M.secboot.fd; SBVARS=/usr/share/OVMF/OVMF_VARS_4M.ms.fd
run(){
  local name=$1 mem=$2; shift 2
  local mon=/tmp/navin-mon-$name serial="$OUT/serial-$name.log"; : > "$serial"
  timeout 900 qemu-system-x86_64 $ACCEL -m "$mem" -smp 2 -vga std -display none -cdrom "$ISO" -boot d \
    -serial "file:$serial" -monitor "unix:$mon,server,nowait" -nic user,model=virtio-net-pci "$@" &
  local pid=$! t=0 res=fail
  while [ $t -lt 840 ]; do
    sleep 10; t=$((t+10))
    if grep -q NAVIN_BOOT_OK "$serial"; then res=pass; sleep 5; break; fi
    kill -0 $pid 2>/dev/null || break
  done
  echo "screendump $OUT/screen-$name.ppm" | socat - "UNIX-CONNECT:$mon" >/dev/null 2>&1; sleep 2
  command -v convert >/dev/null && convert "$OUT/screen-$name.ppm" "$OUT/screen-$name.png" && rm -f "$OUT/screen-$name.ppm"
  kill $pid 2>/dev/null; wait $pid 2>/dev/null
  echo "result_${name//-/_}=$res" >> "$OUT/results.env"
  echo "time_${name//-/_}=$t" >> "$OUT/results.env"
  grep -a NAVIN_BOOT_OK "$serial" | tail -1 | tr -d '\r' | sed "s/^/detail_${name//-/_}=/" >> "$OUT/results.env"
  echo "$name: $res after ${t}s"
}
run bios-2g 2048
cp "$CODE" /tmp/code.fd 2>/dev/null; cp /usr/share/OVMF/OVMF_VARS_4M.fd /tmp/vars.fd
run uefi-4g 4096 -machine q35 -drive if=pflash,format=raw,unit=0,file="$CODE",readonly=on -drive if=pflash,format=raw,unit=1,file=/tmp/vars.fd
cp "$SBVARS" /tmp/sbvars.fd
run uefi-sb 4096 -machine q35,smm=on -global driver=cfi.pflash01,property=secure,value=on \
  -drive if=pflash,format=raw,unit=0,file="$SBCODE",readonly=on -drive if=pflash,format=raw,unit=1,file=/tmp/sbvars.fd
exit 0
