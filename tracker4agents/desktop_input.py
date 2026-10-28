"""Qt-free tracker input helpers: piano keyboard layouts, hex digits and clipboard grid text.

The piano maps follow the FastTracker convention. Two rows give the notes: the lower row
(with its black keys on the home row) starts at the base octave, the upper row (black
keys on the number row) starts one octave higher. Both rows continue a few keys into the
next octave, as in the classic trackers.
"""

from __future__ import annotations

import re

from .model import NOTES, XM_NOTES, Cell, ValidationError
from .patch import cell_text, parse_cell

LAYOUTS = ("auto", "qwerty", "azerty")

# Semitone offsets from the base octave, by the character the key produces.
QWERTY_KEYS = {
    **dict(zip("zsxdcvgbhnjm,l.;/", range(17))),
    **dict(zip("q2w3er5t6y7ui9o0p", range(12, 29))),
}
AZERTY_KEYS = {
    **dict(zip("wsxdcvgbhnj,;l:m!", range(17))),
    **dict(zip('aéz"er(t-yèuiçoàp', range(12, 29))),
}
# Unshifted number row of an AZERTY keyboard, accepted as hexadecimal digits.
AZERTY_DIGITS = dict(zip("&é\"'(-è_çà", "1234567890"))
HEX_DIGITS = "0123456789abcdef"
# XM: the key left of "2" on the number row (the "&" key of an AZERTY keyboard) enters key off, as in FastTracker II.
KEY_OFF_KEYS = {"qwerty": "1", "azerty": "&"}
EFFECT_LETTERS = "ghijklmnopqrstuvwxyz"   # XM effects 16..35 follow F (0-9 then A-Z)


def valid_layout(value: object) -> str:
    """Session values are untrusted: anything unknown means automatic."""
    return value if isinstance(value, str) and value in LAYOUTS else "auto"


def resolve_layout(setting: object, locale_name: str = "", language: str = "") -> str:
    """Turn Auto/QWERTY/AZERTY into a concrete map; Auto picks AZERTY for French input."""
    setting = valid_layout(setting)
    if setting != "auto":
        return setting
    name = (locale_name or "").replace("-", "_").lower()
    if language.lower().startswith("fr") or name.startswith("fr") or name.endswith("_be"):
        return "azerty"
    return "qwerty"


def semitone(layout: str, text: str) -> int | None:
    """Semitone offset above the base octave for a typed character, or None."""
    table = AZERTY_KEYS if layout == "azerty" else QWERTY_KEYS
    return table.get(text.lower()) if len(text) == 1 else None


def note_name(octave: int, offset: int, fmt: str = "mod") -> str | None:
    """Tracker note for `offset` semitones above C of `octave`, or None outside the format's range
    (C-1..B-3 in a MOD, C-0..B-7 in an XM)."""
    if fmt == "xm":
        index = octave * 12 + offset
        return XM_NOTES[index] if 0 <= index < len(XM_NOTES) else None
    index = (octave - 1) * 12 + offset
    return NOTES[index] if 0 <= index < len(NOTES) else None


def is_key_off(layout: str, text: str) -> bool:
    """True for the character of the key-off key at this layout (the number-row key before "2")."""
    return len(text) == 1 and text == KEY_OFF_KEYS["azerty" if layout == "azerty" else "qwerty"]


def effect_letter(text: str) -> str | None:
    """Uppercase letter G-Z that starts an XM effect (the digits and A-F come from `hex_digit`)."""
    return text.upper() if len(text) == 1 and text.lower() in EFFECT_LETTERS else None


def hex_digit(layout: str, text: str) -> str | None:
    """Uppercase hexadecimal digit for a typed character; AZERTY accepts the unshifted number row."""
    if len(text) != 1:
        return None
    text = text.lower()
    if layout == "azerty" and text in AZERTY_DIGITS:
        return AZERTY_DIGITS[text]
    return text.upper() if text in HEX_DIGITS else None


# --- clipboard ----------------------------------------------------------------------

def format_block(block: list[list[Cell]], fmt: str = "mod") -> str:
    """Grid text as printed by `inspect --grid`, without the row prefix: `C-2 01 ... | --- -- ...`."""
    return "\n".join(" | ".join(cell_text(value, fmt) for value in row) for row in block)


def parse_block(text: str, fmt: str = "mod", max_rows: int = 64, max_channels: int = 4) -> list[list[Cell]]:
    """Read grid text from the clipboard: bare cells, or rows like `10 | C-2 01 ... | ...`.

    Lines without a `|` that are not cells (titles an agent printed) are skipped. The row
    numbers of an agent's grid are ignored: the block lands at the cursor.
    """
    rows: list[list[Cell]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [part.strip() for part in line.strip("|").split("|")]
        if len(parts) > 1 and re.fullmatch(r"[0-9A-Fa-f]{2}", parts[0]):
            parts = parts[1:]
        try:
            rows.append([parse_cell(part, fmt) for part in parts])
        except ValidationError:
            if "|" in line:
                raise
    if not rows:
        raise ValidationError("The clipboard holds no pattern cells.", "PATCH_CELL")
    if len({len(row) for row in rows}) != 1 or len(rows[0]) > max_channels or len(rows) > max_rows:
        raise ValidationError(f"The clipboard block must have 1-{max_rows} rows of 1-{max_channels} cells.", "PATCH_CELL")
    return rows
