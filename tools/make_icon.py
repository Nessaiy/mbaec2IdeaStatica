"""Erzeugt das Programm-Icon (pdf2idea/icon.ico + pdf2idea/icon_data.py). Aufruf: python tools/make_icon.py"""
import base64, io, math, os
from PIL import Image, ImageDraw, ImageFilter

S = 1024
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "pdf2idea")


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def make():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    # Hintergrund: Verlauf marine -> dunkelblau, abgerundet
    bg = Image.new("RGBA", (S, S))
    px = bg.load()
    for y in range(S):
        for x in range(S):
            t = (x * 0.4 + y * 0.6) / S
            px[x, y] = lerp((38, 74, 128), (10, 20, 48), t) + (255,)
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle((20, 20, S - 20, S - 20), radius=210, fill=255)
    img.paste(bg, (0, 0), mask)
    d = ImageDraw.Draw(img)
    # feines Raster (Zeichenblatt)
    for k in range(120, S, 130):
        d.line((k, 40, k, S - 40), fill=(255, 255, 255, 14), width=3)
        d.line((40, k, S - 40, k), fill=(255, 255, 255, 14), width=3)
    c = (S // 2, S // 2 + 30)

    def beam(p0, p1, w=96):
        """Stahlprofil (I) von oben: Flansche hell, Steg dunkler."""
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        n = math.hypot(dx, dy)
        nx, ny = -dy / n, dx / n
        def quad(o1, o2, col):
            pts = [(p0[0] + nx * o1, p0[1] + ny * o1), (p1[0] + nx * o1, p1[1] + ny * o1),
                   (p1[0] + nx * o2, p1[1] + ny * o2), (p0[0] + nx * o2, p0[1] + ny * o2)]
            d.polygon(pts, fill=col)
        quad(-w / 2, w / 2, (120, 135, 160, 255))
        quad(-w / 2, -w / 2 + 22, (214, 224, 240, 255))
        quad(w / 2 - 22, w / 2, (214, 224, 240, 255))
        quad(-8, 8, (92, 106, 132, 255))

    beam((120, c[1]), (S - 120, c[1]))            # durchlaufender Riegel
    beam((c[0], 150), c)                          # Stuetze von oben (endet am Knoten)
    # Knotenblech
    r = 118
    d.ellipse((c[0] - r, c[1] - r, c[0] + r, c[1] + r), fill=(255, 176, 0, 255), outline=(255, 214, 120, 255), width=10)
    for a in range(0, 360, 60):
        x, y = c[0] + 82 * math.cos(math.radians(a)), c[1] + 82 * math.sin(math.radians(a))
        d.ellipse((x - 11, y - 11, x + 11, y + 11), fill=(120, 70, 0, 255))
    # Kraftpfeil (gruen) von rechts oben auf den Knoten
    def arrow(p0, p1, col, w=34, head=92):
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        n = math.hypot(dx, dy); ux, uy = dx / n, dy / n
        b = (p1[0] - ux * head, p1[1] - uy * head)
        d.line((p0, b), fill=col, width=w)
        d.polygon([p1, (b[0] - uy * head * 0.55, b[1] + ux * head * 0.55), (b[0] + uy * head * 0.55, b[1] - ux * head * 0.55)], fill=col)
    arrow((c[0] + 330, c[1] + 330), (c[0] + 135, c[1] + 135), (60, 220, 90, 255))
    # Momentenbogen (rot) um den Knoten
    box = (c[0] - 205, c[1] - 205, c[0] + 205, c[1] + 205)
    d.arc(box, 200, 330, fill=(255, 70, 70, 255), width=36)
    ex, ey = c[0] + 205 * math.cos(math.radians(330)), c[1] + 205 * math.sin(math.radians(330))
    tx, ty = -math.sin(math.radians(330)), math.cos(math.radians(330))
    nx, ny = math.cos(math.radians(330)), math.sin(math.radians(330))
    d.polygon([(ex + tx * 78, ey + ty * 78), (ex + nx * 48, ey + ny * 48), (ex - nx * 48, ey - ny * 48)], fill=(255, 70, 70, 255))
    # Glanz oben
    gl = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(gl).rounded_rectangle((20, 20, S - 20, 420), radius=210, fill=(255, 255, 255, 26))
    img = Image.alpha_composite(img, Image.composite(gl, Image.new("RGBA", (S, S), (0, 0, 0, 0)), mask))
    return img


if __name__ == "__main__":
    big = make()
    sizes = [16, 24, 32, 48, 64, 128, 256]
    big.save(os.path.join(OUT, "icon.ico"), sizes=[(s, s) for s in sizes])
    big.resize((256, 256), Image.LANCZOS).save(os.path.join(HERE, "icon_preview.png"))
    buf = io.BytesIO()
    big.resize((128, 128), Image.LANCZOS).save(buf, "PNG")
    data = base64.b64encode(buf.getvalue()).decode()
    with open(os.path.join(OUT, "icon_data.py"), "w") as f:
        f.write('"""Automatisch erzeugt (tools/make_icon.py): Fenster-Icon als PNG (base64)."""\nPNG_B64 = (\n')
        for i in range(0, len(data), 100):
            f.write(f'    "{data[i:i+100]}"\n')
        f.write(")\n")
    print("ok")
