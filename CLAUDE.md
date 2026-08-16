# mdr-navi-i18n

Tooling to translate **Medarot Navi** (GBA, 2001, Japan-only) without
reverse-engineering anything yourself, plus the translations built with it.
Modelled on [medarot-rb-i18n](https://github.com/caribbeansc/medarot-rb-i18n):
language packs hold fingerprints and translations, never the game's text or
bytes; every slow fact about the ROM lives in code under `navi/`, documented
where it is used.

## Commands

```
python navi.py                 # interactive menu
python navi.py rom <path>      # point the tools at your dump
python navi.py scan            # what the dump holds
python navi.py extract [lang]  # dump all text to work/ (Japanese + translation)
python navi.py validate <lang> # widths, tags, capacity, stale fingerprints
python navi.py build <lang>    # patched ROM in build/, IPS patch in dist/
python navi.py slots [--write] # (re)pick which kana codes new glyphs take
python navi.py font [chars]    # ASCII preview of the patched font
python navi.py doctor          # check the setup
pytest                         # tests; ROM-dependent ones skip without a dump
make -C tools                  # build gbashot (needs: brew install mgba libpng)
```

## Verifying in the emulator (do this, it catches what static checks cannot)

`tools/gbashot` runs the ROM **headless at unlocked speed** via libmgba and
takes PNG screenshots on a schedule — no window, thousands of frames in
seconds. Always run it with `DYLD_LIBRARY_PATH=$(brew --prefix mgba)/lib`.

```
DYLD_LIBRARY_PATH=$(brew --prefix mgba)/lib ./tools/gbashot build/…gba \
  --frames 1800 --every 35:a --press 600:start:4 --shot 1800:work/shots/x.png \
  --watch 85D8B54:86299A0
```

- `--every N:KEY` mashes a key to advance dialogue; `--press F:KEY:HELD` is a
  one-off press. In zsh use `${=VAR}` if you build press lists in a variable.
- `--watch MIN:MAX` (hex bus addresses) scans EWRAM each frame and prints every
  new pointer into that range. Pointed at the script area it reveals **which
  script the game is running** — this is how play order is recovered, and the
  ROM order of scripts is *not* play order (the game opens in script 48, not 0).
- Screenshots are read back with the Read tool to check rendering by eye.
- `--dumpvram F:x.bin` saves LCD registers + palette + VRAM + OAM for
  `tools/vramtool.py`; name the file `*.ram.*` instead and it saves
  EWRAM+IWRAM. `--savestate F:x.state` / `--loadstate x.state` skip the walk.
- **Savestates EXPIRE when the build changes.** A state carries RAM copies of
  pointers into the OLD build's layout (relocated strings, tables); loading it
  on a different build dereferences stale addresses and can hang with PC→0 —
  a fake crash that bisects like an impossible "interaction". Any repro or
  bisect must regenerate its states with the build under test, from power-on.
- `tools/gbawatch` (same Makefile) answers *who wrote this byte*: it arms a
  write watchpoint and prints pc/lr/r0-r5 at every hit. It takes the same
  `--press FRAME:KEY[:HELD]` and `--loadstate`, so screens that need the
  d-pad are reachable; `--mash 0` turns the built-in A-mashing off. Bisect
  the `--arm FRAME` to learn *when* the write happens, then feed the pc to
  `tools/disasm.py`.

## What the ROM is (Kuwagata; constants in `navi/rom.py`)

- 8 MB; real data ends at 0x7F7541, the tail is the only safe free space.
  **Runs of zeroes inside the data are transparent pixels, not free space.**
- Text: 1 byte/char, kanji 2 bytes (0xE0xx/0xE1xx). Control codes are exposed
  as tags: `<NL> <WAIT> <CLEAR> <END> <FACE:xx> <SFX:xx> <PLAYER> <MEDABOT>
  <YESNO> <DELAY:xxxx>`. Tables in `data/charset-*.tbl`.
- 170 event scripts via a master pointer table at 0x6299A0 (370 entries, dupes
  allowed). Inside a script, opcode 0x01 carries a 16-bit offset from the
  script's start to its string. Opcode walker in `navi/script.py`; sizes came
  from Normmatt's ScriptEditor (see NOTICE).
- Loose text (menus, labels) is found by scanning every aligned ROM pointer and
  keeping targets that decode as text, filtered by a bigram model trained on
  the scripts themselves (`navi/strings.py`). Strings in fixed-stride tables
  (terrain names: 4 chars!) are flagged `fixed` and can never grow or move.
- Font: 1bpp, 9 bytes/glyph, **ink = 0 bit**, indexed by character code, at
  0x658BF0. No lowercase, no accents. The build raises the native Latin block
  (0x9E–0xDF) one pixel and draws our glyphs (`data/glyphs-latin.txt`) into the
  **least-used** kana codes — chosen by counting, `navi/slots.py` — so
  untranslated Japanese stays readable (1.9% of characters affected, vs 49% if
  you take the obvious hiragana block). Never blank unassigned kana glyphs.

## The hard rules

- **22 visible columns per row, 2 rows per screenful.** (The tile buffer is 32 wide; columns 23-32 exist but are off-window, so overflow is silently invisible. Measured: no Japanese row exceeds 22.) `<WAIT>`/`<CLEAR>` reset the
  box, `<NL>` breaks the row. No scrolling: overflow is silently not drawn.
  `validate` measures every line; fix text, don't skip validation.
- A build never edits in place what could break: translations that fit
  overwrite the Japanese; longer script lines are appended to a **whole copy**
  of the script in free space (16-bit pointers repointed inside the copy, the
  master table repointed to it). A missed line then still shows Japanese,
  never garbage.
- Language packs (`langs/<code>/`) contain `key`, `src` (12-hex fingerprint of
  the Japanese), `t` (translation). If `src` no longer matches the dump, the
  build refuses that line. **Never commit Japanese text, ROM bytes, `work/`,
  `build/`, `dist/`, or any `.gba`.**
- Translation style: es-419, Latin-American dub canon — see
  `langs/es/GLOSSARY.md`. The Sperobo verbal tic is a trailing `-robo`;
  drop it when a row would exceed the visible width.
- **What the original already shows in English STAYS in English** — UI or
  dialogue, text or graphics: `push start`, `OPTION`/`TIME`/`BGM`, `WIN`/
  `LOSE`, `LV`/`EXP`/`MF`, `ROBOTTLE!`, `MEDAROT`, `TYPE`/`LEVEL`, `PAGE`,
  `navi`, katakana loanwords the game itself romanises, etc. Do not
  hispanicise them; the graphics inventory's `latin-text` blocks are
  untouched for the same reason.

## Workflow for translating

1. `extract` → read `work/kuwagata/*.json` (Japanese next to translation).
2. Write translations as `{key: text}` dicts in `work/tr_*.py`, then
   `python tools/apply.py es` folds them into `langs/es/` with fingerprints.
3. `validate` → fix every width/tag complaint → `build` → gbashot screenshots.

## Graphic menus (navi/gfx.py)

The title menu and the OPTION screen keep their labels as **4bpp tiles
compressed with the game's own "Malias" codec** (blocks start with `Le`;
format in navi/gfx.py, ported from Normmatt's Malias2.cs). The build
decompresses each registered asset, erases the Japanese pixels, draws the
Spanish with the game's (already patched) dialogue font, recompresses, and
either writes in place or relocates + repoints the single pointer. Label texts
live in `langs/es/gfx.json`; widths are measured and refused when they overflow.

Hard-won facts:
- Title-menu palettes SWAP fill/outline between selected and dimmed states:
  labels must be drawn body=index 1 with a top rim of 15 (`style="bevel"`),
  or the dimmed entry goes near-invisible.
- Pass the ALREADY-BUILT font into `Typesetter` — building it from a patched
  rom raises the native block twice and shears the top row off every capital.
- The OPTION headers (戦闘時間/戦闘BGM) share their 戦闘 tiles; their tilemap
  rows are UNCOMPRESSED right after the sheet block (offsets in gfx.py), so
  the build grows the sheet with fresh tiles and repoints those map rows.
- Sprite tiles use 1-D mapping: a WxH sprite is W*H consecutive tiles.
- When a sheet's dedup leaves a label no room (leg-type plates: 二脚 owned 2
  of its 5 columns), the way out is FRESH TILES + MAP REPOINT: append tiles
  to the sheet, draw the full word, rewrite that entry's cells in its
  uncompressed map (`patch_part_type_plates` in gfx.py, map at 0x663F8C;
  same idea as the OPTION headers and the robottle banner).
