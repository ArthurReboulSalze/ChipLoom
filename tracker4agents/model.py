"""The v1 musical model. Note names use ProTracker's C-1..B-3 convention."""

from __future__ import annotations

from dataclasses import dataclass, field
import re

PROFILE = "protracker-4ch-pal-v1"
PAL_CLOCK = 3_546_895.0
REFERENCE_PERIOD = 428  # C-2, finetune 0; sample playback rate, not musical pitch.
SAMPLE_RATE = PAL_CLOCK / REFERENCE_PERIOD
PERIODS = (
    856, 808, 762, 720, 678, 640, 604, 570, 538, 508, 480, 453,
    428, 404, 381, 360, 339, 320, 302, 285, 269, 254, 240, 226,
    214, 202, 190, 180, 170, 160, 151, 143, 135, 127, 120, 113,
)
# Four-channel MOD signatures the codec reads and writes. ProTracker names 64 patterns as
# the M.K. limit and 100 (patterns 00-99) as the M!K! limit; the 128-entry order list
# could address 128 patterns, but ProTracker 2.3 itself cannot open more than 100.
MOD_SIGNATURES = ("M.K.", "M!K!", "FLT4", "4CHN")
MAX_MK_PATTERNS = 64
MAX_PATTERNS = 100
DEFAULT_RESTART_BYTE = 0x7F
PITCHES = ("C-", "C#", "D-", "D#", "E-", "F-", "F#", "G-", "G#", "A-", "A#", "B-")
NOTES = tuple(f"{pitch}{octave}" for octave in range(1, 4) for pitch in PITCHES)
NOTE_TO_PERIOD = dict(zip(NOTES, PERIODS))
PERIOD_TO_NOTE = dict(zip(PERIODS, NOTES))
# XM notes: numbers 1..96 are C-0..B-7 (C-4 is middle C at relative note 0) and 97 is key off.
# The label C-2 therefore names a different pitch in a MOD (period 428) and in an XM (note 25):
# grid text is always read with the module's format. A Cell stores the Amiga period for a MOD
# and the note number for an XM; the two ranges (113..856 and 1..97) never overlap.
XM_NOTES = tuple(f"{pitch}{octave}" for octave in range(8) for pitch in PITCHES)
XM_NOTE_TO_NUMBER = {name: number for number, name in enumerate(XM_NOTES, 1)}
XM_KEY_OFF = 97
XM_KEY_OFF_NAME = "==="
FORMATS = ("mod", "xm")
MOD_MAX_CHANNELS = 32
MOD_PROFILE_N = "protracker-nch-pal-v1"  # MOD with a channel count other than four
XM_PROFILE = "fasttracker2-xm-v1"
MOD_ROWS = 64
EFFECT_DIGITS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"  # XM effects 0..35 (0-9, A-Z)


class ValidationError(ValueError):
    """A rejected score or operation. `code` is a stable identifier for agents."""

    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        self.code = code


def require_int(value: object, label: str, minimum: int, maximum: int, code: str = "INTEGER_RANGE") -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValidationError(f"{label}: entier attendu dans [{minimum}, {maximum}].", code)
    return value


def ascii_field(value: str, size: int, label: str) -> bytes:
    if not isinstance(value, str):
        raise ValidationError(f"{label}: texte attendu.", "TEXT_TYPE")
    if any(ord(char) < 32 or ord(char) > 126 for char in value):
        raise ValidationError(f"{label}: utilise du texte ASCII imprimable pour ce profil.", "TEXT_ASCII")
    if len(value) > size:
        raise ValidationError(f"{label}: {size} caractères maximum (aucune troncature implicite).", "TEXT_LENGTH")
    return value.encode("ascii").ljust(size, b"\x00")


