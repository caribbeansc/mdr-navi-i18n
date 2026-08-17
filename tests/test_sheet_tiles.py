"""Two labels that share a sheet tile must put the same letter in it.

The tile sheets are DEDUPLICATED atlases: where two of the game's words drew
the same 8x8 pixels, the sheet stores that tile once and both words point at
it. So a label's rectangle is not private — one cell of it can belong to
another label as well, and the build simply draws them in order, last write
winning.

Nothing refuses that. It shipped once: in battle-action-names the shoot plate
and the set-trap plate share sheet tile 0x0A (both are ``tile_rect``
``[2, 2, 1, 1]``), which is why the Spanish spells them ``Tir`` and ``Tra`` —
the letter they share is ``r``. The English first draft used ``Sho`` and
``Set``, so the cell was written ``o`` and then ``e``, and the shoot plate
would have drawn ``Sh`` followed by a hybrid glyph nobody chose. The build
reported nothing: both labels fit their rectangles, and each is correct on its
own.

The rule this pins is the one the sheets' own notes state: where two pieces of
TEXT claim a cell, they have to agree about it. Furniture — the plate faces,
bevels and rules that over-fill a rectangle to paint it — is excluded by the
only thing that distinguishes it mechanically: it writes more characters than
the rectangle has tiles, because it is paint rather than writing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from .conftest import language_packs, pack_id

#: The one overlay both packs share on purpose: the rotation tab's edge is
#: composed by drawing two symbols into the same cell, not two words.
INTENTIONAL = {("status-tab-bar", (0, 23))}


def _writes(label: dict) -> dict[tuple[int, int], str]:
    """The cell each character of a label lands in, one character per tile."""
    x, y, width, _ = label["tile_rect"]
    text = label.get("text", "")
    if len(text) > width:
        return {}          # paint, not writing: it over-fills to cover the box
    return {(x + i, y): character for i, character in enumerate(text)}


@pytest.mark.parametrize("pack", language_packs(), ids=pack_id)
def test_labels_sharing_a_tile_agree_on_it(pack: Path):
    clashes = []
    for sheet in json.loads((pack / "gfx.json").read_text("utf-8"))["sheets"]:
        claimed: dict[tuple[int, int], tuple[str, str]] = {}
        for label in sheet.get("labels", []):
            if "tile_rect" not in label:
                continue
            for cell, character in _writes(label).items():
                owner = claimed.get(cell)
                if (owner and owner[1] != character
                        and (sheet["name"], cell) not in INTENTIONAL):
                    clashes.append(
                        f"{sheet['name']} tile {cell}: {owner[0]!r} draws "
                        f"{owner[1]!r} there and {label['key']!r} draws "
                        f"{character!r}")
                claimed[cell] = (label["key"], character)
    assert not clashes, (
        "labels fighting over a shared tile — the later one wins and the "
        f"earlier one is left drawing a letter it did not choose: {clashes}")