- `tools/disasm.py` (capstone) disassembles the ROM queryably: `range`,
  `xref ADDR` (literal pools), `func ADDR`, `callers ADDR` — use it to read
  the code that loads an asset instead of probing blind.
- Some UI screens draw their kanji from a **glyph bank**, not a sheet: 8x16
  cells plus a 1024-entry table where `code - 0xE001` is the top tile and
  `+32` the bottom one, and the text renderer blits one cell per two-byte
  kanji code. `glyph_banks` in gfx.json repaints a word's cells (8px per
  code, two stacked lines of two capitals) — see "kanji glyph banks" in
  navi/gfx.py. Only list words whose kanji never appear in another word on
  those screens: a repainted code changes every string that draws it.
- On-screen kanji has a **third** home besides strings and glyph banks:
  captions **pre-rendered as 4bpp pixels** inside an ordinary compressed
  sheet. The battle parts panel's action and uses captions are like this
  (both in block 0x662720) — their codes appear in no live string, both
  banks leave those codes on the empty cell, and blanking their glyphs in
  the kanji font at 0x6593D0 changes nothing, because the game decompresses
  the sheet into the EWRAM tile pool at 0x02002474 and DMAs tiles into BG0
  from 0x0801C880. When a caption resists every search, dump VRAM in the
  frame, rebuild the glyph's tile bytes and grep the DECOMPRESSED blocks for
  them (`work/inventory/index.json` lists all 1969). The pixels are a
  redraw, not a copy: the sheet's kanji are hand-tightened, so matching them
  against the font glyph only works within a few pixels.
