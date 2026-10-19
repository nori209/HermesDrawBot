"""PNG-билет в высоком качестве, платиново-красно-белая палитра Hermes."""
import io
from datetime import datetime, timezone

from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 720, 1160
SCALE = 3
SW, SH = W * SCALE, H * SCALE


def S(v):
    return int(round(v * SCALE))


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
            return ImageFont.truetype(path, S(size))
        except OSError:
            continue
    return ImageFont.load_default()


def _draw_logo(draw, cx, cy, width, height, color):
    cx, cy = S(cx), S(cy)
    hw, hh = S(width) / 2, S(height) / 2
    gap = max(2, S(width) * 0.012)
    waist = hh * 0.22
    left = [(cx - hw, cy - hh), (cx - gap, cy - waist),
            (cx - gap, cy + waist), (cx - hw, cy + hh)]
    right = [(cx + gap, cy - waist), (cx + hw, cy - hh),
             (cx + hw, cy + hh), (cx + gap, cy + waist)]
    draw.polygon(left, fill=color)
    draw.polygon(right, fill=color)


def _draw_tracked(draw, text, x, y, font, fill, tracking=0, align="left"):
    x, y = S(x), S(y)
    track_px = S(tracking)
    widths = []
    for ch in text:
        bbox = draw.textbbox((0, 0), ch, font=font)
        widths.append(bbox[2] - bbox[0])
    total = sum(widths) + track_px * max(0, len(text) - 1)
    if align == "center":
        cx = x - total / 2
    elif align == "right":
        cx = x - total
    else:
        cx = x
    for ch, w in zip(text, widths):
        bbox = draw.textbbox((0, 0), ch, font=font)
        draw.text((cx - bbox[0], y), ch, font=font, fill=fill)
        cx += w + track_px


def generate(number, total=None):
    img = Image.new("RGB", (SW, SH), BLACK)
    draw = ImageDraw.Draw(img)

    for y in range(SH):
        t = min(1.0, y / SH)
        e = t * t
        r = int(CHERRY[0] * (1 - e) + BLACK[0] * e)
        g = int(CHERRY[1] * (1 - e) + BLACK[1] * e)
        b = int(CHERRY[2] * (1 - e) + BLACK[2] * e)
        draw.line([(0, y), (SW, y)], fill=(r, g, b))

    header_h = S(120)
    draw.rectangle([0, 0, SW, header_h], fill=PLATINUM)

    for i in range(72):
        x = S(30) + i * S(9)
        h = S(4) if i % 3 else S(8)
        draw.line([(x, S(28)), (x, S(28) + h)], fill=PLATINUM_DARK, width=S(2))

    corner = _font("bold", 17)
    draw.text((S(30), S(58)), "HERMES EXCHANGE", font=corner, fill=DEEP_RED)
    draw.text((S(30), S(82)), "КРИПТОБИЛЕТ · 2026",
              font=_font("regular", 13), fill=DEEP_RED)

    draw.rectangle([0, header_h, SW, header_h + S(5)], fill=HERMES_RED)

    _draw_tracked(draw, "БИЛЕТ", W / 2, 195, _font("bold", 22), SOFT,
                  tracking=14, align="center")

    num_font = _font("bold", 300)
    num_str = str(number)
    bbox = draw.textbbox((0, 0), num_str, font=num_font)
    tw = bbox[2] - bbox[0]
    nx = (SW - tw) / 2 - bbox[0]
    ny = S(440) - bbox[1]

    glow = Image.new("RGBA", (SW, SH), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.text((nx, ny), num_str, font=num_font, fill=(*HERMES_RED, 240))
    glow = glow.filter(ImageFilter.GaussianBlur(S(55)))
    img.paste(glow, (0, 0), glow)

    draw = ImageDraw.Draw(img)
    draw.text((nx, ny), num_str, font=num_font, fill=WHITE)

    date_str = datetime.now(timezone.utc).strftime("%d.%m.%Y")
    _draw_tracked(draw, f"ДАТА  {date_str}", W / 2, 900,
                  _font("regular", 15), PLATINUM_DARK,
                  tracking=3, align="center")

    _draw_logo(draw, W / 2, 1010, 220, 58, PLATINUM)

    brand = _font("bold", 13)
    _draw_tracked(draw, "THE HERMES EXCHANGE — SINCE 2018",
                  W / 2, 1080, brand, HERMES_RED,
                  tracking=3, align="center")

    draw.rectangle([0, 0, SW - 1, SH - 1], outline=HERMES_RED, width=S(1))

    img = img.resize((W, H), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()