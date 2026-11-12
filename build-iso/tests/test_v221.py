"""NAVIN 2.2.1: real touchpad diagnosis/repair decisions, libinput settings mapping, fan diagnosis,
boot menu touchpad port fix (Samsung RV411 class) and the 2 GB ISO rule."""
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
REPO = ROOT.parent
IC = ROOT / 'config/includes.chroot'
sys.path.insert(0, str(IC / 'usr/local/lib/navin'))
spec = importlib.util.spec_from_file_location('navin_hw', IC / 'usr/local/lib/navin/navin_hw.py')
H = importlib.util.module_from_spec(spec); spec.loader.exec_module(H)

ELAN = 'I: Bus=0011 Vendor=0002 Product=000e Version=0000\nN: Name="ETPS/2 Elantech Touchpad"\nP: Phys=isa0060/serio1/input0\nH: Handlers=mouse0 event5\nB: PROP=5\nB: ABS=660800011000003\n'
KBD = 'I: Bus=0011 Vendor=0001 Product=0001 Version=ab41\nN: Name="AT Translated Set 2 keyboard"\nP: Phys=isa0060/serio0/input0\nH: Handlers=sysrq kbd event0\nB: PROP=0\n'
BASIC = 'I: Bus=0011 Vendor=0002 Product=0003 Version=0000\nN: Name="ImPS/2 Generic Wheel Mouse"\nP: Phys=isa0060/serio1/input0\nH: Handlers=mouse0 event5\nB: PROP=0\n'
USBMOUSE = 'I: Bus=0003 Vendor=046d Product=c077 Version=0111\nN: Name="Logitech USB Optical Mouse"\nP: Phys=usb-0000:00:1d.0-1/input0\nH: Handlers=mouse1 event6\nB: PROP=0\n'
SAMSUNG = {"sys_vendor": "SAMSUNG ELECTRONICS CO., LTD.", "product_name": "RV411/RV511/E3511/S3511/RV711/E3411", "chassis_type": "10"}
AUX = [{"port": "serio1", "description": "i8042 AUX port", "driver": "psmouse"}]
KBD_ONLY_LOG = "i8042: PNP: PS/2 Controller [PNP0303:KBD] at 0x60,0x64 irq 1\nserio: i8042 KBD port at 0x60,0x64 irq 1"


def diag(text, aux=(), log="", cmdline="", live=False, **kw):
    return H.touchpad_diagnose(H.parse_input_devices(text), list(aux), log, {"psmouse"}, kw.pop("dmi", SAMSUNG), [], cmdline, live=live, **kw)


