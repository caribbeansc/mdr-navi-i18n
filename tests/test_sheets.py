"""patch_sheets must fold two specs that name the same block.

Each spec's pass decompresses the pristine block, so without folding the
second spec's write silently undoes the first one's labels (found when the
Medawatch additions to menu-status-labels arrived as a second spec).
"""

import pytest

from navi import gfx
from navi.build import Allocator
from navi.font import GLYPH_BYTES
from navi.strings import pointer_index
from navi.table import load_latin


class _Report:
    pass


@pytest.fixture
def sheet_rom(make_rom):
    rom = make_rom(0x40000)
    tiles = bytes(0x11) * (4 * 32)  # four solid 4bpp tiles
    packed = gfx.compress(tiles)
    block = 0x8000
    rom.write(block, packed)
    rom.write_ptr(0x100, block)  # a site so a grown block can relocate
    return rom, block, len(packed)


def _specs(block):
    label = {"fill": 15, "outline": 5, "top": 0}
    return [
        {"name": "first", "block": hex(block), "codec": "malias",
         "tiles_wide": 4,
         "labels": [dict(label, key="a", tile_rect=[0, 0, 2, 1], text="A")]},
        {"name": "second", "block": hex(block), "codec": "malias",
         "tiles_wide": 4,
         "labels": [dict(label, key="b", tile_rect=[2, 0, 2, 1], text="B")]},
    ]


def test_two_specs_on_one_block_compose(sheet_rom):
    rom, block, _ = sheet_rom
    charset = load_latin()
    font_data = bytes([0xFF]) * (256 * GLYPH_BYTES)  # blank font base
    # give 'A' and 'B' one ink pixel each so the draw is observable
    font = bytearray(font_data)
    for char in "AB":
        code = charset.encode[char]
        font[code * GLYPH_BYTES] = 0x7F  # ink in column 0 of row 0
    allocator = Allocator(rom)
    report = gfx.patch_sheets(rom, charset, _specs(block), allocator,
                              pointer_index(rom), font_data=bytes(font))
    assert report.drawn == 2 and not report.skipped
    where = rom.ptr(0x100)  # in place, or wherever the grown block went
    tiles, _ = gfx.decompress(bytes(rom.data), where)
    left = tiles[0:32]
    right = tiles[2 * 32:3 * 32]
    assert any(v != 0x11 for v in left), "first spec's label was lost"
    assert any(v != 0x11 for v in right), "second spec's label was lost"
