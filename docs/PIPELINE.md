# The text pipeline

Where Medarot Navi keeps its text, and how `python navi.py build` rewrites it.
This is for a contributor who knows Python but has never modified a GBA game.
Everything described here is implemented in `navi/`; each module's docstring
covers its own corner, and when this document and the code disagree, the code
wins. Offsets below are for the Kuwagata release (`navi/rom.py`).

## The cartridge

A GBA cartridge is a single flat file — no filesystem, no sections, no
metadata. The console maps it read-only at bus address `0x08000000`, so every
32-bit pointer stored in the data reads `0x08xxxxxx`; subtract that base and
you have a file offset. `Rom.ptr` and `Rom.write_ptr` in `navi/rom.py` do the
conversion, and they are the only place it happens.

The Kuwagata dump is 8 MB and lays out roughly like this:

| File offset | What lives there |
|---|---|
| `0x0000A0` | Header. The 12-byte title `MEDAROTNVKWG` identifies the release |
| below `~0x100000` | ARM code (the loose-string scan uses this boundary) |
| `0x4C75E8` | 16-entry table expanding 1bpp font nibbles into 4bpp pixels |
| `0x5D8B54`–`0x6299A0` | The event scripts, back to back |
| `0x6299A0` | Master script table: 370 pointers, 4 bytes each |
| `0x658BF0` | Font: 224 glyphs of 9 bytes |
| `0x6593D0` | Kanji font: 10 bytes per glyph |
| `0x7F7541` | `data_end` — the first byte past everything real |
| to `0x800000` | Padding a flash chip never wrote. The only free space |

The myth to unlearn: the ROM contains hundreds of kilobytes of zero runs, and
none of them are free. A run of zeroes inside the graphics is a stretch of
transparent pixels, and text written over it corrupts a sprite in a way nobody
notices until they reach that screen, possibly hours in. `find_free_space`
therefore hands out only the tail past `data_end` — about 35 KB, minus a
reserved `0x200` at the very end because some flash carts and emulators keep
save data there. If a build needs more, the `Allocator` in `navi/build.py`
grows the ROM (cartridge sizes are powers of two; 32 MB is the most the bus
can map) and the patch switches from IPS to BPS (`navi/patch.py`).

Kabuto is the same game with the data at slightly shifted offsets. Its
`Release` in `navi/rom.py` is a stub; fill its constants from a Kabuto dump
before pointing the tools at one.

## Text encoding

Text is one byte per character, looked up in `data/charset-jp.tbl` (or
`charset-latin.tbl` for a translated cartridge). Kanji take two bytes: a lead
of `0xE0` or `0xE1`, then a second byte. Everything from `0xE2` up is a
control code, and `navi/table.py` exposes each one as a `<TAG>` so a
translator can move them around without knowing the bytes:

| Tag | Byte(s) | Effect |
|---|---|---|
| `<NL>` | `F1` | End the current row |
| `<WAIT>` | `F2` | Wait for the player, then clear the box |
| `<END>` | `F3` | End the string (terminator) |
| `<CLEAR>` | `F4` | Clear the box and end the string (terminator) |
| `<SFX:xx>` | `F5 xx` | Play a sound effect |
| `<FACE:xx>` | `F6 xx` | Show a portrait |
| `<FACE7:xx>` | `F7 xx` | Show a portrait (second form) |
| `<PLAYER>` | `F8` | Insert the player's name |
| `<MEDABOT>` | `F9` | Insert the medabot's name |
| `<YESNO>` | `E2` | Open the yes/no prompt |
| `<MUSIC>` | `E6` | Change the music |
| `<DELAY:xxxx>` | `E5 xx xx` | Pause for the given time |

A string ends at a `0x00` byte, at `<END>`, or at `<CLEAR>`. Codes the table
cannot name round-trip as escapes — `<K:xxxx>` for an unknown kanji,
`<X:xx>` for an unknown control code, `<B:xx>` for an unknown byte — so
decoding and re-encoding is always lossless. A few glyphs have no character to
stand for them and are spelled `[<3]` and `[note]`; `Charset.multi` makes the
encoder try those before single characters, and the width checks count each as
one screen cell.

## Event scripts