class TouchpadDiagnosis(unittest.TestCase):
    def test_elan_touchpad_ok(self):
        d = diag(KBD + "\n" + ELAN, AUX)
        self.assertEqual(d["state"], "ok")
        self.assertEqual(d["devices"][0]["vendor"], "ELAN")
        self.assertIn("psmouse", d["devices"][0]["driver"])
        self.assertEqual(d["actions"], [])
        self.assertTrue(d["rv411"])

    def test_generic_ps2_pointer_is_the_touchpad_in_basic_mode(self):
        d = diag(KBD + "\n" + BASIC, AUX, "psmouse serio1: elantech: failed to query capabilities.")
        self.assertEqual(d["state"], "basic")
        self.assertIn("elantech", d["problems"][0]["cause"])
        self.assertEqual(d["actions"], [])  # never reload a working pointer

    def test_usb_mouse_is_not_the_touchpad(self):
        d = diag(KBD + "\n" + USBMOUSE, AUX)
        self.assertEqual(d["state"], "missing-port")

    def test_aux_port_without_touchpad_gets_safe_steps_in_order(self):
        d = diag(KBD, AUX)
        self.assertEqual(d["actions"], ["aux-reconnect", "psmouse-reload", "psmouse-fallback"])

    def test_rv411_missing_port_needs_nopnp_installed(self):
        d = diag(KBD, (), KBD_ONLY_LOG, cmdline="boot=live i8042.nomux=1 i8042.reset=1")
        self.assertEqual(d["state"], "no-port")
        self.assertEqual(d["kernel_params"], ["i8042.nopnp=1", "i8042.noloop=1"])
        self.assertEqual(d["actions"], ["boot-fix"])
        self.assertIn("ACPI", d["problems"][0]["cause"])

    def test_live_mode_never_writes_boot_fix(self):
        d = diag(KBD, (), KBD_ONLY_LOG, cmdline="boot=live", live=True)
        self.assertEqual(d["actions"], [])

    def test_no_port_even_with_nopnp_reports_hardware_reason(self):
        d = diag(KBD, (), "", cmdline="i8042.nopnp=1 i8042.noloop=1")
        self.assertEqual(d["actions"], [])
        self.assertIn("BIOS setup", d["problems"][0]["cause"])

    def test_desktop_without_touchpad_is_fine(self):
        d = diag(KBD, (), dmi={"sys_vendor": "Dell", "chassis_type": "3"}, laptop=False)
        self.assertEqual(d["state"], "not-laptop")
        self.assertEqual(d["actions"], [])

    def test_i2c_touchpad_from_acpi(self):
        d = H.touchpad_diagnose(H.parse_input_devices(KBD), [], "", {"psmouse"}, {"sys_vendor": "HP"}, ["PNP0C50"], "")
        self.assertEqual(d["state"], "i2c-missing")
        self.assertEqual(d["actions"], ["load-modules", "i2c-reload"])

    def test_disabled_touchpad(self):
        d = diag(ELAN, AUX, xinput_disabled=True)
        self.assertEqual(d["state"], "disabled")

    def test_kernel_log_issues(self):
        found = H.kernel_log_issues("psmouse serio1: issuing reconnect request\nACPI Error: AE_NOT_FOUND\n" + KBD_ONLY_LOG)
        self.assertEqual(set(found), {"lost_sync", "acpi_error", "i8042_kbd_only"})

    def test_samsung_quirks_include_port_probe(self):
        q = H.laptop_quirks(SAMSUNG, [], ["avx"], 4000000)
        self.assertEqual(q["kernel_params"], ["i8042.nomux=1", "i8042.reset=1", "i8042.nopnp=1", "i8042.noloop=1"])

    def test_repair_actions_are_whitelisted_in_script(self):
        script = (IC / 'usr/lib/navin-os/navin-touchpad-repair.sh').read_text()
        for a in H.REPAIR_ACTIONS:
            self.assertIn(f"    {a})", script)
        self.assertIn('refused unknown action', script)


class TouchpadSettings(unittest.TestCase):
    PROPS = H.parse_list_props("""Device 'ETPS/2 Elantech Touchpad':
	Device Enabled (170):	1
	libinput Tapping Enabled (303):	0
	libinput Natural Scrolling Enabled (311):	0
	libinput Scroll Methods Available (314):	1, 1, 0
	libinput Scroll Method Enabled (315):	1, 0, 0
	libinput Click Methods Available (317):	1, 1
	libinput Click Method Enabled (318):	1, 0
	libinput Accel Speed (322):	0.000000
	libinput Accel Profiles Available (324):	1, 1, 1
	libinput Accel Profile Enabled (325):	1, 0, 0
	libinput Disable While Typing Enabled (330):	1""")

    def test_parse(self):
        self.assertEqual(self.PROPS["libinput Scroll Method Enabled"], ["1", "0", "0"])

    def test_edge_scroll_flat_and_two_finger_click(self):
        out = dict(H.touchpad_props({"scrollmethod": "edge", "accel": "flat", "click": "fingers", "speed": "2", "tap": "on"}, self.PROPS))
        self.assertEqual(out["libinput Scroll Method Enabled"], ["0", "1", "0"])
        self.assertEqual(out["libinput Accel Profile Enabled"], ["0", "1", "0"])
        self.assertEqual(out["libinput Click Method Enabled"], ["0", "1"])
        self.assertEqual(out["libinput Accel Speed"], ["1.00"])  # clamped to -1..1
        self.assertEqual(out["libinput Tapping Enabled"], ["1"])

    def test_props_the_device_lacks_are_skipped(self):
        out = dict(H.touchpad_props({}, self.PROPS))
        self.assertNotIn("libinput Middle Emulation Enabled", out)
        self.assertNotIn("libinput Scrolling Pixel Distance", out)

    def test_unsupported_edge_scroll_not_forced(self):
        props = dict(self.PROPS, **{"libinput Scroll Methods Available": ["1", "0", "0"]})
        self.assertNotIn("libinput Scroll Method Enabled", dict(H.touchpad_props({"scrollmethod": "edge"}, props)))


