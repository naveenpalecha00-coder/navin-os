"""NAVIN XP 3.0: display guard (2.2.1 tty1 stop), boot splash hardware line, 6-entry boot menu,
Update Center logic (real APT status/progress, security-only, never removes packages), What's New XP."""
import importlib.util, json, pathlib, subprocess, sys, tempfile, unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]; REPO = ROOT.parent
IC = ROOT / 'config/includes.chroot'
sys.path.insert(0, str(IC / 'usr/local/lib/navin'))
import navin_hw as hw  # noqa: E402
import navin_update as U  # noqa: E402


class DisplayGuard(unittest.TestCase):
    def test_fallback_order(self):
        self.assertEqual(hw.display_next_level('default'), 'modesetting')
        self.assertEqual(hw.display_next_level('modesetting'), 'noaccel')
        self.assertEqual(hw.display_next_level('noaccel'), 'fbdev')

    def test_glamor_error_skips_to_noaccel(self):
        self.assertEqual(hw.display_next_level('default', errors=['glamor initialization failed']), 'noaccel')

    def test_nomodeset_goes_to_fbdev(self):
        self.assertEqual(hw.display_next_level('default', cmdline='boot=live nomodeset quiet'), 'fbdev')

    def test_vesa_only_on_bios(self):
        self.assertIsNone(hw.display_next_level('fbdev', uefi=True))
        self.assertEqual(hw.display_next_level('fbdev', uefi=False), 'vesa')
        self.assertIsNone(hw.display_next_level('vesa', uefi=False))

    def test_conf_text(self):
        self.assertEqual(hw.display_fallback_conf('default'), '')
        self.assertIn('Driver "modesetting"', hw.display_fallback_conf('modesetting'))
        self.assertIn('"AccelMethod" "none"', hw.display_fallback_conf('noaccel'))
        self.assertIn('Driver "fbdev"', hw.display_fallback_conf('fbdev'))
        self.assertTrue(hw.DISPLAY_FALLBACK_CONF.endswith('05-navin-display-fallback.conf'))  # sorts before 10-/20- configs

    def test_xorg_errors(self):
        log = '[ 5.1] (EE) intel(0): failed to set mode\n[ 5.2] (EE) \n[ 5.3] (EE) Backtrace:\n[ 5.4] (II) ok\n[ 5.5] (EE) no screens found\n'
        self.assertEqual(hw.xorg_errors(log), ['intel(0): failed to set mode', 'no screens found'])

    def test_services_enabled_and_graphical_default(self):
        hook = (ROOT / 'config/hooks/live/01-navin-os-customization.hook.chroot').read_text()
        self.assertIn('navin-display-guard.service navin-display-guard-early.service', hook)
        self.assertIn('systemctl set-default graphical.target', hook)


class BootSplash(unittest.TestCase):
    def test_hw_summary_honest(self):
        line = hw.boot_hw_summary('Intel(R) Core(TM) i3 CPU M 380 @ 2.53GHz', 3891200, [{'vendor': '8086'}], True, False, True, False)
        self.assertEqual(line, 'Intel Core i3 M 380 · 3.7 GB RAM · Intel graphics · Wi-Fi · no Bluetooth · audio · no touchpad yet')
        self.assertIn('graphics not found', hw.boot_hw_summary('', 0, [], False, False, False, False))

    def test_theme_files(self):
        t = IC / 'usr/share/plymouth/themes/navin-xp'
        for f in ['logo.png', 'glow.png', 'bar.png', 'starting.png', 'tagline.png'] + [f'spinner-{i}.png' for i in range(24)]:
            self.assertTrue((t / f).exists(), f)
        self.assertIn('ScriptFile=/usr/share/plymouth/themes/navin-xp/navin-xp.script', (t / 'navin-xp.plymouth').read_text())

    def test_navin_theme_is_default_not_spinner(self):
        hook = (ROOT / 'config/hooks/live/01-navin-os-customization.hook.chroot').read_text()
        self.assertLess(hook.index('plymouth-set-default-theme -R navin-xp'), hook.index('plymouth-set-default-theme -R spinner'))


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


