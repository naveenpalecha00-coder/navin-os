"""NAVIN XP 3.1: Task Manager, Defender, Battery & Thermal, Backup & Restore, adaptive glass, en/hi texts."""
import json, pathlib, sys, unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
IC = ROOT / 'config/includes.chroot'
sys.path.insert(0, str(IC / 'usr/local/lib/navin'))
import navin_xp as X  # noqa: E402
import navin_logic as L  # noqa: E402


class TaskManager(unittest.TestCase):
    def test_cpu_percent(self):
        a = X.cpu_times('cpu  100 0 100 800 0 0 0 0 0 0\ncpu0 1 2 3 4\n')
        b = X.cpu_times('cpu  150 0 150 900 0 0 0 0 0 0\n')
        self.assertEqual(X.cpu_percent(a, b), 50.0)
        self.assertEqual(X.cpu_percent(a, a), 0.0)

    def test_meminfo(self):
        m = X.parse_meminfo('MemTotal: 4096000 kB\nMemFree: 100000 kB\nMemAvailable: 2048000 kB\nSwapTotal: 1024000 kB\nSwapFree: 512000 kB\n')
        self.assertEqual((m['total'], m['used'], m['percent'], m['swap_used']), (4000, 2000, 50.0, 500))

    def test_net_skips_loopback(self):
        t = 'Inter-|\n face |bytes\n    lo: 999 1 0 0 0 0 0 0 999 1 0 0 0 0 0 0\n  wlan0: 1000 5 0 0 0 0 0 0 200 3 0 0 0 0 0 0\n'
        self.assertEqual(X.net_bytes(t), (1000, 200))

    def test_disk_counts_whole_disks_only(self):
        t = ('   8       0 sda 10 0 100 0 5 0 50 0 0 0 0\n   8       1 sda1 10 0 100 0 5 0 50 0 0 0 0\n'
             ' 259       0 nvme0n1 1 0 2 0 1 0 4 0 0 0 0\n   7       0 loop0 1 0 9 0 0 0 0 0 0 0 0\n')
        self.assertEqual(X.disk_bytes(t), ((100 + 2) * 512, (50 + 4) * 512))

    def test_rate_never_negative(self):
        self.assertEqual(X.rate(1000, 3000, 2), 1000)
        self.assertEqual(X.rate(5000, 10, 1), 0)

    def test_pid_stat_with_spaces_and_parens(self):
        line = '1234 (Web Content (x)) S 1000 1234 1234 0 -1 4194560 0 0 0 0 70 30 0 0 20 0 1 0 100 1000000 2560 18446744073709551615'
        p = X.parse_pid_stat(line)
        self.assertEqual((p['pid'], p['name'], p['ppid'], p['ticks'], p['rss_pages']), (1234, 'Web Content (x)', 1000, 100, 2560))

    def test_kill_rules(self):
        own = {'pid': 4000, 'ppid': 900, 'name': 'firefox'}
        self.assertEqual(X.kill_allowed(own, 1000, 1000), (True, ''))
        self.assertFalse(X.kill_allowed({'pid': 1, 'ppid': 0, 'name': 'systemd'}, 1000, 0)[0])
        self.assertFalse(X.kill_allowed({'pid': 55, 'ppid': 2, 'name': 'kworker/0:1'}, 0, 0)[0])
        self.assertFalse(X.kill_allowed(own, 1000, 0)[0])                       # root's process
        self.assertFalse(X.kill_allowed({'pid': 700, 'ppid': 1, 'name': 'xfwm4'}, 1000, 1000)[0])
        self.assertFalse(X.kill_allowed(own, 1000, 1000, my_pid=4000)[0])

    def test_process_rows_sorted_by_cpu(self):
        prev = {1: {'name': 'a', 'ticks': 0, 'rss_pages': 256}, 2: {'name': 'b', 'ticks': 0, 'rss_pages': 512}}
        cur = {1: {'name': 'a', 'ticks': 10, 'rss_pages': 256}, 2: {'name': 'b', 'ticks': 50, 'rss_pages': 512}, 3: {'name': 'new', 'ticks': 5, 'rss_pages': 1}}
        rows = X.process_rows(prev, cur, 100)
        self.assertEqual([r['name'] for r in rows], ['b', 'a', 'new'])
        self.assertEqual((rows[0]['cpu'], rows[0]['ram_mb']), (50.0, 2.0))
        self.assertEqual(rows[2]['cpu'], 0.0)   # first sample of a new process: no CPU guessed

    def test_startup_override_and_rules(self):
        sys_text = '[Desktop Entry]\nType=Application\nName=Clipboard\nExec=xfce4-clipman\nOnlyShowIn=XFCE;\n'
        off = X.autostart_override(sys_text, False)
        e = X.parse_desktop_entry(off)
        self.assertEqual((e['Hidden'], e['Exec']), ('true', 'xfce4-clipman'))
        self.assertFalse(X.autostart_enabled(e))
        self.assertTrue(X.autostart_enabled(X.parse_desktop_entry(X.autostart_override(off, True))))
        gnome_only = X.parse_desktop_entry('[Desktop Entry]\nName=G\nOnlyShowIn=GNOME;\n')
        rows = X.startup_apps({'c.desktop': X.parse_desktop_entry(sys_text), 'g.desktop': gnome_only}, {'c.desktop': e})
        self.assertEqual([(r['file'], r['enabled']) for r in rows], [('c.desktop', False)])


