# NAVIN OS 1.2 — known issues and limits (honest list)

- **Test build.** Not validated on physical hardware yet. Build 10 (Debian 12) stays published for daily use and rollback.
- **Installer.** Calamares (Debian 13 settings, NAVIN branding) is unchanged from Debian's stock modules; a full
  automated installation test is not part of CI. On some machines the bootloader step may download GRUB packages,
  so keep the internet connected during installation.
- **Secure Boot.** The ISO boots through Debian's Microsoft-signed shim and signed kernel. Unsigned extras do
  not load under Secure Boot: memtest86+ (EFI), and DKMS modules such as the NVIDIA proprietary driver until a MOK
  key is enrolled (Debian prompts for this during installation of the driver).
- **Liquorix removed.** It is not signed for Secure Boot; NAVIN 1.2 uses the Debian kernel only.
- **Gestures.** touchegg is not in Debian 13. NAVIN's own gesture service supports 3-finger swipes only
  (no pinch/zoom gestures).
- **Window previews.** Alt+Tab shows window names/icons; live thumbnails are not available with the picom setup.
- **App-specific shortcuts.** Xfce has no per-application global shortcut layer; the shortcut editor manages
  global shortcuts only.
- **Windows programs.** Wine runs many but not all .exe files. Anti-cheat games, drivers and some installers fail.
- **Fan control.** Only firmware-exposed interfaces are used. Many laptops expose none, so fan control is
  monitoring-only there. NAVIN never stops a fan or slows it below BIOS control.
- **Touchpad latency** cannot be measured automatically; use `sudo libinput measure` manually.
- **Download speed** depends on GitHub's CDN and your connection. Browser downloads from GitHub support resume.
