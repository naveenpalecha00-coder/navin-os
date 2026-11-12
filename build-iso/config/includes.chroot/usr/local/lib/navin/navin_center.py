#!/usr/bin/python3
"""NAVIN System Center (NAVIN 2.0): What's New, Laptop & Touchpad, Hardware Manager, Driver Manager, System Monitor, Performance
Center, Fan Control, Boot Manager, Recovery, System Repair, Update Manager, Hardware Diagnostics.
Every page reads real system data; privileged actions go through pkexec + whitelisted helpers."""
import gi, json, os, pathlib, re, shutil, subprocess, sys, threading, time
sys.path.insert(0, "/usr/local/lib/navin")
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib, Gdk
import psutil
import navin_hw
from navin_sys import leak_candidates, parse_systemd_analyze

REPAIR = ["pkexec", "/usr/local/lib/navin/navin-repair"]
FAN = ["pkexec", "/usr/local/lib/navin/navin-fan"]
LIVE = pathlib.Path("/run/live").exists()
PAGES = [("whatsnew", "What's New in 2.2"), ("laptop", "Touchpad"), ("hardware", "Hardware Manager"), ("drivers", "Driver Manager"), ("monitor", "System Monitor"),
         ("performance", "Performance Center"), ("fan", "Fan Control"), ("troubleshoot", "Touchpad & Fan Troubleshooter"), ("boot", "Boot Manager"),
         ("recovery", "Recovery"), ("repair", "System Repair"), ("updates", "Update Manager"),
         ("diagnostics", "Hardware Diagnostics")]


def sh(args, timeout=30):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return (p.stdout + p.stderr).strip()
    except (OSError, subprocess.SubprocessError) as e:
        return f"{args[0]}: {e}"


class Log(Gtk.ScrolledWindow):
    def __init__(self, height=220):
        super().__init__(); self.set_min_content_height(height)
        self.view = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR); self.add(self.view)
    def set(self, text):
        self.view.get_buffer().set_text(text)
    def add_text(self, text):
        b = self.view.get_buffer(); b.insert(b.get_end_iter(), text)
        self.view.scroll_to_iter(b.get_end_iter(), 0, False, 0, 0)
    def stream(self, args, done=None):
        self.add_text("$ " + " ".join(a for a in args if a != "pkexec") + "\n")
        def task():
            try:
                p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=dict(os.environ, DEBIAN_FRONTEND="noninteractive"))
                for line in p.stdout:
                    GLib.idle_add(self.add_text, line)
                rc = p.wait()
            except OSError as e:
                GLib.idle_add(self.add_text, str(e) + "\n"); rc = 1
            GLib.idle_add(self.add_text, "✔ finished\n\n" if rc == 0 else f"✘ failed (exit {rc})\n\n")
            if done:
                GLib.idle_add(done, rc)
        threading.Thread(target=task, daemon=True).start()


def background(fn, done):
    def task():
        try:
            v = fn()
        except Exception as e:  # shown to the user, never hidden
            v = f"Error: {e}"
        GLib.idle_add(done, v)
    threading.Thread(target=task, daemon=True).start()


def page(title, subtitle):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10); box.set_border_width(18)
    h = Gtk.Label(xalign=0); h.set_markup(f"<span size='x-large' weight='bold'>{title}</span>"); box.pack_start(h, False, False, 0)
    s = Gtk.Label(label=subtitle, xalign=0); s.set_line_wrap(True); s.get_style_context().add_class("dim-label"); box.pack_start(s, False, False, 0)
    return box


def row(*widgets):
    r = Gtk.Box(spacing=8)
    for w in widgets:
        r.pack_start(w, False, False, 0)
    return r


def btn(label, fn):
    b = Gtk.Button(label=label); b.connect("clicked", lambda *_: fn()); return b


def confirm(parent, text, detail=""):
    d = Gtk.MessageDialog(transient_for=parent, modal=True, message_type=Gtk.MessageType.QUESTION, buttons=Gtk.ButtonsType.OK_CANCEL, text=text)
    d.format_secondary_text(detail); ok = d.run() == Gtk.ResponseType.OK; d.destroy(); return ok