All dialogue lives in event scripts: small bytecode programs followed by the
text they show. The master table at `0x6299A0` holds 370 pointers, one per
event, and several events often share a script, so there are 170 unique ones.
A script has no length field; it runs until the next script starts, and the
last one runs up to the table itself (`script_bounds` in `navi/script.py`).

Inside a script, opcode `0x01` draws a text box. Its operand is a **16-bit
offset, counted from the start of the script**, of the string to draw. Those
operands are the whole game, in both directions: they are how extraction finds
the text, and they are the bytes the build has to rewrite. `navi/script.py`
walks the bytecode (opcode sizes came from Normmatt's ScriptEditor; see
NOTICE), following branches and jumps, and records every `0x01` site.

When a translation is longer than the Japanese it replaces — which is almost
always, Japanese is dense — the string cannot grow in place: the next string
starts right behind it. And the 16-bit script-relative operand cannot point
outside its own script, so the string cannot be moved out alone either. So
`_rebuild_script` in `navi/build.py` does this instead:

- Translations that fit are written over the Japanese inside a copy of the
  script, the leftover tail of the slot zeroed (zero is also the terminator).
- Translations that do not fit are appended to the end of the copy, and the
  `0x01` operand at each site that used them is rewritten to the new offset.
- If anything was appended, the whole copy goes to free space and every master
  table entry that pointed at the original is repointed to it. A script that
  would grow past the 64 KB a 16-bit offset can reach is skipped entirely and
  reported.

Copying the script **whole** — bytecode, translated strings, and the original
Japanese of everything else — is what makes this safe. Any line the walker
failed to find still has its operand pointing at the same relative offset,
where the same Japanese bytes still sit inside the copy. A missed line costs a
missed translation, never garbage and never a crash.

## One line's journey

Take the second line of the opening scene. The game opens in script 48 (not
script 0 — ROM order is not play order; see gbashot below), which starts at
file offset `0x5FBFE2` and draws 33 strings.

1. **Catalog key.** `navi/catalog.py` walks the dump and names the line
   `script:0048:04B1`: script index 48, string at `0x4B1` bytes from the
   script's start, so at `0x5FC493` in the file. The Japanese there occupies
   14 bytes, terminator included. The same walk runs at extract time and at
   build time, so the name cannot drift.

2. **Pack entry.** `langs/es/script/script_0048.json` holds:

   ```json
   {"key": "script:0048:04B1", "src": "2dd616c88bdd",
    "t": "<FACE:1E>¿Adónde va usted, hermano?"}
   ```

   `src` is the first 12 hex digits of the SHA-256 of the decoded Japanese —
   enough to notice the source changed, useless for recovering it. If the dump
   decodes to anything else there, `Pack.translation_for` returns nothing and
   the build leaves the line in Japanese rather than write the wrong words.

3. **Encode.** `encode()` with `charset-latin.tbl` turns the text into 28
   bytes: `F6 1E` for the portrait tag, then one byte per character — `¿` is
   `9D`, a kana slot the font patch took over; lower-case letters likewise.

4. **Fits or doesn't.** 28 bytes into a 14-byte slot does not fit, so the
   payload is appended to the rebuilt script and the operand at its `0x01`
   site now reads the append offset. (Its neighbour `script:0048:07D8` needs
   22 bytes and has 24, so it is overwritten in place inside the same rebuild,
   tail zeroed.)

5. **Relocation.** Script 48 had 29 of its 33 lines grow, so the whole rebuilt
   script is written into the free tail past `0x7F7544`, and every one of the
   370 master-table entries that held `0x08000000 + 0x5FBFE2` is repointed to
   the copy. The original script is left untouched where it was.

The patched ROM lands in `build/`, and `navi/patch.py` diffs it against the
dump into `dist/` — IPS normally, BPS if the build expanded past 16 MB.

## Loose strings

Menus, item names, part names and system messages are not in scripts; they sit
loose in the data, reached by ordinary 32-bit pointers. Rather than keep a
hand-written offset list that only matches one release, `navi/strings.py`
scans every aligned word in the ROM, keeps values that look like cartridge
pointers, and tries to decode text at each target.

