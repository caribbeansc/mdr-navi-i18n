"""Fold a work/tr_*.py table of translations into langs/<code>/."""
import importlib.util, sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from navi.rom import Rom
from navi.catalog import build
from navi.config import Config
from navi.lang import Pack, Entry, fingerprint

def load(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    table = getattr(mod, "T", None)
    if not isinstance(table, dict):
        print(f"  skipping {path.name}: no T dict")
        return {}
    return table

rom = Rom.load(Config.load().resolve_rom())
cat = build(rom)
pack = Pack.load(sys.argv[1] if len(sys.argv) > 1 else "es")
added = 0
for path in sorted((ROOT / "work").glob("tr_*.py")):
    for key, text in load(path).items():
        if key not in cat.lines:
            print(f"  no such line: {key}"); continue
        pack.entries[key] = Entry(key=key, src=fingerprint(cat.lines[key].text), t=text)
        added += 1
parts = defaultdict(list)
for key, entry in pack.entries.items():
    line = cat.lines.get(key)
    part = "menus" if line is None or line.kind == "loose" else f"script/script_{line.script:04d}"
    parts[part].append(entry)
for part, entries in parts.items():
    pack.save_part(part, entries)
print(f"{added} lines applied, {len(pack)} in the pack")
