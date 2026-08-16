"""Choosing which character codes the new glyphs take over.

The font is indexed by the character's code, and every code from 0x01 to 0xDF
already means something: katakana, hiragana, and the Latin block the game does
have. There is no free space, so lower case and accents have to displace kana.

Which kana matters more than it sounds. Until a translation is finished, the
lines nobody has reached yet are still drawn from the same font, and every code
that has been taken over renders as a Latin letter inside a Japanese sentence.
Take over the common kana and half of the remaining text turns to noise; take
over the rarest and it stays readable while the work goes on.

So the codes are not picked by hand. This counts how often the cartridge
actually uses each one and hands back the quietest.
"""

from __future__ import annotations

from collections import Counter

from .catalog import Catalog
from .rom import Rom
from .table import Charset, KANJI_LEAD, encode

#: Codes that stand for kana, and so are candidates for being taken over.
KANA_RANGE = range(0x01, 0x9E)


def usage(catalog: Catalog, charset: Charset) -> Counter:
    """How many times each single-byte code appears in the game's own text."""
    counts: Counter = Counter()
    for line in catalog.lines.values():
        try:
            payload = encode(line.text, charset)
        except Exception:
            continue
        i = 0
        while i < len(payload):
            if payload[i] in KANJI_LEAD:
                i += 2
                continue
            counts[payload[i]] += 1
            i += 1
    return counts


def quietest(catalog: Catalog, charset: Charset, count: int) -> list[int]:
    """The ``count`` kana codes the cartridge uses least, in code order."""
    counts = usage(catalog, charset)
    ranked = sorted(KANA_RANGE, key=lambda code: (counts.get(code, 0), code))
    return sorted(ranked[:count])


def cost(catalog: Catalog, charset: Charset, codes: list[int]) -> tuple[int, float]:
    """How much text taking these codes would garble: absolute and as a share."""
    counts = usage(catalog, charset)
    total = sum(counts.values()) or 1
    hit = sum(counts.get(code, 0) for code in codes)
    return hit, 100.0 * hit / total


def render_charset(assignments: list[tuple[int, str]], native: list[tuple[int, str]],
                   symbols: list[tuple[int, str]], note: str = "") -> str:
    """Write a charset file, grouped and commented for a human to edit."""
    out = [
        "# Character set a translated cartridge stores text in.",
        "#",
        "# The codes below 0x9E are kana slots this build takes over. They were",
        "# chosen by counting how often the cartridge uses each one, so that the",
        "# Japanese that is not translated yet stays as readable as it can:",
    ]
    if note:
        out.append(f"# {note}")
    out += [
        "#",
        "# Regenerate with: python navi.py slots --write",
        "#",
        "# One entry per line: <hex code>=<text>.",
        "",
        "# -- glyphs we draw; see data/glyphs-latin.txt -------------------------------",
    ]
    for code, char in assignments:
        out.append(f"{code:02X}={char}")
    out += ["", "# -- symbols the game already draws ------------------------------------------"]
    for code, char in symbols:
        out.append(f"{code:02X}={char}")
    out += ["", "# -- the game's own Latin glyphs ---------------------------------------------"]
    for code, char in native:
        out.append(f"{code:02X}={char}" if char != " " else f"{code:02X}=")
    return "\n".join(out) + "\n"
