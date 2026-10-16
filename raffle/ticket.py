"""PNG-билет в стиле трамвайного, платиново-красно-белая палитра Hermes."""
import io
from datetime import datetime, timezone

from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 560, 900

PLATINUM = (213, 220, 212)
PLATINUM_DARK = (168, 176, 170)
HERMES_RED = (224, 36, 53)
DEEP_RED = (140, 20, 30)
CHERRY = (77, 3, 3)
BLACK = (6, 6, 6)
WHITE = (255, 255, 255)
SOFT = (255, 204, 213)

FONTS = {
    "bold": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ],
    "regular": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ],
}


def _font(weight, size):
    for path in FONTS[weight]:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _draw_logo(draw, cx, cy, width, height, color):
    hw, hh = width / 2, height / 2
    gap = max(2, width * 0.012)
    waist = hh * 0.22
    left = [(cx - hw, cy - hh), (cx - gap, cy - waist),
            (cx - gap, cy + waist), (cx - hw, cy + hh)]
    right = [(cx + gap, cy - waist), (cx + hw, cy - hh),
             (cx + hw, cy + hh), (cx + gap, cy + waist)]
    draw.polygon(left, fill=color)
    draw.polygon(right, fill=color)


def _draw_tracked(draw, text, x, y, font, fill, tracking=0, align="left"):
    widths = []
    for ch in text:
        bbox = draw.textbbox((0, 0), ch, font=font)
        widths.append(bbox[2] - bbox[0])
    total = sum(widths) + tracking * max(0, len(text) - 1)
    if align == "center":
        cx = x - total / 2
    elif align == "right":
        cx = x - total
    else:
        cx = x
    for ch, w in zip(text, widths):
        bbox = draw.textbbox((0, 0), ch, font=font)
        draw.text((cx - bbox[0], y), ch, font=font, fill=fill)
        cx += w + tracking


def _perforation(draw, y, x_start=40, x_end=W - 40, color=PLATINUM_DARK):
    x = x_start
    while x < x_end:
        draw.line([(x, y), (x + 6, y)], fill=color, width=2)
        x += 14


def generate(number, total=None):
    img = Image.new("RGB", (W, H), BLACK)
    draw = ImageDraw.Draw(img)

    for y in range(H):
        t = min(1.0, y / H)
        e = t * t
        r = int(CHERRY[0] * (1 - e) + BLACK[0] * e)
        g = int(CHERRY[1] * (1 - e) + BLACK[1] * e)
        b = int(CHERRY[2] * (1 - e) + BLACK[2] * e)
        draw.line([(0, y), (W, y)], fill=(r, g, b))

    header_h = 96
    draw.rectangle([0, 0, W, header_h], fill=PLATINUM)

    for i in range(60):
        x = 24 + i * 8
        h = 4 if i % 3 else 7
        draw.line([(x, 22), (x, 22 + h)], fill=PLATINUM_DARK, width=2)

    corner = _font("bold", 15)
    draw.text((24, 46), "HERMES EXCHANGE", font=corner, fill=DEEP_RED)
    draw.text((24, 66), "ТРАМВАЙНЫЙ БИЛЕТ · 2026", font=_font("regular", 12), fill=DEEP_RED)

    _draw_logo(draw, W - 90, header_h / 2, 96, 34, DEEP_RED)

    draw.rectangle([0, header_h, W, header_h + 4], fill=HERMES_RED)

    _draw_tracked(draw, "БИЛЕТ", W / 2, 150, _font("bold", 18), SOFT,
                  tracking=12, align="center")

    num_font = _font("bold", 240)
    num_str = str(number)
    bbox = draw.textbbox((0, 0), num_str, font=num_font)
    tw = bbox[2] - bbox[0]
    nx = (W - tw) / 2 - bbox[0]
    ny = 340 - bbox[1]

    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.text((nx, ny), num_str, font=num_font, fill=(*HERMES_RED, 240))
    glow = glow.filter(ImageFilter.GaussianBlur(45))
    img.paste(glow, (0, 0), glow)

    draw = ImageDraw.Draw(img)
    draw.text((nx, ny), num_str, font=num_font, fill=WHITE)

    series_font = _font("bold", 16)
    _draw_tracked(draw, "СЕРИЯ  HE", 40, 620, series_font, PLATINUM,
                  tracking=3, align="left")
    _draw_tracked(draw, f"№  {number:05d}", W - 40, 620, series_font, PLATINUM,
                  tracking=3, align="right")

    date_str = datetime.now(timezone.utc).strftime("%d.%m.%Y")
    _draw_tracked(draw, f"ДАТА  {date_str}", 40, 646, _font("regular", 13), PLATINUM_DARK,
                  tracking=2, align="left")

    _perforation(draw, 700)

    stub_font = _font("bold", 14)
    _draw_tracked(draw, "КОНТРОЛЬНЫЙ КОРЕШОК", W / 2, 730, stub_font, SOFT,
                  tracking=6, align="center")

    _draw_logo(draw, W / 2, 800, 180, 48, PLATINUM)

    brand = _font("bold", 11)
    _draw_tracked(draw, "THE HERMES EXCHANGE — SINCE 2018", W / 2, 850, brand,
                  HERMES_RED, tracking=2, align="center")

    draw.rectangle([0, 0, W - 1, H - 1], outline=HERMES_RED, width=1)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()