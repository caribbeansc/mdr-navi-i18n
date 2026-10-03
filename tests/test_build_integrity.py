"""A build changes text and the pointers to it, and nothing else.

Every check here is on the BUILT bytes, because each failure it guards
against encoded, fitted, validated and rendered fine, and still broke the game:

- Script 35's logic was rewritten. rescue_sites took two bytes of a run of
  ``07`` instructions for a text op, and the build repointed them. Players
  were thrown onto the Cluster's station map right after the class
  president's talk, with half the story skipped.
- Script 0's header was overwritten. The last loose string in the cartridge
  counted the free tail's zeroes as its own padding and wrote its
  translation "in place" over the relocated copy of the script that 170
  master-table slots share.
- Sound samples and a compressed sheet got addresses written into them. The
  loose writer "repointed" every aligned word that spelled a moved string's
  address, and in that data four bytes such as ``f4 fe 08 08`` do so by accident.
- "Block intrusion alert!" drew three bytes of garbage in front of its text.
  A phantom line, the same string seven bytes in and reached by nothing,
  was written in place on top of it.

So, per pack, after a full build:

1. each script's code differs from the dump only in the two bytes of a text
   site's pointer;
2. every aligned word the build turned from one cartridge address into
   another is a word with evidence of being a pointer;
3. following each translated line's real pointer, script or loose, lands on
   that translation's bytes, intact.

A full build per pack, so this is marked `slow`: run it before a release
with `pytest -m slow`.
"""

import json
import struct
from pathlib import Path

import pytest

from .conftest import language_packs, pack_id
from navi.build import _encode_or_skip, Report, build
from navi.catalog import build as build_catalog
from navi.lang import Pack
from navi.rom import BASE, Rom
from navi.script import read_scripts
from navi.table import Charset

ROOT = Path(__file__).resolve().parent.parent


CASES = [(dump, pack) for dump in ("game_rom", "other_rom") for pack in language_packs()]


@pytest.fixture(scope="module", params=CASES,
                ids=[f"{'this' if d == 'game_rom' else 'other'}-{pack_id(p)}" for d, p in CASES])
def built(request):
    """(dump, dump bytes, built bytes, catalog, pack, charset), per release and pack.

    Both cartridges when both dumps are here: the pointer tables one of the
    Kabuto packs copied byte for byte only exist in that release's layout.
    """
    which, pack_dir = request.param
    dump = request.getfixturevalue(which)
    charset = Charset.load(ROOT / "data" / "charset-latin.tbl")
    subject = Rom.load(dump.path)
    pack = Pack.load(pack_dir.name, release=subject.release.name)
    catalog = build_catalog(subject, seeds=pack.loose_sites())
    before = bytes(subject.data)
    build(subject, catalog, pack, charset)
    return dump, before, bytes(subject.data), catalog, pack, charset


def _ptr(data: bytes, at: int) -> int:
    return struct.unpack_from("<I", data, at)[0] - BASE


def is_pointer_site(data: bytes, site: int) -> bool:
    """The evidence a word needs to count as a pointer, stated independently.

    Written out here rather than imported, so the test does not grade the
    build with the build's own function: the code loads it with a
    PC-relative ``ldr``, or a neighbour within 8 bytes is a cartridge
    address too. Nothing below 0x8000, which is boot code.
    """
    if site < 0x8000:
        return False
    for at in range(max(0, site - 1024), site, 2):
        half = data[at] | data[at + 1] << 8
        if half >> 11 == 0b01001 and ((at + 4) & ~3) + (half & 0xFF) * 4 == site:
            return True
    for delta in (-8, -4, 4, 8):
        at = site + delta
        if 0 <= at <= len(data) - 4 and BASE <= struct.unpack_from("<I", data, at)[0] < BASE + len(data):
            return True
    return False


@pytest.mark.game
@pytest.mark.slow
def test_script_code_changes_only_at_text_pointers(built):
    game_rom, before, after, catalog, _, _ = built
    table = game_rom.release.script_table
    damaged = []
    for script in read_scripts(game_rom):
        slots = [i for i in range(game_rom.release.script_table_len)
                 if _ptr(before, table + 4 * i) == script.offset]
        homes = {_ptr(after, table + 4 * i) for i in slots}
        assert len(homes) == 1, f"script {script.index}: its slots disagree: {homes}"
        home = homes.pop()
        if not script.sites:
            continue
        code_end = min(site.text_at for site in script.sites)
        pointers = {site.pointer_at + k for site in script.sites for k in (0, 1)}
        copy = after[home:home + code_end]
        for i in range(code_end):
            if copy[i] != script.data[i] and i not in pointers:
                damaged.append(f"script {script.index} +{i:04X}: "
                               f"{script.data[i]:02X} -> {copy[i]:02X}")
    assert not damaged, (
        f"{len(damaged)} bytes of script CODE changed (first few: {damaged[:8]})")


