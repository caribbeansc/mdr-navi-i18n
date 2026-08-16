"""Redrawing the menus that are pictures, not text.

The title menu (はじめから・つづきから・設定) and the OPTION screen keep their
labels as 4bpp sprite tiles, compressed with the game's own "Malias" scheme —
a 2-bit-per-command LZ variant whose blocks start with the bytes ``Le``. No
string table is involved, so translating them means: decompress the block,
erase the Japanese pixels, draw the Spanish with the same font the dialogue
uses, recompress, and put the block back.

Putting it back is the delicate part. A recompressed block that fits where the
original sat is written in place. A bigger one is relocated to free space and
the one pointer that names the block is repointed — every block here is
reached through a small asset table, one pointer each, found by scanning.

Format, ported from Normmatt's Malias2.cs (see NOTICE):
  header  'L' 'e' <len:3> <pad:1>, then command bytes, 4 fields of 2 bits
  mode 0  far copy:  2 bytes -> distance (v&0xFFF)+5, count (v>>12)+3
  mode 1  near copy: 1 byte  -> distance (v&3)+1,     count (v>>2)+2
  mode 2  1 literal byte
  mode 3  3 literal bytes
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import struct

from . import font as font_mod
from .rom import Rom
from .table import Charset

MAGIC = b"Le"

TILE_BYTES = 32
TILE_SIDE = 8


class GfxError(Exception):
    pass


# -- the Malias codec ----------------------------------------------------


def decompress(data: bytes, offset: int) -> tuple[bytes, int]:
    """Decompress one block. Returns (payload, compressed length)."""
    if data[offset:offset + 2] != MAGIC:
        raise GfxError(f"No Malias block at {offset:#x}")
    length = data[offset + 2] | data[offset + 3] << 8 | data[offset + 4] << 16
    src = offset + 6
    out = bytearray()
    remaining = length
    while remaining > 0:
        command = data[src]
        src += 1
        for _ in range(4):
            if remaining <= 0:
                break
            mode = command & 3
            if mode == 0:
                value = data[src] | data[src + 1] << 8
                src += 2
                distance = (value & 0xFFF) + 5
                count = (value >> 12) + 3
                if distance > len(out):
                    raise GfxError(f"Bad back-reference at {offset:#x}")
                for _ in range(count):
                    out.append(out[-distance])
                remaining -= count
            elif mode == 1:
                value = data[src]
                src += 1
                distance = (value & 3) + 1
                count = (value >> 2) + 2
                if distance > len(out):
                    raise GfxError(f"Bad back-reference at {offset:#x}")
                for _ in range(count):
                    out.append(out[-distance])
                remaining -= count
            elif mode == 2:
                out.append(data[src])
                src += 1
                remaining -= 1
            else:
                out += data[src:src + 3]
                src += 3
                remaining -= 3
            command >>= 2
    return bytes(out[:length]), src - offset


def compress(raw: bytes) -> bytes:
    """A greedy Malias encoder. Decompresses to ``raw`` exactly."""
    fields: list[tuple[int, bytes]] = []  # (mode, payload bytes)
    i = 0
    n = len(raw)
    literals: list[int] = []

    def flush_literals() -> None:
        while len(literals) >= 3:
            fields.append((3, bytes(literals[:3])))
            del literals[:3]
        while literals:
            fields.append((2, bytes([literals.pop(0)])))

    while i < n:
        best_len = 0
        best_mode = -1
        best_payload = b""
        # Near copy: distances 1-4, up to 65 bytes. This is what makes runs
        # of identical tiles cheap, so try it first at equal length.
        for distance in range(1, 5):
            if distance > i:
                break
            length = 0
            while length < 65 and i + length < n and raw[i + length] == raw[i + length - distance]:
                length += 1
            if length >= 2 and length > best_len:
                best_len = length
                best_mode = 1
                best_payload = bytes([((length - 2) << 2) | (distance - 1)])
        # Far copy: distances 5-4100, 3-18 bytes.
        start = max(0, i - 4100)
        window = raw[start:i]
        limit = min(18, n - i)
        if limit >= 3:
            probe = min(limit, 18)
            for length in range(probe, max(2, best_len), -1):
                needle = raw[i:i + length]
                # Overlapping copies never happen here: distance >= 5 > 0 and
                # the needle must sit wholly inside the window.
                at = window.rfind(needle)
                while at >= 0:
                    distance = i - (start + at)
                    if 5 <= distance <= 4100:
                        best_len = length
                        best_mode = 0
                        value = ((length - 3) << 12) | (distance - 5)
                        best_payload = bytes([value & 0xFF, value >> 8])
                        break
                    at = window.rfind(needle, 0, at + length - 1)
                if best_mode == 0:
                    break
        if best_mode >= 0 and best_len >= 2:
            flush_literals()
            fields.append((best_mode, best_payload))
            i += best_len
        else:
            literals.append(raw[i])
            i += 1
            if len(literals) == 3:
                flush_literals()
    flush_literals()

    out = bytearray(MAGIC)
    out += bytes([len(raw) & 0xFF, (len(raw) >> 8) & 0xFF, (len(raw) >> 16) & 0xFF, 0])
    for group_start in range(0, len(fields), 4):
        group = fields[group_start:group_start + 4]
        command = 0
        for slot, (mode, _) in enumerate(group):
            command |= mode << (2 * slot)
        out.append(command)
        for _, payload in group:
            out += payload
    return bytes(out)


# -- pixel canvases ------------------------------------------------------


class Canvas:
    """A sprite's tiles as one addressable pixel grid.

    Sprites use one-dimensional tile mapping: a WxH-tile sprite is W*H
    consecutive tiles, row by row. 4bpp: each tile is 32 bytes, two pixels
    per byte, low nibble first.
    """

    def __init__(self, tiles: bytearray, tiles_wide: int, tiles_high: int, base_tile: int = 0):
        self.tiles = tiles
        self.width = tiles_wide * TILE_SIDE
        self.height = tiles_high * TILE_SIDE
        self.tiles_wide = tiles_wide
        self.base = base_tile

    def _locate(self, x: int, y: int) -> tuple[int, int]:
        tile = self.base + (y // TILE_SIDE) * self.tiles_wide + (x // TILE_SIDE)
        offset = tile * TILE_BYTES + (y % TILE_SIDE) * 4 + (x % TILE_SIDE) // 2
        return offset, x & 1
    def get(self, x: int, y: int) -> int:
        offset, odd = self._locate(x, y)
        byte = self.tiles[offset]
        return byte >> 4 if odd else byte & 0xF

    def set(self, x: int, y: int, value: int) -> None:
        if not (0 <= x < self.width and 0 <= y < self.height):
            return
        offset, odd = self._locate(x, y)
        byte = self.tiles[offset]
        if odd:
            self.tiles[offset] = (byte & 0x0F) | (value << 4)
        else:
            self.tiles[offset] = (byte & 0xF0) | value

    def clear(self, value: int = 0) -> None:
        for y in range(self.height):
            for x in range(self.width):
                self.set(x, y, value)

    def ink_box(self) -> tuple[int, int, int, int] | None:
        """Bounding box of the non-zero pixels, or None if blank."""
        xs, ys = [], []
        for y in range(self.height):
            for x in range(self.width):
                if self.get(x, y):
                    xs.append(x)
                    ys.append(y)
        if not xs:
            return None
        return min(xs), min(ys), max(xs), max(ys)


# -- drawing text with the game's font -----------------------------------


class Typesetter:
    """Rasterises text using the same glyphs the dialogue box draws.

    Glyph ink is measured so letters pack proportionally instead of sitting
    in fixed 8-pixel cells — menu labels are tight on space.
    """

    def __init__(self, rom: Rom, charset: Charset, font_data: bytes | None = None):
        if font_data is None:
            # Build from a PRISTINE rom only: build_font raises the native
            # Latin block, and raising an already-patched font a second time
            # shears the top row off every capital.
            font_data, _ = font_mod.build_font(rom, charset)
        self.font = font_data
        self.charset = charset

    def _glyph(self, char: str) -> tuple[list[list[bool]], int, int]:
        code = self.charset.encode.get(char)
        if code is None or code >= font_mod.GLYPH_COUNT:
            raise GfxError(f"No glyph for {char!r}")
        rows = self.font[code * font_mod.GLYPH_BYTES:(code + 1) * font_mod.GLYPH_BYTES]
        grid = [[not (row & (0x80 >> x)) for x in range(8)] for row in rows]
        inked = [x for row in grid for x in range(8) if row[x]]
        if not inked:
            return grid, 0, 3  # a space
        return grid, min(inked), max(inked) - min(inked) + 1

    def measure(self, text: str, spacing: int = 1) -> int:
        total = 0
        for char in text:
            _, _, width = self._glyph(char)
            total += (width or 3) + spacing
        return max(0, total - spacing)

    def draw(self, canvas: Canvas, x: int, y: int, text: str,
             fill: int, outline: int | None = None, spacing: int = 1) -> int:
        """Draw ``text`` with its top-left at (x, y). Returns the end x."""
        pen = x
        for char in text:
            grid, left, width = self._glyph(char)
            if width == 0:
                pen += 3 + spacing
                continue
            for gy in range(font_mod.GLYPH_HEIGHT):
                for gx in range(width):
                    if grid[gy][left + gx]:
                        canvas.set(pen + gx, y + gy, fill)
            pen += width + spacing
        if outline is not None:
            self._outline(canvas, fill, outline)
        return pen - spacing

    def outline_pass(self, canvas: Canvas, fill: int, outline: int) -> None:
        """Ring every ``fill`` pixel with ``outline``, once, over a whole canvas.

        ``draw`` does this per call; text drawn in several passes wants one
        outline pass at the end instead, so the second line does not re-outline
        the first through the gap between them.
        """
        self._outline(canvas, fill, outline)

    def rim(self, canvas: Canvas, body: int, rim: int) -> None:
        """A one-pixel highlight along the top edge of every body pixel."""
        if rim is None:
            return
        for y in range(canvas.height):
            for x in range(canvas.width):
                if canvas.get(x, y) == body and y > 0 and canvas.get(x, y - 1) == 0:
                    canvas.set(x, y - 1, rim)

    def _outline(self, canvas: Canvas, fill: int, outline: int) -> None:
        for y in range(canvas.height):
            for x in range(canvas.width):
                if canvas.get(x, y):
                    continue
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < canvas.width and 0 <= ny < canvas.height \
                            and canvas.get(nx, ny) == fill:
                        canvas.set(x, y, outline)
                        break


# -- the assets ----------------------------------------------------------


@dataclass
class Label:
    """One piece of text inside an asset."""

    #: Key into the language pack's gfx.json.
    key: str
    #: First tile of the sprite holding it, within the block.
    base_tile: int
    #: Sprite dimensions in tiles.
    tiles: tuple[int, int]
    #: Palette index the letters are filled with.
    fill: int
    #: Palette index of the outline, or None.
    outline: int | None = None
    #: "outline" draws fill+outline; "bevel" draws the body in ``fill`` and a
    #: one-pixel top rim in ``outline`` — the title menu's palettes swap the
    #: two between the selected and the dimmed state, so the BODY must use the
    #: index the Japanese glyphs used or the dimmed label goes near-invisible.
    style: str = "outline"


@dataclass
class Asset:
    """One compressed block and the labels drawn inside it."""

    name: str
    block: int
    labels: list[Label] = field(default_factory=list)


#: The graphic menus of the Kuwagata release. Block offsets are file offsets
#: of their 'Le' headers; each is reached by exactly one pointer.
KUWAGATA_ASSETS = [
    Asset("title-continue", 0x639738,
          [Label("title.continue", 0, (8, 4), fill=1, outline=15, style="bevel")]),
    Asset("title-new-game", 0x639838,
          [Label("title.new_game", 0, (8, 4), fill=1, outline=15, style="bevel")]),
    Asset("title-settings", 0x639954,
          [Label("title.settings", 0, (8, 4), fill=1, outline=15, style="bevel")]),
    Asset("option-values", 0x64231C,
          [Label("option.long", 0, (4, 2), fill=15, outline=5),
           Label("option.normal", 8, (4, 2), fill=15, outline=5),
           Label("option.short", 16, (4, 2), fill=15, outline=5)]),
]

#: The OPTION screen's two headers (戦闘時間 / 戦闘BGM) live in a BG tile
#: sheet whose tilemap rows sit *uncompressed* right after the sheet block —
#: and the two labels share their 戦闘 tiles, so redrawing in place cannot
#: give them different words. Instead the sheet grows new tiles at the end and
#: the map rows are repointed at them. Each entry below is (file offset of the
#: row's five u16 map entries).
OPTION_SHEET_BLOCK = 0x641C48
OPTION_HEADERS = [
    # key,          (top row at, bottom row at)
    ("option.time", (0x641EA2, 0x641EDE)),
    ("option.bgm",  (0x6420FA, 0x642136)),
]
OPTION_HEADER_COLS = 5
OPTION_HEADER_FILL = 15
OPTION_HEADER_OUTLINE = 5

#: The robottle-start banner (戦闘開始, the white box the overlay opens with)
#: is NOT a plain 10x2 picture. Its twelve-by-two tilemap sits uncompressed at
#: BATTLE_BANNER_MAP, holding tile numbers relative to the sheet; the game adds
#: the VRAM base and palette bank 2 and lays the rows over screen x=0..95.
#: The Japanese map reads
#:      0  1  2  3  4  4  5  6  7  8  9  0
#:      0 10 11 12 13 14 15 16 17 18 19  0
#: — tile 0 is a blank pad in the four corner cells, so the banner is ten
#: columns wide, its BOTTOM halves are tiles 10-19 in order but its TOP halves
#: are only tiles 1-9, because columns 3 and 4 SHARE tile 4. 闘's upper half
#: happens to repeat across that seam; Latin letters never do, so a sheet drawn
#: as a straight 10x2 image came out with its top row shifted one cell left and
#: doubled in the middle (the "ЯB0B0̈ATALLA" bug).
#:
#: The build therefore rewrites the map into a straight ten-column banner —
#: sheet tiles 0-9 over 10-19, each used once — and pads the two corner cells
#: with the banner's own outer columns. That only works while those columns
#: carry no ink, so they are checked; when they do, the sheet is left alone and
#: the Japanese banner keeps its Japanese map.
BATTLE_BANNER_BLOCK = 0x662970
BATTLE_BANNER_MAP = 0x664758
BATTLE_BANNER_MAP_JP = (0, 1, 2, 3, 4, 4, 5, 6, 7, 8, 9, 0,
                        0, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 0)
BATTLE_BANNER_MAP_ES = (0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 9,
                        10, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 19)
#: The tiles the rewritten map re-uses as padding: the banner's first and last
#: column, top and bottom half. In practice the word must measure 62px or less
#: so that centring it in the 80px sheet leaves both outer columns empty.
BATTLE_BANNER_PADS = (0, 9, 10, 19)

#: THE MEDAWATCH BAR IS A CAROUSEL, AND ITS LAYOUT IS DATA, NOT CODE.
#: The bar along the top of the Medawatch (navi badge, then one entry per
#: unlocked function) is not painted from a screen tilemap of its own: the
#: game blits rectangles out of the SHEET'S OWN tilemap, uncompressed at
#: MEDAWATCH_MAP, sixteen cells to the row. The blitter is at 0x0807CC9C and
#: takes (destination, first cell, width, height); the bar is assembled at
#: 0x0807CE9E and DMA'd from 0x03005ED4. One entry occupies the rectangle
#: (row, 0, w, 2) while it sits in a small side plate and (row, w, w, 2) while
#: it is the selected one in the wide field — the two "states" every entry has
#: in this sheet are those two plates, not selected/unselected colours.
#:
#: `row` and `w` are one byte per entry in two six-byte tables in ROM:
#:      MEDAWATCH_ROWS   00 02 04 00 06 08   (sheet map row of each entry)
#:      MEDAWATCH_WIDTHS 04 04 05 00 04 03   (cells, i.e. 8px units)
#: in entry order メダロッチ, 仲間配置, メダロット生産, (unused), ステータス,
#: セーブ. The bar is 30 cells, the badge eats 3, and the code pads the
#: selected entry with 27 - sum(1 + w) filler cells, so ALL the entries
#: together cannot grow past 22 cells; each row also stops where the icon
#: blits start (column 10, or column 7 in セーブ's row, which the badge uses).
#: Widening an entry therefore means paying for it out of another one, and is
#: why the carousel words are as short as they are.
#: Both tables have exactly one reader each (the composer's literal pool at
#: 0x0807CE7C), and the entry list they are indexed by is built at 0x0808009C:
#: types 0, 1, 2 and 5 plus 4 behind a flag, terminated with 0x7A — five
#: entries at most, so the whole bar costs 5 separators and the widths must sum
#: to 22 or less. Spanish spends them differently: メダロッチ takes eight cells
#: for "Medarreloj" and メダロット生産 pays for them by dropping to three
#: ("Crea"), which lands on exactly 27 and leaves the selected entry no filler.
#: Eight cells do not fit beside the icon blits that own columns 10-15 of every
#: entry row, so メダロッチ moves to row 40 — the map is 40 rows but the 256
#: bytes after it are zero and nothing in the ROM points at them, which is
#: eight spare rows the blitter can already reach (cell = row * 16 + column).
MEDAWATCH_SHEET_BLOCK = 0x7F2190
MEDAWATCH_MAP = 0x7F32D0
MEDAWATCH_MAP_STRIDE = 16
MEDAWATCH_MAP_ROWS = 40
MEDAWATCH_ROWS = 0x5D5EF0
MEDAWATCH_WIDTHS = 0x5D5EEA
MEDAWATCH_ROWS_JP = (0, 2, 4, 0, 6, 8)
MEDAWATCH_WIDTHS_JP = (4, 4, 5, 0, 4, 3)
#: 30 cells of bar, three of them the navi badge.
MEDAWATCH_BAR_CELLS = 27

#: AND THE SHEET CANNOT GROW AT ALL. It is not unpacked into RAM and DMA'd:
#: 0x0807CC42 hands the block straight to the decompressor with 0x06004000 as
#: the destination, so the sheet IS the VRAM at char base 1 and every byte past
#: its 12160 lands on the next graphic — which is a scene tileset on most of
#: the screens that load it. A build that grew the sheet to 421 tiles shipped
#: once and turned the station street in the intro to noise; four tiles over
#: looked clean in the Medawatch captures and is still forbidden, because
#: "clean in the frames I sampled" is not the same as "inside the budget".
#: Fresh tiles therefore have to come from INSIDE the sheet: a plate's chrome
#: row is the same eight pixels in every column, so one chrome tile can be
#: repeated across a whole row and the rest of that row's tiles are free for
#: the words.
MEDAWATCH_SHEET_TILES = 380
MEDAWATCH_SHEET_MAX_TILES = MEDAWATCH_SHEET_TILES

#: The Spanish bar, then, is a re-cut of the cells rather than a bigger sheet.
#: メダロッチ moves to row 40 — the map is 40 rows, the 256 bytes behind it are
#: zero and nothing in the ROM points at them — and takes eight cells, because
#: eight will not fit on its old row where the icon blits own columns 10-15.
#: メダロット生産 drops to three to pay for it: five entries, one separator
#: cell each, and 27 cells of bar means the widths must sum to 22.
MEDAWATCH_ROWS_ES = (40, 2, 4, 0, 6, 8)
MEDAWATCH_WIDTHS_ES = (8, 4, 3, 0, 4, 3)

#: The seven leg-type plates (飛行/浮遊/多脚/二脚/車両/戦車/潜水) are laid out
#: by an uncompressed u16 table at PART_TYPE_PLATE_MAP: seven plates of 5x2
#: cells, plain sheet-tile indices (one 0x0800 v-flip bit on 戦車's corner).
#: The Japanese map DEDUPLICATES aggressively — columns 0 and 4 are shared
#: pads and 二脚 owns only 2 of its 5 columns (the rest belong to 多脚) — so
#: no full Spanish word fits the tiles a plate owns. The build instead
#: appends ten FRESH tiles per plate to the sheet, draws the full word
#: centred across the whole 40x16 plate, and rewrites that plate's ten map
#: entries; the sheet grows and relocates through its one pointer. Words come
#: from gfx.json "plate_words" (seven entries, plate order above).
PART_TYPE_PLATE_BLOCK = 0x661958
PART_TYPE_PLATE_MAP = 0x663F8C
PART_TYPE_PLATE_COUNT = 7
PART_TYPE_PLATE_CELLS = 10
#: Ink budget: 40px minus one outline column each side.
PART_TYPE_PLATE_INK = 38


def patch_part_type_plates(rom: Rom, charset: Charset, words: list[str],
                           allocator, pointer_sites: dict[int, list[int]],
                           report: "GfxReport",
                           font_data: bytes | None = None) -> None:
    """Give every leg-type plate its own tiles and the full Spanish word."""
    if len(words) != PART_TYPE_PLATE_COUNT:
        report.skipped.append(("plate_words",
                               f"want {PART_TYPE_PLATE_COUNT} words, got {len(words)}"))
        return
    sites = pointer_sites.get(PART_TYPE_PLATE_BLOCK, [])
    at = rom.ptr(sites[0]) if sites else PART_TYPE_PLATE_BLOCK
    dec, enc = CODECS["lz77"]
    try:
        raw, comp_len = dec(bytes(rom.data), at)
    except GfxError as exc:
        report.skipped.append(("plate_words", str(exc)))
        return
    tiles = bytearray(raw)
    base = len(tiles) // TILE_BYTES
    tiles += bytes(PART_TYPE_PLATE_COUNT * PART_TYPE_PLATE_CELLS * TILE_BYTES)
    setter = Typesetter(rom, charset, font_data)

    for i, word in enumerate(words):
        spacing = 1
        width = setter.measure(word, spacing)
        if width > PART_TYPE_PLATE_INK:
            spacing = 0
            width = setter.measure(word, spacing)
        if width > PART_TYPE_PLATE_INK:
            report.skipped.append((f"plate:{word}",
                                   f"{width}px into {PART_TYPE_PLATE_INK}px"))
            continue
        canvas = Canvas(tiles, 5, 2, base_tile=base + i * PART_TYPE_PLATE_CELLS)
        setter.draw(canvas, (5 * TILE_SIDE - width) // 2, 3, word,
                    fill=15, outline=5, spacing=spacing)
        for j in range(PART_TYPE_PLATE_CELLS):
            entry_at = PART_TYPE_PLATE_MAP + (i * PART_TYPE_PLATE_CELLS + j) * 2
            rom.write(entry_at, bytes([
                (base + i * PART_TYPE_PLATE_CELLS + j) & 0xFF,
                ((base + i * PART_TYPE_PLATE_CELLS + j) >> 8) & 0x03,
            ]))
        report.drawn += 1

    packed = enc(bytes(tiles))
    if len(packed) <= comp_len:
        rom.write(at, packed)
        report.in_place += 1
    else:
        destination = allocator.take(len(packed))
        rom.write(destination, packed)
        if not sites:
            report.skipped.append(("plate_words", "grew, and nothing points at it"))
            return
        for site in sites:
            rom.write_ptr(site, destination)
        report.relocated += 1


def load_texts(pack_dir: Path) -> dict[str, str]:
    path = pack_dir / "gfx.json"
    if not path.is_file():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return dict(raw.get("labels", {}))


@dataclass
class GfxReport:
    drawn: int = 0
    in_place: int = 0
    relocated: int = 0
    skipped: list[tuple[str, str]] = field(default_factory=list)


def patch(rom: Rom, charset: Charset, texts: dict[str, str], allocator,
          pointer_sites: dict[int, list[int]],
          font_data: bytes | None = None) -> GfxReport:
    """Redraw every asset whose labels have text, and put the blocks back.

    When the rom's font has already been patched (the normal case inside a
    build), pass that font in as ``font_data``.
    """
    report = GfxReport()
    setter = Typesetter(rom, charset, font_data)
    data = bytes(rom.data)

    for asset in KUWAGATA_ASSETS:
        wanted = [(label, texts.get(label.key)) for label in asset.labels]
        if not any(text for _, text in wanted):
            continue
        try:
            raw, comp_len = decompress(data, asset.block)
        except GfxError as exc:
            report.skipped.append((asset.name, str(exc)))
            continue
        tiles = bytearray(raw)

        for label, text in wanted:
            if not text:
                continue
            canvas = Canvas(tiles, label.tiles[0], label.tiles[1], label.base_tile)
            box = canvas.ink_box()
            canvas.clear()
            width = setter.measure(text)
            if width > canvas.width:
                report.skipped.append(
                    (label.key, f"{text!r} is {width}px, the sprite is {canvas.width}px"))
                continue
            # Sit where the Japanese sat; centre horizontally.
            top = box[1] if box else (canvas.height - font_mod.GLYPH_HEIGHT) // 2
            top = min(top, canvas.height - font_mod.GLYPH_HEIGHT - 1)
            if label.style == "bevel":
                setter.draw(canvas, (canvas.width - width) // 2, top, text,
                            label.fill, None)
                setter.rim(canvas, label.fill, label.outline)
            else:
                setter.draw(canvas, (canvas.width - width) // 2, top, text,
                            label.fill, label.outline)
            report.drawn += 1

        packed = compress(bytes(tiles))
        if len(packed) <= comp_len:
            rom.write(asset.block, packed)
            report.in_place += 1
        else:
            sites = pointer_sites.get(asset.block, [])
            if not sites:
                report.skipped.append((asset.name, "grew, and nothing points at it"))
                continue
            destination = allocator.take(len(packed))
            rom.write(destination, packed)
            for site in sites:
                rom.write_ptr(site, destination)
            report.relocated += 1

    _patch_option_headers(rom, setter, texts, allocator, pointer_sites, report, data)
    patch_save_panel(rom, setter, allocator, pointer_sites, report)
    return report


def _patch_option_headers(rom: Rom, setter: Typesetter, texts: dict[str, str],
                          allocator, pointer_sites: dict[int, list[int]],
                          report: GfxReport, original: bytes) -> None:
    """Grow the OPTION sheet with fresh header tiles and repoint the map rows."""
    wanted = [(key, rows, texts.get(key)) for key, rows in OPTION_HEADERS]
    if not any(text for _, _, text in wanted):
        return
    try:
        raw, comp_len = decompress(original, OPTION_SHEET_BLOCK)
    except GfxError as exc:
        report.skipped.append(("option-headers", str(exc)))
        return
    tiles = bytearray(raw)

    for key, (top_row_at, bottom_row_at), text in wanted:
        if not text:
            continue
        width = setter.measure(text)
        if width > OPTION_HEADER_COLS * TILE_SIDE:
            report.skipped.append(
                (key, f"{text!r} is {width}px, the header fits "
                      f"{OPTION_HEADER_COLS * TILE_SIDE}px"))
            continue
        base = len(tiles) // TILE_BYTES
        tiles += bytes(OPTION_HEADER_COLS * 2 * TILE_BYTES)
        canvas = Canvas(tiles, OPTION_HEADER_COLS, 2, base)
        top = (canvas.height - font_mod.GLYPH_HEIGHT) // 2
        setter.draw(canvas, (canvas.width - width) // 2, top, text,
                    OPTION_HEADER_FILL, OPTION_HEADER_OUTLINE)
        for column in range(OPTION_HEADER_COLS):
            rom.write_u16(top_row_at + 2 * column, base + column)
            rom.write_u16(bottom_row_at + 2 * column, base + OPTION_HEADER_COLS + column)
        report.drawn += 1

    packed = compress(bytes(tiles))
    if len(packed) <= comp_len:
        rom.write(OPTION_SHEET_BLOCK, packed)
        report.in_place += 1
    else:
        sites = pointer_sites.get(OPTION_SHEET_BLOCK, [])
        if not sites:
            report.skipped.append(("option-headers", "sheet grew, nothing points at it"))
            return
        destination = allocator.take(len(packed))
        rom.write(destination, packed)
        for site in sites:
            rom.write_ptr(site, destination)
        report.relocated += 1


# -- the BIOS LZ77 codec --------------------------------------------------
#
# Most of the battle/status sheets use the GBA BIOS's LZ77 (header 0x10 +
# 24-bit size), not Malias. The compressor keeps every back-reference at a
# displacement of 2 or more, because the BIOS's VRAM decompressor writes
# 16-bit halfwords and a displacement of 1 corrupts under it.

def lz77_decompress(data: bytes, offset: int) -> tuple[bytes, int]:
    if data[offset] != 0x10:
        raise GfxError(f"No LZ77 block at {offset:#x}")
    size = data[offset + 1] | data[offset + 2] << 8 | data[offset + 3] << 16
    p = offset + 4
    out = bytearray()
    while len(out) < size:
        flags = data[p]
        p += 1
        for bit in range(8):
            if len(out) >= size:
                break
            if flags & (0x80 >> bit):
                value = (data[p] << 8) | data[p + 1]
                p += 2
                count = (value >> 12) + 3
                distance = (value & 0xFFF) + 1
                if distance > len(out):
                    raise GfxError(f"Bad LZ77 back-reference at {offset:#x}")
                for _ in range(count):
                    out.append(out[-distance])
            else:
                out.append(data[p])
                p += 1
    return bytes(out[:size]), p - offset


def lz77_compress(raw: bytes) -> bytes:
    out = bytearray([0x10, len(raw) & 0xFF, (len(raw) >> 8) & 0xFF, (len(raw) >> 16) & 0xFF])
    i = 0
    n = len(raw)
    while i < n:
        flags = 0
        chunk = bytearray()
        for bit in range(8):
            if i >= n:
                break
            best_len = 0
            best_dist = 0
            start = max(0, i - 0x1000)
            window = raw[start:i]
            limit = min(18, n - i)
            if limit >= 3:
                for length in range(limit, 2, -1):
                    at = window.rfind(raw[i:i + length])
                    while at >= 0:
                        distance = i - (start + at)
                        if distance >= 2:
                            best_len = length
                            best_dist = distance
                            break
                        at = window.rfind(raw[i:i + length], 0, at + length - 1)
                    if best_len:
                        break
            if best_len:
                flags |= 0x80 >> bit
                value = ((best_len - 3) << 12) | (best_dist - 1)
                chunk += bytes([value >> 8, value & 0xFF])
                i += best_len
            else:
                chunk.append(raw[i])
                i += 1
        out.append(flags)
        out += chunk
    while len(out) % 4:
        out.append(0)
    return bytes(out)


CODECS = {
    "malias": (decompress, compress),
    "lz77": (lz77_decompress, lz77_compress),
}


# -- data-driven sheet patching ------------------------------------------
#
# A "sheet" is one compressed block of tiles holding several drawn labels.
# The language pack describes each label as a tile-rectangle plus text
# (langs/<code>/gfx.json, "sheets" section); the build clears the rectangle,
# draws the text with the game's own font, and puts the block back — in
# place when the recompressed block fits, relocated (every listed write site
# repointed) when it does not.

def patch_sheets(rom: Rom, charset: Charset, sheets: list[dict], allocator,
                 pointer_sites: dict[int, list[int]],
                 font_data: bytes | None = None) -> GfxReport:
    report = GfxReport()
    setter = Typesetter(rom, charset, font_data)
    data = bytes(rom.data)

    # Two specs naming the same block must be folded into one pass: each
    # iteration decompresses the PRISTINE block, so a second spec would
    # silently undo the first one's labels.
    folded: dict[int, dict] = {}
    ordered: list[dict] = []
    for sheet in sheets:
        first = int(str((sheet["blocks"] if "blocks" in sheet
                         else [sheet["block"]])[0]), 16)
        prior = folded.get(first)
        if prior is None:
            copy = dict(sheet)
            copy["labels"] = list(sheet.get("labels", []))
            copy["map_clones"] = list(sheet.get("map_clones", []))
            copy["map_points"] = list(sheet.get("map_points", []))
            folded[first] = copy
            ordered.append(copy)
            continue
        if prior.get("codec", "malias") != sheet.get("codec", "malias") or \
                int(prior.get("tiles_wide", 16)) != int(sheet.get("tiles_wide", 16)):
            report.skipped.append((sheet.get("name", hex(first)),
                                   f"same block as {prior.get('name')} but "
                                   "different codec/tiles_wide"))
            continue
        prior["labels"].extend(sheet.get("labels", []))
        prior["map_clones"].extend(sheet.get("map_clones", []))
        prior["map_points"].extend(sheet.get("map_points", []))
        # The folded sheet is the first spec, so a later one's request of the
        # block as a whole has to travel with its labels.
        if sheet.get("medawatch_layout"):
            prior["medawatch_layout"] = sheet["medawatch_layout"]

    for sheet in ordered:
        blocks = [int(str(b), 16) for b in
                  (sheet["blocks"] if "blocks" in sheet else [sheet["block"]])]
        codec = sheet.get("codec", "malias")
        dec, enc = CODECS[codec]
        try:
            raw, comp_len = dec(data, blocks[0])
        except GfxError as exc:
            report.skipped.append((sheet.get("name", hex(blocks[0])), str(exc)))
            continue
        tiles = bytearray(raw)
        # Clone first: the cloned tiles are what the run-addressed labels draw
        # on, and their map cells must not move unless the block is written.
        runs, map_writes = apply_map_clones(tiles, sheet, rom, report)
        map_writes += apply_map_points(sheet, rom, report)
        apply_sheet_labels(tiles, sheet, setter, report, runs)

        relayout = sheet.get("medawatch_layout") == "es"
        if blocks[0] == MEDAWATCH_SHEET_BLOCK:
            problem = _medawatch_sheet_problem(rom, tiles, relayout)
            if problem is not None:
                report.skipped.append((sheet.get("name", hex(blocks[0])), problem))
                continue

        remap = None
        if blocks[0] == BATTLE_BANNER_BLOCK:
            problem = _battle_banner_map_problem(rom, tiles)
            if problem is not None:
                report.skipped.append((sheet.get("name", hex(blocks[0])), problem))
                continue
            remap = BATTLE_BANNER_MAP_ES

        packed = enc(bytes(tiles))
        if len(packed) <= comp_len:
            for block in blocks:
                rom.write(block, packed)
            report.in_place += 1
        else:
            destination = allocator.take(len(packed))
            rom.write(destination, packed)
            repointed = False
            for block in blocks:
                for site in pointer_sites.get(block, []):
                    rom.write_ptr(site, destination)
                    repointed = True
            if not repointed:
                report.skipped.append(
                    (sheet.get("name", hex(blocks[0])), "grew, and nothing points at it"))
                continue
            report.relocated += 1
        for cell, tile in map_writes:
            rom.write_u16(cell, tile)
        if relayout:
            for index, row in enumerate(MEDAWATCH_ROWS_ES):
                rom.data[MEDAWATCH_ROWS + index] = row
            for index, width in enumerate(MEDAWATCH_WIDTHS_ES):
                rom.data[MEDAWATCH_WIDTHS + index] = width
        if remap is not None:
            for cell, tile in enumerate(remap):
                rom.write_u16(BATTLE_BANNER_MAP + 2 * cell, tile)
    return report


def _battle_banner_map_problem(rom: Rom, tiles: bytes) -> str | None:
    """Why the robottle banner's tilemap cannot be straightened, or None."""
    current = tuple(rom.u16(BATTLE_BANNER_MAP + 2 * cell)
                    for cell in range(len(BATTLE_BANNER_MAP_JP)))
    if current != BATTLE_BANNER_MAP_JP:
        return f"the tilemap at {BATTLE_BANNER_MAP:#x} is not the one this build knows"
    inked = [tile for tile in BATTLE_BANNER_PADS
             if any(tiles[tile * TILE_BYTES:(tile + 1) * TILE_BYTES])]
    if inked:
        return ("the banner reaches its outer columns (tiles "
                + ", ".join(str(tile) for tile in inked)
                + "), and the straightened map pads its corners with them")
    if not any(tiles):
        return "nothing was drawn into the banner"
    return None


