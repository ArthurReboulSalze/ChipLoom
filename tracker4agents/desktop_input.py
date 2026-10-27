"""Qt-free tracker input helpers: piano keyboard layouts, hex digits and clipboard grid text.

The piano maps follow the FastTracker convention. Two rows give the notes: the lower row
(with its black keys on the home row) starts at the base octave, the upper row (black
keys on the number row) starts one octave higher. Both rows continue a few keys into the
next octave, as in the classic trackers.
"""

from __future__ import annotations

import re

from .model import NOTES, Cell, ValidationError
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


def note_name(octave: int, offset: int) -> str | None:
    """Tracker note for `offset` semitones above C of `octave`, or None outside C-1..B-3."""
    index = (octave - 1) * 12 + offset
    return NOTES[index] if 0 <= index < len(NOTES) else None


def hex_digit(layout: str, text: str) -> str | None:
    """Uppercase hexadecimal digit for a typed character; AZERTY accepts the unshifted number row."""
    if len(text) != 1:
        return None
    text = text.lower()
    if layout == "azerty" and text in AZERTY_DIGITS:
        return AZERTY_DIGITS[text]
    return text.upper() if text in HEX_DIGITS else None


# --- clipboard ----------------------------------------------------------------------

def format_block(block: list[list[Cell]]) -> str:
    """Grid text as printed by `inspect --grid`, without the row prefix: `C-2 01 ... | --- -- ...`."""
    return "\n".join(" | ".join(cell_text(value) for value in row) for row in block)


def parse_block(text: str) -> list[list[Cell]]:
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
            rows.append([parse_cell(part) for part in parts])
        except ValidationError:
            if "|" in line:
                raise
    if not rows:
        raise ValidationError("The clipboard holds no pattern cells.", "PATCH_CELL")
    if len({len(row) for row in rows}) != 1 or len(rows[0]) > 4 or len(rows) > 64:
        raise ValidationError("The clipboard block must have 1-64 rows of 1-4 cells.", "PATCH_CELL")
    return rows
