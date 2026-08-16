"""Every drawn glyph must keep its ink inside columns 2-6.

The battle unit panel and the name-entry keyboard bake a 1px outline around
each glyph inside its own 8px cell, and every NATIVE capital and digit runs
to column 6 with its outline on column 7. The only background pixel that can
separate a native glyph's outline from ours is our own column 0-1 — so drawn
ink starts at column 2 (outline on 1, background on 0) and ends by column 6
(outline on 7, never clipped). Caught by eye twice ("Bosq", "Grapnel");
this test replaces the eyeballing.
"""

from navi.font import GLYPH_WIDTH, read_glyphs


def ink_columns(rows):
    return [x for row in rows for x in range(GLYPH_WIDTH) if not row & (0x80 >> x)]


def test_drawn_ink_stays_inside_columns_2_to_6():
    offenders = []
    for name, glyph in read_glyphs().items():
        cols = ink_columns(glyph.rows)
        if not cols:
            continue
        if min(cols) < 2 or max(cols) > 6:
            offenders.append(f"{name!r} spans columns {min(cols)}-{max(cols)}")
    assert not offenders, (
        "glyphs outside columns 2-6 lose their outline and glue to the "
        "neighbouring letter in the battle panel and keyboard: "
        + ", ".join(offenders)
    )
