"""The battle-message composed-width contract.

The destruction cinematic's renderer leaks stack per composed cell (see the
comment above BATTLE_MSG_TABLE in navi/build.py): a translation that composes
wider than its Japanese original crashes the game with a jump to 0x040000D4.
The build refuses such lines; this test keeps the whole pack clean so the
refusal never has to fire.
"""

import json
import struct

import pytest

from navi.build import (BATTLE_MSG_TABLE, _INSERT_W_ES, _INSERT_W_JP,
                        _composed_cells)
from navi.lang import fingerprint
from navi.table import decode, load_japanese

from .conftest import REPO_ROOT


def _japanese_messages(game_rom):
    charset = load_japanese()
    data = bytes(game_rom.data)
    start, end = BATTLE_MSG_TABLE
    seen = {}
    targets = set()
    for site in range(start, end, 4):
        target = struct.unpack_from("<I", data, site)[0]
        if 0x08000000 <= target < 0x09000000:
            targets.add(target & 0x1FFFFFF)
    # Targets, plus the pointerless GROUP VARIANTS that follow them (the
    # engine walks past <X:F0> terminators to pick one) — see the variant
    # pass in navi/build.py.
    starts = sorted(targets) + [0x4CA150]
    for i in range(len(starts) - 1):
        at = starts[i]
        limit = starts[i + 1]
        while at < limit:
            if data[at] == 0:
                at += 1
                continue
            text, string_end = decode(data, at, charset, limit=120)
            if string_end <= at:
                at += 1
                continue
            if text.replace("<X:F0>", "").strip():
                seen[fingerprint(text)] = text
            at = string_end
    return seen


def test_insert_widths_cover_the_slot_labels():
    # コ inserts the part-slot label from "ptr_strings"; the width table
    # must not understate it or the composed check lies.
    pack = json.loads((REPO_ROOT / "langs/es/gfx.json").read_text("utf-8"))
    longest = max(len(entry["t"]) for entry in pack["ptr_strings"].values())
    assert longest <= _INSERT_W_ES["コ"]


def test_every_battle_message_composes_within_its_japanese(game_rom):
    pack = json.loads((REPO_ROOT / "langs/es/gfx.json").read_text("utf-8"))
    japanese = _japanese_messages(game_rom)
    offenders = []
    orphans = []
    for key, latin in pack["battle_messages"].items():
        source = japanese.get(key)
        if source is None:
            orphans.append(key)
            continue
        over = (_composed_cells(latin, _INSERT_W_ES)
                - _composed_cells(source, _INSERT_W_JP))
        if over > 0:
            offenders.append((key, over, latin))
    assert not orphans, f"stale keys, no Japanese behind them: {orphans}"
    assert not offenders, f"would crash the cinematic: {offenders}"
