"""Tests for the kanji glyph banks: the code -> cell lookup, and repainting.

A bank is a run of 8x16 glyph cells plus a 1024-entry table where entry
``code - 0xE001`` is a cell's top tile and the entry 32 further on its bottom
tile (navi/gfx.py, "kanji glyph banks"). These tests build a tiny bank by hand,
so none of them need the game.
"""

from __future__ import annotations

import pytest

from navi import gfx
from navi.rom import KUWAGATA, Rom

CODE_A = 0xE006          # index 5 in the table
CODE_B = 0xE007          # index 6, the cell to its right on screen
TILES = 0x001000         # where the hand-built bank sits in the image
LUT = TILES + 8 * gfx.TILE_BYTES
ENTRIES = 128            # a short table: the codes under test are indexes 5, 6


class FakeSetter:
    """A Typesetter that paints solid bars, so geometry is what is measured."""

    def __init__(self, width: int = 6):
        self.glyph_width = width
        self.outlined: list[tuple[int, int]] = []

    def measure(self, text: str, spacing: int = 1) -> int:
        return max(0, len(text) * (self.glyph_width + spacing) - spacing)

    def draw(self, canvas, x, y, text, fill, outline=None, spacing=1):
        pen = x
        for _ in text:
            for gy in range(8):
                for gx in range(self.glyph_width):
                    canvas.set(pen + gx, y + gy, fill)
            pen += self.glyph_width + spacing
        return pen - spacing

    def outline_pass(self, canvas, fill, outline):
        self.outlined.append((fill, outline))


def make_bank(tile_count: int = 8, entries: int = ENTRIES):
    """Tiles 0..n, a blank tile 2, and a table pointing two codes at cells."""
    tiles = bytearray()
    for index in range(tile_count):
        tiles += bytes([index]) * gfx.TILE_BYTES     # each tile is its own index
    tiles[2 * gfx.TILE_BYTES:3 * gfx.TILE_BYTES] = bytes(gfx.TILE_BYTES)  # blank
    lut = [2] * entries
    lut[CODE_A - gfx.BANK_FIRST_CODE] = 4
    lut[CODE_A - gfx.BANK_FIRST_CODE + gfx.BANK_LUT_WIDTH] = 5
    lut[CODE_B - gfx.BANK_FIRST_CODE] = 6
    lut[CODE_B - gfx.BANK_FIRST_CODE + gfx.BANK_LUT_WIDTH] = 7
    return tiles, lut


def raw_spec(**extra) -> dict:
    spec = {
        "name": "test-bank",
        "codec": "raw",
        "tiles": hex(TILES),
        "lut": hex(LUT),
        "tile_count": 8,
        "lut_entries": ENTRIES,
    }
    spec.update(extra)
    return spec


def test_bank_cell_reads_the_pair_the_code_points_at():
    _, lut = make_bank()
    assert gfx.bank_cell(lut, CODE_A) == (4, 5)
    assert gfx.bank_cell(lut, CODE_B) == (6, 7)


def test_bank_cell_refuses_a_code_outside_the_table():
    _, lut = make_bank()
    with pytest.raises(gfx.GfxError):
        gfx.bank_cell(lut, 0xE001 + ENTRIES)


def test_lut_round_trips_through_bytes():
    _, lut = make_bank()
    assert gfx.bank_lut(gfx.bank_lut_bytes(lut)) == lut


def test_a_word_paints_only_the_cells_of_its_codes():
    tiles, lut = make_bank()
    report = gfx.GfxReport()
    word = {"key": "w", "codes": ["E006", "E007"], "lines": ["AB", "CD"], "fill": 15}
    moved = gfx.apply_bank_words(tiles, lut, {"words": [word]}, FakeSetter(), report)

    assert (report.drawn, report.skipped, moved) == (1, [], False)
    for tile in (4, 5, 6, 7):
        painted = tiles[tile * gfx.TILE_BYTES:(tile + 1) * gfx.TILE_BYTES]
        assert set(painted) <= {0x00, 0x0F, 0xF0, 0xFF}, f"tile {tile} kept old ink"
        assert 0xFF in painted, f"tile {tile} should carry the new letters"
    for tile in (0, 1, 3):
        untouched = tiles[tile * gfx.TILE_BYTES:(tile + 1) * gfx.TILE_BYTES]
        assert set(untouched) == {tile}, f"tile {tile} must not be touched"


