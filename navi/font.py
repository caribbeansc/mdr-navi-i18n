"""Teaching the cartridge's font the letters Spanish needs.

The game draws ordinary characters from a 1bpp font of 9 rows per glyph, eight
pixels wide, indexed straight by the character's code. It has capitals, digits
and punctuation; it has no lower case and no accents, and the Latin glyphs it
does have sit one pixel lower than a lower-case baseline wants.

So the build does two things. It raises every Latin glyph by one pixel, which
frees the bottom row for descenders and gives the whole alphabet one baseline.
Then it writes our own glyphs into the kana codes the cartridge uses least —
navi/slots.py picks them by counting — so that the Japanese nobody has
translated yet keeps drawing almost entirely intact.

Nothing here patches code. The font is data, and the game reads it where it
always did.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .rom import Rom
from .table import Charset

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

GLYPH_HEIGHT = 9
GLYPH_WIDTH = 8
GLYPH_BYTES = GLYPH_HEIGHT
#: The font covers every single-byte code below the kanji lead bytes.
GLYPH_COUNT = 0xE0

#: Ink is a zero bit; the conversion table the game uses inverts as it expands.
BLANK_ROW = 0xFF
BLANK_GLYPH = bytes([BLANK_ROW] * GLYPH_HEIGHT)

#: The block the cartridge fills with Latin letters, digits, punctuation and
#: symbols. All of it sits one pixel lower than a lower-case baseline wants, so
#: the build raises the whole block together and leaves the drawing alone.
NATIVE_LATIN = tuple(range(0x9E, 0xE0))

#: Built by turning the cartridge's own glyph upside down, so the style matches.
ROTATED = {"¿": 0xB8, "¡": 0xB9}


class FontError(Exception):
    pass


@dataclass
class Glyph:
    name: str
    rows: list[int]

    def to_bytes(self) -> bytes:
        return bytes(self.rows)

    def ascii_art(self) -> str:
        out = []
        for row in self.rows:
            out.append("".join("#" if not row & (0x80 >> x) else "." for x in range(GLYPH_WIDTH)))
        return "\n".join(out)


def read_glyphs(path: str | Path | None = None) -> dict[str, Glyph]:
    """Load data/glyphs-latin.txt into ``character -> Glyph``."""
    path = Path(path) if path else DATA_DIR / "glyphs-latin.txt"
    glyphs: dict[str, Glyph] = {}
    name: str | None = None
    rows: list[int] = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.rstrip()
        if not line:
            continue
        if name is None:
            # Between glyphs, a leading '#' is a comment. Inside one it is ink,
            # which is why this test only runs out here.
            if line.lstrip().startswith("#"):
                continue
            name = line.strip()
            rows = []
            continue
        if len(line) < GLYPH_WIDTH:
            line = line.ljust(GLYPH_WIDTH, ".")
        value = 0
        for x in range(GLYPH_WIDTH):
            # A zero bit is ink, so start from all ones and clear where drawn.
            if line[x] != "#":
                value |= 0x80 >> x
        rows.append(value)
        if len(rows) == GLYPH_HEIGHT:
            if name in glyphs:
                raise FontError(f"{path}:{number}: {name!r} is defined twice")
            glyphs[name] = Glyph(name=name, rows=rows)
            name = None
    if name is not None:
        raise FontError(f"{path}: {name!r} has {len(rows)} rows, expected {GLYPH_HEIGHT}")
    return glyphs


def read_font(rom: Rom) -> list[bytes]:
    """The cartridge's own font, one entry per code."""
    base = rom.release.font
    return [rom.read(base + i * GLYPH_BYTES, GLYPH_BYTES) for i in range(GLYPH_COUNT)]


def raise_glyph(glyph: bytes) -> bytes:
    """Move a glyph up one pixel, blanking the row it leaves behind."""
    return glyph[1:] + bytes([BLANK_ROW])


def _left_margin(rows: list[int] | bytes) -> int:
    """Leftmost inked column, remembering that ink is a ZERO bit."""
    columns = [
        x
        for row in rows
        for x in range(GLYPH_WIDTH)
        if not row & (0x80 >> x)
    ]
    return min(columns) if columns else GLYPH_WIDTH