class Center(Gtk.Window):
    def __init__(self, start):
        super().__init__(title="NAVIN System Center"); self.set_default_size(1000, 680); self.connect("destroy", Gtk.main_quit)
        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        side = Gtk.StackSidebar(stack=self.stack); side.set_size_request(210, -1)
        box = Gtk.Box(); box.pack_start(side, False, False, 0); box.pack_start(self.stack, True, True, 0); self.add(box)
        self.samples = {}
        for key, title in PAGES:
            scroll = Gtk.ScrolledWindow(); scroll.add(getattr(self, "p_" + key)()); self.stack.add_titled(scroll, key, title)
        self.show_all(); self.stack.set_visible_child_name(start if start in dict(PAGES) else "hardware")

    # ---- Hardware Manager
    def p_hardware(self):
        b = page("Hardware Manager", "Detected through DMI, ACPI, PCI, USB, HID/I2C input and hwmon. Nothing is installed automatically.")
        log = Log(460); log.set("Scanning hardware…")
        refresh = lambda: background(lambda: sh(["navin-hwdetect"], 60), log.set)
        def save():
            path = pathlib.Path.home() / "navin-hardware-report.json"; path.write_text(sh(["navin-hwdetect", "--json"], 60)); log.add_text(f"\nSaved {path}\n")
        b.pack_start(row(btn("Re-scan", refresh), btn("Save JSON report", save)), False, False, 0); b.pack_start(log, True, True, 0); refresh(); return b

    # ---- Driver Manager
    def p_drivers(self):
        b = page("Driver Manager", "Only drivers that match your hardware are offered. NVIDIA proprietary drivers are offered only when nvidia-detect supports the GPU; Nouveau stays as the fallback.")
        lst = Gtk.ListBox(); log = Log(160); b.pack_start(lst, False, False, 0)
        def fill(rep):
            for c in lst.get_children():
                lst.remove(c)
            if isinstance(rep, str):
                lst.add(Gtk.Label(label=rep)); lst.show_all(); return
            items = list(rep["drivers"])
            for m in rep["touchpad"]["modules"]:
                items.append({"module": m, "reason": "Touchpad kernel driver (built into the kernel, not loaded yet)"})
            for k in rep["touchpad"]["kernel_params"]:
                items.append({"param": k, "reason": "Suggested touchpad kernel option — add in Boot Manager only if the touchpad is not smooth"})
            if not items:
                lst.add(Gtk.Label(label="All detected hardware already has its drivers.", margin=10))
            for it in items:
                r = Gtk.Box(spacing=8); r.set_border_width(8)
                name = it.get("package") or it.get("module") or it.get("param") or "Info"
                l = Gtk.Label(xalign=0); l.set_markup(f"<b>{GLib.markup_escape_text(name)}</b>\n{GLib.markup_escape_text(it['reason'])}"); l.set_line_wrap(True); l.set_max_width_chars(70)
                r.pack_start(l, True, True, 0)
                if it.get("package"):
                    def inst(p=it["package"], warn=it.get("needs_confirmation")):
                        detail = "Proprietary driver. If Secure Boot is on you must enroll a MOK key on next boot. Keep 'Safe Graphics' in the boot menu as a fallback." if warn else "Installs from the signed Debian repositories."
                        if confirm(self, f"Install {p}?", detail):
                            log.stream(REPAIR + ["install", p], lambda rc: load())
                    r.pack_end(btn("Install", inst), False, False, 0)
                if it.get("module"):
                    r.pack_end(btn("Load driver", lambda m=it["module"]: log.stream(REPAIR + ["module", m], lambda rc: load())), False, False, 0)
                lst.add(r)
            lst.show_all()
        load = lambda: background(navin_hw.collect, fill)
        b.pack_start(row(btn("Re-check drivers", load)), False, False, 0); b.pack_start(log, True, True, 0); load(); return b

    # ---- System Monitor
    def p_monitor(self):
        b = page("System Monitor", "Live CPU, memory, pressure and process data. Memory-leak watch flags processes whose memory only grows.")
        self.mon = Gtk.Label(xalign=0, selectable=True); self.mon.set_line_wrap(True); b.pack_start(self.mon, False, False, 0)
        self.procs = Log(220); self.leaks = Gtk.Label(xalign=0); b.pack_start(self.procs, True, True, 0); b.pack_start(self.leaks, False, False, 0)
        b.pack_start(row(btn("Open Task Manager", lambda: subprocess.Popen(["xfce4-taskmanager"]))), False, False, 0)
        psutil.cpu_percent(percpu=True); GLib.timeout_add_seconds(2, self.tick); GLib.timeout_add_seconds(5, self.leak_tick); return b

    def tick(self):
        if self.stack.get_visible_child_name() != "monitor":
            return True
        per = psutil.cpu_percent(percpu=True); vm = psutil.virtual_memory(); sw = psutil.swap_memory(); f = psutil.cpu_freq()
        psi = {}
        for k in ("cpu", "memory", "io"):
            try:
                psi[k] = re.search(r"some avg10=([\d.]+)", open(f"/proc/pressure/{k}").read()).group(1)
            except (OSError, AttributeError):
                psi[k] = "n/a"
        try:
            t = json.loads(pathlib.Path("/run/navin/thermal.json").read_text())
        except (OSError, ValueError):
            t = {}
        cpu = f"<b>CPU</b> {sum(per)/len(per):.0f}% · cores {' '.join(f'{p:.0f}' for p in per)}" + (f" · {f.current:.0f} MHz" if f else "")
        self.mon.set_markup(cpu + f"\n<b>RAM</b> {vm.used//2**20} / {vm.total//2**20} MB ({vm.percent}%) · <b>ZRAM/swap</b> {sw.used//2**20} / {sw.total//2**20} MB"
                            f"\n<b>Pressure (avg10)</b> CPU {psi['cpu']}% · memory {psi['memory']}% · I/O {psi['io']}%"
                            f"\n<b>Temperature</b> CPU {t.get('cpu_c') or 'n/a'} °C · GPU {t.get('gpu_c') or 'n/a'} °C · state {t.get('level', 'n/a')}")
        rows = []
        for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info"]):
            try:
                rows.append((p.info["cpu_percent"] or 0, p.info["memory_info"].rss // 2**20, p.info["pid"], p.info["name"]))
            except (psutil.Error, AttributeError):
                pass
        rows.sort(reverse=True)
        self.procs.set("  CPU%   RSS MB    PID  NAME\n" + "\n".join(f"{c:6.1f} {m:8} {pid:6}  {n}" for c, m, pid, n in rows[:15])); return True

    def leak_tick(self):
        for p in psutil.process_iter(["pid", "name", "memory_info"]):
            try:
                name, rss = self.samples.get(p.info["pid"], (p.info["name"], []))
                rss.append(p.info["memory_info"].rss // 1024); self.samples[p.info["pid"]] = (name, rss[-24:])
            except (psutil.Error, AttributeError):
                pass
        alive = set(psutil.pids()); self.samples = {k: v for k, v in self.samples.items() if k in alive}
        found = leak_candidates(self.samples)
        self.leaks.set_text("Memory-leak watch: " + (", ".join(f"{x['name']} (+{x['growth_mb']} MB)" for x in found[:5]) or "no steadily growing process in the last 2 minutes"))
        return True

    # ---- Performance Center
    def p_performance(self):
        b = page("Performance Center", "CPU power profile, RAM profile, ZRAM, SSD TRIM and repeatable benchmarks.")
        st = Gtk.Label(xalign=0, selectable=True); log = Log(200)
        upd = lambda *_: st.set_text(sh(["navin-power", "status"]) + "\nRAM profile: " + (pathlib.Path("/run/navin/memprofile").read_text().strip() if pathlib.Path("/run/navin/memprofile").exists() else "n/a") + "\n" + sh(["zramctl"]) + "\nTRIM timer: " + sh(["systemctl", "is-enabled", "fstrim.timer"]))
        prof = [btn(n.title(), lambda n=n: log.stream(["pkexec", "/usr/local/bin/navin-power", "set", n], upd)) for n in ("powersave", "balanced", "performance", "auto")]
        b.pack_start(Gtk.Label(label="CPU power profile (Auto lets TLP switch on AC/battery):", xalign=0), False, False, 0); b.pack_start(row(*prof), False, False, 0)
        combo = Gtk.ComboBoxText()
        for n in ("auto", "lite", "balanced", "standard"):
            combo.append_text(n)
        combo.set_active(0); b.pack_start(row(Gtk.Label(label="RAM profile (next boot):"), combo, btn("Save", lambda: log.stream(REPAIR + ["memprofile", combo.get_active_text()]))), False, False, 0)
        b.pack_start(row(btn("Run TRIM now", lambda: log.stream(REPAIR + ["fstrim"])), btn("Turbo on/off", lambda: log.stream(["navin-turbo", "toggle"])),
                         btn("Run benchmark", lambda: subprocess.Popen(["xfce4-terminal", "--hold", "-e", "navin-benchmark run"])), btn("Compare last two", self.compare(log))), False, False, 0)
        b.pack_start(st, False, False, 0); b.pack_start(log, True, True, 0); upd(); return b

    def compare(self, log):
        def go():
            files = sorted((pathlib.Path.home() / "navin-benchmarks").glob("*.json"))
            log.set("Run the benchmark at least twice (before and after a change)." if len(files) < 2 else sh(["navin-benchmark", "compare", str(files[-2]), str(files[-1])]))
        return go

    # ---- NAVIN 2.0: What's New (real list shipped with the image, every entry names its file)
    def p_whatsnew(self):
        b = page("What's New in NAVIN XP 3.0", "Every change below is in this system; the file that does it is shown in grey. 2.2.1, 2.2, 2.1 and 2.0 changes are kept and listed after the NAVIN XP ones.")
        items = []
        for ver in ("3.0", "2.2.1", "2.2", "2.1", "2.0"):
            try:
                items += [dict(it, category=f"{ver} · {it['category']}") for it in json.loads(pathlib.Path(f"/usr/share/navin/whatsnew-{ver}.json").read_text())["items"] if not it.get("superseded")]
            except (OSError, ValueError, KeyError):
                pass
        groups = {}
        for it in items:
            groups.setdefault(it["category"], []).append(it)
        total = Gtk.Label(xalign=0); total.set_markup(f"<b>{len(items)} changes</b> in {len(groups)} areas"); b.pack_start(total, False, False, 0)
        for cat, rows in groups.items():
            exp = Gtk.Expander(label=f"{cat} ({len(rows)})"); exp.set_expanded(cat == next(iter(groups)))
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4); inner.set_border_width(8)
            for it in rows:
                l = Gtk.Label(xalign=0); l.set_line_wrap(True)
                l.set_markup("• " + GLib.markup_escape_text(it["title"]) + "  <span foreground='#6B7280' size='small'>" + GLib.markup_escape_text(it["path"].split("includes.chroot/")[-1]) + "</span>")
                inner.pack_start(l, False, False, 0)
            exp.add(inner); b.pack_start(exp, False, False, 0)
        return b

    # ---- NAVIN 2.0: Laptop & Touchpad (old-laptop care, Samsung RV411 class)
    def p_laptop(self):
        b = page("Touchpad Control Center", "Every switch here changes the real touchpad through libinput (xinput). Detection reads /proc/bus/input/devices, "
                 "the PS/2 and I2C buses and the kernel log; repairs need your password and are verified by a new scan.")
        status = Gtk.Label(xalign=0, selectable=True); status.set_line_wrap(True); b.pack_start(status, False, False, 0)
        log = Log(200)
        def show(d):
            if isinstance(d, str):
                status.set_text(d); return
            icon = {"ok": "🟢", "basic": "🟡", "disabled": "⚪"}.get(d["state"], "🔴")
            lines = [f"<span size='large'><b>{icon} {GLib.markup_escape_text(d['summary'])}</b></span>"]
            lines.append(f"Computer: {GLib.markup_escape_text(d['model'] or 'unknown')}" + (" · Samsung RV411 profile active" if d.get("rv411") else (" · Samsung profile" if d.get("samsung") else "")))
            for p in d["devices"]:
                lines.append(GLib.markup_escape_text(f"Hardware: {p['name']} · maker {p['vendor']} · bus {p['bus']} · ID {p['id']} · driver {p['driver']}"))
            lines.append(GLib.markup_escape_text("Kernel modules: " + (", ".join(d.get("modules", [])) or "none") + " · boot options: " + (" ".join(d.get("cmdline_i8042", [])) or "none")))
            for p in d["problems"]:
                lines.append(GLib.markup_escape_text(f"• Problem: {p['problem']}\n   Cause: {p['cause']}\n   Fix: {p['fix']}"))
            status.set_markup("\n".join(lines))
        def scan(*_):
            import navin_tp
            status.set_text("Scanning the real hardware…"); background(navin_tp.collect_diag, show); return False
        def after(rc):
            sh(["navin-touchpad", "apply"]); scan()
        big = Gtk.Button(); big.add(Gtk.Label(label="AUTO DETECT & REPAIR TOUCHPAD")); big.get_style_context().add_class("suggested-action"); big.set_size_request(320, 52)
        big.connect("clicked", lambda *_: log.stream(["pkexec", "/usr/lib/navin-os/navin-touchpad-repair.sh", "run", "--manual"], after))
        rescan = Gtk.Button(label="FORCE HARDWARE RESCAN"); rescan.set_size_request(220, 52)
        rescan.connect("clicked", lambda *_: log.stream(["pkexec", "/usr/lib/navin-os/navin-touchpad-repair.sh", "rescan"], after))
        b.pack_start(row(big, rescan, btn("Touchpad hardware test", lambda: TouchpadTest(self)), btn("Refresh", scan)), False, False, 0)
        import navin_tp
        conf = {**navin_hw.TOUCHPAD_DEFAULTS, **navin_tp.load_conf()}
        grid = Gtk.Grid(column_spacing=14, row_spacing=8); r = 0
        def setting(*args):
            rc = subprocess.run(["navin-touchpad", *args], capture_output=True, text=True)
            log.add_text(f"navin-touchpad {' '.join(args)}: {'applied to the touchpad' if rc.returncode == 0 else (rc.stderr or rc.stdout).strip() or 'no touchpad found'}\n")
        for key, label in (("enabled", "Touchpad on"), ("tap", "Tap to click"), ("drag", "Tap and drag (double tap)"), ("natural", "Natural scrolling"),
                           ("dwt", "Disable touchpad while typing"), ("middle", "Middle click (press left + right together)"), ("lefthanded", "Left-handed buttons")):
            sw = Gtk.Switch(active=conf.get(key) == "on", halign=Gtk.Align.START)
            sw.connect("notify::active", lambda s, _p, k=key: setting(*(["on" if s.get_active() else "off"] if k == "enabled" else [k, "on" if s.get_active() else "off"])))
            grid.attach(Gtk.Label(label=label, xalign=0), 0, r, 1, 1); grid.attach(sw, 1, r, 1, 1); r += 1
        for key, label, opts in (("scrollmethod", "Scrolling", (("twofinger", "Two-finger scrolling"), ("edge", "Edge scrolling (where supported)"), ("none", "Off"))),
                                 ("click", "Right click", (("areas", "Press bottom-right corner"), ("fingers", "Two-finger click"))),
                                 ("accel", "Pointer acceleration", (("adaptive", "Adaptive (smooth movement)"), ("flat", "Flat (fast response, low latency)")))):
            cb = Gtk.ComboBoxText()
            for v, t in opts:
                cb.append(v, t)
            cb.set_active_id(conf.get(key) or opts[0][0]); cb.connect("changed", lambda c, k=key: setting(k, c.get_active_id()))
            grid.attach(Gtk.Label(label=label, xalign=0), 0, r, 1, 1); grid.attach(cb, 1, r, 1, 1); r += 1
        for key, label, lo, hi, step in (("speed", "Pointer speed / sensitivity", -1, 1, 0.05), ("scroll", "Scroll distance (lower = faster)", 5, 50, 1)):
            sc = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, step); sc.set_size_request(320, -1)
            try:
                sc.set_value(float(conf.get(key)))
            except (TypeError, ValueError):
                pass
            pend = {"id": 0}
            def commit(s=sc, k=key, p=pend):
                p["id"] = 0; setting(k, f"{s.get_value():.2f}" if k == "speed" else str(int(s.get_value()))); return False
            def moved(s, p=pend, c=commit):
                if p["id"]:
                    GLib.source_remove(p["id"])
                p["id"] = GLib.timeout_add(500, c)
            sc.connect("value-changed", moved)
            grid.attach(Gtk.Label(label=label, xalign=0), 0, r, 1, 1); grid.attach(sc, 1, r, 1, 1); r += 1
        b.pack_start(grid, False, False, 0)
        note = Gtk.Label(xalign=0); note.set_line_wrap(True)
        note.set_text("Palm detection is automatic in libinput when the touchpad reports finger size or pressure (no switch exists for it). "
                      "Left and right click always work; 'Right click' only chooses how. Settings are saved and applied again at every login. "
                      "Touchpad key: Fn+F5 on Samsung (XF86TouchpadToggle) or Ctrl+Win+T switches the touchpad; F10 is not taken over.")
        b.pack_start(note, False, False, 0)
        b.pack_start(Gtk.Label(label="Touchpad performance", xalign=0), False, False, 0)
        b.pack_start(row(btn("Fast response mode", lambda: setting("preset", "fast")), btn("Smooth movement mode", lambda: setting("preset", "smooth")),
                         btn("Restore optimal settings", lambda: setting("preset", "optimal")),
                         btn("Input lag diagnostics", lambda: log.set(sh(["bash", "-c", "journalctl -k -b 0 -q -o cat 2>/dev/null | grep -ciE 'lost sync|issuing reconnect' | sed 's/^/Touchpad resyncs this boot: /'; "
                                                                          "uptime; grep -E 'MemAvailable|SwapFree' /proc/meminfo; ps -eo pcpu,comm --sort=-pcpu | head -6"])))), False, False, 0)
        R = ["pkexec", "/usr/lib/navin-os/navin-touchpad-repair.sh"]
        def guarded(text, args):
            if confirm(self, text, "A backup of the NAVIN touchpad configuration is saved first. Keyboard and USB mice are not changed."):
                log.stream(R + args, after)
        b.pack_start(Gtk.Label(label="Touchpad driver", xalign=0), False, False, 0)
        b.pack_start(row(btn("Driver information", lambda: log.set(sh(["python3", "/usr/local/lib/navin/navin_tp.py", "info"]) + "\n\n" +
                                                                    sh(["dpkg-query", "-W", "-f=${Package} ${Version}\n", "xserver-xorg-input-libinput", "libinput10", "libinput-bin"]))),
                         btn("Reload touchpad module", lambda: guarded("Reload the touchpad kernel module?", ["reload"])),
                         btn("Update driver", lambda: guarded("Update the libinput touchpad driver from Debian?", ["driver", "update"])),
                         btn("Reinstall driver", lambda: guarded("Reinstall the libinput touchpad driver?", ["driver", "reinstall"]))), False, False, 0)
        b.pack_start(row(btn("Roll back last repair", lambda: guarded("Roll back to the configuration saved before the last repair?", ["driver", "rollback"])),
                         btn("Restore default driver", lambda: guarded("Remove NAVIN's saved basic-mode fallback and use the native driver next boot?", ["driver", "restore-default"])),
                         btn("Boot fix on", lambda: log.stream(["pkexec", "/usr/local/lib/navin/navin-quirks", "on"])),
                         btn("Boot fix off", lambda: log.stream(["pkexec", "/usr/local/lib/navin/navin-quirks", "off"])),
                         btn("Driver logs", lambda: log.set(sh(["tail", "-80", "/var/log/navin/touchpad-repair.log"])))), False, False, 0)
        b.pack_start(Gtk.Label(label="Uninstalling the touchpad driver is not offered: libinput is also the driver of the keyboard and USB mouse.", xalign=0, wrap=True), False, False, 0)
        b.pack_start(log, True, True, 0); scan(); return b

    # ---- Fan Control
    def p_fan(self):
        b = page("Fan Control", "Fan speed slider plus profiles. Uses only interfaces your firmware exposes (ThinkPad ACPI, hwmon PWM, ACPI platform profile). Fans are never stopped or slowed below BIOS control, the thermal guard takes over at 90 °C, and firmware control is restored on exit or error.")
        cap = sh(["/usr/local/lib/navin/navin-fan", "capability"]).strip() or "none"
        what = {"thinkpad": "ThinkPad fan levels 1–7", "hwmon-pwm": "real fan speed (PWM), lowest 30 %", "platform-profile": "firmware cooling profile (quiet / balanced / performance)",
                "none": "this laptop's BIOS does not let Linux set the fan speed (common on older laptops such as Samsung RV411). The slider limits CPU speed instead, so the laptop makes less heat."}[cap if cap in ("thinkpad", "hwmon-pwm", "platform-profile") else "none"]
        info = Gtk.Label(xalign=0); info.set_line_wrap(True); info.set_markup("<b>Slider controls:</b> " + GLib.markup_escape_text(what)); b.pack_start(info, False, False, 0)
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 5); scale.set_hexpand(True); scale.set_size_request(420, -1)
        scale.add_mark(0, Gtk.PositionType.BOTTOM, "Auto (BIOS)"); scale.add_mark(50, Gtk.PositionType.BOTTOM, "50 %"); scale.add_mark(100, Gtk.PositionType.BOTTOM, "Max")
        try:
            scale.set_value(int(pathlib.Path("/run/navin/fan-slider").read_text().strip()))
        except (OSError, ValueError):
            scale.set_value(0)
        value = Gtk.Label(label="Auto" if scale.get_value() == 0 else f"{int(scale.get_value())} %"); value.set_width_chars(6)
        st = Gtk.Label(xalign=0, selectable=True); log = Log(160)
        warn = Gtk.Label(xalign=0); warn.set_line_wrap(True); b.pack_start(warn, False, False, 0)
        def upd(*_):
            s = sh(["/usr/local/lib/navin/navin-fan", "status"])
            mode = "Monitoring only — this hardware exposes no safe fan control." if cap == "none" else ""
            st.set_text(s + "\n" + sh(["sensors"]) + ("\n" + mode if mode else ""))
            def shown(d):
                if isinstance(d, str):
                    warn.set_text(d); return
                hot = d["max_temp"] is not None and d["max_temp"] >= 85
                head = f"<b>{'🔥 OVERHEATING — ' if hot else ''}Hottest sensor: {d['max_temp'] if d['max_temp'] is not None else 'n/a'} °C · fan: {', '.join(f'{r} RPM' for r in d['rpm']) or 'RPM not reported by this BIOS'}"
                head += f" · ACPI fans: {d['acpi_fans']} · Samsung mode: {d['samsung_level'] or 'n/a'}</b>"
                warn.set_markup(head + "".join(GLib.markup_escape_text(f"\n• {p['problem']} — Cause: {p['cause']} — Fix: {p['fix']}") for p in d["problems"]))
            import navin_tp
            background(navin_tp.fan, shown); return True
        pending = {"id": 0}
        def commit():
            pending["id"] = 0; log.stream(FAN + ["set", str(int(scale.get_value()))], upd); return False
        def moved(sc):
            v = int(sc.get_value()); value.set_text("Auto" if v == 0 else f"{v} %")
            if pending["id"]:
                GLib.source_remove(pending["id"])
            pending["id"] = GLib.timeout_add(700, commit)  # wait until the finger stops moving
        scale.connect("value-changed", moved)
        r = Gtk.Box(spacing=10); r.pack_start(Gtk.Label(label="Fan speed"), False, False, 0); r.pack_start(scale, True, True, 0); r.pack_start(value, False, False, 0)
        b.pack_start(r, False, False, 0)
        b.pack_start(row(*[btn(n.title(), lambda n=n: log.stream(FAN + [n], upd)) for n in ("silent", "balanced", "cooling", "auto")], btn("Restore firmware control", lambda: (scale.set_value(0), log.stream(FAN + ["restore"], upd))),
                         btn("Diagnose & repair fan", lambda: log.stream(FAN + ["repair"], upd)), btn("Fan logs", lambda: log.set(sh(["tail", "-60", "/var/log/navin/fan.log"])))), False, False, 0)
        b.pack_start(st, False, False, 0); b.pack_start(log, False, False, 0); upd(); GLib.timeout_add_seconds(5, lambda: upd() if self.stack.get_visible_child_name() == "fan" else True); return b

    # ---- Touchpad & Fan Troubleshooter
    def p_troubleshoot(self):
        b = page("Touchpad & Fan Troubleshooter", "Problem → Cause → Recommended fix → Repair → Verification. Scans read the real hardware; repairs ask for your password.")
        out = Gtk.Label(xalign=0, selectable=True); out.set_line_wrap(True); b.pack_start(out, False, False, 0)
        log = Log(260)
        def quick():
            import navin_tp
            def both():
                return navin_tp.collect_diag(), navin_tp.fan()
            def shown(v):
                if isinstance(v, str):
                    out.set_text(v); return
                tp, fan = v
                text = [f"Touchpad: {tp['summary']}"] + [f"  • {p['problem']}\n     Cause: {p['cause']}\n     Fix: {p['fix']}" + (f"\n     Repair: {p['action']}" if p.get('action') else "") for p in tp["problems"]]
                text += [f"Fan: control {fan['control']}, hottest {fan['max_temp']} °C"] + [f"  • {p['problem']}\n     Cause: {p['cause']}\n     Fix: {p['fix']}" for p in fan["problems"]]
                out.set_text("\n".join(text))
            out.set_text("Scanning…"); background(both, shown)
        R = ["pkexec", "/usr/lib/navin-os/navin-touchpad-repair.sh"]
        b.pack_start(row(btn("Quick hardware scan", quick), btn("Full hardware scan", lambda: log.stream(["navin-hwdetect"], lambda rc: quick())),
                         btn("Touchpad repair wizard", lambda: log.stream(R + ["run", "--manual"], lambda rc: quick())),
                         btn("Driver repair wizard", lambda: confirm(self, "Reinstall the touchpad driver packages?", "Needs internet. A backup is made first.") and log.stream(R + ["driver", "reinstall"], lambda rc: quick())),
                         btn("Fan repair wizard", lambda: log.stream(FAN + ["repair"], lambda rc: quick()))), False, False, 0)
        def export():
            rep = sh(R + ["report"], 60).splitlines()
            path = rep[-1] if rep else ""
            dest = pathlib.Path.home() / "NAVIN-touchpad-fan-report.txt"
            try:
                dest.write_text(pathlib.Path(path).read_text(errors="replace") + "\n\n== fan\n" + sh(["python3", "/usr/local/lib/navin/navin_tp.py", "fan"]) + "\n" + sh(["sensors"]))
                log.set(f"Report saved: {dest}")
            except OSError as e:
                log.set(f"Report not saved: {e}")
        b.pack_start(row(btn("Thermal diagnostics", lambda: log.set(sh(["sensors"]) + "\n" + sh(["bash", "-c", "for z in /sys/class/thermal/thermal_zone*; do echo \"${z##*/} $(cat $z/type) $(( $(cat $z/temp)/1000 )) C mode=$(cat $z/mode 2>/dev/null) policy=$(cat $z/policy 2>/dev/null)\"; done; for c in /sys/class/thermal/cooling_device*; do echo \"${c##*/} $(cat $c/type) $(cat $c/cur_state)/$(cat $c/max_state)\"; done"]))),
                         btn("Kernel input diagnostics", lambda: log.set(sh(["python3", "/usr/local/lib/navin/navin_tp.py", "info"]) + "\n\n" + sh(["cat", "/proc/bus/input/devices"]))),
                         btn("Hardware compatibility report", lambda: log.set(sh(["navin-hwdetect"]))),
                         btn("Generate diagnostic report", lambda: log.set(sh(R + ["report"], 60))), btn("Export system logs", export)), False, False, 0)
        b.pack_start(log, True, True, 0); quick(); return b

    # ---- Boot Manager
    def p_boot(self):
        b = page("Boot Manager", "Boot timing and installed-system boot menu settings.")
        log = Log(260)
        info = sh(["systemd-analyze", "time"]) + "\n\nSlowest services:\n" + "\n".join(sh(["systemd-analyze", "blame"]).splitlines()[:10]) + "\n\nUEFI entries:\n" + (sh(["efibootmgr"]) if pathlib.Path("/sys/firmware/efi").exists() else "Legacy BIOS boot")
        if LIVE:
            b.pack_start(Gtk.Label(label="Live session: the boot menu (Live Mode / Full Installation / Safe Graphics) is on the USB. Settings below apply after installation.", xalign=0, wrap=True), False, False, 0)
        else:
            cfg = pathlib.Path("/etc/default/grub").read_text(errors="replace") if pathlib.Path("/etc/default/grub").exists() else ""
            cur = int((re.search(r"^GRUB_TIMEOUT=(\d+)", cfg, re.M) or [0, 5])[1])
            spin = Gtk.SpinButton.new_with_range(0, 30, 1); spin.set_value(cur)
            b.pack_start(row(Gtk.Label(label="Boot menu timeout (seconds):"), spin, btn("Apply", lambda: log.stream(REPAIR + ["grub-timeout", str(int(spin.get_value()))])),
                             btn("Regenerate boot menu", lambda: log.stream(REPAIR + ["grub-update"]))), False, False, 0)
        log.set(info); b.pack_start(log, True, True, 0); return b

    # ---- Recovery
    def p_recovery(self):
        b = page("Recovery", "Snapshots, boot repair and desktop reset. In an emergency choose 'Safe Graphics' or 'Memory test' in the boot menu.")
        log = Log(260)
        def reset_desktop():
            if not confirm(self, "Reset desktop settings?", "Your current Xfce settings are moved to a backup folder, then NAVIN defaults are restored. You will be logged out."):
                return
            cfg = pathlib.Path.home() / ".config/xfce4"; bak = cfg.with_name("xfce4.backup-" + time.strftime("%Y%m%d-%H%M%S"))
            if cfg.exists():
                cfg.rename(bak)
            shutil.copytree("/etc/skel/.config/xfce4", cfg); log.add_text(f"Backup saved to {bak}\n"); subprocess.Popen(["xfce4-session-logout", "--logout"])
        b.pack_start(row(btn("Open Timeshift", lambda: subprocess.Popen(["timeshift-launcher"])), btn("Create snapshot now", lambda: log.stream(["pkexec", "timeshift", "--create", "--comments", "NAVIN manual", "--tags", "O"])),
                         btn("Rebuild initramfs", lambda: log.stream(REPAIR + ["initramfs"])), btn("Regenerate GRUB", lambda: log.stream(REPAIR + ["grub-update"])), btn("Reset my desktop", reset_desktop)), False, False, 0)
        b.pack_start(log, True, True, 0); return b

    # ---- System Repair
    def p_repair(self):
        b = page("System Repair", "Each button runs one whitelisted repair and shows its full output.")
        log = Log(320); acts = [("Wi-Fi", "wifi"), ("Network", "network"), ("Bluetooth", "bluetooth"), ("Broken packages", "packages"), ("Failed services", "services"), ("Clock", "time"), ("Clean caches", "clean"), ("Printer", "printer"), ("Firewall on", "firewall-on")]
        grid = Gtk.FlowBox(max_children_per_line=5, selection_mode=Gtk.SelectionMode.NONE)
        for label, a in acts:
            grid.add(btn(label, lambda a=a: log.stream(REPAIR + [a])))
        b.pack_start(grid, False, False, 0); b.pack_start(log, True, True, 0); return b

    # ---- Update Manager
    def p_updates(self):
        b = page("Update Manager", "Debian 13 packages and security fixes come from signed repositories (APT verifies every InRelease signature). Flatpak apps update from Flathub.")
        log = Log(320)
        def check():
            def after(rc):
                up = sh(["apt", "list", "--upgradable"]).splitlines()[1:]
                sec = [u for u in up if "-security" in u]
                log.add_text(f"{len(up)} updates available, {len(sec)} security updates.\n" + "\n".join(up[:60]) + "\n")
            log.stream(REPAIR + ["apt-update"], after)
        insecure = [str(p) for p in [pathlib.Path("/etc/apt/sources.list"), *pathlib.Path("/etc/apt/sources.list.d").glob("*")] if p.is_file() and re.search(r"trusted=yes|allow-insecure", p.read_text(errors="replace"))]
        b.pack_start(Gtk.Label(label=("⚠ Unsigned repository found: " + ", ".join(insecure)) if insecure else "✔ All configured repositories require valid signatures.", xalign=0), False, False, 0)
        b.pack_start(row(btn("Check for updates", check), btn("Install all updates", lambda: confirm(self, "Install all updates now?", "Keep the computer plugged in.") and log.stream(REPAIR + ["upgrade"])),
                         btn("Update Flatpak apps", lambda: log.stream(REPAIR + ["flatpak-update"])), btn("NAVIN releases", lambda: subprocess.Popen(["navin-updater"])),
                         btn("Open NAVIN XP Update Center", lambda: subprocess.Popen(["navin-update-center"]))), False, False, 0)
        b.pack_start(log, True, True, 0); return b

    # ---- Hardware Diagnostics
    def p_diagnostics(self):
        b = page("Hardware Diagnostics", "Graphics, video acceleration, Vulkan, audio, network, sensors, battery and disk health.")
        log = Log(460)
        checks = [("Graphics renderer", ["glxinfo", "-B"]), ("Video acceleration (VA-API)", ["vainfo"]), ("Vulkan", ["vulkaninfo", "--summary"]),
                  ("Audio devices", ["aplay", "-l"]), ("Network", ["nmcli", "device"]), ("Radios", ["rfkill", "list"]), ("Sensors", ["sensors"]),
                  ("Kernel errors this boot", ["journalctl", "-p", "3", "-b", "--no-pager", "-n", "40"])]
        def run_all():
            def collect():
                out = []
                rep = navin_hw.collect()
                out.append("== Battery health ==\n" + ("\n".join(f"{x['name']}: {x['health_percent']}% of design capacity, {x['capacity']}% charged" for x in rep["batteries"]) or "No battery"))
                for title, args in checks:
                    out.append(f"== {title} ==\n" + (sh(args, 40) if shutil.which(args[0]) else f"{args[0]} not installed"))
                return "\n\n".join(out)
            log.set("Running diagnostics…"); background(collect, log.set)
        def save():
            p = pathlib.Path.home() / ("navin-diagnostics-" + time.strftime("%Y%m%d-%H%M%S") + ".txt"); b2 = log.view.get_buffer()
            p.write_text(b2.get_text(b2.get_start_iter(), b2.get_end_iter(), False)); log.add_text(f"\nSaved {p}\n")
        b.pack_start(row(btn("Run diagnostics", run_all), btn("Disk health (SMART)", lambda: log.stream(REPAIR + ["smart"])), btn("Save report", save)), False, False, 0)
        b.pack_start(log, True, True, 0); return b



