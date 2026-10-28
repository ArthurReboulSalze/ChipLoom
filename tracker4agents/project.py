"""Compact, sparse JSON score and reproducible sample recipe interchange.

Two schemas share one model. v1 stores PCM as a JSON list of signed integers;
v2 (the default for new files) stores the same bytes as base64 plus a SHA-256
that is verified on load. Everything else is identical.

Beyond the four-channel MOD: a top-level `channels` (default 4; profile
`protracker-nch-pal-v1` when it is not 4) and, for an XM, `format: "xm"` with profile
`fasttracker2-xm-v1`. XM header values and instrument extras live in `metadata.xm`.
Grid rows hold one cell per channel; an XM cell reads `NOTE II VV EEE`.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile

from .errors import error_code
from .model import (
    EMPTY, FORMATS, MAX_PATTERNS, MOD_MAX_CHANNELS, MOD_PROFILE_N, PROFILE, XM_PROFILE, Cell, Module, Pattern, Sample,
    ValidationError, ascii_field, cell, require_int, validate, validate_cell, validate_sample,
)
from .patch import cell_text, row_cells
from .synth import from_recipe

SCHEMA_V1 = "tracker4agents.project.v1"
SCHEMA_V2 = "tracker4agents.project.v2"
SCHEMA = SCHEMA_V2
SCHEMAS = {SCHEMA_V1: 1, SCHEMA_V2: 2}
MAX_PROJECT_BYTES = 12_000_000
MAX_PCM_BYTES = 65_534
MAX_PCM_BASE64 = (MAX_PCM_BYTES + 2) // 3 * 4

_SAMPLE_COMMON = {"name", "volume", "finetune", "recipe", "loop_start", "loop_length",
                  "bits", "loop_mode", "panning", "relative_note"}
SAMPLE_KEYS = {1: _SAMPLE_COMMON | {"pcm"}, 2: _SAMPLE_COMMON | {"pcm_base64", "pcm_sha256"}}
_TOP_KEYS = {"schema", "profile", "title", "samples", "patterns", "orders", "metadata", "format", "channels"}
PROFILES = {"mod": (PROFILE, MOD_PROFILE_N), "xm": (XM_PROFILE,)}
LIMITS = {"mod": {"samples": 31, "patterns": MAX_PATTERNS, "orders": 128, "rows": 64},
          "xm": {"samples": 128, "patterns": 256, "orders": 256, "rows": 256}}
MAX_XM_PCM_BYTES = 2 * 1_048_576
EMPTY_HINT = " A blank project (one empty slot) comes from `chiploom new` (MCP tool new_project)."


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


def _line(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(", ", ": "))


def _project_text(value: dict) -> str:
    """Keep scores compact and diff-friendly: one line per sample and per event."""
    parts = []
    for key, item in value.items():
        if key == "samples" and isinstance(item, list):
            body = ",\n".join(f"    {_line(sample)}" for sample in item)
            parts.append(f'  "samples": [\n{body}\n  ]' if item else '  "samples": []')
        elif key == "patterns" and isinstance(item, list):
            patterns = []
            for pattern in item:
                if isinstance(pattern, dict) and isinstance(pattern.get("events"), list):
                    header = _line({k: v for k, v in pattern.items() if k != "events"})[:-1]
                    separator = ", " if header != "{" else ""
                    events = ",\n".join(f"      {_line(event)}" for event in pattern["events"])
                    body = f"[\n{events}\n    ]" if events else "[]"
                    patterns.append(f'    {header}{separator}"events": {body}}}')
                elif isinstance(pattern, dict) and isinstance(pattern.get("rows"), dict):
                    header = _line({k: v for k, v in pattern.items() if k != "rows"})[:-1]
                    separator = ", " if header != "{" else ""
                    rows = ",\n".join(f"      {_line(key)}: {_line(line)}" for key, line in pattern["rows"].items())
                    body = f"{{\n{rows}\n    }}" if rows else "{}"
                    patterns.append(f'    {header}{separator}"rows": {body}}}')
                else:
                    patterns.append(f"    {_line(pattern)}")
            parts.append('  "patterns": [\n' + ",\n".join(patterns) + "\n  ]" if patterns else '  "patterns": []')
        else:
            text = json.dumps(item, ensure_ascii=False, indent=2, allow_nan=False).replace("\n", "\n  ")
            parts.append(f"  {json.dumps(key, ensure_ascii=False)}: {text}")
    return "{\n" + ",\n".join(parts) + "\n}"


def dumps(value: object) -> str:
    """Projects get the compact score layout; everything else stays indented JSON."""
    if (isinstance(value, dict) and str(value.get("schema", "")).startswith("tracker4agents.project")
            and isinstance(value.get("patterns"), list)):
        return _project_text(value)
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)


def write_json(path: Path, value: object) -> None:
    atomic_bytes(path, (dumps(value) + "\n").encode("utf-8"))


def read_json(path: Path) -> object:
    if path.stat().st_size > MAX_PROJECT_BYTES:
        raise ValidationError("Projet JSON trop grand pour le prototype.", "FILE_TOO_LARGE")
    return json.loads(path.read_text(encoding="utf-8"))


def schema_version(data: object) -> int | None:
    """1 or 2 for a recognized `schema` string, otherwise None."""
    schema = data.get("schema") if isinstance(data, dict) else None
    return SCHEMAS.get(schema) if isinstance(schema, str) else None


def _keys(value: object, allowed: set[str], label: str) -> dict:
    if not isinstance(value, dict):
        raise ValidationError(f"{label}: objet JSON attendu.", "SCHEMA")
    unknown = set(value) - allowed
    if unknown:
        raise ValidationError(f"{label}: champs inconnus {sorted(unknown)}.", "UNKNOWN_FIELD")
    return value


def _pcm_from_base64(item: dict, label: str, bits: int = 8, limit: int = MAX_PCM_BYTES) -> tuple[int, ...]:
    """Decode a hash-checked `pcm_base64`: signed bytes, or little-endian int16 for a 16-bit XM sample."""
    encoded = item.get("pcm_base64")
    if not isinstance(encoded, str) or len(encoded) > (limit + 2) // 3 * 4:
        raise ValidationError(f"{label}: pcm_base64 must be a base64 string of at most {limit} bytes.",
                              "SAMPLE_PCM")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except ValueError as exc:  # binascii.Error is a ValueError
        raise ValidationError(f"{label}: pcm_base64 is not valid base64.", "SAMPLE_PCM") from exc
    digest = item.get("pcm_sha256")
    if not isinstance(digest, str):
        raise ValidationError(f"{label}: pcm_sha256 (hex SHA-256 of the raw PCM bytes) is required with pcm_base64.",
                              "SAMPLE_PCM_HASH")
    if hashlib.sha256(raw).hexdigest() != digest.lower():
        raise ValidationError(f"{label}: pcm_sha256 does not match the decoded PCM bytes; the file is damaged "
                              "or was edited without updating the hash.", "SAMPLE_PCM_HASH")
    if bits == 16:
        if len(raw) % 2:
            raise ValidationError(f"{label}: a 16-bit sample holds an even number of bytes.", "SAMPLE_PCM")
        return struct.unpack(f"<{len(raw) // 2}h", raw)
    return tuple(value - 256 if value > 127 else value for value in raw)


def _sample_from_dict(item: object, index: int, version: int = 1, fmt: str = "mod") -> Sample:
    label = f"Sample {index}"
    if version == 2 and isinstance(item, dict) and "pcm" in item:
        raise ValidationError(f"{label}: 'pcm' belongs to schema v1; schema v2 uses pcm_base64 and pcm_sha256.",
                              "UNKNOWN_FIELD")
    if version == 1 and isinstance(item, dict) and ("pcm_base64" in item or "pcm_sha256" in item):
        raise ValidationError(f"{label}: pcm_base64 belongs to schema v2; schema v1 uses a 'pcm' list.",
                              "UNKNOWN_FIELD")
    item = _keys(item, SAMPLE_KEYS[version], label)
    name, volume, tune = item.get("name", ""), item.get("volume", 64 if fmt == "xm" else 40), item.get("finetune", 0)
    pcm_keys = ("pcm", "pcm_base64", "pcm_sha256", "loop_start", "loop_length")
    extras = {key: item[key] for key in ("bits", "loop_mode", "panning", "relative_note") if key in item}
    bits = extras.get("bits", 8)
    if bits not in (8, 16):
        raise ValidationError(f"{label}: bits must be 8 or 16.", "SAMPLE_PCM")
    if fmt != "xm" and extras:
        raise ValidationError(f"{label}: {sorted(extras)} are XM-only sample fields.", "MOD_XM_FIELD")
    if "recipe" in item:
        if any(key in item for key in pcm_keys):
            raise ValidationError("Une recette définit son PCM et sa boucle ; ne les duplique pas.", "RECIPE_INVALID")
        sample = from_recipe(name, item["recipe"], volume, tune)
        for key, value in extras.items():
            setattr(sample, key, value)
        return sample
    limit = MAX_XM_PCM_BYTES if fmt == "xm" else MAX_PCM_BYTES
    if version == 2:
        pcm = _pcm_from_base64(item, label, bits, limit)
    else:
        pcm = item.get("pcm")
        if not isinstance(pcm, list) or len(pcm) > limit:
            raise ValidationError(f"Sample {index}: liste PCM manquante ou trop longue.", "SAMPLE_PCM")
        pcm = tuple(pcm)
    sample = Sample(name, pcm, volume, tune, item.get("loop_start", 0), item.get("loop_length", 0))
    for key, value in extras.items():
        setattr(sample, key, value)
    return sample


def _grid_rows(rows: object, label: str, fmt: str = "mod", channels: int = 4) -> list[tuple[int, list]]:
    """Parse v2 pattern rows: {"00": "C-2 01 ... | --- -- ... | --- -- ... | --- -- ..."}.

    One cell per channel. A MOD has rows 00-3F; an XM rows 00-FF (the pattern's `length` bounds them)."""
    last = "3F" if fmt == "mod" else "FF"
    if not isinstance(rows, dict):
        raise ValidationError(f"{label}: 'rows' must map hexadecimal row numbers (00-{last}) to grid lines.", "PATTERNS")
    result = []
    for key, line in rows.items():
        if not isinstance(key, str) or len(key) != 2 or any(char not in "0123456789ABCDEFabcdef" for char in key):
            raise ValidationError(f"{label}: row key {key!r} must be two hexadecimal digits, 00 to {last}.", "PATTERNS")
        row = int(key, 16)
        if fmt == "mod" and row > 63:
            raise ValidationError(f"{label}: row {key} is past 3F (63).", "PATTERNS")
        try:
            result.append((row, row_cells(line, channels, fmt)))
        except ValidationError as exc:
            raise ValidationError(f"{label}, row {key}: {exc}", exc.code) from exc
    return result


def _kind(data: dict) -> tuple[str, int]:
    """(format, channels) of a project dict; the profile, `format` and `channels` must agree."""
    profile = data.get("profile")
    fmt = data.get("format", "xm" if profile == XM_PROFILE else "mod")
    if fmt not in FORMATS:
        raise ValidationError(f"format: expected one of {', '.join(FORMATS)}.", "SCHEMA")
    channels = data.get("channels", 4)
    if type(channels) is not int:
        raise ValidationError("channels: integer expected.", "CHANNELS")
    if profile not in PROFILES[fmt]:
        raise ValidationError(f"Expected profile {' or '.join(PROFILES[fmt])} for format {fmt}.", "SCHEMA")
    if fmt == "mod" and (channels == 4) != (profile == PROFILE):
        raise ValidationError(f"Profile {PROFILE} is for four channels and {MOD_PROFILE_N} for any other count.",
                              "SCHEMA")
    require_int(channels, "channels", 2, MOD_MAX_CHANNELS, "CHANNELS")
    return fmt, channels


def from_dict(data: object) -> Module:
    data = _keys(data, _TOP_KEYS, "Projet")
    version = schema_version(data)
    if version is None or data.get("profile") not in (PROFILE, MOD_PROFILE_N, XM_PROFILE):
        raise ValidationError(f"Expected schema {SCHEMA_V2} (or {SCHEMA_V1}) and profile {PROFILE}.", "SCHEMA")
    fmt, channels = _kind(data)
    limits = LIMITS[fmt]
    samples_data, patterns_data, orders = data.get("samples"), data.get("patterns"), data.get("orders")
    if not isinstance(samples_data, list) or not 1 <= len(samples_data) <= limits["samples"]:
        raise ValidationError(f"samples: array of 1 to {limits['samples']} slots expected.{EMPTY_HINT}", "SAMPLE_SLOT")
    if not isinstance(patterns_data, list) or not 1 <= len(patterns_data) <= limits["patterns"]:
        raise ValidationError(f"patterns: array of 1 to {limits['patterns']} patterns expected.", "PATTERNS")
    if not isinstance(orders, list):
        raise ValidationError("orders: tableau attendu.", "ORDERS")
    samples = []
    for index, item in enumerate(samples_data, 1):
        sample = _sample_from_dict(item, index, version, fmt)
        samples.append(sample)
    patterns = []
    for index, item in enumerate(patterns_data):
        allowed = {"name", "events", "rows", "length"} if version == 2 else {"name", "events", "length"}
        item = _keys(item, allowed, f"Pattern {index}")
        pattern = Pattern(item.get("name", f"Pattern {index:02X}"))
        if not isinstance(pattern.name, str):
            raise ValidationError(f"Pattern {index}: nom textuel attendu.", "TEXT_TYPE")
        if "length" in item:
            pattern.rows = require_int(item["length"], f"Pattern {index} length", 1, limits["rows"], "PATTERNS")
        if "rows" in item:
            if "events" in item:
                raise ValidationError(f"Pattern {index}: use either 'rows' or 'events', not both.", "SCHEMA")
            for row, values in _grid_rows(item["rows"], f"Pattern {index}", fmt, channels):
                for channel, value in enumerate(values):
                    pattern.put(row, channel, value)
            patterns.append(pattern)
            continue
        events = item.get("events")
        if not isinstance(events, list) or len(events) > pattern.rows * channels:
            raise ValidationError(f"Pattern {index}: liste d'événements invalide ({pattern.rows * channels} maximum).",
                                  "PATTERNS")
        seen = {}
        for event_index, event in enumerate(events):
            event = _keys(event, {"row", "channel", "note", "sample", "effect", "volume"}, f"Événement du pattern {index}")
            row, channel = event.get("row"), event.get("channel")
            value = cell(event.get("note"), event.get("sample", 0), event.get("effect", "000"), fmt,
                         event.get("volume", 0))
            # Check coordinates before hashing and preserve the first writer.
            require_int(row, "row", 0, pattern.rows - 1)
            require_int(channel, "channel", 0, channels - 1)
            if (row, channel) in seen:
                previous_index, previous = seen[row, channel]
                raise ValidationError(f"Pattern {index}: cellule ({row}, {channel}) définie deux fois — "
                                      f"events[{previous_index}] existant: {previous.text()} / "
                                      f"events[{event_index}] nouveau: {value.text()}.", "CELL_DUPLICATE")
            seen[row, channel] = event_index, value
            pattern.put(row, channel, value)
        patterns.append(pattern)
    metadata = data.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ValidationError("metadata: objet JSON attendu.", "SCHEMA")
    module = Module(data.get("title", ""), samples, patterns, orders, metadata, channels, fmt)
    validate(module)
    return module


def to_dict(module: Module, recipes: bool = True, schema: int = 2, layout: str = "rows") -> dict:
    """Serialize to a project dict. `schema=1` reproduces the original list-of-ints output exactly.

    Schema v2 writes each pattern as grid `rows` by default; `layout="events"` keeps sparse events.
    """
    if type(schema) is not int or schema not in (1, 2):
        raise ValidationError("schema: 1 or 2 expected.", "SCHEMA")
    if layout not in ("rows", "events"):
        raise ValidationError("layout: 'rows' or 'events' expected.", "SCHEMA")
    validate(module)
    fmt = module.format
    samples = []
    for sample in module.samples:
        entry = {"name": sample.name, "volume": sample.volume, "finetune": sample.finetune}
        if recipes and sample.recipe is not None:
            entry["recipe"] = sample.recipe
        elif schema == 1:
            entry.update(pcm=list(sample.pcm), loop_start=sample.loop_start, loop_length=sample.loop_length)
        else:
            raw = (struct.pack(f"<{len(sample.pcm)}h", *sample.pcm) if sample.bits == 16
                   else bytes(value & 255 for value in sample.pcm))
            entry.update(pcm_base64=base64.b64encode(raw).decode("ascii"), pcm_sha256=hashlib.sha256(raw).hexdigest(),
                         loop_start=sample.loop_start, loop_length=sample.loop_length)
        # XM-only sample properties appear only when they differ from the MOD sample, so a MOD
        # project is written exactly as before.
        for key, default in (("bits", 8), ("loop_mode", "forward"), ("panning", 128), ("relative_note", 0)):
            if getattr(sample, key) != default:
                entry[key] = getattr(sample, key)
        samples.append(entry)
    patterns = []
    for pattern in module.patterns:
        length = {} if pattern.rows == 64 else {"length": pattern.rows}
        if schema == 2 and layout == "rows":
            rows = {}
            for row in range(pattern.rows):
                values = [pattern.get(row, channel) for channel in range(module.channels)]
                if any(value != EMPTY for value in values):
                    rows[f"{row:02X}"] = " | ".join(cell_text(value, fmt) for value in values)
            patterns.append({"name": pattern.name, **length, "rows": rows})
            continue
        events = []
        for (row, channel), value in sorted(pattern.cells.items()):
            if value == EMPTY:
                continue
            entry = {"row": row, "channel": channel}
            if value.note:
                entry["note"] = value.note
            if value.sample:
                entry["sample"] = value.sample
            if value.volume:
                entry["volume"] = value.volume
            if value.command or value.param:
                entry["effect"] = value.effect
            events.append(entry)
        patterns.append({"name": pattern.name, **length, "events": events})
    head: dict = {"schema": SCHEMA_V1 if schema == 1 else SCHEMA_V2}
    if fmt == "xm":
        head.update(profile=XM_PROFILE, format="xm", channels=module.channels)
    elif module.channels != 4:
        head.update(profile=MOD_PROFILE_N, channels=module.channels)
    else:
        head.update(profile=PROFILE)
    return {**head, "title": module.title,
            "samples": samples, "patterns": patterns, "orders": module.orders,
            "metadata": module.metadata}


def load(path: Path) -> Module:
    return from_dict(read_json(path))


def _validate_cell(fmt: str, value: Cell, row: int, channel: int, pattern_index: int, sample_count: int,
                   order_count: int, channels: int, rows: int) -> None:
    if fmt == "xm":
        from .xm import validate_xm_cell
        validate_xm_cell(value, row, channel, pattern_index, sample_count, order_count, channels, rows)
    else:
        validate_cell(value, row, channel, pattern_index, sample_count, order_count, channels, rows)


def diagnose(data: object) -> list[dict]:
    """Read-only independent diagnostics; never repair or export partial input.

    Collect one primary error per field/sample/event, plus collisions. Invalid
    containers cannot be descended into; dependent playback checks run only
    after all structural checks pass. Uses the same validators as normal load.
    Each entry is {"path", "code", "message"}; messages keep the core wording
    (the CLI localizes them). Supports schema v1 and v2.
    """
    errors = []

    def add(path, message, code):
        errors.append({"path": path, "code": code, "message": message})

    def check(path, operation):
        try:
            return operation()
        except (ValueError, TypeError, OverflowError) as exc:
            code = error_code(exc) if isinstance(exc, ValueError) else "INVALID_VALUE"
            add(path, str(exc), code)
            return None

    if not isinstance(data, dict):
        return [{"path": "$", "code": "SCHEMA", "message": "Projet: objet JSON attendu."}]
    check("$", lambda: _keys(data, _TOP_KEYS, "Projet"))
    version = schema_version(data)
    if version is None:
        add("schema", f"Expected schema {SCHEMA_V2} (or {SCHEMA_V1}).", "SCHEMA")
    fmt, channels = "mod", 4
    kind = check("$", lambda: _kind(data)) if data.get("profile") in (PROFILE, MOD_PROFILE_N, XM_PROFILE) else None
    if kind is not None:
        fmt, channels = kind
    elif data.get("profile") not in (PROFILE, MOD_PROFILE_N, XM_PROFILE):
        add("profile", f"Expected profile {PROFILE}.", "SCHEMA")
    limits = LIMITS[fmt]
    check("title", lambda: ascii_field(data.get("title", ""), 20, "Titre MOD"))
    if not isinstance(data.get("metadata", {}), dict):
        add("metadata", "metadata: objet JSON attendu.", "SCHEMA")
    containers = {}
    for key, limit, code in (("samples", limits["samples"], "SAMPLE_SLOT"), ("patterns", limits["patterns"], "PATTERNS"),
                             ("orders", limits["orders"], "ORDERS")):
        value = data.get(key)
        if not isinstance(value, list) or not 1 <= len(value) <= limit:
            add(key, f"{key}: array of 1 to {limit} entries expected." + (EMPTY_HINT if key == "samples" else ""), code)
        else:
            containers[key] = value
    samples, patterns, orders = (containers.get(key, []) for key in ("samples", "patterns", "orders"))
    if version is None:  # Unknown schema string: judge samples by the encoding they use.
        version = 2 if any(isinstance(item, dict) and "pcm_base64" in item for item in samples) else 1
    for index, item in enumerate(samples):
        def inspect_sample(item=item, index=index):
            sample = _sample_from_dict(item, index + 1, version, fmt)
            if fmt == "xm":
                from .xm import validate_xm_sample
                validate_xm_sample(sample, index + 1)
            else:
                validate_sample(sample, index + 1)
        check(f"samples[{index}]", inspect_sample)
    if patterns and orders:
        before = len(errors)
        for index, value in enumerate(orders):
            check(f"orders[{index}]", lambda value=value, index=index:
                  require_int(value, f"orders[{index}]", 0, len(patterns) - 1, "ORDERS"))
        if len(errors) == before and fmt == "mod" and max(orders) != len(patterns) - 1:
            add("orders", "Le dernier pattern stocké doit apparaître dans la liste d'ordres.", "ORDERS")
    for index, item in enumerate(patterns):
        path = f"patterns[{index}]"
        allowed = {"name", "events", "rows", "length"} if schema_version(data) == 2 else {"name", "events", "length"}
        check(path, lambda item=item, allowed=allowed: _keys(item, allowed, path))
        if not isinstance(item, dict):
            continue
        if not isinstance(item.get("name", ""), str):
            add(path + ".name", "Nom textuel attendu.", "TEXT_TYPE")
        rows_here = 64
        if "length" in item:
            rows_here = check(path + ".length", lambda: require_int(item["length"], f"Pattern {index} length", 1,
                                                                    limits["rows"], "PATTERNS")) or 64
        if "rows" in item and "rows" in allowed:
            if "events" in item:
                add(path, "Use either 'rows' or 'events', not both.", "SCHEMA")
                continue
            rows = item["rows"]
            if not isinstance(rows, dict):
                add(path + ".rows", f"'rows' must map hexadecimal row numbers (00-{'3F' if fmt == 'mod' else 'FF'}) "
                    "to grid lines.", "PATTERNS")
                continue
            for key, line in rows.items():
                location = f"{path}.rows[{key!r}]"

                def inspect_row(key=key, line=line, rows_here=rows_here):
                    for row, values in _grid_rows({key: line}, f"Pattern {index}", fmt, channels):
                        for channel, value in enumerate(values):
                            _validate_cell(fmt, value, row, channel, index, len(samples) if samples else limits["samples"],
                                           len(orders) if orders else limits["orders"], channels, rows_here)
                check(location, inspect_row)
            continue
        events = item.get("events")
        if not isinstance(events, list) or len(events) > rows_here * channels:
            add(path + ".events", f"Liste d'événements invalide ({rows_here * channels} maximum).", "PATTERNS")
            continue
        seen = {}
        for event_index, event in enumerate(events):
            location = f"{path}.events[{event_index}]"
            def inspect_event(event=event, rows_here=rows_here):
                _keys(event, {"row", "channel", "note", "sample", "effect", "volume"}, location)
                row, channel = event.get("row"), event.get("channel")
                require_int(row, "row", 0, rows_here - 1)
                require_int(channel, "channel", 0, channels - 1)
                if (row, channel) in seen:
                    previous_index, previous = seen[row, channel]
                    add(location,
                        f"Pattern {index}: cellule ({row}, {channel}) définie deux fois — "
                        f"events[{previous_index}] existant: {previous!r} / events[{event_index}] nouveau: {event!r}.",
                        "CELL_DUPLICATE")
                else:
                    seen[row, channel] = event_index, event
                value = cell(event.get("note"), event.get("sample", 0), event.get("effect", "000"), fmt,
                             event.get("volume", 0))
                _validate_cell(fmt, value, row, channel, index, len(samples) if samples else limits["samples"],
                               len(orders) if orders else limits["orders"], channels, rows_here)
            check(location, inspect_event)
    if not errors:
        check("$", lambda: from_dict(data))
    return errors
