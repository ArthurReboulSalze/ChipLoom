"""Batch edit operations shared by the CLI, the desktop window and live sessions.

A patch is a JSON list of operations applied to a copy of the module and
validated as one transaction: either every operation applies or none does.
Indices for patterns, orders, rows and channels are zero-based; sample slots
are 1-31 (instruments 1-128 in an XM) as in the score. Cells use the compact grid text
of `inspect --grid`: `NOTE SS EEE` for a MOD, `NOTE II VV EEE` for an XM (VV is the raw
volume-column byte in hexadecimal, `--` when empty). Rows hold one cell per channel.
"""

from __future__ import annotations

import copy
import dataclasses
import re
from pathlib import Path

from .model import (
    EMPTY, MAX_PATTERNS, NOTE_TO_PERIOD, NOTES, XM_KEY_OFF, XM_NOTES, Cell, Module, Pattern, Sample, ValidationError, cell,
    playback_plan, require_int, xm_profile,
)

XM_HEADER_KEYS = ("restart_position", "default_speed", "default_bpm", "frequency_table")

EMPTY_TOKENS = {"", "---", "...", "--", "..", "000"}
CELL_TEXT = re.compile(r"^\s*(\S{3})(?:\s+(\S{2}))?(?:\s+(\S{3}))?\s*$")
XM_CELL_TEXT = re.compile(r"^\s*(\S{3})(?:\s+(\S{2}))?(?:\s+(\S{2}))?(?:\s+(\S{3}))?\s*$")


def cell_text(value: Cell, fmt: str = "mod") -> str:
    """Grid spelling: note or ---, sample in hex or --, effect in hex or ....

    An XM cell adds the volume column between instrument and effect: `C-4 01 40 A0F`
    (raw hexadecimal byte, `--` when empty); its effect letters run 0-9 then A-Z."""
    if fmt == "xm":
        if value == EMPTY:
            return "--- -- -- ..."
        sample = f"{value.sample:02X}" if value.sample else "--"
        volume = f"{value.volume:02X}" if value.volume else "--"
        effect = value.effect if value.command or value.param else "..."
        return f"{value.note or '---'} {sample} {volume} {effect}"
    if value == EMPTY:
        return "--- -- ..."
    sample = f"{value.sample:02X}" if value.sample else "--"
    effect = value.effect if value.command or value.param else "..."
    return f"{value.note or '---'} {sample} {effect}"


NOTE_LIKE = re.compile(r"[A-Ga-g][-#b]*-?\d+")


def _note_hint(text: str, xm: bool) -> str:
    """Extra advice when the first token looks like a note but is not spelled with three characters."""
    first = text.split()[0] if text.split() else ""
    if len(first) == 3 or not NOTE_LIKE.fullmatch(first):
        return ""
    if xm:
        return (f" The note {first!r} is malformed: XM notes are three characters, C-4 for a natural and C#4 "
                "for a sharp (no dash), C-0 to B-7, or === for key off.")
    return (f" The note {first!r} is malformed: MOD notes are three characters, C-2 for a natural and C#2 "
            "for a sharp (no dash), C-1 to B-3.")


def parse_cell(text: object, fmt: str = "mod") -> Cell:
    """Parse `C-2 01 C20`, `--- -- ...`, `G#2 0A`, `C-3` or an empty string.

    With `fmt="xm"`: `C-4 01 40 A0F`, `=== -- -- ...`, `E-4 02 C8`, `C-4 01 40` or `C-4 01 A0F`
    (a two-character third token is the volume column, a three-character one the effect)."""
    if text is None:
        return EMPTY
    xm = fmt == "xm"
    example = "C-4 01 40 A0F" if xm else "C-2 01 C20"
    if not isinstance(text, str):
        raise ValidationError(f"A cell must be grid text such as '{example}' or '--- -- ...'.", "PATCH_CELL")
    if not text.strip():
        return EMPTY
    match = (XM_CELL_TEXT if xm else CELL_TEXT).match(text)
    if not match:
        raise ValidationError(f"Unreadable cell {text!r}; expected '{'NOTE II VV EEE' if xm else 'NOTE SS EEE'}', "
                              f"e.g. '{example}'.{_note_hint(text, xm)}", "PATCH_CELL")
    volume_value = 0
    if xm:
        note, sample, volume, effect = match.groups()
        try:
            volume_value = 0 if volume is None or volume in EMPTY_TOKENS else int(volume, 16)
        except ValueError:
            raise ValidationError(f"Cell {text!r}: the volume column must be two hexadecimal digits or --.",
                                  "PATCH_CELL") from None
    else:
        note, sample, effect = match.groups()
    note = None if note in EMPTY_TOKENS else note.upper()
    try:
        sample_value = 0 if sample is None or sample in EMPTY_TOKENS else int(sample, 16)
    except ValueError:
        raise ValidationError(f"Cell {text!r}: the sample must be two hexadecimal digits or --.", "PATCH_CELL") from None
    effect = "000" if effect is None or effect in EMPTY_TOKENS else effect
    return cell(note, sample_value, effect, fmt, volume_value)


def row_cells(text: object, channels: int = 4, fmt: str = "mod") -> list[Cell]:
    """Parse one grid row: `channels` cells separated by '|', optionally prefixed by 'NN |'."""
    words = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 8: "eight"}.get(channels, str(channels))
    if not isinstance(text, str):
        raise ValidationError(f"A grid row must be text with {words} cells separated by '|'.", "PATCH_CELL")
    parts = [part.strip() for part in text.strip().strip("|").split("|")]
    if len(parts) == channels + 1 and re.fullmatch(r"[0-9A-Fa-f]{2}", parts[0]):
        parts = parts[1:]
    if len(parts) != channels:
        raise ValidationError(f"Grid row {text!r}: expected {words} cells separated by '|'.", "PATCH_CELL")
    return [parse_cell(part, fmt) for part in parts]