- **A sheet is not necessarily the picture.** The robottle banner (戦闘開始) is
  laid out by a 12x2 tilemap, uncompressed at 0x664758, that pads the box's
  corners with the sheet's blank tile and makes the top-row columns 3 and 4
  SHARE one tile — the kanji repeat there, Latin never does, so drawing the
  block as a straight 10x2 image came out shifted and doubled. The build
  straightens that map (`BATTLE_BANNER_MAP` in gfx.py) and pads the corners
  with the banner's own outer columns, so the word must measure ≤62px; the
  columns are checked and the sheet is left Japanese when they carry ink.
  Before drawing into any BG sheet, dump VRAM in the real frame and read the
  screenblock: the map, not the sheet, says where each tile lands.
- ~1969 compressed graphic blocks exist ROM-wide (Malias + BIOS LZ77). The
  full visual classification lives in `docs/GFX-BACKLOG.md` (sanitised, 25
  pending blocks, priorities, duplicate pairs, and the LZ77-codec blocker);
  transcriptions stay local in work/inventory/RESULTS.md.

## Gotchas that already cost time

- Kabuto is the same game at shifted offsets — `Release` in `navi/rom.py` has a
  stub; fill its constants before touching a Kabuto dump.
- The catalog key is `script:NNNN:OFFS` / `str:OFFSET` — stable per release
  only. Kabuto will need its own packs or key remapping.
- `Charset.multi` handles `[<3]` and `[note]` spellings; width checks count
  them as one cell.
- mGBA's CLI binary is GUI-only; anything headless goes through gbashot.
- New glyphs in `data/glyphs-latin.txt` must keep ink inside columns 2-6
  (tests/test_glyph_margins.py enforces it): the battle unit panel and the
  name keyboard bake a 1px outline inside each 8px cell, and every NATIVE
  capital/digit runs to column 6 — only our own column-0 background pixel
  separates the outlines. Native glyphs stay untouched; their merged
  outlines are the game's own look.
- **The battle part panel's effect row is 9 cells and OVERFLOWS, it does not
  clip.** Each row of that panel owns a fixed run of BG0 tiles (2 tiles per
  cell): the effect row starts at tile 0xC8 and the terrain bar starts at
  0xDA, so a 10th character is drawn on top of `--------- BOSQ` (probed with
  9/10/11-char strings; the Japanese never exceeds 9 either). Both tables that
  feed it — skill/effect names (24-byte field, stride 0x80, from 0x0930D8) and
  Medaforce names (16-byte field, stride 0x78, from 0x090BF8) — must stay ≤9
  characters; tests/test_panel_width.py enforces it over both packs. An
  UNTRANSLATED entry there is not harmless: its katakana lands in the kana
  codes the font build re-used for Latin lowercase and draws as garbage
  (a four-katakana attack name came out as `(Bé/`), so every name in those
  tables needs a translation, not just the long ones.
- The battle bar keeps a few literals (turn counter, AP charge, the robottle
  jingle, rule numbers) as **Shift-JIS** at 0x4BA7AC-0x4BC1D8, transcoded to
  the game charset at compose time. Translate them via gfx.json
  `sjis_strings` using **fullwidth** Latin (ＴＵＲＮＯ) — halfwidth ASCII
  truncates to garbage in the transcoder. That's also why charset searches
  never find these strings.
- The battle-message pointer table starts at **0x4C8660**, not 0x4C8738 —
  the first 54 entries (attack announcements, traps, can't-act) hide before
  the obvious run. Messages can be NESTED (one is the tail of another):
  in-place writes must never cross another live target (see
  `_write_battle_messages`).
- A string that does not end in `<WAIT>`/`<END>`/`<CLEAR>` **flows into the next
  string on the same row** (the engine keeps the box open across 0x01 text
  ops). The validator measures strings in isolation, so when the Japanese
  original ends without a boundary tag, keep the translation's final row short
  enough that the next string's first row still fits beside it (22 visible) — and check the
  seam in a gbashot screenshot.
