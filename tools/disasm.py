#!/usr/bin/env python3
"""Disassemble the cartridge's code with capstone, queryably.

The ROM is ~megabytes of THUMB with ARM islands; a single flat listing is
unusable, so this is a query tool:

  python3 tools/disasm.py range 0x46580 0x46700 [arm]
      # THUMB (default) or ARM listing of a file-offset window
  python3 tools/disasm.py xref 0x7F2190
      # every aligned literal word equal to 0x0800_0000|addr (literal pools
      # and data tables both show up), each with the THUMB context above it
  python3 tools/disasm.py func 0x465AA
      # walk back to the probable function start (push {..,lr}) and list
      # forward through its pops
  python3 tools/disasm.py callers 0x465A8
      # scan the whole ROM for BL instructions landing on the address

Addresses are FILE offsets (bus 0x08000000 is added where needed).
"""

import struct
import sys

from capstone import CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB, Cs

ROM_PATH = "Medarot Navi - Kuwagata (Japan).gba"
BASE = 0x08000000


def load() -> bytes:
    return open(ROM_PATH, "rb").read()


def listing(data: bytes, start: int, end: int, thumb: bool = True) -> None:
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB if thumb else CS_MODE_ARM)
    md.skipdata = True
    for insn in md.disasm(data[start:end], BASE + start):
        print(f"{insn.address:08X}  {insn.bytes.hex():<8}  {insn.mnemonic} {insn.op_str}")


def xref(data: bytes, target: int) -> None:
    wanted = {BASE | target, target}
    hits = []
    for at in range(0, len(data) - 3, 4):
        if struct.unpack_from("<I", data, at)[0] in wanted:
            hits.append(at)
    print(f"{len(hits)} literal(s) for {target:#x}")
    for at in hits:
        print(f"\n--- literal at {at:#08x} (bus {BASE + at:#010x}); context above:")
        listing(data, max(0, at - 0x20), at, thumb=True)


def func(data: bytes, at: int) -> None:
    # THUMB function prologue: push {...,lr} = B5xx
    start = at & ~1
    for back in range(0, 0x400, 2):
        half = struct.unpack_from("<H", data, start - back)[0]
        if half & 0xFF00 == 0xB500:
            start -= back
            break
    else:
        print("no push {lr} within 0x400 bytes; listing raw window")
        start = max(0, at - 0x80)
    end = at + 4
    # extend forward to the matching pop {...,pc} = BDxx
    probe = at
    while probe < min(len(data), at + 0x800):
        half = struct.unpack_from("<H", data, probe)[0]
        probe += 2
        if half & 0xFF00 == 0xBD00:
            end = probe
            break
    print(f"function ~{BASE + start:#010x}..{BASE + end:#010x}")
    listing(data, start, end, thumb=True)


def callers(data: bytes, target: int) -> None:
    # THUMB BL is a pair: F000-F7FF then F800-FFFF
    bus = BASE + (target & ~1)
    found = 0
    for at in range(0, len(data) - 3, 2):
        hi = struct.unpack_from("<H", data, at)[0]
        if hi & 0xF800 != 0xF000:
            continue
        lo = struct.unpack_from("<H", data, at + 2)[0]
        if lo & 0xF800 != 0xF800:
            continue
        offset = ((hi & 0x7FF) << 12) | ((lo & 0x7FF) << 1)
        if offset & 0x400000:
            offset -= 0x800000
        if BASE + at + 4 + offset == bus:
            print(f"BL from {BASE + at:#010x}")
            found += 1
    print(f"{found} caller(s)")


def main() -> None:
    data = load()
    mode = sys.argv[1]
    if mode == "range":
        listing(data, int(sys.argv[2], 16), int(sys.argv[3], 16),
                thumb=(len(sys.argv) < 5 or sys.argv[4] != "arm"))
    elif mode == "xref":
        xref(data, int(sys.argv[2], 16))
    elif mode == "func":
        func(data, int(sys.argv[2], 16))
    elif mode == "callers":
        callers(data, int(sys.argv[2], 16))
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
