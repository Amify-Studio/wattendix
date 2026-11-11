"""Capture the card screenshots of the README from dev/demo (invented data).

    python dev/screenshots.py            every card image, French and English
    python dev/screenshots.py tiles      only the images whose name contains "tiles"

Needs Chrome or Edge, and the network for the icons and the font.
"""

from __future__ import annotations

import functools
import http.server
import json
import pathlib
import subprocess
import sys
import threading
import urllib.parse

from PIL import Image, ImageChops

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "images"
BROWSERS = (
    "C:/Program Files/Google/Chrome/Application/chrome.exe",
    "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
)
SCALE = 2
ALL = ["day", "week", "month", "year"]

# name: (card width, theme, home, card configuration)
SHOTS = {
    "card-tiles": (760, "light", "full", {"periods": ALL}),
    "card-charts": (620, "light", "full", {"periods": ALL, "charts": True, "hide_heating": True}),
    "card-table": (620, "light", "full", {"periods": ["hour", *ALL], "layout": "table"}),
    "card-mini": (360, "light", "full", {"periods": ALL, "layout": "mini", "descending": True}),
    "card-phone": (360, "dark", "full", {"periods": ["day", "month"], "charts": True, "hide_heating": True}),
    "card-energy": (520, "light", "kwh", {"periods": ALL}),
    "card-delayed": (520, "light", "delayed", {"periods": ALL}),
}


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args: object) -> None:
        pass


def browser() -> str:
    for path in BROWSERS:
        if pathlib.Path(path).exists():
            return path
    raise SystemExit("Chrome or Edge not found")


def crop(path: pathlib.Path) -> None:
    """Keep the card and an even margin of page around it."""
    image = Image.open(path).convert("RGB")
    background = Image.new("RGB", image.size, image.getpixel((2, 2)))
    box = ImageChops.difference(image, background).getbbox()
    margin = 12 * SCALE
    image.crop((
        max(box[0] - margin, 0), max(box[1] - margin, 0),
        min(box[2] + margin, image.width), min(box[3] + margin, image.height),
    )).save(path, optimize=True)


def main() -> None:
    wanted = sys.argv[1] if len(sys.argv) > 1 else ""
    handler = functools.partial(Quiet, directory=str(ROOT))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    OUT.mkdir(parents=True, exist_ok=True)
    exe = browser()
    for name, (width, theme, home, config) in SHOTS.items():
        if wanted not in name:
            continue
        for lang in ("fr", "en"):
            query = urllib.parse.urlencode({
                "lang": lang, "theme": theme, "home": home, "width": width, "config": json.dumps(config),
            })
            target = OUT / f"{name}.{lang}.png"
            subprocess.run([
                exe, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                f"--force-device-scale-factor={SCALE}", f"--window-size={width + 32},1700",
                "--virtual-time-budget=8000", f"--screenshot={target}",
                f"http://127.0.0.1:{server.server_port}/dev/demo/index.html?{query}",
            ], check=True, capture_output=True, timeout=90)
            crop(target)
            print(target.relative_to(ROOT), Image.open(target).size)
    server.shutdown()


if __name__ == "__main__":
    main()
