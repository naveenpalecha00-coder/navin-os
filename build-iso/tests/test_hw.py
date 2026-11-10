import importlib.util
import pathlib
import unittest

IC = pathlib.Path(__file__).resolve().parents[1] / 'config/includes.chroot'


def load(name):
    spec = importlib.util.spec_from_file_location(name, IC / f'usr/local/lib/navin/{name}.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


hw = load('navin_hw')
sysl = load('navin_sys')

ELAN_I2C = '''I: Bus=0018 Vendor=04f3 Product=3140 Version=0100
N: Name="ELAN0501:00 04F3:3140 Touchpad"
P: Phys=i2c-ELAN0501:00
H: Handlers=mouse1 event7
B: PROP=5
B: ABS=2e0800000000003

I: Bus=0011 Vendor=0001 Product=0001 Version=ab83
N: Name="AT Translated Set 2 keyboard"
H: Handlers=sysrq kbd event3
B: PROP=0
'''
SYN_PS2 = '''I: Bus=0011 Vendor=0002 Product=0007 Version=01b1
N: Name="SynPS/2 Synaptics TouchPad"
H: Handlers=mouse0 event6
B: PROP=5
B: ABS=660800011000003
'''
ALPS = '''I: Bus=0011 Vendor=0002 Product=0008 Version=0300
N: Name="AlpsPS/2 ALPS GlidePoint"
H: Handlers=mouse0 event5
B: PROP=0
'''


class Touchpad(unittest.TestCase):
    def test_elan_i2c_precision(self):
        devs = hw.parse_input_devices(ELAN_I2C)
        self.assertEqual(len(devs), 2)
        plan = hw.touchpad_plan(devs, ['PNP0C50'], {'i2c_hid_acpi'})
        self.assertEqual(len(plan['touchpads']), 1)
        t = plan['touchpads'][0]
        self.assertEqual((t['vendor'], t['bus'], t['event']), ('ELAN', 'I2C', 'event7'))
        self.assertIn('hid_multitouch', plan['modules'])

    def test_synaptics_ps2_suggests_intertouch(self):
        plan = hw.touchpad_plan(hw.parse_input_devices(SYN_PS2), [], {'psmouse'})
        self.assertEqual(plan['touchpads'][0]['vendor'], 'Synaptics')
        self.assertEqual(plan['kernel_params'], ['psmouse.synaptics_intertouch=1'])
        self.assertEqual(plan['modules'], [])

    def test_alps_detected_by_name(self):
        plan = hw.touchpad_plan(hw.parse_input_devices(ALPS), [], {'psmouse'})
        self.assertEqual(plan['touchpads'][0]['vendor'], 'ALPS')

    def test_missing_i2c_touchpad_loads_safe_drivers(self):
        kb_only = hw.parse_input_devices(ELAN_I2C.split('\n\n')[1])
        plan = hw.touchpad_plan(kb_only, ['ELAN0501', 'PNP0C50'], set())
        self.assertEqual(plan['touchpads'], [])
        self.assertEqual(plan['modules'], ['i2c_designware_platform', 'i2c_hid_acpi', 'hid_multitouch', 'elan_i2c'])
        self.assertTrue(all(m in hw.SAFE_MODULES for m in plan['modules']))

    def test_keyboard_is_not_touchpad(self):
        self.assertFalse(hw.is_touchpad(hw.parse_input_devices(ELAN_I2C)[1]))


class Drivers(unittest.TestCase):
    def test_pci_classes(self):
        self.assertEqual(hw.classify_pci('0x030000'), 'gpu')
        self.assertEqual(hw.classify_pci('0x028000'), 'wifi')
        self.assertEqual(hw.classify_pci('0x010802'), 'storage')

    def test_nvidia_only_when_detect_supports(self):
        g = [{'vendor': '10de', 'device': '1c8d', 'driver': 'nouveau'}]
        none = hw.gpu_plan(g, False, set(), 'No NVIDIA GPU supported by the proprietary driver')
        self.assertFalse(any((r['package'] or '').startswith('nvidia-driver') for r in none))
        yes = hw.gpu_plan(g, True, set(), 'It is recommended to install the\n    nvidia-driver\npackage.')
        drv = [r for r in yes if r['package'] == 'nvidia-driver'][0]
        self.assertTrue(drv['needs_confirmation'])
        self.assertIn('Secure Boot', drv['reason'])

    def test_installed_not_offered_again(self):
        rec = hw.gpu_plan([{'vendor': '8086', 'device': '9a49', 'driver': 'i915'}], False, {'intel-media-va-driver', 'i965-va-driver'})
        self.assertEqual(rec, [])


class Profiles(unittest.TestCase):
    def test_ram(self):
        self.assertEqual(hw.ram_profile(2 * 1048576)[0], 'lite')
        self.assertEqual(hw.ram_profile(4 * 1048576)[0], 'balanced')
        self.assertEqual(hw.ram_profile(8 * 1048576)[0], 'standard')

    def test_thermal(self):
        self.assertEqual([hw.thermal_level(t) for t in (60, 85, 92, 99, None)], ['ok', 'warm', 'hot', 'critical', 'unknown'])


class Shortcuts(unittest.TestCase):
    XML = (IC / 'etc/skel/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-keyboard-shortcuts.xml').read_text()

    def test_normalize(self):
        self.assertEqual(sysl.normalize_accel('<Primary><Alt>t'), 'Ctrl+Alt+T')
        self.assertEqual(sysl.normalize_accel('<Super>e'), 'Super+E')
        self.assertEqual(sysl.normalize_accel('Super_L'), 'Super')

    def test_required_defaults(self):
        s = {sysl.normalize_accel(a): v for _, a, v in sysl.parse_shortcuts(self.XML)}
        expected = {'Super': 'xfce4-popup-whiskermenu', 'Ctrl+Escape': 'xfce4-popup-whiskermenu', 'Super+E': 'thunar',
                    'Super+D': 'show_desktop_key', 'Super+L': 'xflock4', 'Alt+Tab': 'cycle_windows_key', 'Alt+F4': 'close_window_key',
                    'Super+R': 'xfce4-appfinder --collapsed', 'Super+I': 'navin-settings', 'Super+S': 'navin-search',
                    'Super+A': 'navin-control-center', 'Super+W': 'rofi -show window -show-icons', 'Super+Left': 'tile_left_key',
                    'Super+Right': 'tile_right_key', 'Super+Up': 'maximize_window_key', 'Super+Down': 'hide_window_key',
                    'Ctrl+Alt+T': 'xfce4-terminal', 'Print': 'xfce4-screenshooter', 'Shift+Print': 'xfce4-screenshooter -r',
                    'Ctrl+Shift+Escape': 'xfce4-taskmanager'}
        for k, v in expected.items():
            self.assertEqual(s.get(k), v, k)

    def test_defaults_have_no_conflicts(self):
        self.assertEqual(sysl.find_conflicts(sysl.parse_shortcuts(self.XML)), {})

    def test_conflict_detected(self):
        c = sysl.find_conflicts([('commands', '<Super>e', 'thunar'), ('xfwm4', '<Super>E', 'x')])
        self.assertIn('Super+E', c)

    def test_search(self):
        r = sysl.search_shortcuts(sysl.parse_shortcuts(self.XML), 'terminal')
        self.assertTrue(any(v == 'xfce4-terminal' for _, _, v in r))


class Bench(unittest.TestCase):
    def test_compare(self):
        r = sysl.compare_benchmarks({'boot_s': 20, 'disk_write_mbps': 100}, {'boot_s': 15, 'disk_write_mbps': 80})
        self.assertEqual(r['boot_s']['change_percent'], -25.0)
        self.assertTrue(r['boot_s']['better'])
        self.assertFalse(r['disk_write_mbps']['better'])

    def test_systemd_analyze(self):
        self.assertEqual(sysl.parse_systemd_analyze('Startup finished in 3.1s (kernel) + 9.4s (userspace) = 12.5s'), 12.5)
        self.assertEqual(sysl.parse_systemd_analyze('... = 1min 2.5s'), 62.5)

    def test_leak(self):
        s = {1: ('leaky', [100000 + i * 20000 for i in range(8)]), 2: ('steady', [50000, 60000, 50000, 60000, 50000, 60000])}
        self.assertEqual([x['name'] for x in sysl.leak_candidates(s)], ['leaky'])

    def test_swipe(self):
        self.assertEqual(sysl.classify_swipe(-300, 10, 1000, 600), 'left')
        self.assertEqual(sysl.classify_swipe(0, -200, 1000, 600), 'up')
        self.assertIsNone(sysl.classify_swipe(50, 30, 1000, 600))


if __name__ == '__main__':
    unittest.main()
