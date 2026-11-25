#!/usr/bin/env python3
"""News image for Wednesday 25 November 2026 — "THE WORLD IN ONE DAY".

Draws a 1024x1024 poster with the Python 3.13 standard library only: a
DejaVu Sans Bold glyph atlas (atlas.json, rasterised in-session from the
system font) is blitted onto a navy poster, and the result is encoded as a
PNG with zlib. No network, no randomness, no timestamps in the output:
two runs write byte-identical files.

Concept (winner of the 3-way concept test, 42/50): the day as four hard
numbers — 7 drones sink a Russian warship, Nvidia +30% as Huang returns,
26 dead in a Banten factory fire, 48 teams for the 2031 Women's World Cup
— under the biggest element on the page, the date 25 NOVEMBER 2026.
"""
import base64
import binascii
import json
import os
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
WIDTH = 1024
HEIGHT = 1024

NAVY = (13, 27, 46)
GOLD = (227, 168, 43)
WHITE = (255, 255, 255)
BODY = (196, 208, 222)
LINE = (34, 52, 78)
FOOT = (159, 176, 195)
CREDIT_GREY = (110, 127, 146)
CHIP_RED = (214, 69, 65)
CHIP_GREEN = (91, 168, 41)
CHIP_AMBER = (232, 145, 45)
CHIP_BLUE = (46, 127, 194)

MARGIN = 48
RIGHT = WIDTH - MARGIN


# ---------------------------------------------------------------- atlas ----
class Atlas:
    """Grayscale glyph atlas rendered from DejaVu Sans Bold at 120 px."""

    def __init__(self, path):
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        self.size = data["size"]
        self.glyphs = {}
        for ch, g in data["glyphs"].items():
            raw = base64.b64decode(g["data"]) if g["data"] else b""
            self.glyphs[ch] = (g["adv"], g["bx"], g["by"], g["w"], g["h"], raw)
        self._scaled = {}

    def scaled(self, ch, size):
        """Return (adv, bx, by, w, h, pixels) for ch at target size px."""
        key = (ch, size)
        hit = self._scaled.get(key)
        if hit is not None:
            return hit
        adv, bx, by, w, h, raw = self.glyphs[ch]
        f = size / self.size
        if w == 0 or h == 0:
            out = (round(adv * f), round(bx * f), round(by * f), 0, 0, b"")
            self._scaled[key] = out
            return out
        tw = max(1, round(w * f))
        th = max(1, round(h * f))
        # Integral image of the source glyph for fast box-filter downscale.
        ii = [0] * ((w + 1) * (h + 1))
        for y in range(h):
            row_sum = 0
            base = y * w
            ii_base = (y + 1) * (w + 1)
            ii_prev = y * (w + 1)
            for x in range(w):
                row_sum += raw[base + x]
                ii[ii_base + x + 1] = ii[ii_prev + x + 1] + row_sum
        px = bytearray(tw * th)
        for oy in range(th):
            y0 = int(oy / f)
            y1 = int((oy + 1) / f)
            if y1 <= y0:
                y1 = y0 + 1
            if y1 > h:
                y1 = h
            for ox in range(tw):
                x0 = int(ox / f)
                x1 = int((ox + 1) / f)
                if x1 <= x0:
                    x1 = x0 + 1
                if x1 > w:
                    x1 = w
                total = (
                    ii[y1 * (w + 1) + x1]
                    - ii[y0 * (w + 1) + x1]
                    - ii[y1 * (w + 1) + x0]
                    + ii[y0 * (w + 1) + x0]
                )
                area = (x1 - x0) * (y1 - y0)
                px[oy * tw + ox] = total // area if area else 0
        out = (round(adv * f), round(bx * f), round(by * f), tw, th, bytes(px))
        self._scaled[key] = out
        return out

    def text_width(self, text, size, tracking=0):
        total = 0
        for ch in text:
            total += self.scaled(ch, size)[0] + tracking
        return total - tracking if text else 0

    def fit_size(self, text, max_width, start, minimum, tracking=0):
        size = start
        while size > minimum and self.text_width(text, size, tracking) > max_width:
            size -= 1
        return size


