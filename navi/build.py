"""Turning a language pack and a dump into a playable cartridge.

Three things change, and nothing else does.

**The font.** New glyphs go into the codes the hiragana used; see navi/font.py.

**Event scripts.** A translated line is almost always longer than the Japanese
it replaces, and the pointer that reaches it is only 16 bits wide, counted from
the start of its own script. So a script that gains text is copied whole into
free space, the translations are appended, and the 16-bit pointers are repointed
inside the copy. The master table then sends the game to the copy instead.

Copying the script *whole* is what makes this safe: any line the walker failed
to find keeps pointing at the Japanese that is still sitting there, so an
incomplete parse costs a missed translation, never a crash.

**Loose strings.** Menus and labels are reached by ordinary 32-bit pointers.
A translation that fits goes in place; a longer one goes to free space and the
pointers follow it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import font
from .catalog import Catalog, Line
from .lang import Pack
from .rom import BASE, Rom, find_free_space
from .script import Script
from .table import Charset, TableError, encode

#: A 16-bit pointer counted from the start of the script caps how big one can get.
MAX_SCRIPT_SIZE = 0x10000

#: Leave the last block alone: some flash carts and emulators keep save data there.
RESERVED_TAIL = 0x200


@dataclass
class Report:
    """What the build did, in enough detail to argue with."""

    language: str = ""
    written: int = 0
    skipped: list[tuple[str, str]] = field(default_factory=list)
    scripts_moved: int = 0
    strings_inline: int = 0
    strings_moved: int = 0
    glyphs_added: int = 0
    gfx_drawn: int = 0
    gfx_relocated: int = 0
    bytes_used: int = 0
    rom_size: int = 0
    expanded: bool = False

    def summary(self) -> str:
        lines = [
            f"{self.written} lines written",
            f"{self.scripts_moved} scripts relocated",
            f"{self.strings_inline + self.strings_moved} loose strings "
            f"({self.strings_inline} in place, {self.strings_moved} moved)",
            f"{self.glyphs_added} glyphs added to the font",
            f"{self.gfx_drawn} graphic labels redrawn"
            + (f" ({self.gfx_relocated} blocks relocated)" if self.gfx_relocated else ""),
            f"{self.bytes_used} bytes of free space used",
        ]
        if self.skipped:
            lines.append(f"{len(self.skipped)} lines skipped")
        if self.expanded:
            lines.append(f"ROM expanded to {self.rom_size // (1024 * 1024)} MB")
        return "\n".join(lines)


class Allocator:
    """Hands out unused stretches of the ROM, growing it only if it must."""

    def __init__(self, rom: Rom, reserve: int = RESERVED_TAIL):
        self.rom = rom
        self._runs = [
            (offset, max(0, length - reserve))
            for offset, length in find_free_space(rom, minimum=0x40)
        ]
        self._runs.sort()
        self._reserve = reserve
        self.used = 0
        self.expanded = False

    def take(self, size: int, align: int = 4) -> int:
        for i, (offset, length) in enumerate(self._runs):
            start = (offset + align - 1) & ~(align - 1)
            waste = start - offset
            if length - waste >= size:
                self._runs[i] = (start + size, length - waste - size)
                self.used += size
                return start
        return self._grow(size, align)

    def _grow(self, size: int, align: int) -> int:
        rom = self.rom
        old = len(rom)
        target = old * 2 if old * 2 >= old + size else old + size
        # Cartridge sizes are powers of two; 32 MB is the largest the bus maps.
        limit = 32 * 1024 * 1024
        if target > limit:
            raise MemoryError("Out of ROM space: the translation does not fit in 32 MB")
        rom.expand(target)
        self.expanded = True
        start = (old + align - 1) & ~(align - 1)
        # The reserve holds in the grown ROM too: the last block stays free.
        available = target - self._reserve - start - size
        if available < 0:
            raise MemoryError("Out of ROM space even after expanding")
        self._runs.append((start + size, available))
        self._runs.sort()
        self.used += size
        return start


def _encode_or_skip(text: str, charset: Charset, key: str, report: Report) -> bytes | None:
    """Encode a line **sealed with its terminator**.

    The engine reads a string until a 0x00 or an <END> byte; nothing else stops
    it — not even the end of the text we wrote. A payload without a terminator
    therefore runs straight into whatever bytes follow it, and on screen that
    splices every relocated line into one endless string. Decoding strips the
    original's terminator silently, so it has to be put back here, always.
    """
    try:
        payload = encode(text, charset)
    except TableError as exc:
        report.skipped.append((key, str(exc)))
        return None
    if not text.endswith("<END>"):
        payload += b"\x00"
    return payload


def _rebuild_script(script: Script, translations: dict[int, tuple[bytes, int]]
                    ) -> tuple[bytes, bool] | None:
    """The script with its translations in, and whether it has to move.

    A line that is no longer than the Japanese it replaces is written straight
    over it, which costs nothing and leaves the script where it is. Only the
    lines that outgrow their slot are appended, and only a script with at least
    one of those has to be relocated at all.
    """
    out = bytearray(script.data)
    appended: dict[int, int] = {}
    for relative in sorted(translations):
        payload, room = translations[relative]
        if len(payload) <= room:
            out[relative:relative + len(payload)] = payload
            # Blank the tail of the old line so nothing of it is left to draw.
            out[relative + len(payload):relative + room] = bytes(room - len(payload))
        else:
            appended[relative] = len(out)
            out.extend(payload)
    if len(out) > MAX_SCRIPT_SIZE:
        return None
    for site in script.sites:
        new_at = appended.get(site.text_at)
        if new_at is None:
            continue
        out[site.pointer_at] = new_at & 0xFF
        out[site.pointer_at + 1] = (new_at >> 8) & 0xFF
    return bytes(out), bool(appended)


def _write_default_names(rom: Rom, pack: Pack, charset: Charset, report: Report) -> None:
    """Latinise the default names (player, medal, cast) at their fixed sites.

    Each is a fixed-width field the name UI edits in place, so a name is
    encoded with the live charset, padded to the field width with the byte the
    UI itself pads with, and written where the Japanese one sat. Keeping the
    texts in the language pack (gfx.json "names") means a future charset
    remap re-encodes them for free.
    """
    import json

    path = pack.path / "gfx.json" if pack.path else None
    if path is None or not path.is_file():
        return
    section = json.loads(path.read_text(encoding="utf-8")).get("names", {})
    for entry in section.get("entries", []):
        text = entry["text"]
        field_width = int(entry.get("field", 8))
        pad = int(str(entry.get("pad", "0xDB")), 16)
        try:
            payload = encode(text, charset)
        except TableError as exc:
            report.skipped.append((f"name:{text}", str(exc)))
            continue
        if len(payload) > field_width:
            report.skipped.append(
                (f"name:{text}", f"{len(payload)} bytes into an {field_width}-byte field"))
            continue
        payload += bytes([pad]) * (field_width - len(payload))
        for site in entry["at"]:
            rom.write(int(str(site), 16), payload)
        report.written += 1


#: The robattle team-info table: 147 records of 0xC0 bytes, each carrying six
#: 8-byte 0xDB-padded name fields at +0x10 (team, leader, and the medarots).
#: These render through the character fonts, so kana left here turns to Latin
#: soup once the fonts are patched — they must be romanised together.
TEAM_TABLE = 0x86640
TEAM_COUNT = 147
TEAM_RECORD = 0xC0
TEAM_NAME_FIELDS = 6


def _write_team_names(rom: Rom, pack: Pack, charset: Charset, report: Report) -> None:
    """Romanise the battle team/leader/medarot names.

    The pack stores translations keyed by a fingerprint of the Japanese
    (gfx.json "team_names"), so the repository never carries the kana itself.
    Fields whose fingerprint has no entry are left alone and reported.
    """
    import json

    from .lang import fingerprint
    from .table import load_japanese

    path = pack.path / "gfx.json" if pack.path else None
    if path is None or not path.is_file():
        return
    table = json.loads(path.read_text(encoding="utf-8")).get("team_names", {})
    if not table:
        return
    japanese = load_japanese()
    missing: set[str] = set()
    for index in range(TEAM_COUNT):
        record = TEAM_TABLE + index * TEAM_RECORD
        for fld in range(TEAM_NAME_FIELDS):
            at = record + 0x10 + 8 * fld
            raw = rom.read(at, 8)
            kana = "".join(japanese.decode.get(b, "?")
                           for b in raw if b and b != 0xDB)
            if not kana:
                continue
            latin = table.get(fingerprint(kana))
            if latin is None:
                missing.add(kana)
                continue
            try:
                payload = encode(latin, charset)
            except TableError as exc:
                report.skipped.append((f"team:{latin}", str(exc)))
                continue
            if len(payload) > 8:
                report.skipped.append(
                    (f"team:{latin}", f"{len(payload)} bytes into an 8-byte field"))
                continue
            rom.write(at, payload + bytes([0xDB]) * (8 - len(payload)))
    if missing:
        report.skipped.append(
            ("team-names", f"{len(missing)} names have no entry yet"))


#: The battle system's announcement messages ("N damage to X!", symptom
#: effects...) live behind their own pointer table and end in the engine's
#: 0xF0 insert/stop byte instead of a normal terminator, which is why the
#: loose-string scanner never saw them. <NL>x pairs inside them are VALUE
#: INSERTS (F1 + slot code), not line breaks — translations keep them intact.
#: The pointer table really starts at 0x4C8660 — the first 0x36 entries were
#: found later (attack announcements, trap and can't-act messages). Before
#: 0x4C8660 the data is Shift-JIS text, not pointers.
BATTLE_MSG_TABLE = (0x4C8660, 0x4C8964)


def _write_battle_messages(rom: Rom, pack: Pack, charset: Charset,
                           allocator, report: Report) -> None:
    import json
    import struct

    from .lang import fingerprint
    from .table import decode, load_japanese

    path = pack.path / "gfx.json" if pack.path else None
    if path is None or not path.is_file():
        return
    table = json.loads(path.read_text(encoding="utf-8")).get("battle_messages", {})
    if not table:
        return
    japanese = load_japanese()
    relocated: dict[str, int] = {}
    missing: set[str] = set()
    handled: set[int] = set()
    start, end = BATTLE_MSG_TABLE
    # Some messages are NESTED: a short message is the tail of a longer one
    # (0x4C97B0 sits inside 0x4C97A0's bytes). An in-place write may never
    # cross another live target, or its zero padding wipes the inner message.
    targets = sorted({rom.ptr(site) for site in range(start, end, 4)
                      if rom.ptr(site) >= 0})
    for site in range(start, end, 4):
        target = rom.ptr(site)
        if target < 0 or target in handled:
            continue
        handled.add(target)
        source, source_end = decode(bytes(rom.data), target, japanese, limit=120)
        for other in targets:
            if target < other < source_end:
                source_end = other
                break
        key = fingerprint(source)
        latin = table.get(key)
        if latin is None:
            if source:
                missing.add(key)
            continue
        # The kana after each <NL> is the insert SLOT byte, spelled as the
        # kana it decodes to; turn it back into the raw byte so the Latin
        # charset never has to know it.
        import re as _re

        def _slot(match: "\\re.Match[str]") -> str:
            code = japanese.encode.get(match.group(1))
            return f"<NL><B:{code:02X}>" if code is not None else match.group(0)

        latin = _re.sub(r"<NL>(.)", _slot, latin)
        try:
            payload = encode(latin, charset)
        except TableError as exc:
            report.skipped.append((f"battlemsg:{key}", str(exc)))
            continue
        if not latin.endswith(("<X:F0>", "<END>")):
            payload += b"\x00"
        room = source_end - target
        if len(payload) <= room:
            rom.write(target, payload + bytes(room - len(payload)))
        else:
            destination = relocated.get(key)
            if destination is None:
                destination = allocator.take(len(payload), align=1)
                rom.write(destination, payload)
                relocated[key] = destination
            rom.write_ptr(site, destination)
        report.written += 1
    if missing:
        report.skipped.append(
            ("battle-messages", f"{len(missing)} messages have no entry yet"))


def _write_extra_strings(rom: Rom, pack: Pack, charset: Charset, report: Report) -> None:
    """Index-reached system strings (action names, Medaforce lines...).

    Stored in gfx.json "extra_strings" as ``src-fingerprint -> {t, sites,
    room}``: the string at each site is fingerprint-checked against the dump,
    then overwritten in place — these are reached by index, so they can never
    move and the translation must fit its room.
    """
    import json

    from .lang import fingerprint
    from .table import decode, load_japanese

    path = pack.path / "gfx.json" if pack.path else None
    if path is None or not path.is_file():
        return
    table = json.loads(path.read_text(encoding="utf-8")).get("extra_strings", {})
    if not table:
        return
    japanese = load_japanese()
    for src, entry in table.items():
        text = entry.get("t", "")
        if not text:
            continue
        room = int(entry["room"])
        try:
            payload = encode(text, charset)
        except TableError as exc:
            report.skipped.append((f"extra:{src}", str(exc)))
            continue
        if not text.endswith("<END>"):
            payload += b"\x00"
        if len(payload) > room:
            report.skipped.append(
                (f"extra:{src}", f"{len(payload)} bytes into a {room}-byte slot"))
            continue
        for site in entry["sites"]:
            at = int(str(site), 16)
            source, _ = decode(bytes(rom.data), at, japanese, limit=64)
            if fingerprint(source) != src:
                continue  # dump differs here; leave it alone
            rom.write(at, payload + bytes(room - len(payload)))
        report.written += 1


def _write_sjis_strings(rom: Rom, pack: Pack, report: Report) -> None:
    """Battle-bar literals stored as Shift-JIS and transcoded at runtime.

    The bar engine keeps a handful of strings (turn counter, AP charge,
    the robottle jingle...) as Shift-JIS around 0x4BA7AC-0x4BC1D8 and
    converts them to the game charset while composing. FULLWIDTH Latin
    survives that conversion — halfwidth ASCII does not (it truncates to
    garbage) — so translations here must use fullwidth letters. Stored in
    gfx.json "sjis_strings" as site -> {jp, t, room}; in-place only.
    """
    import json

    path = pack.path / "gfx.json" if pack.path else None
    if path is None or not path.is_file():
        return
    table = json.loads(path.read_text(encoding="utf-8")).get("sjis_strings", {})
    for site, entry in table.items():
        at = int(str(site), 16)
        original = entry["jp"].encode("shift_jis")
        if bytes(rom.data[at:at + len(original)]) != original:
            report.skipped.append((f"sjis:{site}", "dump differs here; left alone"))
            continue
        payload = entry["t"].encode("shift_jis") + b"\x00"
        room = int(entry["room"])
        if len(payload) > room:
            report.skipped.append(
                (f"sjis:{site}", f"{len(payload)} bytes into a {room}-byte slot"))
            continue
        rom.write(at, payload + bytes(room - len(payload)))
        report.written += 1


def _write_ptr_strings(rom: Rom, pack: Pack, charset: Charset,
                       allocator, report: Report) -> None:
    """Pointer-reached UI labels whose originals cannot be edited in place.

    The battle target panel's slot labels live as OVERLAPPING suffixes of one
    7-kanji run (頭右腕左腕脚部 at 0x4BF45C) behind four pointers at
    0x655410 — writing any of them in place eats its neighbours. Stored in
    gfx.json "ptr_strings" as pointer-site -> {jp, t}: the target is checked
    against ``jp``, the translation goes to free space, the pointer moves.
    """
    import json

    from .table import decode, load_japanese

    path = pack.path / "gfx.json" if pack.path else None
    if path is None or not path.is_file():
        return
    table = json.loads(path.read_text(encoding="utf-8")).get("ptr_strings", {})
    if not table:
        return
    japanese = load_japanese()
    for site, entry in table.items():
        at = int(str(site), 16)
        target = rom.ptr(at)
        source, _ = decode(bytes(rom.data), target, japanese, limit=40)
        if not source.startswith(entry["jp"]):
            report.skipped.append((f"ptr:{site}", "dump differs here; left alone"))
            continue
        try:
            payload = encode(entry["t"], charset) + b"\x00"
        except TableError as exc:
            report.skipped.append((f"ptr:{site}", str(exc)))
            continue
        destination = allocator.take(len(payload), align=1)
        rom.write(destination, payload)
        rom.write_ptr(at, destination)
        report.written += 1


def build(rom: Rom, catalog: Catalog, pack: Pack, charset: Charset) -> Report:
    """Apply a language pack to a ROM, in place. Returns what happened."""
    report = Report(language=pack.code)

    font_data, placed = font.build_font(rom, charset)
    rom.write(rom.release.font, font_data)
    report.glyphs_added = len(placed)

    allocator = Allocator(rom)

    # -- event scripts ---------------------------------------------------
    per_script: dict[int, dict[int, tuple[bytes, int]]] = {}
    for line in catalog.of_kind("script"):
        text = pack.translation_for(line.key, line.text)
        if text is None:
            continue
        payload = _encode_or_skip(text, charset, line.key, report)
        if payload is None:
            continue
        per_script.setdefault(line.script, {})[line.relative] = (payload, line.length)

    table_base = rom.release.script_table
    table = [rom.ptr(table_base + 4 * i) for i in range(rom.release.script_table_len)]

    for index, translations in sorted(per_script.items()):
        script = catalog.scripts[index]
        rebuilt = _rebuild_script(script, translations)
        if rebuilt is None:
            for relative in translations:
                report.skipped.append(
                    (f"script:{index:04d}:{relative:04X}",
                     "script would grow past the 64 KB a 16-bit pointer can reach")
                )
            continue
        payload, must_move = rebuilt
        if must_move:
            destination = allocator.take(len(payload))
            rom.write(destination, payload)
            for slot, target in enumerate(table):
                if target == script.offset:
                    rom.write_ptr(table_base + 4 * slot, destination)
            report.scripts_moved += 1
        else:
            rom.write(script.offset, payload)
        report.written += len(translations)

    # -- loose strings ---------------------------------------------------
    for line in catalog.of_kind("loose"):
        text = pack.translation_for(line.key, line.text)
        if text is None:
            continue
        payload = _encode_or_skip(text, charset, line.key, report)
        if payload is None:
            continue
        if line.fixed and len(payload) > line.length:
            report.skipped.append((
                line.key,
                f"a record in a fixed-stride table: {len(payload)} bytes "
                f"will not fit in {line.length}"))
            continue
        if len(payload) <= line.length:
            # Pad with the terminator the original used, so anything reading
            # past the end behaves as before.
            rom.write(line.offset, payload + bytes(line.length - len(payload)))
            report.strings_inline += 1
        else:
            if not line.pointers:
                report.skipped.append((line.key, "too long, and nothing points at it"))
                continue
            destination = allocator.take(len(payload), align=1)
            rom.write(destination, payload)
            for site in line.pointers:
                rom.write_ptr(site, destination)
            report.strings_moved += 1
        report.written += 1

    # -- graphic menus ---------------------------------------------------
    if pack.path is not None:
        from . import gfx
        from .strings import pointer_index

        texts = gfx.load_texts(pack.path)
        sites = pointer_index(rom)
        if texts:
            gfx_report = gfx.patch(rom, charset, texts, allocator,
                                   sites, font_data=font_data)
            report.gfx_drawn = gfx_report.drawn
            report.gfx_relocated = gfx_report.relocated
            report.skipped.extend(gfx_report.skipped)

        import json as _json
        gfx_path = pack.path / "gfx.json"
        sheets = []
        banks = []
        if gfx_path.is_file():
            gfx_pack = _json.loads(gfx_path.read_text(encoding="utf-8"))
            sheets = gfx_pack.get("sheets", [])
            banks = gfx_pack.get("glyph_banks", [])
        if sheets:
            sheet_report = gfx.patch_sheets(rom, charset, sheets, allocator,
                                            sites, font_data=font_data)
            report.gfx_drawn += sheet_report.drawn
            report.gfx_relocated += sheet_report.relocated
            report.skipped.extend(sheet_report.skipped)

        plate_words = []
        if gfx_path.is_file():
            plate_words = _json.loads(
                gfx_path.read_text(encoding="utf-8")).get("plate_words", [])
        if plate_words:
            plate_report = gfx.GfxReport()
            gfx.patch_part_type_plates(rom, charset, plate_words, allocator,
                                       sites, plate_report, font_data=font_data)
            report.gfx_drawn += plate_report.drawn
            report.gfx_relocated += plate_report.relocated
            report.skipped.extend(plate_report.skipped)
        if banks:
            # Kanji the UI text renderer blits per two-byte code, not a sheet:
            # see "kanji glyph banks" in navi/gfx.py.
            bank_report = gfx.patch_glyph_banks(rom, charset, banks, allocator,
                                                sites, font_data=font_data)
            report.gfx_drawn += bank_report.drawn
            report.gfx_relocated += bank_report.relocated
            report.skipped.extend(bank_report.skipped)

        _write_default_names(rom, pack, charset, report)
        _write_team_names(rom, pack, charset, report)
        _write_battle_messages(rom, pack, charset, allocator, report)
        _write_extra_strings(rom, pack, charset, report)
        _write_sjis_strings(rom, pack, report)
        _write_ptr_strings(rom, pack, charset, allocator, report)

    # -- the name-entry keyboard's font ----------------------------------
    # It is separate from the dialogue font (see navi/font.py). The patched
    # version grows its pattern table, so both tables are relocated and the
    # two code literals that name them are repointed.
    kb_lut, kb_font = font.build_keyboard_font(rom, charset)
    lut_at = allocator.take(len(kb_lut))
    font_at = allocator.take(len(kb_font))
    rom.write(lut_at, kb_lut)
    rom.write(font_at, kb_font)
    font_literal, lut_literal = font.KEYBOARD_LITERALS
    rom.write_ptr(font_literal, font_at)
    rom.write_ptr(lut_literal, lut_at)

    report.bytes_used = allocator.used
    report.rom_size = len(rom)
    report.expanded = allocator.expanded
    return report
