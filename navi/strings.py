"""Finding the text that is not in an event script.

Menus, item names, part names and system messages sit loose in the data and are
reached by ordinary 32-bit pointers. Rather than carry a hand-written list of
offsets, which only ever matches the one release it was written for, this walks
every aligned pointer in the ROM and keeps the ones that land on something that
decodes as text.
"""

from __future__ import annotations

import struct
from collections import defaultdict
from dataclasses import dataclass, field

from .rom import BASE, Rom, data_end
from .table import Charset, TERMINATORS, decode

#: A run shorter than this is almost always a coincidence.
MIN_LENGTH = 2

#: Bytes that never start a real string.
BAD_LEAD = {0x00, 0xF1, 0xF3, 0xF4}


@dataclass
class LooseString:
    """A string outside the event scripts, and every pointer that reaches it."""

    offset: int
    text: str
    length: int
    pointers: list[int] = field(default_factory=list)
    #: True when the string is a record in a fixed-stride table. The game finds
    #: those by multiplying an index, so they can be neither moved nor resized.
    fixed: bool = False
    #: Bytes the decoded text itself occupies (terminator included), before
    #: any stride padding was absorbed into ``length``.
    text_bytes: int = 0

    @property
    def key(self) -> str:
        return f"str:{self.offset:06X}"

    @property
    def capacity(self) -> int:
        """Characters that fit, terminator excluded."""
        return max(0, self.length - 1)


def pointer_index(rom: Rom, step: int = 4) -> dict[int, list[int]]:
    """Map each pointed-at file offset to the places that point at it."""
    index: dict[int, list[int]] = defaultdict(list)
    data = rom.data
    size = len(data)
    for site in range(0, size - 3, step):
        value = struct.unpack_from("<I", data, site)[0]
        if BASE <= value < BASE + size:
            index[value - BASE].append(site)
    return index


def _plausible(text: str, charset: Charset) -> bool:
    if len(text) < MIN_LENGTH:
        return False
    # Anything the charset could not name comes back as a <B:xx> or <X:xx>
    # placeholder. One is a decoding accident; the string is not text.
    if "<B:" in text or "<X:" in text or "<K:" in text:
        return False
    visible = text
    for tag in ("<NL>", "<END>", "<CLEAR>", "<WAIT>"):
        visible = visible.replace(tag, "")
    return len(visible.strip()) >= MIN_LENGTH


#: How many padding zeroes a fixed-stride table may leave after a string.
PAD_LIMIT = 15


def padded_end(data: bytes | bytearray, end: int, stop: int) -> int:
    """``end`` extended over the zero padding that follows a string.

    Fixed-stride tables pad each record to its stride with extra zeroes, and
    those are absorbed into the record's length, which both keeps a run going
    and reports the capacity a translation really has.

    It never runs past ``stop``, the end of the data (see rom.data_end). The
    zeroes after the LAST string in the cartridge are not padding but the
    free tail, and that is where the build relocates scripts. str:7F7526 once
    claimed 15 of them, so its translation, written "in place", went over the
    header of the relocated script 0. That script is the one 170 of the
    master table's slots share.
    """
    padded = end
    while padded < stop and data[padded] == 0x00 and padded - end < PAD_LIMIT:
        padded += 1
    return padded


def _thumb_literal_load(data: bytes | bytearray, site: int) -> bool:
    """Whether a Thumb ``ldr rN, [pc, #imm]`` in the KB before ``site`` loads it."""
    for at in range(max(0, site - 1024), site, 2):
        half = data[at] | (data[at + 1] << 8)
        if half >> 11 == 0b01001 and ((at + 4) & ~3) + (half & 0xFF) * 4 == site:
            return True
    return False


