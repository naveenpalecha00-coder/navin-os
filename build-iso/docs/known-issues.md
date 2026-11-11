# NAVIN OS 1.2 — known issues and limits (honest list)

- **Physical hardware.** Every release passes automatic live-boot, install and reboot tests in virtual machines,
  but has not yet been confirmed on physical computers. Build 10 (Debian 12) stays published for rollback.
- **Installer.** Calamares (Debian 13) with NAVIN branding, a NAVIN slideshow and a "Before you install" guide
  (start mode, Secure Boot, disks, Windows, BitLocker, battery). CI opens the real Calamares window and then runs
  the Calamares install steps through NAVIN's helpers on an empty disk; clicking through the Calamares pages
  themselves is not automated. The boot loader installs offline (GRUB, signed shim and signed GRUB ship in the
  image); the GRUB package that manages later GRUB updates is added at the first online start. In the PC's own
  firmware boot list the entry is named "debian" (Debian's signed GRUB needs that folder name); the NAVIN boot
  menu itself says NAVIN OS.
- **Dual boot.** Windows and other systems are listed in the boot menu (os-prober). The installer cannot shrink a
  BitLocker partition: turn BitLocker off or shrink in Windows first. The USB must start in the same mode
  (UEFI or Legacy) as Windows; the install guide warns when it does not.
- **Secure Boot.** The ISO boots through Debian's Microsoft-signed shim and signed kernel. Unsigned extras do
  not load under Secure Boot: memtest86+ (EFI), and DKMS modules such as the NVIDIA proprietary driver until a MOK
  key is enrolled (Debian prompts for this during installation of the driver).
- **Liquorix removed.** It is not signed for Secure Boot; NAVIN 1.2 uses the Debian kernel only.
- **Gestures.** touchegg is not in Debian 13. NAVIN's own gesture service handles 3-finger swipes and 2-finger
  pinch zoom (sent as Ctrl+= / Ctrl+-, so it zooms in browsers, file manager, image viewers, office apps).
  Pinch needs a multi-touch touchpad; turn it off with `navin-touchpad pinch off`. Rotate gestures are not supported.
- **Window previews.** Alt+Tab shows a live picture of each window with the default xfwm4 compositor. The 2 GB
  profile, Turbo mode and the optional picom mode (rounded corners; "Window Effects" in the menu) show icons only.
  Minimised windows show their last picture or icon.
- **App-specific shortcuts.** Xfce has no per-application global shortcut layer; the shortcut editor manages
  global shortcuts only.
- **Windows programs.** Wine runs many but not all .exe files. Anti-cheat games, drivers and some installers fail.
- **Fan control.** Only firmware-exposed interfaces are used. Many laptops expose none, so fan control is
  monitoring-only there. NAVIN never stops a fan or slows it below BIOS control.
- **Touchpad latency** cannot be measured automatically; use `sudo libinput measure` manually.
- **Download speed** depends on GitHub's CDN and your connection. Browser downloads from GitHub support resume.


## NAVIN 2.0
- Samsung RV411: if the cursor does not move, press Fn+F5 once (hardware touchpad switch), then run `navin-touchpad rescue` or choose "Old Laptop Mode" at boot.
- The fan slider cannot change fan speed on laptops whose BIOS hides the fan from Linux; it limits CPU speed (less heat) instead and says so.
- Boot-time goal ~10 s is realistic on an SSD; on the RV411's original hard disk expect longer. Measure with `systemd-analyze`.
