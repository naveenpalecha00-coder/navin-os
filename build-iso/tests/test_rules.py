import importlib.util
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
IC = ROOT / 'config/includes.chroot'


def load(name):
    spec = importlib.util.spec_from_file_location(name, IC / f'usr/local/lib/navin/{name}.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


logic = load('navin_logic')


class Rules(unittest.TestCase):
    def test_build(self):
        self.assertEqual(logic.BUILD, 50)
        self.assertEqual(logic.VERSION, '3.0')
        self.assertEqual(logic.release_build('v2.0-update.21'), 21)
        # Debian 12 patches are a different base and are never applied to NAVIN 2.0.
        self.assertIsNone(logic.release_build('v1.0-build.10'))
        self.assertIsNone(logic.release_build('v1.2-trixie-test'))
        self.assertIsNone(logic.release_build('v2.0'))

    def test_hold(self):
        self.assertEqual(logic.HOLD_SECONDS, 5)

    def test_voices(self):
        self.assertEqual(logic.VOICES, ('Kore', 'Puck', 'Charon', 'Aoede', 'Fenrir', 'Leda'))

    def test_image_sizes(self):
        self.assertEqual(logic.IMAGE_SIZES, ('1024x1024', '1536x1024'))

    def test_patch_safety(self):
        self.assertTrue(logic.safe_patch_path('usr/local/bin/navin-updater'))
        for value in ('../etc/passwd', '/etc/passwd', 'etc/navin/build-evil', 'etc/xdg/picom.conf.evil'):
            self.assertFalse(logic.safe_patch_path(value), value)

    def test_tuning(self):
        config = (IC / 'etc/sysctl.d/98-navin-speed.conf').read_text()
        values = dict(re.findall(r'([\w.]+)\s*=\s*(\d+)', config))
        self.assertEqual(values['vm.dirty_background_bytes'], '16777216')
        self.assertEqual(values['vm.dirty_bytes'], '50331648')
        self.assertEqual(values['vm.vfs_cache_pressure'], '50')
        self.assertEqual(values['vm.swappiness'], '100')

    def test_tools_present(self):
        for tool in ('navin-turbo', 'navin-quick-share', 'navin-recorder', 'navin-vault', 'navin-snapshot', 'navin-theme',
                     'navin-pill', 'navin-exe-helper', 'navin-hwdetect', 'navin-touchpad', 'navin-power', 'navin-center',
                     'navin-benchmark', 'navin-shortcuts'):
            self.assertTrue((IC / 'usr/local/bin' / tool).is_file(), tool)

    def test_debian13_base(self):
        self.assertIn('--distribution trixie', (ROOT / 'auto/config').read_text())
        self.assertNotIn('bookworm', (ROOT / 'auto/config').read_text())
        pkgs = [w for line in (ROOT / 'config/package-lists/navin-os.list.chroot').read_text().splitlines() for w in line.split('#', 1)[0].split()]
        for gone in ('policykit-1', 'neofetch'):
            self.assertNotIn(gone, pkgs)
        for needed in ('shim-signed', 'grub-efi-amd64-signed', 'pkexec'):
            self.assertIn(needed, pkgs)
        hook = (ROOT / 'config/hooks/live/01-navin-os-customization.hook.chroot').read_text()
        self.assertNotIn('liquorix.net', hook)

    def test_light_theme_default(self):
        self.assertIn('case "${1:-light}" in', (IC / 'usr/local/bin/navin-theme').read_text())

    def test_live_only_passwordless_admin(self):
        script = (IC / 'usr/local/sbin/navin-live-user').read_text()
        self.assertIn('if [ ! -d /run/live ]; then', script)
        self.assertLess(script.index('/run/live'), script.index('useradd'))

    def test_exe_never_silent(self):
        self.assertIn('zenity --list', (IC / 'usr/local/bin/navin-exe-run').read_text())

    def test_fan_never_below_firmware(self):
        fan = (IC / 'usr/local/lib/navin/navin-fan').read_text()
        self.assertIn("trap 'restore' ERR", fan)
        self.assertNotRegex(fan, r'echo 0 > "\$p"')

    def test_memprofile_thresholds_match_python(self):
        hw = load('navin_hw')
        sh = (IC / 'usr/local/sbin/navin-memprofile').read_text()
        self.assertIn('-le 2726297', sh)
        self.assertIn('-le 6815744', sh)
        self.assertEqual(hw.ram_profile(2726297), ('lite', 100))
        self.assertEqual(hw.ram_profile(2726298 + 1048576), ('balanced', 75))
        self.assertEqual(hw.ram_profile(6815745), ('standard', 50))


if __name__ == '__main__':
    unittest.main()