def is_pointer_site(data: bytes | bytearray, site: int) -> bool:
    """Whether the aligned word at ``site`` is a pointer, not data that looks like one.

    The scan takes every aligned word that equals a cartridge address, and
    most of the ROM is not code or tables: it is sound, pixels and compressed
    graphics, where four bytes such as ``f4 fe 08 08`` spell 0x0808FEF4 by
    accident. The loose writer used to repoint every one of them when it
    moved a string. That wrote addresses into 8-bit PCM samples and, at
    0x55EF08, into the middle of a compressed sheet. So a word counts as a
    pointer only with evidence:

    - the code loads it (a PC-relative ``ldr`` aims at it), or
    - it sits in a table, with a neighbour within 8 bytes that is itself a
      cartridge address.

    Every site the build ever repointed for a real reason passes. None of the
    coincidences did. Words below 0x8000 never count: the boot code can spell
    an address by accident, and repointing one white-screened the ROM.
    """
    if site < 0x8000 or site + 4 > len(data):
        return False
    if _thumb_literal_load(data, site):
        return True
    for delta in (-8, -4, 4, 8):
        at = site + delta
        if 0 <= at and at + 4 <= len(data):
            value = struct.unpack_from("<I", data, at)[0]
            if BASE <= value < BASE + len(data):
                return True
    return False


def _run_from(rom: Rom, start: int, charset: Charset, max_length: int,
              stop: int | None = None) -> list[tuple[int, str, int]]:
    """Decode strings back to back from ``start`` for as long as they hold up.

    Fixed-stride tables pad each record to its stride with extra zeroes; those
    are absorbed into the record's length (see `padded_end`).
    """
    data = rom.data
    stop = len(data) if stop is None else stop
    out: list[tuple[int, str, int]] = []
    at = start
    while at < len(data):
        if data[at] in BAD_LEAD:
            break
        text, end = decode(data, at, charset, limit=max_length)
        if end - at >= max_length or not _plausible(text, charset):
            break
        if data[end - 1] not in TERMINATORS:
            break
        padded = padded_end(data, end, stop)
        out.append((at, text, padded - at, end - at))
        at = padded
    return out


def _visible(text: str) -> str:
    out = text
    for tag in ("<NL>", "<END>", "<CLEAR>", "<WAIT>", "<YESNO>", "<MUSIC>"):
        out = out.replace(tag, "")
    return out


class LanguageModel:
    """How much a run of bytes looks like this game's own writing.

    Deciding by hand which byte sequences are text does not survive contact
    with 8 MB of graphics and ARM code: too much of it decodes into plausible
    kana. But the event scripts are text beyond doubt, so they can teach the
    scanner what the game's prose actually looks like, and anything that scores
    far below them is not prose.
    """

    def __init__(self, samples: list[bytes], floor: float = 1e-6):
        self.floor = floor
        counts: dict[tuple[int, int], int] = defaultdict(int)
        totals: dict[int, int] = defaultdict(int)
        for sample in samples:
            for a, b in zip(sample, sample[1:]):
                counts[(a, b)] += 1
                totals[a] += 1
        self.counts = counts
        self.totals = totals
        self.vocabulary = len({b for sample in samples for b in sample}) or 1

    def score(self, payload: bytes) -> float:
        """Mean log-probability per byte pair. Higher is more like real text."""
        import math

        if len(payload) < 2:
            return -99.0
        total = 0.0
        for a, b in zip(payload, payload[1:]):
            seen = self.counts.get((a, b), 0)
            denominator = self.totals.get(a, 0) + self.vocabulary
            total += math.log((seen + 1) / denominator)
        return total / (len(payload) - 1)

    @classmethod
    def from_scripts(cls, rom: Rom) -> "LanguageModel":
        from .script import read_scripts

        samples: list[bytes] = []
        for script in read_scripts(rom):
            for text_at in script.text_offsets():
                if text_at < len(script.data):
                    samples.append(script.data[text_at:text_at + 64])
        return cls(samples)