@dataclass(frozen=True)
class Cell:
    """One pattern cell. `period` is the Amiga period (MOD) or the note number 1..97 (XM);
    `sample` is the sample slot (MOD) or instrument (XM); `volume` is the XM volume-column
    byte and stays 0 in a MOD; `command` is 0..15 in a MOD and 0..35 (0-9, A-Z) in an XM."""

    period: int = 0
    sample: int = 0
    command: int = 0
    param: int = 0
    volume: int = 0

    @property
    def note(self) -> str | None:
        if 0 < self.period < XM_KEY_OFF:
            return XM_NOTES[self.period - 1]
        if self.period == XM_KEY_OFF:
            return XM_KEY_OFF_NAME
        return PERIOD_TO_NOTE.get(self.period)

    @property
    def effect(self) -> str:
        return f"{EFFECT_DIGITS[self.command] if 0 <= self.command < 36 else '?'}{self.param:02X}"

    def text(self) -> str:
        volume = f" {self.volume:02X}" if self.volume else ""
        return f"{self.note or '---'} {self.sample:02X}{volume} {self.effect}"


EMPTY = Cell()


def cell(note: str | None = None, sample: int = 0, effect: str = "000", fmt: str = "mod", volume: int = 0) -> Cell:
    """Build a cell from grid spellings; `fmt` ("mod" or "xm") decides how the note label and the
    effect letter are read. The volume column byte is an XM matter and must be 0 for a MOD."""
    if fmt == "xm":
        if note is not None and (not isinstance(note, str) or (note not in XM_NOTE_TO_NUMBER and note != XM_KEY_OFF_NAME)):
            raise ValidationError(f"Unknown XM note {note!r}; use C-0 to B-7 (sharps without a dash: C#4, A#2) "
                                  "or === for key off.", "NOTE_UNKNOWN")
        if not isinstance(effect, str) or not re.fullmatch(r"[0-9A-Za-z][0-9A-Fa-f]{2}", effect):
            raise ValidationError("An XM effect is a letter or digit (0-9, A-Z) followed by two hexadecimal "
                                  "digits, for example 037, A0F or G40.", "EFFECT_FORMAT")
        number = XM_KEY_OFF if note == XM_KEY_OFF_NAME else XM_NOTE_TO_NUMBER.get(note, 0)
        return Cell(number, sample, EFFECT_DIGITS.index(effect[0].upper()), int(effect[1:], 16), volume)
    if note is not None and (not isinstance(note, str) or note not in NOTE_TO_PERIOD):
        raise ValidationError(f"Note inconnue {note!r}; utilise C-1 à B-3, dièses sans tiret "
                              "(exemples : C-3, G#3, A#2 ; notation ProTracker).", "NOTE_UNKNOWN")
    if not isinstance(effect, str) or not re.fullmatch(r"[0-9A-Fa-f]{3}", effect):
        raise ValidationError("Un effet doit contenir trois chiffres hexadécimaux, par exemple 037 ou C20.", "EFFECT_FORMAT")
    return Cell(NOTE_TO_PERIOD.get(note, 0), sample, int(effect[0], 16), int(effect[1:], 16), volume)


@dataclass
class Sample:
    name: str
    pcm: tuple[int, ...]
    volume: int = 40
    finetune: int = 0
    loop_start: int = 0
    loop_length: int = 0
    recipe: dict | None = None
    # XM-only properties; the defaults are the MOD sample. `bits` is 8 or 16 (pcm values then span
    # -128..127 or -32768..32767), loop points count sample frames, `loop_mode` is "forward" or
    # "pingpong", `panning` 0..255 and `relative_note` -96..95.
    bits: int = 8
    loop_mode: str = "forward"
    panning: int = 128
    relative_note: int = 0


@dataclass
class Pattern:
    """`rows` is 64 in a MOD and 1..256 in an XM. Coordinates are checked against the owning
    module's channel count and the pattern's rows by `validate`; `put` only bounds them to
    the format maxima (256 rows, 32 channels)."""

    name: str = ""
    cells: dict[tuple[int, int], Cell] = field(default_factory=dict)
    rows: int = MOD_ROWS

    def get(self, row: int, channel: int) -> Cell:
        return self.cells.get((row, channel), EMPTY)

    def put(self, row: int, channel: int, value: Cell) -> None:
        require_int(row, "row", 0, 255)
        require_int(channel, "channel", 0, MOD_MAX_CHANNELS - 1)
        if value == EMPTY:
            self.cells.pop((row, channel), None)
        else:
            self.cells[row, channel] = value


