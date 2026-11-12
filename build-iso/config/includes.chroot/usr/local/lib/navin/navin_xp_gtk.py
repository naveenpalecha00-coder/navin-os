"""NAVIN XP 3.1 shared GTK pieces: glass CSS (#1677F2 / #F8FAFF), live graph, command runner.
Logic lives in navin_xp.py; this file only draws and runs real commands."""
import os, subprocess, threading
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib
import navin_xp as X

CSS = b"""
window, .navin-bg { background-color: #F8FAFF; color: #17243A; }
.navin-card { background-color: rgba(255,255,255,0.75); border: 1px solid rgba(22,119,242,0.18); border-radius: 14px; padding: 12px; }
.navin-title { font-size: 18px; font-weight: bold; color: #17243A; }
.navin-big { font-size: 22px; font-weight: bold; color: #1677F2; }
.navin-muted { color: #5B6B85; }
.navin-bad { color: #C62828; font-weight: bold; }
.navin-good { color: #1B7F3B; font-weight: bold; }
button.suggested-action { background: #1677F2; color: #FFFFFF; border-radius: 10px; }
"""


def setup(title, w=860, h=600):
    prov = Gtk.CssProvider(); prov.load_from_data(CSS)
    Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    win = Gtk.Window(title=title); win.set_default_size(w, h); win.connect("destroy", Gtk.main_quit)
    return win


def language():
    try:
        saved = open(os.path.expanduser("~/.config/navin/lang")).read()
    except OSError:
        saved = None
    return X.lang(saved=saved)


def label(text, cls=None, xalign=0.0, wrap=True):
    l = Gtk.Label(label=text, xalign=xalign); l.set_line_wrap(wrap); l.set_selectable(False)
    if cls:
        l.get_style_context().add_class(cls)
    return l


def card(*children, spacing=6):
    b = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing); b.get_style_context().add_class("navin-card")
    for c in children:
        b.pack_start(c, False, False, 0)
    return b


def read(path, default=""):
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return default


class Graph(Gtk.DrawingArea):
    """Real-time line graph of the last 60 samples (values 0..max)."""
    def __init__(self, maximum=100.0, height=90):
        super().__init__(); self.values = []; self.maximum = maximum; self.set_size_request(220, height)
        self.connect("draw", self.on_draw)

    def push(self, v):
        self.values = (self.values + [float(v)])[-60:]; self.queue_draw()

    def on_draw(self, _w, cr):
        a = self.get_allocation(); w, h = a.width, a.height
        cr.set_source_rgba(1, 1, 1, 0.9); cr.rectangle(0, 0, w, h); cr.fill()
        cr.set_source_rgba(0.086, 0.467, 0.949, 0.15); cr.set_line_width(1)
        for i in range(1, 4):
            cr.move_to(0, h * i / 4); cr.line_to(w, h * i / 4)
        cr.stroke()
        if len(self.values) < 2:
            return
        top = max(self.maximum, max(self.values)) or 1
        step = w / 59.0; x0 = w - step * (len(self.values) - 1)
        cr.move_to(x0, h)
        for i, v in enumerate(self.values):
            cr.line_to(x0 + i * step, h - (v / top) * (h - 4))
        cr.line_to(w, h); cr.close_path()
        cr.set_source_rgba(0.086, 0.467, 0.949, 0.25); cr.fill_preserve()
        cr.set_source_rgb(0.086, 0.467, 0.949); cr.set_line_width(2); cr.stroke()


class Runner:
    """Runs one real command, streams its output into a TextView, calls done(rc, text)."""
    def __init__(self, view):
        self.view = view; self.proc = None

    def busy(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self, cmd, done=None):
        if self.busy():
            return False
        buf = self.view.get_buffer(); buf.set_text("$ " + " ".join(cmd) + "\n")
        try:
            self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        except OSError as e:
            buf.insert(buf.get_end_iter(), str(e) + "\n")
            if done:
                done(127, str(e))
            return False
        out = []
        def pump():
            for line in self.proc.stdout:
                out.append(line); GLib.idle_add(self._append, line)
            rc = self.proc.wait()
            if done:
                GLib.idle_add(done, rc, "".join(out))
        threading.Thread(target=pump, daemon=True).start()
        return True

    def _append(self, line):
        buf = self.view.get_buffer(); buf.insert(buf.get_end_iter(), line)
        self.view.scroll_to_iter(buf.get_end_iter(), 0, False, 0, 0)
        return False


def output_view():
    tv = Gtk.TextView(editable=False, monospace=True, cursor_visible=False); tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
    sw = Gtk.ScrolledWindow(); sw.set_min_content_height(160); sw.add(tv)
    return tv, sw
