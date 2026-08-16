"""Tests for navi/patch.py: IPS round-trips, RLE, and the BPS fallback."""

import random
import struct
import zlib

import pytest

from navi.patch import IPS_LIMIT, apply_ips, make, make_bps, make_ips


def _read_varint(blob: bytes, i: int) -> tuple[int, int]:
    """Decode one BPS varint; returns (value, next offset)."""
    value, shift = 0, 1
    while True:
        byte = blob[i]
        i += 1
        value += (byte & 0x7F) * shift
        if byte & 0x80:
            return value, i
        shift <<= 7
        value += shift


def test_ips_round_trips_random_mutations_and_growth():
    rng = random.Random(0xC0FFEE)
    original = bytes(rng.randrange(256) for _ in range(4096))
    patched = bytearray(original)
    for _ in range(64):
        patched[rng.randrange(len(patched))] = rng.randrange(256)
    patched.extend(rng.randrange(256) for _ in range(700))   # the file grows
    patched = bytes(patched)

    patch = make_ips(original, patched)
    assert patch.startswith(b"PATCH")
    assert patch.endswith(b"EOF")
    assert apply_ips(original, patch) == patched


def test_ips_round_trips_identical_files():
    original = bytes(range(256))
    patch = make_ips(original, original)
    assert patch == b"PATCH" + b"EOF"
    assert apply_ips(original, patch) == original


def test_apply_ips_handles_a_hand_crafted_rle_record():
    original = bytes(16)
    patch = (b"PATCH"
             + (4).to_bytes(3, "big") + (0).to_bytes(2, "big")   # length 0: RLE
             + (6).to_bytes(2, "big") + b"\xaa"                  # run 6 of 0xAA
             + b"EOF")
    assert apply_ips(original, patch) == bytes(4) + b"\xaa" * 6 + bytes(6)


def test_apply_ips_rle_record_can_grow_the_file():
    patch = (b"PATCH"
             + (12).to_bytes(3, "big") + (0).to_bytes(2, "big")
             + (8).to_bytes(2, "big") + b"\x55"
             + b"EOF")
    assert apply_ips(bytes(10), patch) == bytes(12) + b"\x55" * 8


def test_ips_expanded_build_round_trips_exactly():
    """The expanded-ROM shape: new data past the original, then 0xFF padding.

    The data carries a long 0xFF run of its own (compressed blocks do), which
    a patcher that pads growth with zeroes must still reproduce — and the
    applied file must come out at the full padded size, not stop at the last
    byte of data.
    """
    rng = random.Random(0x16A8)
    original = bytes(rng.randrange(256) for _ in range(0x1000))
    high = bytearray(rng.randrange(256) for _ in range(0x800))
    high[0x100:0x180] = b"\xff" * 0x80
    patched = original + bytes(high) + b"\xff" * 0x40000

    patch = make_ips(original, patched)
    assert apply_ips(original, patch) == patched     # content AND size
    assert len(patch) < 0x1000                       # padding went out as RLE


def test_ips_growth_ending_in_zeroes_still_pins_the_size():
    original = b"\x01" * 16
    patched = original + b"\x02" * 8 + b"\x00" * 32
    patch = make_ips(original, patched)
    assert apply_ips(original, patch) == patched


def test_ips_long_runs_travel_as_rle():
    original = bytes(0x3000)
    patched = bytearray(original)
    patched[0x100:0x2100] = b"\xaa" * 0x2000
    patch = make_ips(original, bytes(patched))
    assert apply_ips(original, patch) == bytes(patched)
    assert len(patch) < 64


def test_ips_dodges_an_rle_record_at_the_eof_offset():
    # A record whose offset field reads 0x454F46 spells "EOF"; a same-value
    # run starting exactly there must still survive the round trip.
    original = bytes(0x454F46 + 0x100)
    patched = bytearray(original)
    patched[0x454F46:0x454F46 + 0x20] = b"\xbb" * 0x20
    patch = make_ips(original, bytes(patched))
    assert apply_ips(original, patch) == bytes(patched)


def test_apply_ips_rejects_other_formats():
    with pytest.raises(ValueError):
        apply_ips(b"", b"NOT AN IPS PATCH")


def test_make_ips_refuses_past_16mb():
    with pytest.raises(ValueError):
        make_ips(b"", bytes(IPS_LIMIT + 1))


def test_make_picks_ips_when_it_fits():
    original, patched = b"MEDAROT", b"MEDAROT!"
    ext, blob = make(original, patched)
    assert ext == "ips"
    assert apply_ips(original, blob) == patched


def test_make_falls_back_to_bps_past_16mb():
    original = bytes(64)
    patched = bytes(IPS_LIMIT + 1)
    ext, blob = make(original, patched)
    assert ext == "bps"
    assert blob.startswith(b"BPS1")
    assert blob[-12:] == struct.pack(
        "<III",
        zlib.crc32(original),
        zlib.crc32(patched),
        zlib.crc32(blob[:-4]),
    )


def test_make_bps_structure_and_checksums():
    original = b"MEDAROT NAVI ORIGINAL"
    patched = b"MEDAROT NAVI TRADUCIDO, MAS LARGO"
    blob = make_bps(original, patched)

    assert blob[:4] == b"BPS1"
    i = 4
    source_size, i = _read_varint(blob, i)
    target_size, i = _read_varint(blob, i)
    metadata_size, i = _read_varint(blob, i)
    assert source_size == len(original)
    assert target_size == len(patched)
    assert metadata_size == 0

    action, i = _read_varint(blob, i)
    assert action & 3 == 0                      # TargetRead
    assert (action >> 2) + 1 == len(patched)    # covering the whole target
    assert blob[i:i + len(patched)] == patched
    i += len(patched)

    source_crc, target_crc, patch_crc = struct.unpack_from("<III", blob, i)
    assert i + 12 == len(blob)                  # nothing after the checksums
    assert source_crc == zlib.crc32(original)
    assert target_crc == zlib.crc32(patched)
    assert patch_crc == zlib.crc32(blob[:-4])
