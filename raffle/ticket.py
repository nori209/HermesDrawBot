"""PNG-билет в фирменном стиле Hermes Exchange."""
import io

from PIL import Image, ImageDraw, ImageFont, ImageFilter

SIZE = 800

SILVER = (213, 220, 212)
HERMES_RED = (224, 36, 53)
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
    """Знак Hermes — две встречные формы с сужением в центре."""
    hw, hh = width / 2, height / 2
    gap = 4
    waist = hh * 0.22

    left = [
        (cx - hw, cy - hh),
        (cx - gap, cy - waist),
        (cx - gap, cy + waist),
        (cx - hw, cy + hh),
    ]
    right = [
        (cx + gap, cy - waist),
        (cx + hw, cy - hh),
        (cx + hw, cy + hh),
        (cx + gap, cy + waist),
    ]
    draw.polygon(left, fill=color)
    draw.polygon(right, fill=color)


def _draw_tracked(draw, text, x, y, font, fill, tracking=0, align="left"):
    """Текст с letter-spacing. Pillow такого не умеет — рисуем по буквам."""
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


def generate(number, total):
    img = Image.new("RGB", (SIZE, SIZE), BLACK)
    draw = ImageDraw.Draw(img)

    for y in range(SIZE):
        t = min(1.0, (y / SIZE) * 1.5)
        e = t * t
        r = int(CHERRY[0] * (1 - e) + BLACK[0] * e)
        g = int(CHERRY[1] * (1 - e) + BLACK[1] * e)
        b = int(CHERRY[2] * (1 - e) + BLACK[2] * e)
        draw.line([(0, y), (SIZE, y)], fill=(r, g, b))

    overlay = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    for x in range(SIZE):
        alpha = max(0, int(110 * (1 - x / (SIZE * 0.75))))
        if alpha:
            od.line([(x, 0), (x, SIZE)], fill=(*HERMES_RED, alpha))
    overlay = overlay.filter(ImageFilter.GaussianBlur(90))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(img)

    corner = _font("bold", 15)
    draw.text((42, 40), "HERMES EXCHANGE", font=corner, fill=SOFT)
    draw.text((42, 62), "2026", font=corner, fill=SOFT)

    ticket_text = "TICKET"
    bbox = draw.textbbox((0, 0), ticket_text, font=corner)
    draw.text((SIZE - 42 - (bbox[2] - bbox[0]), 40), ticket_text, font=corner, fill=SOFT)

    logo_cy = 220
    logo_w = 500
    logo_h = 130
    _draw_logo(draw, SIZE / 2, logo_cy, logo_w, logo_h, SILVER)

    reg = _font("bold", 16)
    draw.text((SIZE / 2 + logo_w / 2 + 2, logo_cy - logo_h / 2 - 14), "®", font=reg, fill=SILVER)

    draw.line([(140, 330), (SIZE - 140, 330)], fill=HERMES_RED, width=1)

    label = _font("bold", 20)
    _draw_tracked(draw, "ВАШ БИЛЕТ", SIZE / 2, 360, label, HERMES_RED,
                  tracking=8, align="center")

    num_font = _font("bold", 300)
    num_str = str(number)
    bbox = draw.textbbox((0, 0), num_str, font=num_font)
    tw = bbox[2] - bbox[0]
    nx = (SIZE - tw) / 2 - bbox[0]
    ny = 470 - bbox[1]

    glow = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.text((nx, ny), num_str, font=num_font, fill=(*HERMES_RED, 235))
    glow = glow.filter(ImageFilter.GaussianBlur(55))
    img.paste(glow, (0, 0), glow)

    draw = ImageDraw.Draw(img)
    draw.text((nx, ny), num_str, font=num_font, fill=WHITE)

    small = _font("regular", 18)
    _draw_tracked(draw, f"ИЗ {total} УЧАСТНИКОВ", SIZE / 2, 700, small, SOFT,
                  tracking=5, align="center")

    brand = _font("bold", 12)
    _draw_tracked(draw, "THE HERMES EXCHANGE — SINCE 2018", SIZE / 2, 745, brand,
                  HERMES_RED, tracking=3, align="center")

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()