def test_the_two_lines_land_one_above_the_other():
    """Line 1 fills the top tiles, line 2 the bottom ones — 8 rows each."""
    tiles, lut = make_bank()
    report = gfx.GfxReport()
    word = {"key": "w", "codes": ["E006"], "lines": ["A", "B"], "fill": 15}
    gfx.apply_bank_words(tiles, lut, {"words": [word]}, FakeSetter(width=8), report)

    top = tiles[4 * gfx.TILE_BYTES:5 * gfx.TILE_BYTES]
    bottom = tiles[5 * gfx.TILE_BYTES:6 * gfx.TILE_BYTES]
    assert set(top) == {0xFF} and set(bottom) == {0xFF}


def test_a_word_wider_than_its_kanji_is_refused_not_clipped():
    tiles, lut = make_bank()
    before = bytes(tiles)
    report = gfx.GfxReport()
    word = {"key": "too.wide", "codes": ["E006"], "lines": ["ABC"], "fill": 15}
    gfx.apply_bank_words(tiles, lut, {"words": [word]}, FakeSetter(), report)

    assert report.drawn == 0
    assert bytes(tiles) == before
    assert report.skipped and "8px" in report.skipped[0][1]


def test_new_cells_grows_the_bank_and_repoints_the_table():
    tiles, lut = make_bank()
    report = gfx.GfxReport()
    word = {"key": "w", "codes": ["E006", "E007"], "lines": ["AB"], "fill": 15,
            "new_cells": True}
    moved = gfx.apply_bank_words(tiles, lut, {"words": [word]}, FakeSetter(), report)

    assert moved is True
    assert len(tiles) == 12 * gfx.TILE_BYTES          # four fresh tiles
    assert gfx.bank_cell(lut, CODE_A) == (8, 9)
    assert gfx.bank_cell(lut, CODE_B) == (10, 11)
    # the cells the codes used to name keep the original glyphs
    for tile in (4, 5, 6, 7):
        assert set(tiles[tile * gfx.TILE_BYTES:(tile + 1) * gfx.TILE_BYTES]) == {tile}


def test_a_raw_bank_refuses_to_grow():
    """Its table sits right after the last tile: there is nowhere to grow into."""
    tiles, lut = make_bank()
    before = bytes(tiles)
    report = gfx.GfxReport()
    word = {"key": "w", "codes": ["E006"], "lines": ["A"], "new_cells": True}
    spec = raw_spec(words=[word])
    moved = gfx.apply_bank_words(tiles, lut, spec, FakeSetter(), report)

    assert (moved, report.drawn) == (False, 0)
    assert bytes(tiles) == before
    assert report.skipped and "raw" in report.skipped[0][1]


def test_patch_writes_a_raw_bank_back_where_it_was(monkeypatch):
    data = bytearray(0x8000)
    data[0xA0:0xAC] = KUWAGATA.title.encode("ascii")
    tiles, lut = make_bank()
    data[TILES:TILES + len(tiles)] = tiles
    data[LUT:LUT + 2 * ENTRIES] = gfx.bank_lut_bytes(lut)
    rom = Rom(data)

    spec = raw_spec(words=[{"key": "w", "codes": ["E006", "E007"],
                            "lines": ["AB", "CD"], "fill": 15}])
    monkeypatch.setattr(gfx, "Typesetter", lambda *a, **k: FakeSetter())
    report = gfx.patch_glyph_banks(rom, None, [spec], allocator=None,
                                   pointer_sites={})

    assert (report.drawn, report.relocated, report.in_place) == (1, 0, 1)
    assert len(rom.data) == 0x8000                      # nothing moved or grew
    for tile in (4, 5, 6, 7):
        at = TILES + tile * gfx.TILE_BYTES
        assert 0xFF in rom.data[at:at + gfx.TILE_BYTES]
        assert set(rom.data[at:at + gfx.TILE_BYTES]) <= {0x00, 0x0F, 0xF0, 0xFF}
    untouched = TILES + 3 * gfx.TILE_BYTES
    assert set(rom.data[untouched:untouched + gfx.TILE_BYTES]) == {3}
    assert rom.data[LUT:LUT + 2 * ENTRIES] == gfx.bank_lut_bytes(lut)   # unchanged