def apply_map_clones(tiles: bytearray, sheet: dict, rom: Rom,
                     report: GfxReport) -> tuple[dict[str, tuple[int, int]],
                                                 list[tuple[int, int]]]:
    """Give a run of tilemap cells private copies of the tiles they name.

    A deduplicated sheet fuses whatever two labels happen to draw identically —
    two menu entries that start with the same kana end up sharing those tiles,
    and then neither can be translated without wrecking the other. Where the
    game composes the screen out of the sheet's own tilemap (see MEDAWATCH_MAP)
    the way out is to copy the shared tiles onto the end of the sheet and point
    one entry's cells at the copies: nothing changes on screen until a label
    draws over them, and the other entry keeps the originals to itself. Cloning
    the entry's whole row also makes its run contiguous, which is what lets one
    label span it.

    ``expect`` fingerprints the cells the way a language pack fingerprints a
    line: when the dump does not hold those tiles, the clone is refused rather
    than guessed at. Returns the named runs, {name: (first tile, count)}, and
    the map writes to make once the block is safely back in the ROM.
    """
    runs: dict[str, tuple[int, int]] = {}
    writes: list[tuple[int, int]] = []
    for clone in sheet.get("map_clones", []):
        name = clone.get("name", "?")
        map_at = int(str(clone["map"]), 16)
        stride = int(clone.get("stride", MEDAWATCH_MAP_STRIDE))
        row, col, count = int(clone["row"]), int(clone["col"]), int(clone["count"])
        cells = [map_at + 2 * (row * stride + col + index) for index in range(count)]
        sources = [rom.u16(cell) for cell in cells]
        expect = [int(str(tile), 16) for tile in clone.get("expect", [])]
        if expect and sources != expect:
            report.skipped.append(
                (name, f"the tilemap at {map_at:#x} row {row} column {col} holds "
                       + " ".join(hex(tile) for tile in sources)
                       + ", not the tiles this build knows"))
            continue
        fresh = bool(clone.get("fresh"))
        if not fresh and any((tile + 1) * TILE_BYTES > len(tiles) for tile in sources):
            report.skipped.append((name, "a cell names a tile past the end of the sheet"))
            continue
        base = len(tiles) // TILE_BYTES
        for index, source in enumerate(sources):
            # A run on cells that hold nothing yet (the map's spare rows) starts
            # blank; every pixel of it is painted by the labels that follow.
            tiles += (bytes(TILE_BYTES) if fresh
                      else tiles[source * TILE_BYTES:(source + 1) * TILE_BYTES])
            writes.append((cells[index], base + index))
        runs[name] = (base, count)
    return runs, writes


