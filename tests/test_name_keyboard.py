"""The name screen draws a FIXED number of cells, so a short label is garbage.

The name-entry keyboard's four buttons live in 8-byte slots at 0x5D6100, and
the screen does not draw them as strings that stop at their terminator: it
draws as many cells as the Japanese label had. The cartridge's own labels are
padded to that width with spaces — おわる is three kana and two spaces — so
every cell it draws holds a character.

A translation that is SHORTER leaves the build's 0x00 padding sitting in a
drawn cell, and the renderer paints the tile at code zero: a block of
multicoloured noise. It reached the screen in English as
``lower  Back▓  Done▓``, four-letter words in five-cell slots, while the
Spanish build was clean because Listo and Atrás happen to be exactly five.

``navi validate`` cannot see this — the slot is eight bytes and the text fits
it fine; the constraint is the number of cells the SCREEN paints, which is a
property of the Japanese, not of the field. So it is pinned here, against the
dump, for every pack.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from navi.table import decode, load_japanese, visible_length

from .conftest import language_packs, pack_id

#: The four buttons, and the prompt above them. The prompt is drawn as an
#: ordinary string and only its ceiling matters; the buttons are copied cell
#: for cell and must match exactly.
BUTTONS = (0x5D6100, 0x5D6108, 0x5D6110, 0x5D6118)
PROMPT = 0x5D6120


def _texts(pack: Path) -> dict[int, str]:
    entries = json.loads((pack / "menus.json").read_text("utf-8"))["entries"]
    out = {}
    for entry in entries:
        if entry["key"].startswith("str:") and entry.get("t"):
            out[int(entry["key"][4:], 16)] = entry["t"]
    return out


@pytest.mark.game
@pytest.mark.parametrize("pack", language_packs(), ids=pack_id)
def test_the_keyboard_buttons_fill_every_cell_the_screen_draws(game_rom, pack):
    japanese = load_japanese()
    data = bytes(game_rom.data)
    texts = _texts(pack)
    wrong = []
    for at in BUTTONS:
        original, _ = decode(data, at, japanese, limit=16)
        text = texts.get(at)
        if text is None:
            continue          # not translated yet: the Japanese still fills it
        if visible_length(text) != len(original):
            wrong.append(f"{at:06X}: {text!r} is {visible_length(text)} cells "
                         f"where the screen draws {len(original)}")
    assert not wrong, (
        "name-entry buttons whose cells the screen draws and the translation "
        f"does not fill — the padding renders as tile noise: {wrong}")


@pytest.mark.game
@pytest.mark.parametrize("pack", language_packs(), ids=pack_id)
def test_the_keyboard_prompt_is_not_cut_off(game_rom, pack):
    japanese = load_japanese()
    original, _ = decode(bytes(game_rom.data), PROMPT, japanese, limit=32)
    text = _texts(pack).get(PROMPT)
    if text is None:
        pytest.skip("the prompt is not translated in this pack")
    assert visible_length(text) <= len(original), (
        f"{text!r} is {visible_length(text)} cells and the screen draws "
        f"{len(original)}: the tail is simply not painted")