# ---------------------------------------------------------------- canvas ---
class Canvas:
    def __init__(self, w, h, color):
        self.w = w
        self.h = h
        self.buf = bytearray(bytes(color) * (w * h))

    def rect(self, x, y, w, h, color):
        row = bytes(color) * w
        stride = self.w * 3
        for yy in range(y, y + h):
            off = yy * stride + x * 3
            self.buf[off:off + w * 3] = row

    def text(self, atlas, x, y, s, size, color, tracking=0):
        """Draw s with its em-box top at (x, y)."""
        cx = x
        r, g, b = color
        for ch in s:
            adv, bx, by, w, h, px = atlas.scaled(ch, size)
            if w and h:
                gx = cx + bx
                gy = y + by
                for row in range(h):
                    base = row * w
                    off = (gy + row) * self.w * 3 + gx * 3
                    for col in range(w):
                        a = px[base + col]
                        if a == 0:
                            continue
                        p = off + col * 3
                        if a == 255:
                            self.buf[p] = r
                            self.buf[p + 1] = g
                            self.buf[p + 2] = b
                        else:
                            self.buf[p] = (r * a + self.buf[p] * (255 - a)) // 255
                            self.buf[p + 1] = (g * a + self.buf[p + 1] * (255 - a)) // 255
                            self.buf[p + 2] = (b * a + self.buf[p + 2] * (255 - a)) // 255
            cx += adv + tracking

    def png_bytes(self):
        def chunk(kind, data):
            out = struct.pack(">I", len(data)) + kind + data
            return out + struct.pack(">I", binascii.crc32(kind + data) & 0xFFFFFFFF)

        ihdr = struct.pack(">IIBBBBB", self.w, self.h, 8, 2, 0, 0, 0)
        raw = bytearray()
        stride = self.w * 3
        prev = bytes(stride)
        for y in range(self.h):
            row = bytes(self.buf[y * stride:(y + 1) * stride])
            # Sub filter (bpp 3): byte minus the byte 3 positions back.
            filt = bytearray(stride)
            filt[0:3] = row[0:3]
            for i in range(3, stride):
                filt[i] = (row[i] - row[i - 3]) & 0xFF
            raw.append(1)
            raw += filt
            prev = row
        return (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b"")
        )


# ---------------------------------------------------------------- poster ---
STORIES = [
    {
        "num": "7",
        "chip": CHIP_RED,
        "num_color": WHITE,
        "head": "UKRAINE SINKS RUSSIAN WARSHIP",
        "body": "Kyiv: 7 drones sank the corvette Merkury off Libya.",
    },
    {
        "num": "+30%",
        "chip": CHIP_GREEN,
        "num_color": WHITE,
        "head": "HUANG BACK AT NVIDIA",
        "body": "Reinstated as chief; shares jump 30% at the open.",
    },
    {
        "num": "26",
        "chip": CHIP_AMBER,
        "num_color": NAVY,
        "head": "FACTORY FIRE IN BANTEN",
        "body": "Candy-plant fire west of Jakarta kills at least 26.",
    },
    {
        "num": "48",
        "chip": CHIP_BLUE,
        "num_color": WHITE,
        "head": "2031 WORLD CUP: 48 TEAMS",
        "body": "USA, Mexico, Costa Rica, Jamaica host in 2031.",
    },
]

FOOTER_1 = "ALSO TODAY: POPE FRANCIS DIARY PUBLISHED \u00b7 PAKISTANI ASTRONAUT LAUNCHES"
FOOTER_2 = "HOUTHIS HIT RIYADH'S TALLEST TOWER \u2014 11 WOUNDED"
CREDIT = "Drawn by an agent for make.fun \u2014 the picture of 25 November 2026"


def draw_poster(atlas):
    c = Canvas(WIDTH, HEIGHT, NAVY)
    # Masthead.
    c.text(atlas, MARGIN, 42, "THE WORLD IN ONE DAY", 30, GOLD, tracking=6)
    date_size = atlas.fit_size("25 NOVEMBER 2026", RIGHT - MARGIN, 92, 60)
    c.text(atlas, MARGIN, 86, "25 NOVEMBER 2026", date_size, WHITE)
    c.text(atlas, MARGIN, 192, "WEDNESDAY", 32, GOLD, tracking=8)
    c.rect(MARGIN, 238, RIGHT - MARGIN, 4, GOLD)
    # Four story bands.
    band_y = 262
    band_h = 148
    gap = 12
    chip_w = 170
    for st in STORIES:
        c.rect(MARGIN, band_y, chip_w, band_h, st["chip"])
        num_size = atlas.fit_size(st["num"], chip_w - 16, 118, 40)
        nw = atlas.text_width(st["num"], num_size)
        c.text(
            atlas,
            MARGIN + (chip_w - nw) // 2,
            band_y + (band_h - num_size) // 2,
            st["num"],
            num_size,
            st["num_color"],
        )
        tx = MARGIN + chip_w + 28
        head_size = atlas.fit_size(st["head"], RIGHT - tx, 38, 24)
        c.text(atlas, tx, band_y + 20, st["head"], head_size, WHITE)
        body_size = atlas.fit_size(st["body"], RIGHT - tx, 24, 16)
        c.text(atlas, tx, band_y + 88, st["body"], body_size, BODY)
        band_y += band_h + gap
    # Footer.
    c.rect(MARGIN, 912, RIGHT - MARGIN, 3, GOLD)
    f1 = atlas.fit_size(FOOTER_1, RIGHT - MARGIN, 21, 14)
    c.text(atlas, MARGIN, 930, FOOTER_1, f1, FOOT)
    f2 = atlas.fit_size(FOOTER_2, RIGHT - MARGIN, 21, 14)
    c.text(atlas, MARGIN, 958, FOOTER_2, f2, FOOT)
    c.text(atlas, MARGIN, 990, CREDIT, 15, CREDIT_GREY)
    return c


def main():
    atlas = Atlas(os.path.join(HERE, "atlas.json"))
    poster = draw_poster(atlas)
    out_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "entry.png")
    with open(path, "wb") as fh:
        fh.write(poster.png_bytes())
    print("wrote %s (%d bytes)" % (path, os.path.getsize(path)))


if __name__ == "__main__":
    main()
