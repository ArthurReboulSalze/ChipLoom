"""`chiploom live sync`: push the differences between a project file and the open session as live patches.

An agent that rewrites a whole project with a script still wants every change to land in the owner's
window as small, undoable, highlighted steps. `sync` reads the session's whole module (the `module`
method of the live API), compares it with the project and sends:

1. one patch for the samples (`recipe_sample` / `library_sample` with `replace`, then `sample`);
2. one patch for the pattern structure (title, added patterns, XM lengths, pattern names);
3. one patch per pattern whose cells differ (a `write` or `clear` per changed channel);
4. one patch for the order list, the patterns removed at the end and the XM header.

Every patch carries `base_revision` = the revision read in step 0, so an edit the owner made after the
read and that a patch would overwrite stops the sync with `LIVE_CONFLICT`. The plan is simulated on a
copy of the session module first (the same checks the session runs), so a patch is only sent when it
reproduces the project; what operations cannot express is listed under `not_synced`.
"""

from __future__ import annotations

from pathlib import Path

from . import formats, project
from .live import LiveClient, clone_module
from .model import EMPTY, Module, Pattern, Sample, ValidationError, playback_plan, validate, xm_profile
from .patch import XM_HEADER_FIELDS, apply_ops, cell_text

LABEL_LIMIT = 80
MISMATCH_LIMIT = 10
MOD_SAMPLE_FIELDS = ("name", "volume", "finetune")              # what the `sample` op sets in a MOD
XM_SAMPLE_FIELDS = MOD_SAMPLE_FIELDS + ("panning", "relative_note", "loop_mode")
CONTENT_FIELDS = ("pcm", "loop_start", "loop_length", "bits")  # only an insertion (recipe, library) changes these
XM_HEADER_DEFAULTS = {"restart_position": 0, "default_speed": 6, "default_bpm": 125, "frequency_table": "linear"}
RELOAD_HINT = "reload the project in the window to take it"
RELOAD = f"patch operations cannot express it; {RELOAD_HINT}"


def load_source(path: Path) -> Module:
    """A project JSON (or a MOD/XM file), read the way the window opens it."""
    path = Path(path)
    return project.load(path) if path.suffix.lower() == ".json" else formats.read(path)


def read_session(client: LiveClient) -> tuple[int, Module]:
    """The session's revision and an exact copy of its module (PCM, recipes, metadata)."""
    try:
        payload = client.call("module")
    except ValidationError as exc:
        if exc.code == "LIVE_UNKNOWN_METHOD":
            raise ValidationError("This session cannot send its whole module; update the ChipLoom window "
                                  "(or the headless server) to use `live sync`.", "LIVE_UNKNOWN_METHOD") from exc
        raise
    module = project.from_dict(payload["project"])
    for slot, recipe in (payload.get("recipes") or {}).items():
        module.samples[int(slot) - 1].recipe = recipe
    return payload["revision"], module


# --- differences ---------------------------------------------------------------------------------------

def _sample_fields(module: Module) -> tuple[str, ...]:
    return XM_SAMPLE_FIELDS if module.format == "xm" else MOD_SAMPLE_FIELDS


def _blank(sample: Sample | None) -> bool:
    return sample is None or (not sample.pcm and not sample.name)


def _content(sample: Sample | None) -> tuple:
    return tuple(getattr(sample, key) for key in CONTENT_FIELDS) if sample is not None else ((), 0, 0, 8)


def _header(module: Module) -> dict:
    block = xm_profile(module)
    return {key: block.get(key, XM_HEADER_DEFAULTS[key]) for key in XM_HEADER_FIELDS}