def scan(rom: Rom, charset: Charset, exclude: tuple[int, int] | None = None,
         max_length: int = 200, min_run: int = 4, min_avg: float = 5.0,
         code_end: int = 0x100000, min_score: float = -5.5,
         model: "LanguageModel | None" = None) -> list[LooseString]:
    """Every pointed-at string in the ROM, outside ``exclude``.

    Loose text is reached two ways, and each needs its own test.

    Tables of text — menu entries, part names, terrain names — sit in blocks:
    one string after another, each ending in a terminator. A run of ``min_run``
    of them averaging ``min_avg`` characters is text; a shorter, choppier run is
    a stretch of ARM code that happens to decode as kana.

    Single strings that the code points at directly — prompts, button hints —
    have no run to vouch for them, so they are accepted only when the pointer
    itself lives in the executable, below ``code_end``.
    """
    index = pointer_index(rom)
    data = rom.data
    stop = data_end(rom)
    model = model or LanguageModel.from_scripts(rom)
    accepted: dict[int, tuple[str, int]] = {}
    visited: set[int] = set()

    for target in sorted(index):
        if target in visited or target >= len(data):
            continue
        if exclude and exclude[0] <= target < exclude[1]:
            continue
        # Only start a run where one really starts: after a terminator.
        if target > 0 and data[target - 1] not in TERMINATORS:
            continue
        run = _run_from(rom, target, charset, max_length, stop)
        if not run:
            continue

        from_code = any(site < code_end for site in index.get(target, ()))
        # A pointer from the executable is independent evidence that this is
        # data the game reads, so such runs get a laxer language bar.
        bar = min_score - 1.0 if from_code else min_score

        # A run happily walks off the end of a real table into neighbouring
        # data that also happens to decode, and that junk would sink the whole
        # score. So take the longest prefix that still reads as text — the
        # real strings survive, the tail is dropped. Scoring text bytes only:
        # the padding a fixed-stride table leaves is not prose.
        spans = []
        acc = b""
        for offset, _, _, text_len in run:
            acc += bytes(data[offset:offset + text_len])
            spans.append(acc)
        lengths = [len(_visible(text)) for _, text, _, _ in run]

        def _accepts(k: int) -> bool:
            if model.score(spans[k - 1]) < bar:
                return False
            block = k >= min_run and sum(lengths[:k]) / k >= min_avg
            return block or from_code

        keep = 0
        for k in range(len(run), 0, -1):
            if _accepts(k):
                keep = k
                break
        if not keep:
            continue
        run = run[:keep]
        # Mark only what was accepted: a rejected run must not swallow the
        # legitimate start of a later block that happens to sit inside it.
        visited.update(offset for offset, _, _, _ in run)
        for offset, text, length, text_len in run:
            accepted[offset] = (text, length, text_len)

    found = [
        LooseString(offset=offset, text=text, length=length,
                    pointers=sorted(index.get(offset, [])),
                    text_bytes=text_bytes)
        for offset, (text, length, text_bytes) in sorted(accepted.items())
    ]
    found = split_slot_tables(found, rom, charset)
    mark_fixed_tables(found)
    return found


#: Name tables the game reaches by multiplying an index, as
#: ``(first slot, stride, slots, bytes per name)``.
#:
#: A name that fills its slot leaves no terminator, so the scanner reads it and
#: the slot next door as ONE run — and a translation of that run then writes
#: over both, blanking the second. Eighteen part names came out empty in-game
#: that way (マスクドカブト, キラーホエール, ジェミニ...), silently, because
#: nothing about a blank name looks wrong in a diff. Declaring the geometry
#: here splits every such run back into one entry per slot, so a translation
#: can only ever reach the record it belongs to.
SLOT_TABLES = (
    # A medal record is 0x1C bytes and carries TWO names: the family it
    # belongs to (クワガタ, カブト, ザウルス...) and the medal's own. The
    # family name is what the game shows in "you got the X medal", so leaving
    # that column Japanese printed four kana through the Latin font.
    (0x092998, 0x1C, 16, 8),
    (0x0929A0, 0x1C, 16, 8),
    # Part names, the two Tinpets at the end included.
    (0x092BD8, 0x08, 152, 8),
    # Room names for the cluster's travel map — the "Bloq. Info" panel reads
    # one per 0x20-byte record. Nothing points at them, so the pointer scan
    # never saw the table at all and all 39 stayed Japanese.
    (0x5D632C, 0x20, 41, 9),
)


