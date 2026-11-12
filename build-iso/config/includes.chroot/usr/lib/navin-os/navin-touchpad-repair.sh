#!/bin/bash
# NAVIN 2.2.1 automatic touchpad repair engine (root; started at boot by navin-touchpad-repair.service,
# after resume by system-sleep/navin-input, and from Settings › Touchpad through pkexec).
#   run [--boot|--resume]  diagnose -> run only the safe actions for the exact state -> verify with a fresh scan
#   rescan                 FORCE HARDWARE RESCAN: udev re-trigger of input/serio/hid/i2c, no driver unload
#   reload                 reload the touchpad's own kernel module (psmouse or i2c_hid_acpi/hid_multitouch)
#   driver update|reinstall|rollback|restore-default   libinput driver packages / NAVIN touchpad overrides
#   status | report        current state | full diagnostic report -> /var/log/navin/touchpad-report.txt
# Rules: one pass per call (no loops), psmouse is only reloaded when no touchpad answers, keyboard (atkbd)
# and USB mice are never touched, every file change is backed up first, success only after a real scan.
set -u
TP=/usr/local/lib/navin/navin_tp.py
LOGD=/var/log/navin; LOG=$LOGD/touchpad-repair.log; STATUS=/run/navin/touchpad-status.json
SAVE=/etc/modprobe.d/navin-touchpad-rescue.conf; QUIRK=/etc/default/grub.d/90-navin-quirks.cfg
BACKUP=/var/lib/navin/backup/touchpad
mkdir -p "$LOGD" /run/navin "$BACKUP"
log(){ echo "$(date '+%F %T') $*" >> "$LOG"; echo "$*"; }
[ "$(id -u)" = 0 ] || { echo "run as root: pkexec $0 ${1:-run}" >&2; exit 1; }
LIVE=0; [ -d /run/live ] && LIVE=1
scan(){ python3 "$TP" diagnose --json > "$STATUS.tmp" 2>/dev/null && mv "$STATUS.tmp" "$STATUS"; python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["state"])' "$STATUS" 2>/dev/null || echo unknown; }
summary(){ python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["summary"])' "$STATUS" 2>/dev/null; }
good(){ case "$1" in ok|basic|disabled|not-laptop) return 0;; esac; return 1; }
backup(){ local d="$BACKUP/$(date +%Y%m%d-%H%M%S)"; mkdir -p "$d"; for f in "$@"; do [ -f "$f" ] && cp -a "$f" "$d/"; done; echo "$d" > "$BACKUP/last"; log "backup: $d"; }
present(){ grep -qiE 'Phys=isa0060/serio[1-9]|touchpad|trackpad|glidepoint' /proc/bus/input/devices; }
aux_ports(){ for s in /sys/bus/serio/devices/serio*; do grep -qs AUX "$s/description" && echo "$s"; done; }

act(){
  case "$1" in
    load-modules)
      for m in psmouse i2c_designware_platform i2c_hid_acpi hid_multitouch; do
        grep -q "^$m " /proc/modules || { modinfo "$m" >/dev/null 2>&1 && modprobe "$m" 2>/dev/null && log "loaded $m"; }
      done; sleep 1;;
    aux-reconnect)
      for s in $(aux_ports); do echo -n reconnect > "$s/drvctl" 2>/dev/null && log "reconnect ${s##*/}"; done; sleep 2;;
    psmouse-reload)
      present && return 0  # never drop a working pointer
      modprobe -r psmouse 2>/dev/null; modprobe psmouse; log "psmouse reloaded (native protocol)"; sleep 2;;
    psmouse-fallback)
      present && return 0
      for proto in exps imps bare; do
        modprobe -r psmouse 2>/dev/null; modprobe psmouse proto=$proto; sleep 2
        if present; then
          log "touchpad answers in basic PS/2 mode proto=$proto (move, click, tap, wheel)"
          if [ $LIVE = 0 ]; then backup "$SAVE"; printf '# NAVIN touchpad repair: native protocol did not answer on this laptop\noptions psmouse proto=%s\n' "$proto" > "$SAVE"; log "saved $SAVE (undo: Settings › Touchpad › Roll back)"; fi
          return 0
        fi
      done
      modprobe -r psmouse 2>/dev/null; modprobe psmouse;;
    i2c-reload)
      modprobe -r hid_multitouch i2c_hid_acpi 2>/dev/null; modprobe i2c_hid_acpi; modprobe hid_multitouch; log "I2C-HID touchpad drivers reloaded"; sleep 2;;
    boot-fix)
      [ $LIVE = 1 ] && { log "Live Mode: boot options cannot be saved; use the legacy-BIOS boot menu or add i8042.nopnp=1 i8042.noloop=1"; return 0; }
      [ -d /etc/default/grub.d ] || return 0
      grep -q 'i8042.nopnp=1' "$QUIRK" 2>/dev/null && grep -q 'i8042.nopnp=1' /proc/cmdline && return 0
      backup "$QUIRK"
      printf '# NAVIN touchpad repair: probe the PS/2 touchpad port directly (BIOS ACPI did not list it)\nGRUB_CMDLINE_LINUX_DEFAULT="$GRUB_CMDLINE_LINUX_DEFAULT i8042.nomux=1 i8042.reset=1 i8042.nopnp=1 i8042.noloop=1"\n' > "$QUIRK"
      rm -f /etc/navin/quirks-off
      update-grub >/dev/null 2>&1 && log "boot fix written (i8042.nopnp=1 i8042.noloop=1) - restart needed" || log "update-grub failed";;
    *) log "refused unknown action: $1";;
  esac
}

