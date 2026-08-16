"""The robottle banner's tilemap is straightened, but only when it is safe.

The Japanese map pads the box's corner cells with the sheet's blank tile and
lets the banner's top-row columns 3 and 4 share one tile, which shreds Latin
text. The build rewrites it into ten one-to-one columns padded with the
banner's own outer columns — so those columns have to stay empty, and a word
that reaches them must leave the whole sheet, map included, Japanese.
"""

import pytest

from navi import gfx
from navi.build import Allocator
from navi.font import GLYPH_BYTES
from navi.strings import pointer_index
from navi.table import load_latin

#: Ink in one pixel per glyph makes every letter exactly 1px wide, so a text of
#: N letters measures 2N-1 px and the tests can aim at a column.
POINT_FONT_ROW = 0x7F

SHEET_TILES = 20
POINTER_SITE = 0x100


@pytest.fixture
def banner_rom(make_rom):
    rom = make_rom(0x700000)
    japanese = bytes([0x11]) * (SHEET_TILES * gfx.TILE_BYTES)
    rom.write(gfx.BATTLE_BANNER_BLOCK, gfx.lz77_compress(japanese))
    rom.write_ptr(POINTER_SITE, gfx.BATTLE_BANNER_BLOCK)
    for cell, tile in enumerate(gfx.BATTLE_BANNER_MAP_JP):
        rom.write_u16(gfx.BATTLE_BANNER_MAP + 2 * cell, tile)
    return rom


@pytest.fixture
def point_font():
    charset = load_latin()
    font = bytearray([0xFF]) * (256 * GLYPH_BYTES)
    font[charset.encode["A"] * GLYPH_BYTES] = POINT_FONT_ROW
    return charset, bytes(font)


def _spec(text):
    return [{"name": "battle-start-banner",
             "block": hex(gfx.BATTLE_BANNER_BLOCK), "codec": "lz77",
             "tiles_wide": 10,
             "labels": [{"key": "battle.start", "tile_rect": [0, 0, 10, 2],
                         "text": text, "fill": 15, "outline": 5, "top": 4}]}]


def _map_of(rom):
    return tuple(rom.u16(gfx.BATTLE_BANNER_MAP + 2 * cell)
                 for cell in range(len(gfx.BATTLE_BANNER_MAP_JP)))


def _patch(rom, point_font, text):
    charset, font = point_font
    return gfx.patch_sheets(rom, charset, _spec(text), Allocator(rom),
                            pointer_index(rom), font_data=font)


def test_a_narrow_banner_straightens_the_map(banner_rom, point_font):
    report = _patch(banner_rom, point_font, "AAAAA")
    assert report.drawn == 1 and not report.skipped
    assert _map_of(banner_rom) == gfx.BATTLE_BANNER_MAP_ES
    tiles, _ = gfx.lz77_decompress(bytes(banner_rom.data), banner_rom.ptr(POINTER_SITE))
    for tile in gfx.BATTLE_BANNER_PADS:
        assert not any(tiles[tile * gfx.TILE_BYTES:(tile + 1) * gfx.TILE_BYTES]), \
            f"tile {tile} pads a corner cell and must stay blank"


def test_a_banner_reaching_its_outer_columns_is_left_japanese(banner_rom, point_font):
    original = banner_rom.read(gfx.BATTLE_BANNER_BLOCK, 64)
    report = _patch(banner_rom, point_font, "A" * 40)
    assert _map_of(banner_rom) == gfx.BATTLE_BANNER_MAP_JP
    assert banner_rom.read(gfx.BATTLE_BANNER_BLOCK, 64) == original
    assert any("outer columns" in reason for _, reason in report.skipped)


def test_an_unknown_map_is_never_overwritten(banner_rom, point_font):
    banner_rom.write_u16(gfx.BATTLE_BANNER_MAP, 0x1234)
    report = _patch(banner_rom, point_font, "AAAAA")
    assert banner_rom.u16(gfx.BATTLE_BANNER_MAP) == 0x1234
    assert any("not the one this build knows" in reason for _, reason in report.skipped)
