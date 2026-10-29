"""Managing a sample bank one sample at a time, and the bank the window and the agent share.

The owner (in the window) and the agent (CLI, MCP) use the same calls:

- `active_library()` / `set_active_library(path)`: the active bank, kept in `bank.json` under the ChipLoom home
  (`live.live_home()`), so a bank chosen in the window is the one `chiploom samples` uses without `--library`.
  `CHIPLOOM_BANK` overrides it; without either, `exports/sample_library` under the working directory.
- `song_slots(module)`: the samples of an open song or module, each with the role `usage.study` gives it, how it
  is tuned (`tuning`) and whether the bank already holds it.
- `add_from_song` / `add_from_module`: one slot into the bank with the name, role, category and tags the owner
  chose; `add_from_wav`: a WAV file (8, 16, 24 or 32-bit PCM, mono or mixed down) as an XM-style sample whose
  C-4 plays the file at its own rate.
- `tuning(sample, fmt)`: the note the sample sounds when C is written (XM C-4, MOD C-2) and its cents, so parts
  whose samples were tuned differently are found before they clash. `palette_tuning` compares a palette's pitched
  entries with its most played one and gives the relative note and finetune that bring each in line.

A sample name read from a module is source data: it becomes a label, never an instruction.
"""
from __future__ import annotations

import math
import os
from pathlib import Path
import wave

from . import formats, project
from .model import Module, Sample, ValidationError, require_int
from .sample_library import (CATEGORIES, DEFAULT_LIBRARY, MAX_FRAMES, SETTINGS, SampleLibrary, _digest,
                             _envelope_facts, clean_name, estimate_pitch, pcm_bytes)

BANK_FILE = "bank.json"
MAX_WAV_BYTES = 64 * 1024 * 1024
TUNING_TOLERANCE_CENTS = 25.0   # pitched entries further apart than this (modulo whole semitones) are retuned


# --- the active bank -----------------------------------------------------------------------------

def _home() -> Path:
    from .live import live_home
    return live_home()


def active_library() -> Path:
    """The bank used when no `--library` is given: `CHIPLOOM_BANK`, then the one chosen in the window, then
    `exports/sample_library` under the working directory."""
    override = os.environ.get("CHIPLOOM_BANK")
    if override:
        return Path(override).expanduser().resolve()
    path = _home() / BANK_FILE
    if path.exists():
        try:
            value = project.read_json(path)
        except (ValidationError, OSError):
            value = None
        if isinstance(value, dict) and isinstance(value.get("path"), str) and value["path"]:
            return Path(value["path"]).expanduser().resolve()
    return DEFAULT_LIBRARY.resolve()


def recent_libraries() -> list[str]:
    path = _home() / BANK_FILE
    try:
        value = project.read_json(path) if path.exists() else {}
    except (ValidationError, OSError):
        value = {}
    recent = value.get("recent") if isinstance(value, dict) else None
    return [item for item in recent if isinstance(item, str)][:8] if isinstance(recent, list) else []


def set_active_library(path: Path) -> dict:
    """Make `path` the active bank (it must hold a bank or be an empty or new folder)."""
    path = Path(path).expanduser().resolve()
    if path.exists() and not path.is_dir():
        raise ValidationError("A sample bank is a folder.", "SAMPLE_LIBRARY")
    if path.exists() and not (path / "library.json").exists() and any(path.iterdir()):
        raise ValidationError("This folder is neither a sample bank nor empty.", "SAMPLE_LIBRARY")
    recent = [str(path)] + [item for item in recent_libraries() if item != str(path)]
    home = _home()
    home.mkdir(parents=True, exist_ok=True)
    project.write_json(home / BANK_FILE, {"schema": "chiploom.active-bank.v1", "path": str(path),
                                          "recent": recent[:8]})
    return {"ok": True, "library": str(path), "exists": (path / "library.json").exists(), "recent": recent[:8]}


def describe_active() -> dict:
    path = active_library()
    source = "environment" if os.environ.get("CHIPLOOM_BANK") else (
        "chosen" if (_home() / BANK_FILE).exists() and path != DEFAULT_LIBRARY.resolve() else "default")
    entries = None
    if (path / "library.json").exists():
        try:
            entries = len(project.read_json(path / "library.json").get("samples", []))
        except (ValidationError, OSError, AttributeError):
            entries = None
    return {"ok": True, "library": str(path), "source": source, "exists": entries is not None, "entries": entries,
            "recent": recent_libraries()}


