"""The offset map, pinned: a wrong entry here is a corrupted second cartridge.

Every address this project knows is written down as a KUWAGATA offset and goes
through ``rom.at`` before it is read or written, so on a Kabuto dump the whole
toolchain is only ever as right as ``data/offsets-kabuto.json``. Nothing about a
wrong entry looks wrong: the build reports the same counts, the patch applies,
and the damage is a font drawn over a sprite or a translation written into the
middle of somebody else's table, hours into a playthrough on the release nobody
tested. The map is derived mechanically, which means it can be checked
mechanically, and that is what this file does.

Two halves. The first needs no dump: the committed map has to be well formed —
sorted, non-overlapping, covering nearly the whole ROM — the canonical release
has to be its own identity, a span crossing a seam has to be refused rather
than guessed at, and every offset that maps has to come back as itself. The
second half needs both cartridges and checks the map against them: the places
this project actually writes to (the fonts, the pointer tables) must hold the
same bytes there, every catalogued line must read the same Japanese there, and
the sites a language pack names must land on the Japanese the pack was written
against. All of it skips cleanly when a dump is missing.
"""

from __future__ import annotations

import json

import pytest

from navi import align
from navi.build import BATTLE_MSG_TABLE
from navi.catalog import build as build_catalog
from navi.lang import LANGS_DIR, fingerprint
from navi.rom import KABUTO, KUWAGATA, Rom
from navi.script import CHAIN_KEYS
from navi.table import decode, load_japanese

MAP_PATH = align.DATA_DIR / "offsets-kabuto.json"

#: Both releases are 8 MB cartridges.
ROM_SIZE = 0x800000

#: The dialogue font: 0xE0 single-byte codes, nine 1bpp rows each.
FONT_BYTES = 0xE0 * 9
#: The kanji font: ten rows a glyph, over the 0xE0xx/0xE1xx code space.
KANJI_FONT_BYTES = 512 * 10
#: The table that expands a 1bpp nibble into four 4bpp pixels: 16 halfwords.
LUT_BYTES = 16 * 2

#: Enough of a script or a message to tell it from its neighbour.
SAMPLE_BYTES = 64
#: …of which this much has to be inside one run, or the map says nothing.
MIN_SAMPLE_BYTES = 8


@pytest.fixture(scope="module")
def kabuto_map() -> align.Alignment:
    """The committed Kuwagata-to-Kabuto map, which is checked in, not derived."""
    alignment = align.load("kabuto")
    assert alignment is not None, f"{MAP_PATH} is missing"
    return alignment


