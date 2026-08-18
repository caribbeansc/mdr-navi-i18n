#!/usr/bin/env python3
"""Upscale GBA screenshots so the Read tool can resolve the 8x8 font.

Nearest-neighbour, default 4x, writes alongside as <name>.z.png (or to a
given output path). Optional crop box in source pixels: --crop x,y,w,h.
"""
import sys
from PIL import Image

args = [a for a in sys.argv[1:]]
scale = 4
crop = None
out = None
paths = []
i = 0
while i < len(args):
    a = args[i]
    if a == "--scale":
        i += 1
        scale = int(args[i])
    elif a == "--crop":
        i += 1
        crop = tuple(int(v) for v in args[i].split(","))
    elif a == "--out":
        i += 1
        out = args[i]
    else:
        paths.append(a)
    i += 1

for p in paths:
    im = Image.open(p).convert("RGB")
    if crop:
        x, y, w, h = crop
        im = im.crop((x, y, x + w, y + h))
    im = im.resize((im.width * scale, im.height * scale), Image.NEAREST)
    dest = out if out else p.rsplit(".", 1)[0] + ".z.png"
    im.save(dest)
    print(dest, im.size)
