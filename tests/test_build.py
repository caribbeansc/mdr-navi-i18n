"""Tests for navi/build.py, end to end on the synthetic image."""

import navi.catalog as catalog_mod
from navi.build import RESERVED_TAIL, Allocator, build
from navi.lang import Entry, Pack, fingerprint
from navi.rom import data_end
from navi.table import decode, encode, load_japanese, load_latin

KEY_A1 = "script:0000:0019"   # script A, string at 25, 8 bytes of room


def _pack(*entries: tuple[str, str, str]) -> Pack:
    pack = Pack(code="es")
    for key, source, translation in entries:
        pack.entries[key] = Entry(key=key, src=fingerprint(source), t=translation)
    return pack


def test_fitting_translation_overwrites_in_place(synth):
    rom = synth.rom
    catalog = catalog_mod.build(rom, loose=False)
    latin = load_latin()
    pack = _pack((KEY_A1, catalog.lines[KEY_A1].text, "HOLA<END>"))
    table_before = [rom.ptr(synth.table + 4 * i) for i in range(3)]

    report = build(rom, catalog, pack, latin)

    assert report.written == 1
    assert report.scripts_moved == 0
    assert report.skipped == []
    # The script was not relocated: the master table is exactly as it was.
    assert [rom.ptr(synth.table + 4 * i) for i in range(3)] == table_before

    payload = encode("HOLA<END>", latin)
    room = synth.a_sites[25][1]
    assert rom.read(synth.script_a + 25, room) == payload + bytes(room - len(payload))
    text, _ = decode(rom.data, synth.script_a + 25, latin)
    assert text == "HOLA<END>"
    # The untranslated neighbour is untouched.
    text, _ = decode(rom.data, synth.script_a + 33, load_japanese())
    assert text == "サシス<END>"


def test_growing_translation_relocates_whole_script(synth):
    rom = synth.rom
    catalog = catalog_mod.build(rom, loose=False)
    latin = load_latin()
    japanese = load_japanese()
    spanish = "ESTE MENSAJE ES MUY LARGO<END>"
    assert len(encode(spanish, latin)) > synth.a_sites[25][1]
    pack = _pack((KEY_A1, catalog.lines[KEY_A1].text, spanish))

    report = build(rom, catalog, pack, latin)

    assert report.written == 1
    assert report.scripts_moved == 1
    assert report.skipped == []

    moved = rom.ptr(synth.table)
    assert moved >= synth.data_end            # relocated into the free tail
    assert rom.ptr(synth.table + 8) == moved  # the duplicate slot follows
    assert rom.ptr(synth.table + 4) == synth.script_b   # script B stays put

    # The 16-bit in-script pointer now reaches the payload appended at the end.
    pointer_at = synth.a_sites[25][0]
    new_at = rom.u16(moved + pointer_at)
    assert new_at == synth.script_a_len
    text, _ = decode(rom.data, moved + new_at, latin)
    assert text == spanish

    # The script moved whole: the Japanese is still inside the copy, the other
    # site still points at it, and the original script was never touched.
    text, _ = decode(rom.data, moved + 25, japanese)
    assert text == "アイウエオカキ<END>"
    assert rom.u16(moved + synth.a_sites[33][0]) == 33
    text, _ = decode(rom.data, synth.script_a + 25, japanese)
    assert text == "アイウエオカキ<END>"


def _add_loose(rom, catalog, offset: int, fixed: bool):
    rom.write(offset, bytes([1, 2, 3, 4, 5, 0]))   # "アイウエオ" + terminator
    text, end = decode(rom.data, offset, load_japanese())
    key = catalog_mod.loose_key(offset)
    catalog.lines[key] = catalog_mod.Line(
        key=key, text=text, kind="loose", offset=offset,
        length=end - offset, fixed=fixed,
    )
    return key, text


def test_fixed_record_longer_than_capacity_is_skipped(synth):
    rom = synth.rom
    catalog = catalog_mod.build(rom, loose=False)
    key, source = _add_loose(rom, catalog, 0x500000, fixed=True)
    pack = _pack((key, source, "DEMASIADO LARGO"))   # 15 bytes into 6

    report = build(rom, catalog, pack, load_latin())

    assert report.written == 0
    assert report.strings_inline == 0 and report.strings_moved == 0
    assert len(report.skipped) == 1
    skipped_key, reason = report.skipped[0]
    assert skipped_key == key
    assert "fixed-stride" in reason
    # The record was left exactly as it was.
    assert rom.read(0x500000, 6) == bytes([1, 2, 3, 4, 5, 0])


def test_fixed_record_that_fits_is_rewritten_in_place(synth):
    rom = synth.rom
    catalog = catalog_mod.build(rom, loose=False)
    key, source = _add_loose(rom, catalog, 0x500000, fixed=True)
    latin = load_latin()
    pack = _pack((key, source, "HOLA"))   # 4 bytes into 6

    report = build(rom, catalog, pack, latin)

    assert report.written == 1
    assert report.strings_inline == 1
    assert report.skipped == []
    payload = encode("HOLA", latin)
    assert rom.read(0x500000, 6) == payload + bytes(6 - len(payload))


def test_allocator_only_allocates_past_data_end(synth):
    rom = synth.rom
    end = data_end(rom)
    assert end == synth.data_end

    allocator = Allocator(rom)
    first = allocator.take(0x40)
    # Free space leaves at least a byte of clearance after data_end, so the
    # stripped 0x00 terminator of the last real string survives.
    assert first == ((end + 4) & ~3)
    assert first > end
    second = allocator.take(0x20)
    assert second == first + 0x40
    assert second >= end

    # Exhaust the tail exactly: everything up to the reserved last block.
    tail = len(rom) - first - RESERVED_TAIL
    third = allocator.take(tail - 0x60)
    assert third == second + 0x20

    # The next byte cannot dip below data_end or into the reserve: the ROM
    # grows instead, and the allocation lands past the old end of the image.
    old_size = len(rom)
    grown = allocator.take(0x10)
    assert grown >= old_size
    assert allocator.expanded
    assert len(rom) > old_size