def _point_tiles(point: dict) -> list[int]:
    """The tiles a map_points entry names: a list, a run, or one repeated."""
    if "tiles" in point:
        return [int(str(tile), 16) for tile in point["tiles"]]
    count = int(point["count"])
    if "fill" in point:
        return [int(str(point["fill"]), 16)] * count
    first = int(str(point["from"]), 16)
    return [first + index for index in range(count)]


def apply_map_points(sheet: dict, rom: Rom, report: GfxReport) -> list[tuple[int, int]]:
    """Point tilemap cells at tiles the sheet already has.

    The way to un-share a sheet that cannot grow. A plate's chrome row is the
    same eight pixels in every column, so one chrome tile can serve a whole row
    — and the tiles that row used to spend on chrome are then free to carry
    another entry's word. Nothing is appended and nothing is drawn here: only
    the map moves, and only when the cells still hold what the pack expects.
    """
    writes: list[tuple[int, int]] = []
    for point in sheet.get("map_points", []):
        name = point.get("name", "?")
        map_at = int(str(point["map"]), 16)
        stride = int(point.get("stride", MEDAWATCH_MAP_STRIDE))
        row, col = int(point["row"]), int(point["col"])
        tiles = _point_tiles(point)
        cells = [map_at + 2 * (row * stride + col + index) for index in range(len(tiles))]
        current = [rom.u16(cell) for cell in cells]
        expect = [int(str(tile), 16) for tile in point.get("expect", [])]
        if not expect:
            report.skipped.append((name, "a map_points entry without a fingerprint"))
            continue
        if current != expect:
            report.skipped.append(
                (name, f"the tilemap at {map_at:#x} row {row} column {col} holds "
                       + " ".join(hex(tile) for tile in current)
                       + ", not the cells this build knows"))
            continue
        writes.extend(zip(cells, tiles))
    return writes


