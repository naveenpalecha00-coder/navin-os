# NAVIN XP: explain the text screen when the desktop could not start (written by navin-display-guard).
if [ -z "$DISPLAY" ] && [ "$(tty 2>/dev/null)" = /dev/tty1 ]; then
  if [ -f /run/navin/display-failed ]; then
    printf '\nNAVIN XP: the desktop could not start with any graphics driver.\n  Errors: /var/log/Xorg.0.log   Guard log: /var/log/navin/display-guard.log\n  Try: restart and choose "Safe Graphics" in the boot menu, or run: sudo navin-display-guard reset\n\n'
  elif ! pgrep -x Xorg >/dev/null 2>&1; then
    printf '\nNAVIN XP: the desktop is still starting (the display guard is checking the graphics driver).\n  If it does not appear within 2 minutes press Ctrl+Alt+F7, or run: sudo systemctl restart lightdm\n\n'
  fi
fi