class Defender(unittest.TestCase):
    UFW = ('Status: active\nLogging: on (low)\nDefault: deny (incoming), allow (outgoing), disabled (routed)\nNew profiles: skip\n\n'
           'To                         Action      From\n--                         ------      ----\n22/tcp                     ALLOW IN    Anywhere\n')

    def test_ufw_status(self):
        s = X.parse_ufw_status(self.UFW)
        self.assertEqual((s['active'], s['incoming'], s['outgoing'], len(s['rules'])), (True, 'deny', 'allow', 1))
        self.assertFalse(X.parse_ufw_status('Status: inactive\n')['active'])

    def test_whitelist(self):
        self.assertIn(['ufw', '--force', 'enable'], X.defender_plan('fw-enable'))
        self.assertEqual(X.defender_plan('sig-update'), [['freshclam', '--stdout']])
        for bad in ('rm', 'fw-enable; reboot', None):
            with self.assertRaises(ValueError):
                X.defender_plan(bad)

    def test_clamscan_command_safe(self):
        c = X.clamscan_command(['/home/navin/Downloads'])
        self.assertEqual(c[:2], ['clamscan', '-r'])
        self.assertNotIn('--remove', c); self.assertEqual(c[-2:], ['--', '/home/navin/Downloads'])
        with self.assertRaises(ValueError):
            X.clamscan_command(['relative', '/a/../etc'])

    def test_clamscan_parse(self):
        out = ('/home/n/Downloads/eicar.com: Win.Test.EICAR_HDB-1 FOUND\n\n----------- SCAN SUMMARY -----------\n'
               'Known viruses: 8700000\nScanned files: 42\nInfected files: 1\n')
        r = X.parse_clamscan(out)
        self.assertEqual((r['infected'], r['scanned'], r['infected_count'], r['finished']),
                         ([('/home/n/Downloads/eicar.com', 'Win.Test.EICAR_HDB-1')], 42, 1, True))
        self.assertFalse(X.parse_clamscan('LibClamAV Error: cli_loaddbdir(): No supported database files found\n')['finished'])

    def test_usb_mounts(self):
        m = ('/dev/sda2 / ext4 rw 0 0\n/dev/sdb1 /media/navin/MY\\040USB vfat rw 0 0\n'
             'tmpfs /run/media tmpfs rw 0 0\n/dev/mmcblk0p1 /run/media/navin/SD exfat rw 0 0\n')
        self.assertEqual(X.removable_mounts(m), ['/media/navin/MY USB', '/run/media/navin/SD'])


class Battery(unittest.TestCase):
    def test_energy_battery(self):
        h = X.battery_health({'energy_full': '36000000\n', 'energy_full_design': '48000000', 'energy_now': '18000000',
                              'cycle_count': '312', 'status': 'Discharging\n', 'capacity': '50'})
        self.assertEqual((h['unit'], h['design'], h['full'], h['health'], h['wear'], h['cycles'], h['label']),
                         ('Wh', 48.0, 36.0, 75.0, 25.0, 312, 'Fair'))

    def test_charge_battery_without_cycles(self):
        h = X.battery_health({'charge_full': '4000000', 'charge_full_design': '4400000', 'cycle_count': '0'})
        self.assertEqual((h['unit'], h['cycles'], h['health'], h['label']), ('mAh', None, 90.9, 'Good'))

    def test_nothing_guessed(self):
        h = X.battery_health({'status': 'Unknown'})
        self.assertEqual((h['health'], h['wear'], h['cycles'], h['label']), (None, None, None, None))

    def test_temps_and_fans(self):
        self.assertEqual(X.temperatures([('x86_pkg_temp', '52000\n'), ('bad', 'n/a'), ('acpitz', '-273000')]), [('x86_pkg_temp', 52.0)])
        self.assertEqual(X.fan_rpms([('thinkpad fan1', '2480\n'), ('x', '')]), [('thinkpad fan1', 2480)])
        self.assertEqual(X.fan_profile_command('silent'), ['pkexec', '/usr/local/lib/navin/navin-fan', 'silent'])
        with self.assertRaises(ValueError):
            X.fan_profile_command('max')


