"""NAVIN OS 1.2 pure helpers: keyboard shortcuts, benchmarks, memory-leak watch."""
import re
import xml.etree.ElementTree as ET

MODS = {"primary": "Ctrl", "control": "Ctrl", "ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "super": "Super", "mod4": "Super"}
MOD_ORDER = ("Ctrl", "Alt", "Shift", "Super")
LOWER_IS_BETTER = {"boot_s", "login_s", "cpu_idle_percent", "ram_used_mb", "app_launch_s", "thunar_launch_s", "max_psi_full"}


def normalize_accel(accel):
    """'<Primary><Alt>t' -> 'Ctrl+Alt+T'; 'Super_L' -> 'Super'."""
    mods = {MODS.get(m.lower(), m.title()) for m in re.findall(r"<([^>]+)>", accel)}
    key = re.sub(r"<[^>]+>", "", accel)
    if key in ("Super_L", "Super_R"):
        key, mods = "", mods | {"Super"}
    key = key.upper() if len(key) == 1 else key
    parts = [m for m in MOD_ORDER if m in mods] + sorted(mods - set(MOD_ORDER))
    return "+".join(parts + ([key] if key else []))


def parse_shortcuts(xml_text):
    """Return list of (section, accel, action) from xfce4-keyboard-shortcuts.xml custom sets."""
    root = ET.fromstring(xml_text)
    out = []
    for section in ("commands", "xfwm4"):
        sec = root.find(f"./property[@name='{section}']/property[@name='custom']")
        if sec is None:
            continue
        for p in sec.findall("property"):
            if p.get("name") != "override":
                out.append((section, p.get("name"), p.get("value")))
    return out


def find_conflicts(shortcuts):
    """shortcuts: iterable of (section, accel, action). Returns {normalized: [actions]} with >1 binding."""
    seen = {}
    for section, accel, action in shortcuts:
        seen.setdefault(normalize_accel(accel), []).append(f"{section}:{action}")
    return {k: v for k, v in seen.items() if len(v) > 1}


def search_shortcuts(shortcuts, query):
    q = query.lower().strip()
    return [s for s in shortcuts if q in normalize_accel(s[1]).lower() or q in (s[2] or "").lower()]


def compare_benchmarks(before, after):
    """Return {metric: {'before','after','change_percent','better'}} for metrics in both."""
    out = {}
    for k in sorted(set(before) & set(after)):
        a, b = before[k], after[k]
        if not isinstance(a, (int, float)) or not isinstance(b, (int, float)) or isinstance(a, bool):
            continue
        change = None if a == 0 else round((b - a) * 100 / a, 1)
        better = (b < a) if k in LOWER_IS_BETTER else (b > a)
        out[k] = {"before": a, "after": b, "change_percent": change, "better": better if a != b else None}
    return out


def leak_candidates(samples, min_growth_mb=64, min_samples=6):
    """samples: {pid: (name, [rss_kb,...])}. Flags steady RSS growth (never shrinking) above threshold."""
    flagged = []
    for pid, (name, rss) in samples.items():
        if len(rss) < min_samples:
            continue
        rises = all(b >= a for a, b in zip(rss, rss[1:]))
        growth = (rss[-1] - rss[0]) / 1024
        if rises and growth >= min_growth_mb:
            flagged.append({"pid": pid, "name": name, "growth_mb": round(growth, 1)})
    return sorted(flagged, key=lambda x: -x["growth_mb"])


def parse_systemd_analyze(text):
    """'Startup finished in 3.1s (kernel) + 9.4s (userspace) = 12.5s' -> 12.5 (seconds)."""
    m = re.search(r"=\s*(?:(\d+)min\s*)?([\d.]+)(ms|s)", text)
    if not m:
        return None
    value = float(m.group(2)) / (1000 if m.group(3) == "ms" else 1)
    return round(value + 60 * int(m.group(1) or 0), 2)


def classify_swipe(dx, dy, width, height, threshold=0.15):
    """Three-finger swipe direction from total movement relative to the touchpad size."""
    if not width or not height:
        return None
    rx, ry = dx / width, dy / height
    if max(abs(rx), abs(ry)) < threshold:
        return None
    if abs(rx) >= abs(ry):
        return "right" if rx > 0 else "left"
    return "down" if ry > 0 else "up"
