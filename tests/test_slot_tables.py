"""Every slot of an index-reached name table needs its own translation.

The game finds these names by multiplying an index, so a record that fills
its slot leaves no terminator and the scanner used to read it together with
the slot next door. Translating that pair then wrote over BOTH slots and
zeroed the second: eighteen part names (マスクドカブト, キラーホエール,
ジェミニ...) drew as an empty gap in-game, and the medal FAMILY column was
never catalogued at all, so "you got the X medal" printed four kana through
the Latin font and came out as ``H¿ガP``.

The ceiling is one byte short of the slot, to leave room for the terminator.
For the 8-byte tables the code says so outright: the insert slot is filled
with spaces, the name copied over its first 8 bytes and trailing spaces
trimmed backwards from byte 7 (0x0807C198), so an eight-character name never
gets a terminator and the printer runs into the rest of the slot.
"""

import json
from pathlib import Path

import pytest

from navi.lang import fingerprint

from .conftest import language_packs, pack_id
from navi.strings import SLOT_TABLES, scan
from navi.table import load_japanese, visible_length

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def slots(game_rom):
    return {s.offset: s for s in scan(game_rom, load_japanese()) if s.fixed}


def _pack(pack):
    entries = json.loads((pack / "menus.json").read_text("utf-8"))
    return {e["key"]: e for e in entries["entries"]}


@pytest.mark.parametrize("pack_dir", language_packs(), ids=pack_id)
def test_every_slot_is_translated(slots, pack_dir):
    pack = _pack(pack_dir)
    missing = []
    for start, stride, count, _width in SLOT_TABLES:
        for i in range(count):
            entry = slots.get(start + i * stride)
            if entry is None:      # an empty slot has nothing to translate
                continue
            line = pack.get(entry.key)
            if line is None or not line.get("t"):
                missing.append(f"{entry.key} ({entry.text})")
            elif line["src"] != fingerprint(entry.text):
                missing.append(f"{entry.key}: stale fingerprint")
    assert not missing, (
        "name slots the build would leave Japanese or blank on screen: "
        f"{missing[:12]}")


@pytest.mark.parametrize("pack_dir", language_packs(), ids=pack_id)
def test_no_slot_translation_fills_its_field(slots, pack_dir):
    pack = _pack(pack_dir)
    over = []
    for start, stride, count, width in SLOT_TABLES:
        for i in range(count):
            entry = slots.get(start + i * stride)
            line = entry and pack.get(entry.key)
            if line and visible_length(line["t"]) > width - 1:
                over.append(f"{entry.key}: {line['t']!r}")
    assert not over, (
        "a name that fills all 8 bytes leaves no terminator and the insert "
        f"printer runs past it: {over}")
