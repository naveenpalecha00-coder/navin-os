# NAVIN OS 1.2 — hardware compatibility (Debian 13 Trixie base)

Status legend: **Supported by drivers in the image** means the kernel/firmware/packages are present and
NAVIN's detection selects them. It does **not** mean NAVIN has tested that exact model. Real-hardware
results are added to this file only after someone reports a test.

| Area | What the image contains | How NAVIN selects it | Tested on real hardware |
|---|---|---|---|
| Kernel | Debian 13 signed kernel (6.12 LTS series) | single kernel; Safe Graphics entry as fallback | not yet |
| CPU | Intel & AMD microcode, intel_pstate/amd-pstate, cpupower | `navin-power` profiles + TLP auto | not yet |
| Intel graphics | i915/xe, Mesa, intel-media-va-driver (+ i965 offered) | Driver Manager offers missing VA-API driver | not yet |
| AMD graphics | amdgpu/radeon, firmware-amd-graphics, Mesa VA-API, RADV Vulkan | automatic | not yet |
| NVIDIA graphics | Nouveau (+ firmware-nvidia-graphics if it fits the image) | proprietary driver offered only when `nvidia-detect` supports the GPU; Secure Boot needs MOK enrollment | not yet |
| Touchpads | libinput; i2c_hid_acpi, hid_multitouch, psmouse (Synaptics/ELAN/ALPS PS/2, SMBus/RMI4), elan_i2c | `navin-hwdetect` reads ACPI (PNP0C50, ELAN, SYNA, ALPS…) and input devices; loads missing in-kernel drivers; resume recovery | not yet |
| Gestures | 3-finger swipes via `navin-gestures` (evdev + uinput) | needs a touchpad reporting 3 fingers (BTN_TOOL_TRIPLETAP) | not yet |
| Wi-Fi / Bluetooth | Intel, Realtek, Atheros, Broadcom (brcm80211), MediaTek (misc-nonfree) firmware | kernel autoload | not yet |
| Audio | PipeWire + WirePlumber, SOF firmware, ALSA UCM | kernel autoload; mic fix tool | not yet |
| Fans | thinkpad_acpi (fan_control=1), dell_smm_hwmon, hwmon PWM, ACPI platform_profile | `navin-fan`; monitoring-only when no safe interface | not yet |
| Boot | GRUB EFI via Microsoft-signed shim (Secure Boot), ISOLINUX for legacy BIOS | Live Mode / Full Installation / Safe Graphics | VM only (see build report) |

## Report a test
Run `navin-hwdetect > hw.txt` and `navin-benchmark run`, then open a GitHub issue with both files and
what worked or failed.
