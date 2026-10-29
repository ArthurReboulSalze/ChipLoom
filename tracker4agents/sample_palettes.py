"""Palettes of a sample bank: which entries a reference song played together, and how that song is built.

`palettes.json` holds one palette per readable source module, with a neutral ID (`PAL-0001`), the format,
channel count, initial speed and BPM, the duration, the bank entries it uses (role, confidence, how much the
song plays each), the role of every channel with the entries it plays, and the structure (`usage.study`:
order count, distinct patterns, sections as start order / length / active channel count, channel entry
order). No notes, no names, no pattern data: the private provenance alone maps a palette to its source.

`use_palette` lays a palette into a library-mode project in role order (drums, bass, chords, leads, pads,
textures, effects) through `SampleLibrary.insert`, so an agent starts from samples chosen to go together.
"""
from __future__ import annotations

from pathlib import Path

from . import project
from .model import Module, ValidationError, require_int

SCHEMA = "chiploom.sample-palettes.v1"
MAX_PALETTES = 10_000
NOTE = ("One palette per reference module: the bank entries it plays, their scored roles and the song's structure. "
        "Roles are evidence-based suggestions to confirm by listening; the structure holds counts and lengths, never "
        "notes.")


def read_palettes(bank: Path) -> list[dict]:
    value = project.read_json(Path(bank) / "palettes.json")
    if not isinstance(value, dict) or value.get("schema") != SCHEMA or not isinstance(value.get("palettes"), list) \
            or len(value["palettes"]) > MAX_PALETTES:
        raise ValidationError("Unsupported palettes file.", "SAMPLE_LIBRARY")
    for palette in value["palettes"]:
        if not isinstance(palette, dict) or not isinstance(palette.get("id"), str) \
                or not isinstance(palette.get("entries"), list):
            raise ValidationError("Invalid palette entry.", "SAMPLE_LIBRARY")
    return value["palettes"]


def write_palettes(bank: Path, palettes: list[dict]) -> None:
    project.write_json(Path(bank) / "palettes.json", {"schema": SCHEMA, "note": NOTE, "palettes": palettes})


def palette_summary(palette: dict) -> str:
    from .usage import role_summary
    return role_summary([entry["role"] for entry in palette["entries"] if entry["note_starts"] and entry["role"]])


def build_palette(palette_id: str, module: Module, study: dict, entry_ids: dict[int, list[tuple[str, bool]]],
                  occurrences: dict[str, dict]) -> dict:
    """The public palette of one studied module. `entry_ids` maps each slot to `(bank entry, played)` pairs: an
    XM instrument with several samples has several entries, and the one its key map plays carries the slot's
    song evidence. `occurrences` (private, by occurrence key) give each entry's role in this module."""
    from .convert import first_row_timing
    from .model import xm_profile
    slots = {slot["slot"]: slot for slot in study["slots"]}
    by_entry = {item["entry_id"]: item for item in occurrences.values()}
    total_starts = sum(slot["note_starts"] for slot in slots.values()) or 1
    entries = []
    slot_entries: dict[int, list[str]] = {}
    for slot in sorted(entry_ids):
        facts = slots.get(slot)
        for entry_id, played in entry_ids[slot]:
            occurrence = by_entry.get(entry_id, {})
            starts = facts["note_starts"] if played and facts else 0
            entries.append({"id": entry_id, "role": occurrence.get("role"),
                            "confidence": occurrence.get("role_confidence"), "note_starts": starts,
                            "share": round(starts / total_starts, 3),
                            "channels": facts["channels"] if played and facts else []})
            if played and facts:
                slot_entries.setdefault(slot, []).append(entry_id)
    layout = []
    for channel in study["channel_details"]:
        played = [entry_id for slot in channel["slots"] for entry_id in slot_entries.get(slot, [])]
        layout.append({"channel": channel["channel"], "role": channel["role"], "roles": channel["roles"],
                       "entries": played, "note_ons": channel["note_ons"],
                       "notes_per_second": channel["notes_per_second"],
                       "sounding_fraction": channel["sounding_fraction"]})
    structure = study["structure"]
    if module.format == "xm":
        info = xm_profile(module)
        speed, bpm = info.get("default_speed", 6), info.get("default_bpm", 125)
    else:
        timing = first_row_timing(module)
        speed, bpm = timing.get("speed", 6), timing.get("bpm", 125)
    palette = {
        "id": palette_id, "format": module.format, "channels": module.channels, "speed": speed, "bpm": bpm,
        "duration_seconds": structure["duration_seconds"], "entries": entries, "channel_layout": layout,
        "structure": {"orders": structure["orders"], "orders_played": structure["orders_played"],
                      "distinct_patterns": structure["distinct_patterns"],
                      "sections": [{"start_order": section["start_order"], "orders": section["orders"],
                                    "seconds": section["seconds"], "active_channels": len(section["active_channels"])}
                                   for section in structure["sections"]],
                      "channel_entry_order": [structure["channel_entry_order"].get(channel)
                                              for channel in range(module.channels)],
                      "loop_start_seconds": structure["loop_start_seconds"]},
    }
    palette["summary"] = palette_summary(palette)
    return palette


