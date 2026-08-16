#!/usr/bin/env python3
"""Pick apart a gbashot --dumpvram capture.

The dump is LCD registers + palette RAM + VRAM + OAM, back to back. This
renders each background layer and the sprite layer as its own PNG, and can
report which tiles a given screen rectangle uses — the starting point for
tracing on-screen text back to the compressed block it came from in the ROM.
"""

from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

REGS = 0x60
PALETTE = 0x400
VRAM = 0x18000
OAM = 0x400


class Dump:
    def __init__(self, path: str | Path):
        blob = Path(path).read_bytes()
        expected = REGS + PALETTE + VRAM + OAM
        if len(blob) != expected:
            raise SystemExit(f"{path}: {len(blob)} bytes, expected {expected}")
        self.regs = blob[:REGS]
        self.palette = blob[REGS:REGS + PALETTE]
        self.vram = blob[REGS + PALETTE:REGS + PALETTE + VRAM]
        self.oam = blob[REGS + PALETTE + VRAM:]

    def reg16(self, offset: int) -> int:
        return struct.unpack_from("<H", self.regs, offset)[0]

    @property
    def dispcnt(self) -> int:
        return self.reg16(0x00)

    def bg_control(self, index: int) -> int:
        return self.reg16(0x08 + 2 * index)

    def bg_enabled(self, index: int) -> bool:
        return bool(self.dispcnt & (1 << (8 + index)))

    def color(self, bank: int, index: int, obj: bool = False) -> tuple[int, int, int]:
        base = 0x200 if obj else 0
        value = struct.unpack_from("<H", self.palette, base + (bank * 16 + index) * 2)[0]
        return ((value & 31) << 3, ((value >> 5) & 31) << 3, ((value >> 10) & 31) << 3)


def tile_4bpp(data: bytes, offset: int) -> list[list[int]]:
    rows = []
    for y in range(8):
        row = []
        for x in range(4):
            byte = data[offset + y * 4 + x]
            row += [byte & 0xF, byte >> 4]
        rows.append(row)
    return rows


def tile_8bpp(data: bytes, offset: int) -> list[list[int]]:
    return [list(data[offset + y * 8:offset + y * 8 + 8]) for y in range(8)]


def write_png(path: str, pixels: list[list[tuple[int, int, int]]]) -> None:
    height = len(pixels)
    width = len(pixels[0])
    raw = b""
    for row in pixels:
        raw += b"\x00" + b"".join(bytes(c) for c in row)

    def chunk(tag: bytes, body: bytes) -> bytes:
        piece = struct.pack(">I", len(body)) + tag + body
        return piece + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)

    blob = b"\x89PNG\r\n\x1a\n"
    blob += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    blob += chunk(b"IDAT", zlib.compress(raw, 9))
    blob += chunk(b"IEND", b"")
    Path(path).write_bytes(blob)