def _medawatch_sheet_problem(rom: Rom, tiles: bytes, relayout: bool) -> str | None:
    """Why the Medawatch sheet must not be written, or None."""
    grown = len(tiles) // TILE_BYTES
    if grown > MEDAWATCH_SHEET_MAX_TILES:
        return (f"the sheet grew to {grown} tiles; it is decompressed straight into "
                f"VRAM and only {MEDAWATCH_SHEET_MAX_TILES} fit before the next graphic")
    rows = tuple(rom.data[MEDAWATCH_ROWS:MEDAWATCH_ROWS + len(MEDAWATCH_ROWS_JP)])
    widths = tuple(rom.data[MEDAWATCH_WIDTHS:MEDAWATCH_WIDTHS + len(MEDAWATCH_WIDTHS_JP)])
    if rows != MEDAWATCH_ROWS_JP or widths != MEDAWATCH_WIDTHS_JP:
        return (f"the layout tables at {MEDAWATCH_ROWS:#x}/{MEDAWATCH_WIDTHS:#x} are "
                "not the ones this build knows")
    if not relayout:
        return None
    if sum(1 + width for width in MEDAWATCH_WIDTHS_ES if width) > MEDAWATCH_BAR_CELLS:
        return "the Spanish widths do not fit the bar"
    spare_at = MEDAWATCH_MAP + 2 * MEDAWATCH_MAP_ROWS * MEDAWATCH_MAP_STRIDE
    rows_used = MEDAWATCH_ROWS_ES[0] + 2 - MEDAWATCH_MAP_ROWS
    if any(rom.read(spare_at, 2 * MEDAWATCH_MAP_STRIDE * rows_used)):
        return f"the map's spare rows at {spare_at:#x} are not empty"
    return None


