# Spanish glossary

The terms are in Spanish, because that is what they are. The notes are in
English so that anyone reviewing the pack can follow the reasoning.

> The Japanese source terms are not in this document: the repository does not
> distribute the game's text. Run `python navi.py extract` and you will see the
> original next to every translation, under `work/`.

The canon is the Latin American dub of the anime (Etcétera Group / Fox Kids,
2002), which is also what [medarot-rb-i18n][rb] uses, so a player moving between
the two games meets the same words.

[rb]: https://github.com/caribbeansc/medarot-rb-i18n

## The hard constraint

The dialogue window shows **22 columns and two rows**, in a fixed-width font (the buffer behind it is 32 wide — overflow lands in hidden tiles and simply never appears).
There is no scrolling: a row that overruns is simply not drawn. Spanish runs
roughly a third longer than the Japanese it replaces, so most lines have to be
re-cut rather than translated straight, and some have to be shortened on
purpose. `python navi.py validate es` measures every one of them.

Where a shorter word costs nothing, take it. Where it would cost the meaning,
split the line with `<NL>`, or the screen with `<WAIT>`.

## Franchise terms

| Spanish term | Note |
|---|---|
| **Medabot / Medabots** | CANON. Never `robot`. |
| **Medaguerrero** | CANON for Latin America. `Medaluchador` is the Spain term and is banned here. |
| **Robobatalla** | CANON. Verb: `robobatallar`. In tight UI, `Batalla`. |
| **Medafuerza** | CANON. |
| **Medaparte** | CANON. `Medapieza` is the Spain term and is banned. |
| **Medarreloj** | CANON, with the double r. |
| **Medalla** | The Medal that drives a Medabot. Capitalised when it is the object, lower case in running prose. |
| **Tinpet** | CANON: left untranslated, as the dub did. |
| **Rokusho** | CANON. The KWG (Kuwagata) line, which is this release's cover Medabot. |
| **Metabee** | CANON. The KBT (Kabuto) line. |

## This game's own terms

Medarot Navi is not the anime, and some of what it names has no dub to defer to.
These are settled here, and should not drift.

| Spanish term | Note |
|---|---|
| **Banda Sperobo** | The gang that has taken the map. The game's own name for them, not the Rubberobo of the anime, so it keeps its own name. Members: `los Sperobo`. |
| **Bloque** | A section of the map, taken and retaken. Kept literal: the game treats it as a place name. |
| **Recuperar un bloque** | What the player does to a Bloque. Not `conquistar`: the player is taking it back. |
| **Jefe** | A Sperobo officer. `Jefe de Mar`, `Jefe de Montaña`, and so on, after the terrain they hold. |
| **-robo** | The Sperobo tic of ending sentences with ロボ. Rendered as a trailing `-robo` on the last word where it fits (`¡Es terrible-robo!`), and dropped where it would push the line over 32 characters. Keeping it in most lines and losing it in a few reads better than shrinking every line to fit it. |

## Terrain

These are records in a fixed-stride table: **four characters, no more**, and the
build refuses anything longer. They are terrain types shown on the battle
screen, so an abbreviation is legible in context.

| Spanish | Meaning |
|---|---|
| `AREN` | sandy ground |
| `DESI` | desert |
| `LOMA` | hill |
| `MONT` | mountain |
| `PRAD` | grassland |
| `BOSQ` | forest |
| `RUTA` | road |
| `CIUD` | town |
| `ORIL` | waterside |
| `MAR ` | sea |
| `AIRE` | air |
| `ESPA` | space |

The paired entries (`BOSQ Y LOMA`) are a second table of eleven characters.

## English stays English

Whatever the original game already displays in English — on screen or in
dialogue, as text or as artwork — keeps its English form in the Spanish
translation: `push start`, `OPTION` / `TIME` / `BGM`, `WIN` / `LOSE`,
`LV` / `EXP` / `MF`, `ROBOTTLE!`, `MEDAROT`, `TYPE` / `LEVEL`, `PAGE`,
the `navi` logo, and any name the game itself writes in Latin letters
(`FarEast`, part model codes like `KWG-01NF`). The game chose English as part
of its visual identity; the translation respects that choice.

## Register

The cast are middle-schoolers, and the Sperobo are comic villains who lose. Keep
it spoken, not literary: `¿Qué hacemos?`, not `¿Qué habremos de hacer?`.

Use es-419 throughout: `ustedes`, never `vosotros`.