class Backup(unittest.TestCase):
    def test_plans(self):
        self.assertEqual(X.backup_plan('list'), ['timeshift', '--list', '--scripted'])
        c = X.backup_plan('create', '/dev/sdb1', 'pre update; rm -rf /')
        self.assertEqual(c[-2:], ['--snapshot-device', '/dev/sdb1'])
        self.assertNotIn(';', ' '.join(c))
        for dev in ('/dev/sdb', '/tmp/x', '/dev/sdb1;reboot'):
            with self.assertRaises(ValueError):
                X.backup_plan('create', dev)
        with self.assertRaises(ValueError):
            X.backup_plan('delete')

    def test_parse_list_and_devices(self):
        lst = ('Num     Name                 Tags  Description\n-----\n0    >  2026-11-10_10-00-01  D\n'
               '1    >  2026-11-12_09-30-00  O     before update\n')
        r = X.parse_timeshift_list(lst)
        self.assertEqual([(x['name'], x['comment']) for x in r], [('2026-11-12_09-30-00', 'before update'), ('2026-11-10_10-00-01', '')])
        dev = 'Num     Device       Size  Type  Label\n----\n0    >  /dev/sda2   118.6 GB  ext4   \n1    >  /dev/sdb1   29.3 GB   ext4   NAVIN-BACKUP\n'
        self.assertEqual(X.parse_timeshift_devices(dev)[1], {'device': '/dev/sdb1', 'size': '29.3 GB', 'type': 'ext4', 'label': 'NAVIN-BACKUP'})


class Glass(unittest.TestCase):
    def test_tiers_by_ram(self):
        self.assertEqual(X.glass_tier(1950)[0], 'Ultra Light')
        self.assertEqual(X.glass_tier(3900)[0], 'Balanced')
        self.assertEqual(X.glass_tier(7800)[0], 'Premium Glass')
        self.assertEqual(X.glass_tier(16000, 'Ultra Light'), ('Ultra Light', 2))

    def test_conf_is_replaced_not_stacked(self):
        base = (IC / 'etc/xdg/picom.conf').read_text()
        once = X.glass_picom_conf(base, 'Balanced')
        twice = X.glass_picom_conf(once, 'Premium Glass')
        self.assertIn('blur-method = "dual_kawase";', once)
        self.assertEqual(twice.count('blur-method'), 1); self.assertIn('blur-strength = 8;', twice)
        self.assertIn('backend = "glx";', twice)   # dual_kawase needs the glx backend

    def test_compositor_has_glass_mode(self):
        s = (IC / 'usr/local/bin/navin-compositor').read_text()
        self.assertIn('glass) run_glass;;', s); self.assertIn('xfwm|lite|picom|glass|off) echo "$1" > "$CONF"; apply', s)


class Language(unittest.TestCase):
    def test_same_keys(self):
        self.assertEqual(set(X.TEXT['en']), set(X.TEXT['hi']))
        self.assertTrue(all(X.TEXT['hi'][k] for k in X.TEXT['hi']))

    def test_choice(self):
        self.assertEqual(X.lang({'LANG': 'hi_IN.UTF-8'}), 'hi')
        self.assertEqual(X.lang({'LANG': 'hi_IN.UTF-8'}, 'en\n'), 'en')
        self.assertEqual(X.lang({'LANG': 'en_IN.UTF-8'}), 'en')
        self.assertEqual(X.t('end_task', 'hi'), 'टास्क बंद करें')


class Release(unittest.TestCase):
    def test_version_and_files(self):
        self.assertEqual((L.VERSION, L.BUILD), ('3.1', 51))
        self.assertIn('navin-xp-3.1-x86_64.iso', (ROOT / 'build.sh').read_text())
        wf = (ROOT.parent / '.github/workflows/build-iso.yml').read_text()
        self.assertIn('FINAL_TAG: v3.1', wf); self.assertIn('branches: [navin-xp]', wf)
        for app in ('navin-task-manager', 'navin-defender', 'navin-battery', 'navin-backup-restore'):
            self.assertTrue((IC / 'usr/local/bin' / app).exists(), app)
            self.assertTrue((IC / 'usr/share/applications' / (app + '.desktop')).exists(), app)
            self.assertIn(app, wf)

    def test_whatsnew_entries_are_real(self):
        data = json.loads((IC / 'usr/share/navin/whatsnew-3.1.json').read_text())
        self.assertGreaterEqual(len(data['items']), 15)
        for it in data['items']:
            p = ROOT.parent / it['path']
            self.assertTrue(p.exists(), it['path'])
            if 'check' in it:
                self.assertIn(it['check'], p.read_text(errors='ignore'), it['title'])

    def test_helper_only_calls_whitelists(self):
        s = (IC / 'usr/lib/navin-os/navin-xp-helper').read_text()
        self.assertIn('X.defender_plan(a[0])', s); self.assertIn('X.backup_plan(a[1]', s)
        self.assertNotIn('shell=True', s)
        self.assertIn('/usr/lib/navin-os/navin-xp-helper', (IC / 'usr/share/polkit-1/actions/org.navin.repair.policy').read_text())


if __name__ == '__main__':
    unittest.main()
