#!/usr/bin/env python3
"""Is a player's save still valid for this build?

The in-game save stores an ABSOLUTE ROM pointer to the current scene's
script (a 32-bit word at .sav offset 0x3220). Our builds relocate scripts,
so a save made with one build points somewhere else in the next one: the
engine then runs whatever bytes are there — a corrupted name-entry screen
opened when the player walked, with the save otherwise intact.

The check is cheap: that word must be one of the master script table's
entries. Run it before handing a new build to someone who is mid-game.

  python3 tools/savecheck.py build/rom.gba build/rom.sav
"""

import struct
import sys

SCENE_POINTER = 0x3220
MASTER_TABLE = 0x6299A0
MASTER_ENTRIES = 370


def main() -> int:
    rom = open(sys.argv[1], "rb").read()
    sav = open(sys.argv[2], "rb").read()
    stored = struct.unpack_from("<I", sav, SCENE_POINTER)[0]
    table = {struct.unpack_from("<I", rom, MASTER_TABLE + 4 * i)[0]
             for i in range(MASTER_ENTRIES)}
    if stored == 0:
        print("save: the scene pointer is zeroed — NPCs will be mute")
        return 1
    if stored in table:
        print(f"save: OK, {stored:#010x} is a live script in this build")
        return 0
    print(f"save: STALE, {stored:#010x} is not a script in this build.")
    print("      The fix is to load it in the emulator, poke the right value")
    print("      into 0x0201B334 and save in-game so the game writes its own")
    print("      checksum; the value is")
    print("      master_table[ram[0x0201B3A8] * 5 + ram[0x0201B3A9]].")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
