"""A deduplicated sheet is un-shared by cloning tilemap cells, not by hoping.

Two menu entries that begin with the same kana share those tiles, so writing
over them spells half of one word inside the other (the Medawatch carousel:
メダロッチ and メダロット生産 shared their メダ, and "Reloj" came out as
"Relット生産"). Where the game builds the screen out of the sheet's own
tilemap, the build copies the shared tiles onto the end of the sheet and
repoints one entry's cells at the copies.
"""

import pytest

from navi import gfx
from navi.build import Allocator
from navi.font import GLYPH_BYTES
from navi.strings import pointer_index
from navi.table import load_latin

BLOCK = 0x8000
MAP = 0x9000
POINTER_SITE = 0x100
SHEET_TILES = 4
#: One ink pixel per glyph: every letter measures 1px, so a rect never overflows.
POINT_FONT_ROW = 0x7F


@pytest.fixture
def sheet_rom(make_rom):
    """Four distinct tiles, and a map whose two rows share row 0's first cell."""
    rom = make_rom(0x40000)
    tiles = b"".join(bytes([n + 1]) * gfx.TILE_BYTES for n in range(SHEET_TILES))
    rom.write(BLOCK, gfx.compress(tiles))
    rom.write_ptr(POINTER_SITE, BLOCK)
    for cell, tile in enumerate((0, 1, 0, 2)):   # rows of two: (0,1) and (0,2)
        rom.write_u16(MAP + 2 * cell, tile)
    return rom


@pytest.fixture
def point_font():
    charset = load_latin()
    font = bytearray([0xFF]) * (256 * GLYPH_BYTES)
    # Ink on different rows, so a tile drawn with 'A' cannot equal one with 'B'.
    font[charset.encode["A"] * GLYPH_BYTES] = POINT_FONT_ROW
    font[charset.encode["B"] * GLYPH_BYTES + 3] = POINT_FONT_ROW
    return charset, bytes(font)


def _spec(clones=(), labels=()):
    return [{"name": "shared-sheet", "block": hex(BLOCK), "codec": "malias",
             "tiles_wide": 2, "map_clones": list(clones), "labels": list(labels)}]


def _patch(rom, point_font, spec):
    charset, font = point_font
    return gfx.patch_sheets(rom, charset, spec, Allocator(rom),
                            pointer_index(rom), font_data=font)