@dataclass
class Module:
    title: str
    samples: list[Sample]
    patterns: list[Pattern]
    orders: list[int]
    metadata: dict = field(default_factory=dict)
    channels: int = 4
    format: str = "mod"


def mod_profile(module: Module) -> dict:
    """The optional `metadata["mod"]` block describing MOD file details the model does not
    otherwise carry (signature, restart byte, inactive orders, header oddities)."""
    block = module.metadata.get("mod") if isinstance(module.metadata, dict) else None
    return block if isinstance(block, dict) else {}


def channel_signature(channels: int) -> str:
    """The MOD signature that names a channel count: 6CHN, 8CHN, 10CH ... 32CH."""
    return f"{channels}CHN" if channels < 10 else f"{channels}CH"


def mod_signature(module: Module, profile: dict | None = None) -> str:
    """Signature written on export: the stored one, else M.K. up to 64 patterns, else M!K!.
    A channel count other than four is named by the signature itself (6CHN, 8CHN, 10CH ...)."""
    if module.channels != 4:
        return channel_signature(module.channels)
    stored = (mod_profile(module) if profile is None else profile).get("signature")
    return stored or ("M.K." if len(module.patterns) <= MAX_MK_PATTERNS else "M!K!")


def mod_order_table(module: Module, profile: dict | None = None) -> list[int]:
    """The full 128-entry order table: active orders, then stored inactive values (default 0)."""
    inactive = (mod_profile(module) if profile is None else profile).get("inactive_orders") or {}
    table = list(module.orders)
    for slot in range(len(table), 128):
        table.append(inactive.get(str(slot), 0))
    return table


_MOD_KEYS = {"signature", "restart_byte", "inactive_orders", "title_bytes", "sample_quirks", "import_notes"}
_QUIRK_KEYS = {"finetune_high", "header_loop_words", "unlooped_head", "name_bytes"}
_NOTE_KEYS = {"code", "kind", "message", "slots", "details"}


def _hex_bytes(value: object, size: int, label: str) -> None:
    try:
        ok = isinstance(value, str) and len(bytes.fromhex(value)) == size and value == value.lower()
    except ValueError:
        ok = False
    if not ok:
        raise ValidationError(f"{label}: expected {size} bytes as lowercase hexadecimal.", "MOD_METADATA")


def _slot_key(key: object, low: int, high: int, label: str) -> None:
    if not (isinstance(key, str) and key.isascii() and key.isdecimal() and str(int(key)) == key and low <= int(key) <= high):
        raise ValidationError(f"{label}: invalid slot {key!r} (expected {low} to {high}).", "MOD_METADATA")


