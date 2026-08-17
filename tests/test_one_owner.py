"""A ROM site may be written by one mechanism, never two.

The pack writes strings two ways: menus.json entries, which the loose-string
writer handles, and gfx.json extra_strings, which run afterwards for text no
pointer reaches. When both name the same site the loose writer goes first and
extra_strings then fails its own fingerprint check — the bytes no longer hold
the Japanese it expects — so it is silently skipped and the other text ships.

That is how "Ataca al Medabot<NL>más cercano" reached the screen as
``Ataca al Medabotás cerca``: the box does not honour <NL>, and the
extra_strings version that renders correctly on its three sibling sites never
got to write this one.
"""

import json
from pathlib import Path

import pytest

from navi.build import TEAM_COUNT, TEAM_RECORD, TEAM_TABLE
from navi.strings import scan
from navi.table import load_japanese

from .conftest import language_packs, pack_id

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("pack", language_packs(), ids=pack_id)
def test_no_site_is_claimed_by_both_mechanisms(game_rom, pack):
    catalogued = {s.offset for s in scan(game_rom, load_japanese())}
    named = {e["key"] for e in
             json.loads((pack / "menus.json").read_text("utf-8"))["entries"]
             if e.get("t")}
    gfx = json.loads((pack / "gfx.json").read_text("utf-8"))
    clashes = []
    for key, entry in gfx["extra_strings"].items():
        for site in entry.get("sites", []):
            at = int(str(site), 16)
            if at in catalogued and f"str:{at:06X}" in named:
                clashes.append(f"{at:06X}: menus.json and extra:{key}")
    assert not clashes, (
        "sites two writers claim; the loose one wins and the other is "
        f"silently skipped: {clashes}")


@pytest.mark.parametrize("pack", language_packs(), ids=pack_id)
def test_the_team_table_is_left_to_its_own_writer(game_rom, pack):
    """Nothing loose may be written inside the robattle team table.

    That table has one writer, gfx.json "team_names", which reads each 8-byte
    field and matches it by fingerprint. The loose scan finds runs in there
    too — stat columns that decode as kana, and name fields it reads as one
    long run — and translating one of those lands on top of the names the
    other writer is about to place. It nearly shipped that way for Kabuto:
    five such runs came back from the translators as byte-for-byte copies,
    and one of them spelled four team names in Latin across a whole record.
    """
    base = game_rom.at(TEAM_TABLE)
    assert base is not None, "this dump has no team table where one is expected"
    span = range(base, base + TEAM_COUNT * TEAM_RECORD)

    inside = []
    for part in [pack / "menus.json", *sorted(pack.glob("*/menus.json"))]:
        if not part.is_file():
            continue
        for entry in json.loads(part.read_text("utf-8"))["entries"]:
            key = entry["key"]
            if not entry.get("t") or not key.startswith("str:"):
                continue
            offset = int(key.rsplit(":", 1)[1], 16)
            here = game_rom.at(offset) if key.count(":") == 1 else offset
            if here in span:
                inside.append(f"{key} -> {here:06X}")
    assert not inside, (
        "loose entries inside the team table, whose names gfx.json "
        f"team_names writes: {inside}")
