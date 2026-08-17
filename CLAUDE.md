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
python3 tools/align.py <kabuto.gba>   # regenerate data/offsets-kabuto.json
```

Two packs ship: `langs/es` (es-419) and `langs/en` (English dub canon). Both
build for either release — point `navi.py rom` at the dump you want and the
same pack applies (see "The two releases").

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

## The two releases

Kuwagata and Kabuto shipped the same day and are ONE build with the data
shifted: 159 of the 170 event scripts are byte-identical, the fonts and tables
move by a few hundred bytes, and only the cover Medabot's own scenes differ.
Kuwagata is canonical here — every offset written down in this repository is a
Kuwagata offset — and `navi/align.py` places it in the other cartridge. Kabuto
constants live in `rom.py` like Kuwagata's (script table 0x629728, font
0x657D60, kanji font 0x658540, 1bpp table 0x4C7608; the first three agree with
Normmatt's independently reversed values). Regenerate the map with
`python3 tools/align.py "…Kabuto (Japan).gba"` — it prints where each anchor
landed and refuses to be quiet about one it could not place.

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

- **22 visible columns on a box's FIRST row, 21 on the second.** The last
  cell of a second row is never drawn: a 22-character row there loses its
  final letter and nobody notices while reading a diff (346 rows were doing
  it). Proved with an A-Z ruler in-game; the cartridge agrees, 38 of its
  22-column rows are first rows and only 2 are not. `validate` and
  tests/test_second_row_width.py enforce both limits. And before calling
  anything truncated, sample DENSELY: the box types character by character,
  and the little continue arrow only appears once it has finished.
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
  build refuses that line. A pack is written against Kuwagata and serves both
  releases; `langs/<code>/kabuto/` holds only what that cartridge words its
  own way, loaded on top when the dump is a Kabuto one. On a non-canonical
  release `validate` reports `absent` (that cartridge has no such line) and
  `differs` (it says it its own way) instead of `orphan`/`stale`, and neither
  blocks a build — the fingerprint leaves those lines Japanese, which is the
  honest outcome until someone translates them. **Never commit Japanese text,
  ROM bytes, `work/`, `build/`, `dist/`, or any `.gba`.**
- The pack-specific tests are parameterised over EVERY pack in `langs/`
  (`language_packs()` in tests/conftest.py): a rule the cartridge imposes is
  not a Spanish rule, and a new language gets the same enforcement for free.
- Translation style: es-419, Latin-American dub canon (`langs/es/GLOSSARY.md`);
  English follows the Nelvana dub (`langs/en/GLOSSARY.md`): Medabot,
  Medafighter, Robattle, Medaforce, Medapart, Medawatch, Tinpet. The Sperobo
  verbal tic is a trailing `-robo` in both; drop it when a row would exceed
  the visible width.
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

- **Kabuto is the same build at shifted offsets, and that is now derived, not
  re-reversed.** `navi/align.py` aligns the two dumps into 2205 byte-identical
  runs covering 97.5% of the cartridge (committed as `data/offsets-kabuto.json`
  by `tools/align.py`, offsets only). Every constant in this project stays a
  KUWAGATA offset and goes through `rom.at(offset, length)` at the point of
  use; `None` means the releases differ there and the caller must leave it
  alone. NEVER pass an offset read out of the ROM through `at` — it is already
  in that dump's space. Pointer TABLES cannot be content-matched (their bytes
  are the addresses that differ): they are found by mapping what they point at,
  in `tools/align.py`.
- The catalog key is `script:NNNN:OFFS` / `str:OFFSET`, and it names where
  KUWAGATA keeps the line **in both releases**, so one pack serves both — 4323
  of the Spanish pack's 4481 lines apply to a Kabuto dump unchanged. A line
  only the other release has is keyed `str:KBT:OFFSET`; what Kabuto words
  differently (the Grand Beetle scenes, a few name tables) lives in
  `langs/<code>/kabuto/` and is loaded on top when the dump is Kabuto.
  The loose scan is a heuristic and finds slightly different runs on each
  cartridge, so the catalogue is also SEEDED from the pack's own keys
  (`catalog.seeded`) — same finding, read through the alignment.
- `Charset.multi` handles `[<3]` and `[note]` spellings; width checks count
  them as one cell.
- **Fused fixed-table records** (several 8-byte name fields with no
  terminator decode as ONE loose string: medal/model tables at 0x0929A9+/
  0x092C40+): translate them as a single entry whose payload replicates the
  exact byte structure — names ≤7 + `<B:00>` separators, and `<B:xx>` copies
  of any stats tail the decode swallowed — because the loose writer zero-pads
  the whole decoded length. A short-JP field that needs a longer Latin name
  goes through gfx.json `extra_strings` (room 8) instead, which runs AFTER
  the loose pass: the fused entry preserves that field's kana verbatim so the
  fingerprint still matches when extra_strings overwrites it. `<B:00>` counts
  as a row break in `lines_of` for the same reason.
- mGBA's CLI binary is GUI-only; anything headless goes through gbashot.
- **The in-game SAVE stores an absolute ROM pointer into script text** (one
  32-bit word at .sav offset 0x3220, e.g. 0x0885E080 — the dialogue the
  event engine was on). Relocated text moves with every build, so a save
  made on build A dereferences a DIFFERENT line on build B: the engine runs
  whatever bytes are there and lands in unrelated code (a corrupted name
  entry screen opened when walking, with the save otherwise intact).
  Diagnosed by: same .sav on the pristine Japanese ROM behaves fine; RAM at
  the frame before the jump is byte-identical between two builds, and the
  ONLY differing pointer is that one. The right value is COMPUTABLE, no
  guessing: the loader builds it as
  ``master_table[ram[0x0201B3A8] * 5 + ram[0x0201B3A9]]`` (map byte and
  sub-index, both carried in the save; literals in the pool at 0x08084110).
  Zeroing the word only stops the crash — it leaves every NPC mute, because
  that pointer IS the scene's dialogue. Rescue: load the save, poke the
  computed value into 0x0201B334 (``gbashot --poke FRAME:ADDR:VALUE``) and
  save in-game so the game writes its own checksum; the .sav cannot be
  edited by hand, its checksum at 0x14 is not a plain sum.
  ``tools/savecheck.py ROM SAV`` says whether a save still matches a build
  — run it before handing a new build to someone mid-game.
- **A word in the BOOT code can equal a string address by coincidence** (two
  THUMB instructions at 0x334 spelled a pointer to a 3-byte junk "string"
  the scanner accepted). Relocating that "loose string" rewrote the boot
  code and white-screened the ROM at power-on. The loose writer now refuses
  to repoint any site below 0x8000, and `supplement()` filters them too;
  after ANY change to relocation logic, boot the build from power-on with
  gbashot before shipping it.
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
- **A battle message may never COMPOSE wider than its Japanese original.**
  The destruction cinematic's renderer leaks 4 bytes of stack per composed
  cell (epilogue 0x08042A00); one over-wide message walks the return address
  onto a stale register and the game jumps to 0x040000D4 and resets. Proven
  by single-message bisection; ROM byte count is irrelevant, only composed
  cells count, and which messages the cinematic can show is not statically
  knowable — so the rule is blanket over the whole table. `<NL>x` inserts
  count at their expansion width (names 8, numbers 3, slot labels 4 — the
  コ insert copies a FIXED BYTE COUNT, the one its Japanese label occupied,
  never seeking a terminator: 頭 is 2 bytes so the head label must BE 2
  chars ("CB"), while 右腕/左腕/脚部 are 4 and keep 4-char labels; verified
  per slot in-game. Tables in navi/build.py). The build
  refuses violators (the line shows Japanese instead) and
  tests/test_battle_compose.py keeps the pack at zero refusals. Fingerprints
  are charset-sensitive: a `.tbl` respelling silently orphans pack keys, so
  the test also fails on keys with no Japanese behind them.
- **Neighbouring text is NOT proof of one string.** A few strings really are
  CHAINS the engine reads through `<CLEAR>` (the Navi terminal's three-box
  greeting), but the opcode walker misses sites, so two lines of DIFFERENT
  speakers sitting next to each other look identical to a chain. Reading
  them as one showed an NPC's line twice — the second time with the other
  character's portrait — and, when the merged translation fitted in place,
  BLANKED a live line and left a save unplayable. `CHAIN_KEYS` in
  navi/script.py lists the ones verified on screen; everything else is read
  as a single box.
- A string that does not end in `<WAIT>`/`<END>`/`<CLEAR>` **flows into the next
  string on the same row** (the engine keeps the box open across 0x01 text
  ops). The validator measures strings in isolation, so when the Japanese
  original ends without a boundary tag, keep the translation's final row short
  enough that the next string's first row still fits beside it (22 visible) — and check the
  seam in a gbashot screenshot.
- **Check a line against its BOX, in navi/boxes.py, not against one rule.**
  The cartridge has several and they differ in the two things that matter:
  columns before the cut, and which control codes they honour. Measured with
  an A-Z-0-9 ruler written into the field — the last character drawn IS the
  width: dialogue 22 then 21, the medal card's bar 26 and the part card's 28,
  and in both of those bars the SECOND row keeps its last cell, unlike the
  dialogue box. `python3 tools/wide.py` walks the pack against them. Where a
  width is not measured the box says `None` and the check skips it: ten correct
  battle-bar lines were being held to 22 when "¡Robobatalla con START!" (23)
  demonstrably renders whole, and an honest gap beats a guessed number.
  Offsets matter — the aptitude table starts at 0x090744 (0x0906F4 is the
  action-name table, stride 8), the skill table's last record has its
  descriptions PAST its name at 0x0956D8, and the medal and Medaforce pages
  share ONE 26-column bar.
- **A box that does not support a control code does worse than ignore it.** In
  the Medarreloj's description bars `<NL>` swallows ITSELF AND THE CHARACTER
  AFTER IT: "Ataque de combate`<NL>`básico" drew as `Ataque de combateásico`
  and "Ataca al Medabot`<NL>`más cercano" as `Ataca al Medabotás cerca`. Both
  read like clipping and neither was. The Japanese is the evidence for what a
  field accepts — those description fields use no control code at all — so
  tests/test_control_codes.py checks every line against the BOX that draws it
  (`navi/boxes.py`), not against a list of blessed sites, and refuses any code
  that box does not honour. `python3 tools/codes.py` lists them with both texts
  side by side; `python3 tools/wide.py` walks the pack against the same boxes.
- **The robattle chatter bar is NOT the dialogue box, and this cost 37 lines.**
  The 412 quips a rival drops at the start and end of a battle (0x08D490-
  0x08FF90) draw in the bar under the two teams on the ROBOTTLE! screen, and it
  **does not page**: a `<WAIT>` there is not honoured and everything after it is
  silently not drawn. "¿Robobatalla? Acepto,`<NL>`¿pero podrás`<WAIT>`competir?"
  reached a player's screen as two rows ending in "¿pero podrás". Thirty-seven
  Spanish lines had used `<WAIT>` as if it were a page break, purely to escape
  the 21-column second row, and every one of them was losing its ending. The
  cartridge says so plainly: all 412 Japanese lines use `<NL>` exactly ONCE and
  `<END>` at the end (ten also a `<PLAYER>`), and not one uses `<WAIT>` or
  `<CLEAR>` — the pool is written for two rows and a single screenful. It is now
  its own box (`ROBATTLE_CHATTER`), so the test enforces it for every pack.
  The lesson generalises: when a whole class of sites is exempted from a rule,
  the exemption is a claim about a box, and it can simply be wrong.
- **An index-reached string in menus.json will be RELOCATED and lost.** The
  loose-string writer moves a translation that outgrows its field and repoints
  its pointers, which is right for pointer-reached text and silently wrong for
  a table the game indexes: the leg-type terrain line at 0x09579C moved to the
  ROM tail, its two pointers followed, and the game kept reading the Japanese
  that was still in the field — drawing kana soup, and fragments of other
  relocated strings in the row below. Its six siblings were in `extra_strings`,
  written in place, which is why only that one failed. Index-reached text
  belongs in `extra_strings` or in `SLOT_TABLES`, never in the loose pass.
- **A site may have exactly ONE writer.** menus.json and gfx.json
  `extra_strings` can both name the same offset; the loose writer runs first,
  and extra_strings then fails its own fingerprint check (the bytes no longer
  hold the Japanese) and is skipped in silence. That is how "Ataca al
  Medabot`<NL>`más cercano" shipped and drew as `Ataca al Medabotás cerca` —
  that box does not honour `<NL>` — while the version that renders correctly
  on its three sibling sites never got to write this one.
  tests/test_one_owner.py keeps the two lists disjoint.
- **Several of this game's labels cannot be written as text AT ALL.** 装甲 成功
  威力 対象 射程 熟練度 消費 推進 近接 遠隔 use kanji that have NO code in
  `charset-jp.tbl` (甲 成 功 威 象 射 程 熟 練 費 推 近 遠 隔), and the 6160
  strings of the corpus never emit one — they exist only as pixels. Before
  hunting a label through the string tables, check whether its kanji are even
  encodable; if they are not, it is a sheet or a glyph bank and nothing else.
  Of the sixteen codes those screens do use, thirteen point at the EMPTY cell
  in both glyph banks, so there is nothing to repaint there either.
- **The Medarreloj's status screens are one sheet, and it had a twin.** The
  seven kanji labels of the part page (行動 装甲 回数 成功 威力 対象 射程) are
  pre-rendered 4bpp pixels in `medal-status-tileset` (block 0x6471E0, 8 tiles
  wide, relocated by the build), NOT a glyph bank: E014/E018 are repainted in
  both banks and the screen still showed Japanese. Its twin
  `parts-status-tileset` (0x6FC0F0) already carried every one of them, so the
  fix was to copy the twin's two-letter pairs onto this sheet's tile numbers.
  When a screen keeps showing Japanese although its codes are handled, check
  whether a SECOND sheet feeds it and whether the twin's spec is the complete
  one.
- **Find leftover Japanese without playing: `python3 tools/leftovers.py
  build/…-es.gba`** (and `navi.py build` prints the count). It diffs the built
  ROM against the dump and reports runs the build never touched that still
  read as text, worst first — the ones on codes the font re-used for Latin
  draw as GARBAGE, not as Japanese, so they come first. Two signals, because
  neither is enough: the bigram model finds prose but NOT tables of katakana
  proper nouns (they score worse than tile data — the model learned the
  scripts' hiragana), and "how many bytes did the build rewrite within ±0x40"
  finds a name we missed among names we translated. Event scripts and strings
  the pack already relocated are skipped — a longer translation leaves its
  Japanese sitting there, dead, and that is not a leftover. What is left over
  is diffed against `langs/es/leftovers.json`, which holds OFFSETS ONLY (the
  Japanese must never enter the repo) and silences the noisy
  neighbourhood-only class, so a NEW leftover stands out.
- **Index-reached NAME tables need one catalog entry per slot** —
  `SLOT_TABLES` in navi/strings.py, `(first slot, stride, slots, width)`. A
  name that fills its slot leaves no terminator, so the pointer scan reads it
  and the slot next door as one run; translating that run wrote over BOTH and
  zeroed the second. Eighteen part names drew as an empty gap that way, in
  silence. The declaration also reaches tables nothing points at, which the
  scan cannot see at all: the medal FAMILY column and the 39 cluster room
  names were never catalogued and stayed Japanese for months.
- **The cast-name table is 86 records, not the ten the pack had** — 0x7ECA90,
  stride 0x10, an 8-character field padded with 0xDB. These are the names the
  robattle screen shows, so kana left there is drawn through the patched font
  and comes out as Latin soup (ヒヨリ rendered `Á")`). Nothing points at the
  table, so the scan never saw it and the ten that were translated were the
  ten someone had listed by hand. gfx.json `names` covers all 86 now and
  tests/test_cast_names.py keeps it that way; the transliterations follow the
  spellings the dialogue already ships (Shiden, Hiyori, Fubuki, Rainy…), and
  the records that name a role rather than a person are translated
  (ほうどうじん → Prensa, かかリいん → Personal, だんいん → Miembro).
