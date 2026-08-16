"""The catalogue: every translatable line in one dump, with a stable name.

Both extraction and the build walk the ROM the same way and must agree on what
each line is called, or a pack written today would miss tomorrow. That walk
lives here, once.

Keys look like ``script:0042:0335`` (script index, offset within it) or
``str:7EC660`` (file offset). They are stable for a given release because they
name where the game keeps the line, not what it says.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .lang import fingerprint
from .rom import Rom
from .script import Script, read_scripts, read_strings
from .strings import LooseString, scan, script_area
from .table import Charset, load_japanese


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


def loose_key(offset: int) -> str:
    return f"str:{offset:06X}"


def build(rom: Rom, charset: Charset | None = None, loose: bool = True) -> Catalog:
    """Walk a dump and name everything in it."""
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
            key = loose_key(found.offset)
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

    return catalog


def loose_string(line: Line) -> LooseString:
    return LooseString(offset=line.offset, text=line.text, length=line.length,
                       pointers=line.pointers)
