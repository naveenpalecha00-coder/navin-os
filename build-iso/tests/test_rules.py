import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('logic', ROOT / 'config/includes.chroot/usr/local/lib/navin/navin_logic.py')
logic = importlib.util.module_from_spec(spec)
spec.loader.exec_module(logic)

class Rules(unittest.TestCase):
    def test_build(self):
        self.assertEqual(logic.BUILD, 10)
        self.assertEqual(logic.release_build('v1.0-build.10'), 10)
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
        config = (ROOT / 'config/includes.chroot/etc/sysctl.d/98-navin-speed.conf').read_text()
        import re
        values = dict(re.findall(r'([\w.]+)\s*=\s*(\d+)', config))
        self.assertEqual(values['vm.dirty_background_bytes'], '16777216')
        self.assertEqual(values['vm.dirty_bytes'], '50331648')
        self.assertEqual(values['vm.vfs_cache_pressure'], '50')
        self.assertEqual(values['vm.swappiness'], '100')

    def test_turbo_and_tools_present(self):
        for tool in ('navin-turbo', 'navin-quick-share', 'navin-recorder', 'navin-vault', 'navin-snapshot', 'navin-theme', 'navin-pill', 'navin-exe-helper'):
            self.assertTrue((ROOT / 'config/includes.chroot/usr/local/bin' / tool).is_file(), tool)
    def test_gestures(self):
        conf = (ROOT / 'config/includes.chroot/etc/skel/.config/touchegg/touchegg.conf').read_text()
        self.assertIn('fingers="3" direction="UP"', conf)
        self.assertIn('type="PINCH" fingers="4"', conf)

if __name__ == '__main__':
    unittest.main()