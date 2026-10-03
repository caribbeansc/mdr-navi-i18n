"""The catalogue: every translatable line in one dump, with a stable name.

Both extraction and the build walk the ROM the same way and must agree on what
each line is called, or a pack written today would miss tomorrow. That walk
lives here, once.

Keys look like ``script:0042:0335`` (script index, offset within it) or
``str:7EC660`` (file offset). They name where the game keeps the line, not what
it says — and specifically where KUWAGATA keeps it, in both releases, because
Kabuto is the same data shifted (navi/align.py) and one pack should serve both.
A line only Kabuto has is named ``str:KBT:645264`` so it can never collide.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .lang import fingerprint
from .rom import Rom, data_end
from .script import Script, read_scripts, read_strings
from .strings import LooseString, scan, script_area
from .table import Charset, decode, load_japanese


def read_chain(data: bytes, at: int, charset: Charset,
               starts: set[int] | frozenset[int] = frozenset(),
               limit: int = 4096) -> tuple[str, int]:
    """The text the engine reads from ``at``, as ``(text, end)``.

    `decode` stops at <CLEAR>, but the engine does not: it clears the box and
    reads on, and only a 0x00 or an <END> stops it. So a line that ends in
    <CLEAR> with more text behind it is ONE string to the game, a chain of
    boxes, and has to be translated as one. Three loose lines are like that.
    Translating only their first box sealed the translation with a 0x00 and
    cut the scene there: the alarm in the Cluster ("Emergency!") lost the
    eleven boxes that send the party to the Pyramid Block, and the scene
    where the Medabot is sent to haul something out of the water lost its
    next thirteen. Navi's closing lines in the Lobby scene were cut too.

    Reading stops where another catalogued line starts (``starts``), like
    read_strings does for the scripts' chains.
    """
    import re

    text, end = decode(data, at, charset, limit=limit)
    while (2 <= end < len(data) and data[end - 1] == 0xF4
           and data[end] not in (0x00, 0xF3) and end not in starts):
        more, after = decode(data, end, charset, limit=limit)
        if after <= end or len(re.sub(r"<[^>]+>", "", more).strip()) < 2:
            break
        text += more
        end = after
    return text, end


@dataclass
class Line:
    """One translatable line."""

    key: str
    text: str
    #: "script" or "loose".
    kind: str
    #: Where it lives, as a file offset.
    offset: int
    #: For script lines: the script it belongs to.
    script: int = -1
    #: For script lines: the offset within that script.
    relative: int = 0
    #: For loose lines: how many bytes the original occupies, terminator included.
    length: int = 0
    #: For loose lines: the pointers that reach it.
    pointers: list[int] = field(default_factory=list)
    #: For loose lines: a record in a fixed-stride table, so it cannot move.
    fixed: bool = False

    @property
    def src(self) -> str:
        return fingerprint(self.text)


@dataclass
class Catalog:
    """Everything one dump has to say."""

    lines: dict[str, Line] = field(default_factory=dict)
    scripts: list[Script] = field(default_factory=list)

    def sources(self) -> dict[str, str]:
        return {key: line.text for key, line in self.lines.items()}

    def of_kind(self, kind: str) -> list[Line]:
        return [line for line in self.lines.values() if line.kind == kind]

    def by_script(self, index: int) -> list[Line]:
        return sorted(
            (l for l in self.lines.values() if l.script == index),
            key=lambda l: l.relative,
        )

    def __len__(self) -> int:
        return len(self.lines)


def script_key(index: int, relative: int) -> str:
    return f"script:{index:04d}:{relative:04X}"


def loose_key(offset: int, tag: str = "") -> str:
    return f"str:{tag}:{offset:06X}" if tag else f"str:{offset:06X}"


def seeded(rom: Rom, charset: Charset, wanted: dict[int, str],
           known: dict[str, Line]) -> list[Line]:
    """Loose lines the scan missed here but a pack already names.

    The scan is a heuristic — a run of strings has to look enough like the
    game's own writing to be believed — and the other release shifts the data
    it weighs that against, so a block the Kuwagata scan accepts whole can
    come up one string short on Kabuto. The pack knows where those strings
    are: its keys ARE the list, in Kuwagata's offsets, each with a fingerprint
    of what it expects to find. Following it here is not a second scanner, it
    is the same finding read through the alignment — and a line is only
    catalogued where the dump still holds the Japanese the pack was written
    against, so a seed can never invent a line that is not there.
    """
    from .strings import padded_end, pointer_index

    index = pointer_index(rom)
    data = bytes(rom.data)
    stop = data_end(rom)
    out: list[Line] = []
    for canonical, src in sorted(wanted.items()):
        at = rom.at(canonical)
        if at is None or loose_key(canonical) in known:
            continue
        text, end = decode(data, at, charset, limit=200)
        if not text.strip() or end <= at:
            continue
        if fingerprint(text) != src:
            # A pack translates a chain whole (see read_chain).
            whole, _ = read_chain(data, at, charset)
            if fingerprint(whole) != src:
                continue
            text = whole
        padded = padded_end(data, end, stop)
        out.append(Line(
            key=loose_key(canonical),
            text=text,
            kind="loose",
            offset=at,
            length=padded - at,
            pointers=sorted(index.get(at, [])),
        ))
    return out


def build(rom: Rom, charset: Charset | None = None, loose: bool = True,
          seeds: dict[int, str] | None = None) -> Catalog:
    """Walk a dump and name everything in it.

    ``seeds`` are canonical (Kuwagata) offsets of loose strings a pack already
    translates; on another release they are followed through the alignment to
    catch what the scan words differently there. They are followed on Kuwagata
    too, because the scan is not a fixed list even here: it weighs a candidate
    against a bigram model trained on the scripts, so widening what the script
    walk finds moves the threshold, and four already-translated labels around
    0x645E dropped out of the scan the day rescue_sites was added. A seed only
    catalogues a line where the dump still holds the Japanese its fingerprint
    was written against, so following one can never invent a line.
    """
    charset = charset or load_japanese()
    catalog = Catalog()

    catalog.scripts = read_scripts(rom)
    for script in catalog.scripts:
        for relative, (text, size) in read_strings(script, charset).items():
            key = script_key(script.index, relative)
            catalog.lines[key] = Line(
                key=key,
                text=text,
                kind="script",
                offset=script.offset + relative,
                script=script.index,
                relative=relative,
                length=size,
            )

    if loose:
        from .strings import supplement

        found_all = scan(rom, charset, exclude=script_area(rom))
        found_all += supplement(rom, charset)
        for found in found_all:
            # A key names a line by where KUWAGATA keeps it, in every release,
            # so that one pack serves both: the other cartridge is the same
            # data shifted, and navi/align.py says by how much. A string that
            # has no Kuwagata twin — the ones naming the release's own cover
            # Medabot — is named after this dump instead, tagged so it can
            # never collide with a Kuwagata key.
            canonical = rom.back(found.offset, max(1, found.length))
            key = (loose_key(canonical) if canonical is not None
                   else loose_key(found.offset, rom.release.tag))
            if key in catalog.lines:
                continue
            catalog.lines[key] = Line(
                key=key,
                text=found.text,
                kind="loose",
                offset=found.offset,
                length=found.length,
                pointers=found.pointers,
                fixed=found.fixed,
            )

        if seeds:
            for line in seeded(rom, charset, seeds, catalog.lines):
                catalog.lines[line.key] = line

        data = bytes(rom.data)
        loose_starts = {line.offset for line in catalog.lines.values() if line.kind == "loose"}
        for line in catalog.lines.values():
            if line.kind != "loose" or line.fixed:
                continue
            # The text grows to the whole chain; the ROOM stays the first box,
            # as in read_strings, so a chain is relocated whole and the
            # original stays intact for anything that enters it mid-way.
            text, _ = read_chain(data, line.offset, charset, loose_starts - {line.offset})
            if len(text) > len(line.text) and text.startswith(line.text):
                line.text = text

        for key in phantoms(rom, charset, catalog):
            del catalog.lines[key]

    return catalog


def phantoms(rom: Rom, charset: Charset, catalog: Catalog) -> list[str]:
    """Loose lines that are only the TAIL of another line, reached by nothing real.

    The pointer scan believes any aligned word that spells a cartridge address,
    so a word inside a compressed sheet that happens to equal an address in the
    middle of a line makes that middle look like a string of its own. Two did:
    str:7F6AF3 starts 37 bytes into str:7F6ACE, a scene the game reaches
    through the table at 0x7F7348, and str:7F7503 starts seven bytes into
    "Block intrusion alert!" (str:7F74FC, loaded by the code at 0x844A6).
    Their only "pointers" were at 0x55EF08 and 0x74BAA8, both inside
    compressed graphics. Once they were in a pack, the seeds kept them alive
    on both releases.

    A tail costs twice. Written in place, it lands on top of its own head's
    translation: the intrusion alert drew three bytes of garbage in front of
    "Intruder alert!". Relocated, the writer "repoints" the coincidence and
    corrupts the sheet. So a non-fixed line that starts inside another line's
    own bytes, before that line's terminator, is dropped unless the code
    loads one of its pointers, or one of them sits in a table of strings,
    next to a word that points at another catalogued line. That is stricter
    than `is_pointer_site`, on purpose: 0x74BAA8 passes that test, because the
    compressed bytes beside it happen to spell 0x08030087. Fixed-stride slots
    nest by design, because a name that fills its slot has no terminator, so
    they are left alone.
    """
    import struct

    from .rom import BASE
    from .strings import _thumb_literal_load

    data = bytes(rom.data)
    loose = sorted((line for line in catalog.lines.values() if line.kind == "loose"),
                   key=lambda line: line.offset)
    starts = {line.offset for line in loose}

    def vouched(site: int) -> bool:
        if site < 0x8000:
            return False
        if _thumb_literal_load(data, site):
            return True
        for delta in (-8, -4, 4, 8):
            at = site + delta
            if 0 <= at and at + 4 <= len(data):
                if struct.unpack_from("<I", data, at)[0] - BASE in starts:
                    return True
        return False

    out = []
    for i, outer in enumerate(loose):
        _, end = read_chain(data, outer.offset, charset, starts - {outer.offset})
        for inner in loose[i + 1:]:
            if inner.offset >= end:
                break
            if inner.fixed or outer.fixed:
                continue
            if any(vouched(site) for site in inner.pointers):
                continue
            out.append(inner.key)
    return sorted(set(out))


def loose_string(line: Line) -> LooseString:
    return LooseString(offset=line.offset, text=line.text, length=line.length,
                       pointers=line.pointers)
