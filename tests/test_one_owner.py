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

from navi.strings import scan
from navi.table import load_japanese

ROOT = Path(__file__).resolve().parent.parent


def test_no_site_is_claimed_by_both_mechanisms(game_rom):
    catalogued = {s.offset for s in scan(game_rom, load_japanese())}
    named = {e["key"] for e in
             json.loads((ROOT / "langs/es/menus.json").read_text("utf-8"))["entries"]
             if e.get("t")}
    gfx = json.loads((ROOT / "langs/es/gfx.json").read_text("utf-8"))
    clashes = []
    for key, entry in gfx["extra_strings"].items():
        for site in entry.get("sites", []):
            at = int(str(site), 16)
            if at in catalogued and f"str:{at:06X}" in named:
                clashes.append(f"{at:06X}: menus.json and extra:{key}")
    assert not clashes, (
        "sites two writers claim; the loose one wins and the other is "
        f"silently skipped: {clashes}")
