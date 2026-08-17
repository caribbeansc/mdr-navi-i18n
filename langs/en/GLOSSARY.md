# English glossary

The canon is the English dub of the anime (Nelvana / Fox Kids, 2001), the same
choice the Spanish pack makes for Latin America, so a player moving between the
two translations — or between this game and
[medarot-rb-i18n][rb] — meets the same words.

> The Japanese source terms are not in this document: the repository does not
> distribute the game's text. Run `python navi.py extract` and you will see the
> original next to every translation, under `work/`.

[rb]: https://github.com/caribbeansc/medarot-rb-i18n

## The hard constraint

The dialogue window shows **22 columns on a box's first row and 21 on its
second**, in a fixed-width font (the buffer behind it is 32 wide — overflow
lands in hidden tiles and simply never appears). There is no scrolling: a row
that overruns is not wrapped, it is not drawn.

English is close to Japanese in length and much shorter than Spanish, so most
lines translate straight — but the limit is the limit, and
`python navi.py validate en` measures every one of them. Where a shorter word
costs nothing, take it. Where it would cost the meaning, split the row with
`<NL>` or the screen with `<WAIT>`.

## Franchise terms

| English term | Note |
|---|---|
| **Medabot / Medabots** | CANON. Never `robot`, never `Medarot` in prose. |
| **Medafighter** | CANON. The kids who own and battle Medabots. |
| **Robattle** | CANON. Also a verb: `to Robattle`, `Let's Robattle!`. |
| **Medaforce** | CANON. The finishing move. |
| **Medapart / Medaparts** | CANON. `part` alone is fine inside a UI table. |
| **Medawatch** | CANON for the wrist device. Never `Medarotch`. |
| **Medal** | The Medal that drives a Medabot. Capitalised as an object, lower case in running prose. |
| **Tinpet** | CANON: left untranslated, as the dub did. |
| **Rokusho** | CANON. The KWG (Kuwagata) line, this release's cover Medabot. |
| **Metabee** | CANON. The KBT (Kabuto) line, the other release's. |

## This game's own terms

Medarot Navi is not the anime, and some of what it names has no dub to defer
to. These are settled here, and should not drift.

| English term | Note |
|---|---|
| **Sperobo Gang** | The gang that has taken the map. The game's own name for them, NOT the anime's Rubberobo Gang: this game names its own gang. Members: `the Sperobos`, one of them `a Sperobo`. |
| **Block** | A section of the map, taken and retaken. Kept literal: the game treats it as a place name. |
| **take a Block back** | What the player does to a Block. Not `conquer`: the player is taking it back. |
| **Boss** | A Sperobo officer, named after the terrain they hold: `Sea Boss`, `Mountain Boss`, `Sky Boss`. |
| **-robo** | The Sperobo tic of ending sentences with ロボ. Rendered as a trailing `-robo` on the last word where it fits (`This is terrible-robo!`), and dropped where it would push the row past its limit. Keeping it in most lines and losing it in a few reads better than shrinking every line to fit it. |

## Terrain

These are records in a fixed-stride table: **four characters, no more**, and the
build refuses anything longer. They are terrain types shown on the battle
screen, so an abbreviation is legible in context.

| English | Meaning |
|---|---|
| `SAND` | sandy ground |
| `DSRT` | desert |
| `HILL` | hill |
| `MNTN` | mountain |
| `GRSS` | grassland |
| `WOOD` | forest |
| `ROAD` | road |
| `TOWN` | town |
| `SHOR` | waterside |
| `SEA ` | sea |
| `AIR ` | air |
| `SPCE` | space |

The paired entries (`WOOD & HILL`) are a second table of eleven characters.

## Battle slot labels

The part-slot insert copies a FIXED BYTE COUNT, so these labels have to be
exactly as long as the kanji they replace: **head is 2 characters**, the other
three are 4.

| Slot | Label |
|---|---|
| head | `HD` |
| right arm | `R.Ar` |
| left arm | `L.Ar` |
| legs | `Legs` |

## English stays English

Whatever the original game already displays in English — on screen or in
dialogue, as text or as artwork — keeps exactly the form the cartridge gives
it: `push start`, `OPTION` / `TIME` / `BGM`, `WIN` / `LOSE`, `LV` / `EXP` /
`MF`, `ROBOTTLE!`, `MEDAROT`, `TYPE` / `LEVEL`, `PAGE`, the `navi` logo, and
any name the game itself writes in Latin letters (`FarEast`, part model codes
like `KWG-01NF`). The game chose those spellings as part of its visual
identity; the translation does not "fix" them into dub spelling, even where
the prose around them says Medabot and Robattle.

## Register

The cast are middle-schoolers, and the Sperobos are comic villains who lose.
Keep it spoken, not literary: `What do we do now?`, not `What are we to do?`.
Contractions everywhere (`don't`, `it's`, `we're`) — they read naturally and
they save columns.

American spelling throughout (`color`, `traveled`, `defense`).