# --- tuning --------------------------------------------------------------------------------------

def tuning(sample: Sample, fmt: str = "mod") -> dict:
    """The note a sample sounds when C is written (XM C-4, MOD C-2): `written_c_sounds` (pitch class), `cents`,
    `hz` and `transpose_semitones` (the semitones that would make written C sound C). A measurement; a drum or
    a noise gives `pitched: false` with the reason."""
    pitch = estimate_pitch(sample, fmt)
    result = {"reference_note": pitch["reference_note"], "pitched": pitch["estimated_hz_at_c2"] is not None}
    if not result["pitched"]:
        return {**result, "reason": pitch["reason"]}
    return {**result, "hz": pitch["estimated_hz_at_c2"], "nearest_note": pitch["nearest_note"],
            "written_c_sounds": pitch["pitch_class"], "cents": pitch["cents"],
            "transpose_semitones": pitch["transpose_semitones"], "method": pitch["method"]}


def _offset_cents(info: dict) -> float:
    """Cents of the sound at written C above C, folded into -600..600."""
    names = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
    value = names.index(info["written_c_sounds"]) * 100 + info["cents"]
    return (value + 600) % 1200 - 600


def palette_tuning(library: SampleLibrary, palette: dict) -> dict:
    """Compare the pitched entries a palette plays with its most played pitched entry: for each, the note it
    sounds at written C and the relative note / finetune (XM, 1/128 semitone) that would align it."""
    from .usage import PERCUSSION
    rows = []
    for entry in palette["entries"]:
        if not entry["note_starts"] or entry.get("role") in PERCUSSION:
            continue
        stored = library.get(entry["id"])
        info = tuning(library.read_sample(entry["id"]), stored["format_origin"])
        if info["pitched"]:
            rows.append({"id": entry["id"], "role": entry.get("role"), "note_starts": entry["note_starts"],
                         "written_c_sounds": info["written_c_sounds"], "cents": info["cents"],
                         "offset": _offset_cents(info)})
    if not rows:
        return {"consistent": True, "reference": None, "entries": [], "note": "No pitched entry to compare."}
    reference = max(rows, key=lambda row: row["note_starts"])
    consistent = True
    for row in rows:
        delta = row.pop("offset") - _offset_cents({"written_c_sounds": reference["written_c_sounds"],
                                                   "cents": reference["cents"]})
        delta = (delta + 600) % 1200 - 600
        semitones = round(delta / 100)
        residual = delta - 100 * semitones
        row.update(delta_cents=round(delta, 1), retune_relative_note=-semitones,
                   retune_finetune=-round(residual * 1.28) if abs(residual) > TUNING_TOLERANCE_CENTS else 0)
        row["in_tune"] = row["retune_relative_note"] == 0 and row["retune_finetune"] == 0
        consistent &= row["in_tune"]
    return {"consistent": consistent, "reference": reference["id"], "entries": rows,
            "note": "Measured: the note each pitched entry sounds when C is written, compared with the most played "
                    "one. An entry off by whole semitones was written transposed in its song; retune it (XM: "
                    "relative note and finetune, the PCM is not touched) or transpose its notes."}


def retune(module: Module, slot_map: list[dict], report: dict) -> list[dict]:
    """Apply `palette_tuning` corrections to the inserted XM samples (relative note and finetune only)."""
    import dataclasses
    if module.format != "xm":
        raise ValidationError("Retuning by relative note needs an XM; in a MOD transpose the notes instead.",
                              "SAMPLE_INCOMPATIBLE")
    slots = {item["id"]: item["slot"] for item in slot_map}
    changed = []
    for row in report["entries"]:
        if row["in_tune"] or row["id"] not in slots:
            continue
        sample = module.samples[slots[row["id"]] - 1]
        finetune = sample.finetune + row["retune_finetune"]
        relative = sample.relative_note + row["retune_relative_note"] + (finetune > 127) - (finetune < -128)
        finetune = (finetune + 128) % 256 - 128
        if not -96 <= relative <= 95:
            continue
        module.samples[slots[row["id"]] - 1] = dataclasses.replace(sample, relative_note=relative, finetune=finetune)
        changed.append({"slot": slots[row["id"]], "id": row["id"], "relative_note": relative, "finetune": finetune})
    return changed


# --- slots of a song ----------------------------------------------------------------------------