def pattern_grid(module: Module, pattern: int, start: int = 0, rows: int | None = None) -> list[str]:
    """Readable rows such as `10 | C-2 01 ... | --- -- ... | E-3 05 C20 | --- -- ...` (one cell per
    channel); `rows` defaults to the rest of the pattern (64 rows in a MOD, up to 256 in an XM)."""
    require_int(pattern, "pattern", 0, len(module.patterns) - 1)
    selected = module.patterns[pattern]
    require_int(start, "row", 0, selected.rows - 1)
    rows = selected.rows - start if rows is None else rows
    require_int(rows, "rows", 1, selected.rows - start)
    return [f"{row:02X} | " + " | ".join(cell_text(selected.get(row, channel), module.format)
                                         for channel in range(module.channels))
            for row in range(start, start + rows)]


# --- operations -----------------------------------------------------------------

def _fields(op: dict, required: set[str], optional: set[str]) -> dict:
    unknown = set(op) - required - optional - {"op"}
    if unknown:
        raise ValidationError(f"unknown fields {sorted(unknown)}.", "UNKNOWN_FIELD")
    missing = required - set(op)
    if missing:
        raise ValidationError(f"missing fields {sorted(missing)}.", "PATCH_FIELD")
    return op


def _pattern(module: Module, value: object, label: str = "pattern") -> Pattern:
    return module.patterns[require_int(value, label, 0, len(module.patterns) - 1)]


def _block(op: dict, module: Module, pattern: Pattern) -> tuple[int, int, int, int]:
    row, rows = op.get("row", 0), op.get("rows", 1)
    channel, channels = op.get("channel", 0), op.get("channels", 1)
    require_int(row, "row", 0, pattern.rows - 1)
    require_int(rows, "rows", 1, pattern.rows - row)
    require_int(channel, "channel", 0, module.channels - 1)
    require_int(channels, "channels", 1, module.channels - channel)
    return row, rows, channel, channels


def _read_block(pattern: Pattern, row: int, rows: int, channel: int, channels: int) -> list[list[Cell]]:
    return [[pattern.get(row + r, channel + c) for c in range(channels)] for r in range(rows)]


def _write_block(module: Module, pattern: Pattern, row: int, channel: int, block: list[list[Cell]]) -> None:
    if row + len(block) > pattern.rows or channel + len(block[0]) > module.channels:
        raise ValidationError(f"The destination block goes past row {pattern.rows - 1} or channel "
                              f"{module.channels - 1}.", "PATCH_BOUNDS")
    for r, values in enumerate(block):
        for c, value in enumerate(values):
            pattern.put(row + r, channel + c, value)


BLOCK = {"pattern", "row", "rows", "channel", "channels"}


def _set(module: Module, op: dict) -> dict:
    _fields(op, {"pattern", "row", "channel"}, {"note", "sample", "effect", "cell", "volume"})
    pattern = _pattern(module, op["pattern"])
    require_int(op["row"], "row", 0, pattern.rows - 1)
    require_int(op["channel"], "channel", 0, module.channels - 1)
    if "cell" in op:
        if any(key in op for key in ("note", "sample", "effect", "volume")):
            raise ValidationError("Use either 'cell' or note/sample/effect, not both.", "PATCH_FIELD")
        value = parse_cell(op["cell"], module.format)
    else:
        old = pattern.get(op["row"], op["channel"])
        note = op["note"] if "note" in op else old.note
        if note in EMPTY_TOKENS:
            note = None
        sample = op.get("sample", old.sample)
        require_int(sample, "sample", 0, 128 if module.format == "xm" else 31)
        effect = op.get("effect", old.effect)
        effect = "000" if effect in (None, "...") else effect
        volume = op.get("volume", old.volume)
        value = cell(note, sample, effect, module.format, require_int(volume, "volume", 0, 255))
    pattern.put(op["row"], op["channel"], value)
    return {}


def _write(module: Module, op: dict) -> dict:
    """Write consecutive cells down one channel, or whole grid rows across all channels."""
    _fields(op, {"pattern"}, {"row", "channel", "cells", "lines", "step"})
    pattern = _pattern(module, op["pattern"])
    row, step = op.get("row", 0), op.get("step", 1)
    require_int(row, "row", 0, pattern.rows - 1)
    require_int(step, "step", 1, pattern.rows)
    if ("cells" in op) == ("lines" in op):
        raise ValidationError("Provide exactly one of 'cells' (one channel) or 'lines' (grid rows).", "PATCH_FIELD")
    values = op.get("cells", op.get("lines"))
    if not isinstance(values, list) or not values:
        raise ValidationError("'cells'/'lines' must be a non-empty list.", "PATCH_FIELD")
    if row + (len(values) - 1) * step > pattern.rows - 1:
        raise ValidationError(f"The written rows go past row {pattern.rows - 1}.", "PATCH_BOUNDS")
    if "cells" in op:
        channel = op.get("channel", 0)
        require_int(channel, "channel", 0, module.channels - 1)
        for index, text in enumerate(values):
            pattern.put(row + index * step, channel, parse_cell(text, module.format))
    else:
        if "channel" in op:
            words = "the four" if module.channels == 4 else f"all {module.channels}"
            raise ValidationError(f"'lines' always covers {words} channels; remove 'channel'.", "PATCH_FIELD")
        for index, text in enumerate(values):
            for channel, value in enumerate(row_cells(text, module.channels, module.format)):
                pattern.put(row + index * step, channel, value)
    return {}


def _clear(module: Module, op: dict) -> dict:
    _fields(op, {"pattern"}, BLOCK - {"pattern"})
    pattern = _pattern(module, op["pattern"])
    row, rows, channel, channels = _block(op, module, pattern)
    _write_block(module, pattern, row, channel, [[EMPTY] * channels for _ in range(rows)])
    return {}


def _copy_or_move(module: Module, op: dict, move: bool) -> dict:
    _fields(op, {"pattern"}, BLOCK - {"pattern"} | {"to_pattern", "to_row", "to_channel"})
    source = _pattern(module, op["pattern"])
    row, rows, channel, channels = _block(op, module, source)
    target = _pattern(module, op.get("to_pattern", op["pattern"]), "to_pattern")
    to_row, to_channel = op.get("to_row", row), op.get("to_channel", channel)
    require_int(to_row, "to_row", 0, target.rows - 1)
    require_int(to_channel, "to_channel", 0, module.channels - 1)
    block = _read_block(source, row, rows, channel, channels)
    if move:
        _write_block(module, source, row, channel, [[EMPTY] * channels for _ in range(rows)])
    _write_block(module, target, to_row, to_channel, block)
    return {}


