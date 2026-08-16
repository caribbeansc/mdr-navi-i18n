# Adding a language

A language is a folder under `langs/`, not code. The Spanish pack is the
template; the whole process is copy, empty, translate, build.

## 1. Copy the Spanish pack

```
cp -r langs/es langs/fr
```

Edit `langs/fr/lang.json`: set `code`, `name`, `english_name`, your `credits`,
and the accented characters your language needs in `validation.extra_chars`.
Delete `GLOSSARY.md` or replace it with your own terminology notes.

## 2. Empty the translations, keep the keys

Every entry looks like `{"key": ..., "src": ..., "t": ...}`. Set every `"t"`
to `""` and leave `key` and `src` alone — they name the line in the ROM and
fingerprint its Japanese, and they are identical for every language:

```
python3 - <<'EOF'
import json, pathlib
for p in pathlib.Path("langs/fr").rglob("*.json"):
    d = json.loads(p.read_text())
    if "entries" not in d: continue
    for e in d["entries"]: e["t"] = ""
    p.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n")
EOF
```

## 3. Draw any glyphs the font lacks

The font has no lower case and no accents; the build adds them from
`data/glyphs-latin.txt`. If your language needs characters that are not in
that file (say `ç` or `à`), draw them there: each glyph is its name on one
line, then 9 rows of 8 characters, `#` for ink. The comment at the top of the
file shows where the baseline and descenders go. (`¿` and `¡` are special:
the build rotates the game's own `?` and `!`, so do not draw those.)

Then let the tools pick which kana codes the new glyphs displace:

```
python navi.py slots [--write]
```

Run it once without `--write` to see the cost — it should stay around 2% of
the game's characters — then with `--write` to regenerate
`data/charset-latin.tbl`. Packs store text, not bytes, so reassigning codes
never breaks an existing language.

## 4. Translate, validate, build

```
python navi.py extract fr     # work/kuwagata/*.json, Japanese beside your text
python navi.py validate fr    # widths, tags, capacity, stale fingerprints
python navi.py build fr       # patched ROM in build/, IPS patch in dist/
```

Fill in the `"t"` fields (the `work/` dumps show the Japanese side by side;
see CLAUDE.md for the `work/apply.py` round-trip the Spanish pack uses).
`validate` measures every line against the 32-character, 2-row text box —
fix what it flags rather than skipping it — and `build` writes the patched
ROM. If you have built `tools/gbashot`, screenshot your first scenes and look
at them; docs/PIPELINE.md explains how.

Never commit Japanese text, ROM bytes, `work/`, `build/`, `dist/`, or any
`.gba`. A pack holds only keys, fingerprints and your own words.
