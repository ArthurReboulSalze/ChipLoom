"""Batch edit operations shared by the CLI, the desktop window and live sessions.

A patch is a JSON list of operations applied to a copy of the module and
validated as one transaction: either every operation applies or none does.
Indices for patterns, orders, rows and channels are zero-based; sample slots
are 1-31 as in the score. Cells use the compact grid text of `inspect --grid`.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path

from .model import (
    EMPTY, NOTE_TO_PERIOD, NOTES, Cell, Module, Pattern, ValidationError, cell, require_int,
)

EMPTY_TOKENS = {"", "---", "...", "--", "..", "000"}
CELL_TEXT = re.compile(r"^\s*(\S{3})(?:\s+(\S{2}))?(?:\s+(\S{3}))?\s*$")


def cell_text(value: Cell) -> str:
    """Grid spelling: note or ---, sample in hex or --, effect in hex or ...."""
    if value == EMPTY:
        return "--- -- ..."
    sample = f"{value.sample:02X}" if value.sample else "--"
    effect = value.effect if value.command or value.param else "..."
    return f"{value.note or '---'} {sample} {effect}"


def parse_cell(text: object) -> Cell:
    """Parse `C-2 01 C20`, `--- -- ...`, `G#2 0A`, `C-3` or an empty string."""
    if text is None:
        return EMPTY
    if not isinstance(text, str):
        raise ValidationError("A cell must be grid text such as 'C-2 01 C20' or '--- -- ...'.", "PATCH_CELL")
    match = CELL_TEXT.match(text)
    if not text.strip():
        return EMPTY
    if not match:
        raise ValidationError(f"Unreadable cell {text!r}; expected 'NOTE SS EEE', e.g. 'C-2 01 C20'.", "PATCH_CELL")
    note, sample, effect = match.groups()
    note = None if note in EMPTY_TOKENS else note.upper()
    try:
        sample_value = 0 if sample is None or sample in EMPTY_TOKENS else int(sample, 16)
    except ValueError:
        raise ValidationError(f"Cell {text!r}: the sample must be two hexadecimal digits or --.", "PATCH_CELL") from None
    effect = "000" if effect is None or effect in EMPTY_TOKENS else effect
    return cell(note, sample_value, effect)


def row_cells(text: object) -> list[Cell]:
    """Parse one grid row: four cells separated by '|', optionally prefixed by 'NN |'."""
    if not isinstance(text, str):
        raise ValidationError("A grid row must be text with four cells separated by '|'.", "PATCH_CELL")
    parts = [part.strip() for part in text.strip().strip("|").split("|")]
    if len(parts) == 5 and re.fullmatch(r"[0-9A-Fa-f]{2}", parts[0]):
        parts = parts[1:]
    if len(parts) != 4:
        raise ValidationError(f"Grid row {text!r}: expected four cells separated by '|'.", "PATCH_CELL")
    return [parse_cell(part) for part in parts]


def pattern_grid(module: Module, pattern: int, start: int = 0, rows: int = 64) -> list[str]:
    """Readable rows such as `10 | C-2 01 ... | --- -- ... | E-3 05 C20 | --- -- ...`."""
    require_int(pattern, "pattern", 0, len(module.patterns) - 1)
    require_int(start, "row", 0, 63)
    require_int(rows, "rows", 1, 64 - start)
    selected = module.patterns[pattern]
    return [f"{row:02X} | " + " | ".join(cell_text(selected.get(row, channel)) for channel in range(4))
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


def _block(op: dict) -> tuple[int, int, int, int]:
    row, rows = op.get("row", 0), op.get("rows", 1)
    channel, channels = op.get("channel", 0), op.get("channels", 1)
    require_int(row, "row", 0, 63)
    require_int(rows, "rows", 1, 64 - row)
    require_int(channel, "channel", 0, 3)
    require_int(channels, "channels", 1, 4 - channel)
    return row, rows, channel, channels


def _read_block(pattern: Pattern, row: int, rows: int, channel: int, channels: int) -> list[list[Cell]]:
    return [[pattern.get(row + r, channel + c) for c in range(channels)] for r in range(rows)]


def _write_block(pattern: Pattern, row: int, channel: int, block: list[list[Cell]]) -> None:
    if row + len(block) > 64 or channel + len(block[0]) > 4:
        raise ValidationError("The destination block goes past row 63 or channel 3.", "PATCH_BOUNDS")
    for r, values in enumerate(block):
        for c, value in enumerate(values):
            pattern.put(row + r, channel + c, value)


BLOCK = {"pattern", "row", "rows", "channel", "channels"}


def _set(module: Module, op: dict) -> dict:
    _fields(op, {"pattern", "row", "channel"}, {"note", "sample", "effect", "cell"})
    pattern = _pattern(module, op["pattern"])
    require_int(op["row"], "row", 0, 63)
    require_int(op["channel"], "channel", 0, 3)
    if "cell" in op:
        if any(key in op for key in ("note", "sample", "effect")):
            raise ValidationError("Use either 'cell' or note/sample/effect, not both.", "PATCH_FIELD")
        value = parse_cell(op["cell"])
    else:
        old = pattern.get(op["row"], op["channel"])
        note = op["note"] if "note" in op else old.note
        if note in EMPTY_TOKENS:
            note = None
        sample = op.get("sample", old.sample)
        require_int(sample, "sample", 0, 31)
        effect = op.get("effect", old.effect)
        effect = "000" if effect in (None, "...") else effect
        value = cell(note, sample, effect)
    pattern.put(op["row"], op["channel"], value)
    return {}


def _write(module: Module, op: dict) -> dict:
    """Write consecutive cells down one channel, or whole grid rows across all four."""
    _fields(op, {"pattern"}, {"row", "channel", "cells", "lines", "step"})
    pattern = _pattern(module, op["pattern"])
    row, step = op.get("row", 0), op.get("step", 1)
    require_int(row, "row", 0, 63)
    require_int(step, "step", 1, 64)
    if ("cells" in op) == ("lines" in op):
        raise ValidationError("Provide exactly one of 'cells' (one channel) or 'lines' (grid rows).", "PATCH_FIELD")
    values = op.get("cells", op.get("lines"))
    if not isinstance(values, list) or not values:
        raise ValidationError("'cells'/'lines' must be a non-empty list.", "PATCH_FIELD")
    if row + (len(values) - 1) * step > 63:
        raise ValidationError("The written rows go past row 63.", "PATCH_BOUNDS")
    if "cells" in op:
        channel = op.get("channel", 0)
        require_int(channel, "channel", 0, 3)
        for index, text in enumerate(values):
            pattern.put(row + index * step, channel, parse_cell(text))
    else:
        if "channel" in op:
            raise ValidationError("'lines' always covers the four channels; remove 'channel'.", "PATCH_FIELD")
        for index, text in enumerate(values):
            for channel, value in enumerate(row_cells(text)):
                pattern.put(row + index * step, channel, value)
    return {}


def _clear(module: Module, op: dict) -> dict:
    _fields(op, {"pattern"}, BLOCK - {"pattern"})
    pattern = _pattern(module, op["pattern"])
    row, rows, channel, channels = _block(op)
    _write_block(pattern, row, channel, [[EMPTY] * channels for _ in range(rows)])
    return {}


def _copy_or_move(module: Module, op: dict, move: bool) -> dict:
    _fields(op, {"pattern"}, BLOCK - {"pattern"} | {"to_pattern", "to_row", "to_channel"})
    source = _pattern(module, op["pattern"])
    row, rows, channel, channels = _block(op)
    target = _pattern(module, op.get("to_pattern", op["pattern"]), "to_pattern")
    to_row, to_channel = op.get("to_row", row), op.get("to_channel", channel)
    require_int(to_row, "to_row", 0, 63)
    require_int(to_channel, "to_channel", 0, 3)
    block = _read_block(source, row, rows, channel, channels)
    if move:
        _write_block(source, row, channel, [[EMPTY] * channels for _ in range(rows)])
    _write_block(target, to_row, to_channel, block)
    return {}


def _transpose(module: Module, op: dict) -> dict:
    _fields(op, {"pattern", "semitones"}, BLOCK - {"pattern"})
    pattern = _pattern(module, op["pattern"])
    semitones = require_int(op["semitones"], "semitones", -35, 35)
    defaults = {"rows": 64 - op.get("row", 0), "channels": 1}
    row, rows, channel, channels = _block({**defaults, **op})
    for r in range(row, row + rows):
        for c in range(channel, channel + channels):
            old = pattern.get(r, c)
            if old.note:
                target = NOTES.index(old.note) + semitones
                if not 0 <= target < len(NOTES):
                    raise ValidationError(f"Transposing {old.note} by {semitones} leaves C-1..B-3.", "NOTE_RANGE")
                pattern.put(r, c, Cell(NOTE_TO_PERIOD[NOTES[target]], old.sample, old.command, old.param))
    return {}


def _add_pattern(module: Module, op: dict) -> dict:
    _fields(op, set(), {"copy_of", "name", "insert_order"})
    if len(module.patterns) >= 64:
        raise ValidationError("The M.K. profile holds at most 64 patterns.", "PATTERNS")
    if "copy_of" in op:
        new = copy.deepcopy(_pattern(module, op["copy_of"], "copy_of"))
    else:
        new = Pattern()
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
    available = [ch for ch in range(4) if pattern.get(0, ch).command == 15]
    available += [ch for ch in range(4) if ch not in available and pattern.get(0, ch).effect == "000"]
    if len(available) < 2:
        raise ValidationError("Il faut deux colonnes d'effet libres ou Fxx sur la première ligne pour fixer tempo et "
                              "vitesse sans effacer d'autres effets.", "TIMING")
    for channel in range(4):
        old = pattern.get(0, channel)
        if old.command == 15:
            pattern.put(0, channel, Cell(old.period, old.sample))
    for channel, parameter in zip(available[:2], (speed, bpm)):
        old = pattern.get(0, channel)
        pattern.put(0, channel, Cell(old.period, old.sample, 15, parameter))
    if isinstance(module.metadata.get("timing"), dict):
        module.metadata["timing"].update(bpm=bpm, speed=speed)


def _timing(module: Module, op: dict) -> dict:
    _fields(op, {"bpm", "speed"}, set())
    set_initial_timing(module, op["bpm"], op["speed"])
    return {}


def _sample(module: Module, op: dict) -> dict:
    _fields(op, {"slot"}, {"volume", "finetune", "name"})
    slot = require_int(op["slot"], "slot", 1, len(module.samples))
    sample = module.samples[slot - 1]
    if "volume" in op:
        sample.volume = require_int(op["volume"], "volume", 0, 64)
    if "finetune" in op:
        sample.finetune = require_int(op["finetune"], "finetune", -8, 7)
    if "name" in op:
        sample.name = op["name"]
    return {}


def _library_sample(module: Module, op: dict) -> dict:
    _fields(op, {"library", "id"}, {"slot", "replace", "adapt"})
    from .sample_library import SampleLibrary
    candidate, info = SampleLibrary(Path(op["library"])).insert(
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


OPERATIONS = {
    "set": _set, "write": _write, "clear": _clear,
    "copy": lambda module, op: _copy_or_move(module, op, False),
    "move": lambda module, op: _copy_or_move(module, op, True),
    "transpose": _transpose, "add_pattern": _add_pattern, "remove_pattern": _remove_pattern,
    "rename_pattern": _rename_pattern, "set_orders": _set_orders, "insert_order": _insert_order,
    "remove_order": _remove_order, "move_order": _move_order, "title": _title, "timing": _timing,
    "sample": _sample, "library_sample": _library_sample, "recipe_sample": _recipe_sample,
}


def apply_ops(module: Module, ops: object) -> list[dict]:
    """Apply operations in order to `module` in place. Callers validate afterwards."""
    if isinstance(ops, dict):
        ops = ops.get("ops") if set(ops) <= {"ops", "base_revision", "label"} else [ops]
    if not isinstance(ops, list) or not ops:
        raise ValidationError("A patch is a non-empty list of operations.", "PATCH_FORMAT")
    if len(ops) > 2000:
        raise ValidationError("A patch holds at most 2000 operations.", "PATCH_FORMAT")
    results = []
    for index, op in enumerate(ops):
        try:
            if not isinstance(op, dict) or op.get("op") not in OPERATIONS:
                raise ValidationError(f"unknown operation; use one of {sorted(OPERATIONS)}.", "PATCH_OP")
            results.append({"op": op["op"], **OPERATIONS[op["op"]](module, op)})
        except ValidationError as exc:
            raise ValidationError(f"ops[{index}] ({op.get('op') if isinstance(op, dict) else '?'}): {exc}",
                                  exc.code or "PATCH_OP") from exc
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
                              "before": cell_text(old.get(key, EMPTY)), "after": cell_text(new.get(key, EMPTY))})
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
    if samples:
        result["samples"] = samples
    if before.title != after.title:
        result["title"] = {"before": before.title, "after": after.title}
    if before.metadata != after.metadata:
        result["metadata"] = True
    return result


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
    """Short human/agent-readable lines: 'P03 r10 ch2: E-2 01 ... → G-2 01 ...'."""
    lines = [f"P{item['pattern']:02X} r{item['row']:02X} ch{item['channel'] + 1}: {item['before']} → {item['after']}"
             for item in diff.get("cells", [])[:limit]]
    if len(diff.get("cells", [])) > limit:
        lines.append(f"… {len(diff['cells']) - limit} more cells")
    if "orders" in diff:
        lines.append(f"orders: {diff['orders']['before']} → {diff['orders']['after']}")
    if "pattern_count" in diff:
        lines.append(f"patterns: {diff['pattern_count']['before']} → {diff['pattern_count']['after']}")
    for slot in diff.get("samples", []):
        lines.append(f"sample {slot:02X} changed")
    if "title" in diff:
        lines.append(f"title: {diff['title']['before']!r} → {diff['title']['after']!r}")
    return lines


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
                              "theirs": cell_text(theirs.patterns[item["pattern"]].get(item["row"], item["channel"]))})
            continue
        merged.patterns[item["pattern"]].put(item["row"], item["channel"], value)
    for slot in mine_diff.get("samples", []):
        if ("sample", slot) in their_keys:
            conflicts.append({"unit": "sample", "slot": slot})
        elif slot <= len(mine.samples):
            while len(merged.samples) < slot:
                merged.samples.append(copy.deepcopy(mine.samples[len(merged.samples)]))
            merged.samples[slot - 1] = copy.deepcopy(mine.samples[slot - 1])
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