def rotate_glyph(glyph: bytes) -> bytes:
    """Turn a glyph 180 degrees: '?' becomes '¿'.

    Reversing rows and bits leaves the drawing with the ORIGINAL's right
    margin on its left, so it is slid back until its left margin matches the
    original's — a '?' inked in columns 2-5 yields a '¿' inked in columns 2-5.
    """
    rotated = []
    for row in reversed(glyph):
        value = 0
        for x in range(GLYPH_WIDTH):
            if row & (0x80 >> x):
                value |= 1 << x
        rotated.append(value)
    shift = _left_margin(rotated) - _left_margin(glyph)
    if shift > 0:  # slide left, background (ones) filling in from the right
        rotated = [((r << shift) & 0xFF) | ((1 << shift) - 1) for r in rotated]
    elif shift < 0:  # slide right, background filling in from the left
        s = -shift
        rotated = [(r >> s) | (~(0xFF >> s) & 0xFF) for r in rotated]
    return bytes(rotated)


def build_font(rom: Rom, charset: Charset, glyphs: dict[str, Glyph] | None = None
               ) -> tuple[bytes, dict[str, int]]:
    """Return the patched font and the codes each new character landed on.

    ``charset`` is the Latin table: it decides which code every character is
    written as, so the font and the encoder cannot drift apart.
    """
    glyphs = read_glyphs() if glyphs is None else glyphs
    font = read_font(rom)

    # One baseline for the whole alphabet.
    for code in NATIVE_LATIN:
        font[code] = raise_glyph(font[code])

    # Where each character's native (raised) glyph lives, for the keyboard
    # alias codes that duplicate capitals and punctuation onto kana slots.
    native_of: dict[str, int] = {}
    for code, char in charset.decode.items():
        if code in NATIVE_LATIN and len(char) == 1:
            native_of.setdefault(char, code)

    placed: dict[str, int] = {}
    for code, char in sorted(charset.decode.items()):
        if code >= GLYPH_COUNT or len(char) != 1:
            continue
        if code in NATIVE_LATIN or char == " ":
            continue
        if char in ROTATED:
            font[code] = rotate_glyph(read_font(rom)[ROTATED[char]])
            placed[char] = code
            continue
        glyph = glyphs.get(char)
        if glyph is not None:
            font[code] = glyph.to_bytes()
            placed[char] = code
            continue
        source = native_of.get(char)
        if source is not None:
            font[code] = font[source]  # already raised above
            placed[char] = code
            continue
        raise FontError(
            f"The Latin charset maps {char!r} to {code:#04x} but "
            f"data/glyphs-latin.txt has no glyph for it"
        )

    # Every kana code we did not take over keeps its glyph: the lines nobody
    # has translated yet still draw from this font, and they stay readable
    # only if the kana are still there.

    return b"".join(font), placed


def apply(rom: Rom, charset: Charset) -> dict[str, int]:
    """Write the patched font into the ROM. Returns the new characters."""
    data, placed = build_font(rom, charset)
    rom.write(rom.release.font, data)
    return placed


def preview(rom: Rom, charset: Charset, codes: list[int] | None = None) -> str:
    """Render glyphs as text, for eyeballing a change without an emulator."""
    data, _ = build_font(rom, charset)
    codes = codes or sorted({c for c in charset.encode.values() if c < GLYPH_COUNT})
    out = []
    for code in codes:
        char = charset.decode.get(code, "?")
        glyph = Glyph(name=char, rows=list(data[code * GLYPH_BYTES:(code + 1) * GLYPH_BYTES]))
        out.append(f"{char} ({code:#04x})\n{glyph.ascii_art()}")
    return "\n\n".join(out)


# -- the name-entry keyboard's own font ----------------------------------
#
# The name screen does not draw from the dialogue font. It has a second font
# at KEYBOARD_FONT: 224 glyphs of 22 bytes — 11 rows, each row two bytes,
# each byte an index into the pattern table at KEYBOARD_LUT whose u16 entries
# expand to four 4bpp pixels (background 0, baked outline 5, fill 15). Found
# by watchpointing the VRAM write of a grid tile; the two code literals that
# name these tables are at KEYBOARD_LITERALS.

