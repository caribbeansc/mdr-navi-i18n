"""No line of dialogue may go uncatalogued without a reason on record.

The opcode walk alone entered a script only through its header and followed
only the jumps it knew, and 438 lines sat behind the branches it never
reached — most of two of the game's biggest scripts. Nobody noticed for a
long time because the failure used to be harmless: an unreached line simply
stayed Japanese. It is not harmless now. The charset spends the whole kana
range on Latin, so an unreached line draws as garbage, and that is how this
was found: from a player's screenshot, two hours into the game.

`rescue_sites` recovers every line something points at. What is left over is
pinned here BY OFFSET (never by text — the repository does not hold the
game's words), and each one was checked to be reachable by nothing at all.
So this test fails in both directions that matter: a line the walk stops
seeing turns up as a new run, and a run that becomes reachable — because the
walk improved — has to be taken off the list and translated.
"""

import json
from pathlib import Path

import pytest

from navi.script import read_scripts, read_strings
from navi.table import decode, encode, load_japanese

PINNED = Path(__file__).parent / "data" / "unreached-scripts.json"


def unreached(rom, charset):
    """Text inside a script that the catalogue does not name, as index -> offsets."""
    out = {}
    for script in read_scripts(rom):
        known = read_strings(script, charset)
        if not known:
            continue
        data = bytes(script.data)
        start = min(known)
        # A catalogued line covers its whole chain, not just its first box.
        covered = set()
        for at, (text, size) in known.items():
            end = at
            while True:
                _, nxt = decode(data, end, charset)
                end = nxt
                if (end >= len(data) or data[end - 1] in (0x00, 0xF3)
                        or end > at + len(encode(text, charset)) + 2):
                    break
            covered.update(range(at, end))
        found, pos = [], start
        while pos < len(data):
            if pos in covered or data[pos] == 0x00:
                pos += 1
                continue
            try:
                text, end = decode(data, pos, charset)
            except Exception:
                pos += 1
                continue
            if end <= pos:
                pos += 1
                continue
            # Real writing, not a run of table bytes that decodes as kana.
            if sum(1 for ch in text if ord(ch) > 0x2000) >= 4 and end - pos >= 6:
                found.append("%04X" % pos)
            pos = end
        if found:
            out["%04d" % script.index] = found
    return out


@pytest.mark.game
def test_no_uncatalogued_dialogue_beyond_the_pinned_list(game_rom):
    charset = load_japanese()
    pinned = json.loads(PINNED.read_text())["runs"]
    found = unreached(game_rom, charset)

    appeared = {k: sorted(set(v) - set(pinned.get(k, ())))
                for k, v in found.items()}
    appeared = {k: v for k, v in appeared.items() if v}
    assert not appeared, (
        "dialogue the catalogue cannot see, and the font would draw as "
        f"garbage: {appeared}")

    gone = {k: sorted(set(v) - set(found.get(k, ())))
            for k, v in pinned.items()}
    gone = {k: v for k, v in gone.items() if v}
    assert not gone, (
        "these runs are catalogued now — translate them and take them off "
        f"tests/data/unreached-scripts.json: {gone}")


@pytest.mark.game
def test_the_pinned_runs_are_reachable_by_nothing(game_rom):
    """Why they are allowed to stay Japanese: the game cannot draw them.

    A 16-bit pointer to a string lives in its own script, and an absolute one
    would be a word anywhere in the ROM. Neither exists for any of these, so
    they are script that was cut, not script the pack forgot.

    A ``01 <lo> <hi>`` whose 0x01 the walk read as another instruction's
    ARGUMENT is not a pointer. Script 158 spells 0x0607 that way, by
    coincidence, in the middle of a run of ``07`` instructions. Taking it
    for a text op is what rewrote the bus scene's logic (see rescue_sites).
    """
    import struct

    from navi.script import read_scripts, script_bounds

    pinned = json.loads(PINNED.read_text())["runs"]
    data = bytes(game_rom.data)
    bounds = script_bounds(game_rom)
    scripts = read_scripts(game_rom)
    reachable = []
    for index, offsets in pinned.items():
        base, length = bounds[int(index)]
        script = data[base:base + length]
        operands = scripts[int(index)].operands
        for spelling in offsets:
            at = int(spelling, 16)
            needle = bytes([0x01, at & 0xFF, (at >> 8) & 0xFF])
            hits = [i for i in range(len(script) - 2)
                    if script[i:i + 3] == needle and i not in operands]
            if hits:
                reachable.append(f"script:{index}:{spelling} (relative)")
            if struct.pack("<I", 0x08000000 + base + at) in data:
                reachable.append(f"script:{index}:{spelling} (absolute)")
    assert not reachable, (
        f"the game CAN reach these, so they are not cut script: {reachable}")
