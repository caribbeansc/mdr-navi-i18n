"""A loose line that carries on through <CLEAR> is catalogued whole.

The engine reads a string until a 0x00 or an <END>. A <CLEAR> only clears
the box, and the text behind it is the same string. `decode` stops at
<CLEAR>, so three loose lines were catalogued as their first box alone, and
their translations, sealed with 0x00, cut the scene short. The Cluster's
asteroid alarm lost the eleven boxes that send the party to the Pyramid
Block, and the scene where the Medabot hauls something out of the water
lost its next thirteen.
"""

import pytest

from navi.catalog import build as build_catalog, read_chain
from navi.table import load_japanese

from .conftest import language_packs


@pytest.mark.game
def test_every_loose_chain_is_read_to_its_end(game_rom):
    charset = load_japanese()
    catalog = build_catalog(game_rom, charset)
    data = bytes(game_rom.data)
    starts = {line.offset for line in catalog.of_kind("loose")}
    short = []
    for line in catalog.of_kind("loose"):
        if line.fixed:
            continue
        whole, _ = read_chain(data, line.offset, charset, starts - {line.offset})
        if whole != line.text:
            short.append(line.key)
    assert not short, f"loose lines catalogued shorter than the engine reads them: {short}"


@pytest.mark.game
@pytest.mark.parametrize("pack_dir", language_packs(), ids=lambda p: p.name)
def test_a_translated_chain_carries_every_box(game_rom, pack_dir):
    """A chain's translation keeps at least as many boxes as the original."""
    from navi.lang import Pack

    pack = Pack.load(pack_dir.name, release=game_rom.release.name)
    catalog = build_catalog(game_rom, seeds=pack.loose_sites())
    thin = []
    for line in catalog.of_kind("loose"):
        head = line.text.split("<CLEAR>", 1)
        if len(head) < 2 or not head[1]:
            continue          # not a chain: nothing after its first <CLEAR>
        text = pack.translation_for(line.key, line.text)
        if text is None:
            continue
        # Every segment after a <CLEAR> has to be there: count the boxes of
        # the continuation alone, so an extra break in the head (a long
        # first box split in two) cannot hide a box missing further on.
        def tail_boxes(t: str) -> int:
            rest = t.split("<CLEAR>", 1)[1] if "<CLEAR>" in t else ""
            return rest.count("<WAIT>") + rest.count("<CLEAR>")
        if tail_boxes(text) < tail_boxes(line.text):
            thin.append(f"{line.key}: {tail_boxes(text)} boxes after the first "
                        f"<CLEAR> for {tail_boxes(line.text)}")
    assert not thin, f"chains translated short: {thin}"
