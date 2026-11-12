"""NAVIN 2.1: two-choice boot menu with the touchpad fix, toolbox logic, What's New 2.1."""
import importlib.util
import json
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
REPO = ROOT.parent
IC = ROOT / 'config/includes.chroot'
spec = importlib.util.spec_from_file_location('navin_tools', IC / 'usr/local/lib/navin/navin_tools.py')
T = importlib.util.module_from_spec(spec); spec.loader.exec_module(T)

GRUB = '''menuentry "Live system (amd64)" --hotkey=l {
\tlinux\t/live/vmlinuz boot=live components persistence i8042.nomux=1 i8042.reset=1 quiet splash
\tinitrd\t/live/initrd.img
}
menuentry "Live system (amd64 fail-safe mode)" {
\tlinux\t/live/vmlinuz boot=live components memtest noapic nosplash
\tinitrd\t/live/initrd.img
}
submenu 'Utilities...' --hotkey=u {
\tmenuentry "Memory Diagnostic Tool (memtest86+)" --hotkey=m {
\t\tlinux16 /live/memtest86+x64.bin
\t}
}
'''
ISOLINUX = '''label live-amd64
\tmenu label ^Live system (amd64)
\tmenu default
\tlinux /live/vmlinuz
\tappend boot=live components quiet splash

label live-amd64-failsafe
\tmenu label ^Live system (amd64 fail-safe mode)
\tlinux /live/vmlinuz
\tappend boot=live components memtest noapic nosplash
'''


