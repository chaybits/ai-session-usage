#!/usr/bin/env python3
"""Draw the program's mark at every size the packages need, so they are reproducible and carry nothing of this machine.

The mark is three usage bars in dark tracks, filled 33 / 66 / 100 per cent in white, orange and red: the same
language the widget itself speaks, where a bar approaching its limit warms from the theme colour through amber
into red. Colours and bar geometry are taken from the chosen reference render (chosen 2026-10-16); the large
surfaces use that render directly, while every size drawn here is vector-clean so it survives 24 px.

Writes, under widgets-board/AiSessionUsage/: the app's logos in Assets/ (the sizes the package manifest and the
Start menu read: Square150x150Logo, Square44x44Logo with its unplated 24 px form, StoreLogo 50 px,
Wide310x150Logo and SplashScreen 620x300, each also at scale-200), and in ProviderAssets/ the icon the Widgets
Board shows in the widget's attribution area and the picker (ProviderIcon, WidgetIcon). It also writes the KDE
applet icon, src/contents/icons/aisessionusage.svg, which src/metadata.json names.

Usage: python3 -B scripts/draw_icons.py [--out DIR] [--svg PATH]
Prints one summary line; the size of every picture is in logs/draw_icons.log.
"""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "widgets-board" / "AiSessionUsage"
DEFAULT_SVG = ROOT / "src" / "contents" / "icons" / "aisessionusage.svg"

SS = 4  # supersampling: draw large, shrink down, get clean curves without a vector library

# Sampled from the reference render. The three fills are the mark; everything else serves them.
WHITE = (222, 222, 221)
ORANGE = (226, 135, 36)
RED = (209, 55, 39)
# LOAD-BEARING: the plate and track are lifted well above the reference render's near-black. In the render
# both sit within three values of the background, which looks rich at 1024 px and leaves no silhouette at all
# at 24 px, where the icon has to read against a dark panel. Do not darken these to "match the render".
PLATE = (32, 31, 30)
PLATE_RIM = (62, 60, 58)
TRACK = (61, 59, 57)
TEXT = (235, 235, 235)

FILLS = (0.33, 0.66, 1.00)
PAD = 0.125        # side margin, as a fraction of the icon
BAR_H = 0.105      # bar height
GAP = 0.085        # space between bars
RADIUS = 0.225     # plate corner radius


def font(size: int):
    """A sans-serif font of the machine (fontconfig's choice), or Pillow's default when none can be found."""
    from PIL import ImageFont
    try:
        path = subprocess.run(["fc-match", "-f", "%{file}", "sans-serif"], capture_output=True, text=True,
                              check=True).stdout.strip()
        return ImageFont.truetype(path, size)
    except (OSError, subprocess.CalledProcessError):
        return ImageFont.load_default()


def icon(size: int, plated: bool = True, rim: bool = True) -> Image.Image:
    """The mark at one size: three bars in dark tracks, filled 33 / 66 / 100 per cent."""
    s = size * SS
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if plated:
        r = int(s * RADIUS)
        if rim:
            d.rounded_rectangle((0, 0, s - 1, s - 1), radius=r, fill=PLATE_RIM + (255,))
            inset = max(1, round(s * 0.012))
            d.rounded_rectangle((inset, inset, s - 1 - inset, s - 1 - inset),
                                radius=max(1, r - inset), fill=PLATE + (255,))
        else:
            d.rounded_rectangle((0, 0, s - 1, s - 1), radius=r, fill=PLATE + (255,))

    pad = s * PAD
    width = s - 2 * pad
    bar_h = s * BAR_H
    gap = s * GAP
    top = (s - (3 * bar_h + 2 * gap)) / 2
    glow = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)

    for i, (frac, colour) in enumerate(zip(FILLS, (WHITE, ORANGE, RED))):
        y = top + i * (bar_h + gap)
        rad = bar_h / 2
        # the empty track: what makes a filled bar read as "this much of a limit is used"
        d.rounded_rectangle((pad, y, pad + width, y + bar_h), radius=rad,
                            fill=(TRACK if plated else (150, 147, 143)) + (255 if plated else 120,))
        fw = max(width * frac, bar_h)
        d.rounded_rectangle((pad, y, pad + fw, y + bar_h), radius=rad, fill=colour + (255,))
        gd.rounded_rectangle((pad, y, pad + fw, y + bar_h), radius=rad, fill=colour + (120,))

    glow = glow.filter(ImageFilter.GaussianBlur(s * 0.018))
    out = Image.alpha_composite(glow, img) if plated else img
    return out.resize((size, size), Image.LANCZOS)