class TouchpadTest(Gtk.Window):
    """Touchpad hardware test: counts only real events whose source device is the built-in touchpad."""
    def __init__(self, parent):
        super().__init__(title="Touchpad hardware test", transient_for=parent); self.set_default_size(620, 460)
        import navin_tp
        names = [sh(["xinput", "list", "--name-only", i]) for i in navin_tp.xinput_ids()]
        self.names = {n for n in names if n}
        self.seen = {"move": 0, "left": 0, "right": 0, "middle": 0, "scroll": 0, "gesture": 0}
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8); box.set_border_width(14); self.add(box)
        head = Gtk.Label(xalign=0, wrap=True)
        head.set_text(("Testing: " + ", ".join(sorted(self.names))) if self.names else "No touchpad device in X - run Auto Detect & Repair first. Nothing can pass without real touchpad events.")
        box.pack_start(head, False, False, 0)
        self.area = Gtk.EventBox(); self.area.set_size_request(-1, 220)
        self.area.add(Gtk.Label(label="Use the touchpad here: move · left click/tap · right click · two-finger scroll"))
        self.area.add_events(Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.SCROLL_MASK |
                             Gdk.EventMask.SMOOTH_SCROLL_MASK | Gdk.EventMask.TOUCHPAD_GESTURE_MASK)
        self.area.connect("event", self.on_event)  # one handler: every real event is counted once
        frame = Gtk.Frame(); frame.add(self.area); box.pack_start(frame, True, True, 0)
        self.result = Gtk.Label(xalign=0, selectable=True); box.pack_start(self.result, False, False, 0)
        caps = sh(["bash", "-c", "libinput list-devices 2>/dev/null | grep -A12 -iE 'Device:.*(touchpad|ps/2)' | grep -E 'Capabilities|Nat.scrolling|Tap-to-click|Scroll methods'"])
        box.pack_start(Gtk.Label(label="libinput: " + (caps or "not available"), xalign=0, wrap=True), False, False, 0)
        self.update(); self.show_all()

    def on_event(self, w, ev):
        dev = ev.get_source_device()
        if not dev or dev.get_name() not in self.names:
            return False  # other mice / keyboard never count
        t = ev.type
        if t == Gdk.EventType.MOTION_NOTIFY:
            self.seen["move"] += 1
        elif t == Gdk.EventType.BUTTON_PRESS:
            self.seen[{1: "left", 2: "middle", 3: "right"}.get(ev.button, "left")] += 1
        elif t == Gdk.EventType.SCROLL:
            self.seen["scroll"] += 1
        elif t in (Gdk.EventType.TOUCHPAD_SWIPE, Gdk.EventType.TOUCHPAD_PINCH):
            self.seen["gesture"] += 1
        self.update(); return False

    def update(self):
        s = self.seen
        rows = [("Pointer movement (single finger)", s["move"] >= 20), ("Left click / tap", s["left"] > 0), ("Right click", s["right"] > 0),
                ("Two-finger / edge scrolling", s["scroll"] >= 3), ("Multi-touch gesture (pinch/swipe, where supported)", s["gesture"] > 0)]
        self.result.set_text("\n".join(f"{'✔ PASS' if ok else '… waiting'}  {name}" for name, ok in rows) + f"\nreal events: {s}")


if __name__ == "__main__":
    Center(sys.argv[1] if len(sys.argv) > 1 else "hardware"); Gtk.main()
