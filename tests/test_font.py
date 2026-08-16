"""Tests for navi/font.py: glyph parsing, raising, rotating, building.

No ROM is needed: build_font is exercised through a monkeypatched read_font
returning a synthetic base font.
"""

import pytest

import navi.font as font_mod
from navi.font import (
    BLANK_GLYPH,
    BLANK_ROW,
    GLYPH_BYTES,
    GLYPH_COUNT,
    GLYPH_HEIGHT,
    GLYPH_WIDTH,
    NATIVE_LATIN,
    ROTATED,
    FontError,
    Glyph,
    build_font,
    raise_glyph,
    read_glyphs,
    rotate_glyph,
)
from navi.table import Charset


def art_to_rows(art: list[str]) -> list[int]:
    """'#' is ink, ink is a zero bit; short rows pad with background."""
    rows = []
    for line in art:
        value = 0
        for x in range(GLYPH_WIDTH):
            if x >= len(line) or line[x] != "#":
                value |= 0x80 >> x
        rows.append(value)
    return rows


def art_to_bytes(art: list[str]) -> bytes:
    return bytes(art_to_rows(art))


# -- read_glyphs ---------------------------------------------------------

GLYPHS_TXT = """\
# A comment before any glyph is skipped.
# So is this one.

a
........
..###...
.#...#..
.#####..
.#......
.#...#..
..###...
........
........

# A comment between glyphs is skipped too.
!
###.....
###.....
###.....
###.....
###.....
........
###.....
........
........

i
........
##
........
........
........
........
........
........
........
"""


@pytest.fixture
def glyph_file(tmp_path):
    path = tmp_path / "glyphs.txt"
    path.write_text(GLYPHS_TXT, encoding="utf-8")
    return path


def test_read_glyphs_parses_all_glyphs(glyph_file):
    glyphs = read_glyphs(glyph_file)
    assert set(glyphs) == {"a", "!", "i"}
    assert all(len(g.rows) == GLYPH_HEIGHT for g in glyphs.values())


def test_read_glyphs_hash_inside_glyph_is_ink_not_comment(glyph_file):
    # Every row of '!' starts with '#'; those are ink rows, not comments.
    bang = read_glyphs(glyph_file)["!"]
    assert bang.rows == [0x1F] * 5 + [0xFF, 0x1F, 0xFF, 0xFF]


def test_read_glyphs_ink_is_zero_bit(glyph_file):
    a = read_glyphs(glyph_file)["a"]
    assert a.rows[0] == 0xFF  # blank row: all background bits set
    assert a.rows == art_to_rows(
        [
            "........",
            "..###...",
            ".#...#..",
            ".#####..",
            ".#......",
            ".#...#..",
            "..###...",
            "........",
            "........",
        ]
    )


def test_read_glyphs_pads_short_rows(glyph_file):
    i = read_glyphs(glyph_file)["i"]
    assert i.rows[1] == 0x3F  # "##" -> ink in columns 0-1, background after


def test_read_glyphs_wrong_row_count_raises(tmp_path):
    path = tmp_path / "short.txt"
    path.write_text("x\n########\n########\n########\n", encoding="utf-8")
    with pytest.raises(FontError, match="has 3 rows"):
        read_glyphs(path)


def test_read_glyphs_duplicate_raises(tmp_path):
    body = "z\n" + "########\n" * 9
    path = tmp_path / "dupe.txt"
    path.write_text(body + body, encoding="utf-8")
    with pytest.raises(FontError, match="defined twice"):
        read_glyphs(path)


# -- raise_glyph ---------------------------------------------------------


def test_raise_glyph_moves_ink_up_and_blanks_last_row():
    glyph = bytes(range(1, GLYPH_HEIGHT + 1))
    raised = raise_glyph(glyph)
    assert raised == bytes(range(2, GLYPH_HEIGHT + 1)) + bytes([BLANK_ROW])
    assert len(raised) == GLYPH_HEIGHT


# -- rotate_glyph --------------------------------------------------------

