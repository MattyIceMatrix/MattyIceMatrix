#!/usr/bin/env python3
# Blast radius: reads one image you point it at, writes ascii.txt in this repo
# root (overwrites it). Nothing else. Needs Pillow (pip install pillow) — name
# only, this script installs nothing.
"""Turn a photo or logo into the ASCII portrait used by generate.py.

usage: python tools/img2ascii.py path/to/photo.jpg [--cols 42] [--invert]
"""
import argparse, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAMP = " .'`^,:;!i|lj1r*[{}H%k@#Mg"   # dark -> bright

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--cols", type=int, default=42)
    ap.add_argument("--invert", action="store_true", help="for photos on a light background")
    a = ap.parse_args()
    try:
        from PIL import Image, ImageOps
    except ImportError:
        sys.exit("Pillow is required: pip install pillow")
    src = Path(a.image)
    if not src.is_file():
        sys.exit(f"no such image: {src}")
    im = ImageOps.autocontrast(Image.open(src).convert("L"))
    if a.invert:
        im = ImageOps.invert(im)
    rows = int(im.height / im.width * a.cols * 0.5)   # glyphs are ~2x tall as wide
    im = im.resize((a.cols, rows))
    px = im.load()
    out = []
    for y in range(rows):
        out.append("".join(RAMP[px[x, y] * (len(RAMP) - 1) // 255] for x in range(a.cols)).rstrip())
    (ROOT / "ascii.txt").write_text("\n".join(out) + "\n")
    print(f"wrote ascii.txt ({a.cols}x{rows})")

if __name__ == "__main__":
    main()
