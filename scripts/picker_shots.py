#!/usr/bin/env python3
"""Make the Widgets Board picker's previews from screenshots of the real widget.

Microsoft's picker page asks for the medium widget, 300 x 304 pixels with transparent rounded corners, and takes one
picture per theme. This crops the widget's card out of a light and a dark screenshot of the Board (taken at a scale where
the medium card is larger than 300 px, so the result is a reduction, not an enlargement), scales it to 300 x 304 with
Lanczos, and makes the corners transparent. The screenshots come from the Windows 11 VM with the fake CLIs' values.

Usage: picker_shots.py LIGHT.png DARK.png --box X0,Y0,X1,Y1 [--radius PX] [--out DIR]
  --box     the card in the screenshots (the same place in both), in screenshot pixels
  --radius  the corner radius of the result (default 15, the card's 24 px at 150 % scaled down)
  --out     default widgets-board/AiSessionUsage/ProviderAssets: WidgetScreenshot.png (light) and WidgetScreenshotDark.png
Prints one summary line.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
SIZE = (300, 304)  # the picker's size (Microsoft Learn, "Integrate with the widget picker")


def preview(capture: Path, box: tuple[int, int, int, int], radius: int) -> Image.Image:
    """The card cut from a screenshot, scaled to the picker's size, its corners transparent."""
    with Image.open(capture) as im:
        card = im.convert("RGB").crop(box)
    if card.width < SIZE[0] or card.height < SIZE[1]:
        raise ValueError(f"{capture}: the card is {card.size}, smaller than {SIZE}; take the screenshot at a higher scale")
    card = card.resize(SIZE, Image.Resampling.LANCZOS).convert("RGBA")
    mask = Image.new("L", SIZE, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, SIZE[0] - 1, SIZE[1] - 1), radius=radius, fill=255)
    card.putalpha(mask)
    return card


def main() -> None:
    """Make the two picker previews from the two screenshots and print one summary line."""
    parser = argparse.ArgumentParser(description="Make the picker previews from screenshots of the widget.")
    parser.add_argument("light", type=Path)
    parser.add_argument("dark", type=Path)
    parser.add_argument("--box", required=True, help="X0,Y0,X1,Y1 of the card in the screenshots")
    parser.add_argument("--radius", type=int, default=15)
    parser.add_argument("--out", type=Path, default=ROOT / "widgets-board" / "AiSessionUsage" / "ProviderAssets")
    args = parser.parse_args()
    box = tuple(int(v) for v in args.box.split(","))
    if len(box) != 4:
        parser.error(f"--box needs four numbers, got {args.box!r}")
    args.out.mkdir(parents=True, exist_ok=True)
    written = []
    for capture, name in ((args.light, "WidgetScreenshot.png"), (args.dark, "WidgetScreenshotDark.png")):
        path = args.out / name
        preview(capture, box, args.radius).save(path, format="PNG", optimize=True)
        written.append(f"{name} {path.stat().st_size} bytes")
    print(f"picker previews {SIZE[0]}x{SIZE[1]}: " + ", ".join(written))


if __name__ == "__main__":
    main()
