"""Turning the cartridge's bytes into text and back.

The game stores one byte per character, except for kanji, which take two. On
top of that sit the control codes that drive the text box: line breaks, pauses,
portraits, the player's name. Those are written as ``<TAGS>`` so that a
translator can move them around without touching the encoding.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

#: Control codes that take no argument, and the tag each is written as.
SIMPLE_CODES = {
    0xE2: "YESNO",
    0xE6: "MUSIC",
    0xF1: "NL",
    0xF2: "WAIT",
    0xF3: "END",
    0xF4: "CLEAR",
    0xF8: "PLAYER",
    0xF9: "MEDABOT",
}

#: Control codes followed by a fixed number of argument bytes.
ARG_CODES = {
    0xE5: ("DELAY", 2),
    0xF5: ("SFX", 1),
    0xF6: ("FACE", 1),
    0xF7: ("FACE7", 1),
}

#: Codes that end a string outright.
TERMINATORS = {0x00, 0xF3, 0xF4}

#: First byte of a two-byte kanji.
KANJI_LEAD = (0xE0, 0xE1)

TAG_RE = re.compile(r"<([A-Z0-9]+)(?::([0-9A-Fa-f]+))?>")


class TableError(Exception):
    pass


@dataclass
class Charset:
    """A mapping between codes and the text they stand for."""

    name: str
    decode: dict[int, str] = field(default_factory=dict)
    encode: dict[str, int] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path) -> "Charset":
        path = Path(path)
        charset = cls(name=path.stem)
        for raw in path.read_text(encoding="utf-8").splitlines():
            if not raw or raw.lstrip().startswith("#"):
                continue
            if "=" not in raw:
                continue
            code_text, value = raw.split("=", 1)
            code_text = code_text.strip()
            if not re.fullmatch(r"[0-9A-Fa-f]{2,4}", code_text):
                continue
            code = int(code_text, 16)
            # A bare "DB=" means the space character; a trailing space would be
            # eaten by every editor that trims lines.
            if value == "":
                value = " "
            charset.decode.setdefault(code, value)
            charset.encode.setdefault(value, code)
        if not charset.decode:
            raise TableError(f"{path} defines no characters")
        return charset

    @property
    def max_code(self) -> int:
        return max(c for c in self.decode if c <= 0xFF)

    @property
    def multi(self) -> list[str]:
        """Entries written as more than one character, longest first.

        A few glyphs have no character to stand for them — the heart, the music
        note — so the table spells them ``[<3]`` and ``[note]``. The encoder has
        to try these before falling back to single characters.
        """
        cached = getattr(self, "_multi", None)
        if cached is None:
            cached = sorted((k for k in self.encode if len(k) > 1), key=len, reverse=True)
            object.__setattr__(self, "_multi", cached)
        return cached


def load_japanese() -> Charset:
    return Charset.load(DATA_DIR / "charset-jp.tbl")


def load_latin() -> Charset:
    return Charset.load(DATA_DIR / "charset-latin.tbl")


# -- decoding ------------------------------------------------------------


def decode(data: bytes, offset: int, charset: Charset, limit: int = 4096) -> tuple[str, int]:
    """Read one string. Returns the text and the offset just past its end."""
    out: list[str] = []
    i = offset
    end = min(len(data), offset + limit)
    while i < end:
        byte = data[i]
        if byte == 0x00:
            i += 1
            break
        if byte in KANJI_LEAD:
            if i + 1 >= end:
                break
            code = (byte << 8) | data[i + 1]
            out.append(charset.decode.get(code, f"<K:{code:04X}>"))
            i += 2
            continue
        if byte in ARG_CODES:
            tag, argc = ARG_CODES[byte]
            args = data[i + 1 : i + 1 + argc]
            out.append(f"<{tag}:{args.hex().upper()}>")
            i += 1 + argc
            continue
        if byte in SIMPLE_CODES:
            out.append(f"<{SIMPLE_CODES[byte]}>")
            i += 1
            if byte in TERMINATORS:
                break
            continue
        if byte >= 0xE0:
            out.append(f"<X:{byte:02X}>")
            i += 1
            continue
        out.append(charset.decode.get(byte, f"<B:{byte:02X}>"))
        i += 1
    return "".join(out), i


# -- encoding ------------------------------------------------------------

_REVERSE_SIMPLE = {name: code for code, name in SIMPLE_CODES.items()}
_REVERSE_ARG = {name: (code, argc) for code, (name, argc) in ARG_CODES.items()}


def encode(text: str, charset: Charset) -> bytes:
    """Write one string back into the cartridge's encoding.

    Raises :class:`TableError` naming the first character the font cannot draw,
    which is what a translator needs to know.
    """
    out = bytearray()
    i = 0
    while i < len(text):
        if text[i] == "<":
            match = TAG_RE.match(text, i)
            if not match:
                raise TableError(f"Malformed tag at {i}: {text[i:i + 12]!r}")
            name, arg = match.group(1), match.group(2)
            if name in _REVERSE_SIMPLE:
                out.append(_REVERSE_SIMPLE[name])
            elif name in _REVERSE_ARG:
                code, argc = _REVERSE_ARG[name]
                if arg is None or len(arg) != argc * 2:
                    raise TableError(f"<{name}> needs {argc} argument byte(s)")
                out.append(code)
                out.extend(bytes.fromhex(arg))
            elif name in ("K", "B", "X") and arg:
                value = int(arg, 16)
                out.extend(value.to_bytes(2 if name == "K" else 1, "big"))
            else:
                raise TableError(f"Unknown tag <{name}>")
            i = match.end()
            continue
        for token in charset.multi:
            if text.startswith(token, i):
                code = charset.encode[token]
                out.extend(code.to_bytes(2 if code > 0xFF else 1, "big"))
                i += len(token)
                break
        else:
            char = text[i]
            code = charset.encode.get(char)
            if code is None:
                raise TableError(f"No glyph for {char!r} in charset {charset.name}")
            out.extend(code.to_bytes(2 if code > 0xFF else 1, "big"))
            i += 1
    return bytes(out)


#: Glyphs the table spells out, and the one cell each really takes on screen.
SPELLED = {"[<3]": "\u2665", "[note]": "\u266a"}


def _collapse(text: str) -> str:
    for spelling, glyph in SPELLED.items():
        text = text.replace(spelling, glyph)
    return text


def visible_length(text: str) -> int:
    """How many character cells a line takes up, ignoring tags."""
    return len(_collapse(TAG_RE.sub("", text)))


#: Tags that end the row being drawn.
#: <B:00> is a raw string terminator: fused fixed-table records spell several
#: strings in one entry, separated by it, and the game draws each separately.
ROW_BREAKS = {"NL", "WAIT", "CLEAR", "END", "B:00"}


def lines_of(text: str) -> list[str]:
    """The rows this line draws.

    A row ends at <NL>, and also at <WAIT> and <CLEAR>: those wait for the
    player and then start the box again, so what follows is a fresh row rather
    than more of the same one.
    """
    def _name(m: "re.Match[str]") -> str:
        return f"{m.group(1)}:{m.group(2)}" if m.group(2) else m.group(1)

    broken = TAG_RE.sub(lambda m: "\n" if _name(m) in ROW_BREAKS else "", _collapse(text))
    return [row for row in broken.split("\n")]


@dataclass(frozen=True)
class Row:
    """One drawn row, and whether it is the first of its box."""

    text: str
    first_in_box: bool


def rows_by_box(text: str) -> list[Row]:
    """The rows this line draws, each marked as first-of-box or not.

    The distinction matters because the box only draws 22 columns on its
    FIRST row: on the second the last cell never appears, so a 22nd
    character is silently dropped.
    """
    def _name(m: "re.Match[str]") -> str:
        return f"{m.group(1)}:{m.group(2)}" if m.group(2) else m.group(1)

    marked = TAG_RE.sub(
        lambda m: "\x00" if _name(m) in ("WAIT", "CLEAR", "END")
        else ("\n" if _name(m) in ROW_BREAKS else ""), _collapse(text))
    out: list[Row] = []
    for box in marked.split("\x00"):
        rows = [row for row in box.split("\n")]
        first = True
        for row in rows:
            if not row:
                continue
            out.append(Row(row, first))
            first = False
    return out
