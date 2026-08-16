#!/usr/bin/env python3
"""Look at, and try patches on, one compressed graphics sheet.

For whoever is writing the "sheets" section of a language pack's gfx.json:
render a block to see what it holds, then apply a candidate spec and render
the result, without touching the build or the real ROM.

  python3 tools/gfxsheet.py render 0x662970 lz77 out.png [tiles_wide]
  python3 tools/gfxsheet.py grid   0x662970 lz77 out.png [tiles_wide]
      # same, plus tile coordinates burned into the margins every tile
  python3 tools/gfxsheet.py apply  spec.json out.png
      # spec.json = one entry of the "sheets" list; renders the patched sheet
  python3 tools/gfxsheet.py bank   spec.json out.png
      # spec.json = one entry of the "glyph_banks" list; renders every cell of
      # the bank (before and after), so a word's plate can be read by eye

Colors are a grayscale guess of the 4bpp values; the real palette depends on
the screen that draws the sheet.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from vramtool import write_png  # noqa: E402
from navi import gfx  # noqa: E402
from navi.rom import Rom  # noqa: E402
from navi.table import load_latin  # noqa: E402
from navi.config import Config  # noqa: E402


def load_rom() -> Rom:
    return Rom.load(Config.load().resolve_rom())


def render_tiles(tiles: bytes, cols: int, path: str, ruler: bool = False) -> None:
    count = len(tiles) // gfx.TILE_BYTES
    rows = (count + cols - 1) // cols
    pad = 12 if ruler else 0
    width = cols * 8 + pad
    height = rows * 8 + pad
    px = [[(20, 20, 60)] * width for _ in range(height)]
    for t in range(count):
        gx = (t % cols) * 8 + pad
        gy = (t // cols) * 8 + pad
        for y in range(8):
            b4 = tiles[t * 32 + y * 4: t * 32 + y * 4 + 4]
            for xi in range(4):
                v = b4[xi]
                for k, nib in ((0, v & 0xF), (1, v >> 4)):
                    g = int(nib * 255 / 15)
                    px[gy + y][gx + xi * 2 + k] = (g, g, g)
    if ruler:
        for c in range(cols):
            for y in range(pad - 2, pad):
                px[y][pad + c * 8] = (255, 80, 80)
        for r in range(rows):
            for x in range(pad - 2, pad):
                px[pad + r * 8][x] = (255, 80, 80)
    write_png(path, px)
    print(f"{count} tiles ({cols} wide) -> {path}")


def main() -> None:
    mode = sys.argv[1]
    rom = load_rom()
    if mode in ("render", "grid"):
        block = int(sys.argv[2], 16)
        codec = sys.argv[3]
        out = sys.argv[4]
        cols = int(sys.argv[5]) if len(sys.argv) > 5 else 16
        dec, _ = gfx.CODECS[codec][0](bytes(rom.data), block)
        render_tiles(dec, cols, out, ruler=(mode == "grid"))
    elif mode == "apply":
        spec = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
        out = sys.argv[3]
        charset = load_latin()

        from navi import font as font_mod
        font_data, _ = font_mod.build_font(rom, charset)
        block = int(str(spec["blocks"][0] if "blocks" in spec else spec["block"]), 16)
        codec = spec.get("codec", "malias")
        raw, comp_len = gfx.CODECS[codec][0](bytes(rom.data), block)
        tiles = bytearray(raw)
        setter = gfx.Typesetter(rom, charset, font_data)
        report = gfx.GfxReport()
        gfx.apply_sheet_labels(tiles, spec, setter, report)
        packed = gfx.CODECS[codec][1](bytes(tiles))
        print(f"drawn={report.drawn} skipped={report.skipped} "
              f"recompressed={len(packed)}B (original {comp_len}B; bigger is fine, it relocates)")
        render_tiles(bytes(tiles), int(spec.get("tiles_wide", 16)), out)
    elif mode == "bank":
        spec = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
        out = sys.argv[3]
        charset = load_latin()

        from navi import font as font_mod
        font_data, _ = font_mod.build_font(rom, charset)
        codec = spec.get("codec", "lz77")
        tiles, lut = gfx.load_bank(bytes(rom.data), spec)
        was = len(tiles)
        setter = gfx.Typesetter(rom, charset, font_data)
        report = gfx.GfxReport()
        moved = gfx.apply_bank_words(tiles, lut, spec, setter, report)
        print(f"drawn={report.drawn} skipped={report.skipped} table rewritten={moved}")
        if codec == "raw":
            print(f"raw bank {was}B -> {len(tiles)}B, written in place")
        else:
            dec, enc = gfx.CODECS[codec]
            tiles_len = dec(bytes(rom.data), int(str(spec["tiles"]), 16))[1]
            lut_len = dec(bytes(rom.data), int(str(spec["lut"]), 16))[1]
            print(f"bank {was}B -> {len(tiles)}B, recompressed "
                  f"{len(enc(bytes(tiles)))}B (original {tiles_len}B); table "
                  f"{len(enc(gfx.bank_lut_bytes(lut)))}B (original {lut_len}B)")
        # Every cell the table names, in code order, before and after.
        cells = []
        for index in range(len(lut) - gfx.BANK_LUT_WIDTH):
            top, bottom = lut[index], lut[index + gfx.BANK_LUT_WIDTH]
            if top == lut[2] or bottom == lut[2]:
                continue
            cells.append((index + gfx.BANK_FIRST_CODE, top, bottom))
        strip = bytearray()
        for _, top, bottom in cells:
            strip += tiles[top * 32:(top + 1) * 32]
        for _, top, bottom in cells:
            strip += tiles[bottom * 32:(bottom + 1) * 32]
        print("cells:", " ".join(f"{code:04X}" for code, _, _ in cells))
        render_tiles(bytes(strip), len(cells), out)
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