def _transpose(module: Module, op: dict) -> dict:
    _fields(op, {"pattern", "semitones"}, BLOCK - {"pattern"})
    pattern = _pattern(module, op["pattern"])
    xm = module.format == "xm"
    semitones = require_int(op["semitones"], "semitones", -95 if xm else -35, 95 if xm else 35)
    defaults = {"rows": pattern.rows - op.get("row", 0), "channels": 1}
    row, rows, channel, channels = _block({**defaults, **op}, module, pattern)
    for r in range(row, row + rows):
        for c in range(channel, channel + channels):
            old = pattern.get(r, c)
            if xm:
                if old.period and old.period != XM_KEY_OFF:
                    target = old.period - 1 + semitones
                    if not 0 <= target < len(XM_NOTES):
                        raise ValidationError(f"Transposing {old.note} by {semitones} leaves C-0..B-7.", "NOTE_RANGE")
                    pattern.put(r, c, Cell(target + 1, old.sample, old.command, old.param, old.volume))
            elif old.note:
                target = NOTES.index(old.note) + semitones
                if not 0 <= target < len(NOTES):
                    raise ValidationError(f"Transposing {old.note} by {semitones} leaves C-1..B-3.", "NOTE_RANGE")
                pattern.put(r, c, Cell(NOTE_TO_PERIOD[NOTES[target]], old.sample, old.command, old.param))
    return {}


def _add_pattern(module: Module, op: dict) -> dict:
    _fields(op, set(), {"copy_of", "name", "insert_order", "length"})
    limit = 256 if module.format == "xm" else MAX_PATTERNS
    if len(module.patterns) >= limit:
        raise ValidationError(f"The profile holds at most {limit} patterns.", "PATTERNS")
    if "copy_of" in op:
        if "length" in op:
            raise ValidationError("A copied pattern keeps its length; remove 'length'.", "PATCH_FIELD")
        new = copy.deepcopy(_pattern(module, op["copy_of"], "copy_of"))
    else:
        new = Pattern()
        if "length" in op:
            if module.format != "xm":
                raise ValidationError("A MOD pattern always has 64 rows; 'length' is for XM modules.", "PATCH_FIELD")
            new.rows = require_int(op["length"], "length", 1, 256, "PATTERNS")
    index = len(module.patterns)
    new.name = op.get("name", f"Pattern {index:02X}" if "copy_of" not in op else new.name)
    if not isinstance(new.name, str):
        raise ValidationError("name: text expected.", "PATCH_FIELD")
    module.patterns.append(new)
    at = op.get("insert_order", "end")
    if at is not None:
        position = len(module.orders) if at == "end" else require_int(at, "insert_order", 0, len(module.orders))
        module.orders.insert(position, index)
        return {"pattern": index, "order": position}
    return {"pattern": index}


def _remove_pattern(module: Module, op: dict) -> dict:
    _fields(op, {"pattern"}, set())
    index = require_int(op["pattern"], "pattern", 0, len(module.patterns) - 1)
    if index in module.orders:
        raise ValidationError(f"Pattern {index} is still used by the order list; remove those orders first.", "ORDERS")
    if len(module.patterns) == 1:
        raise ValidationError("A module keeps at least one pattern.", "PATTERNS")
    del module.patterns[index]
    module.orders[:] = [value - 1 if value > index else value for value in module.orders]
    return {}


def _rename_pattern(module: Module, op: dict) -> dict:
    _fields(op, {"pattern", "name"}, set())
    if not isinstance(op["name"], str) or len(op["name"]) > 64:
        raise ValidationError("name: text of at most 64 characters expected.", "PATCH_FIELD")
    _pattern(module, op["pattern"]).name = op["name"]
    return {}


def _set_orders(module: Module, op: dict) -> dict:
    _fields(op, {"orders"}, set())
    if not isinstance(op["orders"], list):
        raise ValidationError("orders: list expected.", "ORDERS")
    module.orders[:] = op["orders"]
    return {}


def _insert_order(module: Module, op: dict) -> dict:
    _fields(op, {"pattern"}, {"at"})
    require_int(op["pattern"], "pattern", 0, len(module.patterns) - 1)
    at = op.get("at", len(module.orders))
    require_int(at, "at", 0, len(module.orders))
    module.orders.insert(at, op["pattern"])
    return {"order": at}


def _remove_order(module: Module, op: dict) -> dict:
    _fields(op, {"at"}, set())
    require_int(op["at"], "at", 0, len(module.orders) - 1)
    del module.orders[op["at"]]
    return {}


def _move_order(module: Module, op: dict) -> dict:
    _fields(op, {"at", "to"}, set())
    require_int(op["at"], "at", 0, len(module.orders) - 1)
    require_int(op["to"], "to", 0, len(module.orders) - 1)
    module.orders.insert(op["to"], module.orders.pop(op["at"]))
    return {}


def _title(module: Module, op: dict) -> dict:
    _fields(op, {"title"}, set())
    module.title = op["title"]
    return {}


def set_initial_timing(module: Module, bpm: int, speed: int) -> None:
    """Write Fxx speed/BPM on the first played row, reusing Fxx or empty effect columns."""
    require_int(bpm, "tempo", 33, 255)
    require_int(speed, "vitesse", 1, 31)
    pattern = module.patterns[module.orders[0]]
    available = [ch for ch in range(module.channels) if pattern.get(0, ch).command == 15]
    available += [ch for ch in range(module.channels) if ch not in available and pattern.get(0, ch).effect == "000"]
    if len(available) < 2:
        raise ValidationError("Il faut deux colonnes d'effet libres ou Fxx sur la première ligne pour fixer tempo et "
                              "vitesse sans effacer d'autres effets.", "TIMING")
    for channel in range(module.channels):
        old = pattern.get(0, channel)
        if old.command == 15:
            pattern.put(0, channel, Cell(old.period, old.sample, 0, 0, old.volume))
    for channel, parameter in zip(available[:2], (speed, bpm)):
        old = pattern.get(0, channel)
        pattern.put(0, channel, Cell(old.period, old.sample, 15, parameter, old.volume))
    if isinstance(module.metadata.get("timing"), dict):
        module.metadata["timing"].update(bpm=bpm, speed=speed)
    if module.format == "xm" and isinstance(module.metadata.get("xm"), dict):
        # The header defaults start the replay before row 0 is read: keep them equal to the Fxx just written.
        module.metadata["xm"].update(default_speed=speed, default_bpm=bpm)


