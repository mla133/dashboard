"""Generate the LCARS-style app icons (run: python make_icons.py). Needs Pillow."""
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).parent
S = 1024
PALETTES = {
    "lcars_dash.ico": dict(main="#ff9900", a="#ffcc99", b="#cc99cc", c="#9999ff", d="#99ccff", glyph=None),
    "lcars_dash_tui.ico": dict(main="#9999ff", a="#99ccff", b="#cc99cc", c="#ff9900", d="#ffcc99", glyph="#ff9900"),
}


def draw_icon(p: dict) -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, S - 1, S - 1), radius=200, fill="#000000")
    # elbow: vertical bar + top bar with a large rounded outer corner and a concave inner corner
    d.rectangle((60, 60, 420, 964), fill=p["main"])
    d.rectangle((60, 60, 620, 300), fill=p["main"])
    d.rectangle((60, 60, 320, 320), fill="#000000")
    d.pieslice((60, 60, 580, 580), 180, 270, fill=p["main"])
    d.rounded_rectangle((420, 300, 1000, 1000), radius=90, fill="#000000")
    # top bar segments
    d.rounded_rectangle((650, 60, 800, 300), radius=30, fill=p["a"])
    d.rounded_rectangle((830, 60, 964, 300), radius=120, fill=p["b"])
    # lower vertical bar segments
    d.rectangle((60, 560, 420, 590), fill="#000000")
    d.rectangle((60, 610, 420, 780), fill=p["d"])
    d.rounded_rectangle((60, 800, 420, 964), radius=70, fill=p["b"])
    d.rectangle((60, 800, 420, 860), fill=p["b"])
    if p["glyph"]:
        # terminal prompt ">_" for the TUI icon
        g = p["glyph"]
        d.line([(500, 430), (640, 560), (500, 690)], fill=g, width=56, joint="curve")
        d.rounded_rectangle((690, 660, 900, 716), radius=20, fill=g)
    else:
        for box, col in (((480, 380, 940, 450), p["c"]), ((480, 500, 820, 570), p["d"]),
                         ((480, 620, 900, 690), p["b"]), ((480, 740, 700, 810), p["a"])):
            d.rounded_rectangle(box, radius=35, fill=col)
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, S - 1, S - 1), radius=200, fill=255)
    img.putalpha(mask)
    return img


for name, pal in PALETTES.items():
    big = draw_icon(pal).resize((256, 256), Image.LANCZOS)
    big.save(OUT / name, format="ICO", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    big.save(OUT / name.replace(".ico", "_preview.png"))
    print("wrote", OUT / name)