class FanDiagnosis(unittest.TestCase):
    def test_samsung_silent_is_the_cause(self):
        d = H.fan_diagnose([{"temps": [{"c": 70}], "fans": []}], [], [], "silent", "none", set(), samsung=True)
        self.assertEqual(d["actions"], ["samsung-normal"])

    def test_disabled_zone_and_missing_fan_driver(self):
        zones = [{"type": "acpitz", "temp_c": 60, "mode": "disabled", "trips": [{"type": "active", "c": 60}]}]
        d = H.fan_diagnose([], [], zones, "", "none", {"coretemp"})
        self.assertEqual(d["actions"], ["enable-zones", "load-fan"])

    def test_bios_controlled_fan_is_explained_not_forced(self):
        d = H.fan_diagnose([{"temps": [{"c": 55}], "fans": []}], [], [], "normal", "none", {"coretemp"})
        self.assertEqual(d["actions"], [])
        self.assertTrue(any("BIOS/EC controls the fan" in p["cause"] for p in d["problems"]))

    def test_overheat_warning(self):
        d = H.fan_diagnose([{"temps": [{"c": 91}], "fans": [{"rpm": 1200}]}], [], [], "", "hwmon-pwm", set())
        self.assertTrue(any(p["problem"].startswith("Overheating") for p in d["problems"]))

    def test_never_overclock(self):
        self.assertEqual(H.samsung_level_for("cooling", ["silent", "normal", "overclock"]), "normal")
        self.assertEqual(H.samsung_level_for("silent", ["silent", "normal"]), "silent")


class BootMenu(unittest.TestCase):
    def test_hook_adds_port_fix(self):
        with tempfile.TemporaryDirectory() as d:
            d = pathlib.Path(d); (d / 'boot/grub').mkdir(parents=True); (d / 'isolinux').mkdir()
            (d / 'boot/grub/grub.cfg').write_text('menuentry "Live system (amd64)" {\n\tlinux\t/live/vmlinuz boot=live i8042.nomux=1 i8042.reset=1 quiet\n\tinitrd\t/live/initrd.img\n}\n')
            (d / 'isolinux/live.cfg').write_text('label live-amd64\n\tmenu label ^Live system\n\tmenu default\n\tlinux /live/vmlinuz\n\tappend boot=live i8042.nomux=1 i8042.reset=1 quiet\n')
            subprocess.run(['sh', str(ROOT / 'config/hooks/live/02-navin-bootmenu.hook.binary')], cwd=d, check=True, capture_output=True)
            iso = (d / 'isolinux/live.cfg').read_text(); grub = (d / 'boot/grub/grub.cfg').read_text()
            self.assertEqual(iso.count('i8042.nopnp=1 i8042.noloop=1'), 2)  # Live Mode + Full Installation
            self.assertEqual(grub.count('$navin_tp'), 2)
            self.assertIn('export navin_tp', grub)
            self.assertEqual(grub.count('menuentry '), 2)

    def test_quirk_file_from_repair_is_kept(self):
        with tempfile.TemporaryDirectory() as d:
            r = pathlib.Path(d); (r / 'etc/default/grub.d').mkdir(parents=True)
            f = r / 'etc/default/grub.d/90-navin-quirks.cfg'
            f.write_text('# NAVIN touchpad repair: probe\nGRUB_CMDLINE_LINUX_DEFAULT="$GRUB_CMDLINE_LINUX_DEFAULT i8042.nopnp=1"\n')
            H.apply_quirks({"kernel_params": []}, lambda m: None, root=d)
            self.assertTrue(f.exists())


class Release(unittest.TestCase):
    def test_iso_under_2_gb(self):
        self.assertIn('-gt 2000000000', (REPO / '.github/workflows/build-iso.yml').read_text())

    def test_version_tags(self):
        spec = importlib.util.spec_from_file_location('navin_logic', IC / 'usr/local/lib/navin/navin_logic.py')
        L = importlib.util.module_from_spec(spec); spec.loader.exec_module(L)
        self.assertEqual(L.os_version('v2.2.1'), (2, 2, 1))
        self.assertEqual(L.newer_os_release([{"tag_name": "v2.2.1"}], "2.2")["tag_name"], "v2.2.1")
        self.assertIsNone(L.newer_os_release([{"tag_name": "v2.2"}], "2.2.1"))

    def test_whatsnew_221_entries_exist(self):
        data = json.loads((IC / 'usr/share/navin/whatsnew-2.2.1.json').read_text())
        for it in data['items']:
            self.assertIn(it['check'], (REPO / it['path']).read_text(), it['title'])


if __name__ == '__main__':
    unittest.main()
