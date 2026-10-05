#!/usr/bin/env python3
# Blast radius: reads a photo (and optional segmentation model) you point it at,
# writes portrait.json in this repo root. Nothing else. Needs Pillow + numpy, and
# onnxruntime only if you pass --model. This script installs nothing.
"""Turn a selfie into the colour-shaded ASCII portrait used by generate.py.

usage: python tools/photo2portrait.py me.jpg --box 100,400,1350,1700 [--model u2net_human_seg.onnx]
--box is the crop (left,top,right,bottom) in pixels; aim for roughly square, face + collar.
--model removes the background (rembg's u2net_human_seg.onnx); without it the whole crop is used.
"""
import argparse, json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAMP = ".,:;i1tfLCG08@"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("photo"); ap.add_argument("--box", required=True)
    ap.add_argument("--model"); ap.add_argument("--cols", type=int, default=70)
    ap.add_argument("--rows", type=int, default=46); ap.add_argument("--local", type=float, default=1.2)
    a = ap.parse_args()
    try:
        import numpy as np
        from PIL import Image, ImageOps, ImageFilter
    except ImportError:
        sys.exit("needs Pillow and numpy")
    if not Path(a.photo).is_file():
        sys.exit(f"no such photo: {a.photo}")
    src = ImageOps.exif_transpose(Image.open(a.photo)).convert("RGB")
    if a.model:
        import onnxruntime as ort
        s = ort.InferenceSession(a.model, providers=["CPUExecutionProvider"])
        x = np.asarray(src.resize((320, 320)), dtype=np.float32) / 255.
        x = ((x - [0.485, 0.456, 0.406]) / [0.229, 0.224, 0.225]).transpose(2, 0, 1)[None].astype(np.float32)
        m = s.run(None, {s.get_inputs()[0].name: x})[0][0, 0]
        m = (m - m.min()) / (m.max() - m.min())
        mask = Image.fromarray((m * 255).astype("uint8")).resize(src.size, Image.BILINEAR)
    else:
        mask = Image.new("L", src.size, 255)
    box = tuple(int(v) for v in a.box.split(","))
    im, mask = src.convert("L").crop(box), mask.crop(box)
    g = np.asarray(im, float)
    bl = np.asarray(im.filter(ImageFilter.GaussianBlur(50)), float)
    im = Image.fromarray(np.clip(g + a.local * (g - bl), 0, 255).astype("uint8")).filter(ImageFilter.UnsharpMask(3, 100, 2))
    im, mask = im.resize((a.cols, a.rows), Image.LANCZOS), mask.resize((a.cols, a.rows), Image.BILINEAR)
    g, m = np.asarray(im, float), np.asarray(mask, float) / 255
    inside = g[m > .5]
    lo, hi = np.percentile(inside, 2), np.percentile(inside, 99.5)
    n = np.clip((g - lo) / (hi - lo), 0, 1)
    chars, levels = [], []
    for y in range(a.rows):
        cr, lr = "", []
        for x in range(a.cols):
            if m[y, x] < .5:
                cr += " "; lr.append(0)
            else:
                cr += RAMP[min(len(RAMP) - 1, int(n[y, x] * len(RAMP)))]; lr.append(1 + min(7, int(n[y, x] * 8)))
        chars.append(cr); levels.append(lr)
    (ROOT / "portrait.json").write_text(json.dumps({"chars": chars, "levels": levels}) + "\n")
    print(f"wrote portrait.json ({a.cols}x{a.rows})")


if __name__ == "__main__":
    main()