def validate_mod_metadata(module: Module) -> None:
    metadata = module.metadata
    if not isinstance(metadata, dict) or "mod" not in metadata:
        return
    block = metadata["mod"]
    if not isinstance(block, dict) or set(block) - _MOD_KEYS:
        raise ValidationError(f"metadata.mod: expected an object with keys among {sorted(_MOD_KEYS)}.", "MOD_METADATA")
    if "signature" in block and block["signature"] not in MOD_SIGNATURES:
        raise ValidationError(f"metadata.mod.signature: expected one of {', '.join(MOD_SIGNATURES)}.", "MOD_METADATA")
    if "restart_byte" in block:
        require_int(block["restart_byte"], "metadata.mod.restart_byte", 0, 255, "MOD_METADATA")
    if "title_bytes" in block:
        _hex_bytes(block["title_bytes"], 20, "metadata.mod.title_bytes")
    inactive = block.get("inactive_orders", {})
    if not isinstance(inactive, dict):
        raise ValidationError("metadata.mod.inactive_orders: expected an object {slot: pattern}.", "MOD_METADATA")
    for key, value in inactive.items():
        _slot_key(key, 0, 127, "metadata.mod.inactive_orders")
        require_int(value, f"metadata.mod.inactive_orders[{key}]", 0, 127, "MOD_METADATA")
    quirks = block.get("sample_quirks", {})
    if not isinstance(quirks, dict):
        raise ValidationError("metadata.mod.sample_quirks: expected an object {slot: details}.", "MOD_METADATA")
    for key, quirk in quirks.items():
        label = f"metadata.mod.sample_quirks[{key}]"
        _slot_key(key, 1, 31, "metadata.mod.sample_quirks")
        if not isinstance(quirk, dict) or set(quirk) - _QUIRK_KEYS:
            raise ValidationError(f"{label}: allowed keys are {sorted(_QUIRK_KEYS)}.", "MOD_METADATA")
        if "finetune_high" in quirk:
            require_int(quirk["finetune_high"], f"{label}.finetune_high", 1, 15, "MOD_METADATA")
        if "unlooped_head" in quirk and quirk["unlooped_head"] is not True:
            raise ValidationError(f"{label}.unlooped_head: expected true.", "MOD_METADATA")
        if "name_bytes" in quirk:
            _hex_bytes(quirk["name_bytes"], 22, f"{label}.name_bytes")
        if "header_loop_words" in quirk:
            words = quirk["header_loop_words"]
            if not isinstance(words, list) or len(words) != 2:
                raise ValidationError(f"{label}.header_loop_words: expected [start, length] in words.", "MOD_METADATA")
            for word in words:
                require_int(word, f"{label}.header_loop_words", 0, 65535, "MOD_METADATA")
    notes = block.get("import_notes", [])
    if not isinstance(notes, list):
        raise ValidationError("metadata.mod.import_notes: expected a list.", "MOD_METADATA")
    for note in notes:
        if (not isinstance(note, dict) or set(note) - _NOTE_KEYS or not {"code", "kind", "message"} <= set(note)
                or note["kind"] not in ("preserved", "converted")
                or not all(isinstance(note[key], str) for key in ("code", "message"))):
            raise ValidationError("metadata.mod.import_notes: expected notes with code, kind and message.", "MOD_METADATA")
        if "slots" in note and not (isinstance(note["slots"], list) and all(type(slot) is int and 1 <= slot <= 31 for slot in note["slots"])):
            raise ValidationError("metadata.mod.import_notes: slots must list sample slots 1 to 31.", "MOD_METADATA")
        if "details" in note and not isinstance(note["details"], dict):
            raise ValidationError("metadata.mod.import_notes: details must be an object.", "MOD_METADATA")


def validate_sample(sample: Sample, index: int = 1, quirk: dict | None = None) -> None:
    label = f"Sample {index}"
    quirk = quirk or {}
    ascii_field(sample.name, 22, label)
    if (sample.bits, sample.loop_mode, sample.panning, sample.relative_note) != (8, "forward", 128, 0):
        raise ValidationError(f"{label}: bits, loop_mode, panning and relative_note are XM-only sample "
                              "properties; a MOD sample is 8-bit, forward-looped, centred and not transposed.",
                              "MOD_XM_FIELD")
    require_int(sample.volume, f"{label} volume", 0, 64)
    require_int(sample.finetune, f"{label} finetune", -8, 7)
    length = len(sample.pcm)
    if length % 2 or length > 65_534 or length in (1, 2):
        raise ValidationError(f"{label}: longueur paire, de 4 à 65534 octets, ou sample vide.", "SAMPLE_LENGTH")
    if any(type(value) is not int or not -128 <= value <= 127 for value in sample.pcm):
        raise ValidationError(f"{label}: valeurs PCM signées 8 bits attendues (-128 à 127).", "SAMPLE_PCM")
    require_int(sample.loop_start, f"{label} loop_start", 0, length)
    require_int(sample.loop_length, f"{label} loop_length", 0, length)
    if sample.loop_start % 2 or sample.loop_length % 2:
        raise ValidationError(f"{label}: les points de boucle doivent être alignés sur deux octets.", "SAMPLE_LOOP")
    if sample.loop_length:
        if sample.loop_length < 4 or sample.loop_start + sample.loop_length > length:
            raise ValidationError(f"{label}: boucle trop courte ou en dehors du sample.", "SAMPLE_LOOP")
    elif sample.loop_start or (any(sample.pcm[:2]) and not quirk.get("unlooped_head")):
        # ProTracker keeps replaying the first word of an unlooped sample; libxmp and
        # libopenmpt stop instead. Only an imported file may carry such a head, flagged.
        raise ValidationError(f"{label}: un son sans boucle doit commencer par deux octets nuls.", "SAMPLE_LOOP")
    words = quirk.get("header_loop_words")
    if words is not None and length and words[1] > 1:
        raise ValidationError(f"{label}: header_loop_words describes a loop; use loop_start/loop_length.", "MOD_METADATA")