#: Fixed-stride records whose TEXT is followed by the record's own data, as
#: ``(first record, stride, records, bytes of text at the front)``.
#:
#: The part table is 608 records of 0x14: an eight-byte model code and an
#: eight-byte name — sixteen bytes of text — and then three bytes of the
#: part's own stats with a zero for padding. Neither text field carries a
#: terminator; 127 of the 608 names fill all eight bytes, so the game reads
#: fixed widths and a translation has exactly those bytes to spend.
#:
#: gfx.json declared a "room" of 9 to 12 for 188 of those names, and 20 — the
#: whole record — for the entries that cover code and name together. The
#: extra-strings writer believes room: it writes the payload and then
#: ZERO-PADS to room. Both halves of that corrupted the record — a long name
#: wrote over the stats, a short one padded zeroes over them — and 125 records
#: came out of the build with the wrong data. A player found it because the
#: stat they could see was the part's gender ("Prominence is listed as
#: Female"); the others are silent. Nothing catches it downstream: the text is
#: valid, fits its box and renders. Only the bytes after it are wrong.
TEXT_RECORDS = (
    (0x095B30, 0x14, 608, 0x10),
)


def record_text_room(offset: int) -> int | None:
    """Bytes a translation may write at ``offset``, or None if unconstrained.

    The answer is how much of the record's TEXT is left from there on, so a
    site on the name field gets eight and one on the model code gets sixteen.
    ``offset`` is a canonical (Kuwagata) file offset, the way gfx.json and the
    packs name every site.
    """
    for start, stride, count, text in TEXT_RECORDS:
        if not start <= offset < start + stride * count:
            continue
        position = (offset - start) % stride
        if position < text:
            return text - position
        return 0            # inside the data tail: nothing may be written
    return None


def split_slot_tables(found: list[LooseString], rom: Rom,
                      charset: Charset) -> list[LooseString]:
    """Replace runs that cross a :data:`SLOT_TABLES` table with one entry per slot."""
    data = bytes(rom.data)
    spans: list[tuple[int, int]] = []
    made: list[LooseString] = []
    for start, stride, count, width in SLOT_TABLES:
        # The tables are declared where Kuwagata keeps them; on the other
        # release the same records sit elsewhere, and where a table has no
        # twin at all (a cover-Medabot part list) there is nothing to split.
        start = rom.at(start, stride * count)
        if start is None:
            continue
        for i in range(count):
            at = start + i * stride
            spans.append((at, at + width))
            text, end = decode(data, at, charset, limit=width)
            if not text.strip():
                continue
            made.append(LooseString(offset=at, text=text, length=width,
                                    fixed=True,
                                    text_bytes=min(end - at, width)))
    slots = {entry.offset: entry for entry in made}
    keep = []
    for entry in found:
        reach = entry.offset + max(entry.length, 1)
        if any(low < reach and entry.offset < high for low, high in spans):
            # The scan's own pointers are still worth carrying over.
            if entry.offset in slots:
                slots[entry.offset].pointers = entry.pointers
            continue
        keep.append(entry)
    return sorted(keep + made, key=lambda entry: entry.offset)


def mark_fixed_tables(found: list[LooseString], run: int = 3) -> None:
    """Flag strings that are records in a fixed-stride table.

    When several strings in a row are the same length and butt up against each
    other, the game is almost certainly reaching them by multiplying an index
    rather than by following a pointer. Such a string can be rewritten, but not
    moved and not made longer: doing either shifts every record after it.
    """
    i = 0
    while i < len(found):
        j = i + 1
        while (j < len(found)
               and found[j].length == found[i].length
               and found[j].offset == found[j - 1].offset + found[j - 1].length):
            j += 1
        if j - i >= run:
            stride = found[i].length
            for entry in found[i:j]:
                entry.fixed = True
            # The table's LAST record swallows whatever zeroed free space
            # follows the table, so its length is inflated past the stride and
            # the chain above stops just short of it. It is still a record:
            # flag it, and cap its capacity at the one slot it really owns.
            # Unless, that is, it opens a chain of its own — then it is the
            # first record of the NEXT table, not the tail of this one.
            candidate = found[j] if j < len(found) else None
            opens_own_chain = (
                candidate is not None
                and j + 1 < len(found)
                and found[j + 1].length == candidate.length
                and found[j + 1].offset == candidate.offset + candidate.length
            )
            fits_one_slot = (candidate is not None
                             and 0 < candidate.text_bytes <= stride)
            if (candidate is not None
                    and not opens_own_chain
                    and fits_one_slot
                    and candidate.offset == found[j - 1].offset + stride
                    and candidate.length >= stride):
                candidate.fixed = True
                candidate.length = stride
                j += 1
        i = j if j > i + 1 else i + 1