class BootMenu(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = tempfile.TemporaryDirectory(); d = pathlib.Path(cls.d.name)
        (d / 'boot/grub').mkdir(parents=True); (d / 'boot/grub/grub.cfg').write_text(GRUB)
        subprocess.run(['sh', str(ROOT / 'config/hooks/live/02-navin-bootmenu.hook.binary')], cwd=d, check=True, capture_output=True)
        cls.grub = (d / 'boot/grub/grub.cfg').read_text()

    @classmethod
    def tearDownClass(cls):
        cls.d.cleanup()

    def test_six_entries_live_first(self):
        top = [l.split('"')[1] for l in self.grub.splitlines() if l.startswith('menuentry ')]
        self.assertEqual(top, ['Live Mode - Start NAVIN XP from USB', 'Install NAVIN XP - HDD, SSD or USB',
                               'Safe Graphics - NAVIN XP (black screen fix)', 'Recovery Mode - NAVIN XP', 'Restart', 'Shutdown'])

    def test_timeout_15_and_default_live(self):
        self.assertIn('set timeout=15', self.grub)
        self.assertIn('set default=0', self.grub)

    def test_recovery_and_power(self):
        rec = self.grub[self.grub.index('Recovery Mode'):]
        self.assertIn('navin.recovery=1', rec.split('}')[0])
        self.assertIn('nomodeset', rec.split('}')[0])
        self.assertIn('\treboot\n', self.grub)
        self.assertIn('\thalt\n', self.grub)


APT_LIST = '''Listing...
firefox-esr/stable-security 128.5.0esr-1~deb13u1 amd64 [upgradable from: 128.4.0esr-1~deb13u1]
linux-image-amd64/stable 6.12.120-1 amd64 [upgradable from: 6.12.116-1]
firmware-iwlwifi/stable 20250410-2 all [upgradable from: 20250410-1]
'''


class UpdateCenter(unittest.TestCase):
    def test_parse_upgradable(self):
        rows = U.parse_upgradable(APT_LIST)
        self.assertEqual([(r['name'], r['security'], r['kind']) for r in rows],
                         [('firefox-esr', True, 'app'), ('linux-image-amd64', False, 'kernel'), ('firmware-iwlwifi', False, 'driver')])
        self.assertEqual(U.summary(rows), {'total': 3, 'security': 1, 'kernel': 1, 'driver': 1})
        self.assertTrue(U.is_major(rows))
        self.assertFalse(U.is_major(rows[:1]))

    def test_apt_status_and_progress(self):
        d = U.parse_apt_status('dlstatus:1:50.0:Retrieving file 1 of 3')
        self.assertEqual((d['kind'], d['percent']), ('download', 50.0))
        self.assertEqual(U.overall_percent(d), 20.0)
        i = U.parse_apt_status('pmstatus:bash:100.0000:Installed bash (amd64)')
        self.assertEqual(U.overall_percent(i), 100.0)
        self.assertEqual(U.parse_apt_status('pmerror:/var/cache/x.deb:40:dpkg failed')['kind'], 'error')
        self.assertIsNone(U.parse_apt_status('Reading package lists...'))

    def test_never_removes_packages(self):
        for cmd in U.plan('upgrade') + U.plan('download'):
            self.assertNotIn('dist-upgrade', cmd); self.assertNotIn('full-upgrade', cmd); self.assertNotIn('autoremove', cmd)
        self.assertIn('--with-new-pkgs', U.plan('upgrade')[1])

    def test_security_only_installs_given_packages(self):
        cmd = U.plan('security', ['firefox-esr'])[-1]
        self.assertEqual(cmd[-3:], ['install', '--only-upgrade', 'firefox-esr'][-3:])
        self.assertEqual(U.plan('security', []), [])

    def test_plan_rejects_unknown(self):
        with self.assertRaises(ValueError):
            U.plan('rm-rf')
        with self.assertRaises(ValueError):
            U.plan('security', ['bash; reboot'])

    def test_low_bandwidth(self):
        self.assertIn('Acquire::http::Dl-Limit=200', U.plan('upgrade', low_bandwidth=True)[1])

    def test_sizes(self):
        self.assertEqual(U.parse_sizes('Need to get 12.5 MB of archives.\nAfter this operation, 4,096 kB of additional disk space will be used.'), (12500000, 4096000))
        self.assertEqual(U.parse_sizes('Need to get 0 B/1,200 kB of archives.\nAfter this operation, 2 MB disk space will be freed.'), (0, -2000000))

    def test_simulation_flags_important_removals(self):
        sim = U.parse_simulation('Inst bash [5.2] (5.3 Debian:13/stable)\nRemv lightdm [1.32]\nRemv foo [1]\n')
        self.assertEqual(sim['remove'], ['lightdm', 'foo']); self.assertEqual(sim['important_removed'], ['lightdm'])

    def test_history(self):
        log = ('Start-Date: 2026-11-10  10:00:00\nCommandline: apt-get upgrade\nUpgrade: bash:amd64 (5.2, 5.3), curl:amd64 (8.1, 8.2)\nEnd-Date: 2026-11-10  10:01:00\n\n'
               'Start-Date: 2026-11-11  09:00:00\nCommandline: apt-get install vlc\nInstall: vlc:amd64 (3.0), libvlc5:amd64 (3.0, automatic)\nError: Sub-process /usr/bin/dpkg returned an error code (1)\nEnd-Date: 2026-11-11  09:02:00\n')
        h = U.parse_history(log)
        self.assertEqual([(e['date'], e['upgraded'], e['installed']) for e in h], [('2026-11-11  09:00:00', 0, 2), ('2026-11-10  10:00:00', 2, 0)])
        self.assertIn('dpkg returned', h[0]['error'])

    def test_preflight(self):
        self.assertEqual(U.preflight(10 ** 10, 10 ** 8, True, False), [])
        p = U.preflight(100 * 1024 * 1024, 0, False, True, battery_percent=20, on_ac=False)
        self.assertEqual(len(p), 4)

    def test_diagnose(self):
        self.assertEqual(len(U.diagnose('W: GPG error: ... NO_PUBKEY 1234')), 1)
        self.assertEqual(U.diagnose('Hit:1 http://deb.debian.org trixie InRelease'), [])

    def test_reboot_needed(self):
        self.assertTrue(U.reboot_needed(True, '6.12.116+deb13-amd64', []))
        self.assertTrue(U.reboot_needed(False, '6.12.116+deb13-amd64', ['6.12.116+deb13-amd64', '6.12.120+deb13-amd64']))
        self.assertFalse(U.reboot_needed(False, '6.12.120+deb13-amd64', ['6.12.116+deb13-amd64', '6.12.120+deb13-amd64']))

    def test_flatpak(self):
        self.assertEqual(U.parse_flatpak_updates('org.videolan.VLC\t3.0.21\tstable\nbad line\n'), [{'name': 'org.videolan.VLC', 'version': '3.0.21'}])

    def test_helper_and_polkit(self):
        helper = (IC / 'usr/lib/navin-os/navin-update-helper').read_text()
        self.assertIn('systemd-inhibit', helper)
        self.assertIn('/usr/lib/navin-os/navin-update-helper', (IC / 'usr/share/polkit-1/actions/org.navin.repair.policy').read_text())


class Release(unittest.TestCase):
    def test_version_and_newer_release(self):
        spec = importlib.util.spec_from_file_location('navin_logic', IC / 'usr/local/lib/navin/navin_logic.py')
        L = importlib.util.module_from_spec(spec); spec.loader.exec_module(L)
        self.assertEqual((L.VERSION, L.BUILD), ('3.1', 51))
        self.assertEqual(L.newer_os_release([{'tag_name': 'v3.0'}], '2.2.1')['tag_name'], 'v3.0')  # 2.2.1 users are told about NAVIN XP
        self.assertIsNone(L.newer_os_release([{'tag_name': 'v3.0-test', 'prerelease': True}], '2.2.1'))

    def test_iso_name_and_workflow(self):
        self.assertIn('navin-xp-3.1-x86_64.iso', (ROOT / 'build.sh').read_text())
        wf = (REPO / '.github/workflows/build-iso.yml').read_text()
        self.assertIn('FINAL_TAG: v3.1', wf); self.assertIn('branches: [navin-xp]', wf); self.assertIn('ISO: navin-xp-3.1-x86_64.iso', wf)

    def test_whatsnew_xp_entries_exist(self):
        data = json.loads((IC / 'usr/share/navin/whatsnew-3.0.json').read_text())
        self.assertGreaterEqual(len(data['items']), 30)
        for it in data['items']:
            if it.get('superseded'):
                continue  # replaced by a later release (shown in What's New with the reason)
            self.assertIn(it['check'], (REPO / it['path']).read_text(), it['title'])


if __name__ == '__main__':
    unittest.main()
