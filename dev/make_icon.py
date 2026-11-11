"""Draw the Wattcast brand images (run from the repository root).

Icon: a lightning bolt (the watts) and a dotted line rising to a target (the
forecast), on a solid tile so it reads on light and dark themes alike.
Logo: the icon, the name, and "par Amify-Studio" with the studio's mark.

    python dev/make_icon.py            write custom_components/wattcast/brand/*.png
    python dev/make_icon.py --preview  also write dev/icon_preview.png (not committed)
"""

import pathlib
import sys

from PIL import Image, ImageDraw, ImageFont

S = 2048  # supersampled canvas of the icon
BLUE = (21, 138, 224, 255)
WHITE = (255, 255, 255, 255)
AMBER = (255, 190, 40, 255)

# Amify mark, traced from the studio's logo (viewBox 533 x 533): outline, then three holes.
AMIFY_OUTLINE = [(267, 0), (344.2, 156.5), (405.5, 91), (388.5, 245), (533, 533), (0, 533)]
AMIFY_HOLES = [
    [(267, 118), (306, 196), (139.4, 373)],
    [(273.5, 379), (273.5, 480.5), (172.5, 480.5)],
    [(379, 341), (449, 480.5), (364, 480.5)],
]
FONT_BOLD = "C:/Windows/Fonts/segoeuib.ttf"
FONT_REGULAR = "C:/Windows/Fonts/segoeui.ttf"


def amify_mark(size: int, color: tuple[int, int, int, int]) -> Image.Image:
    """The studio's mark, ``size`` pixels wide, in one colour on transparent."""
    scale = 4 * size / 533
    mask = Image.new("L", (4 * size, 4 * size), 0)
    d = ImageDraw.Draw(mask)
    d.polygon([(x * scale, y * scale) for x, y in AMIFY_OUTLINE], fill=255)
    for hole in AMIFY_HOLES:
        d.polygon([(x * scale, y * scale) for x, y in hole], fill=0)
    mask = mask.resize((size, size), Image.LANCZOS)
    image = Image.new("RGBA", (size, size), color)
    image.putalpha(mask.point(lambda v: v * color[3] // 255))
    return image


def icon(with_mark: bool = False) -> Image.Image:
    image = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(image)
    d.rounded_rectangle((0, 0, S - 1, S - 1), radius=int(S * 0.23), fill=BLUE)

    def p(x: float, y: float) -> tuple[int, int]:
        return int(x * S), int(y * S)

    # Bolt, slightly left of centre.
    bolt = [(0.50, 0.13), (0.22, 0.56), (0.41, 0.56), (0.33, 0.87), (0.64, 0.42), (0.45, 0.42)]
    d.polygon([p(x, y) for x, y in bolt], fill=WHITE)

    # Forecast: dots climbing to the right, ending on a ring.
    for x, y, r in ((0.60, 0.80, 0.030), (0.70, 0.71, 0.034), (0.785, 0.60, 0.038)):
        d.ellipse((*p(x - r, y - r), *p(x + r, y + r)), fill=AMBER)
    x, y, r, w = 0.845, 0.455, 0.075, 0.034
    d.ellipse((*p(x - r, y - r), *p(x + r, y + r)), fill=AMBER)
    d.ellipse((*p(x - r + w, y - r + w), *p(x + r - w, y + r - w)), fill=BLUE)

    if with_mark:
        mark = amify_mark(int(S * 0.20), (255, 255, 255, 235))
        image.alpha_composite(mark, p(0.095, 0.095))
    return image


def logo(dark: bool, height: int) -> Image.Image:
    """Wide logo: icon, name, and the studio signature. ``dark``: for dark themes."""
    text = (245, 245, 245, 255) if dark else (28, 32, 38, 255)
    soft = (190, 195, 202, 255) if dark else (96, 104, 114, 255)
    k = height / 256
    name_font = ImageFont.truetype(FONT_BOLD, int(118 * k))
    by_font = ImageFont.truetype(FONT_REGULAR, int(46 * k))
    canvas = Image.new("RGBA", (int(1000 * k), height), (0, 0, 0, 0))
    d = ImageDraw.Draw(canvas)
    tile = int(208 * k)
    canvas.alpha_composite(icon().resize((tile, tile), Image.LANCZOS), (int(24 * k), (height - tile) // 2))
    x = int(24 * k) + tile + int(40 * k)
    d.text((x, int(28 * k)), "Wattcast", font=name_font, fill=text)
    by_y = int(170 * k)
    d.text((x + int(4 * k), by_y), "par", font=by_font, fill=soft)
    mark_size = int(46 * k)
    mark_x = x + int(4 * k) + int(d.textlength("par ", font=by_font)) + int(6 * k)
    canvas.alpha_composite(amify_mark(mark_size, text), (mark_x, by_y + int(10 * k)))
    d.text((mark_x + mark_size + int(12 * k), by_y), "Amify-Studio", font=by_font, fill=text)
    # Trim the empty right side, keep the left margin symmetric.
    box = canvas.getbbox()
    return canvas.crop((0, 0, box[2] + int(24 * k), height))


def preview(out: pathlib.Path) -> None:
    """Both icon candidates at the sizes the UI really uses, and both logos."""
    sheet = Image.new("RGBA", (1180, 620), (250, 250, 250, 255))
    sheet.paste(Image.new("RGBA", (590, 620), (28, 28, 28, 255)), (590, 0))
    for half in (0, 590):
        y = 20
        for with_mark in (False, True):
            x = half + 24
            for size in (160, 64, 40, 24):
                sheet.alpha_composite(icon(with_mark).resize((size, size), Image.LANCZOS), (x, y + (160 - size) // 2))
                x += size + 22
            y += 185
        wide = logo(dark=half > 0, height=256)
        scale = 520 / wide.width
        sheet.alpha_composite(wide.resize((520, int(wide.height * scale)), Image.LANCZOS), (half + 24, 430))
    sheet.save(out)


def main() -> None:
    out = pathlib.Path("custom_components/wattcast/brand")
    out.mkdir(exist_ok=True)
    square = icon(with_mark="--mark" in sys.argv)
    for name, size in (("icon.png", 256), ("icon@2x.png", 512)):
        square.resize((size, size), Image.LANCZOS).save(out / name, optimize=True)
    for dark in (False, True):
        prefix = "dark_" if dark else ""
        logo(dark, 256).save(out / f"{prefix}logo.png", optimize=True)
        logo(dark, 512).save(out / f"{prefix}logo@2x.png", optimize=True)
    if "--preview" in sys.argv:
        preview(pathlib.Path("dev") / "icon_preview.png")
    print("brand images written")


if __name__ == "__main__":
    main()
