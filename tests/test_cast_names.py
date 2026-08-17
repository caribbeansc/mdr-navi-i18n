"""Every record of the cast-name table needs a Latin name.

The table at 0x7ECA90 is 86 records of 0x10 bytes, each an 8-character name
field padded with spaces, and the game draws them through the patched font.
A record left in kana therefore does not read as Japanese — it reads as Latin
soup: ヒヨリ came out as ``Á")``. Ten of the eighty-six were translated and
nobody noticed the other seventy-six, because the characters they name only
turn up in robattles later in the game.
"""

import json
from pathlib import Path

import pytest

from navi.table import Charset, decode, encode, load_japanese

from .conftest import language_packs, pack_id

ROOT = Path(__file__).resolve().parent.parent
BASE, STRIDE, COUNT, FIELD = 0x7ECA90, 0x10, 86, 8

def _sites(pack):
    gfx = json.loads((pack / "gfx.json").read_text("utf-8"))
    out = {}
    for entry in gfx["names"]["entries"]:
        for site in entry["at"]:
            out[int(str(site), 16)] = entry
    return out

@pytest.mark.parametrize("pack", language_packs(), ids=pack_id)
def test_every_cast_record_has_a_name(game_rom, pack):
    japanese = load_japanese()
    data = bytes(game_rom.data)
    sites = _sites(pack)
    missing = []
    for index in range(COUNT):
        at = BASE + index * STRIDE
        text, _ = decode(data, at, japanese, limit=FIELD + 1)
        if not text.strip():
            continue          # an empty record has nothing to name
        if at not in sites:
            missing.append(f"{at:06X} ({text.strip()})")
    assert not missing, (
        "cast records whose kana the font would draw as Latin soup: "
        f"{missing}")

@pytest.mark.parametrize("pack", language_packs(), ids=pack_id)
def test_no_cast_name_overruns_its_field(pack):
    charset = Charset.load(ROOT / "data/charset-latin.tbl")
    over = []
    for at, entry in _sites(pack).items():
        width = int(entry.get("field", FIELD))
        if len(encode(entry["text"], charset)) > width:
            over.append(f"{at:06X}: {entry['text']!r} over {width}")
    assert not over, f"names that do not fit their field: {over}"