def mismatches(target: Module, module: Module) -> list[dict]:
    """Every difference `sync` is meant to remove, each with a hashable `key` (metadata is not listed)."""
    found: list[dict] = []

    def add(key: tuple, **details) -> None:
        found.append({"key": key, **details})

    if target.title != module.title:
        add(("title",), unit="title", project=target.title, session=module.title)
    if len(target.patterns) != len(module.patterns):
        add(("pattern_count",), unit="pattern_count", project=len(target.patterns), session=len(module.patterns))
    if target.orders != module.orders:
        add(("orders",), unit="orders", project=list(target.orders), session=list(module.orders))
    if target.format == "xm":
        mine, theirs = _header(target), _header(module)
        for key in XM_HEADER_FIELDS:
            if mine[key] != theirs[key]:
                add(("xm_header", key), unit="xm_header", field=key, project=mine[key], session=theirs[key])
    for index, wanted in enumerate(target.patterns):
        have = module.patterns[index] if index < len(module.patterns) else Pattern(rows=wanted.rows)
        if index < len(module.patterns) and wanted.name != have.name:
            add(("pattern_name", index), unit="pattern_name", pattern=index, project=wanted.name, session=have.name)
        if wanted.rows != have.rows:
            add(("pattern_rows", index), unit="pattern_rows", pattern=index, project=wanted.rows, session=have.rows)
        for row, channel in sorted(set(wanted.cells) | set(have.cells)):
            if wanted.get(row, channel) != have.get(row, channel):
                add(("cell", index, row, channel), unit="cell", pattern=index, row=row, channel=channel,
                    project=cell_text(wanted.get(row, channel), target.format),
                    session=cell_text(have.get(row, channel), module.format))
    for slot in range(1, max(len(target.samples), len(module.samples)) + 1):
        wanted = target.samples[slot - 1] if slot <= len(target.samples) else None
        have = module.samples[slot - 1] if slot <= len(module.samples) else None
        if wanted is None or have is None:
            if not (_blank(wanted) and _blank(have)):
                add(("sample", slot, "slot"), unit="sample", slot=slot, field="slot",
                    project=wanted is not None, session=have is not None)
            continue
        for key in _sample_fields(target) + CONTENT_FIELDS:
            if getattr(wanted, key) != getattr(have, key):
                details = {} if key == "pcm" else {"project": getattr(wanted, key), "session": getattr(have, key)}
                add(("sample", slot, key), unit="sample", slot=slot, field=key, **details)
    return found


def _public(item: dict) -> dict:
    return {key: value for key, value in item.items() if key != "key"}


def _metadata_gaps(target: Module, module: Module) -> list[dict]:
    """Metadata differences left after the plan: never carried by patch operations."""
    gaps: list[dict] = []
    mine = target.metadata if isinstance(target.metadata, dict) else {}
    theirs = module.metadata if isinstance(module.metadata, dict) else {}
    other = []
    for key in sorted(set(mine) | set(theirs)):
        if mine.get(key) == theirs.get(key):
            continue
        if key == "xm" and isinstance(mine.get(key, {}), dict) and isinstance(theirs.get(key, {}), dict):
            a, b = mine.get("xm", {}), theirs.get("xm", {})
            for name in sorted(set(a) | set(b)):
                if name in XM_HEADER_FIELDS or a.get(name) == b.get(name):
                    continue
                if name == "instruments" and isinstance(a.get(name, {}), dict) and isinstance(b.get(name, {}), dict):
                    x, y = a.get(name, {}), b.get(name, {})
                    for slot in sorted(set(x) | set(y), key=lambda value: (len(value), value)):
                        if x.get(slot) == y.get(slot):
                            continue
                        first, second = x.get(slot) or {}, y.get(slot) or {}
                        fields = sorted(field for field in set(first) | set(second) if first.get(field) != second.get(field))
                        gaps.append({"what": f"XM instrument {slot}", "slot": int(slot) if slot.isdigit() else slot,
                                     "fields": fields, "reason": "envelopes, auto-vibrato, fadeout and the other "
                                     f"instrument data are not patch operations; {RELOAD_HINT}"})
                else:
                    gaps.append({"what": f"metadata.xm.{name}", "reason": RELOAD})
        elif key == "sample_sources" and isinstance(mine.get(key, {}), dict) and isinstance(theirs.get(key, {}), dict):
            x, y = mine.get(key, {}), theirs.get(key, {})
            slots = sorted((slot for slot in set(x) | set(y) if x.get(slot) != y.get(slot)),
                           key=lambda value: (len(value), value))
            gaps.append({"what": "metadata.sample_sources", "slots": slots,
                         "reason": "the provenance records differ (an inserted sample writes its own record); "
                                   + RELOAD})
        else:
            other.append(key)
    if other:
        gaps.append({"what": "metadata", "keys": other, "reason": RELOAD})
    return gaps