@pytest.fixture(scope="module")
def raw_map() -> dict:
    return json.loads(MAP_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def releases(game_rom: Rom, other_rom: Rom) -> tuple[Rom, Rom]:
    """Both dumps, named, because the map runs Kuwagata to Kabuto and not back."""
    dumps = {rom.release.name: rom for rom in (game_rom, other_rom)}
    missing = {KUWAGATA.name, KABUTO.name} - set(dumps)
    if missing:
        pytest.skip(f"No dump of {', '.join(sorted(missing))}")
    return dumps[KUWAGATA.name], dumps[KABUTO.name]


def _spread(alignment: align.Alignment) -> list[int]:
    """Offsets from end to end of the map: a sweep, plus every run's edges.

    A sweep alone walks straight past the hundreds of short runs the shifted
    regions are made of; the edges alone never sample the four-megabyte one.
    """
    offsets = set(range(0, ROM_SIZE, 0x400))
    for start, _, size in alignment.runs:
        offsets.update((start, start + size // 2, start + size - 1))
    return sorted(offsets)


def _vouched(rom: Rom, offset: int, most: int) -> int:
    """How many bytes from ``offset``, at most ``most``, the map vouches for.

    A script ends where the two releases stop agreeing, which for a few of
    them is a dozen bytes in; asking for a fixed window would compare data the
    map never claimed was the same.
    """
    span = most
    while span > 1 and rom.at(offset, span) is None:
        span -= 1
    return span


def _first_gap(alignment: align.Alignment) -> tuple[int, int]:
    """The first ``(last mapped offset, first unmapped offset)`` in the map."""
    for (start, _, size), (next_start, _, _) in zip(alignment.runs,
                                                    alignment.runs[1:]):
        if start + size < next_start:
            return start + size - 1, start + size
    pytest.fail("the map has no gaps at all, which no two releases have")


# -- the committed map, on its own ---------------------------------------


def test_the_map_names_the_two_dumps_it_was_derived_from(raw_map):
    """A map derived from someone's patched build would be quietly wrong."""
    assert raw_map["from"] == KUWAGATA.name
    assert raw_map["to"] == KABUTO.name
    assert raw_map["sha1"][KUWAGATA.name] == KUWAGATA.sha1
    assert raw_map["sha1"][KABUTO.name] == KABUTO.sha1


def test_the_maps_runs_are_sorted_and_never_overlap(raw_map):
    """Overlapping runs mean two answers for one offset, and a coin toss."""
    runs = [tuple(run) for run in raw_map["runs"]]
    assert runs, "the map has no runs"
    for (start, target, size), (next_start, _, _) in zip(runs, runs[1:]):
        assert size > 0
        assert start < next_start, f"run at {start:#x} is out of order"
        assert start + size <= next_start, f"run at {start:#x} overlaps the next"
        assert 0 <= target and target + size <= ROM_SIZE


def test_a_pointer_table_run_never_contradicts_the_run_beside_it(kabuto_map):
    """The tables were found by what they point at, the runs by their bytes.

    They are looked up together, so where the two ways of finding the same
    stretch overlap by a byte or two they have to agree about where it goes;
    if they ever disagree, which answer a lookup gets depends on the order
    ``load`` happened to sort them in.
    """
    runs = kabuto_map.runs
    for (start, target, size), (next_start, next_target, _) in zip(runs, runs[1:]):
        if start + size <= next_start:
            continue
        assert target + (next_start - start) == next_target, (
            f"the runs at {start:#x} and {next_start:#x} disagree")


def test_the_map_covers_the_great_majority_of_the_cartridge(kabuto_map):
    """A map with holes in it is a build that leaves that asset Japanese."""
    assert kabuto_map.covered() > 0.95 * ROM_SIZE
    assert kabuto_map.runs[0][0] == 0, "the header itself is unmapped"
    last_start, _, last_size = kabuto_map.runs[-1]
    assert last_start + last_size >= ROM_SIZE - 0x1000


def test_kuwagata_is_its_own_alignment(kabuto_map):
    """The canonical release answers every offset with the offset itself."""
    identity = align.for_release("Kuwagata")
    assert identity is align.IDENTITY
    for offset in (0, 1, KUWAGATA.font, KUWAGATA.script_table, ROM_SIZE - 1,
                   ROM_SIZE, ROM_SIZE * 2):
        assert identity.at(offset) == offset
        assert identity.at(offset, 0x1000) == offset
        assert identity.back(offset) == offset
        assert identity.near(offset) == offset
    assert align.for_release("kabuto") is kabuto_map


def test_a_release_with_no_map_is_refused_rather_than_guessed_at():
    with pytest.raises(FileNotFoundError):
        align.for_release("Some Unreleased Prototype")


def test_a_synthetic_kuwagata_image_translates_offsets_to_themselves(synth):
    """The same identity, reached the way the rest of the code reaches it."""
    assert synth.rom.at(KUWAGATA.font, FONT_BYTES) == KUWAGATA.font
    assert synth.rom.back(synth.table) == synth.table
    assert synth.rom.near(synth.script_a) == synth.script_a


def test_the_map_puts_the_fonts_where_rom_py_says_kabuto_keeps_them(kabuto_map):
    """Two independent derivations of the same four numbers, kept in step.

    ``navi/rom.py`` carries Kabuto's own constants, reversed by hand; the map
    is derived by aligning the dumps. Either one being wrong is the same bug,
    and the cheapest place to catch it is where they disagree.
    """
    assert kabuto_map.at(KUWAGATA.font, FONT_BYTES) == KABUTO.font
    assert kabuto_map.at(KUWAGATA.font_kanji, KANJI_FONT_BYTES) == KABUTO.font_kanji
    assert kabuto_map.at(KUWAGATA.conversion_lut, LUT_BYTES) == KABUTO.conversion_lut
    assert kabuto_map.at(KUWAGATA.script_table,
                         4 * KUWAGATA.script_table_len) == KABUTO.script_table


def test_an_offset_that_maps_comes_back_as_itself(kabuto_map):
    """back(at(x)) == x, or the pack keys derived through it name other lines.

    Not quite every offset: the cartridge stores some records twice, so a
    Kuwagata run and its duplicate can be matched to the ONE Kabuto copy of
    those bytes, and coming back names whichever copy the map lists. That is
    a handful of offsets in eight megabytes, and it is still the same bytes —
    what must never happen is coming back to somewhere that maps ELSEWHERE.
    """
    exact = 0
    elsewhere = 0
    for offset in _spread(kabuto_map):
        there = kabuto_map.at(offset)
        if there is None:
            continue
        back = kabuto_map.back(there)
        if back == offset:
            exact += 1
            continue
        elsewhere += 1
        assert back is None or kabuto_map.at(back) == there, (
            f"{offset:#x} came back as {back:#x}, which is somewhere else")
    assert exact + elsewhere > 10000, "the sample missed the map"
    assert exact > 0.99 * (exact + elsewhere)


def test_a_span_that_crosses_a_seam_is_refused(kabuto_map):
    """A table straddling two runs is not the same table twice: say None."""
    last, gap = _first_gap(kabuto_map)
    assert kabuto_map.at(last) is not None
    assert kabuto_map.at(last, 2) is None, "a span ran off the end of its run"
    assert kabuto_map.at(gap) is None, "an unmapped offset was answered anyway"
    assert kabuto_map.at(ROM_SIZE * 2) is None


def test_a_boundary_in_a_gap_is_extrapolated_from_the_data_before_it(kabuto_map):
    """``near`` closes a region at the same place relative to what it closes."""
    last, gap = _first_gap(kabuto_map)
    assert kabuto_map.near(gap) == kabuto_map.at(last) + (gap - last)
    assert kabuto_map.near(last) == kabuto_map.at(last)


# -- the map against both cartridges --------------------------------------


@pytest.mark.game
def test_every_run_the_map_claims_is_the_same_bytes_in_both_dumps(releases, raw_map):
    """A run IS the claim "these bytes are those bytes"; check it, all of it."""
    kuwagata, kabuto = releases
    for start, target, size in raw_map["runs"]:
        assert kuwagata.read(start, size) == kabuto.read(target, size), (
            f"the run at {start:#x} is not the data at {target:#x}")
    # The three pointer tables are listed apart precisely because this is not
    # true of them: they were found by what their entries POINT AT, and their
    # entries are addresses in a shifted cartridge, so their bytes differ.
    for name, (start, target, size) in raw_map["tables"].items():
        assert kuwagata.read(start, size) != kabuto.read(target, size), (
            f"{name} matches byte for byte, so it is a run, not a table")


@pytest.mark.game
def test_the_fonts_and_the_expansion_table_are_the_same_bytes_over_there(releases):
    """What the build writes into: a wrong offset here repaints the game."""
    kuwagata, kabuto = releases
    for name, offset, length in (
        ("dialogue font", KUWAGATA.font, FONT_BYTES),
        ("kanji font", KUWAGATA.font_kanji, KANJI_FONT_BYTES),
        ("1bpp expansion table", KUWAGATA.conversion_lut, LUT_BYTES),
    ):
        there = kabuto.at(offset, length)
        assert there is not None, f"the map has no {name}"
        assert kuwagata.read(offset, length) == kabuto.read(there, length), name


@pytest.mark.game
def test_the_script_master_table_maps_to_a_table_holding_the_same_scripts(releases):
    """Every entry, because the build repoints entries one at a time."""
    kuwagata, kabuto = releases
    for index in range(KUWAGATA.script_table_len):
        site = KUWAGATA.script_table + 4 * index
        there = kabuto.at(site, 4)
        assert there is not None, f"entry {index} of the master table is unmapped"
        here_script = kuwagata.ptr(site)
        there_script = kabuto.ptr(there)
        assert here_script >= 0 and there_script >= 0, f"entry {index} is not a pointer"
        # The entries differ — they are pointers into a shifted ROM — so what
        # has to agree is where they LAND.
        assert kabuto.at(here_script) == there_script, f"entry {index} points elsewhere"
        span = _vouched(kabuto, here_script, SAMPLE_BYTES)
        assert span >= MIN_SAMPLE_BYTES, f"entry {index} maps a script by {span} bytes"
        assert (kuwagata.read(here_script, span)
                == kabuto.read(there_script, span)), f"entry {index} is another script"


@pytest.mark.game
def test_the_battle_message_table_maps_to_a_table_holding_the_same_messages(releases):
    """The other table the build rewrites in place, entry by entry."""
    kuwagata, kabuto = releases
    start, end = BATTLE_MSG_TABLE
    assert end > start
    for site in range(start, end, 4):
        there = kabuto.at(site, 4)
        assert there is not None, f"the message table entry at {site:#x} is unmapped"
        here_msg = kuwagata.ptr(site)
        there_msg = kabuto.ptr(there)
        assert here_msg >= 0 and there_msg >= 0, f"{site:#x} is not a pointer"
        assert kabuto.at(here_msg) == there_msg, f"{site:#x} points elsewhere"
        span = _vouched(kabuto, here_msg, SAMPLE_BYTES)
        assert span >= MIN_SAMPLE_BYTES, f"{site:#x} maps a message by {span} bytes"
        assert (kuwagata.read(here_msg, span)
                == kabuto.read(there_msg, span)), f"{site:#x} is another message"


@pytest.mark.game
def test_every_catalogued_script_line_reads_the_same_in_the_other_release(releases):
    """The whole point of the map: a key names the same line in both dumps."""
    kuwagata, kabuto = releases
    charset = load_japanese()
    lines = build_catalog(kuwagata, charset, loose=False).of_kind("script")
    assert len(lines) >= 3443, "the catalogue lost script lines"

    placed = 0
    identical = 0
    differing = []
    for line in lines:
        there = kabuto.at(line.offset, max(1, line.length))
        if there is None:
            continue        # a line the map will not vouch for; see the floor
        placed += 1
        text, _ = decode(kabuto.data, there, charset)
        if text == line.text:
            identical += 1
        else:
            differing.append(line.key)
    assert placed >= 3400
    assert identical >= 3400
    # The residue is not a release difference: a CHAIN is several boxes the
    # engine reads through as one, so the catalogue's text for that site is
    # longer than the single box a plain decode returns there. If anything
    # else ever turns up in this list, the map moved a line.
    assert set(differing) <= CHAIN_KEYS


@pytest.mark.game
def test_the_packs_loose_sites_resolve_into_the_other_release(releases):
    """A pack is written against Kuwagata and has to serve both cartridges.

    Its keys are Kuwagata offsets, so every one of them is a place the build
    will follow through the map and WRITE to. Landing on the wrong bytes there
    is silent — the fingerprint check refuses the line and the build reports
    nothing unusual — so the pin is that the Japanese the pack remembers is
    the Japanese that is there.
    """
    kuwagata, kabuto = releases
    charset = load_japanese()
    raw = json.loads((LANGS_DIR / "es" / "menus.json").read_text(encoding="utf-8"))
    entries = [entry for entry in raw["entries"]
               if entry["key"].startswith("str:") and entry["key"].count(":") == 1]
    assert len(entries) > 900, "menus.json lost its loose keys"

    identical = 0
    placed, known_here, known_there = set(), set(), set()
    for entry in entries:
        key = entry["key"]
        offset = int(key.split(":")[1], 16)
        here, end = decode(kuwagata.data, offset, charset)
        if fingerprint(here) == entry["src"]:
            known_here.add(key)
        # The WHOLE string has to be inside one run: half of it landing in the
        # right place is a translation written over the string next door.
        there = kabuto.at(offset, max(1, end - offset))
        if there is None:
            continue
        placed.add(key)
        text, _ = decode(kabuto.data, there, charset)
        if text == here:
            identical += 1
        if fingerprint(text) == entry["src"]:
            known_there.add(key)

    assert len(placed) > 0.85 * len(entries), "the map places too few of the sites"
    assert identical == len(placed), "a site landed on different Japanese"
    # Whatever the pack still recognises here it recognises there, and nothing
    # else: a site the map places is the same line in both cartridges.
    assert known_there == known_here & placed