def script_area(rom: Rom) -> tuple[int, int]:
    """The span the event scripts occupy, so the scan can skip it."""
    from .script import script_bounds

    bounds = script_bounds(rom)
    if not bounds:
        return (0, 0)
    start = min(offset for offset, _ in bounds)
    end = max(offset + length for offset, length in bounds)
    return (start, end)


#: Live text the scan's heuristics miss — found by a pointer-free kana sweep
#: of the whole dump (2026-08), every zone verified pointer-reachable:
#: the roaming-NPC chatter block parked just BEFORE the event scripts, the
#: late-game scenes parked at the ROM TAIL (below the 0x7F7541 data end, so
#: the allocator never touches them), and the link/result composites next to
#: the battle messages. The scan skips them because their runs fail the
#: preceded-by-a-terminator test or drown in neighbouring non-text.
SUPPLEMENT_ZONES = (
    (0x5D7000, 0x5D8B54),   # roaming-NPC and event snippets
    (0x7F6100, 0x7F7541),   # late-game scenes at the ROM tail
    (0x4CC700, 0x4CCE00),   # link/robattle result composites
)

#: Pointer targets inside those zones that are NOT text: sound/animation
#: ramps and bare insert tokens the composites splice in.
SUPPLEMENT_SKIP = {0x7F6004}

#: Individually curated strings the zone/score filters would reject: the
#: item-get dialog templates and their INSERT words (slot names down to a
#: single kanji, so the min-length bar drops them), each reached by exactly
#: one pointer in the gift table at 0x7F01CC-0x7F01F0.
SUPPLEMENT_EXTRA = (
    0x5D5BD8,            # "this block develops X"
    0x5D5DA4,            # starter-pack 5-box template
    0x5D5E04, 0x5D5E18, 0x5D5E2C,   # tinpet / part / medal get
    0x5D5E40, 0x5D5E48,  # tinpet types (female/male)
    0x5D5E50, 0x5D5E58, 0x5D5E60, 0x5D5E68,  # slot words legs/l.arm/r.arm/head
)


def supplement(rom: Rom, charset: Charset,
               model: "LanguageModel | None" = None) -> list[LooseString]:
    """The curated strings behind SUPPLEMENT_ZONES, as normal loose lines."""
    model = model or LanguageModel.from_scripts(rom)
    index = pointer_index(rom)
    data = bytes(rom.data)
    # Zones and curated targets are written down as Kuwagata offsets; the same
    # text sits elsewhere in the other release (navi/align.py). A zone whose
    # bounds do not both translate is skipped rather than guessed at.
    zones = []
    for low, high in SUPPLEMENT_ZONES:
        start, end = rom.at(low), rom.near(high)
        if start is not None and end is not None and end > start:
            zones.append((start, end))
    extra = [rom.at(target) for target in SUPPLEMENT_EXTRA]
    extra = sorted(target for target in extra if target is not None)
    skip = {rom.at(target) for target in SUPPLEMENT_SKIP}
    out = []
    for target in extra:
        if target in index:
            text, end = decode(data, target, charset, limit=2000)
            pointers = [site for site in index[target] if site >= 0x8000]
            out.append(LooseString(offset=target, text=text,
                                   length=end - target, pointers=pointers,
                                   text_bytes=end - target))
    for target in sorted(index):
        if target in skip or target in extra:
            continue
        if not any(a <= target < b for a, b in zones):
            continue
        text, end = decode(data, target, charset, limit=2000)
        visible = _visible(text)
        if len(visible) < 4 or model.score(data[target:end]) < -4.5:
            continue
        # Words inside the BOOT code (0x334, 0x4820, 0x4B94...) can decode as
        # pointers into these zones by pure coincidence; repointing one there
        # bricks the ROM to a white screen at power-on (it happened). The real
        # loaders' tables and literal pools all live above 0x8000, so only
        # those may ever be rewritten.
        pointers = [site for site in index[target] if site >= 0x8000]
        out.append(LooseString(offset=target, text=text, length=end - target,
                               pointers=pointers, text_bytes=end - target))
    return out
