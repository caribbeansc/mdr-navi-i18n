"""The leftovers baseline names findings the way packs name lines, and only grows.

One file serves both releases. A finding is keyed by where Kuwagata keeps the
same bytes, or tagged with the release when it has no Kuwagata twin, so the
Kabuto build's stat tables do not hide behind or collide with Kuwagata's. And
because a scan of one cartridge cannot tell which of the other's keys are
stale, saving never drops a key: it used to rewrite the file from one scan,
which would have thrown away everything only the other release reports.
"""

import json

from navi.leftovers import Leftover, load_baseline, save_baseline


def _finding(offset, canonical=None, tag=""):
    return Leftover(offset=offset, length=4, chars=4, why="prosa", garbage=True,
                    canonical=canonical, tag=tag)


def test_keys_name_the_kuwagata_twin_or_the_release():
    assert _finding(0x430850, canonical=0x430830, tag="KBT").key == "430830:4"
    assert _finding(0x0879A0, canonical=None, tag="KBT").key == "KBT:0879A0:4"
    assert _finding(0x053BC8, canonical=0x053BC8).key == "053BC8:4"


def test_saving_only_ever_adds(tmp_path):
    path = tmp_path / "leftovers.json"
    path.write_text(json.dumps({"known": ["KBT:0879A0:23", "087222:7"]}))
    save_baseline(path, [_finding(0x053BC8, canonical=0x053BC8)])
    assert load_baseline(path) == {"KBT:0879A0:23", "087222:7", "053BC8:4"}
    # Offsets only: the file never carries the Japanese.
    assert set(json.loads(path.read_text())) == {"comment", "known"}
