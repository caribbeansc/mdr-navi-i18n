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
# The key sequence is the Medarreloj one: B opens the bar, then RIGHT TWICE,
# A opens the panel, UP moves off the default "No", A confirms.
#
# The second RIGHT is not padding. The bar is three entries wide —
# Medarreloj | Ficha | Save — so one RIGHT lands on Ficha, and the A after it
# opens the party sheet and walks its stat pages instead of saving. The repair
# then fails with the save still stale, which reads exactly like the poke not
# having worked; it is the menu that was wrong, not the pointer. Verify by
# screenshotting frames 1040-1230: the help line under the bar names the
# selected entry ("Revisa el poder de tus aliados" is Ficha, not Save).
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

BOOT="--press 200:a:4 --press 280:a:4 --press 360:a:4 --press 440:a:4 \
      --press 520:a:4 --press 600:a:4 --press 680:a:4"

# Round one: boot into the loaded save and read the scene's map/sub bytes.
# shellcheck disable=SC2086
DYLD_LIBRARY_PATH=${DYLD_LIBRARY_PATH:-$(brew --prefix mgba)/lib} \
  "$HERE/gbashot" "$WORK/r.gba" --frames 1200 $BOOT \
  --dumpvram 1150:"$WORK/r.ram.bin" >/dev/null 2>&1

POINTER=$(python3 - "$WORK/r.ram.bin" "$WORK/r.gba" <<'PY'
import struct, sys
ram = open(sys.argv[1], "rb").read()
rom = open(sys.argv[2], "rb").read()
index = ram[0x0201B3A8 - 0x02000000] * 5 + ram[0x0201B3A9 - 0x02000000]
print("%08x" % struct.unpack_from("<I", rom, 0x6299A0 + 4 * index)[0])
PY
)
echo "puntero de escena correcto: 0x$POINTER"

# Round two: poke it in and let the game save, hash and all.
# shellcheck disable=SC2086
DYLD_LIBRARY_PATH=${DYLD_LIBRARY_PATH:-$(brew --prefix mgba)/lib} \
  "$HERE/gbashot" "$WORK/r.gba" --frames 2000 $BOOT \
  --poke 850:201B334:"$POINTER" \
  --press 900:b:4 --press 960:right:4 --press 1020:right:4 --press 1080:a:4 \
  --press 1180:up:4 --press 1260:a:4 --press 1420:a:4 --press 1570:a:4 \
  >/dev/null 2>&1

python3 "$HERE/savecheck.py" "$WORK/r.gba" "$WORK/r.sav"
cp "$SAV" "$SAV.bak"
cp "$WORK/r.sav" "$SAV"
echo "listo: $SAV reparado (copia previa en $SAV.bak)"
