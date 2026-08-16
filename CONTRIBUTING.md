# Contributing

Thanks for wanting to help. The short version: fix lines, keep the box happy,
never commit game data.

## Fixing a translation

1. `python navi.py rom <your dump>` once, then `python navi.py extract es`.
2. Open `work/kuwagata/…json` — Japanese and Spanish side by side. Find the
   line, note its `key`.
3. Put your fix in `langs/es/` (edit the entry with that key), or write a
   `work/tr_yourfix.py` with `T = {"<key>": "<text>"}` and run
   `python tools/apply.py es`.
4. `python navi.py validate es` must come back clean. The text box is 32
   characters wide, two rows per screenful; the validator is the referee,
   not a suggestion.
5. `python navi.py build es`, and if you can, eyeball it with
   `tools/gbashot` (see CLAUDE.md).
6. Commit `langs/es/` only. Pull requests that touch `work/`, `build/`,
   `dist/` or any `.gba` will be asked to slim down.

## Style

`langs/es/GLOSSARY.md` and `langs/es/NAMES.md` are law. es-419, `ustedes`,
dub-canon terms. When a row will not fit, cut words, not accents.

## Adding a language

`docs/ADDING_A_LANGUAGE.md`. In short: copy `langs/es/`, empty the `"t"`
fields, translate; if your language needs glyphs the font lacks, draw them in
`data/glyphs-latin.txt` (ASCII art) and run `python navi.py slots --write`.

## Tooling changes

`pytest -m "not game"` runs without a dump; `pytest` runs everything against
yours. Keep both green. New ROM facts go in `navi/rom.py` next to the ones
that are already there, with the evidence in a comment.

## What not to send

Game files, ROM excerpts, the Japanese script, or screenshots containing large
amounts of untranslated Japanese text. Fingerprints and your own words only.