repair(){
  local st before; st=$(scan); before=$st
  log "scan ($1): $st - $(summary)"
  if good "$st"; then exit 0; fi
  for a in $(python3 "$TP" actions 2>/dev/null); do
    act "$a"; st=$(scan); log "after $a: $st"
    good "$st" && break
  done
  if good "$st"; then log "VERIFIED: $(summary)"; notify "Touchpad repaired" "$(summary)"; exit 0; fi
  if grep -q 'restart needed' <(tail -3 "$LOG"); then notify "Touchpad: restart needed" "NAVIN added the touchpad port fix to the boot menu. Restart once."; exit 4; fi
  log "NOT FIXED ($before -> $st): $(summary)"
  python3 -c 'import json,sys
for p in json.load(open(sys.argv[1]))["problems"]: print("  problem:",p["problem"],"| cause:",p["cause"],"| fix:",p["fix"])' "$STATUS" | tee -a "$LOG"
  exit 3
}
notify(){ # to the logged-in desktop user, if any
  local u; u=$(loginctl list-sessions --no-legend 2>/dev/null | awk '$3!="lightdm"{print $3; exit}')
  [ -n "$u" ] && sudo -u "$u" DISPLAY=:0 DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$(id -u "$u")/bus" notify-send -i input-touchpad "$1" "$2" 2>/dev/null || true
}

case "${1:-run}" in
  run) repair "${2:---manual}";;
  rescan)
    log "force hardware rescan"
    udevadm trigger --action=change --subsystem-match=input --subsystem-match=serio --subsystem-match=hid --subsystem-match=i2c 2>/dev/null
    udevadm settle -t 10 2>/dev/null
    present || for s in $(aux_ports); do echo -n rescan > "$s/drvctl" 2>/dev/null; done; sleep 2
    st=$(scan); log "rescan result: $st - $(summary)"; good "$st"; exit $?;;
  reload)
    bus=$(python3 -c 'import json,sys;d=json.load(open(sys.argv[1]))["devices"];print(d[0]["bus"] if d else "")' "$STATUS" 2>/dev/null)
    case "$bus" in
      I2C|USB) act i2c-reload;;
      *) modprobe -r psmouse 2>/dev/null; modprobe psmouse; log "psmouse reloaded on request"; sleep 2;;
    esac
    st=$(scan); log "reload result: $st"; good "$st"; exit $?;;
  driver)
    P="xserver-xorg-input-libinput libinput10 libinput-bin"
    case "${2:-}" in
      update) log "driver update: $P"; apt-get update -qq && apt-get install -y --only-upgrade $P 2>&1 | tail -3 | tee -a "$LOG";;
      reinstall) log "driver reinstall: $P"; apt-get install -y --reinstall $P 2>&1 | tail -3 | tee -a "$LOG";;
      rollback) d=$(cat "$BACKUP/last" 2>/dev/null); [ -d "$d" ] || { echo "no backup to roll back to"; exit 3; }
        rm -f "$SAVE"; for f in "$d"/*; do [ -f "$f" ] || continue; case "${f##*/}" in navin-touchpad-rescue.conf) cp -a "$f" "$SAVE";; 90-navin-quirks.cfg) cp -a "$f" "$QUIRK"; update-grub >/dev/null 2>&1;; esac; done
        log "rolled back to $d";;
      restore-default) backup "$SAVE"; rm -f "$SAVE"; log "NAVIN touchpad overrides removed (native psmouse protocol next boot)";
        [ $LIVE = 0 ] && update-initramfs -u >/dev/null 2>&1 &;;
      *) echo "driver update|reinstall|rollback|restore-default" >&2; exit 2;;
    esac; exit 0;;
  status) st=$(scan); echo "$st: $(summary)"; good "$st";;
  report)
    R=$LOGD/touchpad-report.txt
    { echo "NAVIN touchpad report $(date)"; python3 "$TP" info; echo; echo "== /proc/bus/input/devices"; cat /proc/bus/input/devices
      echo "== libinput list-devices"; timeout 10 libinput list-devices 2>&1; echo "== kernel log (input)"; journalctl -k -b 0 -q -o cat | grep -iE 'i8042|psmouse|serio|elantech|synaptics|alps|i2c_hid|rmi4|input:' | tail -80
      echo "== lsusb"; lsusb; echo "== lspci"; lspci -nn | grep -iE 'smbus|serial bus|i2c'; echo "== udevadm"; for e in /dev/input/event*; do udevadm info -q property "$e" | grep -E 'NAME=|ID_INPUT_TOUCHPAD=1|ID_PATH=' | tr '\n' ' '; echo; done
      echo "== repair log"; tail -60 "$LOG"; } > "$R" 2>&1; chmod 644 "$R"; echo "$R";;
  *) echo "usage: $0 run|rescan|reload|driver update|reinstall|rollback|restore-default|status|report" >&2; exit 2;;
esac
