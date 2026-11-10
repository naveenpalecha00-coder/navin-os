# NAVIN USB Creator

Native tools that create bootable NAVIN OS USB drives.

| App | Folder | Output |
| --- | --- | --- |
| Windows 10/11 (WinForms, .NET 8, single-file) | `windows/` | `navin-usb-creator-<version>-win-x64.exe` |
| Android 7.0+ (Kotlin, Jetpack Compose) | `android/` | `navin-usb-creator-<version>.apk` |

The version lives in `VERSION`. Pushing to `usb-creator/**` runs `.github/workflows/usb-creator.yml`, which
runs the unit tests, builds both apps and publishes the release `usb-creator-v<version>` with SHA-256 sums.
The release is never marked "latest", so `releases/latest` keeps pointing at the newest NAVIN OS ISO.

## How writing works
- **Disk image mode** (Windows + Android): the image is copied byte-for-byte. The first 1 MiB (partition tables)
  is written last, so a cancelled or unplugged drive never looks valid. Hybrid ISOs boot on UEFI and Legacy BIOS.
- **Extract mode** (Windows only): diskpart creates one FAT32 partition (GPT or MBR, max 32 GB) and the ISO's files
  are copied. Boots on UEFI only; requires `EFI\BOOT\BOOTX64.EFI`, refuses files over 4 GB.
- **Verify**: the drive is read back and compared with the image (SHA-256).
- **Android**: talks to the drive with SCSI commands over USB Bulk-Only Transport through the public USB Host API.
  No root. Only external USB devices are reachable, so internal storage can never be written. Includes a FAT32 formatter.

## Safety rules
- Windows lists only USB/SD disks (MSFT_Disk BusType 7/12/13) and hides system, boot, read-only and Windows-drive disks.
- The user sees the exact drive name and capacity before erasing. Windows: type `ERASE` (the drive is re-checked before writing). Android: one confirmation tap, then the app erases old partition tables (start and backup GPT at the end), writes, verifies and makes the drive bootable.
- Android retries drives that report UNIT ATTENTION / becoming ready, shrinks transfer size for drives or OTG adapters that stall, and stops with a clear message for write-protected drives.

## Signing
- Android: release key from repository secrets `ANDROID_KEYSTORE_B64` / `ANDROID_KEYSTORE_PASSWORD` (alias `navin`).
- Windows: not code-signed yet (needs a purchased code-signing certificate).

## Testing status
Unit tests run in CI. Real-hardware testing (Windows 10/11, GPT/MBR, UEFI/Legacy, Android OTG phones) has not been done yet.