- **A medal record carries two names.** The record is 0x1C bytes: the medal's
  own name at `0x0929A0 + id*0x1C` (read by 0x0804BCF8) and its FAMILY —
  クワガタ, カブト, ザウルス… — at `0x092998 + id*0x1C`. "You got the X medal"
  inserts the FAMILY, so leaving that column Japanese printed four kana
  through the Latin font (`H¿ガP`).
- **An insert is 20 bytes at `0x030014D0 + slot*20`**: cleared to spaces
  (0x0807C1BC), the name copied over its first 8 bytes, then trailing spaces
  trimmed BACKWARDS FROM BYTE 7 (0x0807C198). So a name field holds **7
  characters**, never 8: an eight-character name gets no terminator and the
  printer runs on into the rest of the slot. tests/test_slot_tables.py keeps
  every slot translated and inside its field.
- The result composer's pieces are cut at a 0x0F0 byte, and **kanji get in the
  way**: 変 is 0xE0F0, so scanning for a bare 0xF0 stops on its second half
  and keeps 化した! as the piece's "tail", which the game then draws.
  `_piece_break` walks the encoding instead. A piece must also keep the row
  breaks and number slots (0x01/0x02/0x03) **where the Japanese put them** —
  the composer places the value itself, and a marker moved five cells right
  printed the level jammed onto the end of the word. The build refuses a
  piece whose skeleton drifted (`piece_skeleton`), and
  tests/test_piece_skeleton.py keeps the pack at zero refusals.
- **Every build invalidates the player's save; `tools/savefix.sh ROM SAV`
  repairs it.** The scene pointer at .sav 0x3220 / RAM 0x0201B334 is absolute
  and the build relocates scripts. The game does NOT recompute it on load, so
  loading and saving again preserves the stale value — the repair has to poke
  `master_table[ram[0x0201B3A8]*5 + ram[0x0201B3A9]]` in first, then save
  in-game. Editing the .sav by hand is out: the word at offset 0x14 is a
  HASH, not a checksum (byte/half/word sums and CRC32 over every plausible
  range were tried against four real saves; none match), and the loader
  rejects a save whose hash does not fit.
