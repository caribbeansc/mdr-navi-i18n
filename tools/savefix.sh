#!/bin/sh
# Re-pair a player's save with a freshly built ROM.
#
# The save keeps an ABSOLUTE ROM pointer to the scene's script (.sav offset
# 0x3220, RAM 0x0201B334) and every build relocates the scripts, so a save
# made with yesterday's ROM points into today's at the wrong place. The
# engine then runs whatever bytes are there — a corrupted name-entry screen
# opens when the player walks.
#
# The .sav cannot be hand-edited: the word at offset 0x14 is a hash, not a
# sum, and the loader rejects a save whose hash does not match ("la partida
# guardada se dañó"). So the repair is done by the game itself: boot the new
# ROM with the old save, poke the RIGHT pointer into RAM, and save in-game so
# the engine writes its own hash.
#
# The right pointer is master_table[map * 5 + sub], with map and sub read out
# of RAM at 0x0201B3A8/0x0201B3A9 — the game does NOT recompute it on load,
# which is exactly why the stale value survives a plain load-and-save.
#
#   tools/savefix.sh build/medarot-navi-kuwagata-es.gba \
#                    build/medarot-navi-kuwagata-es.sav
#
# Needs DYLD_LIBRARY_PATH=$(brew --prefix mgba)/lib, like every gbashot run.
# The key sequence is the Medarreloj one: B opens the bar, LEFT selects Save,
# A opens the panel, UP moves off the default "No", A confirms.
#
# LEFT, not RIGHT, and that is the whole trick. The bar GROWS as the game
# unlocks entries — by the Cluster it is five wide (Medawatch | Team | Make |
# Stats | Save), not the three this script was first written against — and it
# WRAPS, so no fixed number of RIGHTs lands on Save for every save file: two
# RIGHTs opened Make and walked its Block pages instead of saving, which reads
# exactly like the poke not having worked. Save is the LAST entry, so one LEFT
# from the freshly opened bar wraps straight onto it whatever the width.
# Verify by screenshotting after the LEFT: the help line under the bar names
# the selected entry ("Save your progress").
#
# The boot is done in two runs with a savestate between them, because the save
# has to be LOADED before the menu keys mean anything and the A-mashing that
# loads it would keep firing during the menu. A fixed handful of A presses is
# not enough: a title screen plus the load menu can take past frame 1200.
set -e

ROM=$1
SAV=$2
[ -n "$ROM" ] && [ -n "$SAV" ] || { echo "uso: savefix.sh ROM SAV" >&2; exit 2; }

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(dirname "$HERE")
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
cp "$ROM" "$WORK/r.gba"
cp "$SAV" "$WORK/r.sav"

# Round one: mash A until the save is loaded, then freeze that moment. The
# state is what lets round two drive the menu without A being mashed into it.
DYLD_LIBRARY_PATH=${DYLD_LIBRARY_PATH:-$(brew --prefix mgba)/lib} \
  "$HERE/gbashot" "$WORK/r.gba" --frames 1300 --every 60:a \
  --savestate 1280:"$WORK/loaded.state" \
  --dumpvram 1250:"$WORK/r.ram.bin" >/dev/null 2>&1

POINTER=$(python3 - "$WORK/r.ram.bin" "$WORK/r.gba" <<'PY'
import struct, sys
ram = open(sys.argv[1], "rb").read()
rom = open(sys.argv[2], "rb").read()
index = ram[0x0201B3A8 - 0x02000000] * 5 + ram[0x0201B3A9 - 0x02000000]
print("%08x" % struct.unpack_from("<I", rom, 0x6299A0 + 4 * index)[0])
PY
)
echo "puntero de escena correcto: 0x$POINTER"

# Round two: from the loaded state, poke it in and let the game save, hash
# and all.
DYLD_LIBRARY_PATH=${DYLD_LIBRARY_PATH:-$(brew --prefix mgba)/lib} \
  "$HERE/gbashot" "$WORK/r.gba" --loadstate "$WORK/loaded.state" \
  --frames 1100 --poke 20:201B334:"$POINTER" \
  --press 60:b:4 --press 130:left:4 --press 200:a:4 \
  --press 320:up:4 --press 400:a:4 \
  --press 560:a:4 --press 720:a:4 --press 880:a:4 \
  >/dev/null 2>&1

python3 "$HERE/savecheck.py" "$WORK/r.gba" "$WORK/r.sav"
cp "$SAV" "$SAV.bak"
cp "$WORK/r.sav" "$SAV"
echo "listo: $SAV reparado (copia previa en $SAV.bak)"
