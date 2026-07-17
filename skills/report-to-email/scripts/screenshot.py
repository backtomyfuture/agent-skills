#!/usr/bin/env python3
"""
Render an HTML email preview to a PNG for visual QA, auto-cropped to the actual
content height (emails are tall and narrow, so a fixed window wastes space and
clips content). Drives headless Chrome — no Selenium needed.

Why screenshot at all: the renderer's first output is rarely perfect. Looking at
the rendered image (ideally with fresh eyes) catches overlaps, clipped text,
broken tables, and a missing logo before you generate the final .eml.

Usage:
    python3 screenshot.py /tmp/notion-email-output.html /tmp/preview.png

Then Read the PNG and inspect it. If the page is taller than one screen, this
prints the content height so you can crop regions with PIL for a closer look.
"""

import subprocess
import sys

CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
]


def find_chrome():
    import os
    for c in CHROME_CANDIDATES:
        if os.path.exists(c):
            return c
    sys.exit("Chrome/Chromium not found — install it or screenshot manually.")


def main():
    if len(sys.argv) != 3:
        sys.exit("usage: screenshot.py <input.html> <output.png>")
    html, png = sys.argv[1], sys.argv[2]
    chrome = find_chrome()
    # Card-heavy monthly reports reach ~5200px; keep headroom and crop after.
    subprocess.run([
        chrome, "--headless", "--disable-gpu", "--hide-scrollbars",
        "--force-device-scale-factor=1", "--window-size=820,7000",
        "--default-background-color=FFFFFFFF", "--virtual-time-budget=3000",
        f"--screenshot={png}", f"file://{html}",
    ], check=True, stderr=subprocess.DEVNULL)

    try:
        from PIL import Image
    except ImportError:
        print(f"saved {png} (install Pillow to auto-crop to content height)")
        return

    im = Image.open(png).convert("RGB")
    W, H = im.size
    px = im.load()
    last = 0
    for y in range(H - 1, -1, -1):
        if any(not (px[x, y][0] > 250 and px[x, y][1] > 250 and px[x, y][2] > 250)
               for x in range(0, W, 12)):
            last = y
            break
    im.crop((0, 0, W, min(H, last + 24))).save(png)
    print(f"saved {png} — content height ~{last}px (width {W})")


if __name__ == '__main__':
    main()
