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


def rescue_sites(data: bytes, sites: list[TextSite]) -> list[TextSite]:
    """The text ops the walk could not reach, found by reading the code as bytes.

    The walker enters a script only through its header's subscripts and only
    follows the jumps it knows, so a branch reached any other way is never
    walked. 438 lines of dialogue sat behind those branches — 108 of them in
    script 27, 166 in script 29 — invisible to extraction, and invisible to
    tools/leftovers.py as well, which skips the script area on the assumption
    that Japanese standing there is the dead original of a relocated line.

    Nobody noticed because the failure used to be benign: an unreached line
    simply stayed Japanese. It is not benign now. The charset spends the whole
    kana range on Latin (data/charset-latin.tbl is a keyboard layout), so an
    unreached line draws as Latin soup instead — which is how this was found,
    from a player's screenshot of script:0027:14A3 two hours into the game.

    So the code is read as bytes too: every ``01 <lo> <hi>`` whose target
    STARTS a string is a text site. The terminator test is what makes that
    safe — a coincidental 0x01 inside some other opcode's argument almost
    never points at a string boundary, and it rejects 1376 candidates that
    land in the text area but not on the start of a line. Checked against the
    walk itself, the scan re-finds 3443 of its 3444 sites and disagrees with
    it nowhere.

    Entering a string MID-CHAIN is deliberately not rescued. Nineteen real
    sites do exactly that, so the rule could be loosened to allow it — but
    then it would also accept every <CLEAR> boundary inside a chain, and
    telling a chain's tail from the next speaker's line needs the screen,
    not a rule (the comment on CHAIN_KEYS says what that cost last time).
    Those tails are picked up anyway, as chains, once their head is known.

    105 strings are still left over after this, listed by offset in
    tests/data/unreached-scripts.json. Their offset appears nowhere in their
    script as bytes and all but two sit behind a clean terminator, so nothing
    reaches them by pointer and nothing runs into them from the line before:
    they read as script that was written and then cut.
    """
    known = {site.text_at for site in sites}
    if not known:
        return []
    # Text lives after the code, so the earliest string the walk found is the
    # end of the code — and everything from there on is the text area.
    text_start = min(known)
    found: dict[int, TextSite] = {}
    for at in range(text_start - 2):
        if data[at] != TEXT_OP:
            continue
        target = data[at + 1] | (data[at + 2] << 8)
        if target in known or target in found:
            continue
        if not text_start <= target < len(data) - 1:
            continue
        # The byte before a string is the previous string's terminator, and
        # the engine has two: 0x00 and <END> (0xF3). Accepting only 0x00 left
        # script:0027:21AB and script:0029:38DA behind, both of them pointed
        # at by a real text op — the tests/data/unreached-scripts.json check
        # is what caught that. The first string in the area has the code in
        # front of it instead.
        if target != text_start and data[target - 1] not in (0x00, 0xF3):
            continue
        if data[target] == 0x00:
            continue
        found[target] = TextSite(pointer_at=at + 1, text_at=target)
    return [found[at] for at in sorted(found)]


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
        script.sites = walker.sites + rescue_sites(data, walker.sites)
        scripts.append(script)
    return scripts


#: The chains this dump has, as the terminator rule finds them. Not an
#: allowlist — the rule decides — but a fixture the tests pin, so that a
#: change to the rule shows up as a diff instead of as a silent merge.
CHAIN_KEYS = frozenset({
    "script:0031:0851",   # the Navi terminal's three-box greeting
    "script:0066:12F7",
    "script:0070:1152",
    "script:0076:0A5C",
    "script:0077:144B",
    "script:0077:14FE",
    "script:0092:06EC",
    # A nine-box farewell scene: one <FACE> at the head and none after it,
    # <CLEAR> between the boxes and <END> to close. Its head was one of the
    # sites rescue_sites recovered, which is the only reason the chain rule
    # ever got to see it. Read WITHOUT stopping at <END> it also swallowed
    # the next speaker's line — the same tell that unmasked the notice at
    # script:0027:2183, which is NOT a chain and is absent from this list.
    "script:0029:37B2",
})


def read_strings(script: Script, charset: Charset) -> dict[int, tuple[str, int]]:
    """Every string the script draws, as ``offset -> (text, bytes it occupies)``.

    The byte count is what decides, later, whether a translation can be written
    over the Japanese instead of forcing the whole script to move.

    Some strings are CHAINS: the engine reads straight through <CLEAR>, so
    one 0x01 op can carry several boxes back to back — the Navi terminal's
    greeting is three (welcome / "I am the management computer" / "my name
    is Navi").

    What tells a chain from two neighbouring lines is the TERMINATOR, not
    the text: the engine stops at 0x00 and at nothing else, so a box that
    ends with one is the end of its string and whatever follows belongs to
    somebody else. `decode` consumes that byte, so the test is on the byte
    just before the end. Merging on "there is text right after" instead
    showed one NPC's line twice — the second time with the other speaker's
    portrait, because the neighbour was a different character's line — and,
    where the merged translation fitted in place, BLANKED a live line and
    left a save unfinishable. Seven strings in this dump are real chains;
    102 neighbours are not.
    """
    out: dict[int, tuple[str, int]] = {}
    data = bytes(script.data)
    offsets = script.text_offsets()
    site_set = set(offsets)
    for i, text_at in enumerate(offsets):
        if text_at >= len(data):
            continue
        limit = offsets[i + 1] if i + 1 < len(offsets) else len(data)
        text, end = decode(data, text_at, charset)
        if not text:
            continue
        first_end = end
        # end - 1 is the byte the previous box ended on. The engine stops at a
        # 0x00 and at an <END> (0xF3) — _encode_or_skip in navi/build.py seals
        # every line it writes with one for exactly that reason — so either of
        # them ends the string and a <CLEAR> is what carries it on. Reading
        # through <END> merged script:0027:2183 with the next speaker's line,
        # and ran script:0029:37B2 past the end of its own scene; those two
        # only surfaced when rescue_sites made their heads catalogued sites,
        # and the bug was there all along.
        while (end < limit and 2 <= end < len(data) - 2
               and data[end - 1] not in (0x00, 0xF3)
               and end not in site_set and data[end] not in (0x00, 0xF3)):
            more, more_end = decode(data, end, charset)
            visible = more
            for tag in ("<CLEAR>", "<END>", "<NL>", "<WAIT>"):
                visible = visible.replace(tag, "")
            import re as _re
            if more_end <= end or len(_re.sub(r"<[^>]+>", "", visible).strip()) < 2:
                break
            text += more
            end = more_end
        # SAFETY: report only the FIRST segment's byte count. The chain's
        # text is what the translator needs to see, but claiming the whole
        # chain's bytes let the builder BLANK the tail — and the opcode
        # walker does not find every site, so a tail can still be some other
        # branch's live line. Under-reporting the room makes a chain
        # translation too long to fit, so it is APPENDED and the original
        # bytes stay untouched: a missed site keeps showing Japanese instead
        # of an empty box. (A save mid-game went unplayable when it blanked.)
        out[text_at] = (text, first_end - text_at)
    return out