class BootMenu(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = tempfile.TemporaryDirectory(); d = pathlib.Path(cls.d.name)
        (d / 'boot/grub').mkdir(parents=True); (d / 'isolinux').mkdir()
        (d / 'boot/grub/grub.cfg').write_text(GRUB); (d / 'isolinux/live.cfg').write_text(ISOLINUX)
        subprocess.run(['sh', str(ROOT / 'config/hooks/live/02-navin-bootmenu.hook.binary')], cwd=d, check=True, capture_output=True)
        cls.grub = (d / 'boot/grub/grub.cfg').read_text(); cls.iso = (d / 'isolinux/live.cfg').read_text()

    @classmethod
    def tearDownClass(cls):
        cls.d.cleanup()

    def top_level_entries(self):
        return [l for l in self.grub.splitlines() if l.startswith('menuentry ')]

    def test_grub_main_menu_has_exactly_live_and_install(self):
        self.assertEqual([l.split('"')[1] for l in self.top_level_entries()],
                         ['Live Mode - Try NAVIN 2.2', 'Full Installation - Install NAVIN 2.2'])
        self.assertNotIn('Old Laptop', self.grub)

    def test_both_grub_choices_have_touchpad_fix_once(self):
        for l in self.grub.splitlines():
            if l.strip().startswith('linux\t/live/vmlinuz'):
                self.assertEqual(l.count('i8042.nomux=1'), 1, l)
                self.assertIn('i8042.reset=1', l)
        self.assertIn('navin.install=1', self.grub)

    def test_safe_graphics_lives_in_tools_submenu(self):
        sub = self.grub[self.grub.index('submenu'):]
        self.assertIn('Safe Graphics - NAVIN 2.2', sub)
        self.assertIn('nomodeset', sub)

    def test_isolinux_two_visible_choices(self):
        labels = [l.strip() for l in self.iso.splitlines() if 'menu label' in l]
        self.assertEqual(len(labels), 3)
        safe = self.iso[self.iso.index('label safe'):]
        self.assertIn('menu hide', safe)
        visible = self.iso[:self.iso.index('label safe')]
        self.assertEqual(visible.count('menu label'), 2)
        self.assertEqual(visible.count('i8042.nomux=1'), 2)

    def test_live_and_installed_boot_lines_have_touchpad_fix(self):
        self.assertIn('persistence i8042.nomux=1 i8042.reset=1', (ROOT / 'auto/config').read_text())
        self.assertIn('GRUB_CMDLINE_LINUX_DEFAULT="i8042.nomux=1 i8042.reset=1', (IC / 'etc/default/grub.d/navin.cfg').read_text())


class Touchpad(unittest.TestCase):
    def test_login_forces_touchpad_on(self):
        tp = (IC / 'usr/local/bin/navin-touchpad').read_text()
        self.assertIn('[ "${2:-}" = --login ] && [ "$(get enabled)" = off ] && save enabled on', tp)
        self.assertIn('navin-touchpad apply --login', (IC / 'usr/local/bin/navin-session-init').read_text())


class Files(unittest.TestCase):
    def test_large_files(self):
        e = [('/h/a', 5), ('/h/b', 300), ('/h/c', 200)]
        self.assertEqual(T.large_files(e, 100), [('/h/b', 300), ('/h/c', 200)])

    def test_duplicates_need_same_size_and_hash(self):
        e = [('a', 10), ('b', 10), ('c', 10), ('d', 20)]
        h = {'a': 'x', 'b': 'x', 'c': 'y', 'd': 'x'}
        self.assertEqual(T.duplicate_groups(e, hasher=h.get), [(10, ['a', 'b'])])

    def test_real_hash(self):
        with tempfile.NamedTemporaryFile() as f:
            f.write(b'navin'); f.flush()
            self.assertEqual(T.file_hash(f.name), __import__('hashlib').sha256(b'navin').hexdigest())

    def test_folder_sizes(self):
        e = [('/h/A/x', 5), ('/h/A/y/z', 5), ('/h/B/q', 3), ('/h/f', 1)]
        self.assertEqual(T.folder_sizes('/h', e), [('A', 10), ('B', 3), ('(files here)', 1)])

    def test_organize_never_overwrites(self):
        plan = T.organize_plan(['song.mp3', 'a.PDF', 'notes', 'pic.jpg'], existing=['Images/pic.jpg'])
        self.assertEqual(plan, [('a.PDF', 'Documents/a.PDF'), ('pic.jpg', 'Images/pic (1).jpg'), ('song.mp3', 'Music/song.mp3')])

    def test_batch_rename(self):
        self.assertEqual(T.batch_rename_plan(['b.jpg', 'a.jpg'], 'Trip {n}', 9), [('a.jpg', 'Trip 09.jpg'), ('b.jpg', 'Trip 10.jpg')])
        with self.assertRaises(ValueError):
            T.batch_rename_plan(['a.jpg', 'b.jpg'], 'same')
        with self.assertRaises(ValueError):
            T.batch_rename_plan(['a.jpg'], '../{n}')

    def test_shred_only_user_files(self):
        self.assertTrue(T.safe_user_path('/home/navin/x.txt', '/home/navin'))
        self.assertTrue(T.safe_user_path('/media/navin/USB/x', '/home/navin'))
        self.assertFalse(T.safe_user_path('/etc/passwd', '/home/navin'))
        self.assertFalse(T.safe_user_path('/home/navin', '/home/navin'))
        self.assertFalse(T.safe_user_path('/home/navin/../other/x', '/home/navin'))
        self.assertEqual(T.shred_cmd('/home/navin/x')[:3], ['shred', '-u', '-z'])


class Media(unittest.TestCase):
    def test_trim_validates_times(self):
        self.assertEqual(T.video_trim_cmd('a.mp4', 'b.mp4', '00:00:05', '0:01:00')[-4:], ['a.mp4', '-c', 'copy', 'b.mp4'])
        with self.assertRaises(ValueError):
            T.video_trim_cmd('a', 'b', '5', '00:01:00')

    def test_image_resize(self):
        self.assertIn('scale=800:-2', T.image_convert_cmd('a.png', 'a.jpg', '800'))
        self.assertNotIn('-vf', T.image_convert_cmd('a.png', 'a.webp'))
        with self.assertRaises(ValueError):
            T.image_convert_cmd('a', 'b', 5)

    def test_pdf(self):
        self.assertEqual(T.pdf_merge_cmd(['1.pdf', '2.pdf'], 'o.pdf'), ['qpdf', '--empty', '--pages', '1.pdf', '2.pdf', '--', 'o.pdf'])
        with self.assertRaises(ValueError):
            T.pdf_merge_cmd(['1.pdf'], 'o.pdf')
        self.assertIn('-dPDFSETTINGS=/screen', T.pdf_compress_cmd('a.pdf', 'b.pdf', 'small'))
        self.assertTrue(T.pdf_split_cmd('/d/x.pdf', '/d')[-1].endswith('x-page-%d.pdf'))

    def test_audio_limits(self):
        self.assertIn('pulse', T.audio_record_cmd('a.ogg', 60))
        with self.assertRaises(ValueError):
            T.audio_record_cmd('a.ogg', 0)


class Network(unittest.TestCase):
    def test_wifi_qr(self):
        self.assertEqual(T.wifi_qr_payload('Home;Net', 'p:ss'), 'WIFI:T:WPA;S:Home\\;Net;P:p\\:ss;;')
        self.assertEqual(T.wifi_qr_payload('Cafe', ''), 'WIFI:T:nopass;S:Cafe;;')

    def test_dns_packet_and_answer(self):
        pkt = T.dns_query_packet('debian.org')
        self.assertEqual(pkt[12:], b'\x06debian\x03org\x00\x00\x01\x00\x01')
        ok = b'\x4e\x41\x81\x80\x00\x01\x00\x01\x00\x00\x00\x00'
        self.assertTrue(T.dns_answer_ok(ok))
        self.assertFalse(T.dns_answer_ok(b'\x4e\x41\x81\x83\x00\x01\x00\x00\x00\x00\x00\x00'))  # NXDOMAIN
        self.assertFalse(T.dns_answer_ok(b'\x00\x01\x81\x80\x00\x01\x00\x01\x00\x00\x00\x00'))  # other query


class System(unittest.TestCase):
    def test_battery_health(self):
        self.assertEqual(T.battery_health('36000000', '48000000'), 75.0)
        self.assertIsNone(T.battery_health(None, '1'))
        self.assertIsNone(T.battery_health('5', '0'))

    def test_blame(self):
        text = '  1min 2.5s apt-daily.service\n 850ms udisks2.service\n  3.200s NetworkManager.service\n'
        self.assertEqual(T.parse_blame(text), [(62.5, 'apt-daily.service'), (3.2, 'NetworkManager.service'), (0.85, 'udisks2.service')])

    def test_service_cmd_rejects_bad_input(self):
        self.assertEqual(T.service_cmd('stop', 'cups.service'), ['pkexec', 'systemctl', 'stop', 'cups.service'])
        for a, u in (('kill', 'cups.service'), ('stop', 'cups; rm -rf /'), ('stop', 'cups')):
            with self.assertRaises(ValueError):
                T.service_cmd(a, u)

    def test_workspaces(self):
        self.assertEqual(T.workspace_count(4, 'add'), 5)
        self.assertEqual(T.workspace_count(12, 'add'), 12)
        self.assertEqual(T.workspace_count(1, 'remove'), 1)

    def test_pomodoro(self):
        self.assertEqual(T.pomodoro_step(0), ('Focus', 1500))
        self.assertEqual(T.pomodoro_step(7), ('Long break', 900))


class WhatsNew21(unittest.TestCase):
    def test_every_listed_change_exists_in_its_file(self):
        data = json.loads((IC / 'usr/share/navin/whatsnew-2.1.json').read_text())
        self.assertEqual(data['version'], '2.1')
        for it in data['items']:
            path = REPO / it['path']
            self.assertTrue(path.exists(), it['path'])
            self.assertIn(it['check'], path.read_text(), f"{it['title']} -> {it['path']}")

    def test_every_toolbox_tool_is_listed(self):
        src = (IC / 'usr/local/bin/navin-toolbox').read_text()
        listed = {it['check'] for v in ('2.1', '2.2') for it in json.loads((IC / f'usr/share/navin/whatsnew-{v}.json').read_text())['items']
                  if it['category'] == 'Toolbox'}
        import re
        for tid in re.findall(r'^    \("(\w+)", "', src, re.M):
            self.assertIn(f'("{tid}", ', listed)


if __name__ == '__main__':
    unittest.main()
