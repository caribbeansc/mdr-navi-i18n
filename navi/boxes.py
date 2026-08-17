"""What each kind of box on screen can actually draw.

A translation is not right or wrong on its own: it is right or wrong for the
box that draws it. The cartridge has several, and they differ in both things
that matter — how many columns they draw before cutting, and which control
codes they honour — so the same line can be perfect in one and mangled in
another.

Two mistakes made this worth writing down. The dialogue box draws 22 columns
on a row and 21 on the second, and 318 lines were quietly losing their last
letter to that. And the Medarreloj's description bars honour NO control code
at all: `<NL>` there swallows itself AND the character after it, so "Ataque de
combate<NL>básico" reached the screen as `Ataque de combateásico`. Both read
like clipping; neither was.

Checking each line against its BOX, rather than keeping a list of individual
sites that were allowed to break the rule, is what makes the check hold as the
pack grows: "the robattle chatter is a dialogue box" is one fact, not forty
exemptions.

Every width here was measured in the emulator with an A-Z-0-9 ruler written
into the field, not inferred: the last character that appears is the width.
Where a width is not known yet it is ``None``, and the width check skips it
while the code check still applies — an honest gap beats a guessed number.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Codes the ordinary dialogue box reads. It is the permissive one: it pages
#: on <WAIT>, clears on <CLEAR>, breaks rows on <NL>, swaps portraits, splices
#: the player's and the medabot's names.
DIALOGUE_CODES = frozenset({
    "NL", "WAIT", "CLEAR", "END", "FACE", "FACE7", "SFX", "MUSIC",
    "DELAY", "PLAYER", "MEDABOT", "YESNO", "X", "K",
})

#: The result composer splices its pieces itself: 0xF0 separates them, 0xF1
#: marks a row and the name inserts are pieces of their own — the Japanese
#: uses all three, so they are the composer's own vocabulary, not additions.
PIECE_CODES = frozenset({"X", "NL", "PLAYER", "MEDABOT"})


@dataclass(frozen=True)
class Box:
    """One kind of box, and what it can draw."""

    name: str
    #: Visible columns on the first row, or None when not measured yet.
    columns: int | None
    #: Columns on later rows. The dialogue box draws one fewer there — its
    #: last cell is never painted — so this is not always ``columns``.
    later_rows: int | None
    #: Control codes the box honours. Anything else it does not merely
    #: ignore: in the description bars <NL> eats the next character too.
    codes: frozenset
    #: What it draws, for the failure message.
    note: str = ""


#: The event-script box, and every pool that draws through it: NPC lines, the
#: robattle chatter, the item-get templates, the menu prompts. 22/21 proved
#: with an A-Z ruler in-game, and the cartridge agrees — 38 of its 22-column
#: rows are first rows and only 2 are not.
DIALOGUE = Box("dialogue", 22, 21, DIALOGUE_CODES,
               "the dialogue box: 22 columns, 21 on later rows")

#: The medal card's description bar in the Medarreloj — ONE box, shared by the
#: aptitude page and the Medaforce page. 26 columns, measured three times with
#: rulers written into both of its fields; unlike the dialogue box, its second
#: row does NOT lose a cell, so both rows draw 26. Two dead cells sit to the
#: right of the text that the renderer never uses, which is what an earlier
#: report mistook for a 28-column box.
MEDAL_DESCRIPTION = Box("medal-description", 26, 26, frozenset(),
                        "the medal card's description bar")

#: The part card's description bar. 28 columns, measured the same way — the
#: ruler reaches '1' — and both of its rows draw 28. Each row is its OWN field
#: in the ROM, not a row break, which is why neither loses a cell.
PART_DESCRIPTION = Box("part-description", 28, 28, frozenset(),
                       "the part card's description bar")

#: The line at +0x78 of an aptitude record, drawn by the ROTATION page. 22
#: characters are safe; which screen exactly draws it is not pinned down.
ROTATION_LINE = Box("rotation-line", 22, 22, frozenset(),
                    "the ROTATION page's line")

#: The result composer's pieces. Their own rules live in navi/build.py
#: (piece_skeleton, piece_cells); here they only need to keep 0xF0.
COMPOSER = Box("composer-piece", None, None, PIECE_CODES,
               "a result-composer piece")

#: The battle screen's own bars: the pre-robattle prompt, the drive/rotation
#: lines of the medal page. Wider than the dialogue box — "¡Robobatalla con
#: START!" is 23 characters and renders whole (work/atlas/shots/12-vs.png) —
#: but not measured with a ruler yet, so the width check skips it rather than
#: hold ten correct lines to a limit that is known to be wrong.
BATTLE_UI = Box("battle-ui", None, None, frozenset(),
                "a battle-screen bar, width not measured yet")

#: Fixed-width name slots, reached by index. Plain text, no codes; the width
#: is the slot's, and tests/test_slot_tables.py enforces it per table.
NAME_FIELD = Box("name-field", None, None, frozenset(),
                 "a fixed-width name slot")


#: Which box draws the strings in a range, as ``(start, end, box)``. Ranges
#: not listed fall back to :data:`DIALOGUE`, which is both the commonest and
#: the most permissive, so an unclassified region is reported rather than
#: silently held to the wrong rule (see :func:`unclassified`).
REGIONS: tuple[tuple[int, int, Box], ...] = (
    # -- the description tables, none of which honour a single code ---------
    # The aptitude table starts at 0x090744, not earlier: 0x0906F4-0x090744 is
    # the action-name table, ten entries of 8 bytes, which is why "base
    # 0x0906F4 + n*0xAC" never lined up with the fields that were on screen.
    (0x0906F4, 0x090744, NAME_FIELD),             # action names, stride 8
    (0x090744, 0x090BF8, MEDAL_DESCRIPTION),      # aptitudes, 7 records of 0xAC
    (0x090BF8, 0x092818, MEDAL_DESCRIPTION),      # Medaforces, 60 of 0x78
    # Up to the leg table, not to the last NAME at 0x0956D8: that record's own
    # two description fields sit at +0x18 and +0x4C, past its name.
    (0x0930D8, 0x095758, PART_DESCRIPTION),       # skills and part effects
    (0x095758, 0x095AF8, PART_DESCRIPTION),       # leg types
    # -- fixed-width name slots, reached by index -------------------------
    (0x092998, 0x093098, NAME_FIELD),   # medal families, medal and part names
    (0x09309D, 0x0930D8, NAME_FIELD),   # effect names (the 9-cell panel row)
    # -- the battle screen -------------------------------------------------
    (0x4BF000, 0x4C8000, BATTLE_UI),
    # -- the composites ----------------------------------------------------
    (0x4CC800, 0x4CCE00, COMPOSER),
)


def box_for(offset: int) -> Box:
    """The box that draws the string at ``offset``."""
    for start, end, box in REGIONS:
        if start <= offset < end:
            return box
    return DIALOGUE


def is_classified(offset: int) -> bool:
    """Whether ``offset`` is covered by a measured region rather than the default."""
    return any(start <= offset < end for start, end, _ in REGIONS)
