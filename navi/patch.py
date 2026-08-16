"""Distributing a translation as a patch rather than as a ROM.

Nobody may hand out the game, so a build is shared as the difference between
your dump and the translated one. IPS is what every GBA patcher reads; it caps
out at 16 MB, and a build that expands past that falls back to BPS.
"""

from __future__ import annotations

import struct
import zlib

IPS_MAGIC = b"PATCH"
IPS_EOF = b"EOF"
IPS_LIMIT = 0x1000000
#: A run this long is cheaper written as an RLE record.
RLE_THRESHOLD = 8
#: A same-value run this long is worth breaking out as its own RLE record.
RLE_WORTHWHILE = 16
MAX_CHUNK = 0xFFFF


def make_ips(original: bytes, patched: bytes) -> bytes:
    """An IPS patch turning ``original`` into ``patched``.

    Where the file grows, the baseline is 0x00, not erased-flash 0xFF: every
    patcher that matters (Lunar IPS, Flips, mGBA's auto-patching, apply_ips
    below) extends the file with zeroes, so a byte no record writes comes out
    as zero. Assuming 0xFF there would silently zero any long 0xFF run inside
    relocated data, and leave an expanded build short of its full size. The
    expanded tail's 0xFF padding is therefore written out — as RLE records,
    eight bytes per 64 KB, so a doubled ROM costs the patch about a kilobyte.
    """
    if len(patched) > IPS_LIMIT:
        raise ValueError("IPS cannot address past 16 MB; use BPS instead")
    out = bytearray(IPS_MAGIC)
    size = len(patched)
    orig_len = len(original)

    def base(index: int) -> int:
        return original[index] if index < orig_len else 0x00

    def emit_literal(start: int, end: int) -> None:
        offset = start
        while offset < end:
            # A record whose offset field is 0x454F46 spells "EOF" and every
            # patcher — apply_ips included — stops right there. Start one
            # byte earlier; the extra byte merely rewrites its own value.
            if offset == 0x454F46:
                offset -= 1
            if offset > 0xFFFFFF:
                raise ValueError("IPS cannot address past 16 MB; use BPS instead")
            chunk = patched[offset:min(offset + MAX_CHUNK, end)]
            out.extend(offset.to_bytes(3, "big") + len(chunk).to_bytes(2, "big") + chunk)
            offset += len(chunk)

    def emit_rle(offset: int, run: int, value: int) -> None:
        while run > 0:
            count = min(run, MAX_CHUNK)
            if offset == 0x454F46:
                # An RLE record here would spell "EOF" too, and backing up one
                # byte would need that byte to share the value. A literal
                # record knows how to dodge, so let it carry this stretch.
                emit_literal(offset, offset + count)
            else:
                if offset > 0xFFFFFF:
                    raise ValueError("IPS cannot address past 16 MB; use BPS instead")
                out.extend(offset.to_bytes(3, "big") + b"\x00\x00"
                           + count.to_bytes(2, "big") + bytes((value,)))
            offset += count
            run -= count

    top = 0  # furthest byte any record writes, to pin the size at the end
    i = 0
    while i < size:
        if patched[i] == base(i):
            i += 1
            continue
        value = patched[i]
        # How far does this same byte repeat? Long runs (the expanded tail's
        # padding above all) go out as RLE; scanning it in 4 KB gulps keeps
        # this linear over megabytes of it.
        run = 1
        gulp = bytes((value,)) * 4096
        while patched[i + run:i + run + 4096] == gulp:
            run += 4096
        while i + run < size and patched[i + run] == value:
            run += 1
        if run >= RLE_WORTHWHILE:
            emit_rle(i, run, value)
            i += run
            top = max(top, i)
            continue
        start = i
        i += run
        while i < size:
            if patched[i] == base(i):
                # Only stop for a decent run of unchanged bytes; a one-byte
                # match is cheaper to rewrite than to start a new record.
                same = 0
                while i + same < size and patched[i + same] == base(i + same):
                    same += 1
                    if same > RLE_THRESHOLD:
                        break
                if same > RLE_THRESHOLD:
                    break
                i += same or 1
                continue
            # A long same-value run is cheaper as its own RLE record.
            if patched[i:i + RLE_WORTHWHILE] == bytes((patched[i],)) * RLE_WORTHWHILE:
                break
            i += 1
        emit_literal(start, i)
        top = max(top, i)
    if size > orig_len and top < size:
        # No record reaches the end of the grown file, so a patcher would
        # leave it short; one literal byte at the very end pins the size.
        emit_literal(size - 1, size)
    out += IPS_EOF
    return bytes(out)


def apply_ips(original: bytes, patch: bytes) -> bytes:
    """Apply an IPS patch, so the tests can check one round-trips."""
    if not patch.startswith(IPS_MAGIC):
        raise ValueError("Not an IPS patch")
    out = bytearray(original)
    i = len(IPS_MAGIC)
    while i < len(patch):
        if patch[i:i + 3] == IPS_EOF:
            break
        offset = int.from_bytes(patch[i:i + 3], "big")
        length = int.from_bytes(patch[i + 3:i + 5], "big")
        i += 5
        if length == 0:  # RLE record
            run = int.from_bytes(patch[i:i + 2], "big")
            value = patch[i + 2]
            i += 3
            payload = bytes([value]) * run
        else:
            payload = patch[i:i + length]
            i += length
        if offset + len(payload) > len(out):
            out.extend(b"\x00" * (offset + len(payload) - len(out)))
        out[offset:offset + len(payload)] = payload
    return bytes(out)


# -- BPS -----------------------------------------------------------------

def _varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value == 0:
            out.append(byte | 0x80)
            break
        out.append(byte)
        value -= 1
    return bytes(out)


def make_bps(original: bytes, patched: bytes) -> bytes:
    """A minimal but valid BPS patch, for builds too big for IPS.

    This emits the whole target as literal data rather than searching for
    matches: correct, checksummed, and larger than a clever encoder would make.
    """
    out = bytearray(b"BPS1")
    out += _varint(len(original))
    out += _varint(len(patched))
    out += _varint(0)  # no metadata
    # Action 0 is TargetRead: the length field is (count - 1) << 2 | action.
    out += _varint(((len(patched) - 1) << 2) | 0)
    out += patched
    out += struct.pack("<I", zlib.crc32(original) & 0xFFFFFFFF)
    out += struct.pack("<I", zlib.crc32(patched) & 0xFFFFFFFF)
    out += struct.pack("<I", zlib.crc32(bytes(out)) & 0xFFFFFFFF)
    return bytes(out)


def make(original: bytes, patched: bytes) -> tuple[str, bytes]:
    """The smallest sensible patch, and the extension to save it under."""
    try:
        return "ips", make_ips(original, patched)
    except ValueError:
        return "bps", make_bps(original, patched)
