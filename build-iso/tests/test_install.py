"""NAVIN OS 1.2 final: pinch zoom, pre-install advice, installer/boot-loader configuration rules."""
import importlib.util
import json
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
IC = ROOT / 'config/includes.chroot'
NAVIN = IC / 'usr/local/lib/navin'


def load(name):
    spec = importlib.util.spec_from_file_location(name, NAVIN / f'{name}.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sysl = load('navin_sys')
inst = load('navin_install')


def pinch(points, w=1000, h=1000):
    t = sysl.PinchTracker(w, h)
    return [t.update(a, b) for a, b in points]


class Pinch(unittest.TestCase):
    def test_spread_fingers_zooms_in_step_by_step(self):
        steps = pinch([((400 - d, 500), (600 + d, 500)) for d in range(0, 201, 10)])
        self.assertGreaterEqual(steps.count(1), 2)
        self.assertNotIn(-1, steps)

    def test_close_fingers_zooms_out(self):
        steps = pinch([((300 + d, 500), (700 - d, 500)) for d in range(0, 151, 10)])
        self.assertIn(-1, steps)
        self.assertNotIn(1, steps)

    def test_two_finger_scroll_never_zooms(self):
        steps = pinch([((400, 200 + y), (600, 210 + y)) for y in range(0, 500, 10)])
        self.assertEqual(set(steps), {0})

    def test_small_jitter_ignored(self):
        steps = pinch([((400 - (i % 2) * 5, 500), (600 + (i % 2) * 5, 500)) for i in range(30)])
        self.assertEqual(set(steps), {0})


LSBLK = json.dumps({"blockdevices": [
    {"name": "nvme0n1", "path": "/dev/nvme0n1", "size": 512110190592, "type": "disk", "rm": False, "tran": "nvme",
     "model": "Samsung SSD", "pttype": "gpt", "children": [
        {"name": "nvme0n1p1", "path": "/dev/nvme0n1p1", "size": 104857600, "type": "part", "fstype": "vfat"},
        {"name": "nvme0n1p3", "path": "/dev/nvme0n1p3", "size": 400000000000, "type": "part", "fstype": "BitLocker"}]},
    {"name": "sda", "path": "/dev/sda", "size": 16000000000, "type": "disk", "rm": True, "tran": "usb", "model": "USB", "pttype": "dos",
     "children": [{"name": "sda1", "path": "/dev/sda1", "size": 16000000000, "type": "part", "fstype": "iso9660"}]},
    {"name": "loop0", "path": "/dev/loop0", "size": 1, "type": "loop"}]})
PROBER = "/dev/nvme0n1p1@/EFI/Microsoft/Boot/bootmgfw.efi:Windows Boot Manager:Windows:efi\n"


def info(**kw):
    base = {"firmware": "uefi", "secure_boot": True, "ram_mb": 8000, "online": True, "on_battery": False,
            "disks": inst.parse_lsblk(LSBLK, "/dev/sda"), "oses": inst.parse_os_prober(PROBER)}
    base.update(kw)
    return base


def titles(advice):
    return {t for _, t, _ in advice}


class InstallAdvice(unittest.TestCase):
    def test_parse(self):
        disks = inst.parse_lsblk(LSBLK, "/dev/sda")
        self.assertEqual([d["name"] for d in disks], ["/dev/nvme0n1", "/dev/sda"])
        self.assertTrue(disks[1]["live"] and disks[1]["removable"])
        self.assertEqual(inst.parse_os_prober(PROBER)[0]["device"], "/dev/nvme0n1p1")

    def test_windows_keep_and_bitlocker(self):
        a = inst.assess(info())
        self.assertIn("Windows found — keep it", titles(a))
        self.assertIn("BitLocker encryption is on", titles(a))
        self.assertTrue(inst.can_install(a))

    def test_uefi_windows_but_usb_started_in_bios(self):
        self.assertIn("Wrong start mode for dual boot", titles(inst.assess(info(firmware="bios"))))
        self.assertNotIn("Wrong start mode for dual boot", titles(inst.assess(info())))

    def test_memory_limit_matches_installer(self):
        self.assertFalse(inst.can_install(inst.assess(info(ram_mb=1400))))
        self.assertTrue(inst.can_install(inst.assess(info(ram_mb=1900))))
        conf = (IC / 'usr/share/navin/calamares/welcome.conf').read_text()
        self.assertIn(f"requiredRam:        {inst.MIN_RAM_MB / 1024}", conf)
        self.assertIn(f"requiredStorage:    {inst.MIN_DISK_GB}", conf)

    def test_live_usb_is_never_an_install_target(self):
        only_usb = json.dumps({"blockdevices": [json.loads(LSBLK)["blockdevices"][1]]})
        a = inst.assess(info(disks=inst.parse_lsblk(only_usb, "/dev/sda"), oses=[]))
        self.assertFalse(inst.can_install(a))

    def test_battery_warning(self):
        self.assertIn("Running on battery", titles(inst.assess(info(on_battery=True))))


class InstallerConfig(unittest.TestCase):
    def test_uefi_also_installs_removable_fallback(self):
        s = (NAVIN / 'navin-grub-install').read_text()
        self.assertIn('--force-extra-removable', s)

    def test_offline_boot_loader_binaries_in_image(self):
        pk = (ROOT / 'config/package-lists/navin-os.list.chroot').read_text().split()
        for p in ('grub-efi-amd64-bin', 'grub-pc-bin', 'grub2-common', 'shim-signed', 'grub-efi-amd64-signed', 'qt6-qpa-plugins'):
            self.assertIn(p, pk)

    def test_dual_boot_menu_lists_other_systems(self):
        self.assertIn('GRUB_DISABLE_OS_PROBER=false', (IC / 'etc/default/grub.d/navin.cfg').read_text())
        self.assertIn('GRUB_DISABLE_OS_PROBER=false', (NAVIN / 'calamares-bootloader-config').read_text())

    def test_installed_system_loses_live_only_admin(self):
        s = (NAVIN / 'calamares-bootloader-config').read_text()
        self.assertIn('navin-nopasswd', s)

    def test_autotest_cannot_touch_real_disks(self):
        s = (NAVIN / 'navin-autotest').read_text()
        for guard in ('systemd-detect-virt -q --vm || exit 0', '[ -d /run/live ] || exit 0', 'NAVINTEST', 'virtio-NAVINTARGET',
                      'not blank', '64*1024*1024*1024'):
            self.assertIn(guard, s)
        unit = (IC / 'etc/systemd/system/navin-autotest.service').read_text()
        self.assertIn('ConditionVirtualization=vm', unit)

    def test_panel_plugins_have_their_packages(self):
        # VM test screenshot showed "power-manager-plugin could not be loaded" when the package was missing.
        panel = (IC / 'etc/skel/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-panel.xml').read_text()
        pk = (ROOT / 'config/package-lists/navin-os.list.chroot').read_text().split()
        pk += (IC / 'usr/share/navin/optional-packages.list').read_text().split()
        need = {'power-manager-plugin': 'xfce4-power-manager-plugins', 'whiskermenu': 'xfce4-whiskermenu-plugin',
                'pulseaudio': 'xfce4-pulseaudio-plugin', 'clipman': 'xfce4-clipman-plugin', 'xkb': 'xfce4-xkb-plugin',
                'genmon': 'xfce4-genmon-plugin'}
        for plugin, pkg in need.items():
            if f'value="{plugin}"' in panel:
                self.assertIn(pkg, pk, plugin)

    def test_window_previews_on_by_default(self):
        h = (ROOT / 'config/hooks/live/01-navin-os-customization.hook.chroot').read_text()
        self.assertIn('<property name="use_compositing" type="bool" value="true"/>', h)

    def test_installed_system_drops_live_autologin(self):
        s = (NAVIN / 'calamares-bootloader-config').read_text()
        self.assertIn("/^autologin-user=navin$/d", s)

    def test_hook_wires_installer(self):
        h = (ROOT / 'config/hooks/live/01-navin-os-customization.hook.chroot').read_text()
        self.assertIn('Exec=navin-install', h)
        self.assertIn('grubInstall: "/usr/local/lib/navin/navin-grub-install"', h)
        self.assertIn('calamares-bootloader-config', h)
        # Signed GRUB finds its config only in \EFI\debian; installer and CI test must use the same folder.
        self.assertIn('efiBootloaderId: "debian"', h)
        self.assertIn('--bootloader-id=debian', (NAVIN / 'navin-autotest').read_text())
        self.assertRegex(h, r'cycle_preview" type="bool" value="true"')


if __name__ == '__main__':
    unittest.main()
