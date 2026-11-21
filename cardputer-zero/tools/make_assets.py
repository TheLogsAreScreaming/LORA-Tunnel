#!/usr/bin/env python3
"""Regenerate the app's image assets from the LORA Tunnel brand artwork.

Sources (repository root): assets/lora-tunnel-radio-logo.png and
assets/vts-official-logo.png. Outputs go to lora_tunnel_zero/assets and
packaging/icon.png. Run from cardputer-zero/: python3 tools/make_assets.py
"""

from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parent
OUT = HERE / "lora_tunnel_zero" / "assets"
BG = (4, 7, 10)


def keyed(image, threshold=40):
    """Make the logo's near-black ground transparent with a soft edge."""
    rgba = image.convert("RGBA")
    pixels = rgba.load()
    for y in range(rgba.height):
        for x in range(rgba.width):
            r, g, b, _ = pixels[x, y]
            level = max(r, g, b)
            if level < threshold:
                alpha = 0 if level < threshold // 2 else int(255 * (level - threshold // 2) / (threshold // 2))
                pixels[x, y] = (r, g, b, alpha)
    return rgba


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    logo = Image.open(REPO / "assets" / "lora-tunnel-radio-logo.png").convert("RGB")

    # Full logo (radio + wordmark), transparent, for the splash screen.
    full = keyed(logo.crop((170, 80, 1086, 1170)))
    full.thumbnail((400, 400), Image.Resampling.LANCZOS)
    full.save(OUT / "logo.png")

    # Radio glyph alone for the status bar and tiles.
    mark = keyed(logo.crop((440, 90, 812, 802)))
    mark.thumbnail((96, 96), Image.Resampling.LANCZOS)
    mark.save(OUT / "radio-mark.png")

    # Store / launcher icon: the full logo on its own dark square.
    icon = logo.resize((256, 256), Image.Resampling.LANCZOS)
    (HERE / "packaging").mkdir(exist_ok=True)
    icon.save(HERE / "packaging" / "icon.png")

    # Valleytech mark recoloured light for the dark About screen.
    vts = Image.open(REPO / "assets" / "vts-official-logo.png").convert("RGBA")
    pixels = vts.load()
    for y in range(vts.height):
        for x in range(vts.width):
            r, g, b, a = pixels[x, y]
            if a:
                shade = 235 if max(r, g, b) < 60 else 140
                pixels[x, y] = (shade, shade, shade, a)
    vts.thumbnail((120, 120), Image.Resampling.LANCZOS)
    vts.save(OUT / "vts.png")
    print("assets written to", OUT)


if __name__ == "__main__":
    main()
