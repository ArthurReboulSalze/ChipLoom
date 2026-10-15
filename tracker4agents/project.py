"""Compact, sparse JSON score and reproducible sample recipe interchange."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

from .model import (
    EMPTY, PROFILE, Module, Pattern, Sample, ValidationError, ascii_field, cell,
    require_int, validate, validate_cell, validate_sample,
)
from .synth import from_recipe

SCHEMA = "tracker4agents.project.v1"
MAX_PROJECT_BYTES = 12_000_000


def atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_json(path: Path, value: object) -> None:
    atomic_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8"))


def read_json(path: Path) -> object:
    if path.stat().st_size > MAX_PROJECT_BYTES:
        raise ValidationError("Projet JSON trop grand pour le prototype.")
    return json.loads(path.read_text(encoding="utf-8"))


def _keys(value: object, allowed: set[str], label: str) -> dict:
    if not isinstance(value, dict):
        raise ValidationError(f"{label}: objet JSON attendu.")
    unknown = set(value) - allowed
    if unknown:
        raise ValidationError(f"{label}: champs inconnus {sorted(unknown)}.")
    return value


def _sample_from_dict(item: object, index: int) -> Sample:
    item = _keys(item, {"name", "volume", "finetune", "recipe", "pcm", "loop_start", "loop_length"}, f"Sample {index}")
    name, volume, tune = item.get("name", ""), item.get("volume", 40), item.get("finetune", 0)
    if "recipe" in item:
        if any(key in item for key in ("pcm", "loop_start", "loop_length")):
            raise ValidationError("Une recette définit son PCM et sa boucle ; ne les duplique pas.")
        sample = from_recipe(name, item["recipe"], volume, tune)
    else:
        pcm = item.get("pcm")
        if not isinstance(pcm, list) or len(pcm) > 65_534:
            raise ValidationError(f"Sample {index}: liste PCM manquante ou trop longue.")
        sample = Sample(name, tuple(pcm), volume, tune, item.get("loop_start", 0), item.get("loop_length", 0))
    return sample


def from_dict(data: object) -> Module:
    data = _keys(data, {"schema", "profile", "title", "samples", "patterns", "orders", "metadata"}, "Projet")
    if data.get("schema") != SCHEMA or data.get("profile") != PROFILE:
        raise ValidationError(f"Schéma attendu : {SCHEMA}, profil : {PROFILE}.")
    samples_data, patterns_data, orders = data.get("samples"), data.get("patterns"), data.get("orders")
    if not isinstance(samples_data, list) or not 1 <= len(samples_data) <= 31:
        raise ValidationError("samples: tableau de 1 à 31 emplacements attendu.")
    if not isinstance(patterns_data, list) or not 1 <= len(patterns_data) <= 64:
        raise ValidationError("patterns: tableau de 1 à 64 patterns attendu.")
    if not isinstance(orders, list):
        raise ValidationError("orders: tableau attendu.")
    samples = []
    for index, item in enumerate(samples_data, 1):
        sample = _sample_from_dict(item, index)
        samples.append(sample)
    patterns = []
    for index, item in enumerate(patterns_data):
        item = _keys(item, {"name", "events"}, f"Pattern {index}")
        events = item.get("events")
        if not isinstance(events, list) or len(events) > 256:
            raise ValidationError(f"Pattern {index}: liste d'événements invalide (256 maximum).")
        pattern = Pattern(item.get("name", f"Pattern {index:02X}"))
        if not isinstance(pattern.name, str):
            raise ValidationError(f"Pattern {index}: nom textuel attendu.")
        seen = {}
        for event_index, event in enumerate(events):
            event = _keys(event, {"row", "channel", "note", "sample", "effect"}, f"Événement du pattern {index}")
            row, channel = event.get("row"), event.get("channel")
            value = cell(event.get("note"), event.get("sample", 0), event.get("effect", "000"))
            # Check coordinates before hashing and preserve the first writer.
            require_int(row, "row", 0, 63)
            require_int(channel, "channel", 0, 3)
            if (row, channel) in seen:
                previous_index, previous = seen[row, channel]
                raise ValidationError(f"Pattern {index}: cellule ({row}, {channel}) définie deux fois — "
                                      f"events[{previous_index}] existant: {previous.text()} / "
                                      f"events[{event_index}] nouveau: {value.text()}.")
            seen[row, channel] = event_index, value
            pattern.put(row, channel, value)
        patterns.append(pattern)
    metadata = data.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ValidationError("metadata: objet JSON attendu.")
    module = Module(data.get("title", ""), samples, patterns, orders, metadata)
    validate(module)
    return module


def to_dict(module: Module, recipes: bool = True) -> dict:
    validate(module)
    samples = []
    for sample in module.samples:
        entry = {"name": sample.name, "volume": sample.volume, "finetune": sample.finetune}
        if recipes and sample.recipe is not None:
            entry["recipe"] = sample.recipe
        else:
            entry.update(pcm=list(sample.pcm), loop_start=sample.loop_start, loop_length=sample.loop_length)
        samples.append(entry)
    patterns = []
    for pattern in module.patterns:
        events = []
        for (row, channel), value in sorted(pattern.cells.items()):
            if value == EMPTY:
                continue
            entry = {"row": row, "channel": channel}
            if value.note:
                entry["note"] = value.note
            if value.sample:
                entry["sample"] = value.sample
            if value.command or value.param:
                entry["effect"] = value.effect
            events.append(entry)
        patterns.append({"name": pattern.name, "events": events})
    return {"schema": SCHEMA, "profile": PROFILE, "title": module.title,
            "samples": samples, "patterns": patterns, "orders": module.orders,
            "metadata": module.metadata}


def load(path: Path) -> Module:
    return from_dict(read_json(path))


def diagnose(data: object) -> list[dict]:
    """Read-only independent diagnostics; never repair or export partial input.

    Collect one primary error per field/sample/event, plus collisions. Invalid
    containers cannot be descended into; dependent playback checks run only
    after all structural checks pass. Uses the same validators as normal load.
    """
    errors = []

    def check(path, operation):
        try:
            return operation()
        except (ValueError, TypeError, OverflowError) as exc:
            errors.append({"path": path, "message": str(exc)})
            return None

    if not isinstance(data, dict):
        return [{"path": "$", "message": "Projet: objet JSON attendu."}]
    check("$", lambda: _keys(data, {"schema", "profile", "title", "samples", "patterns", "orders", "metadata"}, "Projet"))
    for key, expected in (("schema", SCHEMA), ("profile", PROFILE)):
        if data.get(key) != expected:
            errors.append({"path": key, "message": f"Valeur attendue : {expected}."})
    check("title", lambda: ascii_field(data.get("title", ""), 20, "Titre MOD"))
    if not isinstance(data.get("metadata", {}), dict):
        errors.append({"path": "metadata", "message": "metadata: objet JSON attendu."})
    containers = {}
    for key, limit in (("samples", 31), ("patterns", 64), ("orders", 128)):
        value = data.get(key)
        if not isinstance(value, list) or not 1 <= len(value) <= limit:
            errors.append({"path": key, "message": f"{key}: tableau de 1 à {limit} entrées attendu."})
        else:
            containers[key] = value
    samples, patterns, orders = (containers.get(key, []) for key in ("samples", "patterns", "orders"))
    for index, item in enumerate(samples):
        def inspect_sample(item=item, index=index):
            validate_sample(_sample_from_dict(item, index + 1), index + 1)
        check(f"samples[{index}]", inspect_sample)
    if patterns and orders:
        before = len(errors)
        for index, value in enumerate(orders):
            check(f"orders[{index}]", lambda value=value, index=index:
                  require_int(value, f"orders[{index}]", 0, len(patterns) - 1))
        if len(errors) == before and max(orders) != len(patterns) - 1:
            errors.append({"path": "orders", "message": "Le dernier pattern stocké doit apparaître dans la liste d'ordres."})
    for index, item in enumerate(patterns):
        path = f"patterns[{index}]"
        check(path, lambda item=item: _keys(item, {"name", "events"}, path))
        if not isinstance(item, dict):
            continue
        if not isinstance(item.get("name", ""), str):
            errors.append({"path": path + ".name", "message": "Nom textuel attendu."})
        events = item.get("events")
        if not isinstance(events, list) or len(events) > 256:
            errors.append({"path": path + ".events", "message": "Liste d'événements invalide (256 maximum)."})
            continue
        seen = {}
        for event_index, event in enumerate(events):
            location = f"{path}.events[{event_index}]"
            def inspect_event(event=event):
                _keys(event, {"row", "channel", "note", "sample", "effect"}, location)
                row, channel = event.get("row"), event.get("channel")
                require_int(row, "row", 0, 63)
                require_int(channel, "channel", 0, 3)
                if (row, channel) in seen:
                    previous_index, previous = seen[row, channel]
                    errors.append({"path": location, "message":
                        f"Pattern {index}: cellule ({row}, {channel}) définie deux fois — "
                        f"events[{previous_index}] existant: {previous!r} / events[{event_index}] nouveau: {event!r}."})
                else:
                    seen[row, channel] = event_index, event
                value = cell(event.get("note"), event.get("sample", 0), event.get("effect", "000"))
                validate_cell(value, row, channel, index, len(samples) if samples else 31, len(orders) if orders else 128)
            check(location, inspect_event)
    if not errors:
        check("$", lambda: from_dict(data))
    return errors
