#!/usr/bin/env python3
"""What Japanese is still standing in a built ROM, without playing it.

  python3 tools/leftovers.py build/medarot-navi-kuwagata-es.gba
  python3 tools/leftovers.py build/…-es.gba --all      # backlog included
  python3 tools/leftovers.py build/…-es.gba --update   # accept what is left

Only runs missing from langs/es/leftovers.json are listed, so a new one
stands out from the known backlog; `navi.py build` prints the same count.
The ones drawn through the re-purposed kana codes come out as GARBAGE on
screen ("H¿ガP"), not as Japanese, so they are listed first.

The Japanese itself is only printed, never written to a file — it must not
enter the repository.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from navi import leftovers as L                          # noqa: E402
from navi.rom import Rom                                 # noqa: E402
from navi.table import Charset, decode, load_japanese    # noqa: E402

BASELINE = ROOT / "langs/es/leftovers.json"


def scan(built_at: Path):
    dump = next((p for p in ROOT.glob("*.gba")), None)
    if dump is None:
        raise SystemExit("no local dump to compare against")
    original = Rom.load(dump)
    japanese = load_japanese()
    latin = Charset.load(ROOT / "data/charset-latin.tbl")
    from navi.catalog import build as build_catalog
    from navi.lang import Pack

    catalog = build_catalog(original, japanese)
    pack = Pack.load("es")
    skip = (L.script_area(original)
            + L.translated_area(original, catalog, pack)
            + list(L.DATA_AREAS))
    return original, japanese, L.find(original, Rom.load(built_at),
                                      japanese, latin, skip=skip)


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    if not args:
        print(__doc__)
        return 2
    original, japanese, found = scan(Path(args[0]))
    if "--update" in flags:
        # Only the neighbourhood-only class is silenced. Those are almost all
        # stat tables sitting next to translated names, and there are ~2000 of
        # them; the prose findings are a worklist and stay in the report until
        # they are translated.
        quiet = [f for f in found if f.why == "vecindad"]
        L.save_baseline(BASELINE, quiet)
        print(f"registradas {len(quiet)} de {len(found)} "
              "(solo la clase «vecindad»; las de prosa siguen a la vista)")
        return 0

    known = L.load_baseline(BASELINE)
    show = found if "--all" in flags else [f for f in found if f.key not in known]
    source = bytes(original.data)
    garbage = sum(1 for f in show if f.garbage)
    scope = "" if "--all" in flags else f" sin registrar (de {len(found)})"
    print(f"{len(show)} cadenas japonesas en pie{scope}"
          f" — {garbage} se dibujarían como galimatías")
    # Findings that sit at a constant stride are one TABLE, not N strings,
    # and that is the actionable framing: the cast names looked like three
    # unrelated leftovers until the stride showed 86 records behind them.
    offsets = sorted(f.offset for f in show)
    grupos = []
    for stride in (0x08, 0x0A, 0x0C, 0x10, 0x14, 0x18, 0x1C, 0x20, 0x28, 0x30):
        tomados = {o for g in grupos for o in g[2]}
        for start in offsets:
            if start in tomados:
                continue
            run = []
            at = start
            while at in set(offsets) - tomados:
                run.append(at)
                at += stride
            if len(run) >= 3:
                grupos.append((start, stride, run))
                tomados.update(run)
    if grupos:
        print("  posibles TABLAS (mismo paso, mirar la tabla entera, no la cadena):")
        for start, stride, run in sorted(grupos, key=lambda g: -len(g[2]))[:8]:
            print(f"    {start:06X} paso {stride:#04x} x{len(run)}")
    for item in show[:60]:
        text, _ = decode(source, item.offset, japanese, limit=item.length)
        mark = "GALIMATÍAS" if item.garbage else "japonés   "
        print(f"  {mark} {item.offset:06X} {item.chars:3d} car "
              f"[{item.why:14}] {text!r}")
    if len(show) > 60:
        print(f"  … y {len(show) - 60} más")
    return 1 if show else 0


if __name__ == "__main__":
    raise SystemExit(main())
