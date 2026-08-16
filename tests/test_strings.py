"""Tests for navi/strings.py: pointer index, fixed tables, and the scanner."""

from navi.strings import (
    LanguageModel,
    LooseString,
    mark_fixed_tables,
    pointer_index,
    scan,
)
from navi.table import load_japanese


def test_pointer_index_maps_targets_to_sites(make_rom):
    rom = make_rom(0x1000)
    rom.write_ptr(0x200, 0x800)
    rom.write_ptr(0x204, 0x800)   # two sites, one target
    rom.write_ptr(0x300, 0x900)
    rom.write_u32(0x400, 0x12345678)   # not a cartridge address

    index = pointer_index(rom)
    assert set(index) == {0x800, 0x900}
    assert index[0x800] == [0x200, 0x204]
    assert index[0x900] == [0x300]


def _ls(offset: int, length: int) -> LooseString:
    return LooseString(offset=offset, text="x", length=length)


def test_mark_fixed_tables_flags_equal_adjacent_runs():
    found = [
        _ls(0x100, 8),   # three equal, back to back: a fixed-stride table
        _ls(0x108, 8),
        _ls(0x110, 8),
        _ls(0x120, 8),   # same length but a gap before it: not part of the run
        _ls(0x128, 5),   # different length
    ]
    mark_fixed_tables(found)
    assert [entry.fixed for entry in found] == [True, True, True, False, False]


def test_mark_fixed_tables_leaves_short_runs_alone():
    found = [_ls(0x000, 4), _ls(0x004, 4)]   # adjacent and equal, but only two
    mark_fixed_tables(found)
    assert [entry.fixed for entry in found] == [False, False]


def test_scan_finds_pointed_at_block(make_rom):
    rom = make_rom(0x3000)
    record = bytes([1, 2, 3, 4, 5, 6, 0xF3])   # "アイウエオカ<END>"
    block = 0x800
    for i in range(4):
        rom.write(block + i * len(record), record)
    rom.write_ptr(0x200, block)
    rom.write_ptr(0x204, 0x900)   # a pointer at plain zeroes: not text

    charset = load_japanese()
    # The model learns from the block itself, so the score must pass.
    model = LanguageModel([rom.read(block, 4 * len(record))])

    found = scan(rom, charset, model=model)
    by_offset = {entry.offset: entry for entry in found}
    assert set(by_offset) == {0x800, 0x807, 0x80E, 0x815}

    first = by_offset[0x800]
    assert first.text == "アイウエオカ<END>"
    assert first.length == 7
    assert first.pointers == [0x200]
    assert first.key == "str:000800"

    # Four equal records back to back: the scanner must flag them as fixed.
    assert all(entry.fixed for entry in found)
