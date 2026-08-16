"""Walking the event scripts to find every line of dialogue.

Each event is a small bytecode program followed by the text it shows. Opcode
0x01 starts a text box and carries a 16-bit offset, counted from the start of
the script, of the string to draw. Finding those offsets is the whole job:
they are both where the text is and where the build has to write a new one.

The opcode sizes below come from the ScriptEditor in
Normmatt/Medarot-Navi-GBA-Translation; see NOTICE.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .rom import Rom
from .table import Charset, decode

#: Opcodes that stop execution of the current branch.
END_OPS = {0x00, 0x16, 0x1D, 0x2A, 0x2C, 0x2D, 0x2E, 0x2F, 0x35, 0x36}

#: Fixed-size opcodes, as ``opcode -> total length in bytes``.
OP_SIZE: dict[int, int] = {}
for _op in (0x11, 0x17, 0x24, 0x25, 0x39, 0x3C, 0x3F, 0x41, 0x42, 0x43):
    OP_SIZE[_op] = 1
for _op in (0x02, 0x09, 0x0E, 0x0F, 0x12, 0x13, 0x14, 0x15, 0x1A, 0x1B, 0x1E,
            0x20, 0x21, 0x26, 0x27, 0x28, 0x29, 0x38, 0x3A, 0x3B, 0x3D, 0x3E):
    OP_SIZE[_op] = 2
for _op in (0x04, 0x06, 0x08, 0x0B, 0x18, 0x19, 0x1C, 0x1F, 0x22, 0x30, 0x32,
            0x33, 0x37, 0x40):
    OP_SIZE[_op] = 3
for _op in (0x0D, 0x2B):
    OP_SIZE[_op] = 4
OP_SIZE[0x07] = 5
for _op in (0x05, 0x0C, 0x23):
    OP_SIZE[_op] = 6

MAX_OPCODE = 0x43
TEXT_OP = 0x01


@dataclass
class TextSite:
    """One place a script asks for a string to be drawn."""

    #: Offset of the 16-bit pointer, relative to the start of the script.
    pointer_at: int
    #: Offset of the string itself, relative to the start of the script.
    text_at: int


@dataclass
class Script:
    """One event script: its bytes, and every string it draws."""

    index: int
    #: File offset of the script in the ROM.
    offset: int
    data: bytes
    sites: list[TextSite] = field(default_factory=list)

    @property
    def subscripts(self) -> int:
        n = 0
        while (n + 1) * 9 <= len(self.data) and self.data[n * 9] <= 0x80:
            n += 1
        return n

    def text_offsets(self) -> list[int]:
        return sorted({site.text_at for site in self.sites})


class _Walker:
    def __init__(self, data: bytes):
        self.data = data
        self.sites: list[TextSite] = []
        self._seen: set[int] = set()

    def run(self, start: int, depth: int = 0) -> None:
        if depth > 8 or start in self._seen:
            return
        self._seen.add(start)
        data = self.data
        # Text lives after the code, so the first string we meet is also the
        # end of the code we are allowed to walk.
        limit = len(data)
        idx = start
        while 0 <= idx < limit:
            op = data[idx]
            if op > MAX_OPCODE:
                idx += 1
                continue
            if op in END_OPS:
                return
            if op == TEXT_OP:
                if idx + 2 >= limit:
                    return
                text_at = data[idx + 1] | (data[idx + 2] << 8)
                self.sites.append(TextSite(pointer_at=idx + 1, text_at=text_at))
                if text_at < limit:
                    limit = text_at
                idx += 3
                continue
            if op == 0x0A:  # four-way branch on the player's facing
                for arg in (2, 4, 6, 8):
                    if idx + arg + 1 >= len(data):
                        break
                    target = data[idx + arg] | (data[idx + arg + 1] << 8)
                    if target > idx:
                        self.run(target, depth + 1)
                return
            if op == 0x10:  # inline movement list
                idx += 1
                while idx < limit and data[idx] == 0x05:
                    idx += 6
                while idx < limit and data[idx] == 0x06:
                    idx += 3
                continue
            if op == 0x03:  # unconditional jump
                if idx + 2 >= len(data):
                    return
                target = data[idx + 1] | (data[idx + 2] << 8)
                if target > idx:
                    idx = target
                    continue
                return
            if op == 0x31:
                if idx + 4 >= len(data):
                    return
                self.run(data[idx + 3] | (data[idx + 4] << 8), depth + 1)
                idx += 5
                continue
            if op == 0x34:
                if idx + 3 >= len(data):
                    return
                self.run(data[idx + 2] | (data[idx + 3] << 8), depth + 1)
                idx += 4
                continue
            size = OP_SIZE.get(op)
            if size is None:
                return
            idx += size


def script_bounds(rom: Rom) -> list[tuple[int, int]]:
    """Every script in the master table, as ``(offset, length)``.

    The table holds one entry per event, and several events often share a
    script, so the same offset can appear more than once. A script runs until
    the next one starts; the last one runs up to the table itself.
    """
    release = rom.release
    starts: list[int] = []
    for i in range(release.script_table_len):
        target = rom.ptr(release.script_table + 4 * i)
        if target < 0:
            break
        starts.append(target)
    unique = sorted(set(starts))
    bounds = []
    for i, start in enumerate(unique):
        end = unique[i + 1] if i + 1 < len(unique) else release.script_table
        bounds.append((start, end - start))
    return bounds


def script_table(rom: Rom) -> list[int]:
    """The master table as a list of file offsets, duplicates and all."""
    release = rom.release
    out = []
    for i in range(release.script_table_len):
        target = rom.ptr(release.script_table + 4 * i)
        if target < 0:
            break
        out.append(target)
    return out


def read_scripts(rom: Rom) -> list[Script]:
    """Parse every script in the ROM and record where its text is."""
    scripts = []
    for index, (offset, length) in enumerate(script_bounds(rom)):
        data = rom.read(offset, length)
        script = Script(index=index, offset=offset, data=data)
        walker = _Walker(data)
        for sub in range(script.subscripts):
            head = sub * 9
            if head + 4 >= len(data):
                break
            walker.run(data[head + 4] << 8 | data[head + 3])
        script.sites = walker.sites
        scripts.append(script)
    return scripts


def read_strings(script: Script, charset: Charset) -> dict[int, tuple[str, int]]:
    """Every string the script draws, as ``offset -> (text, bytes it occupies)``.

    The byte count is what decides, later, whether a translation can be written
    over the Japanese instead of forcing the whole script to move.
    """
    out: dict[int, tuple[str, int]] = {}
    for text_at in script.text_offsets():
        if text_at >= len(script.data):
            continue
        text, end = decode(script.data, text_at, charset)
        if text:
            out[text_at] = (text, end - text_at)
    return out