Eight megabytes of graphics and ARM code decode into a lot of plausible kana,
so candidates pass three filters. A run must start right after a terminator
and decode cleanly (no `<B:>`/`<X:>`/`<K:>` escapes). It must then score well
under a bigram language model trained on the event scripts themselves — the
one body of text that is beyond doubt — so byte pairs that never occur in real
prose sink it. Finally it must either be a block (four or more strings back to
back averaging five visible characters, the shape of a menu) or be pointed at
from the executable below `0x100000` (the shape of a prompt).

`mark_fixed_tables` then flags runs of three or more adjacent strings of
identical byte length. The game reaches those by multiplying an index, not by
following a pointer, so they can be rewritten but never moved and never grown
— terrain names are four characters, and four characters they stay. At build
time a fitting translation is written in place, zero-padded; a longer one goes
to the free tail with every 32-bit pointer that reached it rewritten; a longer
one in a fixed record, or with no pointers at all, is skipped and reported.

## The font

The font at `0x658BF0` is 1bpp, one glyph per character code, 8 pixels wide by
9 tall, 9 bytes each — one byte per row. **Ink is a zero bit**: the conversion
table at `0x4C75E8` inverts as it expands to 4bpp, so a blank row is `0xFF`.
`data/glyphs-latin.txt` holds our additions as ASCII art (`#` is ink) and
`navi/font.py` packs them accordingly.

The cartridge has capitals, digits and punctuation at `0x9E`–`0xDF`, but no
lower case and no accents, and its Latin glyphs sit one pixel lower than a
lower-case baseline wants. The build raises that whole block one pixel
(`raise_glyph`), freeing the bottom row for descenders and giving the alphabet
one baseline. `¿` and `¡` are made by rotating the cartridge's own `?` and `!`
180 degrees, so they match its style exactly.

Every other new glyph must displace a kana, since every code below `0x9E`
already means something. Which kana matters: until the translation is
finished, untranslated lines still draw from this font, and each taken-over
code renders as a Latin letter inside a Japanese sentence. `navi/slots.py`
counts how often the cartridge uses each code and takes the quietest. The 48
codes it picks cost about 1.9% of the characters the game ever draws; taking
the obvious contiguous hiragana block would garble 49%. For the same reason
`build_font` never blanks a kana it did not take over.

## Validation

The text box is 32 characters wide and shows 2 rows, and there is no
scrolling: an overrun is not a glitch, the rest of the sentence is simply
never drawn. `navi/validate.py` measures every translated line — `<NL>` ends
a row, `<WAIT>` and `<CLEAR>` reset the box so rows are counted per screenful,
`[<3]` and `[note]` count as one cell — and also checks that the tags the game
needs (`PLAYER`, `MEDABOT`, `YESNO`, `FACE`, `FACE7`, `SFX`, `DELAY`) survive
translation, that every character has a glyph, that fixed records are not over
capacity, and that no fingerprint has gone stale. Fix the text; do not skip
validation.

## Verifying with gbashot

Static checks cannot see rendering. `tools/gbashot` (build with `make -C
tools`, after `brew install mgba libpng`) links against libmgba and runs the
ROM headless at unlocked speed — no window, thousands of frames in seconds —
pressing buttons on a schedule and writing PNG screenshots:

```
DYLD_LIBRARY_PATH=$(brew --prefix mgba)/lib ./tools/gbashot build/…gba \
  --frames 1800 --every 35:a --press 600:start:4 --shot 1800:work/shots/x.png \
  --watch 85D8B54:86299A0
```

`--every N:KEY` mashes a key to advance dialogue; `--press FRAME:KEY:HELD` is
a one-off press; keys are `a b select start right left up down r l`.

`--watch MIN:MAX` (hex bus addresses) scans EWRAM each frame and prints every
new pointer into that range the first frame it appears. Pointed at the script
area — `0x85D8B54:0x86299A0`, the offsets above plus the `0x08000000` base —
it reveals which script the game is running as you play. This is how play
order was recovered: the ROM order of scripts is not play order, and the game
opens in script 48.

One shell pitfall: in zsh, `--press $f:start:4` silently expands to just the
value of `$f` — zsh reads `:s` as a history-style modifier on the variable and
swallows the rest of the word. Write `${f}:start:4`. Similarly, a press list
built up in a variable needs `${=VAR}` to be split into words.

Read the screenshots back with an image viewer (or the Read tool) and judge
the rendering by eye; it catches what nothing else in this pipeline can.