# Commands whose behaviour the playback plan and the replay engines agree on. 8xx (PC
# panning), E3x/E7x/E8x and EFx (invert loop, which rewrites sample data and on which libxmp
# and libopenmpt disagree) stay outside. E0x is the Amiga filter: libxmp reads only the lowest
# bit of x (like ProTracker), libopenmpt ignores it, so every x is accepted and kept as is.
SIMPLE_COMMANDS = frozenset({0, 1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12, 13, 15})
EXTENDED_COMMANDS = frozenset({0, 1, 2, 4, 5, 6, 9, 10, 11, 12, 13, 14})


def validate_cell(value: Cell, row: int, channel: int, pattern_index: int,
                 sample_count: int, order_count: int, channels: int = 4, rows: int = MOD_ROWS) -> None:
    where = f"Pattern {pattern_index}, ligne {row}, voie {channel}"
    require_int(row, where, 0, rows - 1)
    require_int(channel, where, 0, channels - 1)
    if value.volume:
        raise ValidationError(f"{where}: the volume column is an XM feature; a MOD cell has none.", "MOD_XM_FIELD")
    require_int(value.period, f"{where} période", 0, 4095)
    if value.period and value.period not in PERIOD_TO_NOTE:
        raise ValidationError(f"{where}: période {value.period} hors des 36 notes du profil.", "NOTE_RANGE")
    require_int(value.sample, f"{where} sample", 0, sample_count, "SAMPLE_REF")
    require_int(value.command, f"{where} effet", 0, 15)
    require_int(value.param, f"{where} paramètre", 0, 255)
    if value.command == 14:
        if value.param >> 4 not in EXTENDED_COMMANDS:
            raise ValidationError(f"{where}: effet {value.effect} non pris en charge par le profil v1.", "EFFECT_UNSUPPORTED")
    elif value.command not in SIMPLE_COMMANDS:
        raise ValidationError(f"{where}: effet {value.effect} hors du profil ProTracker v1.", "EFFECT_UNSUPPORTED")
    if value.command == 12 and value.param > 64:
        raise ValidationError(f"{where}: volume Cxx supérieur à 40 hexadécimal.", "EFFECT_PARAM")
    if value.command == 11 and value.param >= order_count:
        raise ValidationError(f"{where}: Bxx pointe en dehors de la liste d'ordres.", "FLOW")
    if value.command == 13:
        tens, units = value.param >> 4, value.param & 15
        if units > 9 or tens > 6 or tens * 10 + units > 63:
            raise ValidationError(f"{where}: Dxx attend une ligne décimale codée BCD de 00 à 63.", "FLOW")
    if value.command == 15 and value.param in (0, 32):
        raise ValidationError(f"{where}: F00 et F20 ont un comportement ambigu et sont exclus.", "TIMING")


def validate(module: Module) -> None:
    """Validate a module against the profile of its format (MOD here, XM in `xm.validate_xm`)."""
    if module.format == "xm":
        from .xm import validate_xm
        validate_xm(module)
        return
    _validate_mod(module)