# --- the plan ------------------------------------------------------------------------------------------

def _label(label: str, part: str) -> str:
    text = f"{label}: {part}"
    return text if len(text) <= LABEL_LIMIT else text[:LABEL_LIMIT - 1] + "…"


def _check(module: Module, ops: list[dict]) -> None:
    """Apply in place with the checks a live patch goes through."""
    apply_ops(module, ops)
    validate(module)
    playback_plan(module)


def _sample_ops(target: Module, work: Module, library: Path, not_synced: list[dict]) -> list[dict]:
    """`recipe_sample` / `library_sample` for changed PCM, then `sample` for the playback settings; each slot is
    tried on a copy and kept only when it reproduces the project's sample."""
    sources = target.metadata.get("sample_sources") if isinstance(target.metadata, dict) else None
    sources = sources if isinstance(sources, dict) else {}
    xm, ops = target.format == "xm", []
    for slot in range(1, max(len(target.samples), len(work.samples)) + 1):
        wanted = target.samples[slot - 1] if slot <= len(target.samples) else None
        have = work.samples[slot - 1] if slot <= len(work.samples) else None
        if _blank(wanted) and _blank(have):
            continue
        if wanted is None:
            not_synced.append({"what": f"sample {slot}", "slot": slot,
                               "reason": "the slot exists only in the session; operations cannot remove a sample slot"})
            continue
        steps: list[dict] = []
        if have is None or _content(wanted) != _content(have):
            source = sources.get(str(slot)) if isinstance(sources.get(str(slot)), dict) else {}
            if not wanted.pcm:
                not_synced.append({"what": f"sample {slot}", "slot": slot,
                                   "reason": "the project's slot has no PCM; operations cannot clear a sample or "
                                             "add an empty slot (reload the project)"})
                continue
            if wanted.recipe is not None:
                step = {"op": "recipe_sample", "name": wanted.name, "recipe": wanted.recipe, "slot": slot,
                        "volume": wanted.volume, "finetune": 0 if xm else wanted.finetune, "replace": True}
                if source.get("role"):
                    step["role"] = source["role"]
            elif source.get("library_id"):
                step = {"op": "library_sample", "id": source["library_id"], "slot": slot, "replace": True,
                        "library": str(library)}
                if source.get("adaptations"):
                    step["adapt"] = True
            else:
                not_synced.append({"what": f"sample {slot}", "slot": slot,
                                   "reason": "its PCM or loop differs and the project records neither a recipe nor "
                                             "a library_id; PCM edits are not sent (reload the project)"})
                continue
            steps.append(step)
        trial = clone_module(work)
        try:
            if steps:
                apply_ops(trial, steps)
            fields = {key: getattr(wanted, key) for key in _sample_fields(target)
                      if getattr(trial.samples[slot - 1], key) != getattr(wanted, key)}
            if fields:
                steps.append({"op": "sample", "slot": slot, **fields})
                apply_ops(trial, steps[-1:])
        except ValidationError as exc:
            not_synced.append({"what": f"sample {slot}", "slot": slot, "reason": str(exc)})
            continue
        if _content(trial.samples[slot - 1]) != _content(wanted):
            origin = "recipe" if wanted.recipe is not None else f"library sample {steps[0].get('id')}"
            not_synced.append({"what": f"sample {slot}", "slot": slot,
                               "reason": f"inserting the {origin} does not give the project's PCM and loop "
                                         "(edited after insertion?); reload the project"})
            continue
        if steps:
            work, ops = trial, ops + steps
    return ops


