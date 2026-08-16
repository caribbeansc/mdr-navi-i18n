"""The command line, and the menu that stands in front of it."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import extract as extract_mod
from . import font as font_mod
from . import patch as patch_mod
from . import validate as validate_mod
from .build import build as build_rom
from .catalog import build as build_catalog
from .config import ROOT, Config
from .csvio import read_csv, write_csv
from .lang import Entry, Pack, available, fingerprint
from .rom import Rom, RomError, find_free_space
from .table import load_japanese, load_latin

BUILD_DIR = ROOT / "build"
DIST_DIR = ROOT / "dist"


def _rom(config: Config) -> Rom:
    rom = Rom.load(config.resolve_rom())
    if not rom.is_known_dump:
        print(f"  note: this dump's SHA-1 is not the one on record for "
              f"{rom.release.name}; offsets may not line up")
    return rom


def _catalog_and_pack(config: Config, language: str):
    rom = _rom(config)
    catalog = build_catalog(rom)
    pack = Pack.load(language)
    return rom, catalog, pack


# -- commands ------------------------------------------------------------


def cmd_rom(args, config: Config) -> int:
    if args.path:
        path = Path(args.path).expanduser().resolve()
        rom = Rom.load(path)
        config.rom = str(path)
        config.save()
        print(f"Using {path.name}: Medarot Navi {rom.release.name}, "
              f"{len(rom) // (1024 * 1024)} MB, "
              f"{'known dump' if rom.is_known_dump else 'unrecognised dump'}")
    else:
        rom = _rom(config)
        print(f"{Path(rom.path).name}")
        print(f"  release  {rom.release.name} ({rom.release.title})")
        print(f"  sha1     {rom.sha1}")
        print(f"  size     {len(rom) // 1024} KB")
    return 0


def cmd_scan(args, config: Config) -> int:
    rom = _rom(config)
    catalog = build_catalog(rom)
    scripts = [l for l in catalog.lines.values() if l.kind == "script"]
    loose = [l for l in catalog.lines.values() if l.kind == "loose"]
    print(f"Medarot Navi {rom.release.name}")
    print(f"  {len(catalog.scripts)} event scripts holding {len(scripts)} lines")
    print(f"  {len(loose)} loose strings (menus, labels, names)")
    free = find_free_space(rom, minimum=0x1000)
    total = sum(length for _, length in free)
    print(f"  {total // 1024} KB of free space in {len(free)} runs, "
          f"largest {free[0][1] // 1024} KB at {free[0][0]:#08x}" if free else "  no free space")
    return 0


def cmd_extract(args, config: Config) -> int:
    rom = _rom(config)
    catalog = build_catalog(rom)
    pack = Pack.load(args.language) if args.language in available() else None
    out = extract_mod.dump(rom, catalog, pack)
    print(f"{len(catalog)} lines written to {out.relative_to(ROOT)}/")
    if pack:
        print(f"  {len(pack)} of them already translated into {pack.name}")
    return 0


def cmd_validate(args, config: Config) -> int:
    rom, catalog, pack = _catalog_and_pack(config, args.language)
    problems = validate_mod.check(catalog, pack, load_latin())
    for problem in problems[: args.limit or None]:
        print(problem)
    print(validate_mod.summary(problems))
    return 1 if problems else 0


def cmd_build(args, config: Config) -> int:
    rom, catalog, pack = _catalog_and_pack(config, args.language)
    original = bytes(rom.data)

    problems = validate_mod.check(catalog, pack, load_latin())
    blocking = [p for p in problems if p.kind in ("unencodable", "stale", "orphan")]
    if blocking and not args.force:
        for problem in blocking[:20]:
            print(problem)
        print(f"\n{len(blocking)} blocking problems. Fix them, or build --force.")
        return 1

    report = build_rom(rom, catalog, pack, load_latin())
    print(report.summary())
    for key, why in report.skipped[:20]:
        print(f"  skipped {key}: {why}")

    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    out = BUILD_DIR / f"medarot-navi-{rom.release.name.lower()}-{pack.code}.gba"
    rom.save(out)
    print(f"\nROM: {out.relative_to(ROOT)}")

    if not args.no_patch:
        kind, blob = patch_mod.make(original, bytes(rom.data))
        DIST_DIR.mkdir(parents=True, exist_ok=True)
        patch_path = DIST_DIR / f"medarot-navi-{rom.release.name.lower()}-{pack.code}.{kind}"
        patch_path.write_bytes(blob)
        print(f"Patch: {patch_path.relative_to(ROOT)} ({len(blob) // 1024} KB)")

    # A player's save stores the ABSOLUTE address of the scene's script, and
    # this build just moved the scripts, so a save made with the previous one
    # is now pointing at the wrong bytes: the game opens a corrupted name
    # entry when you walk, or every NPC goes mute. Say so loudly here rather
    # than let someone lose an afternoon of play (it happened once).
    save = out.with_suffix(".sav")
    if save.is_file():
        import struct

        stored = struct.unpack_from("<I", save.read_bytes(), 0x3220)[0]
        data = bytes(rom.data)
        table = {struct.unpack_from("<I", data, 0x6299A0 + 4 * i)[0]
                 for i in range(370)}
        if stored not in table:
            print(f"\nWARNING: {save.name} was made with another build "
                  f"({stored:#010x} is not a script here).")
            print("         Regenerate it before handing this ROM to a player "
                  "— see tools/savecheck.py.")
    return 0


def cmd_font(args, config: Config) -> int:
    rom = _rom(config)
    charset = load_latin()
    if args.chars:
        codes = [charset.encode[c] for c in args.chars if c in charset.encode]
    else:
        codes = None
    print(font_mod.preview(rom, charset, codes))
    return 0


def cmd_slots(args, config: Config) -> int:
    from .slots import cost, quietest, render_charset

    rom = _rom(config)
    catalog = build_catalog(rom)
    japanese, current = load_japanese(), load_latin()

    drawn = sorted(font_mod.read_glyphs())
    rotated = sorted(font_mod.ROTATED)
    wanted = [c for c in drawn + rotated]
    codes = quietest(catalog, japanese, len(wanted))
    hit, pct = cost(catalog, japanese, codes)
    print(f"{len(wanted)} glyphs need {len(codes)} codes")
    print(f"  they cost {pct:.2f}% of the cartridge's characters ({hit} of them)")
    print("  " + "  ".join(f"{c:02X}={ch}" for c, ch in list(zip(codes, wanted))[:12]) + " …")

    if not args.write:
        print("\nRun with --write to regenerate data/charset-latin.tbl")
        return 0

    symbol_glyphs = {"△", "▲", "×", "▼", "[<3]", "♀", "♂", "↑", "↓", "→", "←",
                     "·", "±", "[note]", "°"}
    native = [(c, current.decode[c]) for c in sorted(current.decode)
              if 0x9E <= c <= 0xDF and current.decode[c] not in symbol_glyphs]
    symbols = [(c, current.decode[c]) for c in sorted(current.decode)
               if 0x9E <= c <= 0xDF and current.decode[c] in symbol_glyphs]
    note = (f"taking these {len(codes)} costs {pct:.2f}% of the game's characters.")
    path = ROOT / "data" / "charset-latin.tbl"
    path.write_text(render_charset(list(zip(codes, wanted)), native, symbols, note),
                    encoding="utf-8")
    print(f"\nwrote {path.relative_to(ROOT)}")
    return 0


def cmd_csv(args, config: Config) -> int:
    rom, catalog, pack = _catalog_and_pack(config, args.language)
    out = Path(args.out) if args.out else ROOT / "work" / f"{pack.code}.csv"
    n = write_csv(out, catalog, pack, pending_only=args.pending, prefix=args.filter)
    print(f"{n} lines written to {out}")
    return 0


def cmd_import(args, config: Config) -> int:
    rom, catalog, pack = _catalog_and_pack(config, args.language)
    rows = read_csv(Path(args.path))
    sources = catalog.sources()
    updated = 0
    for key, text in rows.items():
        if key not in sources or not text:
            continue
        pack.entries[key] = Entry(key=key, src=fingerprint(sources[key]), t=text)
        updated += 1
    _save_pack(pack, catalog)
    print(f"{updated} lines imported into langs/{pack.code}/")
    return 0


def _save_pack(pack: Pack, catalog) -> None:
    """Write a pack back out, split the same way the catalogue is."""
    parts: dict[str, list[Entry]] = {}
    for key, entry in pack.entries.items():
        if not entry.t:
            continue
        line = catalog.lines.get(key)
        part = "menus" if line is None or line.kind == "loose" else \
            f"script/script_{line.script:04d}"
        parts.setdefault(part, []).append(entry)
    for part, entries in parts.items():
        pack.save_part(part, entries)


def cmd_langs(args, config: Config) -> int:
    for code in available():
        pack = Pack.load(code)
        print(f"  {code:4s} {pack.name:12s} {len(pack)} lines")
    return 0


def cmd_doctor(args, config: Config) -> int:
    ok = True
    print(f"Python {sys.version.split()[0]}")
    try:
        rom = _rom(config)
        print(f"ROM      {Path(rom.path).name} — {rom.release.name}, "
              f"{'known dump' if rom.is_known_dump else 'UNRECOGNISED'}")
    except (RomError, FileNotFoundError) as exc:
        print(f"ROM      {exc}")
        return 1
    try:
        jp, latin = load_japanese(), load_latin()
        print(f"charsets {len(jp.decode)} Japanese codes, {len(latin.decode)} Latin codes")
    except Exception as exc:
        print(f"charsets {exc}")
        ok = False
    try:
        glyphs = font_mod.read_glyphs()
        print(f"glyphs   {len(glyphs)} drawn in data/glyphs-latin.txt")
    except Exception as exc:
        print(f"glyphs   {exc}")
        ok = False
    for code in available():
        print(f"pack     {code}: {len(Pack.load(code))} lines")
    return 0 if ok else 1


# -- menu ----------------------------------------------------------------

MENU = """
  Medarot Navi, in your language

  1  Point me at the game     set the ROM this works on
  2  Look inside              what text the dump holds
  3  Read the game's text     dump everything into work/
  4  Check a translation      widths, tags, missing glyphs
  5  Build a patched ROM
  6  Preview the font
  7  Diagnose

  q  Quit