def _timing(module: Module, op: dict) -> dict:
    """Set the initial BPM and/or speed; the one left out keeps its value on the first played row."""
    _fields(op, set(), {"bpm", "speed"})
    if "bpm" not in op and "speed" not in op:
        raise ValidationError("give bpm, speed or both.", "PATCH_FIELD")
    if "bpm" not in op or "speed" not in op:
        first = playback_plan(module)["timeline"][0]
        op = {"bpm": first["bpm"], "speed": first["speed"], **op}
    set_initial_timing(module, op["bpm"], op["speed"])
    return {"bpm": op["bpm"], "speed": op["speed"]}


def _sample(module: Module, op: dict) -> dict:
    _fields(op, {"slot"}, {"volume", "finetune", "name", "panning", "relative_note", "loop_mode"})
    slot = require_int(op["slot"], "slot", 1, len(module.samples))
    sample = module.samples[slot - 1]
    xm = module.format == "xm"
    for key in ("panning", "relative_note", "loop_mode"):
        if key in op and not xm:
            raise ValidationError(f"'{key}' is an XM sample property.", "MOD_XM_FIELD")
    if "volume" in op:
        sample.volume = require_int(op["volume"], "volume", 0, 64)
    if "finetune" in op:
        sample.finetune = require_int(op["finetune"], "finetune", -128 if xm else -8, 127 if xm else 7)
    if "name" in op:
        sample.name = op["name"]
    if "panning" in op:
        sample.panning = require_int(op["panning"], "panning", 0, 255)
    if "relative_note" in op:
        sample.relative_note = require_int(op["relative_note"], "relative_note", -96, 95)
    if "loop_mode" in op:
        if op["loop_mode"] not in ("forward", "pingpong"):
            raise ValidationError("loop_mode: 'forward' or 'pingpong' expected.", "PATCH_FIELD")
        sample.loop_mode = op["loop_mode"]
    return {}


def _library_sample(module: Module, op: dict) -> dict:
    _fields(op, {"id"}, {"library", "slot", "replace", "adapt"})
    from .sample_library import DEFAULT_LIBRARY, SampleLibrary
    candidate, info = SampleLibrary(Path(op.get("library", DEFAULT_LIBRARY))).insert(
        module, op["id"], op.get("slot"), bool(op.get("replace", False)), bool(op.get("adapt", False)))
    module.__dict__.update(candidate.__dict__)
    return info


def _recipe_sample(module: Module, op: dict) -> dict:
    """Insert a created sample (a recipe) like `library_sample` inserts a library one."""
    _fields(op, {"name", "recipe"}, {"slot", "volume", "finetune", "replace", "role", "match", "library"})
    from .synth_tools import insert_recipe, resolve_reference
    match = op.get("match", "defaults")
    if "library" in op and match != "library":
        raise ValidationError("'library' is only used with \"match\": \"library\".", "PATCH_FIELD")
    reference = None if op.get("volume") is not None else resolve_reference(match, op.get("library"))
    return insert_recipe(module, op["name"], op["recipe"], op.get("slot"), op.get("volume"),
                         op.get("finetune", 0), op.get("replace", False), op.get("role"), reference)


# --- XM structure ---------------------------------------------------------------------------------------

def _pattern_length(module: Module, op: dict) -> dict:
    """Resize an XM pattern (1-256 rows). Cutting rows that hold notes or effects needs `truncate: true`."""
    _fields(op, {"pattern", "rows"}, {"truncate"})
    index = require_int(op["pattern"], "pattern", 0, len(module.patterns) - 1, "PATTERNS")
    rows = require_int(op["rows"], "rows", 1, 256, "PATTERNS")
    truncate = op.get("truncate", False)
    if type(truncate) is not bool:
        raise ValidationError("truncate must be true or false.", "PATCH_FIELD")
    pattern = module.patterns[index]
    lost = sorted(key for key in pattern.cells if key[0] >= rows)
    if lost and not truncate:
        first, last = lost[0][0], lost[-1][0]
        raise ValidationError(f"Pattern {index} holds {len(lost)} non-empty cell(s) on rows {first:02X}-{last:02X}, "
                              f"past the new length {rows}; set \"truncate\": true to drop them.", "PATTERN_TRUNCATE")
    for key in lost:
        del pattern.cells[key]
    before, pattern.rows = pattern.rows, rows
    return {"pattern": index, "rows_before": before, "rows": rows, "cells_dropped": len(lost)}


XM_HEADER_FIELDS = ("restart_position", "default_speed", "default_bpm", "frequency_table")


def _xm_header(module: Module, op: dict) -> dict:
    """Edit the XM header values kept in `metadata.xm`; a field left out keeps its value."""
    _fields(op, set(), set(XM_HEADER_FIELDS))
    if not any(key in op for key in XM_HEADER_FIELDS):
        raise ValidationError(f"give at least one of {list(XM_HEADER_FIELDS)}.", "PATCH_FIELD")
    block = module.metadata.setdefault("xm", {})
    defaults = {"restart_position": 0, "default_speed": 6, "default_bpm": 125, "frequency_table": "linear"}
    before = {key: block.get(key, defaults[key]) for key in XM_HEADER_FIELDS}
    if "restart_position" in op:
        require_int(op["restart_position"], "restart_position", 0, len(module.orders) - 1, "ORDERS")
    if "default_speed" in op:
        require_int(op["default_speed"], "default_speed", 1, 31, "TIMING")
    if "default_bpm" in op:
        require_int(op["default_bpm"], "default_bpm", 32, 255, "TIMING")
    if "frequency_table" in op and op["frequency_table"] not in ("linear", "amiga"):
        raise ValidationError("frequency_table: 'linear' or 'amiga' expected.", "PATCH_FIELD")
    for key in XM_HEADER_FIELDS:
        if key in op:
            block[key] = op[key]
    result = {"before": before, "after": {key: block.get(key, defaults[key]) for key in XM_HEADER_FIELDS}}
    if before["frequency_table"] != result["after"]["frequency_table"]:
        result["note"] = ("Notes keep their pitch; portamento, vibrato and arpeggio slide by a different amount "
                          "with the other frequency table.")
    return result


