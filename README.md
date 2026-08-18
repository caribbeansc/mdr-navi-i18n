# Medarot Navi, in your language

**メダロットnavi** (GBA, 2001) never left Japan, so it only speaks Japanese.

[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20me%20a%20coffee-ffdd00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black)](https://buymeacoffee.com/caribbeansc)

**What this repository is for:** handing anyone the tooling to translate it
without reverse-engineering anything themselves. You point it at your own dump,
type your text, and it builds you a patched ROM. Adding a language takes a
folder, not code, and improving a translation that is already here takes a pull
request.

It starts out with two translations:

| Language | Text | Artwork | State |
|---|---:|---:|---|
| Español | 4480 lines (100%) | 314 labels | playable, in final validation |
| English | 4480 lines (100%) | 314 labels | playable, in final validation |

Every line of game text the catalogue reads is covered — all 170 event
scripts and every real loose string. The raw scan lists 5802 candidates; the
other 1322 are scanner artifacts (data that happens to decode as kana:
character tables, tile rows) or index-reached lines the graphics pass writes
instead, and "translating" them here would corrupt them.

Each glossary follows the anime's own dub — the Latin American one (Etcétera
Group / Fox Kids, 2002) for Spanish, the English one (Nelvana / Fox Kids, 2001)
for English — so a player meets the same words here, in the sibling game
[medarot-rb-i18n](https://github.com/caribbeansc/medarot-rb-i18n), and on
television.

**Both releases work.** Medarot Navi shipped as Kuwagata and Kabuto on the same
day, and they are the same build with the data shifted a few hundred bytes. A
pack is written once, against Kuwagata, and `navi/align.py` says where each of
its lines lives in the other cartridge; only what the two releases genuinely
word differently — the cover Medabot's own scenes — needs its own translation,
under `langs/<code>/kabuto/`.

> **You need your own copy of the game.** These tools read your own cartridge
> dump. They do not contain the game and cannot get it for you.

## Play it — the easy way (no Python, no terminal)

Download the patcher from the
[**latest release**](https://github.com/caribbeansc/mdr-navi-i18n/releases/latest).
It is built automatically from this repository and contains nothing from the
game. Pick the file for your computer:

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
   you're sure — click **Open**. After that it opens like any app. This extra
   step is only because the app isn't signed with a paid Apple certificate.

### Then, on either system

1. Point the patcher at your own dump of the game (a `.gba` file) — Kuwagata
   or Kabuto, it tells them apart on its own.
2. Pick a language and click **Create patched ROM**. Seconds later the
   translated ROM appears next to your dump, named
   `medarot-navi-<release>-<language>.gba`; your original file is not touched.

Prefer plain patch files? Every release also ships the IPS patches: apply the
one matching your cartridge with
[RomPatcher.js](https://www.marcrobledo.com/RomPatcher.js/), or give the
`.ips` the ROM's own name next to it and mGBA patches on load.

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
`python navi.py validate es` — it measures every line against the 32-character
text box and refuses what will not fit — then `build`.

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
the module docstrings under `navi/` — every offset is written down next to the
code that uses it.

`tools/gbashot` (optional, `brew install mgba libpng && make -C tools`) runs
the ROM headless at unlocked speed and takes screenshots, so a change can be
verified against real pixels without opening an emulator.

## Support

If this made the game playable for you, you can buy me a coffee. Fixing a
line that reads wrong helps just as much.

[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20me%20a%20coffee-ffdd00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black)](https://buymeacoffee.com/caribbeansc)

## Licence

Code MIT ([LICENSE](LICENSE)); translations CC BY-SA 4.0
([LICENSE-TRANSLATIONS](LICENSE-TRANSLATIONS)). Unofficial fan project, not
affiliated with Natsume, Imagineer or Nintendo ([NOTICE](NOTICE)). Please do
not open issues or pull requests containing game files or the original
Japanese text.