@pytest.mark.game
@pytest.mark.slow
def test_every_repointed_word_is_a_pointer(built):
    """A repoint changes whole words from one cartridge address to another.

    So the check walks runs of changed aligned words and looks only at runs
    where EVERY word went from an address to an address: a pointer table, or a
    lone pointer. A recompressed sheet rewrites a stretch of mixed data, and a
    word in it may spell an address by chance; that is the sheet's business,
    not a repoint.
    """
    _, before, after, _, _, _ = built
    size = len(before)

    def address(value: int, limit: int) -> bool:
        return BASE <= value < BASE + limit

    suspicious = []
    run: list[int] = []
    for at in range(0, size - 3 + 4, 4):
        changed = at < size - 3 and before[at:at + 4] != after[at:at + 4]
        if changed:
            run.append(at)
            continue
        if run and all(address(struct.unpack_from("<I", before, w)[0], size)
                       and address(struct.unpack_from("<I", after, w)[0], len(after))
                       for w in run):
            for w in run:
                if not is_pointer_site(before, w):
                    suspicious.append(
                        f"{w:#08x}: {struct.unpack_from('<I', before, w)[0]:#010x} -> "
                        f"{struct.unpack_from('<I', after, w)[0]:#010x}")
        run = []
    assert not suspicious, (
        f"{len(suspicious)} words that are not pointers were repointed: {suspicious[:8]}")


@pytest.mark.game
@pytest.mark.slow
def test_each_translation_is_where_its_pointer_leads(built):
    game_rom, before, after, catalog, pack, charset = built
    report = Report(language=pack.code)
    table = game_rom.release.script_table
    # Fields gfx.json's extra_strings rewrites AFTER the loose pass, on purpose:
    # a fused record keeps its kana there so that writer can put the name in.
    claimed: set[int] = set()
    gfx = json.loads((pack.path / "gfx.json").read_text(encoding="utf-8"))
    for entry in gfx.get("extra_strings", {}).values():
        for site in entry["sites"]:
            at = game_rom.at(int(str(site), 16), int(entry["room"]))
            if at is not None:
                claimed.update(range(at, at + int(entry["room"])))
    scripts = {s.index: s for s in read_scripts(game_rom)}
    broken = []
    for line in catalog.lines.values():
        text = pack.translation_for(line.key, line.text)
        if text is None:
            continue
        payload = _encode_or_skip(text, charset, line.key, report)
        if payload is None:
            continue
        if line.kind == "script":
            script = scripts[line.script]
            slot = next(i for i in range(game_rom.release.script_table_len)
                        if _ptr(before, table + 4 * i) == script.offset)
            home = _ptr(after, table + 4 * slot)
            for site in script.sites:
                if site.text_at != line.relative:
                    continue
                rel = after[home + site.pointer_at] | after[home + site.pointer_at + 1] << 8
                if after[home + rel:home + rel + len(payload)] != payload:
                    broken.append(f"{line.key} via +{site.pointer_at - 1:04X}")
        else:
            real = [s for s in line.pointers if is_pointer_site(before, s)]
            if not real:
                continue
            target = _ptr(after, real[0])
            got = after[target:target + len(payload)]
            if any(got[i] != payload[i] and target + i not in claimed
                   for i in range(len(payload))):
                broken.append(f"{line.key} via {real[0]:#x}")
    assert not broken, (
        f"{len(broken)} translations are not intact where the game reads them "
        f"(first few: {broken[:8]})")


@pytest.mark.game
@pytest.mark.slow
def test_no_japanese_left_standing_that_nobody_vetted(built):
    """Every Japanese run the build leaves is known to the pack's baseline.

    The build prints this count and it had grown to 203 that nobody read:
    193 were tiles, code and level data the prose model mistook for writing,
    and the real line among them (a joke the cast's bully says, "your save
    data was destroyed — cry") went unseen behind them. Prose findings now
    need something to reach them, the baseline is keyed by Kuwagata offsets so
    one file serves both releases, and what is left was checked by hand.
    A NEW finding fails here: translate it, or vet it and --accept it.
    """
    from navi import leftovers as L
    from navi.table import load_japanese

    dump, before, after, catalog, pack, charset = built
    original = Rom(bytearray(before), dump.path)
    result = Rom(bytearray(after), dump.path)
    skip = (L.script_area(original) + L.translated_area(original, catalog, pack)
            + L.data_areas(original))
    found = L.find(original, result, load_japanese(), charset, skip=skip)
    known = L.load_baseline(pack.path / "leftovers.json")
    fresh = [f"{f.key} ({f.why})" for f in found if f.key not in known]
    assert not fresh, f"{len(fresh)} Japanese runs nobody vetted: {fresh[:10]}"
