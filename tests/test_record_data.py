"""A translation may never touch the bytes that are not text.

The part table is 608 records of 0x14: eight bytes of model code, eight of
name, then three bytes of the part's own stats and a zero. Neither text field
has a terminator — 127 of the names fill all eight bytes — so the game reads
fixed widths.

gfx.json carries a "room" per entry and the extra-strings writer believes it:
it writes the payload and then ZERO-PADS to room. 188 of those names declared
a room of 9 to 12, and the entries covering code and name together declared
20 — the whole record. Both halves of that corrupted the record: a long name
wrote over the stats, and a short one padded zeroes over them. 125 records
shipped with the wrong data.

Nothing downstream could catch it. The text is encodable, fits its box and
renders correctly; only the bytes after it are wrong. A player found it
because one of those stats is visible — "Prominence is listed as Female" —
and the rest are silent, which is worse.

So the check is on the bytes, not on the text: build the ROM and compare
every record's data tail against the dump. It has to be identical.

That means building the whole ROM once per pack, which is minutes rather
than seconds, so it is marked `slow` and left out of a plain `pytest` run.
Run it before a release: `pytest -m slow`. The cheap half of the file — the
one that only reads the declared rooms — stays in every run, but on its own
it would NOT have caught this: the damage came from the zero padding at
write time, not from what the JSON says.
"""

import json
from pathlib import Path

import pytest

from .conftest import language_packs, pack_id
from navi.build import build
from navi.catalog import build as build_catalog
from navi.lang import Pack
from navi.strings import TEXT_RECORDS, record_text_room
from navi.table import Charset, load_japanese

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.game
@pytest.mark.slow      # a full build per pack: ten minutes from cold
@pytest.mark.parametrize("pack_dir", language_packs(), ids=pack_id)
def test_a_build_never_changes_a_records_data(game_rom, pack_dir):
    """Whatever the packs say, the stats after the text stay untouched."""
    from navi.rom import Rom

    charset = Charset.load(ROOT / "data" / "charset-latin.tbl")
    # build() patches in place and game_rom is session-scoped, so this gets
    # its own copy — otherwise every test after this one reads a patched ROM.
    subject = Rom.load(game_rom.path)
    pack = Pack.load(pack_dir.name, release=subject.release.name)
    catalog = build_catalog(subject, load_japanese(), seeds=pack.loose_sites())
    before = bytes(subject.data)
    build(subject, catalog, pack, charset)
    after = bytes(subject.data)

    damaged = []
    for start, stride, count, text in TEXT_RECORDS:
        for i in range(count):
            at = start + i * stride + text
            end = start + i * stride + stride
            if before[at:end] != after[at:end]:
                damaged.append(
                    f"record {i} at 0x{start + i * stride:06X}: "
                    f"{before[at:end].hex(' ')} -> {after[at:end].hex(' ')}")
    assert not damaged, (
        f"{len(damaged)} records had data overwritten by a translation "
        f"(first few: {damaged[:5]})")


def test_the_declared_room_never_exceeds_the_field():
    """gfx.json may not claim more bytes than the record actually has.

    The writer pads with zeroes up to room, so an over-claimed room damages
    the record even when the translation itself is short enough.
    """
    wrong = []
    for pack_dir in language_packs():
        code = pack_dir.name
        path = ROOT / "langs" / code / "gfx.json"
        if not path.is_file():
            continue
        table = json.loads(path.read_text(encoding="utf-8")).get("extra_strings", {})
        for key, entry in table.items():
            for site in entry.get("sites", []):
                width = record_text_room(int(str(site), 16))
                if width is not None and int(entry["room"]) > width:
                    wrong.append(f"{code} {key} at {site}: "
                                 f"room {entry['room']} into {width} bytes")
    assert not wrong, wrong[:10]