def _cell_ops(index: int, wanted: Pattern, have: Pattern, fmt: str, channels: int) -> list[dict]:
    """One op per changed channel: a `write` over the changed rows, or a `clear` when they become empty."""
    ops = []
    for channel in range(channels):
        rows = [row for row in range(wanted.rows) if wanted.get(row, channel) != have.get(row, channel)]
        if not rows:
            continue
        first, last = rows[0], rows[-1]
        values = [wanted.get(row, channel) for row in range(first, last + 1)]
        if all(value == EMPTY for value in values):
            ops.append({"op": "clear", "pattern": index, "row": first, "rows": len(values), "channel": channel})
        else:
            ops.append({"op": "write", "pattern": index, "row": first, "channel": channel,
                        "cells": [cell_text(value, fmt) for value in values]})
    return ops


def _structure_ops(target: Module, work: Module) -> list[dict]:
    """Title, new patterns, names, XM lengths, then the order list, the patterns removed at the end and the XM
    header (restart_position is checked against the new order list). A MOD must list its last pattern in the
    order list, so new patterns and the orders that use them travel in the same patch."""
    xm = target.format == "xm"
    ops = [{"op": "title", "title": target.title}] if target.title != work.title else []
    for index in range(len(work.patterns), len(target.patterns)):
        wanted = target.patterns[index]
        step = {"op": "add_pattern", "name": wanted.name, "insert_order": None}
        twin = next((number for number, have in enumerate(work.patterns)
                     if have.cells == wanted.cells and have.rows == wanted.rows), None)
        if twin is not None:  # a copy of a pattern the session already holds: no cells to write
            step["copy_of"] = twin
        elif xm and wanted.rows != 64:
            step["length"] = wanted.rows
        ops.append(step)
    for index in range(min(len(work.patterns), len(target.patterns))):
        wanted, have = target.patterns[index], work.patterns[index]
        if wanted.name != have.name:
            ops.append({"op": "rename_pattern", "pattern": index, "name": wanted.name})
        if xm and wanted.rows != have.rows:
            step = {"op": "pattern_length", "pattern": index, "rows": wanted.rows}
            if any(row >= wanted.rows for row, _ in have.cells):
                step["truncate"] = True
            ops.append(step)
    if work.orders != target.orders:
        ops.append({"op": "set_orders", "orders": list(target.orders)})
    ops += [{"op": "remove_pattern", "pattern": index}
            for index in range(len(work.patterns) - 1, len(target.patterns) - 1, -1)]
    if xm:
        mine, theirs = _header(target), _header(work)
        header = {key: mine[key] for key in XM_HEADER_FIELDS if mine[key] != theirs[key]}
        if header:
            ops.append({"op": "xm_header", **header})
    return ops


def _simulate(work: Module, patches: list[dict]) -> Module:
    """Apply the patches one by one to a copy, each checked like the session checks a live patch."""
    work = clone_module(work)
    for item in patches:
        try:
            _check(work, item["ops"])
        except ValidationError as exc:
            raise ValidationError(f"The patch {item['label']!r} would be refused by the session: {exc}",
                                  "LIVE_SYNC_PLAN") from exc
    return work


