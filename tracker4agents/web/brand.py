"""ChipLoom's identity for the browser studio: the wordmark, the emblem favicon and the palette CSS.

The wordmark is the bundled `assets/chiploom-logo.png`, served as it is. The favicon is the same
four-channel emblem the desktop window uses (`logo.copy(100, 160, 520, 410)` in `brand_icon()`),
cropped and scaled once at first request with the standard library only (no Pillow, no Qt) and kept
in memory: no extra binary file lives in the repository. The CSS variables come straight from
`themes.py`, so the page and the desktop palettes cannot drift apart.
"""

from __future__ import annotations

import struct
import threading
import zlib
from pathlib import Path

from ..themes import THEMES

LOGO = Path(__file__).resolve().parents[1] / "assets" / "chiploom-logo.png"
EMBLEM_BOX = (100, 160, 520, 410)         # x, y, width, height: same crop as desktop_widgets.brand_icon()
EMBLEM_SIZE = 96
# Highlights of the public listening page (docs/listen/index.html). The light variants are darker so
# they stay readable (4.5:1) on white; the dark ones are the page's own values.
BRAND = {"midnight": {"mint": "#56e7c6", "violet": "#b09cff"}, "light": {"mint": "#0b7a64", "violet": "#5b43d6"}}
# Channels beyond the theme's four: channel i uses the theme colour i % 4, mixed toward the text colour by
# TINTS[(i // 4) % 3] (a plain sRGB blend, so any toolkit reproduces it). Each group of four channels starts
# with a stronger separator in the grid. Mixing toward the text colour can only raise the contrast.
TINTS = (0.0, 0.30, 0.50)
MAX_CHANNELS = 32
SHADOW = {"midnight": "0 8px 28px rgba(0, 0, 0, .45)", "light": "0 8px 28px rgba(27, 43, 62, .18)"}
_lock = threading.Lock()
_cache: dict[str, bytes | None] = {}


# --- palette -------------------------------------------------------------------------------------------

def mix(color: str, other: str, amount: float) -> str:
    """`color` blended `amount` (0..1) toward `other`, both "#rrggbb": the sRGB blend of CSS color-mix()."""
    a, b = (tuple(int(value[i:i + 2], 16) for i in (1, 3, 5)) for value in (color, other))
    return "#" + "".join(f"{round(x + (y - x) * amount):02x}" for x, y in zip(a, b))


