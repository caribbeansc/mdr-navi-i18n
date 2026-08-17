"""Every line is checked against the BOX that draws it, not against a list.

A box that does not support a control code does worse than ignore it: in the
Medarreloj's description bars ``<NL>`` swallows itself AND the character after
it, so "Ataque de combate<NL>básico" reached the screen as ``Ataque de
combateásico`` and "Ataca al Medabot<NL>más cercano" as ``Ataca al Medabotás
cerca``. Both looked like clipping and neither was.

The first version of this test kept a baseline of the individual sites that
used a code their Japanese did without — fifty-eight of them. That was the
wrong shape: forty of those were one claim, "the robattle chatter draws through
the dialogue box", written out forty times. navi/boxes.py says which box draws
what instead, so the rule is about kinds of box and holds for lines nobody has
written yet.

That claim then turned out to be FALSE, which is the better argument for this
shape. The chatter bar does not page: a <WAIT> there is not honoured and
everything after it is silently not drawn ("¿Robobatalla? Acepto,<NL>¿pero
podrás<WAIT>competir?" reached a player's screen without its last word). One
line in boxes.py — ROBATTLE_CHATTER, whose codes are the <NL>/<END>/<PLAYER>
that all 412 of its Japanese lines use and nothing more — turned thirty-seven
mangled lines into thirty-seven failures here. As forty named exceptions, the
same bug would have stayed invisible.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from navi.boxes import box_for, is_classified
from navi.table import TAG_RE, rows_by_box

from .conftest import language_packs, pack_id

ROOT = Path(__file__).resolve().parent.parent


def _codes(text: str) -> set[str]:
    """Control codes in a line. ``<B:xx>`` is a raw byte, not a code."""
    return {m.group(1) for m in TAG_RE.finditer(text) if m.group(1) != "B"}


def _pack_sites(pack: Path) -> dict[int, tuple[str, str]]:
    """Every non-script translation of a pack, as ``offset -> (text, where)``."""
    out: dict[int, tuple[str, str]] = {}
    gfx = json.loads((pack / "gfx.json").read_text("utf-8"))
    for key, entry in gfx["extra_strings"].items():
        for site in entry.get("sites", []):
            out[int(str(site), 16)] = (entry.get("t", ""), f"extra:{key}")
    for entry in json.loads((pack / "menus.json").read_text("utf-8"))["entries"]:
        if entry["key"].startswith("str:") and entry.get("t"):
            out[int(entry["key"][4:], 16)] = (entry["t"], entry["key"])
    return out


@pytest.mark.parametrize("pack", language_packs(), ids=pack_id)
def test_every_line_only_uses_codes_its_box_honours(pack):
    guilty = []
    for at, (text, where) in sorted(_pack_sites(pack).items()):
        box = box_for(at)
        stray = _codes(text) - box.codes
        if stray:
            guilty.append(f"{at:06X} ({where}) draws in {box.note}, "
                          f"which does not honour {sorted(stray)}: {text!r}")
    assert not guilty, (
        "codes the box will not honour — and an unsupported <NL> eats the "
        f"character after it, it does not just vanish: {guilty}")


@pytest.mark.parametrize("pack", language_packs(), ids=pack_id)
def test_no_line_overruns_the_box_that_draws_it(pack):
    """Only where the width was measured; an unmeasured box is skipped.

    langs/<code>/wide.json holds the rows still too wide, and they are DEBT, not
    exceptions: the description tables were translated before their boxes had
    been measured, so a few hundred rows are cut on screen today. What this
    guards is that the number only goes down — a new over-wide row is not in
    the file and fails here.
    """
    debt_path = pack / "wide.json"
    debt = set(json.loads(debt_path.read_text("utf-8"))["known"]
               if debt_path.is_file() else [])
    guilty = []
    for at, (text, where) in sorted(_pack_sites(pack).items()):
        box = box_for(at)
        if box.columns is None:
            continue
        for row in rows_by_box(text):
            limit = box.columns if row.first_in_box else box.later_rows
            if limit is None or len(row.text) <= limit:
                continue
            if f"{at:06X}:{len(row.text)}" in debt:
                continue
            guilty.append(f"{at:06X} ({where}) {len(row.text)} columns in "
                          f"{box.note} ({limit}): {row.text!r}")
    assert not guilty, f"rows the box cuts off, and not known debt: {guilty[:12]}"


def test_the_regions_that_matter_are_classified():
    """The description tables must not fall back to the dialogue default.

    The fallback is the permissive box, so an unclassified description table
    would pass every check above while being cut on screen. This pins the
    ranges navi/boxes.py claims to know.
    """
    for at in (0x090754, 0x090BF8 + 0x10, 0x0930F0, 0x09579C, 0x4CC96D):
        assert is_classified(at), f"{at:06X} falls back to the dialogue box"
