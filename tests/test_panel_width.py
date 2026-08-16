"""The battle part panel's effect line is NINE cells wide, and it overflows
into its neighbour instead of clipping.

Cycling parts with the panel's arrows draws four rows: part name, effect name,
行動 + action, 回数/AP. Each row owns a fixed run of BG0 tiles, two tiles per
character cell. The effect row's run starts at tile 0xC8 and the terrain bar's
run starts at 0xDA, so the effect row has (0xDA - 0xC8) / 2 = 9 cells — and a
tenth character is not dropped, it is drawn into the bar's first tile, which
is why an 11-character effect put "ma" on top of "--------- BOSQ". Measured
with probe strings of 9, 10 and 11 characters: 9 is clean, 10 spills one cell,
11 spills two. The Japanese originals never exceed 9 either.

Two ROM tables feed rows like this one and are checked here by the addresses
the packs record: the skill/effect names (24-byte field, stride 0x80) and the
Medaforce names (16-byte field, stride 0x78).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

PACK = Path(__file__).resolve().parent.parent / "langs" / "es"

VISIBLE_CELLS = 9

#: (first name field, stride, last name field) for each table of panel names.
NAME_TABLES = (
    (0x0930D8, 0x80, 0x0956D8),   # skill / part effect names
    (0x090BF8, 0x78, 0x0927A0),   # Medaforce names
)

TAG = re.compile(r"<[^>]+>")


def cells(text: str) -> int:
    """Display cells: every tag is one control code, not text."""
    return len(TAG.sub("X", text))


def name_field(address: int) -> bool:
    return any(
        first <= address <= last and (address - first) % stride == 0
        for first, stride, last in NAME_TABLES
    )


def panel_names() -> dict[int, str]:
    """Every translation the packs aim at one of those name fields."""
    found: dict[int, str] = {}
    gfx = json.loads((PACK / "gfx.json").read_text(encoding="utf-8"))
    for entry in gfx.get("extra_strings", {}).values():
        for site in entry["sites"]:
            at = int(site, 16)
            if name_field(at):
                found[at] = entry["t"]
    menus = json.loads((PACK / "menus.json").read_text(encoding="utf-8"))
    for entry in menus["entries"]:
        key = entry["key"]
        if not key.startswith("str:"):
            continue
        at = int(key.split(":")[1], 16)
        if name_field(at):
            found[at] = entry["t"]
    return found


def test_the_pack_aims_at_these_tables():
    assert len(panel_names()) > 100


def test_no_panel_name_overruns_the_nine_visible_cells():
    offenders = [
        f"0x{at:06X} {text!r} is {cells(text)} cells"
        for at, text in sorted(panel_names().items())
        if cells(text) > VISIBLE_CELLS
    ]
    assert not offenders, (
        "the battle panel's effect row holds nine cells and writes the rest "
        "over the terrain bar's tiles: " + ", ".join(offenders)
    )


def test_panel_names_are_single_line():
    offenders = [
        f"0x{at:06X} {text!r}"
        for at, text in sorted(panel_names().items())
        if "<NL>" in text or "<WAIT>" in text
    ]
    assert not offenders, (
        "these fields are one row of a fixed panel, not a text box: "
        + ", ".join(offenders)
    )
