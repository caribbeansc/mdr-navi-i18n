"""A result-composer piece keeps the row breaks and number slots it was born with.

The pieces at 0x4CC83C-0x4CCDA0 are spliced together with values the game
fills in, and the composer decides where each one lands from the piece's own
bytes. Four translations had moved a marker: the medal level-up line put its
number thirteen cells in instead of eight, and the level printed jammed onto
the end of the word ("Medalla a niv1") instead of starting its row.

The build refuses a piece whose skeleton drifted — the line then shows
Japanese, which is recoverable — and this keeps the pack at zero refusals.
"""

import json
from pathlib import Path

from navi.build import _piece_break, piece_cells, piece_skeleton
from navi.table import Charset, TableError, encode

ROOT = Path(__file__).resolve().parent.parent


def _exact_pieces():
    gfx = json.loads((ROOT / "langs/es/gfx.json").read_text("utf-8"))
    for key, entry in gfx["extra_strings"].items():
        if entry.get("exact"):
            yield key, entry


def test_every_exact_piece_keeps_the_original_skeleton(game_rom):
    charset = Charset.load(ROOT / "data/charset-latin.tbl")
    data = bytes(game_rom.data)
    wrong = []
    for key, entry in _exact_pieces():
        site = int(str(entry["sites"][0]), 16)
        original = data[site:site + int(entry["room"])]
        try:
            payload = encode(entry["t"], charset)
        except TableError as exc:      # covered by the pack's own tests
            wrong.append(f"{key}: {exc}")
            continue
        body = payload[:-1] if entry["t"].endswith("<X:F0>") else payload
        if piece_skeleton(body) != piece_skeleton(original):
            wrong.append(f"{key} @{site:06X}: "
                         f"{piece_skeleton(body)} != {piece_skeleton(original)}")
    assert not wrong, ("pieces whose number would print in the wrong place, "
                       f"and which the build therefore refuses: {wrong}")


def test_no_piece_composes_wider_than_its_japanese(game_rom):
    # The pieces of one result line share the box's 22 columns, so a piece
    # that grows pushes the ones after it off the edge, where the game draws
    # nothing at all.
    charset = Charset.load(ROOT / "data/charset-latin.tbl")
    data = bytes(game_rom.data)
    wide = []
    for key, entry in _exact_pieces():
        site = int(str(entry["sites"][0]), 16)
        original = data[site:site + int(entry["room"])]
        try:
            payload = encode(entry["t"], charset)
        except TableError:
            continue           # the skeleton test already reports this
        body = payload[:-1] if entry["t"].endswith("<X:F0>") else payload
        if piece_cells(body) > piece_cells(original):
            wide.append(f"{key} @{site:06X}: "
                        f"{piece_cells(body)} > {piece_cells(original)} cells")
    assert not wide, f"pieces the build would refuse for width: {wide}"


def test_a_kanji_low_byte_is_not_read_as_the_piece_break(game_rom):
    # 変 is 0xE0F0: scanning for a bare 0xF0 stops on its second half and
    # keeps 化した! as the piece's tail, which the game then draws.
    data = bytes(game_rom.data)
    original = data[0x4CC9B5:0x4CC9B5 + 19]
    assert original.find(0xF0) == 10
    assert _piece_break(original) == 16
