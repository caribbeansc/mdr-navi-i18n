"""The ROM itself: loading it, knowing which release it is, and writing it back.

Everything else in this package reads the ROM through this module, so that the
one place that knows about file offsets versus GBA addresses is here.
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from pathlib import Path

BASE = 0x08000000
"""Where the cartridge is mapped in the GBA address space."""

HEADER_TITLE = slice(0xA0, 0xAC)
HEADER_GAME_CODE = slice(0xAC, 0xB0)


@dataclass(frozen=True)
class Release:
    """One of the two retail releases of the game."""

    code: str
    title: str
    name: str
    sha1: str
    #: Master table of script pointers, as a file offset.
    script_table: int
    #: Number of consecutive entries in that table.
    script_table_len: int
    #: Font of ordinary characters (codes 0x00-0xDF), 9 bytes per glyph, 1bpp.
    font: int
    #: Font of kanji (codes 0xE0xx-0xE1xx), 10 bytes per glyph, 1bpp.
    font_kanji: int
    #: 16-entry table expanding a 1bpp nibble into four 4bpp pixels.
    conversion_lut: int
    #: Marks the keys of lines this release has and Kuwagata does not. Empty
    #: for Kuwagata itself, whose layout every key in a pack is named after.
    tag: str = ""


KUWAGATA = Release(
    code="AVIJ",
    title="MEDAROTNVKWG",
    name="Kuwagata",
    sha1="de8de6734f0f990832988ea133fa05241946800e",
    script_table=0x6299A0,
    script_table_len=370,
    font=0x658BF0,
    font_kanji=0x6593D0,
    conversion_lut=0x4C75E8,
)

#: Kabuto ships the same build with its data shifted a few hundred bytes: the
#: fonts, the scripts and the tables are byte-identical, they simply sit
#: elsewhere. These four constants were derived from a dump by aligning it with
#: Kuwagata (navi/align.py) and agree with the ones Normmatt's Kabuto-targeted
#: project reversed by hand (font, 1bpp table, script table — see NOTICE),
#: which is two independent derivations of the same numbers. Everything else
#: this project knows is written as a Kuwagata offset and translated through
#: ``Rom.at``, so there is no second list of addresses to keep in step.
KABUTO = Release(
    code="ANAJ",
    title="MEDAROTNVKBT",
    name="Kabuto",
    sha1="3135545e02fa5557dda0976165cf5c7f3c0b6f8e",
    tag="KBT",
    script_table=0x629728,
    script_table_len=370,
    font=0x657D60,
    font_kanji=0x658540,
    conversion_lut=0x4C7608,
)

RELEASES = (KUWAGATA, KABUTO)


class RomError(Exception):
    pass


class Rom:
    """A mutable copy of a Medarot Navi cartridge."""

    def __init__(self, data: bytes | bytearray, path: Path | None = None):
        self.data = bytearray(data)
        self.path = path
        self.release = self._identify()
        self._alignment = None

    # -- loading ---------------------------------------------------------

    @classmethod
    def load(cls, path: str | Path) -> "Rom":
        path = Path(path)
        if not path.is_file():
            raise RomError(f"No such file: {path}")
        data = path.read_bytes()
        if len(data) < 0x100:
            raise RomError(f"{path.name} is too small to be a GBA ROM")
        return cls(data, path)

    def _identify(self) -> Release:
        title = bytes(self.data[HEADER_TITLE]).decode("ascii", "replace").rstrip("\0")
        for release in RELEASES:
            if title == release.title:
                return release
        raise RomError(
            f"Unrecognised cartridge {title!r}. This tool knows "
            + " and ".join(r.title for r in RELEASES)
            + "."
        )

    @property
    def sha1(self) -> str:
        return hashlib.sha1(self.data).hexdigest()

    @property
    def is_known_dump(self) -> bool:
        return self.sha1 == self.release.sha1

    # -- one release's offsets, in another's ------------------------------

    def at(self, offset: int, length: int = 1) -> int | None:
        """Translate a Kuwagata offset into this dump's own.

        Every address this project has reversed is written down as a Kuwagata
        offset, next to the code that uses it. On a Kuwagata dump this hands
        it straight back; on Kabuto it looks the stretch up in the map derived
        from the two dumps (navi/align.py) and returns where the same bytes
        live there — or ``None`` where the two releases genuinely differ,
        which the caller must read as "leave this alone".

        ONLY constants go through here. An offset read out of this ROM (a
        pointer, a table entry) is already in this dump's own space and
        translating it again would land anywhere.
        """
        if self._alignment is None:
            from . import align

            self._alignment = align.for_release(self.release.name)
        return self._alignment.at(offset, length)

    def near(self, offset: int, slack: int = 0x1000) -> int | None:
        """Like :meth:`at`, for a region BOUNDARY rather than for data."""
        if self._alignment is None:
            from . import align

            self._alignment = align.for_release(self.release.name)
        return self._alignment.near(offset, slack)

    def back(self, offset: int, length: int = 1) -> int | None:
        """The reverse of :meth:`at`: this dump's offset, named in Kuwagata's.

        Keys in a language pack name a line by where Kuwagata keeps it, so a
        line found in a Kabuto dump has to be named by where its Kuwagata twin
        sits before the pack can be asked about it.
        """
        if self._alignment is None:
            from . import align

            self._alignment = align.for_release(self.release.name)
        return self._alignment.back(offset, length)

    # -- reading ---------------------------------------------------------

    def u8(self, off: int) -> int:
        return self.data[off]

    def u16(self, off: int) -> int:
        return struct.unpack_from("<H", self.data, off)[0]

    def u32(self, off: int) -> int:
        return struct.unpack_from("<I", self.data, off)[0]

    def ptr(self, off: int) -> int:
        """Read a GBA pointer and return it as a file offset, or -1."""
        value = self.u32(off)
        if not BASE <= value < BASE + len(self.data):
            return -1
        return value - BASE

    def read(self, off: int, length: int) -> bytes:
        return bytes(self.data[off : off + length])

    # -- writing ---------------------------------------------------------

    def write(self, off: int, payload: bytes) -> None:
        end = off + len(payload)
        if end > len(self.data):
            raise RomError(f"Write past the end of the ROM at {off:#x}")
        self.data[off:end] = payload

    def write_u16(self, off: int, value: int) -> None:
        struct.pack_into("<H", self.data, off, value & 0xFFFF)

    def write_u32(self, off: int, value: int) -> None:
        struct.pack_into("<I", self.data, off, value & 0xFFFFFFFF)

    def write_ptr(self, off: int, target: int) -> None:
        """Write a GBA pointer that points at the given file offset."""
        self.write_u32(off, BASE + target)

    def expand(self, size: int) -> None:
        """Grow the ROM, padding with 0xFF as a flash cartridge would."""
        if size < len(self.data):
            raise RomError("Refusing to shrink the ROM")
        self.data.extend(b"\xff" * (size - len(self.data)))

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(bytes(self.data))
        return path

    def __len__(self) -> int:
        return len(self.data)


def data_end(rom: Rom) -> int:
    """The first offset past everything the cartridge actually stores.

    Whatever follows is padding a flash chip never wrote, and is the only part
    of the ROM that is safe to build in.
    """
    data = rom.data
    end = len(data)
    while end > 0 and data[end - 1] in (0x00, 0xFF):
        end -= 1
    return end


def find_free_space(rom: Rom, start: int | None = None, minimum: int = 0x100
                    ) -> list[tuple[int, int]]:
    """Return the padding at the end of the ROM as ``[(offset, length)]``.

    It is tempting to treat every run of zeroes as free, and there are hundreds
    of kilobytes of them. They are not free: a run of zeroes inside the graphics
    is a stretch of transparent pixels, and writing text over it corrupts a
    sprite in a way that will not show up until someone reaches that screen.
    Only the tail past :func:`data_end` is genuinely unused.
    """
    start = data_end(rom) if start is None else start
    # data_end strips a final 0x00 terminator as if it were padding, and a
    # 4-aligned boundary would round to zero separation — the first relocated
    # payload would then splice itself onto the last real string. +4 before
    # rounding guarantees at least one byte of clearance, terminator included.
    start = (start + 4) & ~3
    if len(rom.data) - start < minimum:
        return []
    return [(start, len(rom.data) - start)]
