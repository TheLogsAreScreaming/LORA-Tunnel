"""Small vector icons drawn with PIL so they stay crisp at any size."""

import math


def _arc(d, cx, cy, r, start, end, color, width):
    d.arc((cx - r, cy - r, cx + r, cy + r), start, end, fill=color, width=width)


def radio(d, x, y, s, color):
    """Handheld radio with waves, echoing the LORA Tunnel logo."""
    w = s * 0.42
    bx, by = x + s * 0.22, y + s * 0.34
    d.rounded_rectangle((bx, by, bx + w, y + s * 0.98), radius=max(1, s * 0.08), fill=color)
    d.rectangle((bx + w * 0.12, by - s * 0.30, bx + w * 0.30, by), fill=color)
    inner = (bx + w * 0.16, by + s * 0.10, bx + w * 0.84, by + s * 0.28)
    d.rectangle(inner, fill=(4, 7, 10))
    for i in range(3):
        yy = by + s * (0.38 + i * 0.11)
        d.rectangle((bx + w * 0.18, yy, bx + w * 0.82, yy + max(1, s * 0.04)), fill=(4, 7, 10))
    cx, cy = bx + w * 0.75, by - s * 0.05
    lw = max(1, int(s * 0.07))
    _arc(d, cx, cy, s * 0.18, 280, 350, color, lw)
    _arc(d, cx, cy, s * 0.32, 280, 350, color, lw)


def nodes(d, x, y, s, color):
    pts = [(x + s * 0.5, y + s * 0.18), (x + s * 0.16, y + s * 0.78), (x + s * 0.84, y + s * 0.78)]
    lw = max(1, int(s * 0.07))
    for a in range(3):
        for b in range(a + 1, 3):
            d.line((pts[a], pts[b]), fill=color, width=lw)
    r = s * 0.14
    for px, py in pts:
        d.ellipse((px - r, py - r, px + r, py + r), fill=color)


def chat(d, x, y, s, color):
    d.rounded_rectangle((x + s * 0.08, y + s * 0.14, x + s * 0.92, y + s * 0.70), radius=s * 0.14, fill=color)
    d.polygon([(x + s * 0.24, y + s * 0.66), (x + s * 0.24, y + s * 0.92), (x + s * 0.48, y + s * 0.68)], fill=color)
    for i in range(3):
        cx = x + s * (0.32 + i * 0.18)
        r = s * 0.05
        d.ellipse((cx - r, y + s * 0.42 - r, cx + r, y + s * 0.42 + r), fill=(4, 7, 10))


def folder(d, x, y, s, color):
    d.rounded_rectangle((x + s * 0.06, y + s * 0.22, x + s * 0.46, y + s * 0.40), radius=s * 0.05, fill=color)
    d.rounded_rectangle((x + s * 0.06, y + s * 0.32, x + s * 0.94, y + s * 0.84), radius=s * 0.07, fill=color)


def sliders(d, x, y, s, color):
    lw = max(1, int(s * 0.08))
    for i, knob in enumerate((0.30, 0.68, 0.45)):
        yy = y + s * (0.22 + i * 0.28)
        d.line((x + s * 0.10, yy, x + s * 0.90, yy), fill=color, width=lw)
        kx = x + s * knob
        r = s * 0.11
        d.ellipse((kx - r, yy - r, kx + r, yy + r), fill=color)
        d.ellipse((kx - r * 0.45, yy - r * 0.45, kx + r * 0.45, yy + r * 0.45), fill=(4, 7, 10))


def satellite(d, x, y, s, color):
    cx, cy = x + s * 0.5, y + s * 0.5
    lw = max(1, int(s * 0.09))
    d.polygon([(cx - s * 0.12, cy), (cx, cy - s * 0.12), (cx + s * 0.12, cy), (cx, cy + s * 0.12)], fill=color)
    d.line((x + s * 0.12, y + s * 0.12, x + s * 0.34, y + s * 0.34), fill=color, width=lw * 2)
    d.line((x + s * 0.66, y + s * 0.66, x + s * 0.88, y + s * 0.88), fill=color, width=lw * 2)
    _arc(d, x + s * 0.18, y + s * 0.82, s * 0.30, 270, 360, color, lw)


def scan(d, x, y, s, color):
    """Radar sweep used for Survey and Recon."""
    cx, cy = x + s * 0.5, y + s * 0.5
    lw = max(1, int(s * 0.07))
    for r in (0.44, 0.28):
        _arc(d, cx, cy, s * r, 0, 360, color, lw)
    d.pieslice((cx - s * 0.44, cy - s * 0.44, cx + s * 0.44, cy + s * 0.44), 300, 345, fill=color)
    d.ellipse((cx - s * 0.06, cy - s * 0.06, cx + s * 0.06, cy + s * 0.06), fill=color)


def shield(d, x, y, s, color):
    d.polygon([(x + s * 0.5, y + s * 0.08), (x + s * 0.88, y + s * 0.22), (x + s * 0.82, y + s * 0.60),
               (x + s * 0.5, y + s * 0.94), (x + s * 0.18, y + s * 0.60), (x + s * 0.12, y + s * 0.22)], fill=color)
    lw = max(1, int(s * 0.09))
    d.line((x + s * 0.32, y + s * 0.50, x + s * 0.46, y + s * 0.64, x + s * 0.70, y + s * 0.36),
           fill=(4, 7, 10), width=lw)


def record(d, x, y, s, color):
    d.ellipse((x + s * 0.15, y + s * 0.15, x + s * 0.85, y + s * 0.85), fill=color)


def pin(d, x, y, s, color):
    cx = x + s * 0.5
    r = s * 0.30
    d.ellipse((cx - r, y + s * 0.08, cx + r, y + s * 0.08 + 2 * r), fill=color)
    d.polygon([(cx - r * 0.85, y + s * 0.50), (cx + r * 0.85, y + s * 0.50), (cx, y + s * 0.95)], fill=color)
    d.ellipse((cx - r * 0.4, y + s * 0.38 - r * 0.4, cx + r * 0.4, y + s * 0.38 + r * 0.4), fill=(4, 7, 10))


def arrow(d, x, y, s, color, degrees):
    """Compass arrow pointing to a bearing (0 = up/north)."""
    cx, cy = x + s / 2, y + s / 2
    rad = math.radians(degrees)
    pts = []
    for angle, radius in ((0, 0.46), (140, 0.36), (180, 0.14), (220, 0.36)):
        a = rad + math.radians(angle)
        pts.append((cx + math.sin(a) * s * radius, cy - math.cos(a) * s * radius))
    d.polygon(pts, fill=color)


ICONS = {"radio": radio, "nodes": nodes, "chat": chat, "folder": folder, "sliders": sliders,
         "satellite": satellite, "scan": scan, "shield": shield, "record": record, "pin": pin}
