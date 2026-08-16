"""Catching the mistakes that only show up on a real screen.

The text box is 32 characters wide and two rows tall, and there is no scrolling.
A line that overruns is not a rendering glitch: the rest of the sentence is
simply never drawn. These checks are the difference between finding that out
here and finding it out three hours into a playthrough.
"""

from __future__ import annotations

from dataclasses import dataclass

from .catalog import Catalog
from .lang import Pack, fingerprint
from .table import Charset, TableError, TAG_RE, encode, lines_of, rows_by_box

#: Columns the dialogue window actually SHOWS. The tile buffer behind it is 32
#: wide and the engine happily types into the hidden tiles, so overflow is
#: invisible rather than wrapped — which is why this was measured, not read
#: from the code: no row of the game's own text exceeds 22, and screenshots
#: crop at exactly 22 with a portrait on screen.
LINE_WIDTH = 22

#: Rows the box shows at once.
BOX_ROWS = 2

#: Tags that must survive translation, because the game needs them.
REQUIRED_TAGS = {"PLAYER", "MEDABOT", "YESNO", "FACE", "FACE7", "SFX", "DELAY"}


@dataclass
class Problem:
    key: str
    kind: str
    detail: str

    def __str__(self) -> str:
        return f"{self.key}: {self.kind} — {self.detail}"


def _tags(text: str) -> list[tuple[str, str | None]]:
    return [(m.group(1), m.group(2)) for m in TAG_RE.finditer(text)]


def check(catalog: Catalog, pack: Pack, charset: Charset) -> list[Problem]:
    """Every problem in a pack, in the order a translator should fix them."""
    problems: list[Problem] = []
    sources = catalog.sources()

    for key, entry in sorted(pack.entries.items()):
        if not entry.t:
            continue
        source = sources.get(key)
        if source is None:
            problems.append(Problem(key, "orphan",
                                    "no line in this dump has that key"))
            continue
        if entry.src and entry.src != fingerprint(source):
            problems.append(Problem(key, "stale",
                                    "the Japanese has changed since this was written"))

        try:
            encode(entry.t, charset)
        except TableError as exc:
            problems.append(Problem(key, "unencodable", str(exc)))
            continue

        want = {name for name, _ in _tags(source) if name in REQUIRED_TAGS}
        have = {name for name, _ in _tags(entry.t) if name in REQUIRED_TAGS}
        for missing in sorted(want - have):
            problems.append(Problem(key, "lost tag", f"<{missing}> is in the original"))
        for extra in sorted(have - want):
            problems.append(Problem(key, "new tag", f"<{extra}> was not in the original"))

        line = catalog.lines.get(key)
        if line is not None and line.kind == "loose":
            # The build seals every payload with a 0x00 terminator unless the
            # text ends the string itself; capacity has to be measured the
            # same way or the last character silently eats the terminator.
            size = len(encode(entry.t, charset))
            if not entry.t.endswith("<END>"):
                size += 1
            if line.fixed and size > line.length:
                problems.append(Problem(
                    key, "over capacity",
                    f"{size} bytes into a fixed {line.length}-byte record; "
                    f"about {line.length - 1} characters fit"))
            elif not line.pointers and size > line.length:
                problems.append(Problem(
                    key, "over capacity",
                    f"{size} bytes into {line.length}, and nothing points at it "
                    f"so it cannot be moved"))

        # The box is 22 columns wide, but only its FIRST row gets all of
        # them: on the second the last cell is never drawn, so a 22nd
        # character silently disappears (proved with an A-Z ruler in-game,
        # and the Japanese agrees — 38 of its 22-column rows are first rows
        # and only 2 are not).
        for number, row in enumerate(rows_by_box(entry.t), 1):
            limit = LINE_WIDTH if row.first_in_box else LINE_WIDTH - 1
            if len(row.text) > limit:
                problems.append(Problem(
                    key, "too wide",
                    f"row {number} is {len(row.text)} characters, "
                    f"{'the box fits' if row.first_in_box else 'a second row fits'} {limit}"))

        # The box clears on <WAIT> and <CLEAR>, so count rows per screenful.
        shown = 0
        for chunk in TAG_RE.sub(lambda m: "\x00" if m.group(1) in ("WAIT", "CLEAR")
                                else ("\n" if m.group(1) == "NL" else ""),
                                entry.t).split("\x00"):
            shown = max(shown, len([r for r in chunk.split("\n") if r]))
        if shown > BOX_ROWS:
            problems.append(Problem(
                key, "too tall",
                f"{shown} rows between pauses, the box shows {BOX_ROWS}"))

    return problems


def summary(problems: list[Problem]) -> str:
    if not problems:
        return "No problems found."
    counts: dict[str, int] = {}
    for problem in problems:
        counts[problem.kind] = counts.get(problem.kind, 0) + 1
    head = ", ".join(f"{n} {kind}" for kind, n in sorted(counts.items()))
    return f"{len(problems)} problems ({head})"
