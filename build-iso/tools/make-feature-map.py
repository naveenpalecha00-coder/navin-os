#!/usr/bin/env python3
"""Writes usr/share/navin/features-2.2.json: every feature named in the NAVIN 2.1/2.2 request
(sections 1-14 = slots 1-1000, plus 1001-1100) and the real NAVIN part that provides it.
tests/test_v22.py checks every entry (package in the ISO list, App Store entry, Toolbox tool, shortcut or file text).
usage: make-feature-map.py ITEMS.json MAP.py"""
import json, pathlib, runpy, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
items = json.load(open(sys.argv[1]))
m = runpy.run_path(sys.argv[2])
M, ALIAS, NAMED = m["M"], m["SECTION_ALIASES"], m["NAMED"]


def entry(spec):
    kind, _, ref = spec.partition(":")
    e = {"kind": kind}
    if kind in ("partial", "none"):
        inner, _, why = ref.rpartition("::")
        e["note"] = why
        if inner:
            e["via"] = entry(inner)
    else:
        e["ref"] = ref
    return e


out = {"version": "2.2", "sections": [], "named": []}
for sec, a, b, names in items["sections"]:
    rows = []
    for i, n in enumerate(names):
        n = n.split(". ")[0] if n.startswith(("recovery after failed updates", "first-boot setup")) else n
        key = ALIAS.get((sec, n), n)
        if key not in M:
            sys.exit(f"no mapping for {sec}: {n}")
        rows.append({"n": a + i, "name": n.replace(". Add customizable shortcut management", " + customizable shortcut management")
                     .replace(". Connect to the official NAVIN OS update infrastructure. Never pretend that Lovable changes automatically reach an installed OS without a real signed update pipeline", "")
                     .replace(". Live Mode must work without installing to the internal disk", ""), **entry(M[key])})
    out["sections"].append({"title": sec.title().replace("&", "&"), "slots": f"{a}-{b}", "items": rows})
for num, name in items["named"]:
    out["named"].append({"n": int(num), "name": name.strip(), **entry(NAMED[num])})
dst = ROOT / "config/includes.chroot/usr/share/navin/features-2.2.json"
dst.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
kinds = {}
for r in [r for s in out["sections"] for r in s["items"]] + out["named"]:
    kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
print(dst, kinds)
