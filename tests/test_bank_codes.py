"""A repainted glyph-bank code must have no Japanese left behind it.

`glyph_banks` repaints a kanji cell, and the cell is reached by CODE, so the
new pixels appear in EVERY string those screens draw with that code. The pack
repaints 回 (E014) to "US" as half of 回数, which its own note admits is not
the safe kind of code: 回 also spells 今回, 前回, 回戦 and, inside the parts
pool, 攻撃1回に.

That is harmless only for as long as every string carrying 回 has a
translation, because then the code never renders. The day one of them loses
it, the line reads "1USに" — Spanish letters inside Japanese — and nothing
else in the tooling would say so. So this pins the condition rather than the
consequence.

Only the LOOSE strings matter: the banks feed the battle parts panel and the
Medarreloj status screens, which read the index-addressed pools. Dialogue
goes through the kanji font at 0x6593D0 instead, so a script line carrying 回
draws the real kanji and is none of this test's business.
"""

import json
from pathlib import Path

import pytest

from navi.catalog import build as build_catalog
from navi.table import load_japanese

from .conftest import language_packs, pack_id

ROOT = Path(__file__).resolve().parent.parent

#: Codes the pack repaints in a bank although they are not exclusive to the
#: word being translated, as ``code -> the kanji, for the failure message``.
SHARED_REPAINTED = {0xE014: "回"}

def _translations(pack):
    gfx = json.loads((pack / "gfx.json").read_text("utf-8"))
    by_offset = {int(str(site), 16): entry.get("t", "")
                 for entry in gfx["extra_strings"].values()
                 for site in entry.get("sites", [])}
    by_key = {e["key"]: e.get("t", "") for e in
              json.loads((pack / "menus.json").read_text("utf-8"))["entries"]}
    return by_key, by_offset

@pytest.mark.parametrize("pack", language_packs(), ids=pack_id)
def test_every_string_behind_a_repainted_code_is_translated(game_rom, pack):
    japanese = load_japanese()
    catalog = build_catalog(game_rom, japanese)
    by_key, by_offset = _translations(pack)
    naked = []
    for code, kanji in SHARED_REPAINTED.items():
        for line in catalog.lines.values():
            if line.kind != "loose" or kanji not in line.text:
                continue
            if by_key.get(line.key) or by_offset.get(getattr(line, "offset", -1)):
                continue
            naked.append(f"{line.key} still carries {kanji}")
    assert not naked, (
        "the bank draws Latin letters for these codes, so an untranslated "
        f"string using one renders as Spanish inside Japanese: {naked}")
