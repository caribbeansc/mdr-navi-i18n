# Graphics still to redraw

Every piece of on-screen Japanese that is **pixels, not strings**, found by
decompressing all 1969 compressed blocks in the Kuwagata dump (Malias + BIOS
LZ77), rendering them as tile sheets, and classifying each one visually.
Verdicts over the whole ROM: 1780 blocks with no text, 81 already-Latin, 76
not graphics at all, and **31 distinct blocks carrying Japanese** — 5 of them
already handled by the build (title menu, OPTION screen), 25 pending.

The visual pass reads whole sheets, so it misses blocks that are mostly empty
with a couple of 8x12 kanji in a corner: 0x662720 was classified as "no text"
and only turned up when the battle panel's caption was traced from the screen
back through VRAM. Blocks that look blank deserve a second look at full zoom.

The descriptions below are sanitised: the Japanese transcriptions stay out of
the repository. The full table with transcriptions is regenerated locally into
`work/inventory/RESULTS.md` (see *Regenerating* at the bottom).

## Pending — high priority (players see these constantly)

| offset | codec | comp/dec | what it is |
| --- | --- | --- | --- |
| 0x7ED058 | malias | 3694 / 10240 | **[DONE]** Navi UI label sheet (13 labels, fits in place) |
| 0x7F2190 | malias | 4415 / 12160 | **[DONE]** Second big menu/status label sheet (22 labels, dark-on-plate twin of 0x7ED058; fits in place, its raw BG map untouched) |
| 0x6FC0F0 | lz77 | 2277 / 6016 | **[DONE]** Main status/parts tileset (49 labels; its tilemap lives in the next block 0x6FC9D8 and needs no edit) |
| 0x662DB4 | lz77 | 978 / 3072 | **[DONE]** Parts/medal status sheet (属性→Tipo, 性格→Alma; grows 6B, relocates via its one pointer 0x654BD4) |
| 0x648B44 | lz77 | 676 / 1408 | **[DONE]** Part-slot banners (Cabeza/Brazo d.-i./Patas). **Byte-identical to 0x6FD334**, both written |
| 0x6FD66C | lz77 | 620 / 1312 | **[DONE]** Part-compare screen (head banner redrawn; rest was Latin/art) |
| 0x6466BC | lz77 | 823 / 2208 | **[DONE]** Battle action-name labels (26 labels over the dedup'd 69-tile sheet). **Byte-identical to 0x660C64**, both written |
| 0x661008 | lz77 | 921 / 2432 | **[DONE]** Status-effect buttons, first half |
| 0x6613A4 | lz77 | 449 / 992 | **[DONE]** Status-effect buttons, second half |
| 0x6486C4 | lz77 | 462 / 832 | **[DONE]** Medarot status-screen tab bar (27 labels incl. wash passes; fits in place) |
| 0x661958 | lz77 | 626 / 1568 | **[DONE]** Leg/part-type name plates — 二脚→Bípedo etc. (21 labels; grows, relocates) |
| 0x646AC0 | lz77 | 495 / 1152 | **[DONE via glyph banks]** Not an atlas: a KANJI GLYPH BANK (18 cells of 8x16 + a 1024-entry code→cell table at 0x646CB0). The LIVE bank for the parts panel is the UNCOMPRESSED twin at 0x4C7628 (table 0x4C7AC8). `glyph_banks` in gfx.json repaints always-same-word pairs (攻撃→AT/AQ, 症状→SÍ/NT) in both copies; mechanism in navi/gfx.py `patch_glyph_banks`, previewable with `gfxsheet.py bank`. A third table candidate sits at 0x6499D8 |
| 0x661BCC | lz77 | 330 / 736 | **[DONE]** Outlined katakana stat/skill plates (4 labels) |
| 0x662970 | lz77 | 270 / 640 | **[DONE]** Battle-start header banner (ROBOBATALLA) |
| 0x662720 | lz77 | 413 / 960 | **[DONE]** Battle parts-panel row captions: "action" (codes E003 E00B) → "Ac." and "uses" (codes E014 E018) → "Uso". Dedup'd atlas, 30 tiles, one pointer at 0x654BBC, no twin; the game decompresses it into the EWRAM tile pool at 0x02002474 and DMAs tiles into BG0 from 0x0801C880. Both captions are pre-rendered pixels, so they are invisible to string searches AND to the glyph banks — see the spec's notes in gfx.json for the tile runs and the 22px limit. The block's remaining labels (two AP plates and a TYPE plate) are already Latin |

| 0x662BF0 | lz77 | 450 / 960 | **[PENDING-HIGH]** Target-scope stamp atlas for the battle part panel: the red hanko stamps 単 (single target, user-reported) and almost certainly 全 (all targets), dedup'd across 30 tiles — tiles 01/03 carry extra grids that need a VRAM dump from the target-select frame to place. Found by the 2026-08 visual re-sweep |

## Pending — medium

| offset | codec | comp/dec | what it is |
| --- | --- | --- | --- |
| 0x6428CC | malias | 546 / 2688 | **[DONE]** Corrupted-save error message (2 lines, flat white ink — outline:0; fits in place) |
| 0x65FC78 | lz77 | 428 / 1024 | **[DONE]** Link-wait plate (Esperando…) |
| 0x6EA69C + 0x6EA72C | lz77 | 144+266 / 512+512 | **[DONE]** 一閃 slash stamp → "¡UN TAJO!" (two 32x32 OBJs; inverted ink body 8 / outline 15) |
| 0x6F1280 + 0x6F130C | lz77 | 137+306 / 512+512 | **[DONE]** 一定 fixed-damage stamp → "DAÑO FIJO" (trigger unreproduced in-game; reading is structural) |
| 0x78BDA8 | malias | 18917 / 38400 | **[BLOCKED: 8bpp]** Opening newspaper page. Full format recovered (8bpp 1-D, 30x20 tiles, 64B/tile; uncompressed 128-entry palette at 0x78BCA8; vertical headline 謎の宇宙メダロット発掘 "Desentierran un misterioso Medabot espacial") — needs an 8bpp path in the sheets pipeline; notes in work/sheets/wf3/_probe-newspaper-8bpp.json |
| 0x642414 | malias | 160 / 384 | BGM track labels (music notes + digits; mostly fine as is) |

## Pending — low

| offset | codec | comp/dec | what it is |
| --- | --- | --- | --- |
| 0x4E1DEC | malias | 8810 / 12160 | Shopping-street map tiles with kanji baked into shop signs (illegible at size) |
| 0x62D49C | malias | 2567 / 19200 | **[KEEP]** Comic BomBom magazine logo card (real Kodansha branding, third boot screen) — brand identity, left as is |
| 0x7F0254 | malias | 6045 dec | **[DONE]** Medawatch face: three hex buttons, each in two palette states → Bot / Med. / Parte (19 labels, fits in place; one 4px kana tip consciously left over the hexagon slope) |
| 0x62DEC4 | malias | 2041 / 19200 | Opening credits card (real staff names — policy is to leave these) |

## How the work ships

- `navi/gfx.py` now carries BOTH codecs (Malias and VRAM-safe BIOS LZ77) and a
  data-driven "sheets" pipeline: specs in `langs/es/gfx.json` name a block,
  its codec, a viewing stride and label tile-rects; the build redraws,
  recompresses, and relocates + repoints when the block grew. Duplicate pairs
  are one spec with a "blocks" list.
- Sheets whose on-screen order is scrambled by a tilemap keep their tilemap
  untouched: labels are expressed as tile RUNS in the sheet itself (see the
  "notes" of work/sheets/part-slot-banners.json for the worked pattern,
  including how the two arm banners share caption tiles).

## Regenerating

The montage renders and the classification live in `work/inventory/` (never
committed). To rebuild them: the montage generator is in the session notes of
`navi/gfx.py`'s history — render every Malias/LZ77 block as a grayscale tile
sheet, 12 per image, and classify each panel visually. `index.json` maps each
panel back to its codec/offset/sizes.
