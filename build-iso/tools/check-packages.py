#!/usr/bin/env python3
"""Check NAVIN OS package lists against the official Debian archive indexes.

Usage: check-packages.py [--suite trixie] [--cache DIR]
Exit 1 if any REQUIRED package (config/package-lists/*.list.chroot) is missing.
Optional packages (config/navin-optional-packages.list) are reported, never fatal.
Writes a Markdown report to stdout.
"""
import argparse, lzma, pathlib, re, sys, urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
COMPONENTS = ("main", "contrib", "non-free", "non-free-firmware")


def parse_list(text):
    """Package names from a live-build list (comments, blank lines and #if blocks ignored)."""
    names = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        names.extend(line.split())
    return names


def parse_index(text):
    """Return set of real package names and set of virtual (Provides) names."""
    real, virtual = set(), set()
    for line in text.splitlines():
        if line.startswith("Package: "):
            real.add(line[9:].strip())
        elif line.startswith("Provides: "):
            for item in line[10:].split(","):
                virtual.add(re.split(r"[\s(]", item.strip(), maxsplit=1)[0])
    return real, virtual


def resolve(name, real, virtual):
    base = name.split(":", 1)[0]
    if base in real:
        return "ok"
    if base in virtual:
        return "virtual"
    return "missing"


def fetch(suite, comp, arch, cache):
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / f"{suite}-{comp}-{arch}.txt"
    if not path.exists():
        url = f"http://deb.debian.org/debian/dists/{suite}/{comp}/binary-{arch}/Packages.xz"
        with urllib.request.urlopen(url, timeout=120) as r:
            path.write_text(lzma.decompress(r.read()).decode("utf-8", "replace"))
    return path.read_text()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--suite", default="trixie")
    ap.add_argument("--cache", default="/tmp/navin-apt-index")
    a = ap.parse_args()
    cache = pathlib.Path(a.cache)
    idx = {}
    for arch in ("amd64", "i386"):
        real, virtual = set(), set()
        for comp in COMPONENTS:
            r, v = parse_index(fetch(a.suite, comp, arch, cache))
            real |= r; virtual |= v
        idx[arch] = (real, virtual)
    required = []
    for f in sorted((ROOT / "config/package-lists").glob("*.list.chroot")):
        required += parse_list(f.read_text())
    opt_file = ROOT / "config/includes.chroot/usr/share/navin/optional-packages.list"
    optional = parse_list(opt_file.read_text()) if opt_file.exists() else []
    bad = []
    print(f"# NAVIN OS package check — Debian {a.suite}\n")
    for title, names in (("Required", required), ("Optional", optional)):
        print(f"## {title} ({len(set(names))})\n")
        for n in sorted(set(names)):
            arch = "i386" if n.endswith(":i386") else "amd64"
            state = resolve(n, *idx[arch])
            if state != "ok":
                print(f"- {n}: {state}")
            if title == "Required" and state == "missing":
                bad.append(n)
        print()
    if bad:
        print("REQUIRED PACKAGES MISSING: " + " ".join(bad))
        return 1
    print("All required packages resolve.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