def _validate_mod(module: Module) -> None:
    if module.format != "mod":
        raise ValidationError(f"Unknown module format {module.format!r}; expected one of {', '.join(FORMATS)}.",
                              "FORMAT")
    require_int(module.channels, "channels", 2, MOD_MAX_CHANNELS, "CHANNELS")
    ascii_field(module.title, 20, "Titre MOD")
    if not 1 <= len(module.samples) <= 31:
        raise ValidationError("Le profil accepte de 1 à 31 emplacements de samples.", "SAMPLE_SLOT")
    if not 1 <= len(module.patterns) <= MAX_PATTERNS:
        raise ValidationError(f"The profile accepts 1 to {MAX_PATTERNS} patterns "
                              f"(M.K. up to {MAX_MK_PATTERNS}, M!K! above).", "PATTERNS")
    if not 1 <= len(module.orders) <= 128:
        raise ValidationError("La liste d'ordres doit contenir de 1 à 128 entrées.", "ORDERS")
    for index, value in enumerate(module.orders):
        require_int(value, f"orders[{index}]", 0, len(module.patterns) - 1, "ORDERS")
    validate_mod_metadata(module)
    profile = mod_profile(module)
    if module.channels != 4 and "signature" in profile:
        raise ValidationError("metadata.mod.signature only applies to four-channel modules; other channel "
                              "counts are named by their own signature (6CHN, 8CHN, 10CH ...).", "MOD_METADATA")
    inactive = profile.get("inactive_orders", {})
    # Players count stored patterns from the highest order entry, active or not, plus one;
    # an inactive entry may also dangle past the stored patterns.
    last = len(module.patterns) - 1
    if last not in (max(module.orders), max([*module.orders, *inactive.values()])):
        raise ValidationError("Le dernier pattern stocké doit apparaître dans la liste d'ordres.", "ORDERS")
    if (module.channels == 4 and len(module.patterns) > MAX_MK_PATTERNS
            and profile.get("signature", "M!K!") != "M!K!"):
        raise ValidationError(f"More than {MAX_MK_PATTERNS} patterns requires the M!K! signature.", "PATTERNS")

    quirks = profile.get("sample_quirks", {})
    for index, sample in enumerate(module.samples, 1):
        validate_sample(sample, index, quirks.get(str(index)))

    for pattern_index, pattern in enumerate(module.patterns):
        if pattern.rows != MOD_ROWS:
            raise ValidationError(f"Pattern {pattern_index}: a MOD pattern always has {MOD_ROWS} rows.", "PATTERNS")
        for (row, channel), value in pattern.cells.items():
            validate_cell(value, row, channel, pattern_index, len(module.samples), len(module.orders),
                          module.channels)


def xm_profile(module: Module) -> dict:
    """The `metadata["xm"]` block of an XM module (header values, instruments, import notes)."""
    block = module.metadata.get("xm") if isinstance(module.metadata, dict) else None
    return block if isinstance(block, dict) else {}


def xm_has_ft2_quirks(tracker_name: str) -> bool:
    """libxmp keeps FastTracker II's pattern-loop jump bug only for files that claim to come from
    FastTracker II or OpenMPT; the playback plan follows the same rule."""
    return tracker_name.startswith(("FastTracker v2.00", "Fasttracker II clone", "OpenMPT "))