QMARK_ART = [
    "..####..",
    "..#..#..",
    ".....#..",
    "....##..",
    "...##...",
    "...#....",
    "........",
    "...#....",
    "........",
]

# The same drawing turned 180 degrees, still starting at column 2.
IQMARK_ART = [
    "........",
    "....#...",
    "........",
    "....#...",
    "...##...",
    "..##....",
    "..#.....",
    "..#..#..",
    "..####..",
]


def leftmost_ink_column(glyph: bytes) -> int:
    return min(
        x
        for row in glyph
        for x in range(GLYPH_WIDTH)
        if not row & (0x80 >> x)
    )


def test_rotate_glyph_turns_question_mark_upside_down():
    assert rotate_glyph(art_to_bytes(QMARK_ART)) == art_to_bytes(IQMARK_ART)


def test_rotate_glyph_keeps_left_margin():
    qmark = art_to_bytes(QMARK_ART)
    assert leftmost_ink_column(rotate_glyph(qmark)) == leftmost_ink_column(qmark)


# -- build_font ----------------------------------------------------------


def base_glyph(code: int) -> bytes:
    if code == ROTATED["¿"]:
        return art_to_bytes(QMARK_ART)
    return bytes([code] * GLYPH_HEIGHT)


@pytest.fixture
def built(monkeypatch):
    monkeypatch.setattr(
        font_mod, "read_font", lambda rom: [base_glyph(c) for c in range(GLYPH_COUNT)]
    )
    charset = Charset(name="latin-test")
    for char, code in {
        "a": 0x13,       # our own glyph, drawn into a kana slot
        "¿": 0x20,       # made by rotating the cartridge's '?'
        " ": 0xDB,       # space needs no glyph
        "A": 0xA0,       # native Latin: raised, never replaced
        "[<3]": 0x50,    # multi-character spelling: not a font entry
    }.items():
        charset.decode[code] = char
        charset.encode[char] = code
    glyphs = {"a": Glyph(name="a", rows=art_to_rows(["...##..."] * GLYPH_HEIGHT))}
    data, placed = build_font(object(), charset, glyphs)
    return data, placed, charset


def seg(data: bytes, code: int) -> bytes:
    return data[code * GLYPH_BYTES : (code + 1) * GLYPH_BYTES]


def test_build_font_covers_every_code(built):
    data, _, _ = built
    assert len(data) == GLYPH_COUNT * GLYPH_BYTES


def test_build_font_places_only_real_single_char_glyphs(built):
    _, placed, _ = built
    assert placed == {"a": 0x13, "¿": 0x20}


def test_build_font_writes_our_glyph_into_its_slot(built):
    data, _, _ = built
    assert seg(data, 0x13) == art_to_bytes(["...##..."] * GLYPH_HEIGHT)


def test_build_font_rotates_the_cartridges_question_mark(built):
    data, _, _ = built
    assert seg(data, 0x20) == art_to_bytes(IQMARK_ART)


def test_build_font_raises_native_latin(built):
    data, _, _ = built
    for code in NATIVE_LATIN:
        assert seg(data, code) == raise_glyph(base_glyph(code))
    # Concretely: the last row is blanked, the rest moved up.
    assert seg(data, 0xA0) == bytes([0xA0] * (GLYPH_HEIGHT - 1)) + bytes([BLANK_ROW])


def test_build_font_keeps_unassigned_kana_glyphs(built):
    data, placed, _ = built
    taken = set(placed.values())
    for code in range(NATIVE_LATIN[0]):
        if code in taken:
            continue
        assert seg(data, code) == base_glyph(code), f"kana {code:#04x} was touched"
        assert seg(data, code) != BLANK_GLYPH, f"kana {code:#04x} was blanked"


def test_build_font_missing_glyph_raises(monkeypatch):
    monkeypatch.setattr(
        font_mod, "read_font", lambda rom: [base_glyph(c) for c in range(GLYPH_COUNT)]
    )
    charset = Charset(name="latin-test", decode={0x13: "a"}, encode={"a": 0x13})
    with pytest.raises(FontError, match="'a'"):
        build_font(object(), charset, {})