def _tiles(rom):
    raw, _ = gfx.decompress(bytes(rom.data), rom.ptr(POINTER_SITE))
    return [bytes(raw[n * gfx.TILE_BYTES:(n + 1) * gfx.TILE_BYTES])
            for n in range(len(raw) // gfx.TILE_BYTES)]


def _cells(rom):
    return tuple(rom.u16(MAP + 2 * cell) for cell in range(4))


def test_a_clone_frees_the_shared_tile_for_the_other_row(sheet_rom, point_font):
    label = {"fill": 15, "outline": 5, "top": 0}
    report = _patch(sheet_rom, point_font, _spec(
        clones=[{"name": "second", "map": hex(MAP), "stride": 2,
                 "row": 1, "col": 0, "count": 2, "expect": ["0x0", "0x2"]}],
        labels=[dict(label, key="first", tile_rect=[0, 0, 2, 1], text="A"),
                dict(label, key="second", run="second", text="B")]))
    assert report.drawn == 2 and not report.skipped
    # The second row now names two fresh tiles at the end of the sheet.
    assert _cells(sheet_rom) == (0, 1, SHEET_TILES, SHEET_TILES + 1)
    tiles = _tiles(sheet_rom)
    assert len(tiles) == SHEET_TILES + 2
    # Both labels drew, and neither landed in the other's tiles.
    assert tiles[0] != tiles[SHEET_TILES], "the clone is still the shared tile"
    assert any(tiles[0]) and any(tiles[SHEET_TILES])


def test_a_clone_is_invisible_until_a_label_draws_on_it(sheet_rom, point_font):
    before = _tiles(sheet_rom)
    report = _patch(sheet_rom, point_font, _spec(
        clones=[{"name": "second", "map": hex(MAP), "stride": 2,
                 "row": 1, "col": 0, "count": 2}]))
    assert not report.skipped
    after = _tiles(sheet_rom)
    assert after[SHEET_TILES] == before[0] and after[SHEET_TILES + 1] == before[2]


def test_a_clone_whose_cells_moved_is_refused(sheet_rom, point_font):
    sheet_rom.write_u16(MAP + 2 * 2, 3)          # the dump is not the one we know
    report = _patch(sheet_rom, point_font, _spec(
        clones=[{"name": "second", "map": hex(MAP), "stride": 2,
                 "row": 1, "col": 0, "count": 2, "expect": ["0x0", "0x2"]}],
        labels=[{"key": "second", "run": "second", "text": "B",
                 "fill": 15, "outline": 5, "top": 0}]))
    assert _cells(sheet_rom) == (0, 1, 3, 2), "the map was rewritten anyway"
    assert len(_tiles(sheet_rom)) == SHEET_TILES
    reasons = " ".join(reason for _, reason in report.skipped)
    assert "not the tiles this build knows" in reasons
    assert "no cloned run" in reasons, "the label must not draw into nowhere"


def test_a_clone_that_would_grow_a_capped_sheet_is_refused(sheet_rom, point_font):
    """A sheet that IS video memory cannot gain tiles; the clone must be free."""
    # The rule the Medawatch sheet lives by, in miniature: growing is refused,
    # so the tiles a clone hands out have to come from inside the sheet.
    assert gfx.MEDAWATCH_SHEET_MAX_TILES == gfx.MEDAWATCH_SHEET_TILES

def test_a_sheet_grown_past_its_vram_slot_is_refused(make_rom, point_font):
    """Overflowing the slot paints the scenery with menu tiles; refuse instead."""
    rom = make_rom(0x800000)
    tiles = b"".join(bytes([n % 16]) * gfx.TILE_BYTES
                     for n in range(gfx.MEDAWATCH_SHEET_TILES))
    rom.write(gfx.MEDAWATCH_SHEET_BLOCK, gfx.compress(tiles))
    rom.write_ptr(POINTER_SITE, gfx.MEDAWATCH_SHEET_BLOCK)
    for index, row in enumerate(gfx.MEDAWATCH_ROWS_JP):
        rom.data[gfx.MEDAWATCH_ROWS + index] = row
    for index, width in enumerate(gfx.MEDAWATCH_WIDTHS_JP):
        rom.data[gfx.MEDAWATCH_WIDTHS + index] = width
    original = rom.read(gfx.MEDAWATCH_SHEET_BLOCK, 32)
    spec = [{"name": "medawatch-carousel", "block": hex(gfx.MEDAWATCH_SHEET_BLOCK),
             "codec": "malias", "tiles_wide": 16,
             "map_clones": [{"name": "one", "map": hex(gfx.MEDAWATCH_MAP),
                             "row": 0, "col": 0, "count": 1}],
             "labels": [{"key": "one", "run": "one", "text": "A",
                         "fill": 15, "outline": 5, "top": 0}]}]
    report = _patch(rom, point_font, spec)
    assert rom.read(gfx.MEDAWATCH_SHEET_BLOCK, 32) == original, "the sheet was written"
    assert any("VRAM" in reason for _, reason in report.skipped)


@pytest.mark.game
def test_the_carousel_layout_tables_are_the_ones_the_notes_describe(game_rom):
    """The bar's geometry is data: if these move, the carousel words must too."""
    assert bytes(game_rom.read(gfx.MEDAWATCH_ROWS, 6)) == bytes(gfx.MEDAWATCH_ROWS_JP)
    assert bytes(game_rom.read(gfx.MEDAWATCH_WIDTHS, 6)) == bytes(gfx.MEDAWATCH_WIDTHS_JP)
    # Five entries at most, one separator cell each, 27 cells of bar.
    assert sum(1 + w for w in gfx.MEDAWATCH_WIDTHS_JP if w) <= gfx.MEDAWATCH_BAR_CELLS

def _points_spec(points, labels=()):
    return [{"name": "shared-sheet", "block": hex(BLOCK), "codec": "malias",
             "tiles_wide": 2, "map_points": list(points), "labels": list(labels)}]


def test_map_points_aims_cells_at_tiles_the_sheet_already_has(sheet_rom, point_font):
    """The un-sharing move for a sheet that cannot grow: no append, just aim."""
    before = _tiles(sheet_rom)
    report = _patch(sheet_rom, point_font, _points_spec(
        [{"name": "second", "map": hex(MAP), "stride": 2, "row": 1, "col": 0,
          "fill": "0x3", "count": 2, "expect": ["0x0", "0x2"]}]))
    assert not report.skipped
    assert _cells(sheet_rom) == (0, 1, 3, 3)
    assert _tiles(sheet_rom) == before, "map_points must never touch the tiles"


def test_map_points_takes_a_run_as_well_as_a_fill(sheet_rom, point_font):
    _patch(sheet_rom, point_font, _points_spec(
        [{"name": "second", "map": hex(MAP), "stride": 2, "row": 1, "col": 0,
          "from": "0x1", "count": 2, "expect": ["0x0", "0x2"]}]))
    assert _cells(sheet_rom) == (0, 1, 1, 2)


@pytest.mark.parametrize("point, why", [
    ({"fill": "0x3", "count": 2, "expect": ["0x1", "0x2"]}, "not the cells"),
    ({"fill": "0x3", "count": 2}, "without a fingerprint"),
])
def test_map_points_without_a_matching_fingerprint_is_refused(sheet_rom, point_font,
                                                              point, why):
    before = _cells(sheet_rom)
    report = _patch(sheet_rom, point_font, _points_spec(
        [dict(point, name="second", map=hex(MAP), stride=2, row=1, col=0)]))
    assert _cells(sheet_rom) == before, "the map moved anyway"
    assert any(why in reason for _, reason in report.skipped)