def render_bg(dump: Dump, index: int, path: str) -> dict:
    control = dump.bg_control(index)
    char_base = ((control >> 2) & 3) * 0x4000
    screen_base = ((control >> 8) & 31) * 0x800
    eight_bpp = bool(control & 0x80)
    size = (control >> 14) & 3
    width_tiles = 32 * (2 if size in (1, 3) else 1)
    height_tiles = 32 * (2 if size in (2, 3) else 1)

    pixels = [[(255, 0, 255)] * (width_tiles * 8) for _ in range(height_tiles * 8)]
    used: dict[int, int] = {}
    for ty in range(height_tiles):
        for tx in range(width_tiles):
            block = (ty // 32) * (width_tiles // 32) + (tx // 32)
            entry_at = screen_base + block * 0x800 + ((ty % 32) * 32 + (tx % 32)) * 2
            entry = struct.unpack_from("<H", dump.vram, entry_at)[0]
            tile = entry & 0x3FF
            hflip = bool(entry & 0x400)
            vflip = bool(entry & 0x800)
            bank = entry >> 12
            used[tile] = used.get(tile, 0) + 1
            if eight_bpp:
                art = tile_8bpp(dump.vram, char_base + tile * 64)
            else:
                art = tile_4bpp(dump.vram, char_base + tile * 32)
            for y in range(8):
                for x in range(8):
                    sx = 7 - x if hflip else x
                    sy = 7 - y if vflip else y
                    value = art[sy][sx]
                    if eight_bpp:
                        pixels[ty * 8 + y][tx * 8 + x] = dump.color(value >> 4, value & 0xF)
                    else:
                        pixels[ty * 8 + y][tx * 8 + x] = dump.color(bank, value)
    write_png(path, pixels)
    return {"char_base": char_base, "screen_base": screen_base,
            "size": (width_tiles, height_tiles), "tiles_used": len(used)}


#: Sprite dimensions by (shape, size), in tiles.
OBJ_SIZES = {
    (0, 0): (1, 1), (0, 1): (2, 2), (0, 2): (4, 4), (0, 3): (8, 8),
    (1, 0): (2, 1), (1, 1): (4, 1), (1, 2): (4, 2), (1, 3): (8, 4),
    (2, 0): (1, 2), (2, 1): (1, 4), (2, 2): (2, 4), (2, 3): (4, 8),
}

OBJ_CHAR_BASE = 0x10000


def render_obj(dump: Dump, path: str) -> list[dict]:
    """Draw every visible sprite onto one 256x256 sheet, at its position."""
    one_dimensional = bool(dump.dispcnt & 0x40)
    pixels = [[(24, 24, 24)] * 256 for _ in range(256)]
    sprites = []
    for index in range(128):
        a0, a1, a2 = struct.unpack_from("<HHH", dump.oam, index * 8)
        if (a0 >> 8) & 3 == 2:  # disabled (non-affine hidden)
            continue
        shape, size = a0 >> 14, a1 >> 14
        width, height = OBJ_SIZES[(shape, size)]
        x, y = a1 & 0x1FF, a0 & 0xFF
        tile, bank = a2 & 0x3FF, a2 >> 12
        eight_bpp = bool(a0 & 0x2000)
        hflip, vflip = bool(a1 & 0x1000), bool(a1 & 0x2000)
        sprites.append({"index": index, "x": x, "y": y, "w": width, "h": height,
                        "tile": tile, "bank": bank, "8bpp": eight_bpp})
        for ty in range(height):
            for tx in range(width):
                sx_t = width - 1 - tx if hflip else tx
                sy_t = height - 1 - ty if vflip else ty
                if one_dimensional:
                    number = tile + (sy_t * width + sx_t) * (2 if eight_bpp else 1)
                else:
                    number = tile + sy_t * 32 + sx_t * (2 if eight_bpp else 1)
                offset = OBJ_CHAR_BASE + number * 32
                if offset + 32 > VRAM:
                    continue
                art = tile_8bpp(dump.vram, offset) if eight_bpp else tile_4bpp(dump.vram, offset)
                for py in range(8):
                    for px in range(8):
                        sx = 7 - px if hflip else px
                        sy = 7 - py if vflip else py
                        value = art[sy][sx]
                        if value == 0:
                            continue
                        screen_x = (x + tx * 8 + px) & 0x1FF
                        screen_y = (y + ty * 8 + py) & 0xFF
                        if screen_x < 256 and screen_y < 256:
                            if eight_bpp:
                                pixels[screen_y][screen_x] = dump.color(value >> 4, value & 0xF, obj=True)
                            else:
                                pixels[screen_y][screen_x] = dump.color(bank, value, obj=True)
    write_png(path, pixels)
    return sprites


def main() -> None:
    dump = Dump(sys.argv[1])
    stem = sys.argv[2] if len(sys.argv) > 2 else "vram"
    print(f"DISPCNT={dump.dispcnt:04X} mode={dump.dispcnt & 7} "
          f"obj={'on' if dump.dispcnt & 0x1000 else 'off'} "
          f"objmap={'1d' if dump.dispcnt & 0x40 else '2d'}")
    for bg in range(4):
        if not dump.bg_enabled(bg):
            print(f"BG{bg}: off")
            continue
        info = render_bg(dump, bg, f"{stem}-bg{bg}.png")
        print(f"BG{bg}: char@{info['char_base']:05X} map@{info['screen_base']:05X} "
              f"{info['size'][0]}x{info['size'][1]} tiles, {info['tiles_used']} distinct "
              f"-> {stem}-bg{bg}.png")
    if dump.dispcnt & 0x1000:
        sprites = render_obj(dump, f"{stem}-obj.png")
        print(f"OBJ: {len(sprites)} visible -> {stem}-obj.png")
        for s in sprites[:24]:
            print(f"  #{s['index']:3d} at ({s['x']:3d},{s['y']:3d}) "
                  f"{s['w']}x{s['h']}t tile={s['tile']:3d} bank={s['bank']} "
                  f"{'8bpp' if s['8bpp'] else '4bpp'}")


if __name__ == "__main__":
    main()
