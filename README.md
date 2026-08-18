# Medarot Navi, in your language

[![Download IPS patches and the patcher](https://img.shields.io/badge/Download-IPS%20patches%20%C2%B7%20patcher-2ea44f?style=for-the-badge&logo=github)](https://github.com/caribbeansc/mdr-navi-i18n/releases/latest)
[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20me%20a%20coffee-ffdd00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black)](https://buymeacoffee.com/caribbeansc)

**メダロットnavi** (GBA, 2001) never left Japan, so it only speaks Japanese.

**Just want to play?** Grab the ready-made IPS patches or the Windows/macOS
patcher from the
[**latest release**](https://github.com/caribbeansc/mdr-navi-i18n/releases/latest).
See [Play it](#play-it--the-easy-way-no-python-no-terminal) below.

**What this repository is for:** translating the game without
reverse-engineering anything. Point it at your own dump, type your text, and
it builds a patched ROM; a new language is a folder, not code.

It starts out with two translations, both covering the game's full text:

| Language | Text | Artwork | State |
|---|---:|---:|---|
| Español | 100% | 314 labels | playable, in final validation |
| English | 100% | 314 labels | playable, in final validation |

**Both releases work.** Kuwagata and Kabuto are the same build with the data
shifted a few hundred bytes: one pack serves both cartridges, and only the
cover Medabot's own scenes need their own translation.

> **You need your own copy of the game.** These tools read your own cartridge
> dump. They do not contain the game and cannot get it for you.

---

## Play it — the easy way (no Python, no terminal)

Every [**release**](https://github.com/caribbeansc/mdr-navi-i18n/releases/latest)
ships two ways to play, both built automatically from this repository and
containing nothing from the game:

- **IPS patches** — `medarot-navi-<release>-<language>.ips`, one per cartridge
  and language. Apply the one matching your dump in the browser with
  [RomPatcher.js](https://www.marcrobledo.com/RomPatcher.js/), or give the
  `.ips` the ROM's own name and keep them side by side; mGBA patches on load.
- **The patcher** — a double-clickable app that applies the translation for
  you and writes the patched ROM next to your dump. Pick the file for your
  computer:

### Windows

1. Download **`MedarotNavi-Patcher-Windows.exe`** and double-click it.
2. The first time, Windows may warn that it doesn't recognise the app (it is
   free software without a paid publisher certificate). Click **More info**,
   then **Run anyway**. The whole source is in this repository if you want to
   check it first.

### macOS

1. Download **`MedarotNavi-Patcher-macOS.zip`** — one app for every Mac,
   Apple Silicon and Intel alike.
2. Double-click the `.zip` to unpack the app, then **right-click it and choose
   Open** (not a normal double-click) the first time. macOS asks once whether
   you're sure; click **Open**. After that it opens like any app. This extra
   step is only because the app isn't signed with a paid Apple certificate.

### Then, on either system

1. Point the patcher at your own dump of the game (a `.gba` file): Kuwagata
   or Kabuto, it tells them apart on its own.
2. Pick a language and click **Create patched ROM**. Seconds later the
   translated ROM appears next to your dump, named
   `medarot-navi-<release>-<language>.gba`; your original file is not touched.

## About the translations

Both packs were written by an LLM, so take them as **a starting point, not a
finished localisation**: 100% means every line is translated, not that every
line is right; the goal is to polish them from here, together. Fixing a line
takes a minute, and every correction reaches everyone. See
[Fix a line](#fix-a-line-or-add-a-language).

Each glossary follows the anime's own dub: the Latin American one (Etcétera
Group / Fox Kids, 2002) for Spanish, the English one (Nelvana / Fox Kids, 2001)
for English. A player meets the same words here, in the sibling game
[medarot-rb-i18n](https://github.com/caribbeansc/medarot-rb-i18n), and on
television.

## Use it — from source

You need Python 3.10+, nothing else. `python gui.py` opens the same graphical
patcher; the menu below does the same and more from the terminal:

```
git clone <this repo>
cd mdr-navi-i18n
python navi.py
```

Then work down the menu: point it at your `.gba`, look inside, build. The
patched ROM lands in `build/`, and an IPS patch for sharing in `dist/`.

```
  1  Point me at the game     set the ROM this works on
  2  Look inside              what text the dump holds
  3  Read the game's text     dump everything into work/
  4  Check a translation      widths, tags, missing glyphs
  5  Build a patched ROM
  6  Preview the font
  7  Diagnose
```

## Fix a line, or add a language

`python navi.py extract es` writes every line of the game into `work/`, the
Japanese on one side and the Spanish on the other. Fix what reads wrong, run
`python navi.py validate es`, which measures every line against the
32-character text box and refuses what will not fit, then `build`.

A new language is a folder: copy `langs/es/`, empty the `"t"` fields, translate.
If your language needs characters the font lacks, draw them in
`data/glyphs-latin.txt` (they are ASCII art) and run
`python navi.py slots --write`.

## No game data, by design

A translation is stored as a reference to a line plus your text, never the
Japanese:

```json
{"key": "script:0048:04BF", "src": "8b1a7f22c0d4", "t": "..."}
```

`src` is a fingerprint: enough to notice when the game's text changes, useless
for reconstructing it. A validation pass refuses to build lines whose source no
longer matches your dump. `work/`, `build/` and `dist/` are never committed.

## How it works, briefly

The game keeps its dialogue in 170 bytecode scripts and its menus as
pointer-reachable strings; the font is 1bpp with no lower case and no accents.
The build teaches the font the missing letters (in the kana slots the game uses
least, so untranslated text stays readable), overwrites lines that fit, and
relocates whole scripts when they grow. Details in
[docs/PIPELINE.md](docs/PIPELINE.md) and in
the module docstrings under `navi/`. Every offset is written down next to the
code that uses it.

`tools/gbashot` (optional, `brew install mgba libpng && make -C tools`) runs
the ROM headless at unlocked speed and takes screenshots, so a change can be
verified against real pixels without opening an emulator.

## Support

If this made the game playable for you, you can buy me a coffee. Fixing a
line that reads wrong helps just as much.

[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20me%20a%20coffee-ffdd00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black)](https://buymeacoffee.com/caribbeansc)

## The rest of the series

This repository is one piece of a longer effort to translate **every Medarot
game**. [medarot-rb-i18n](https://github.com/caribbeansc/medarot-rb-i18n)
does the same for メダロット カードロボトル RB (Switch), Medarot 9 (3DS) is
about 60% translated, and once the series is covered the plan is to move on
to other sagas that never received a translation.

## Credits

Prior art and tools this project stands on. The detail lives in
[NOTICE](NOTICE) and [docs/EXTERNAL-REPOS.md](docs/EXTERNAL-REPOS.md):

- [Normmatt/Medarot-Navi-GBA-Translation](https://github.com/Normmatt/Medarot-Navi-GBA-Translation) —
  the character table our charsets derive from, the script-bytecode opcode
  sizes, the "Malias" graphics codec ported from Malias2.cs, the
  already-reversed Kabuto addresses, and the proof that the cartridge maps
  ROM past 8 MB.
- [Medabots/medarot-navi](https://github.com/Medabots/medarot-navi) — the
  full-disassembly attempt; its dual-release Makefile is why one pack serves
  both cartridges here instead of forking.
- [mGBA](https://mgba.io) — `tools/gbashot` and `gbawatch` link against
  libmgba; every in-emulator verification in this project runs on it.
- [medarot-rb-i18n](https://github.com/caribbeansc/medarot-rb-i18n) — the
  sibling project this repository is modelled on: language packs holding
  fingerprints and translations, never the game.

## Licence

Code MIT ([LICENSE](LICENSE)); translations CC BY-SA 4.0
([LICENSE-TRANSLATIONS](LICENSE-TRANSLATIONS)). Unofficial fan project, not
affiliated with Natsume, Imagineer or Nintendo ([NOTICE](NOTICE)). Please do
not open issues or pull requests containing game files or the original
Japanese text.
