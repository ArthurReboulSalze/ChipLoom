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
PITCHES = ("C-", "C#", "D-", "D#", "E-", "F-", "F#", "G-", "G#", "A-", "A#", "B-")
NOTES = tuple(f"{pitch}{octave}" for octave in range(1, 4) for pitch in PITCHES)
NOTE_TO_PERIOD = dict(zip(NOTES, PERIODS))
PERIOD_TO_NOTE = dict(zip(PERIODS, NOTES))


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
    period: int = 0
    sample: int = 0
    command: int = 0
    param: int = 0

    @property
    def note(self) -> str | None:
        return PERIOD_TO_NOTE.get(self.period)

    @property
    def effect(self) -> str:
        return f"{self.command:X}{self.param:02X}"

    def text(self) -> str:
        return f"{self.note or '---'} {self.sample:02X} {self.effect}"


EMPTY = Cell()


def cell(note: str | None = None, sample: int = 0, effect: str = "000") -> Cell:
    if note is not None and (not isinstance(note, str) or note not in NOTE_TO_PERIOD):
        raise ValidationError(f"Note inconnue {note!r}; utilise C-1 à B-3, dièses sans tiret "
                              "(exemples : C-3, G#3, A#2 ; notation ProTracker).", "NOTE_UNKNOWN")
    if not isinstance(effect, str) or not re.fullmatch(r"[0-9A-Fa-f]{3}", effect):
        raise ValidationError("Un effet doit contenir trois chiffres hexadécimaux, par exemple 037 ou C20.", "EFFECT_FORMAT")
    return Cell(NOTE_TO_PERIOD.get(note, 0), sample, int(effect[0], 16), int(effect[1:], 16))


@dataclass
class Sample:
    name: str
    pcm: tuple[int, ...]
    volume: int = 40
    finetune: int = 0
    loop_start: int = 0
    loop_length: int = 0
    recipe: dict | None = None


@dataclass
class Pattern:
    name: str = ""
    cells: dict[tuple[int, int], Cell] = field(default_factory=dict)

    def get(self, row: int, channel: int) -> Cell:
        return self.cells.get((row, channel), EMPTY)

    def put(self, row: int, channel: int, value: Cell) -> None:
        require_int(row, "row", 0, 63)
        require_int(channel, "channel", 0, 3)
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


def validate_sample(sample: Sample, index: int = 1) -> None:
    label = f"Sample {index}"
    ascii_field(sample.name, 22, label)
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
    elif sample.loop_start or any(sample.pcm[:2]):
        raise ValidationError(f"{label}: un son sans boucle doit commencer par deux octets nuls.", "SAMPLE_LOOP")


def validate_cell(value: Cell, row: int, channel: int, pattern_index: int,
                 sample_count: int, order_count: int) -> None:
    # No PC panning extensions, pattern loops, pattern delays or destructive EFx
    # in v1. All supported effects are delegated to the reference replay engines.
    simple_commands = {0, 1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12, 13, 15}
    extended_commands = {0, 1, 2, 4, 5, 9, 10, 11, 12, 13}
    where = f"Pattern {pattern_index}, ligne {row}, voie {channel}"
    require_int(row, where, 0, 63)
    require_int(channel, where, 0, 3)
    require_int(value.period, f"{where} période", 0, 4095)
    if value.period and value.period not in PERIOD_TO_NOTE:
        raise ValidationError(f"{where}: période {value.period} hors des 36 notes du profil.", "NOTE_RANGE")
    require_int(value.sample, f"{where} sample", 0, sample_count, "SAMPLE_REF")
    require_int(value.command, f"{where} effet", 0, 15)
    require_int(value.param, f"{where} paramètre", 0, 255)
    if value.command == 14:
        if value.param >> 4 not in extended_commands:
            raise ValidationError(f"{where}: effet {value.effect} non pris en charge par le profil v1.", "EFFECT_UNSUPPORTED")
        if value.param >> 4 == 0 and value.param not in (0, 1):
            raise ValidationError(f"{where}: seul E00/E01 est accepté pour le filtre.", "EFFECT_UNSUPPORTED")
    elif value.command not in simple_commands:
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
    ascii_field(module.title, 20, "Titre MOD")
    if not 1 <= len(module.samples) <= 31:
        raise ValidationError("Le profil accepte de 1 à 31 emplacements de samples.", "SAMPLE_SLOT")
    if not 1 <= len(module.patterns) <= 64:
        raise ValidationError("Le profil M.K. accepte de 1 à 64 patterns.", "PATTERNS")
    if not 1 <= len(module.orders) <= 128:
        raise ValidationError("La liste d'ordres doit contenir de 1 à 128 entrées.", "ORDERS")
    for index, value in enumerate(module.orders):
        require_int(value, f"orders[{index}]", 0, len(module.patterns) - 1, "ORDERS")
    if max(module.orders) != len(module.patterns) - 1:
        raise ValidationError("Le dernier pattern stocké doit apparaître dans la liste d'ordres.", "ORDERS")

    for index, sample in enumerate(module.samples, 1):
        validate_sample(sample, index)

    for pattern_index, pattern in enumerate(module.patterns):
        for (row, channel), value in pattern.cells.items():
            validate_cell(value, row, channel, pattern_index, len(module.samples), len(module.orders))


def playback_plan(module: Module) -> dict:
    """Walk supported flow/timing commands up to the first repeated replay state."""
    validate(module)
    speed, bpm = 6, 125
    order, row = 0, 0
    visited: dict[tuple[int, int, int, int], int] = {}
    timeline = []
    elapsed = 0.0
    for _ in range(250_000):
        pattern_index = module.orders[order]
        pattern = module.patterns[pattern_index]
        jump, next_row = None, None
        for channel in range(4):
            value = pattern.get(row, channel)
            if value.command == 15:
                if value.param < 32:
                    speed = value.param
                else:
                    bpm = value.param
            elif value.command == 11:
                jump = value.param
            elif value.command == 13:
                next_row = (value.param >> 4) * 10 + (value.param & 15)
        # A row that explicitly sets timing has the same replay state regardless
        # of the speed/tempo inherited before entering that row.
        state = (order, row, speed, bpm)
        if state in visited:
            loop_at = visited[state]
            return {
                "duration_seconds": round(elapsed, 9),
                "loop_start_seconds": timeline[loop_at]["seconds"],
                "rows": len(timeline), "timeline": timeline,
            }
        visited[state] = len(timeline)
        timeline.append({
            "seconds": round(elapsed, 9), "order": order, "pattern": pattern_index,
            "row": row, "speed": speed, "bpm": bpm,
        })
        elapsed += speed * 2.5 / bpm
        if jump is not None or next_row is not None:
            order = jump if jump is not None else (order + 1) % len(module.orders)
            row = next_row or 0
        else:
            row += 1
            if row == 64:
                order = (order + 1) % len(module.orders)
                row = 0
    raise ValidationError("Déroulement trop long pour le prototype (250000 lignes maximum).", "RENDER_LIMIT")
