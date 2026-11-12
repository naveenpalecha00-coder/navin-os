"""NAVIN 2.0: old-laptop quirks (Samsung RV411 class), fan slider safety, update channel, What's New list."""
import importlib.util
import json
import pathlib
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
REPO = ROOT.parent
IC = ROOT / 'config/includes.chroot'


def load(name):
    spec = importlib.util.spec_from_file_location(name, IC / f'usr/local/lib/navin/{name}.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


hw = load('navin_hw')
logic = load('navin_logic')
SAMSUNG = {'sys_vendor': 'SAMSUNG ELECTRONICS CO., LTD.', 'product_name': 'RV411/RV511/E3511/S3511/RV711'}
IRONLAKE = {'vendor': '8086', 'device': '0046', 'class': 'gpu'}
OLD_FLAGS = 'fpu sse sse2 ssse3 sse4_1 sse4_2 popcnt'.split()
NEW_FLAGS = OLD_FLAGS + ['avx', 'avx2']


class OldLaptop(unittest.TestCase):
    def test_samsung_rv411_gets_touchpad_controller_fix(self):
        q = hw.laptop_quirks(SAMSUNG, [IRONLAKE], OLD_FLAGS, 2 * 1024 * 1024, rotational=True)
        self.assertTrue(q['samsung'])
        self.assertEqual(q['kernel_params'], ['i8042.nomux=1', 'i8042.reset=1', 'i8042.nopnp=1', 'i8042.noloop=1'])
        self.assertTrue(any('Fn+F5' in n for n in q['notes']))

    def test_rv411_class_hardware_gets_no_freeze_settings(self):
        q = hw.laptop_quirks(SAMSUNG, [IRONLAKE], OLD_FLAGS, 4 * 1024 * 1024, rotational=True)
        self.assertEqual(q['xorg_driver'], 'intel-sna')
        self.assertEqual(q['compositor'], 'lite')
        self.assertEqual(q['zram_algo'], 'lz4')
        self.assertEqual(q['chrome_gpu'], 'safe')
        self.assertEqual(q['io_scheduler'], 'bfq')
        self.assertEqual(q['sata_alpm'], 'max_performance')
        self.assertFalse(q['battery_turbo'])

    def test_modern_non_samsung_laptop_keeps_defaults(self):
        q = hw.laptop_quirks({'sys_vendor': 'LENOVO'}, [{'vendor': '8086', 'device': '9a49'}], NEW_FLAGS, 8 * 1024 * 1024)
        self.assertEqual(q['kernel_params'], [])
        self.assertEqual((q['xorg_driver'], q['compositor'], q['zram_algo'], q['chrome_gpu']), ('modesetting', 'xfwm', 'zstd', 'full'))
        self.assertFalse(q['old_laptop'])

    def test_2gb_computer_gets_light_effects(self):
        self.assertEqual(hw.laptop_quirks({}, [], NEW_FLAGS, 2 * 1024 * 1024)['compositor'], 'lite')

    def test_grub_quirks_file(self):
        self.assertEqual(hw.grub_quirks_cfg([]), '')
        text = hw.grub_quirks_cfg(['i8042.nomux=1', 'i8042.reset=1'])
        self.assertIn('GRUB_CMDLINE_LINUX_DEFAULT="$GRUB_CMDLINE_LINUX_DEFAULT i8042.nomux=1 i8042.reset=1"', text)
        # Anything that is not a plain key=value kernel option is dropped (no shell injection into grub).
        self.assertEqual(hw.grub_quirks_cfg(['a=1"; rm -rf /']), '')

    def test_touchpad_missing_only_on_laptops_with_ps2_port(self):
        kb = hw.parse_input_devices('I: Bus=0011 Vendor=0001 Product=0001 Version=ab41\nN: Name="AT Translated Set 2 keyboard"\nH: Handlers=sysrq kbd event0\n')
        self.assertTrue(hw.touchpad_missing(kb, True, True))
        self.assertFalse(hw.touchpad_missing(kb, False, True))
        self.assertFalse(hw.touchpad_missing(kb, True, False))

    def test_apply_quirks_writes_files_and_removes_them_again(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d)
            (root / 'usr/lib/xorg/modules/drivers').mkdir(parents=True); (root / 'usr/lib/xorg/modules/drivers/intel_drv.so').touch()
            (root / 'etc/default/grub.d').mkdir(parents=True)
            q = hw.laptop_quirks(SAMSUNG, [IRONLAKE], OLD_FLAGS, 2 * 1024 * 1024, True)
            hw.apply_quirks(q, lambda m: None, root=d)
            self.assertIn('"AccelMethod" "sna"', (root / 'etc/X11/xorg.conf.d/10-navin-oldintel.conf').read_text())
            self.assertIn('i8042.nomux=1', (root / 'etc/default/grub.d/90-navin-quirks.cfg').read_text())
            self.assertIn('CPU_BOOST_ON_BAT=0', (root / 'etc/tlp.d/60-navin-oldlaptop.conf').read_text())
            self.assertEqual((root / 'run/navin/compositor-default').read_text().strip(), 'lite')
            (root / 'etc/navin').mkdir(parents=True); (root / 'etc/navin/quirks-off').touch()
            hw.apply_quirks(hw.laptop_quirks({}, [], NEW_FLAGS, 8 * 1024 * 1024), lambda m: None, root=d)
            for f in ('etc/X11/xorg.conf.d/10-navin-oldintel.conf', 'etc/default/grub.d/90-navin-quirks.cfg', 'etc/tlp.d/60-navin-oldlaptop.conf'):
                self.assertFalse((root / f).exists(), f)

    def test_live_usb_never_changes_boot_menu(self):
        with tempfile.TemporaryDirectory() as d:
            root = pathlib.Path(d); (root / 'run/live').mkdir(parents=True); (root / 'etc/default/grub.d').mkdir(parents=True)
            hw.apply_quirks(hw.laptop_quirks(SAMSUNG, [], OLD_FLAGS, 4 << 20), lambda m: None, root=d)
            self.assertFalse((root / 'etc/default/grub.d/90-navin-quirks.cfg').exists())

    def test_forced_intertouch_and_fbc_are_gone(self):
        conf = (IC / 'etc/modprobe.d/navin-hw.conf').read_text()
        self.assertNotIn('options psmouse', conf)
        self.assertNotIn('enable_fbc=1', conf)

    def test_boot_menu_3s_timeout(self):
        hook = (ROOT / 'config/hooks/live/02-navin-bootmenu.hook.binary').read_text()
        self.assertIn('set timeout=3', hook)
        self.assertIn('GRUB_TIMEOUT=3', (IC / 'etc/default/grub.d/navin.cfg').read_text())


class FanSlider(unittest.TestCase):
    def test_zero_hands_control_back_to_bios(self):
        for c in ('thinkpad', 'hwmon-pwm', 'platform-profile', 'none'):
            self.assertEqual(hw.fan_plan(c, 0), {'action': 'auto'})

    def test_pwm_never_below_30_percent(self):
        self.assertEqual(hw.fan_pwm_target(1), hw.PWM_FLOOR)
        self.assertEqual(hw.PWM_FLOOR, 77)
        self.assertEqual(hw.fan_pwm_target(100), 255)

    def test_pwm_never_slower_than_bios(self):
        self.assertEqual(hw.fan_pwm_target(1, current_auto_pwm=180), 180)
        self.assertEqual(hw.fan_plan('hwmon-pwm', 10, 200), {'action': 'pwm', 'pwm': 200})

    def test_thinkpad_levels(self):
        self.assertEqual(hw.thinkpad_level(1), 1)
        self.assertEqual(hw.thinkpad_level(50), 4)
        self.assertEqual(hw.thinkpad_level(100), 7)

    def test_platform_profile(self):
        self.assertEqual(hw.fan_plan('platform-profile', 20)['profile'], 'quiet')
        self.assertEqual(hw.fan_plan('platform-profile', 50)['profile'], 'balanced')
        self.assertEqual(hw.fan_plan('platform-profile', 90)['profile'], 'performance')

    def test_no_fan_interface_limits_cpu_heat_instead(self):
        self.assertEqual(hw.fan_plan('none', 100), {'action': 'heat-limit', 'cpu_max_percent': 50})
        self.assertEqual(hw.fan_plan('none', 20), {'action': 'heat-limit', 'cpu_max_percent': 90})

    def test_out_of_range_rejected(self):
        with self.assertRaises(ValueError):
            hw.fan_plan('hwmon-pwm', 101)


class UpdateChannel(unittest.TestCase):
    R = [{'tag_name': 'v2.0-update.21', 'assets': [{'name': 'navin-update.tar.gz'}, {'name': 'navin-update.tar.gz.sha256'}]},
         {'tag_name': 'v2.0-update.22', 'prerelease': True, 'assets': [{'name': 'navin-update.tar.gz'}, {'name': 'navin-update.tar.gz.sha256'}]},
         {'tag_name': 'v2.0-update.23', 'assets': [{'name': 'navin-update.tar.gz'}]},
         {'tag_name': 'v1.0-build.30', 'assets': [{'name': 'navin-update.tar.gz'}, {'name': 'navin-update.tar.gz.sha256'}]},
         {'tag_name': 'v2.1'}, {'tag_name': 'v3.0', 'draft': True}, {'tag_name': 'v2.0'}, {'tag_name': 'v1.2'}]

    def test_newest_complete_stable_patch(self):
        self.assertEqual(logic.newer_patch(self.R, 20)['tag_name'], 'v2.0-update.21')
        self.assertIsNone(logic.newer_patch(self.R, 21))

    def test_newer_full_version(self):
        self.assertEqual(logic.newer_os_release(self.R, '2.0')['tag_name'], 'v2.1')
        self.assertIsNone(logic.newer_os_release(self.R, '2.1'))

    def test_update_tag(self):
        self.assertEqual(logic.update_tag(21), 'v2.0-update.21')
        self.assertIn('update_tag(build)', (IC / 'usr/local/lib/navin/navin-apply-update').read_text())


class WhatsNew(unittest.TestCase):
    def test_every_listed_change_exists_in_its_file(self):
        data = json.loads((IC / 'usr/share/navin/whatsnew-2.0.json').read_text())
        self.assertEqual(data['version'], '2.0')
        self.assertGreaterEqual(len(data['items']), 80)
        for it in data['items']:
            path = REPO / it['path']
            self.assertTrue(path.exists(), it['path'])
            self.assertIn(it['check'], path.read_text(), f"{it['title']} -> {it['path']}")

    def test_version_strings(self):
        hook = (ROOT / 'config/hooks/live/01-navin-os-customization.hook.chroot').read_text()
        self.assertIn('PRETTY_NAME="NAVIN 2.2 (Debian 13 Trixie base)"', hook)
        self.assertIn("printf '41\\n' > /etc/navin/build", hook)
        self.assertIn('navin-2.2.1-x86_64.iso', (ROOT / 'build.sh').read_text())


if __name__ == '__main__':
    unittest.main()