def load_song(path: Path) -> Module:
    path = Path(path)
    if path.suffix.lower() == ".json":
        return project.load(path)
    if path.stat().st_size > 32 * 1024 * 1024:
        raise ValidationError("Module too large.", "SAMPLE_LIBRARY")
    return formats.decode(path.read_bytes())


def _study(module: Module) -> dict:
    from .usage import study
    try:
        return {slot["slot"]: slot for slot in study(module)["slots"]}
    except Exception:  # noqa: BLE001 - a song the study cannot follow still lists its samples
        return {}


def _settings_key(sample: Sample) -> tuple:
    looped = bool(sample.loop_length)
    values = {"pcm_sha256": _digest(pcm_bytes(sample.pcm, sample.bits)), "loop_start": sample.loop_start if looped else 0,
              "loop_length": sample.loop_length if looped else 0, "finetune": sample.finetune, "volume": sample.volume,
              "bits": sample.bits, "loop_mode": sample.loop_mode if looped else "forward", "panning": sample.panning,
              "relative_note": sample.relative_note}
    return tuple(values[field] for field in SETTINGS)


def song_slots(module: Module, library: SampleLibrary | None = None) -> dict:
    """Every non-empty slot of a song: name, frames, bits, loop, the scored role, tuning and its bank entry."""
    studied = _study(module)
    known = {}
    if library is not None and (library.path / "library.json").exists():
        for entry in library._manifest()["samples"]:
            known[tuple(entry[field] for field in SETTINGS)] = entry["id"]
    rows = []
    for slot, sample in enumerate(module.samples, 1):
        if not sample.pcm:
            continue
        scored = studied.get(slot) or {}
        rows.append({"slot": slot, "name": sample.name, "frames": len(sample.pcm), "bits": sample.bits,
                     "looped": bool(sample.loop_length), "loop_mode": sample.loop_mode if sample.loop_length else None,
                     "volume": sample.volume, "role": scored.get("role"), "role_confidence": scored.get("confidence"),
                     "role_evidence": (scored.get("evidence") or [])[:4], "note_starts": scored.get("note_starts", 0),
                     "tuning": tuning(sample, module.format), "in_bank": known.get(_settings_key(sample))})
    return {"ok": True, "format": module.format, "slots": rows,
            "note": "Roles are scored from how the song plays each sample; tuning is measured. Confirm by listening."}


def add_from_song(library: SampleLibrary, module: Module, slot: int, filename: str, name: str | None = None,
                  role: str | None = None, category: str | None = None, tags: list[str] | None = None) -> dict:
    """One slot of an open song into the bank, keeping its PCM and playback settings (XM: bits, loop mode,
    panning, relative note, finetune), with the owner's name, role, category and tags."""
    require_int(slot, "slot", 1, len(module.samples), "SAMPLE_SLOT")
    sample = module.samples[slot - 1]
    if not sample.pcm:
        raise ValidationError(f"Slot {slot} is empty.", "SAMPLE_SLOT")
    scored = None
    if role is None:
        found = _study(module).get(slot)
        if found and found.get("note_starts"):
            scored = (found["role"], found["confidence"], found["evidence"])
    envelope, xm_meta = None, None
    if module.format == "xm":
        instruments = (module.metadata.get("xm") or {}).get("instruments") or {}
        item = instruments.get(str(slot)) if isinstance(instruments, dict) else None
        if isinstance(item, dict):
            envelope = _envelope_facts(item)
            xm_meta = {key: item[key] for key in ("volume_envelope", "vibrato", "fadeout") if item.get(key)}
    source = {"file": Path(filename).name, "slot": slot, "name": clean_name(sample.name)}
    result = library.add_entry(sample, module.format, name if name is not None else clean_name(sample.name), role,
                               category, tags, "module-added", source, envelope, xm_meta, scored)
    result["tuning"] = tuning(sample, module.format)
    return result


def add_from_module(library: SampleLibrary, path: Path, slot: int, **labels) -> dict:
    path = Path(path).resolve()
    if path.is_relative_to(library.path):
        raise ValidationError("The source must be outside the sample bank.")
    return add_from_song(library, load_song(path), slot, path.name, **labels)


# --- WAV files ----------------------------------------------------------------------------------