# --- sample editing (on copies; every edit that changes PCM or the loop is recorded) ---------------------

def _edit_target(module: Module, op: dict, drops_recipe: bool = True):
    from . import sample_tools
    slot = require_int(op["slot"], "slot", 1, len(module.samples), "SAMPLE_SLOT")
    before = module.samples[slot - 1]
    if drops_recipe:
        sample_tools.guard_edit(module, before, slot)
    elif not before.pcm:
        raise ValidationError(f"Sample slot {slot} is empty; there is nothing to edit.", "SAMPLE_SLOT")
    return slot, before


def _commit_edit(module: Module, slot: int, before, after, edit: dict, report: dict) -> dict:
    """Store an edited sample. Unchanged PCM and loop store nothing (the recipe and provenance stay)."""
    from . import sample_tools
    changed = (after.pcm, after.loop_start, after.loop_length) != (before.pcm, before.loop_start, before.loop_length)
    result = {"slot": slot, "changed": changed, **report}
    if changed:
        after.recipe = None
        entry = sample_tools.record_edit(module, slot, before, edit)
        module.samples[slot - 1] = after
        result.update(recipe_dropped=before.recipe is not None, provenance=entry.get("origin"),
                      bytes=len(after.pcm))
    return result


def _sample_loop(module: Module, op: dict) -> dict:
    """Set the loop of a sample (even byte points); `loop_length` 0 removes it (see sample_tools.with_loop)."""
    _fields(op, {"slot", "loop_start", "loop_length"}, {"adapt"})
    from . import sample_tools
    slot, before = _edit_target(module, op)
    after, report = sample_tools.with_loop(before, op["loop_start"], op["loop_length"], sample_tools.flag(op, "adapt"))
    return _commit_edit(module, slot, before, after, {"op": "sample_loop", "loop_start": after.loop_start,
                                                       "loop_length": after.loop_length,
                                                       "adapt": True if report["adaptations"] else None}, report)


def _sample_trim(module: Module, op: dict) -> dict:
    """Keep the PCM bytes in [start, end) exactly; the loop moves with them (see sample_tools.trim)."""
    _fields(op, {"slot"}, {"start", "end", "adjust_loop", "adapt"})
    from . import sample_tools
    if "start" not in op and "end" not in op:
        raise ValidationError("Give start and/or end (even byte offsets).", "PATCH_FIELD")
    slot, before = _edit_target(module, op)
    after, report = sample_tools.trim(before, op.get("start"), op.get("end"), sample_tools.flag(op, "adjust_loop"),
                                      sample_tools.flag(op, "adapt"))
    return _commit_edit(module, slot, before, after, {"op": "sample_trim", "start": report["start"],
                                                       "end": report["end"]}, report)


def _sample_gain(module: Module, op: dict) -> dict:
    """Scale the PCM by `db`; refused if it would clip unless `allow_clip` (see sample_tools.gain)."""
    _fields(op, {"slot", "db"}, {"allow_clip"})
    from . import sample_tools
    slot, before = _edit_target(module, op)
    after, report = sample_tools.gain(before, op["db"], sample_tools.flag(op, "allow_clip"))
    return _commit_edit(module, slot, before, after, {"op": "sample_gain", "db": report["db"],
                                                       "clipped": report["clipped"] or None}, report)


def _sample_fade(module: Module, op: dict) -> dict:
    """Linear fade-in/out in bytes (see sample_tools.fade)."""
    _fields(op, {"slot"}, {"fade_in", "fade_out", "allow_loop"})
    from . import sample_tools
    slot, before = _edit_target(module, op)
    after, report = sample_tools.fade(before, op.get("fade_in", 0), op.get("fade_out", 0),
                                      sample_tools.flag(op, "allow_loop"))
    return _commit_edit(module, slot, before, after, {"op": "sample_fade", "fade_in": report["fade_in"],
                                                       "fade_out": report["fade_out"]}, report)


def _sample_set_pcm(module: Module, op: dict) -> dict:
    """Replace a slot's PCM with drawn or computed bytes (hash-checked base64, like the schema v2 project)."""
    _fields(op, {"slot", "pcm_base64", "pcm_sha256"},
            {"loop_start", "loop_length", "name", "volume", "finetune", "replace", "adapt"})
    from . import sample_tools
    from .model import Sample, ascii_field, validate_sample
    from .project import _pcm_from_base64
    sample_tools.guard_new_pcm(module)
    slot = require_int(op["slot"], "slot", 1, 31, "SAMPLE_SLOT")
    if slot > len(module.samples) + 1:
        raise ValidationError(f"Choose an existing slot or the next free one ({len(module.samples) + 1}); "
                              "gaps are not inserted.", "SAMPLE_SLOT")
    existing = module.samples[slot - 1] if slot <= len(module.samples) else None
    occupied = existing is not None and bool(existing.pcm)
    if occupied and not sample_tools.flag(op, "replace"):
        raise ValidationError(f"Sample slot {slot} is occupied by {existing.name!r}; pass replace (CLI: "
                              "--replace) to overwrite it.", "SAMPLE_SLOT")
    pcm = _pcm_from_base64(op, f"sample_set_pcm slot {slot}")
    name = op.get("name", existing.name if occupied else f"Drawn {slot:02d}")
    ascii_field(name, 22, "Sample name")
    volume = require_int(op.get("volume", existing.volume if occupied else 40), "volume", 0, 64)
    finetune = require_int(op.get("finetune", existing.finetune if occupied else 0), "finetune", -8, 7)
    start, length = op.get("loop_start", 0), op.get("loop_length", 0)
    adaptations: list[str] = []
    if not length:
        pcm = sample_tools.leading_zero(pcm, sample_tools.flag(op, "adapt"), adaptations, "This PCM")
    sample = Sample(name, pcm, volume, finetune, start, length)
    validate_sample(sample, slot)
    if existing is None:
        module.samples.append(sample)
    else:
        module.samples[slot - 1] = sample
    sources = sample_tools.sources_of(module)
    previous = sources.get(str(slot)) if isinstance(sources.get(str(slot)), dict) else {}
    entry = {"origin": "drawn", "pcm_sha256": sample_tools.pcm_sha256(pcm)}
    if previous.get("library_id"):
        entry["replaced_library_id"] = previous["library_id"]
    sources[str(slot)] = entry
    return {"slot": slot, "name": name, "bytes": len(pcm), "loop_start": start, "loop_length": length,
            "looped": bool(length), "volume": volume, "finetune": finetune, "adaptations": adaptations,
            "provenance": "drawn", "changed": True}


