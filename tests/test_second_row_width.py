"""The box's second row is one column narrower than its first.

A 22-character row renders whole when it is the first row of a box and loses
its last character when it is not — the last cell of a second row is never
drawn. Proved in-game with an A-Z ruler, and the cartridge agrees: of its
22-column rows, 38 are first rows and 2 are not.

The pack had 346 rows over that limit, every one of them quietly missing a
letter on screen ("que hallaste" showed as "que hallast"), which is exactly
the kind of thing nobody notices while reading a diff.
"""

import json
from pathlib import Path

import pytest

from navi.table import rows_by_box
from navi.validate import LINE_WIDTH

from .conftest import language_packs, pack_id

ROOT = Path(__file__).resolve().parent.parent


def _parts(pack: Path):
    """Every file of a pack that holds text drawn in the dialogue box."""
    for path in sorted(pack.rglob("script/*.json")):
        yield path
    for path in sorted(pack.glob("menus.json")):
        yield path
    for path in sorted(pack.glob("*/menus.json")):
        yield path       # a release's own lines


@pytest.mark.parametrize("pack", language_packs(), ids=pack_id)
def test_no_second_row_uses_the_last_column(pack):
    offenders = []
    for path in _parts(pack):
        for entry in json.loads(path.read_text("utf-8"))["entries"]:
            text = entry.get("t", "")
            if not text:
                continue
            for row in rows_by_box(text):
                limit = LINE_WIDTH if row.first_in_box else LINE_WIDTH - 1
                if len(row.text) > limit:
                    offenders.append(f"{entry['key']}: {row.text!r} ({len(row.text)})")
    assert not offenders, (
        "rows past the column the box actually draws — the last character "
        f"will be missing on screen: {offenders[:10]}")