def apply_sheet_labels(tiles: bytearray, sheet: dict, setter: Typesetter,
                       report: GfxReport,
                       runs: dict[str, tuple[int, int]] | None = None) -> None:
    """Draw every label of one sheet spec into its decompressed tiles."""
    sheet_cols = int(sheet.get("tiles_wide", 16))
    for label in sheet.get("labels", []):
        text = label.get("text", "")
        if not text:
            continue
        rect = label.get("tile_rect")
        if rect is None:
            # The label sits on a run this sheet cloned, whose tiles only exist
            # once the clone has run, so it is named instead of numbered.
            found = (runs or {}).get(label.get("run"))
            if found is None:
                report.skipped.append(
                    (label.get("key", text), f"no cloned run named {label.get('run')!r}"))
                continue
            base, count = found
            rect = [base % sheet_cols, base // sheet_cols, count, 1]
        tx, ty, tw, th = rect
        # A rect inside a wide sheet is not contiguous tiles, so the canvas
        # walks the sheet's own stride.
        canvas = _RectCanvas(tiles, sheet_cols, tx, ty, tw, th)
        width = setter.measure(text)
        if width > canvas.width:
            # Measure before erasing: a refused label leaves the Japanese
            # pixels in place instead of a blank rectangle.
            report.skipped.append(
                (label.get("key", text),
                 f"{text!r} is {width}px, the rect is {canvas.width}px"))
            continue
        box = canvas.ink_box()
        if label.get("erase_ink") is not None:
            # Surgical erase for glyphs painted ON an art background (the
            # target-scope hanko stamps): drop only the INTERIOR pixels of
            # the ink index — those with no transparent neighbour — so the
            # stamp's rim and silhouette survive. Pair with keep_background.
            ink = int(label["erase_ink"])
            to = int(label.get("erase_to", 0))
            snap = [[canvas.get(x, y) for x in range(canvas.width)]
                    for y in range(canvas.height)]

            def _touches_outside(px: int, py: int) -> bool:
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        nx, ny = px + dx, py + dy
                        if not (0 <= nx < canvas.width and 0 <= ny < canvas.height):
                            return True
                        if snap[ny][nx] == 0:
                            return True
                return False

            for py in range(canvas.height):
                for px in range(canvas.width):
                    if snap[py][px] == ink and not _touches_outside(px, py):
                        canvas.set(px, py, to)
        elif not label.get("keep_background"):
            # "background" clears to a solid palette index instead of
            # transparent — for glyph plates on a solid colour.
            canvas.clear(int(label.get("background", 0)))
        top = label.get("top")
        if top is None:
            top = box[1] if box else (canvas.height - font_mod.GLYPH_HEIGHT) // 2
            top = max(0, min(top, canvas.height - font_mod.GLYPH_HEIGHT))
        setter.draw(canvas, (canvas.width - width) // 2, top, text,
                    int(label.get("fill", 15)), int(label.get("outline", 5)))
        report.drawn += 1


class _RectCanvas(Canvas):
    """A tile rectangle inside a wider sheet, as one pixel grid."""

    def __init__(self, tiles: bytearray, sheet_cols: int,
                 tx: int, ty: int, tw: int, th: int):
        self.tiles = tiles
        self.sheet_cols = sheet_cols
        self.tx = tx
        self.ty = ty
        self.width = tw * TILE_SIDE
        self.height = th * TILE_SIDE

    def _locate(self, x: int, y: int) -> tuple[int, int]:
        tile = ((self.ty + y // TILE_SIDE) * self.sheet_cols
                + self.tx + x // TILE_SIDE)
        offset = tile * TILE_BYTES + (y % TILE_SIDE) * 4 + (x % TILE_SIDE) // 2
        return offset, x & 1


# -- kanji glyph banks ----------------------------------------------------
#
# The Medarotch screens (parts, medal, the battle part panel) do not spell
# their kanji out of a tile sheet: they carry a small BANK of 4bpp kanji
# cells and a LOOKUP TABLE, and the screen's proportional text renderer blits
# one cell per two-byte kanji code as it draws a string. That is why a bank
# holds a handful of unrelated single kanji and why its "tilemap" decodes as
# a picture of loose glyphs: it is not a picture at all.
#
# The lookup table is 1024 u16 entries. Read as a 32-wide grid, entry
# ``code - 0xE001`` is the tile of the glyph's TOP half and the entry directly
# below it (32 further on) is its BOTTOM half — an 8x16 cell, of which the
# kanji face uses 12 rows. Every code the screen never shows points at the
# bank's one blank tile, which is why so few entries are filled.
#
# Verified on the Kuwagata dump: with this rule a bank decodes to the exact
# readings its glyphs have in data/charset-jp.tbl (撃 攻 使 症 状 全 体 力 部
# 回 数 用 敵 …), a fixed string in the ROM spells 回数 as the codes E014 E018
# that the table indexes, and a write watchpoint on the parts panel's text
# tiles catches the BIOS CpuSet that copies one cell of the bank at 0x4C7628
# into VRAM as the panel draws a status-ailment part.
#
# Two shapes exist, and which one a screen reads matters:
#   codec "raw"     the bank the parts panel really draws from — plain 4bpp
#                   tiles in the ROM followed by the plain table. Patched in
#                   place, no recompression, no relocation. Its cells carry
#                   the glyph two rows down (``inset``), leaving the leading
#                   the text renderer expects.
#   codec "lz77"    a compressed twin (0x646AC0 + 0x646CB0) reached through
#                   the asset tables. Same format once unpacked.
#
# A word is translated by REPAINTING the cells its kanji point at: N codes
# side by side give an 8*N x 16 plate, which takes two stacked lines of two
# capitals the way the parts sheet's four-letter abbreviations do. A word may
# instead ask for ``new_cells``: the bank then grows by two tiles per code and
# the lookup table is repointed at them, which is what a word needs when its
# kanji must keep their old glyphs somewhere else. A raw bank cannot grow —
# its table sits immediately after the last tile — so it refuses that.
#
# The danger this mechanism has to be kept away from: a code is repainted
# EVERYWHERE the screens using that bank draw it. Only put a word here when
# its kanji occur in no other word on those screens — 攻撃 and 症状 qualify
# (every single occurrence in the parts text pool is the pair), 全 does not
# (全体, 全パーツ, 全て).

#: The code the lookup table's first entry stands for.
BANK_FIRST_CODE = 0xE001
#: The table is read as a grid this wide; a glyph's bottom half is one row down.
BANK_LUT_WIDTH = 32
#: A glyph cell: a top tile and a bottom tile, 8x16 pixels together.
BANK_CELL_HEIGHT = 2 * TILE_SIDE


class _CellCanvas(Canvas):
    """A row of glyph cells — wherever they sit in the bank — as one grid."""

    def __init__(self, tiles: bytearray, cells: list[tuple[int, int]]):
        self.tiles = tiles
        self.cells = cells
        self.width = len(cells) * TILE_SIDE
        self.height = BANK_CELL_HEIGHT

    def _locate(self, x: int, y: int) -> tuple[int, int]:
        top, bottom = self.cells[x // TILE_SIDE]
        tile = top if y < TILE_SIDE else bottom
        offset = tile * TILE_BYTES + (y % TILE_SIDE) * 4 + (x % TILE_SIDE) // 2
        return offset, x & 1


def bank_lut(raw: bytes) -> list[int]:
    return [raw[i] | raw[i + 1] << 8 for i in range(0, len(raw), 2)]


def bank_lut_bytes(lut: list[int]) -> bytes:
    out = bytearray()
    for entry in lut:
        out += bytes([entry & 0xFF, entry >> 8])
    return bytes(out)


def load_bank(data: bytes, bank: dict) -> tuple[bytearray, list[int]]:
    """The bank's tiles and lookup table, whichever shape it is stored in."""
    codec = bank.get("codec", "lz77")
    tiles_at = int(str(bank["tiles"]), 16)
    lut_at = int(str(bank["lut"]), 16)
    if codec == "raw":
        count = int(bank.get("tile_count", (lut_at - tiles_at) // TILE_BYTES))
        entries = int(bank.get("lut_entries", 1024))
        return (bytearray(data[tiles_at:tiles_at + count * TILE_BYTES]),
                bank_lut(data[lut_at:lut_at + 2 * entries]))
    dec, _ = CODECS[codec]
    return bytearray(dec(data, tiles_at)[0]), bank_lut(dec(data, lut_at)[0])


def bank_cell(lut: list[int], code: int) -> tuple[int, int]:
    """The (top tile, bottom tile) one kanji code draws."""
    index = code - BANK_FIRST_CODE
    if not 0 <= index < len(lut) - BANK_LUT_WIDTH:
        raise GfxError(f"code {code:#06x} is outside the bank's lookup table")
    return lut[index], lut[index + BANK_LUT_WIDTH]


def apply_bank_words(tiles: bytearray, lut: list[int], bank: dict,
                     setter: Typesetter, report: GfxReport) -> bool:
    """Draw every word of one bank spec. Returns whether the table changed."""
    lut_changed = False
    fixed_size = bank.get("codec", "lz77") == "raw"
    for word in bank.get("words", []):
        key = word.get("key", "".join(str(c) for c in word.get("codes", [])))
        lines = [line for line in (word.get("lines") or [word.get("text", "")]) if line]
        if not lines:
            continue
        try:
            codes = [int(str(code), 16) for code in word["codes"]]
            cells = [bank_cell(lut, code) for code in codes]
        except (GfxError, KeyError, ValueError) as exc:
            report.skipped.append((key, str(exc)))
            continue
        if word.get("new_cells") and fixed_size:
            report.skipped.append(
                (key, "new_cells needs a bank that can grow; this one is raw, "
                      "its table sits right after the last tile"))
            continue
        if word.get("new_cells"):
            base = len(tiles) // TILE_BYTES
            tiles += bytes(len(codes) * 2 * TILE_BYTES)
            cells = [(base + 2 * i, base + 2 * i + 1) for i in range(len(codes))]
            for code, (top, bottom) in zip(codes, cells):
                index = code - BANK_FIRST_CODE
                lut[index] = top
                lut[index + BANK_LUT_WIDTH] = bottom
            lut_changed = True
        canvas = _CellCanvas(tiles, cells)
        widths = [setter.measure(line) for line in lines]
        if max(widths) > canvas.width:
            report.skipped.append(
                (key, f"{lines[widths.index(max(widths))]!r} is {max(widths)}px, "
                      f"the {len(codes)} kanji it replaces are {canvas.width}px"))
            continue
        fill = int(word.get("fill", 15))
        outline = word.get("outline", 5)
        tops = word.get("tops") or [0, TILE_SIDE][:len(lines)]
        if len(tops) != len(lines):
            report.skipped.append((key, f"{len(lines)} lines but {len(tops)} tops"))
            continue
        canvas.clear()
        for line, width, top in zip(lines, widths, tops):
            setter.draw(canvas, (canvas.width - width) // 2, int(top), line, fill, None)
        if outline is not None:
            setter.outline_pass(canvas, fill, int(outline))
        report.drawn += 1
    return lut_changed


def patch_glyph_banks(rom: Rom, charset: Charset, banks: list[dict], allocator,
                      pointer_sites: dict[int, list[int]],
                      font_data: bytes | None = None) -> GfxReport:
    """Repaint the kanji cells the language pack names, in every bank."""
    report = GfxReport()
    setter = Typesetter(rom, charset, font_data)
    data = bytes(rom.data)

    for bank in banks:
        name = bank.get("name", str(bank.get("tiles")))
        codec = bank.get("codec", "lz77")
        tiles_at = int(str(bank["tiles"]), 16)
        lut_at = int(str(bank["lut"]), 16)
        try:
            tiles, lut = load_bank(data, bank)
            if codec != "raw":
                dec, enc = CODECS[codec]
                tiles_len = dec(data, tiles_at)[1]
                lut_len = dec(data, lut_at)[1]
        except (GfxError, KeyError) as exc:
            report.skipped.append((name, str(exc)))
            continue
        before = bytes(tiles)

        lut_changed = apply_bank_words(tiles, lut, bank, setter, report)
        if bytes(tiles) == before and not lut_changed:
            continue

        if codec == "raw":
            rom.write(tiles_at, bytes(tiles))
            report.in_place += 1
            if lut_changed:
                rom.write(lut_at, bank_lut_bytes(lut))
            continue
        _put_back(rom, tiles_at, enc(bytes(tiles)), tiles_len,
                  allocator, pointer_sites, report, name + " bank")
        if lut_changed:
            _put_back(rom, lut_at, enc(bank_lut_bytes(lut)), lut_len,
                      allocator, pointer_sites, report, name + " table")
    return report


def _put_back(rom: Rom, block: int, packed: bytes, room: int, allocator,
              pointer_sites: dict[int, list[int]], report: GfxReport,
              name: str) -> None:
    """Write a recompressed block where it was, or somewhere it fits."""
    if len(packed) <= room:
        rom.write(block, packed)
        report.in_place += 1
        return
    sites = pointer_sites.get(block, [])
    if not sites:
        report.skipped.append((name, "grew, and nothing points at it"))
        return
    destination = allocator.take(len(packed))
    rom.write(destination, packed)
    for site in sites:
        rom.write_ptr(site, destination)
    report.relocated += 1


# -- the opening newspaper (8bpp) -----------------------------------------
#
# The page the game shows after the space Medabot is dug up is ONE 8bpp
# image, not a tile atlas: 600 tiles of 64 bytes in 1-D order, 30x20, with
# its own uncompressed 256-colour palette right before the block.  Every
# other asset in this game is 4bpp, so it needs its own canvas and its own
# writer.  The Japanese text is TATEGAKI (vertical columns read right to
# left); Spanish cannot be stacked that way, so the column texts are drawn
# ROTATED 90° clockwise — the same thing a real newspaper does with Latin
# text in a vertical column — while the two photo captions stay horizontal.
NEWSPAPER_BLOCK = 0x78BDA8
NEWSPAPER_PALETTE = 0x78BCA8
NEWSPAPER_COLS = 30
NEWSPAPER_ROWS = 20


class Canvas8:
    """The 8bpp page as one pixel grid (1-D tile order, 30 tiles wide)."""

    def __init__(self, tiles: bytearray, cols: int = NEWSPAPER_COLS):
        self.tiles = tiles
        self.cols = cols
        self.width = cols * TILE_SIDE
        self.height = (len(tiles) // 64) // cols * TILE_SIDE

    def _at(self, x: int, y: int) -> int:
        tile = (y // TILE_SIDE) * self.cols + (x // TILE_SIDE)
        return tile * 64 + (y % TILE_SIDE) * TILE_SIDE + (x % TILE_SIDE)

    def get(self, x: int, y: int) -> int:
        if not (0 <= x < self.width and 0 <= y < self.height):
            return 0
        return self.tiles[self._at(x, y)]

    def set(self, x: int, y: int, value: int) -> None:
        if 0 <= x < self.width and 0 <= y < self.height:
            self.tiles[self._at(x, y)] = value

    def fill_rect(self, x: int, y: int, w: int, h: int, value: int) -> None:
        for py in range(y, y + h):
            for px in range(x, x + w):
                self.set(px, py, value)

    def sample_rect(self, x: int, y: int, w: int, h: int) -> int:
        """The most common value in a rectangle — its background colour."""
        from collections import Counter

        counter = Counter(self.get(px, py)
                          for py in range(y, y + h) for px in range(x, x + w))
        return counter.most_common(1)[0][0]


def _draw8(setter: "Typesetter", canvas: Canvas8, x: int, y: int, text: str,
           ink: int, spacing: int = 1) -> None:
    """Horizontal text, one palette index, no outline."""
    pen = x
    for char in text:
        grid, left, width = setter._glyph(char)
        if width == 0:
            pen += 3 + spacing
            continue
        for gy in range(font_mod.GLYPH_HEIGHT):
            for gx in range(width):
                if grid[gy][left + gx]:
                    canvas.set(pen + gx, y + gy, ink)
        pen += width + spacing


def _draw8_rotated(setter: "Typesetter", canvas: Canvas8, x: int, y: int,
                   text: str, ink: int, spacing: int = 1) -> None:
    """Text rotated 90° clockwise, reading downward from (x, y).

    ``x`` is the LEFT edge of the resulting column, which is
    ``GLYPH_HEIGHT`` pixels wide; the glyph's own top ends up on the right.
    """
    pen = y
    for char in text:
        grid, left, width = setter._glyph(char)
        if width == 0:
            pen += 3 + spacing
            continue
        for gy in range(font_mod.GLYPH_HEIGHT):
            for gx in range(width):
                if grid[gy][left + gx]:
                    canvas.set(x + (font_mod.GLYPH_HEIGHT - 1 - gy), pen + gx, ink)
        pen += width + spacing


#: The page's regions, in PIXELS, measured off the rendered block.
#: ``rot`` columns are drawn top-down with the letters turned clockwise;
#: the rest are ordinary horizontal captions.
NEWSPAPER_AREAS = {
    # key            x,   y,   w,   h,  rotated
    "head.a":      (216,   6,   9, 148, True),
    "head.b":      (226,   6,   9, 148, True),
    "sub":         (190,  48,   9, 105, True),
    "left.a":      ( 72,  72,   9,  86, True),
    "left.b":      ( 58,  96,   9,  62, True),
    "photo":       ( 82, 100, 118,  20, False),
    "boy":         (  4, 138,  62,  20, False),
}


def patch_newspaper(rom: Rom, setter: "Typesetter", texts: dict,
                    allocator, pointer_sites: dict, report: "GfxReport") -> None:
    """Redraw the opening newspaper page (8bpp, vertical Japanese)."""
    if not texts:
        return
    original = bytes(rom.data)
    try:
        raw, comp_len = decompress(original, NEWSPAPER_BLOCK)
    except GfxError as exc:
        report.skipped.append(("newspaper", str(exc)))
        return
    page = bytearray(raw)
    canvas = Canvas8(page)
    for key, lines in texts.items():
        area = NEWSPAPER_AREAS.get(key)
        if area is None or not lines:
            report.skipped.append((f"newspaper:{key}", "no such area"))
            continue
        x, y, w, h, rotated = area
        # Erase to the paper colour the area already sits on, then draw with
        # the ink sampled from its darkest pixel — the dark headline box and
        # the cream page need opposite inks and the sample gets both right.
        background = canvas.sample_rect(x, y, w, h)
        # Pick the ink by LUMINANCE, not by index: the palette is in no
        # particular order, so the lowest index is not the darkest colour
        # (drawing with it left the captions nearly invisible).
        def _lum(index: int) -> int:
            colour = struct.unpack_from("<H", original, NEWSPAPER_PALETTE + 2 * index)[0]
            return ((colour & 31) * 299 + ((colour >> 5) & 31) * 587
                    + ((colour >> 10) & 31) * 114) // 1000

        present = {canvas.get(px, py)
                   for py in range(y, y + h) for px in range(x, x + w)}
        ink = max(present, key=lambda i: abs(_lum(i) - _lum(background)))
        if ink == background:
            ink = min(present, key=_lum)
        canvas.fill_rect(x, y, w, h, background)
        for index, line in enumerate(lines if isinstance(lines, list) else [lines]):
            if rotated:
                span = setter.measure(line)
                if span > h:
                    report.skipped.append(
                        (f"newspaper:{key}", f"{line!r} is {span}px, the column is {h}px"))
                    continue
                _draw8_rotated(setter, canvas, x, y, line, ink)
            else:
                span = setter.measure(line)
                if span > w:
                    report.skipped.append(
                        (f"newspaper:{key}", f"{line!r} is {span}px, the caption is {w}px"))
                    continue
                _draw8(setter, canvas, x, y + index * (font_mod.GLYPH_HEIGHT + 1),
                       line, ink)
        report.drawn += 1
    packed = compress(bytes(page))
    if len(packed) <= comp_len:
        rom.write(NEWSPAPER_BLOCK, packed)
        report.in_place += 1
        return
    sites = pointer_sites.get(NEWSPAPER_BLOCK, [])
    if not sites:
        report.skipped.append(("newspaper", "grew, and nothing points at it"))
        return
    destination = allocator.take(len(packed))
    rom.write(destination, packed)
    for site in sites:
        rom.write_ptr(site, destination)
    report.relocated += 1


# -- the save panel's counters (labels drawn from a flat ROM tile list) ---
#
# The Medawatch save panel names its counters with 8x16 kanji cells whose
# TILEMAP is a flat list of 16-bit tile indices in ROM at 0x7F34B0: sixteen
# top-row cells followed by sixteen bottom-row cells, feeding four labels
# (medals / parts / allies / wins-over-battles).  The renderer copies from
# that list into an IWRAM map buffer, so nothing here is reachable by the
# ordinary "sheets" machinery — found with a write watchpoint on the buffer
# (pc 0x0807CCF2 carries the list pointer in r2).
#
# Two cells share a tile in the original (the third of "medals" is also the
# seventh of "wins"), which is why an earlier attempt at repainting turned
# the panel into black boxes.  The list is ours to rewrite, so the fix is to
# hand every cell its OWN tile first and then paint: the sheet's 29 label
# tiles are used by nothing else in the ROM.
SAVE_PANEL_SHEET = 0x7F2190
SAVE_PANEL_MAP = 0x7F34B0
SAVE_PANEL_BLANK = 0x62

#: (label, top tiles, bottom tiles, line 1, line 2) — the tile numbers are
#: the sheet indices this build assigns to each cell, replacing the original
#: sharing.  Each line is drawn across its row of 8px cells.
SAVE_PANEL_LABELS = (
    # Each cell keeps the tile it already owned on screen — reordering them
    # made letters surface in other rows. The wins label's third cell is
    # drawn twice by the game (the counter row reuses that map entry), so it
    # stays blank and the word sits in the cells after it. Bottom halves are
    # blanked: the Spanish is one 8px line, not a 16px kanji.
    ("medals", (0xC3, 0xC4, 0xC5), (0xD1, 0xD2, 0xD3), "Med.", ""),
    ("parts",  (0xC6, 0xC7, 0xC8), (0xD4, 0xD5, 0xD6), "Par.", ""),
    ("allies", (0xC9, 0xD7),       (0xD8, 0xDA),       "Am.", ""),
    ("wins.gap", (0xCA, 0xCB, 0xCC), (0xDD, 0xDE, 0xDF), "", ""),
    ("wins",   (0xCE, 0xCF, 0xD0, 0xDB, 0xDC), (None,), "Victor.", ""),
    # 時間 over the clock: two exclusive cells, so the word stacks in the
    # 16px height the kanji used.
    # 時間 here is PLAY TIME, not the clock: the counter advanced a minute
    # after 90 seconds of emulated play, and it reads 01:11 rather than the
    # wall clock. Two cells fit two characters a line, so it stacks as an
    # abbreviation, uppercase like the part-type plates.
    ("time",   (0xE0, 0xE1), (0xEF, 0xF0), "TI", "EM"),
)


#: The panel's plate colour is index 4 (its blank tile is solid 4) and the
#: kanji ink is 1, with 3 as their shadow.
SAVE_PANEL_PAPER = 4


def patch_save_panel(rom: Rom, setter: "Typesetter", allocator,
                     pointer_sites: dict, report: "GfxReport",
                     fill: int = 1, outline: int = 1) -> None:
    """Redraw the save panel's four counter labels, map and all."""
    original = bytes(rom.data)
    try:
        raw, comp_len = decompress(original, SAVE_PANEL_SHEET)
    except GfxError as exc:
        report.skipped.append(("save-panel", str(exc)))
        return
    tiles = bytearray(raw)
    cells: list[int] = []
    for name, top, bottom, line1, line2 in SAVE_PANEL_LABELS:
        for row, line in ((top, line1), (bottom, line2)):
            used = [t for t in row if t is not None]
            if not used:
                continue
            if not line:
                for tile in used:
                    blank = bytearray(TILE_BYTES)
                    canvas = Canvas(blank, 1, 1)
                    canvas.clear(SAVE_PANEL_PAPER)
                    tiles[tile * TILE_BYTES:(tile + 1) * TILE_BYTES] = blank
                continue
            width = len(used) * TILE_SIDE
            span = setter.measure(line)
            if span > width:
                report.skipped.append(
                    (f"save-panel:{name}",
                     f"{line!r} is {span}px, the row is {width}px"))
                return
            # One canvas per row: the cells are consecutive in the map, so
            # lay the tiles out side by side in a scratch strip and copy back.
            strip = bytearray(len(used) * TILE_BYTES)
            canvas = Canvas(strip, len(used), 1)
            canvas.clear(SAVE_PANEL_PAPER)
            setter.draw(canvas, (width - span) // 2, 0, line, fill, outline)
            for index, tile in enumerate(used):
                tiles[tile * TILE_BYTES:(tile + 1) * TILE_BYTES] = \
                    strip[index * TILE_BYTES:(index + 1) * TILE_BYTES]
    # Rewrite the map so every cell owns its tile (no sharing left).
    order: list[int] = []
    for name, top, _, _, _ in SAVE_PANEL_LABELS:
        if name == "time":
            continue
        order += [t if t is not None else SAVE_PANEL_BLANK for t in top]
    order = (order + [SAVE_PANEL_BLANK] * 16)[:16]  # la fila del reloj vive
    # más allá de la entrada 32 y conserva su asignación original
    bottoms: list[int] = []
    for name, _, bottom, _, _ in SAVE_PANEL_LABELS:
        if name == "time":
            continue
        bottoms += [t if t is not None else SAVE_PANEL_BLANK for t in bottom]
    bottoms = (bottoms + [SAVE_PANEL_BLANK] * 16)[:16]
    for index, tile in enumerate(order + bottoms):
        rom.write(SAVE_PANEL_MAP + 2 * index, bytes([tile & 0xFF, tile >> 8]))
    packed = compress(bytes(tiles))
    if len(packed) <= comp_len:
        rom.write(SAVE_PANEL_SHEET, packed)
        report.in_place += 1
    else:
        sites = pointer_sites.get(SAVE_PANEL_SHEET, [])
        if not sites:
            report.skipped.append(("save-panel", "grew, and nothing points at it"))
            return
        destination = allocator.take(len(packed))
        rom.write(destination, packed)
        for site in sites:
            rom.write_ptr(site, destination)
        report.relocated += 1
    report.drawn += len(SAVE_PANEL_LABELS)