def _sample_match_level(module: Module, op: dict) -> dict:
    """Set a sample's volume (and, only if volume 64 is not enough, clean gain) to its role's reference level.

    The reference follows `synth_tools.automatic_reference` (explicit `library`, else the default bank when it
    exists, else the fixed levels); `"match": "defaults"` forces the fixed levels and `"match": "library"`
    requires a bank. The role used is recorded in `metadata.sample_sources[slot]["role"]` (other provenance
    fields kept), so `report` compares the sample with the same group afterwards.
    """
    _fields(op, {"slot"}, {"role", "library", "match"})
    from . import loudness, sample_library, sample_tools
    from .synth_tools import automatic_reference, bank_entries, build, resolve_reference
    slot, before = _edit_target(module, op, drops_recipe=False)
    match = op.get("match", "auto")
    if match not in ("auto", "library", "defaults"):
        raise ValidationError(f"match must be one of ['auto', 'library', 'defaults'], got {match!r}.", "PATCH_FIELD")
    if match == "defaults":
        if op.get("library") is not None:
            raise ValidationError("'library' is not used with \"match\": \"defaults\".", "PATCH_FIELD")
        reference = {**resolve_reference("defaults"), "path": None, "selection": "explicit",
                     "reason": "match 'defaults' was given; fixed reference levels."}
    elif match == "library" and op.get("library") is None:
        reference = {**automatic_reference(sample_library.DEFAULT_LIBRARY),
                     "reason": "match 'library' without 'library' uses the default sample bank."}
    else:
        reference = automatic_reference(op.get("library"))
    sources = module.metadata.get("sample_sources") if isinstance(module.metadata, dict) else None
    recorded = sources.get(str(slot)) if isinstance(sources, dict) else None
    recorded = recorded if isinstance(recorded, dict) else {}
    if op.get("role") is not None:
        role, role_source = op["role"], "op"
        if role not in loudness.GROUPS:
            loudness.check_role(role)
    else:  # recorded role, recipe, the bank's category for a library_id, else the loop-length heuristic
        role, role_source = loudness.slot_role(before, recorded, bank_entries(reference))
    origin = {"reference": reference["source"], "reference_path": reference["path"],
              "reference_selection": reference["selection"], "reference_reason": reference["reason"]}
    if before.recipe is not None:
        # A recipe sample stays a recipe: the volume is matched and the recipe's `peak` raised if needed.
        if role not in loudness.ROLES:  # a group name such as "percussion"
            role, role_source = loudness.role_for_recipe(before.recipe), "recipe"
        after, record = build(before.name, before.recipe, before.finetune, role, reference)
        module.samples[slot - 1] = after
        # The PCM is never scaled here (gain_db 0); a raised recipe peak is reported as peak_raised_from/peak.
        result = {"slot": slot, "changed": after != before, "method": "recipe", "volume_before": before.volume,
                  "gain_db": 0.0, **record, **origin}
    else:
        after, report = sample_tools.match_level(before, role, reference)
        result = {"slot": slot, "method": "volume+gain" if report["gain_db"] else "volume", **report, **origin}
        if after.pcm != before.pcm:
            result.update(_commit_edit(module, slot, before, after, {"op": "sample_match_level", "role": role,
                                                                      "gain_db": report["gain_db"]}, {}))
        else:
            module.samples[slot - 1] = after
            result["changed"] = after.volume != before.volume
    sources = sample_tools.sources_of(module)
    entry = dict(sources[str(slot)]) if isinstance(sources.get(str(slot)), dict) else {}
    if not entry and after.recipe is not None:
        entry = {"origin": "synthesized", "recipe_type": after.recipe.get("type")}
    entry["role"] = role
    sources[str(slot)] = entry
    result.update(role=role, role_source=role_source)
    return result


def _apply_instrument(module: Module, op: dict) -> dict:
    """Write an instrument's note and effect phrase into a channel (see tracker4agents.instruments)."""
    _fields(op, {"pattern", "channel", "row", "note", "instrument"},
            {"slot", "replace", "length", "overwrite", "library", "instruments"})
    from .instruments import apply_instrument
    return apply_instrument(module, op)


OPERATIONS = {
    "set": _set, "write": _write, "clear": _clear,
    "copy": lambda module, op: _copy_or_move(module, op, False),
    "move": lambda module, op: _copy_or_move(module, op, True),
    "transpose": _transpose, "add_pattern": _add_pattern, "remove_pattern": _remove_pattern,
    "rename_pattern": _rename_pattern, "set_orders": _set_orders, "insert_order": _insert_order,
    "remove_order": _remove_order, "move_order": _move_order, "title": _title, "timing": _timing,
    "sample": _sample, "library_sample": _library_sample, "recipe_sample": _recipe_sample,
    "sample_loop": _sample_loop, "sample_trim": _sample_trim, "sample_gain": _sample_gain,
    "sample_fade": _sample_fade, "sample_set_pcm": _sample_set_pcm, "sample_match_level": _sample_match_level,
    "apply_instrument": _apply_instrument, "pattern_length": _pattern_length, "xm_header": _xm_header,
}


