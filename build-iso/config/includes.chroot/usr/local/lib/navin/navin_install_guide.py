#!/usr/bin/python3
"""NAVIN OS 1.2 "Before you install" guide. Shows what this computer has (start mode, Secure Boot,
RAM, disks, Windows/other systems, BitLocker, power, internet) and plain advice for dual boot,
then opens the real Calamares installer. It only reads the system; nothing is written to a disk."""
import gi, os, shutil, subprocess, sys, threading
sys.path.insert(0, "/usr/local/lib/navin")
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib
import navin_install

ICON = {"block": "dialog-error", "warn": "dialog-warning", "ok": "emblem-ok-symbolic"}
CHOICES = [("Install alongside", "Keeps Windows or another system. You choose how much space NAVIN OS gets."),
           ("Replace a partition", "Installs NAVIN OS over one partition you pick. Only that partition is erased."),
           ("Erase disk", "Deletes everything on the chosen disk and gives it all to NAVIN OS."),
           ("Manual partitioning", "For experts: create partitions yourself (needs an EFI partition in UEFI mode).")]


def open_installer():
    for cmd in (["calamares-install-debian"], ["install-debian"], ["pkexec", "calamares"]):
        if shutil.which(cmd[0]):
            subprocess.Popen(cmd, start_new_session=True)
            return True
    return False


class Guide(Gtk.Window):
    def __init__(self):
        super().__init__(title="Install NAVIN OS — before you start")
        self.set_default_size(720, 640); self.set_border_width(16)
        self.set_icon_from_file("/usr/share/pixmaps/navin-os-logo.png") if os.path.exists("/usr/share/pixmaps/navin-os-logo.png") else None
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10); self.add(box)
        title = Gtk.Label(xalign=0); title.set_markup("<span size='x-large' weight='bold'>Install NAVIN OS 1.2</span>")
        box.pack_start(title, False, False, 0)
        box.pack_start(Gtk.Label(label="NAVIN checks this computer first so the installer choices are clear. Nothing is changed yet.",
                                 xalign=0, wrap=True), False, False, 0)
        sw = Gtk.ScrolledWindow(); sw.set_vexpand(True); box.pack_start(sw, True, True, 0)
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8); sw.add(self.body)
        self.spinner = Gtk.Spinner(); self.spinner.start()
        row = Gtk.Box(spacing=8); row.pack_start(self.spinner, False, False, 0)
        row.pack_start(Gtk.Label(label="Checking disks and other operating systems…", xalign=0), False, False, 0)
        self.body.pack_start(row, False, False, 0)
        bar = Gtk.Box(spacing=8); box.pack_start(bar, False, False, 0)
        self.recheck = Gtk.Button(label="Check again"); self.recheck.connect("clicked", lambda *_: self.scan())
        gp = Gtk.Button(label="Open GParted"); gp.connect("clicked", lambda *_: subprocess.Popen(["pkexec", "gparted"], start_new_session=True))
        gp.set_sensitive(bool(shutil.which("gparted")))
        cancel = Gtk.Button(label="Cancel"); cancel.connect("clicked", lambda *_: Gtk.main_quit())
        self.go = Gtk.Button(label="Open installer"); self.go.get_style_context().add_class("suggested-action")
        self.go.set_sensitive(False); self.go.connect("clicked", self.launch)
        for w in (self.recheck, gp):
            bar.pack_start(w, False, False, 0)
        bar.pack_end(self.go, False, False, 0); bar.pack_end(cancel, False, False, 0)
        self.scan()

    def scan(self):
        self.recheck.set_sensitive(False); self.go.set_sensitive(False)
        threading.Thread(target=lambda: GLib.idle_add(self.show, navin_install.collect()), daemon=True).start()

    def section(self, text):
        l = Gtk.Label(xalign=0); l.set_markup(f"<b>{GLib.markup_escape_text(text)}</b>"); l.set_margin_top(8)
        self.body.pack_start(l, False, False, 0)

    def line(self, icon, title, text):
        row = Gtk.Box(spacing=10)
        row.pack_start(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.LARGE_TOOLBAR), False, False, 0)
        l = Gtk.Label(xalign=0, wrap=True); l.set_max_width_chars(80)
        l.set_markup(f"<b>{GLib.markup_escape_text(title)}</b>\n{GLib.markup_escape_text(text)}")
        row.pack_start(l, True, True, 0); self.body.pack_start(row, False, False, 0)

    def show(self, info):
        for c in self.body.get_children():
            self.body.remove(c)
        sb = {True: "on", False: "off", None: "unknown"}[info["secure_boot"]]
        self.section("This computer")
        self.line("computer", "Start mode", f"{'UEFI' if info['firmware'] == 'uefi' else 'Legacy BIOS'} · Secure Boot {sb} · "
                  f"{info['ram_mb']} MB RAM · {'battery' if info['on_battery'] else 'mains power'} · "
                  f"{'internet connected' if info['online'] else 'offline'}")
        self.section("Disks")
        disks = [d for d in info["disks"] if not d["live"]] or []
        if not disks:
            self.line("drive-harddisk", "No disks found", "Connect a disk and press Check again.")
        for d in disks:
            parts = ", ".join(f"{p['name'].rsplit('/', 1)[-1]} {p['fstype'] or 'empty'} {p['size_gb']} GB" for p in d["parts"]) or "no partitions"
            self.line("drive-removable-media" if d["removable"] else "drive-harddisk",
                      f"{d['name']} · {d['model'] or 'disk'} · {d['size_gb']} GB" + (" · USB" if d["removable"] else ""),
                      f"Table: {d['table'] or 'none'} · {parts}")
        self.section("Advice")
        advice = navin_install.assess(info)
        for level, title, text in advice:
            self.line(ICON[level], title, text)
        self.section("Installer choices on the Partitions page")
        for title, text in CHOICES:
            self.line("dialog-information", title, text)
        self.body.show_all(); self.recheck.set_sensitive(True)
        self.go.set_sensitive(navin_install.can_install(advice))
        return False

    def launch(self, *_):
        if not open_installer():
            self.line("dialog-error", "Installer not found", "Calamares is not installed on this USB.")
            self.body.show_all(); return
        Gtk.main_quit()


if __name__ == "__main__":
    w = Guide(); w.connect("destroy", Gtk.main_quit); w.show_all(); Gtk.main()