def read_wav(path: Path, loop_start: int = 0, loop_length: int = 0) -> Sample:
    """A WAV file as an XM-style sample: 16-bit when the file has more than 8 bits, channels mixed to mono, and a
    relative note and finetune so that C-4 plays it at its own rate."""
    path = Path(path)
    if path.stat().st_size > MAX_WAV_BYTES:
        raise ValidationError("WAV file too large.", "SAMPLE_WAV")
    try:
        with wave.open(str(path), "rb") as handle:
            channels, width, rate, count = (handle.getnchannels(), handle.getsampwidth(), handle.getframerate(),
                                            handle.getnframes())
            raw = handle.readframes(count)
    except (wave.Error, EOFError) as exc:
        raise ValidationError(f"Not a PCM WAV file ChipLoom can read: {exc}.", "SAMPLE_WAV") from exc
    if width not in (1, 2, 3, 4) or not 1 <= channels <= 8 or not 1000 <= rate <= 192000:
        raise ValidationError("WAV: 8, 16, 24 or 32-bit PCM, 1 to 8 channels, 1 to 192 kHz expected.", "SAMPLE_WAV")
    frames = len(raw) // (width * channels)
    if not frames:
        raise ValidationError("The WAV file holds no audio.", "SAMPLE_WAV")
    if frames > MAX_FRAMES:
        raise ValidationError(f"WAV too long: at most {MAX_FRAMES} frames ({MAX_FRAMES / rate:.1f} s at its rate).",
                              "SAMPLE_WAV")
    values = []
    for frame in range(frames):
        total = 0
        for channel in range(channels):
            start = (frame * channels + channel) * width
            chunk = raw[start:start + width]
            if width == 1:
                total += (chunk[0] - 128) << 8
            else:
                total += int.from_bytes(chunk, "little", signed=True) >> (8 * (width - 2))
        values.append(total // channels)
    bits = 8 if width == 1 else 16
    pcm = tuple(max(-128, min(127, value >> 8)) for value in values) if bits == 8 else \
        tuple(max(-32768, min(32767, value)) for value in values)
    steps = round(12 * math.log2(rate / 8363) * 128)
    relative = max(-96, min(95, round(steps / 128)))
    finetune = max(-128, min(127, steps - relative * 128))
    require_int(loop_start, "loop_start", 0, frames)
    require_int(loop_length, "loop_length", 0, frames - loop_start)
    if loop_length and loop_length < 2:
        raise ValidationError("A loop needs at least 2 frames.", "SAMPLE_LOOP")
    name = clean_name(path.stem) or "WAV sample"
    return Sample(name, pcm, 64, finetune, loop_start if loop_length else 0, loop_length, bits=bits,
                  relative_note=relative)


def add_from_wav(library: SampleLibrary, path: Path, name: str | None = None, role: str | None = None,
                 category: str | None = None, tags: list[str] | None = None, loop_start: int = 0,
                 loop_length: int = 0) -> dict:
    path = Path(path).resolve()
    sample = read_wav(path, loop_start, loop_length)
    source = {"file": path.name, "slot": None, "name": clean_name(path.stem)}
    result = library.add_entry(sample, "xm", name if name is not None else sample.name, role, category, tags,
                               "wav-imported", source)
    result["tuning"] = tuning(sample, "xm")
    return result


def relabel(library: SampleLibrary) -> dict:
    """Give entries extracted under neutral names their source's sample name (entries the owner renamed keep
    theirs) and a readable `source`, from the bank's private provenance."""
    with library._writer():
        manifest = library._manifest()
        provenance = library._provenance()
        first: dict[str, dict] = {}
        for occurrence in provenance["occurrences"].values():
            first.setdefault(occurrence["entry_id"], occurrence)
        renamed = sourced = 0
        for entry in manifest["samples"]:
            occurrence = first.get(entry["id"])
            if occurrence is None:
                continue
            original = clean_name(occurrence.get("original_name"))
            if not entry.get("source"):
                entry["source"] = {"file": occurrence.get("filename"), "slot": occurrence.get("slot"), "name": original}
                sourced += 1
            if original and entry.get("classification") not in ("user-edited", "user-added") and entry["name"] != original:
                entry["name"] = original
                renamed += 1
        project.write_json(library._path("library.json"), manifest)
    return {"ok": True, "library": str(library.path), "renamed": renamed, "sources_added": sourced,
            "entries": len(manifest["samples"])}


__all__ = ["CATEGORIES", "active_library", "add_from_module", "add_from_song", "add_from_wav", "describe_active",
           "load_song", "palette_tuning", "read_wav", "recent_libraries", "relabel", "retune", "set_active_library",
           "song_slots", "tuning"]
