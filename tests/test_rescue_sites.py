"""A text op the walk did not see is rescued only if it IS a text op.

rescue_sites reads a script's code as bytes and takes every ``01 <lo> <hi>``
that aims at the start of a string. Twice that took an instruction's
ARGUMENTS for a text op, and the build repointed them, which rewrote the
script's logic rather than its text.

Script 35 is the bus scene at the Cluster. Right after the class president's
"may I have a word?" it runs a list of five-byte ``07 XX 00 00 01``
instructions, and one record's last byte plus the next one's first two read
``01 07 0E``. 0x0E07 lies two bytes into a line that opens with <FACE:00>,
and the 0x00 there, FACE's argument, passed for a terminator. The build
wrote the phantom line's new offset over ``07 0E``. Players were dropped onto
the station map with half the story skipped. Script 158 had the same shape,
aimed by coincidence at a line that really does start a string.

These scripts are built by hand to have each shape, so the rules are pinned
without the game.
"""

from navi.script import TextSite, _Walker, rescue_sites

TERMINATOR_ROW = b"\xff" * 9


def _u16(value: int) -> bytes:
    return bytes((value & 0xFF, value >> 8))


def _header(entry: int) -> bytes:
    row = bytearray(9)
    row[3:5] = _u16(entry)
    return bytes(row)


def _walk(data: bytes) -> _Walker:
    walker = _Walker(data)
    walker.run(data[4] << 8 | data[3])
    return walker


def _bus_scene() -> bytes:
    """Script 35's shape: a list of 07 records that spells ``01 07 01``."""
    out = bytearray()
    out += _header(18) + TERMINATOR_ROW         # 0, 9
    out += b"\x01" + _u16(0x105)                # 18: the one real text op
    out += b"\x07\x0b\x00\x00\x01"              # 21: a five-byte 07 record
    out += b"\x07\x01\x00\x00\x01"              # 26: 25-27 read 01 07 01 -> 0x0107
    out += b"\x00"                              # 31: end
    out += bytes(0x105 - len(out))              # never executed
    out += b"\xf6\x00\x0b\x0c\x0d\x00"          # 0x105: <FACE:00> + three kana
    return bytes(out)


def _coincidence() -> bytes:
    """Script 158's shape: the false op aims at a REAL string start."""
    out = bytearray()
    out += _header(18) + TERMINATOR_ROW
    out += b"\x01" + _u16(0x100)                # 18: the one real text op
    out += b"\x07\x04\x11\x0e\x01"              # 21: a five-byte 07 record
    out += b"\x06\x01\x00"                      # 26: a three-byte op; 25-27 read 01 06 01
    out += b"\x00"                              # 29: end
    out += bytes(0x100 - len(out))
    out += b"\x0b\x0c\x0d\x0e\x0f\x00"          # 0x100: a line
    out += b"\x0b\x0c\x00"                      # 0x106: a line nothing points at
    return bytes(out)


def test_an_argument_is_not_a_text_op():
    data = _bus_scene()
    walker = _walk(data)
    assert [site.text_at for site in walker.sites] == [0x105]
    # The 0x01 at 25 is the last byte of the record at 21.
    assert 25 in walker.operands
    assert rescue_sites(data, walker.sites, walker.operands) == []


def test_a_face_argument_is_not_a_terminator():
    """Even without the operand rule, 0x0107 is not where a string starts."""
    data = _bus_scene()
    sites = [TextSite(pointer_at=19, text_at=0x105)]
    assert data[0x106] == 0x00          # the trap: FACE's argument
    assert rescue_sites(data, sites) == []


def test_a_coincidence_on_a_real_string_needs_the_operand_rule():
    """A target that does start a string is still refused if the 0x01 is data."""
    data = _coincidence()
    walker = _walk(data)
    assert data[0x105] == 0x00 and data[0x106] != 0x00
    assert 25 in walker.operands
    # Without the operand rule it would be taken...
    assert [s.text_at for s in rescue_sites(data, walker.sites)] == [0x106]
    # ...and with it, it is not.
    assert rescue_sites(data, walker.sites, walker.operands) == []


def test_a_real_unwalked_text_op_is_still_rescued():
    """The rules must not cost the 324 real sites: an op nobody decoded stays."""
    out = bytearray()
    out += _header(18) + TERMINATOR_ROW
    out += b"\x01" + _u16(0x40)                 # 18: walked
    out += b"\x00"                              # 21: end of the walked branch
    out += b"\x01" + _u16(0x44)                 # 22: a branch the walk never enters
    out += b"\x00"
    out += bytes(0x40 - len(out))
    out += b"\x0b\x0c\x0d\x00"                  # 0x40
    out += b"\xf6\x00\x0e\x00"                  # 0x44: opens with <FACE:00>
    data = bytes(out)
    walker = _walk(data)
    assert [(s.pointer_at, s.text_at) for s in rescue_sites(data, walker.sites, walker.operands)] \
        == [(23, 0x44)]