def playback_plan(module: Module) -> dict:
    """Walk flow/timing commands up to the first repeated replay state.

    Row flow follows libxmp, the engine of the real-time view and of the trace check:
    Fxx speed/tempo; Bxx/Dxx jumps (a Bxx resets the break row of the Dxx of lower channels);
    EEx pattern delay (the row lasts (x+1) times longer, the last EEx on the row wins);
    E6x pattern loops with one loop start and one counter per channel, kept across patterns
    and orders (a Bxx/Dxx on the same row cancels a loop jump; the last E6x loop wins).
    Each timeline entry is one visit of a row, so loop passes appear once per pass.

    ProTracker mode (MOD): a break on a delayed row skips the row it lands on, and the
    restart byte is not a loop target (ProTracker ignores it). XM: the song starts at the
    header's default speed and tempo, the end of the order list returns to the header's restart
    position, patterns have their own row count, and for files that claim FastTracker II an
    E60 also sets the row the next order change starts on (the "E60 bug" libxmp reproduces).
    """
    validate(module)
    xm = module.format == "xm"
    channels, count = module.channels, len(module.orders)
    speed, bpm, restart, ft2 = 6, 125, 0, False
    if xm:
        info = xm_profile(module)
        speed, bpm = info.get("default_speed", 6), info.get("default_bpm", 125)
        restart = info.get("restart_position", 0) if info.get("restart_position", 0) < count else 0
        ft2 = xm_has_ft2_quirks(info.get("tracker_name", "FastTracker v2.00"))
    order, row = 0, 0
    loops: tuple[tuple[int, int], ...] = ((0, 0),) * channels  # per channel: (loop start row, loops left)
    jumpline = 0  # row the next order change starts on; only an XM E60 can leave it nonzero
    visited: dict[tuple, int] = {}
    timeline = []
    elapsed = 0.0

    seen_orders: set[int] = set()

    def following(current: int) -> int:
        """The order after `current`; at the end of the list libxmp goes to the restart position only
        if that order was already played in this pass, else back to the first order."""
        return current + 1 if current + 1 < count else (restart if restart in seen_orders else 0)

    def enter(new_order: int, line: int) -> tuple[int, int]:
        return new_order, line if line < module.patterns[module.orders[new_order]].rows else 0

    for _ in range(250_000):
        pattern_index = module.orders[order]
        pattern = module.patterns[pattern_index]
        seen_orders.add(order)
        jump, broken, loop_row, delay = None, False, None, 0
        line = jumpline
        new_loops = list(loops)
        for channel in range(channels):
            value = pattern.get(row, channel)
            if value.command == 15:
                if value.param < 32:
                    speed = value.param
                else:
                    bpm = value.param
            elif value.command == 11:
                jump, line, broken = value.param, 0, True
            elif value.command == 13:
                line, broken = (value.param >> 4) * 10 + (value.param & 15), True
            elif value.command == 14 and value.param >> 4 == 6:
                start, left = new_loops[channel]
                if value.param & 15 == 0:
                    new_loops[channel] = (row, left)
                    if ft2:
                        line = row
                else:
                    left = value.param & 15 if left == 0 else left - 1
                    new_loops[channel] = (start, left)
                    if left:
                        loop_row = start
            elif value.command == 14 and value.param >> 4 == 14:
                delay = value.param & 15
        # A row that explicitly sets timing has the same replay state regardless
        # of the speed/tempo inherited before entering that row.
        state = (order, row, speed, bpm, loops, jumpline)
        if state in visited:
            loop_at = visited[state]
            return {
                "duration_seconds": round(elapsed, 9),
                "loop_start_seconds": timeline[loop_at]["seconds"],
                "rows": len(timeline), "timeline": timeline,
            }
        visited[state] = len(timeline)
        entry = {
            "seconds": round(elapsed, 9), "order": order, "pattern": pattern_index,
            "row": row, "speed": speed, "bpm": bpm,
        }
        if delay:
            entry["delay"] = delay
        timeline.append(entry)
        elapsed += speed * 2.5 / bpm * (1 + delay)
        loops = tuple(new_loops)
        jumpline = line
        if broken:
            order, row = enter(jump if jump is not None else following(order), line)
            jumpline = 0
            if delay and not xm:
                row += 1
                if row >= module.patterns[module.orders[order]].rows:
                    order, row = following(order), 0
        elif loop_row is not None:
            row = loop_row
            if row >= pattern.rows:  # a stale loop start past the end of this pattern ends it
                order, row = enter(following(order), jumpline)
                jumpline = 0
        else:
            row += 1
            if row >= pattern.rows:
                order, row = enter(following(order), jumpline)
                jumpline = 0
    raise ValidationError("Déroulement trop long pour le prototype (250000 lignes maximum).", "RENDER_LIMIT")
