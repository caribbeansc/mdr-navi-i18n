"""Shared fixtures: a synthetic Kuwagata image, and the real dump when present.

The synthetic image is a bytearray shaped like a Kuwagata cartridge: the header
title, a master script table at the release's offset, and two tiny hand-built
event scripts just below it. It is enough for every ROM-shaped module to walk,
without any test needing the game itself.

The ``game`` marker is registered in pytest.ini, not here.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from navi.rom import KUWAGATA, Rom

REPO_ROOT = Path(__file__).resolve().parent.parent

SYNTH_SIZE = 0x700000
#: A sentinel byte at SYNTH_DATA_END - 1 makes rom.data_end() land exactly here.
SYNTH_DATA_END = 0x680000

SCRIPT_A = 0x629800
SCRIPT_B = SCRIPT_A + 40

TERMINATOR_ROW = b"\xff" * 9


def _u16(value: int) -> bytes:
    return bytes((value & 0xFF, (value >> 8) & 0xFF))


def _subscript_header(entry: int) -> bytes:
    """A 9-byte subscript row: first byte <= 0x80, entry point at bytes 3-4."""
    row = bytearray(9)
    row[3:5] = _u16(entry)
    return bytes(row)


def _script_a() -> bytes:
    """Two text sites in a straight line of code, then the strings."""
    out = bytearray()
    out += _subscript_header(18)          # 0: one subscript, code at 18
    out += TERMINATOR_ROW                 # 9: first byte > 0x80 ends the headers
    out += b"\x01" + _u16(25)             # 18: draw the string at 25
    out += b"\x01" + _u16(33)             # 21: draw the string at 33
    out += b"\x00"                        # 24: end of script
    assert len(out) == 25
    out += bytes([1, 2, 3, 4, 5, 6, 7, 0xF3])   # 25: "アイウエオカキ<END>"
    assert len(out) == 33
    out += bytes([0x0B, 0x0C, 0x0D, 0xF3])      # 33: "サシス<END>"
    assert len(out) == 37
    return bytes(out)


def _script_b() -> bytes:
    """Text sites hidden behind a 0x03 jump and a 0x0A four-way branch."""
    out = bytearray()
    out += _subscript_header(18)          # 0
    out += TERMINATOR_ROW                 # 9
    out += b"\x01" + _u16(49)             # 18: text in the main flow
    out += b"\x03" + _u16(28)             # 21: unconditional jump over the junk
    out += b"\x00" * 4                    # 24: never executed
    out += b"\x01" + _u16(53)             # 28: text behind the jump
    # 31: four-way branch; targets 41, 45, 41 again (deduped), 0 (backwards,
    # ignored). Ten bytes: opcode, one unused byte, four 16-bit targets.
    out += b"\x0a\x00" + _u16(41) + _u16(45) + _u16(41) + _u16(0)
    out += b"\x01" + _u16(58) + b"\x00"   # 41: branch target one
    out += b"\x01" + _u16(61) + b"\x00"   # 45: branch target two
    assert len(out) == 49
    out += bytes([6, 7, 8, 0xF3])                     # 49: "カキク<END>"
    out += bytes([0x10, 0x11, 0x12, 0x13, 0xF3])      # 53: "タチツテ<END>"
    out += bytes([0x15, 0x16, 0xF3])                  # 58: "ナニ<END>"
    out += bytes([0x1A, 0x1B, 0x1C, 0x00])            # 61: "ハヒフ", 0x00-ended
    assert len(out) == 65
    return bytes(out)


@dataclass(frozen=True)
class Synth:
    """The synthetic image plus the layout facts the tests assert against."""

    rom: Rom
    table: int
    #: The master table's entries, duplicates and all, as file offsets.
    table_entries: tuple[int, ...]
    script_a: int
    script_b: int
    #: Bounds length of script A: the gap to script B, padding included.
    script_a_len: int
    #: Bounds length of script B: it runs up to the master table.
    script_b_len: int
    #: Script A: text offset -> (pointer_at, byte length) within the script.
    a_sites: dict[int, tuple[int, int]]
    #: Script B: text offset -> (pointer_at, byte length) within the script.
    b_sites: dict[int, tuple[int, int]]
    data_end: int


def blank_rom(size: int) -> Rom:
    """An all-zero image with just enough header to identify as Kuwagata."""
    data = bytearray(size)
    data[0xA0:0xAC] = KUWAGATA.title.encode("ascii")
    return Rom(data)


def build_synthetic() -> Synth:
    rom = blank_rom(SYNTH_SIZE)
    rom.write(SCRIPT_A, _script_a())
    rom.write(SCRIPT_B, _script_b())

    table = KUWAGATA.script_table
    entries = (SCRIPT_A, SCRIPT_B, SCRIPT_A)   # one duplicate
    for slot, target in enumerate(entries):
        rom.write_ptr(table + 4 * slot, target)

    # The last real byte; everything after it is the free tail.
    rom.write(SYNTH_DATA_END - 1, b"\xab")

    return Synth(
        rom=rom,
        table=table,
        table_entries=entries,
        script_a=SCRIPT_A,
        script_b=SCRIPT_B,
        script_a_len=SCRIPT_B - SCRIPT_A,
        script_b_len=table - SCRIPT_B,
        a_sites={25: (19, 8), 33: (22, 4)},
        b_sites={49: (19, 4), 53: (29, 5), 58: (42, 3), 61: (46, 4)},
        data_end=SYNTH_DATA_END,
    )


@pytest.fixture
def synth() -> Synth:
    return build_synthetic()


@pytest.fixture
def make_rom():
    """A factory for small identifiable images, for the string-scanner tests."""
    return blank_rom


@pytest.fixture(scope="session")
def game_rom() -> Rom:
    dumps = sorted(REPO_ROOT.glob("*.gba"))
    if not dumps:
        pytest.skip("no .gba dump at the repository root")
    return Rom.load(dumps[0])