def list_palettes(palettes: list[dict], role: str | None = None, fmt: str | None = None,
                  channels: int | None = None) -> dict:
    from .usage import ROLE_NAMES
    if role is not None and role not in ROLE_NAMES:
        raise ValidationError(f"Unknown role; expected one of {', '.join(sorted(ROLE_NAMES))}.")
    if fmt is not None and fmt not in ("mod", "xm"):
        raise ValidationError("format: mod or xm expected.")
    if channels is not None:
        require_int(channels, "channels", 2, 32, "CHANNELS")
    rows = []
    for palette in palettes:
        played = [entry for entry in palette["entries"] if entry["note_starts"]]
        if role and all(entry["role"] != role for entry in played):
            continue
        if fmt and palette["format"] != fmt or channels and palette["channels"] != channels:
            continue
        rows.append({"id": palette["id"], **({"title": palette["title"]} if palette.get("title") else {}),
                     "format": palette["format"], "channels": palette["channels"],
                     "speed": palette["speed"], "bpm": palette["bpm"],
                     "duration_seconds": palette["duration_seconds"], "entries": len(palette["entries"]),
                     "played": len(played), "summary": palette.get("summary") or palette_summary(palette)})
    return {"ok": True, "total": len(rows), "palettes": rows, "note": NOTE}


def find_palette(palettes: list[dict], palette_id: str) -> dict:
    palette = next((item for item in palettes if item["id"] == palette_id), None)
    if palette is None:
        raise ValidationError(f"Unknown palette: {palette_id}.", "SAMPLE_LIBRARY")
    return palette


def ordered_entries(palette: dict, include_unplayed: bool = False) -> list[dict]:
    """The palette's entries in role order (drums, bass, chords, leads, pads, textures, effects), the most played
    first inside a role; by default only the entries the song plays."""
    from .usage import ROLE_ORDER
    entries = [entry for entry in palette["entries"] if include_unplayed or entry["note_starts"]]
    order = {role: index for index, role in enumerate(ROLE_ORDER)}
    return sorted(entries, key=lambda entry: (order.get(entry["role"], len(order)), -entry["note_starts"], entry["id"]))


def use_palette(library, palette: dict, module: Module, slots: list[int] | None = None, adapt: bool = False,
                include_unplayed: bool = False) -> tuple[Module, dict]:
    """Insert the palette's entries into `module` in role order; returns (new module, slot map with roles).
    `slots` gives the target slot of each entry in that order (default: the next free slots). Into a MOD, an
    entry outside the MOD profile needs `adapt` (the library says what changes); nothing is written otherwise."""
    entries = ordered_entries(palette, include_unplayed)
    if not entries:
        raise ValidationError("The palette has no played entry to insert.", "SAMPLE_LIBRARY")
    if slots is not None:
        if len(slots) != len(entries):
            raise ValidationError(f"slots: {len(entries)} slot numbers expected, one per entry in role order "
                                  f"({', '.join(entry['id'] for entry in entries)}).", "SAMPLE_SLOT")
        for slot in slots:
            require_int(slot, "slot", 1, 128 if module.format == "xm" else 31, "SAMPLE_SLOT")
    result = module
    slot_map = []
    for index, entry in enumerate(entries):
        target = slots[index] if slots else None
        result, info = library.insert(result, entry["id"], target, False, adapt)
        slot_map.append({"slot": info["slot"], "id": entry["id"], "role": entry["role"],
                         "confidence": entry["confidence"], "note_starts": entry["note_starts"],
                         "adaptations": info["adaptations"], **({"xm": info["xm"]} if "xm" in info else {})})
    return result, {"palette": palette["id"], "summary": palette.get("summary") or palette_summary(palette),
                    "format": module.format, "inserted": len(slot_map), "slot_map": slot_map,
                    "channel_layout": [{"channel": item["channel"], "role": item["role"]}
                                       for item in palette["channel_layout"]],
                    "note": "Slots filled in role order (drums, bass, chords, leads, pads, textures, effects). "
                            "Keep the palette's roles together; write your own notes."}