# Sample-editing operations written for the MOD sample (8-bit, even loop points, 31 slots). Inserting a
# library sample or a recipe works in an XM: the sample is converted like `convert` converts a MOD sample.
MOD_ONLY_OPERATIONS = frozenset({
    "sample_loop", "sample_trim", "sample_gain", "sample_fade", "sample_set_pcm", "sample_match_level",
    "apply_instrument",
})
# Operations on what only an XM has: patterns of 1-256 rows and the header in metadata.xm.
XM_ONLY_OPERATIONS = frozenset({"pattern_length", "xm_header"})


def apply_ops(module: Module, ops: object) -> list[dict]:
    """Apply operations in order to `module` in place. Callers validate afterwards."""
    if isinstance(ops, dict):
        if "op" not in ops and not set(ops) <= {"ops", "base_revision", "label"}:
            raise ValidationError("A patch is a list of operations, one operation object with \"op\", or "
                                  f"{{\"ops\": [...]}}; got an object with keys {sorted(ops)[:8]}.", "PATCH_FORMAT")
        ops = ops.get("ops") if "op" not in ops else [ops]
    if not isinstance(ops, list) or not ops:
        raise ValidationError("A patch is a non-empty list of operations.", "PATCH_FORMAT")
    if len(ops) > 2000:
        raise ValidationError("A patch holds at most 2000 operations.", "PATCH_FORMAT")
    results = []
    for index, op in enumerate(ops):
        try:
            if not isinstance(op, dict) or op.get("op") not in OPERATIONS:
                problem = 'missing "op"' if isinstance(op, dict) and "op" not in op else "unknown operation"
                raise ValidationError(f"{problem}; use one of {sorted(OPERATIONS)}.", "PATCH_OP")
            if module.format == "xm" and op["op"] in MOD_ONLY_OPERATIONS:
                raise ValidationError(f"'{op['op']}' edits MOD samples (8-bit, even loops) and is not available "
                                      "on an XM module; library_sample and recipe_sample insert samples into an "
                                      "XM, and 'sample' sets volume, finetune, panning, relative_note and "
                                      "loop_mode.", "XM_OP_UNSUPPORTED")
            if module.format != "xm" and op["op"] in XM_ONLY_OPERATIONS:
                raise ValidationError(f"'{op['op']}' edits XM structure (pattern length, header) and is not "
                                      "available on a MOD module: a MOD pattern always has 64 rows and the song "
                                      "starts at speed 6 / 125 BPM (use 'timing').", "MOD_OP_UNSUPPORTED")
            results.append({"op": op["op"], **OPERATIONS[op["op"]](module, op)})
        except ValidationError as exc:
            message = f"ops[{index}] ({op.get('op') if isinstance(op, dict) else '?'}): {exc}"
            if getattr(exc, "violations", None) is not None:  # keep the offending slots for the agent
                from .sample_source import SampleSourceError
                raise SampleSourceError(message, exc.violations) from exc
            # PATCH_OP is reserved for an unknown operation; classify codeless errors by their text.
            from .errors import error_code
            raise ValidationError(message, error_code(exc)) from exc
    return results


# --- differences ----------------------------------------------------------------

def diff_modules(before: Module, after: Module) -> dict:
    """Describe what changed between two modules, cell by cell, for journals and reviews."""
    cells = []
    for index in range(max(len(before.patterns), len(after.patterns))):
        old = before.patterns[index].cells if index < len(before.patterns) else {}
        new = after.patterns[index].cells if index < len(after.patterns) else {}
        for key in sorted(set(old) | set(new)):
            if old.get(key, EMPTY) != new.get(key, EMPTY):
                cells.append({"pattern": index, "row": key[0], "channel": key[1],
                              "before": cell_text(old.get(key, EMPTY), before.format),
                              "after": cell_text(new.get(key, EMPTY), after.format)})
    samples = [slot for slot in range(1, max(len(before.samples), len(after.samples)) + 1)
               if (before.samples[slot - 1] if slot <= len(before.samples) else None)
               != (after.samples[slot - 1] if slot <= len(after.samples) else None)]
    result = {"cells": cells}
    if before.orders != after.orders:
        result["orders"] = {"before": list(before.orders), "after": list(after.orders)}
    if len(before.patterns) != len(after.patterns):
        result["pattern_count"] = {"before": len(before.patterns), "after": len(after.patterns)}
    names = [index for index in range(min(len(before.patterns), len(after.patterns)))
             if before.patterns[index].name != after.patterns[index].name]
    if names:
        result["pattern_names"] = names
    lengths = {str(index): [before.patterns[index].rows, after.patterns[index].rows]
               for index in range(min(len(before.patterns), len(after.patterns)))
               if before.patterns[index].rows != after.patterns[index].rows}
    if lengths:
        result["pattern_rows"] = lengths
    header = {key: [xm_profile(before).get(key), xm_profile(after).get(key)] for key in XM_HEADER_KEYS
              if xm_profile(before).get(key) != xm_profile(after).get(key)}
    if header:
        result["xm_header"] = header
    if samples:
        result["samples"] = samples
        result["sample_fields"] = {str(slot): _sample_fields_changed(before, after, slot) for slot in samples}
    if before.title != after.title:
        result["title"] = {"before": before.title, "after": after.title}
    if before.metadata != after.metadata:
        result["metadata"] = True
    return result


def _sample_fields_changed(before: Module, after: Module, slot: int) -> list[str]:
    """Names of the sample fields that differ in one slot ("added"/"removed" when the slot itself changed)."""
    old = before.samples[slot - 1] if slot <= len(before.samples) else None
    new = after.samples[slot - 1] if slot <= len(after.samples) else None
    if old is None or new is None:
        return ["added" if old is None else "removed"]
    return [field.name for field in dataclasses.fields(Sample) if getattr(old, field.name) != getattr(new, field.name)]


