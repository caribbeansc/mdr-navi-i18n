"""Japanese that survived the build, found without playing the game.

Every "this is still in Japanese" bug reported from a playthrough has had the
same shape: a run of bytes the build never touched, in a table the pointer
scan cannot see, that the game draws anyway. The medal family names, eighteen
part names and thirty-nine cluster room names were each found one screenshot
at a time. They did not have to be.

A leftover is visible in the built ROM itself: a run that is BYTE-IDENTICAL
to the Japanese dump and still reads as text. The hard half is telling text
from the 8 MB of tiles and ARM code that also decode into plausible kana, and
two different signals do it, because neither is enough alone:

* **Prose.** :class:`navi.strings.LanguageModel`, trained on the event
  scripts, recognises the game's own writing. It catches loose sentences —
  but NOT tables of katakana proper nouns (クワガタ, マスクドカブト), which
  score worse than tile data, because the model learned hiragana.

* **Neighbourhood.** A name that we missed sits among names we translated.
  Counting how many bytes the build rewrote within ±0x40 separates "a table
  we are working on" from "level data": all three tables above sat in
  neighbourhoods with 24 to 115 rewritten bytes, and tile data sits in
  neighbourhoods with none.

Precision is the lesser worry: what matters is that a NEW leftover stands
out, so the findings are diffed against a baseline of offsets (never text —
Japanese must not enter the repository) and the build reports only what the
baseline does not already know.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .rom import Rom
from .strings import LanguageModel
from .table import Charset

#: Single-byte codes that spell kana, and the two kanji lead bytes.
KANA = frozenset(range(0x01, 0x9E))
KANJI_LEAD = frozenset({0xE0, 0xE1})

#: Shorter than this, or spelled with fewer distinct codes, and a run is a
#: coincidence however it scores.
MIN_CHARS = 4
MIN_DISTINCT = 4

#: -- the prose signal ---------------------------------------------------
#: Runs below this look like tiles, not writing.
MIN_SCORE = -4.6
#: Level and tile data is full of runs like 0x01 0x02 0x01 0x02, which decode
#: as アイアイ and score like prose because the scripts do contain those
#: pairs. Written words do not repeat two syllables forever.
MIN_VARIETY = 0.45

#: How much of a run has to sit on re-used codes before it reads as garbage
#: rather than as Japanese with a few wrong letters.
GARBLED_SHARE = 0.5

#: -- the neighbourhood signal -------------------------------------------
#: How far around a run to look, and how many rewritten bytes make that
#: neighbourhood "text we are translating".
NEIGHBOURHOOD = 0x40
MIN_NEIGHBOURS = 24


@dataclass(frozen=True)
class Leftover:
    """One run of Japanese the build left standing."""

    offset: int
    length: int
    chars: int
    #: What noticed it: "prosa", "vecindad", or both.
    why: str
    #: True when MOST of the run sits on codes the font redraws as Latin, so
    #: on screen it is not even Japanese — it is garbage ("H¿ガP", "th×rlr").
    #: 107 of the 157 kana codes are re-used, so "any of them" would be true
    #: of nearly everything; what marks a run as unreadable is the share.
    garbage: bool

    @property
    def key(self) -> str:
        return f"{self.offset:06X}:{self.length}"


def reused_codes(japanese: Charset, latin: Charset) -> set[int]:
    """Kana codes the font build redraws as a Latin letter."""
    return {code for code in KANA
            if japanese.decode.get(code) and latin.decode.get(code)
            and japanese.decode[code] != latin.decode[code]}


#: Byte ranges that decode as kana but are data, verified by looking. The
#: cast table's records are 0x10 bytes with an 8-character name and a
#: terminator; everything after that is portrait and sprite indices — small
#: ascending numbers, which the charset happily reads as ウアテく.
DATA_AREAS = tuple((0x7ECA90 + i * 0x10 + 9, 0x7ECA90 + (i + 1) * 0x10)
                   for i in range(86))


def script_area(original: Rom) -> list[tuple[int, int]]:
    """Where the event scripts live, as ``(start, end)`` pairs.

    Untranslated dialogue is not what this scan is for: the catalog already
    names every line of it and the pack shows which have no translation yet.
    Left in, the story backlog buries the handful of findings that are
    actually invisible to the rest of the tooling.
    """
    from .script import script_bounds
    return [(at, at + size) for at, size in script_bounds(original)]


def translated_area(original: Rom, catalog, pack) -> list[tuple[int, int]]:
    """Where strings the pack DID translate used to live.

    A translation longer than its Japanese is written to free space and the
    pointer repointed, which leaves the Japanese sitting there, dead. Those
    bytes look exactly like a leftover and are not one — 'Acción' and
    'Destreza' were both reported that way before this.
    """
    out = []
    for line in catalog.of_kind("loose"):
        if pack.translation_for(line.key, line.text):
            out.append((line.offset, line.offset + max(line.length, 1)))
    return out


def find(original: Rom, built: Rom, japanese: Charset, latin: Charset,
         model: LanguageModel | None = None,
         skip: list[tuple[int, int]] | None = None) -> list[Leftover]:
    """Every untouched Japanese run in ``built`` that reads as text."""
    model = model or LanguageModel.from_scripts(original)
    reused = reused_codes(japanese, latin)
    source = bytes(original.data)
    data = bytes(built.data)
    limit = min(len(source), len(data))

    # A prefix sum over "the build rewrote this byte", so the neighbourhood
    # of a run is one subtraction rather than a scan.
    rewritten = [0] * (limit + 1)
    for i in range(limit):
        rewritten[i + 1] = rewritten[i] + (source[i] != data[i])

    def neighbours(low: int, high: int) -> int:
        a = min(max(low - NEIGHBOURHOOD, 0), limit)
        b = min(max(high + NEIGHBOURHOOD, 0), limit)
        return rewritten[b] - rewritten[a]

    skip = script_area(original) if skip is None else skip
    blocked = bytearray(limit)
    for low, high in skip:
        for at in range(max(low, 0), min(high, limit)):
            blocked[at] = 1

    out: list[Leftover] = []
    i = 0
    while i < limit:
        if blocked[i]:
            i += 1
            continue
        byte = data[i]
        if byte != source[i] or (byte not in KANA and byte not in KANJI_LEAD):
            i += 1
            continue
        j = i
        while j < limit and data[j] == source[j] and (
                data[j] in KANA or data[j] in KANJI_LEAD):
            j += 1
        run = data[i:j]
        i = max(j, i + 1)
        chars = _chars(run)
        distinct = len(set(run))
        if chars < MIN_CHARS or distinct < MIN_DISTINCT:
            continue
        # A drawn string ends at a terminator, with or without the space
        # padding a fixed field leaves; a run that fades into more data is
        # data.
        end = j
        while end < limit and data[end] == 0xDB:
            end += 1
        if end >= limit or data[end] != 0x00:
            continue
        why = []
        if distinct / len(run) >= MIN_VARIETY and model.score(run) >= MIN_SCORE:
            why.append("prosa")
        if neighbours(i, j) >= MIN_NEIGHBOURS:
            why.append("vecindad")
        if not why:
            continue
        out.append(Leftover(offset=j - len(run), length=len(run), chars=chars,
                            why="+".join(why),
                            garbage=sum(b in reused for b in run)
                            >= len(run) * GARBLED_SHARE))
    # Prose first: a run both signals agree on is almost always real text,
    # and a neighbourhood-only hit in a stat table almost never is.
    rank = {"prosa+vecindad": 0, "prosa": 1, "vecindad": 2}
    out.sort(key=lambda item: (rank[item.why], not item.garbage,
                               -item.chars, item.offset))
    return out


def _chars(run: bytes) -> int:
    """How many characters a run spells, kanji counting as one."""
    chars = i = 0
    while i < len(run):
        i += 2 if run[i] in KANJI_LEAD and i + 1 < len(run) else 1
        chars += 1
    return chars


def load_baseline(path: Path) -> set[str]:
    """The leftovers already accounted for, as ``OFFSET:LENGTH`` keys."""
    if not path.is_file():
        return set()
    return set(json.loads(path.read_text("utf-8")).get("known", []))


def save_baseline(path: Path, found: list[Leftover]) -> None:
    """Record the current backlog. Offsets only — never the Japanese."""
    path.write_text(json.dumps(
        {"comment": "Japanese the build knowingly leaves standing. Offsets "
                    "and lengths only: the text itself never enters the "
                    "repository. Regenerate with tools/leftovers.py --update.",
         "known": sorted(item.key for item in found)},
        ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