def plan(target: Module, current: Module, label: str = "Sync", library: Path | None = None) -> dict:
    """The patches that turn `current` (the session) into `target` (the project), simulated in order.

    Order: samples, structure (with the order list), then one patch per pattern whose cells differ. When an
    intermediate step would be invalid (say a Bxx in an old pattern points past the new order list), the
    structure and the cells go as one patch instead."""
    if (target.format, target.channels) != (current.format, current.channels):
        raise ValidationError(f"The project is a {target.channels}-channel {target.format.upper()} and the session a "
                              f"{current.channels}-channel {current.format.upper()}; patches cannot change the format "
                              "or the channel count. Open the project in the window instead.", "LIVE_SYNC_FORMAT")
    from .sample_library import DEFAULT_LIBRARY
    library = Path(library or DEFAULT_LIBRARY).resolve()  # the session may run in another directory
    not_synced: list[dict] = []

    def patch(part: str, pattern: int | None, ops: list[dict]) -> list[dict]:
        return [{"label": _label(label, part), "pattern": pattern, "ops": ops}] if ops else []

    samples = patch("samples", None, _sample_ops(target, current, library, not_synced))
    structure_ops = _structure_ops(target, current)
    shaped = clone_module(current)
    if structure_ops:
        apply_ops(shaped, structure_ops)  # only to see the patterns the cells are written into
    cells = [(index, wanted.name or f"Pattern {index:02X}",
              _cell_ops(index, wanted, shaped.patterns[index], target.format, target.channels))
             for index, wanted in enumerate(target.patterns)]
    patches = samples + patch("structure", None, structure_ops)
    for index, name, ops in cells:
        patches += patch(name, index, ops)
    try:
        work = _simulate(current, patches)
    except ValidationError as staged:
        whole = structure_ops + [op for _, _, ops in cells for op in ops]
        patches = samples + patch("whole song", None, whole)
        try:
            work = _simulate(current, patches)
        except ValidationError:
            raise staged from None
    # What is still different after the plan: listed, never sent.
    left = mismatches(target, work)
    explained = {item.get("slot") for item in not_synced if item.get("what", "").startswith("sample ")}
    for item in left:
        if item["unit"] == "sample" and item["slot"] in explained:
            continue
        not_synced.append({"what": item["unit"], **{k: v for k, v in _public(item).items() if k != "unit"},
                           "reason": "no patch operation reproduced it"})
    not_synced += _metadata_gaps(target, work)
    return {"patches": patches, "not_synced": not_synced, "expected": {item["key"] for item in left}}


# --- running it ----------------------------------------------------------------------------------------

def sync(client: LiveClient, path: Path, *, dry_run: bool = False, label: str | None = None,
         author: str = "agent", library: Path | None = None) -> dict:
    """Plan, send (unless `dry_run`) and verify. A refused patch stops the sync: the raised error carries
    `sync` with the patches applied before it and the ones not sent."""
    target = load_source(path)
    label = (label or "Sync").strip() or "Sync"
    revision, current = read_session(client)
    planned = plan(target, current, label, library)
    patches = planned["patches"]
    result = {"ok": True, "project": str(Path(path).resolve()), "revision_before": revision,
              "revision_after": revision, "unchanged": not patches, "not_synced": planned["not_synced"]}
    if dry_run or not patches:
        result["patches"] = [{"label": item["label"], "pattern": item["pattern"], "op_count": len(item["ops"]),
                              **({"ops": item["ops"]} if dry_run else {})} for item in patches]
        if dry_run:
            result["dry_run"] = True
        return result
    applied = []
    for position, item in enumerate(patches):
        try:
            answer = client.call("patch", ops=item["ops"], base_revision=revision, label=item["label"], author=author)
        except ValidationError as exc:
            exc.sync = {"revision_before": revision, "applied": applied,
                        "failed": {"label": item["label"], "pattern": item["pattern"], "op_count": len(item["ops"])},
                        "not_applied": [{"label": rest["label"], "pattern": rest["pattern"]}
                                        for rest in patches[position + 1:]],
                        "not_synced": planned["not_synced"]}
            raise
        applied.append({"label": item["label"], "pattern": item["pattern"], "op_count": len(item["ops"]),
                        "revision": answer.get("revision"), "changed": answer.get("changed", True)})
    after_revision, after = read_session(client)
    left = [item for item in mismatches(target, after) if item["key"] not in planned["expected"]]
    result.update(revision_after=after_revision, patches=applied, verified=not left)
    if left:
        result["mismatches"] = [_public(item) for item in left[:MISMATCH_LIMIT]]
        result["mismatch_count"] = len(left)
    return result
