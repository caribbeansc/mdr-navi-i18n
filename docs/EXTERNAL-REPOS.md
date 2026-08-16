# Prior art: the other Medarot Navi projects, and what was taken from them

Two public repositories already exist for this game. Both were examined
(2026-08) to decide whether a full decompile/extract/reassemble workflow would
beat this project's targeted patching. Verdict: it would not — but each repo
contributed something concrete, recorded here so nobody re-investigates.

## Medabots/medarot-navi — the full-disassembly route, abandoned

https://github.com/Medabots/medarot-navi ("Medarot Navi (GBA) disassembly and
translation") is the VariantXYZ workflow that produced complete, buildable
disassemblies of the GBC Medarot games: armips acts as the linker over the
base ROM, sections get lifted into `.S` sources one at a time, and `cmp -l`
enforces a byte-identical rebuild after every step. For this game it holds
one commit (2024-01-30) and nine lines of source — the entry branch and
nothing else. The team that finished three GBC disassemblies stalled here at
"hello world": an 8 MB ARM/Thumb ROM is a different order of magnitude from a
1 MB Z80-family one, and no matching-decomp tooling (pret's agbcc ecosystem,
gbadisasm, luvdis) removes that labor. A full disassembly also would not by
itself "extract the sprites": identifying every asset is the actual work, and
this project already did it the other way (1969 compressed blocks found,
decompressed, and visually classified — see GFX-BACKLOG.md).

Their Makefile targets both releases, which is a useful reminder that any
future Kabuto support here should reuse packs, not fork them.

## Normmatt/Medarot-Navi-GBA-Translation — the engine-hack route, proven

https://github.com/Normmatt/Medarot-Navi-GBA-Translation (last commit
2018-10-31) is an armips + Atlas binary-patching prototype. **It targets the
Kabuto release** — the GfxCompressor.exe debug path spells it out — so every
address in it is a Kabuto address. What it established:

- **ROM expansion works.** Its gfx.asm plants relocated graphics at
  0x08800000, past the 8 MB mark; the cartridge bus maps 32 MB. This
  project's Allocator now does the same when the tail runs out (verified in
  the emulator: a 16 MB build boots, and `--watch 8800000:8878100` shows the
  script engine's read cursor walking relocated text above 8 MB while the
  dialogue draws).
- **Kabuto constants for free.** Its `.definelabel` tables carry
  already-reversed Kabuto addresses (Font 0x08657D60, ConversionLUT
  0x084C7608, DrawString 0x08006F9C, DrawCharacter 0x0804BE0D, and RAM
  locations). The ones navi/rom.py's `Release` dataclass wants are copied
  into the KABUTO stub, marked unverified until someone runs a Kabuto dump.
- **A working VWF exists, as plan B only.** `asm/c_replacements/` hooks
  DrawString into compiled C implementing a variable-width font (own font
  binary + per-glyph width table), which would dissolve the 22-column limit.
  It is a code hack: a bug there hangs the game, where this project's
  data-only method degrades to showing Japanese. Spanish fits in 22 columns;
  do not port this unless a future language cannot fit. If that day comes,
  the C source documents the engine's string struct and the control codes
  (0xE2 draws the yes/no options, 0xE4 toggles fonts), and its script
  pointers show the engine can be taught a 24-bit-pointer text opcode
  (`0xE3 | (address << 8)`) instead of copying whole scripts.
- Its ScriptEditor and MedabotsMapEditor sources double as documentation of
  the script bytecode and map formats (see NOTICE).

## Operational note learned while verifying

tools/gbashot (libmgba) does **not** auto-apply an adjacent .ips the way the
mGBA GUI does: `foo.gba` + `foo.ips` side by side boots the *unpatched* game
with no warning. Emulator checks must always run the already-patched .gba
from build/.