def wide(width: int, height: int) -> Image.Image:
    """The wide tile and the splash screen: the mark beside the name on the plate colour."""
    img = Image.new("RGBA", (width, height), PLATE + (255,))
    mark = icon(height * 56 // 100, rim=False)
    x = width * 10 // 100
    img.paste(mark, (x, (height - mark.height) // 2), mark)
    d = ImageDraw.Draw(img)
    d.text((x + mark.width + width * 5 // 100, height // 2), "AI Session Usage",
           font=font(height * 12 // 100), fill=TEXT, anchor="lm")
    return img


def poster(width: int, height: int, with_name: bool = True) -> Image.Image:
    """A Store listing logo: the mark on the plate colour with the name under it.

    Partner Center's logo slots take fixed sizes and refuse anything else, and where a slot lists two sizes they
    are alternatives rather than a pair. Each slot gets one file from this function or from icon().
    """
    # LOAD-BEARING: the backdrop is darker than PLATE. Drawing the plated mark on the plate colour makes the
    # plate invisible and the bars appear to float, which is not the icon.
    img = Image.new("RGBA", (width, height), (21, 20, 19, 255))
    portrait = height > width
    mark_px = round(min(width, height) * (0.46 if portrait else 0.42))
    mark = icon(mark_px, rim=True)
    cx = (width - mark_px) // 2
    name_px = round(min(width, height) * (0.072 if portrait else 0.065))
    block = mark_px + (round(height * 0.055) + round(name_px * 2.4) if with_name else 0)
    cy = round(height * 0.26) if portrait else max(round(height * 0.08), (height - block) // 2)
    if not with_name:
        cy = (height - mark_px) // 2
    img.paste(mark, (cx, cy), mark)
    d = ImageDraw.Draw(img)
    name_size = name_px
    if not with_name:
        # LOAD-BEARING: Super hero art must not include the product's title (Partner Center's own rule).
        return img
    y = cy + mark_px + round(height * 0.055)
    d.text((width // 2, y), "AI Session Usage", font=font(name_size), fill=TEXT, anchor="ma")
    d.text((width // 2, y + round(name_size * 1.55)), "Claude Code and ChatGPT limits",
           font=font(round(name_size * 0.52)), fill=(165, 163, 160), anchor="ma")
    return img


def svg() -> str:
    """The KDE applet icon. Hand-written so it stays a few hundred bytes and scales to any panel height."""
    V = 64
    pad, bh, gap = V * PAD, V * BAR_H, V * GAP
    width = V - 2 * pad
    top = (V - (3 * bh + 2 * gap)) / 2
    rows = []
    for i, (frac, col) in enumerate(zip(FILLS, (WHITE, ORANGE, RED))):
        y = top + i * (bh + gap)
        hexc = "#%02x%02x%02x" % col
        rows.append(f'  <rect x="{pad:.2f}" y="{y:.2f}" width="{width:.2f}" height="{bh:.2f}" '
                    f'rx="{bh/2:.2f}" fill="#3d3b39"/>')
        rows.append(f'  <rect x="{pad:.2f}" y="{y:.2f}" width="{max(width*frac, bh):.2f}" height="{bh:.2f}" '
                    f'rx="{bh/2:.2f}" fill="{hexc}"/>')
    body = "\n".join(rows)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {V} {V}" width="{V}" height="{V}">\n'
            f'  <rect x="0" y="0" width="{V}" height="{V}" rx="{V*RADIUS:.2f}" fill="#201f1e"/>\n'
            f'{body}\n</svg>\n')


def main() -> None:
    """Draw every logo, icon and the KDE SVG, then print one summary line."""
    parser = argparse.ArgumentParser(description="Draw the program's mark at every packaged size.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT,
                        help="the Widgets Board project folder (Assets/ and ProviderAssets/ go under it)")
    parser.add_argument("--svg", type=Path, default=DEFAULT_SVG, help="where to write the KDE applet icon")
    parser.add_argument("--store", type=Path, default=ROOT / "Upload" / "microsoft-store" / "logos",
                        help="where to write the Partner Center listing logos")
    args = parser.parse_args()
    assets = args.out / "Assets"
    provider = args.out / "ProviderAssets"
    assets.mkdir(parents=True, exist_ok=True)
    provider.mkdir(parents=True, exist_ok=True)
    files: dict[Path, Image.Image] = {
        assets / "Square150x150Logo.png": icon(150),
        assets / "Square150x150Logo.scale-200.png": icon(300),
        assets / "Square44x44Logo.png": icon(44),
        assets / "Square44x44Logo.scale-200.png": icon(88),
        assets / "Square44x44Logo.targetsize-24_altform-unplated.png": icon(24, plated=False),
        assets / "StoreLogo.png": icon(50),
        assets / "StoreLogo.scale-200.png": icon(100),
        assets / "Wide310x150Logo.png": wide(310, 150),
        assets / "Wide310x150Logo.scale-200.png": wide(620, 300),
        assets / "SplashScreen.png": wide(620, 300),
        assets / "SplashScreen.scale-200.png": wide(1240, 600),
        provider / "ProviderIcon.png": icon(128),
        provider / "WidgetIcon.png": icon(128),
    }
    log = ROOT / "logs" / "draw_icons.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with log.open("w", encoding="utf-8") as out:
        for path, image in files.items():
            image.save(path, format="PNG", optimize=True)
            size = path.stat().st_size
            total += size
            out.write(f"{path}: {image.width}x{image.height}, {size} bytes\n")
        args.svg.parent.mkdir(parents=True, exist_ok=True)
        args.svg.write_text(svg(), encoding="utf-8")
        out.write(f"{args.svg}: {args.svg.stat().st_size} bytes\n")
        args.store.mkdir(parents=True, exist_ok=True)
        # One file per Partner Center slot, at a size that slot accepts. It refuses anything else.
        store = {
            # "Store logos"
            "poster-9x16-720x1080.png": poster(720, 1080),
            "poster-9x16-1440x2160.png": poster(1440, 2160),
            "boxart-1x1-1080.png": poster(1080, 1080),
            "boxart-1x1-2160.png": poster(2160, 2160),
            # "Store display images", shown to Windows 10/11 customers
            "apptile-1x1-300.png": icon(300),
            "tile-1x1-150.png": icon(150),
            "tile-1x1-71.png": icon(71),
            # "Windows and Xbox image": no title allowed
            "superhero-16x9-1920x1080.png": poster(1920, 1080, with_name=False),
            "superhero-16x9-3840x2160.png": poster(3840, 2160, with_name=False),
        }
        for name, image in store.items():
            path = args.store / name
            image.convert("RGB").save(path, format="PNG", optimize=True)
            total += path.stat().st_size
            out.write(f"{path}: {image.width}x{image.height}, {path.stat().st_size} bytes\n")
    print(f"drew {len(files) + len(store)} pictures ({total} bytes), {args.svg.name} and the "
          f"{len(store)} Store logos under {args.store}; details: {log}")


if __name__ == "__main__":
    main()