def flow_changes(diff: dict) -> list[str]:
    """Cells where an existing Bxx/Dxx/Fxx (jump, break, speed/tempo) was removed or replaced by another effect."""
    found = []
    for item in diff.get("cells", []):
        before, after = item["before"].split()[-1], item["after"].split()[-1]
        if before[0] in "BDF" and after[0] != before[0]:
            found.append(f"P{item['pattern']:02X} r{item['row']:02X} ch{item['channel']}: {before} → {after}")
    return found


def touched(diff: dict) -> set:
    """Keys of everything a diff touches, used to detect overlapping edits."""
    keys = {("cell", item["pattern"], item["row"], item["channel"]) for item in diff.get("cells", [])}
    if "orders" in diff or "pattern_count" in diff:
        keys.add(("structure",))
    keys |= {("sample", slot) for slot in diff.get("samples", [])}
    keys |= {("pattern_name", index) for index in diff.get("pattern_names", [])}
    if "title" in diff:
        keys.add(("title",))
    return keys


def summarize(diff: dict, limit: int = 12) -> list[str]:
    """Short agent-readable lines: 'P03 r10 ch2: E-2 01 ... → G-2 01 ...' (channels zero-based, as in operations)."""
    lines = [f"P{item['pattern']:02X} r{item['row']:02X} ch{item['channel']}: {item['before']} → {item['after']}"
             for item in diff.get("cells", [])[:limit]]
    if len(diff.get("cells", [])) > limit:
        lines.append(f"… {len(diff['cells']) - limit} more cells")
    if "orders" in diff:
        lines.append(f"orders: {diff['orders']['before']} → {diff['orders']['after']}")
    if "pattern_count" in diff:
        lines.append(f"patterns: {diff['pattern_count']['before']} → {diff['pattern_count']['after']}")
    for index in diff.get("pattern_names", []):
        lines.append(f"pattern {index:02X} renamed")
    for index, (old_rows, new_rows) in diff.get("pattern_rows", {}).items():
        lines.append(f"pattern {int(index):02X} rows: {old_rows} → {new_rows}")
    for key, (old_value, new_value) in diff.get("xm_header", {}).items():
        lines.append(f"xm header {key}: {old_value} → {new_value}")
    for slot in diff.get("samples", []):
        fields = diff.get("sample_fields", {}).get(str(slot))
        lines.append(f"sample {slot:02X} changed" + (f": {', '.join(fields)}" if fields else ""))
    if "title" in diff:
        lines.append(f"title: {diff['title']['before']!r} → {diff['title']['after']!r}")
    return lines


def _carry_provenance(target: Module, source: Module, slot: int) -> None:
    """A merged sample slot brings its `metadata.sample_sources` entry along (or loses a stale one)."""
    mine = source.metadata.get("sample_sources") if isinstance(source.metadata, dict) else None
    entry = mine.get(str(slot)) if isinstance(mine, dict) else None
    sources = target.metadata.get("sample_sources")
    if entry is not None:
        if not isinstance(sources, dict):
            sources = target.metadata["sample_sources"] = {}
        sources[str(slot)] = copy.deepcopy(entry)
    elif isinstance(sources, dict):
        sources.pop(str(slot), None)


def merge_modules(base: Module, mine: Module, theirs: Module) -> tuple[Module, list[dict]]:
    """Three-way merge: start from `theirs` and replay `mine`'s changes since `base`.

    Cells merge one by one. Orders/pattern count, each sample, each pattern name and
    the title merge as whole units. Returns the merged module and the conflicts
    (where both sides changed the same unit differently; `theirs` is kept there).
    """
    merged = copy.deepcopy(theirs)
    conflicts = []
    mine_diff, theirs_diff = diff_modules(base, mine), diff_modules(base, theirs)
    their_keys = touched(theirs_diff)
    if ("structure",) in touched(mine_diff):
        if ("structure",) in their_keys and (mine.orders, len(mine.patterns)) != (theirs.orders, len(theirs.patterns)):
            conflicts.append({"unit": "structure", "mine": mine_diff.get("orders"), "theirs": theirs_diff.get("orders")})
        else:
            merged.orders = list(mine.orders)
            while len(merged.patterns) < len(mine.patterns):
                merged.patterns.append(copy.deepcopy(mine.patterns[len(merged.patterns)]))
            del merged.patterns[len(mine.patterns):]
    for item in mine_diff["cells"]:
        key = ("cell", item["pattern"], item["row"], item["channel"])
        if item["pattern"] >= len(merged.patterns):
            continue
        value = mine.patterns[item["pattern"]].get(item["row"], item["channel"])
        if key in their_keys and theirs.patterns[item["pattern"]].get(item["row"], item["channel"]) != value:
            conflicts.append({"unit": "cell", **{k: item[k] for k in ("pattern", "row", "channel")},
                              "mine": item["after"],
                              "theirs": cell_text(theirs.patterns[item["pattern"]].get(item["row"], item["channel"]),
                                                  theirs.format)})
            continue
        merged.patterns[item["pattern"]].put(item["row"], item["channel"], value)
    for slot in mine_diff.get("samples", []):
        if ("sample", slot) in their_keys:
            conflicts.append({"unit": "sample", "slot": slot})
        elif slot <= len(mine.samples):
            while len(merged.samples) < slot:
                merged.samples.append(copy.deepcopy(mine.samples[len(merged.samples)]))
            merged.samples[slot - 1] = copy.deepcopy(mine.samples[slot - 1])
            _carry_provenance(merged, mine, slot)
    for index in mine_diff.get("pattern_names", []):
        if ("pattern_name", index) in their_keys:
            conflicts.append({"unit": "pattern_name", "pattern": index})
        elif index < len(merged.patterns):
            merged.patterns[index].name = mine.patterns[index].name
    if "title" in mine_diff:
        if ("title",) in their_keys and theirs.title != mine.title:
            conflicts.append({"unit": "title", "mine": mine.title, "theirs": theirs.title})
        else:
            merged.title = mine.title
    return merged, conflicts