def channel_color(name: str, index: int) -> str:
    """Colour of channel `index` (0-based, up to 31) in the theme `name` ("midnight" or "light")."""
    palette = THEMES[name]
    return mix(palette["channels"][index % 4], palette["text"], TINTS[(index // 4) % 3])


def theme_variables(name: str) -> str:
    """The CSS custom properties of one `themes.py` palette."""
    palette = THEMES[name]
    lines = [f"  color-scheme: {'light' if name == 'light' else 'dark'};"]
    for key, value in palette.items():
        if key == "channels":
            lines += [f"  --ch{index + 1}: {color};" for index, color in enumerate(value)]
            lines += [f"  --ch{index + 1}: {channel_color(name, index)};" for index in range(4, MAX_CHANNELS)]
        elif key != "name":
            lines.append(f"  --{key.replace('_', '-')}: {value};")
    lines += [f"  --{key}: {value};" for key, value in BRAND[name].items()]
    lines.append(f"  --shadow: {SHADOW[name]};")
    return "\n".join(lines)


def theme_css() -> bytes:
    """Midnight by default, Light on `data-theme="light"`, and the system's choice on `data-theme="auto"`."""
    dark, light = theme_variables("midnight"), theme_variables("light")
    text = ("/* Generated from tracker4agents/themes.py at request time: do not edit. */\n"
            f":root {{\n{dark}\n}}\n"
            f":root[data-theme=\"dark\"] {{\n{dark}\n}}\n"
            f":root[data-theme=\"light\"] {{\n{light}\n}}\n"
            f"@media (prefers-color-scheme: light) {{\n:root[data-theme=\"auto\"] {{\n{light}\n}}\n}}\n")
    return text.encode("utf-8")


# --- wordmark ----------------------------------------------------------------------------------------------

def logo_png() -> bytes | None:
    try:
        return LOGO.read_bytes()
    except OSError:
        return None


# --- emblem (PNG decode, crop, box-filter scale, encode) -----------------------------------------------------

def _chunks(data: bytes):
    position = 8
    while position + 8 <= len(data):
        size, kind = struct.unpack(">I4s", data[position:position + 8])
        yield kind, data[position + 8:position + 8 + size]
        position += size + 12


def _crop_rgba(png: bytes, box: tuple[int, int, int, int]) -> list[bytearray] | None:
    """The `box` rows of an 8-bit RGBA, non-interlaced PNG as lists of RGBA bytes, or None for other layouts.

    Only the columns left of the crop's right edge are unfiltered: the PNG filters look left and up only."""
    if not png.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    header, idat = None, []
    for kind, body in _chunks(png):
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            idat.append(body)
    if header is None or header[2:] != (8, 6, 0, 0, 0):
        return None
    width, height = header[:2]
    x, y, w, h = box
    if x + w > width or y + h > height:
        return None
    raw = zlib.decompress(b"".join(idat))
    stride, bpp, keep = 1 + width * 4, 4, (x + w) * 4
    previous, rows = bytearray(keep), []
    for row in range(y + h):
        base = row * stride
        kind = raw[base]
        line = bytearray(raw[base + 1:base + 1 + keep])
        if kind == 1:
            for i in range(bpp, keep):
                line[i] = (line[i] + line[i - bpp]) & 255
        elif kind == 2:
            line = bytearray((a + b) & 255 for a, b in zip(line, previous))
        elif kind == 3:
            for i in range(keep):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + previous[i]) >> 1)) & 255
        elif kind == 4:
            for i in range(keep):
                a = line[i - bpp] if i >= bpp else 0
                b, c = previous[i], (previous[i - bpp] if i >= bpp else 0)
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        elif kind != 0:
            return None
        previous = line
        if row >= y:
            rows.append(line[x * 4:(x + w) * 4])
    return rows


def _scale(rows: list[bytearray], width: int, out_w: int, out_h: int) -> list[bytearray]:
    """Area-average downscale with premultiplied alpha."""
    height = len(rows)
    result = []
    for oy in range(out_h):
        y0, y1 = oy * height // out_h, max(oy * height // out_h + 1, (oy + 1) * height // out_h)
        line = bytearray()
        for ox in range(out_w):
            x0, x1 = ox * width // out_w, max(ox * width // out_w + 1, (ox + 1) * width // out_w)
            r = g = b = a = n = 0
            for sy in range(y0, y1):
                source = rows[sy]
                for sx in range(x0, x1):
                    i = sx * 4
                    alpha = source[i + 3]
                    r += source[i] * alpha
                    g += source[i + 1] * alpha
                    b += source[i + 2] * alpha
                    a += alpha
                    n += 1
            if a:
                line += bytes((round(r / a), round(g / a), round(b / a), round(a / n)))
            else:
                line += b"\0\0\0\0"
        result.append(line)
    return result


def _encode_png(rows: list[bytearray], width: int) -> bytes:
    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    data = b"".join(b"\0" + bytes(row) for row in rows)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, len(rows), 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(data, 9)) + chunk(b"IEND", b""))


def emblem_png() -> bytes | None:
    """The four-channel emblem on a transparent square, `EMBLEM_SIZE` px: favicon and apple-touch icon."""
    with _lock:
        if "emblem" not in _cache:
            _cache["emblem"] = None
            png = logo_png()
            try:
                rows = _crop_rgba(png, EMBLEM_BOX) if png else None
            except (zlib.error, struct.error, IndexError):
                rows = None
            if rows:
                box_w, box_h = EMBLEM_BOX[2], EMBLEM_BOX[3]
                out_w = EMBLEM_SIZE
                out_h = max(1, round(box_h * out_w / box_w))
                scaled = _scale(rows, box_w, out_w, out_h)
                blank = bytearray(EMBLEM_SIZE * 4)
                top = (EMBLEM_SIZE - out_h) // 2
                canvas = [blank] * top + scaled + [blank] * (EMBLEM_SIZE - out_h - top)
                _cache["emblem"] = _encode_png(canvas, EMBLEM_SIZE)
        return _cache["emblem"]