KEYBOARD_LUT = 0x659E80
KEYBOARD_LUT_ENTRIES = 28
KEYBOARD_FONT = 0x659EB8
KEYBOARD_GLYPHS = 224
KEYBOARD_ROWS = 11
#: File offsets of the code literals pointing at (font, lut).
KEYBOARD_LITERALS = (0x4C01C, 0x4C020)

FILL = 15
OUTLINE = 5


def _kb_decode(rom: Rom) -> tuple[list[int], list[list[list[int]]]]:
    """The keyboard font as pixel grids, plus its pattern table."""
    import struct

    lut = [struct.unpack_from("<H", rom.data, KEYBOARD_LUT + 2 * i)[0]
           for i in range(KEYBOARD_LUT_ENTRIES)]
    glyphs = []
    for code in range(KEYBOARD_GLYPHS):
        base = KEYBOARD_FONT + 22 * code
        rows = []
        for r in range(KEYBOARD_ROWS):
            pixels = []
            for b in rom.data[base + r * 2: base + r * 2 + 2]:
                half = lut[b] if b < len(lut) else 0
                for k in range(4):
                    pixels.append((half >> (4 * k)) & 0xF)
            rows.append(pixels)
        glyphs.append(rows)
    return lut, glyphs


def _kb_outline(rows: list[list[int]]) -> None:
    """Bake the 8-neighbour outline the native glyphs carry."""
    height, width = len(rows), len(rows[0])
    for y in range(height):
        for x in range(width):
            if rows[y][x] != 0:
                continue
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < height and 0 <= nx < width and rows[ny][nx] == FILL:
                        rows[y][x] = OUTLINE
                        break
                else:
                    continue
                break


def build_keyboard_font(rom: Rom, charset: Charset,
                        glyphs: dict[str, Glyph] | None = None
                        ) -> tuple[bytes, bytes]:
    """The keyboard font with our Latin glyphs drawn in, plus its (possibly
    grown) pattern table. Returns ``(lut_bytes, font_bytes)``.

    Codes the charset does not claim keep their pixels bit-for-bit; claimed
    codes get the same drawing the dialogue box shows, with the outline the
    native glyphs carry.
    """
    import struct

    glyphs = read_glyphs() if glyphs is None else glyphs
    lut, grids = _kb_decode(rom)
    dialogue = read_font(rom)

    native_of: dict[str, int] = {}
    for code, char in charset.decode.items():
        if code in NATIVE_LATIN and len(char) == 1:
            native_of.setdefault(char, code)

    for code, char in sorted(charset.decode.items()):
        if code >= KEYBOARD_GLYPHS or len(char) != 1 or char == " ":
            continue
        if code in NATIVE_LATIN:
            continue  # already Latin in this font
        if char in ROTATED:
            source = rotate_glyph(dialogue[ROTATED[char]])
        elif char in glyphs:
            source = glyphs[char].to_bytes()
        elif char in native_of:
            # Copy the keyboard font's own native glyph, pixel for pixel.
            grids[code] = [row[:] for row in grids[native_of[char]]]
            continue
        else:
            continue
        rows = [[0] * 8 for _ in range(KEYBOARD_ROWS)]
        for gy in range(GLYPH_HEIGHT):
            for gx in range(8):
                if not source[gy] & (0x80 >> gx):
                    rows[gy + 1][gx] = FILL
        _kb_outline(rows)
        grids[code] = rows

    # Re-encode every glyph, growing the pattern table for new pixel groups.
    patterns: dict[int, int] = {value: i for i, value in enumerate(lut)}
    out = bytearray()
    for rows in grids:
        for r in range(KEYBOARD_ROWS):
            for half in range(2):
                value = 0
                for k in range(4):
                    value |= rows[r][half * 4 + k] << (4 * k)
                index = patterns.get(value)
                if index is None:
                    index = len(lut)
                    if index > 0xFF:
                        raise FontError("Keyboard pattern table overflow")
                    lut.append(value)
                    patterns[value] = index
                out.append(index)
    lut_bytes = b"".join(struct.pack("<H", value) for value in lut)
    return lut_bytes, bytes(out)