"""


def menu(config: Config) -> int:
    while True:
        print(MENU)
        choice = input("  > ").strip().lower()
        args = argparse.Namespace(language=config.language, limit=40, out=None,
                                  pending=False, filter=None, force=False,
                                  no_patch=False, chars=None, path=None)
        try:
            if choice == "1":
                args.path = input("  path to your .gba: ").strip().strip("'\"")
                cmd_rom(args, config)
            elif choice == "2":
                cmd_scan(args, config)
            elif choice == "3":
                cmd_extract(args, config)
            elif choice == "4":
                cmd_validate(args, config)
            elif choice == "5":
                cmd_build(args, config)
            elif choice == "6":
                cmd_font(args, config)
            elif choice == "7":
                cmd_doctor(args, config)
            elif choice in ("q", "quit", "exit", ""):
                return 0
            else:
                print("  no such option")
        except (RomError, FileNotFoundError) as exc:
            print(f"  {exc}")
        print()


def main(argv: list[str] | None = None) -> int:
    config = Config.load()
    parser = argparse.ArgumentParser(prog="navi", description=__doc__)
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("rom", help="set or show the ROM to work on")
    p.add_argument("path", nargs="?")
    p.set_defaults(func=cmd_rom)

    p = sub.add_parser("scan", help="what text the dump holds")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("extract", help="dump every line into work/")
    p.add_argument("language", nargs="?", default=config.language)
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser("validate", help="check a translation")
    p.add_argument("language", nargs="?", default=config.language)
    p.add_argument("--limit", type=int, default=40)
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("build", help="write a patched ROM and a patch")
    p.add_argument("language", nargs="?", default=config.language)
    p.add_argument("--force", action="store_true", help="build despite problems")
    p.add_argument("--no-patch", action="store_true")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("font", help="show what the patched font looks like")
    p.add_argument("chars", nargs="?")
    p.set_defaults(func=cmd_font)

    p = sub.add_parser("slots", help="pick which character codes the new glyphs take")
    p.add_argument("--write", action="store_true", help="regenerate the Latin charset")
    p.set_defaults(func=cmd_slots)

    p = sub.add_parser("csv", help="export lines to a spreadsheet")
    p.add_argument("language", nargs="?", default=config.language)
    p.add_argument("--out")
    p.add_argument("--pending", action="store_true", help="only untranslated lines")
    p.add_argument("--filter", help="only keys starting with this")
    p.set_defaults(func=cmd_csv)

    p = sub.add_parser("import", help="read a spreadsheet back in")
    p.add_argument("path")
    p.add_argument("language", nargs="?", default=config.language)
    p.set_defaults(func=cmd_import)

    p = sub.add_parser("langs", help="list language packs")
    p.set_defaults(func=cmd_langs)

    p = sub.add_parser("doctor", help="check the setup")
    p.set_defaults(func=cmd_doctor)

    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        return menu(config)
    try:
        return args.func(args, config)
    except (RomError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
