"""Instruments: a sample, its default settings and a short effect phrase, kept as JSON files.

An instrument answers "what does this sound do when I play a note?". It names a sample (a library ID, a
recipe, or embedded PCM), a default volume and fine tune, and a phrase: up to 32 rows of effect text
(`C20`, `047`, `4A3`, ...) written on the rows that follow the note. One file per instrument lives in an
instrument folder (default `exports/instruments`, which git ignores with the rest of `exports/`).

    {"schema": "chiploom.instrument.v1", "id": "INS-0001", "name": "Soft Pluck", "role": "bass",
     "tags": ["pluck"], "volume": 40, "finetune": 0, "phrase": ["000", "C30", "C20", "C10"],
     "sample": {"kind": "library", "library_id": "SMP-0007"}}

`sample` is `{"kind": "library", "library_id"}`, `{"kind": "recipe", "recipe": {...}}` or
`{"kind": "pcm", "pcm_base64", "pcm_sha256", "loop_start", "loop_length", "origin"?}`. Standard library only.
"""

from __future__ import annotations

import base64
import copy
import json
import os
from pathlib import Path
import re

from . import loudness, project, sample_source, sample_tools, synth
from .model import (NOTE_TO_PERIOD, Cell, Module, Sample, ValidationError, ascii_field, cell, require_int,
                    validate_cell, validate_sample)

SCHEMA = "chiploom.instrument.v1"
DEFAULT_LIBRARY = Path("exports/instruments")
MAX_PHRASE = 32
MAX_ENTRIES = 5_000
KINDS = ("library", "recipe", "pcm")
_ID = re.compile(r"INS-[0-9]{4,6}")
_LIBRARY_ID = re.compile(r"SMP-[0-9]{4,6}")
_TAG = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
_FIELDS = {"schema", "id", "name", "role", "tags", "sample", "volume", "finetune", "phrase"}
_ORIGIN = {"library_id", "edited", "derived_from", "recipe_type"}
_EMPTY_EFFECT = {"", "---", "...", "--", "..", "000"}
_FLOW_COMMANDS = (11, 13, 15)  # Bxx, Dxx, Fxx belong to the song, never to an instrument


def _bad(message: str, code: str = "INSTRUMENT_INVALID") -> ValidationError:
    return ValidationError(message, code)


# --- validation ------------------------------------------------------------------------------------

def normalize_phrase(phrase: object) -> list[str]:
    """Up to 32 effect rows as three upper-case hex digits; empty spellings become `000`.

    Bxx, Dxx and Fxx are refused (they steer the song, not a sound); every other effect must be one the
    profile plays.
    """
    if not isinstance(phrase, list) or len(phrase) > MAX_PHRASE:
        raise _bad(f"phrase: a list of at most {MAX_PHRASE} effect rows (\"000\", \"C20\", \"047\", ...).")
    rows = []
    for index, text in enumerate(phrase):
        if not isinstance(text, str):
            raise _bad(f"phrase[{index}]: effect text such as \"C20\" expected.")
        text = "000" if text.strip() in _EMPTY_EFFECT else text.strip().upper()
        if not re.fullmatch(r"[0-9A-F]{3}", text):
            raise _bad(f"phrase[{index}]: {text!r} is not three hexadecimal digits (e.g. C20, 047, 4A3).")
        if int(text[0], 16) in _FLOW_COMMANDS:
            raise _bad(f"phrase[{index}]: {text} is a flow or timing effect (Bxx, Dxx, Fxx); put those in the song.")
        try:
            validate_cell(cell(None, 0, text), 0, 0, 0, 31, 1)
        except ValidationError as exc:
            raise _bad(f"phrase[{index}]: {exc}") from exc
        rows.append(text)
    return rows


def parse_phrase(text: str) -> list[str]:
    """A phrase from the command line: JSON list, or effects separated by commas or spaces."""
    text = text.strip()
    if text.startswith("["):
        try:
            return normalize_phrase(json.loads(text))
        except ValueError as exc:
            if isinstance(exc, ValidationError):
                raise
            raise _bad(f"The phrase is not valid JSON: {exc}") from exc
    return normalize_phrase([part for part in re.split(r"[\s,]+", text) if part])


def _sample_spec(data: object) -> dict:
    if not isinstance(data, dict) or data.get("kind") not in KINDS:
        raise _bad(f"sample: an object with kind one of {list(KINDS)} expected.")
    kind = data["kind"]
    if kind == "library":
        extra = set(data) - {"kind", "library_id"}
        if extra or not isinstance(data.get("library_id"), str) or not _LIBRARY_ID.fullmatch(data["library_id"]):
            hint = f" (unknown fields {sorted(extra)})" if extra else ""
            raise _bad('sample: {"kind": "library", "library_id": "SMP-0001"} expected' + hint + ".")
        return {"kind": "library", "library_id": data["library_id"]}
    if kind == "recipe":
        if set(data) - {"kind", "recipe"} or not isinstance(data.get("recipe"), dict):
            raise _bad("sample: {\"kind\": \"recipe\", \"recipe\": {...}} expected.")
        synth.from_recipe("Check", data["recipe"])  # RECIPE_INVALID on a bad recipe
        return {"kind": "recipe", "recipe": copy.deepcopy(data["recipe"])}
    extra = set(data) - {"kind", "pcm_base64", "pcm_sha256", "loop_start", "loop_length", "origin"}
    if extra:
        raise _bad(f"sample: unknown fields {sorted(extra)}.")
    pcm = project._pcm_from_base64(data, "sample")
    start, length = data.get("loop_start", 0), data.get("loop_length", 0)
    validate_sample(Sample("Check", pcm, 40, 0, start, length))
    origin = data.get("origin", {})
    if not isinstance(origin, dict) or set(origin) - _ORIGIN:
        raise _bad(f"sample.origin: an object with keys from {sorted(_ORIGIN)} expected.")
    if origin.get("library_id") is not None and not (
            isinstance(origin["library_id"], str) and _LIBRARY_ID.fullmatch(origin["library_id"])):
        raise _bad("sample.origin.library_id: an ID such as SMP-0001 expected.")
    result = {"kind": "pcm", "pcm_base64": data["pcm_base64"], "pcm_sha256": data["pcm_sha256"].lower(),
              "loop_start": start, "loop_length": length}
    if origin:
        result["origin"] = copy.deepcopy(origin)
    return result


def normalize(data: object, need_id: bool = False) -> dict:
    """A validated copy of an instrument (errors carry the code `INSTRUMENT_INVALID`)."""
    if not isinstance(data, dict):
        raise _bad("An instrument is a JSON object.")
    extra = set(data) - _FIELDS
    if extra:
        raise ValidationError(f"instrument: unknown fields {sorted(extra)}.", "UNKNOWN_FIELD")
    if data.get("schema", SCHEMA) != SCHEMA:
        raise _bad(f"Unsupported instrument schema; expected {SCHEMA}.")
    name = data.get("name")
    try:
        ascii_field(name, 22, "Instrument name")
    except ValidationError as exc:
        raise _bad(str(exc)) from exc
    if not name.strip():
        raise _bad("Instrument name must not be empty.")
    instrument_id = data.get("id")
    if instrument_id is not None and not (isinstance(instrument_id, str) and _ID.fullmatch(instrument_id)):
        raise _bad("id: an ID such as INS-0001 expected.")
    if need_id and instrument_id is None:
        raise _bad("id: an ID such as INS-0001 expected.")
    role = data.get("role")
    if role is not None and role not in loudness.ROLES:
        raise _bad(f"role: one of {sorted(loudness.ROLES)} expected, got {role!r}.")
    tags = data.get("tags", [])
    if not isinstance(tags, list) or len(tags) > 16 or any(
            not isinstance(tag, str) or not _TAG.fullmatch(tag) for tag in tags):
        raise _bad("tags: up to 16 lowercase ASCII words (hyphens allowed).")
    result = {"schema": SCHEMA}
    if instrument_id is not None:
        result["id"] = instrument_id
    result.update(name=name)
    if role is not None:
        result["role"] = role
    try:
        volume = require_int(data.get("volume", 40), "volume", 0, 64)
        finetune = require_int(data.get("finetune", 0), "finetune", -8, 7)
    except ValidationError as exc:
        raise _bad(str(exc)) from exc
    result.update(tags=sorted(set(tags)), volume=volume, finetune=finetune,
                  phrase=normalize_phrase(data.get("phrase", [])), sample=_sample_spec(data.get("sample")))
    return result


def summary(instrument: dict) -> dict:
    """The fields a list shows: no PCM bytes."""
    spec = instrument["sample"]
    sample = {"kind": spec["kind"]}
    if spec["kind"] == "library":
        sample["library_id"] = spec["library_id"]
    elif spec["kind"] == "recipe":
        sample["recipe"] = spec["recipe"]
    else:
        raw = base64.b64decode(spec["pcm_base64"])
        sample.update(bytes=len(raw), pcm_sha256=spec["pcm_sha256"], loop_start=spec["loop_start"],
                      loop_length=spec["loop_length"], looped=bool(spec["loop_length"]))
        if spec.get("origin"):
            sample["origin"] = spec["origin"]
    return {"id": instrument.get("id"), "name": instrument["name"], "role": instrument.get("role"),
            "tags": instrument["tags"], "volume": instrument["volume"], "finetune": instrument["finetune"],
            "phrase": instrument["phrase"], "sample": sample}


# --- the instrument folder -----------------------------------------------------------------------------

class InstrumentLibrary:
    """A folder of `INS-nnnn.json` files. Writes are atomic; ids are never reused while the file exists."""

    def __init__(self, path: Path | str = DEFAULT_LIBRARY):
        self.path = Path(path).resolve()

    def _file(self, instrument_id: str) -> Path:
        if not isinstance(instrument_id, str) or not _ID.fullmatch(instrument_id):
            raise _bad(f"Instrument IDs look like INS-0001, got {instrument_id!r}.", "INSTRUMENT_NOT_FOUND")
        return self.path / f"{instrument_id}.json"

    def ids(self) -> list[str]:
        if not self.path.is_dir():
            return []
        return sorted(item.stem for item in self.path.glob("INS-*.json") if _ID.fullmatch(item.stem))

    def get(self, instrument_id: str) -> dict:
        path = self._file(instrument_id)
        if not path.is_file():
            raise _bad(f"Unknown instrument {instrument_id} in {self.path}.", "INSTRUMENT_NOT_FOUND")
        data = normalize(project.read_json(path), need_id=True)
        if data["id"] != instrument_id:
            raise _bad(f"{path.name} holds the id {data['id']}; rename the file or fix the id.")
        return data

    def list(self, query: str = "", tags: list[str] | None = None, role: str | None = None,
             offset: int = 0, limit: int = 50) -> dict:
        require_int(offset, "offset", 0, MAX_ENTRIES)
        require_int(limit, "limit", 1, 500)
        wanted = set(tags or [])
        found, invalid = [], []
        for instrument_id in self.ids():
            try:
                data = self.get(instrument_id)
            except ValueError as exc:
                invalid.append({"id": instrument_id, "error": str(exc)})
                continue
            text = " ".join([data["id"], data["name"], data.get("role") or "", *data["tags"]]).casefold()
            if wanted - set(data["tags"]) or (role and data.get("role") != role):
                continue
            if all(word in text for word in query.casefold().split()):
                found.append(summary(data))
        result = {"ok": True, "folder": str(self.path), "total": len(found), "offset": offset,
                  "instruments": found[offset:offset + limit]}
        if invalid:
            result["invalid"] = invalid
        return result

    def save(self, data: dict, replace: bool = False) -> dict:
        """Write an instrument. Without an `id` a new one is assigned; an existing id needs `replace`."""
        instrument = normalize(data)
        self.path.mkdir(parents=True, exist_ok=True)
        if "id" in instrument:
            path = self._file(instrument["id"])
            if path.exists() and not replace:
                raise _bad(f"Instrument {instrument['id']} exists; set replace to overwrite it.", "INSTRUMENT_EXISTS")
        else:
            used = [int(item[4:]) for item in self.ids()]
            if len(used) >= MAX_ENTRIES:
                raise _bad("Instrument folder is full.", "INSTRUMENT_INVALID")
            number = max(used, default=0) + 1
            while True:  # claim the file name exclusively, so two writers never share an id
                instrument = {**instrument, "id": f"INS-{number:04d}"}
                path = self._file(instrument["id"])
                try:
                    with path.open("x", encoding="utf-8"):
                        pass
                    break
                except FileExistsError:
                    number += 1
        ordered = {"schema": SCHEMA, **{key: instrument[key] for key in
                                       ("id", "name", "role", "tags", "volume", "finetune", "phrase", "sample")
                                       if key in instrument}}
        try:
            project.write_json(path, ordered)
        except BaseException:
            if path.exists() and not path.stat().st_size:
                path.unlink()  # drop the claimed, still empty name
            raise
        return ordered

    def delete(self, instrument_id: str) -> dict:
        path = self._file(instrument_id)
        if not path.is_file():
            raise _bad(f"Unknown instrument {instrument_id} in {self.path}.", "INSTRUMENT_NOT_FOUND")
        os.unlink(path)
        return {"ok": True, "deleted": instrument_id, "folder": str(self.path)}


# --- capturing an instrument from a song ------------------------------------------------------------------

def from_slot(module: Module, slot: int, name: str, phrase: object = (), role: str | None = None,
              tags: list[str] | None = None, volume: int | None = None, finetune: int | None = None,
              embed: bool = False) -> dict:
    """An instrument (without id) captured from sample slot `slot` of a song, plus a phrase.

    A recipe sample becomes a `recipe` instrument and an unedited library sample a `library` one (by ID, so
    no PCM is copied). An edited or embedded sample becomes a `pcm` instrument, remembering its library ID
    or the fact that it came from a recipe in `origin`. `embed` forces the PCM form.
    """
    require_int(slot, "slot", 1, len(module.samples), "SAMPLE_SLOT")
    sample = module.samples[slot - 1]
    if not sample.pcm:
        raise ValidationError(f"Sample slot {slot} is empty.", "SAMPLE_SLOT")
    sources = module.metadata.get("sample_sources") if isinstance(module.metadata, dict) else None
    recorded = sources.get(str(slot)) if isinstance(sources, dict) else None
    recorded = recorded if isinstance(recorded, dict) else {}
    if sample.recipe is not None and not embed:
        spec = {"kind": "recipe", "recipe": copy.deepcopy(sample.recipe)}
        role = role or recorded.get("role") or loudness.role_for_recipe(sample.recipe)
    elif recorded.get("library_id") and not recorded.get("edited") and not embed:
        spec = {"kind": "library", "library_id": recorded["library_id"]}
    else:
        spec = {"kind": "pcm", **sample_tools.pcm_fields(sample.pcm, sample.loop_start, sample.loop_length)}
        origin = {}
        if recorded.get("library_id"):
            origin.update(library_id=recorded["library_id"], edited=bool(recorded.get("edited")))
        if recorded.get("derived_from") == "recipe" or sample.recipe is not None:
            origin["derived_from"] = "recipe"
            kind = (sample.recipe or recorded.get("recipe") or {}).get("type") or recorded.get("recipe_type")
            if kind:
                origin["recipe_type"] = kind
        if origin:
            spec["origin"] = origin
    if role is None and recorded.get("role") in loudness.ROLES:
        role = recorded["role"]
    data = {"name": name, "tags": list(tags or []), "volume": sample.volume if volume is None else volume,
            "finetune": sample.finetune if finetune is None else finetune, "phrase": list(phrase), "sample": spec}
    if role is not None:
        data["role"] = role
    return normalize(data)


# --- applying an instrument ---------------------------------------------------------------------------------

def resolve(instrument: object, folder: Path | str | None = None) -> dict:
    """An instrument from an ID in the instrument folder, or validated from an inline object."""
    if isinstance(instrument, str):
        return InstrumentLibrary(folder or DEFAULT_LIBRARY).get(instrument)
    if isinstance(instrument, dict):
        return normalize(instrument)
    raise ValidationError("instrument: an instrument ID such as \"INS-0001\" or an instrument object expected.",
                          "PATCH_FIELD")


def _library_copy(module: Module | None, library_id: str) -> Sample | None:
    """An unedited copy of a library sample the song already holds, found through its recorded ID."""
    sources = module.metadata.get("sample_sources") if module is not None and isinstance(module.metadata, dict) else None
    if not isinstance(sources, dict):
        return None
    for key, entry in sources.items():
        held = key.isdigit() and 1 <= int(key) <= len(module.samples) and module.samples[int(key) - 1].pcm
        if isinstance(entry, dict) and entry.get("library_id") == library_id and not entry.get("edited") and held:
            return copy.deepcopy(module.samples[int(key) - 1])
    return None


def build_sample(instrument: dict, library: Path | str | None = None,
                 module: Module | None = None) -> tuple[Sample, dict]:
    """The sample an instrument stands for, with its volume, fine tune and name, and its provenance entry."""
    spec = instrument["sample"]
    name, volume, finetune = instrument["name"], instrument["volume"], instrument["finetune"]
    note = {"instrument": instrument.get("id")} if instrument.get("id") else {}
    if spec["kind"] == "recipe":
        sample = synth.from_recipe(name, spec["recipe"], volume, finetune)
        role = instrument.get("role") or loudness.role_for_recipe(spec["recipe"])
        return sample, {"origin": "synthesized", "recipe_type": sample.recipe.get("type"), "role": role, **note}
    if spec["kind"] == "library":
        sample = _library_copy(module, spec["library_id"])  # the song already holds it: no bank needed
        if sample is None:
            from .sample_library import DEFAULT_LIBRARY as DEFAULT_BANK, SampleLibrary
            bank = Path(library or DEFAULT_BANK)
            if not (bank / "library.json").is_file():
                raise ValidationError(f"No sample bank at {bank}: instrument {instrument.get('id') or instrument['name']!r} "
                                      f"uses library sample {spec['library_id']}. Pass the bank folder in 'library'.",
                                      "SAMPLE_LIBRARY")
            sample, _ = SampleLibrary(bank).sample(spec["library_id"])
        sample.name, sample.volume, sample.finetune = name, volume, finetune
        return sample, {"library_id": spec["library_id"], "origin": "module-extracted", "adaptations": [], **note}
    pcm = project._pcm_from_base64(spec, "instrument sample")
    sample = Sample(name, pcm, volume, finetune, spec["loop_start"], spec["loop_length"])
    origin = spec.get("origin", {})
    if origin.get("library_id"):
        entry = {"library_id": origin["library_id"], "origin": "module-extracted", "edited": True, **note}
    elif origin.get("derived_from") == "recipe":
        entry = {"origin": "derived", "derived_from": "recipe", "edited": True, **note}
        if origin.get("recipe_type"):
            entry["recipe_type"] = origin["recipe_type"]
    else:
        entry = {"origin": "embedded-pcm", **note}
    if instrument.get("role"):
        entry["role"] = instrument["role"]
    return sample, entry


def _guard_source(module: Module, instrument: dict, entry: dict) -> None:
    kind = instrument["sample"]["kind"]
    if kind == "library":
        sample_source.guard_insert(module, "library")
    elif kind == "recipe":
        sample_source.guard_insert(module, "recipe")
    elif sample_source.declared(module) == "synthesized" or (
            sample_source.declared(module) == "library" and not entry.get("library_id")):
        sample_tools.guard_new_pcm(module)


def _same_sound(left: Sample, right: Sample) -> bool:
    return (left.pcm == right.pcm and left.loop_start == right.loop_start and left.loop_length == right.loop_length
            and left.volume == right.volume and left.finetune == right.finetune)


def apply_instrument(module: Module, op: dict) -> dict:
    """The `apply_instrument` patch operation: write a note and its instrument phrase into a channel.

    The note goes on `row` with the instrument's sample number. Phrase row 0 is the effect of the note row,
    row 1 the next row, and so on, stopping at the next note in the channel, at `length` rows (default: the
    phrase length), at the end of the pattern or at the end of the phrase. Existing effects are kept unless
    `overwrite` is true, and Bxx/Dxx/Fxx are never replaced; an `000` phrase row never clears anything.
    The sample is reused when the song already holds an identical one (same PCM, loop, volume and fine tune);
    otherwise it goes into `slot` (needing `replace` if occupied) or the first free slot.
    """
    instrument = resolve(op["instrument"], op.get("instruments"))
    pattern = module.patterns[require_int(op["pattern"], "pattern", 0, len(module.patterns) - 1)]
    channel = require_int(op["channel"], "channel", 0, module.channels - 1)  # N-channel MODs
    row = require_int(op["row"], "row", 0, 63)
    note = op["note"].upper() if isinstance(op["note"], str) else op["note"]
    if note is None:
        raise ValidationError("note: a note such as C-2 is required.", "NOTE_UNKNOWN")
    cell(note)  # NOTE_UNKNOWN, with the spelling hint, for anything that is not C-1..B-3
    overwrite = sample_tools.flag(op, "overwrite")
    replace = sample_tools.flag(op, "replace")
    phrase = instrument["phrase"]
    length = require_int(op.get("length", max(1, len(phrase))), "length", 1, 64)

    sample, entry = build_sample(instrument, op.get("library"), module)
    slot = op.get("slot")
    if slot is not None:
        require_int(slot, "slot", 1, 31, "SAMPLE_SLOT")
        if slot > len(module.samples) + 1:
            raise ValidationError(f"Choose an existing slot or the next free one ({len(module.samples) + 1}); "
                                  "gaps are not inserted.", "SAMPLE_SLOT")
    twin = next((index for index, item in enumerate(module.samples, 1)
                 if item.pcm and _same_sound(item, sample) and slot in (None, index)), None)
    reused = twin is not None
    if reused:
        slot = twin
    else:
        _guard_source(module, instrument, entry)
        used = {value.sample for each in module.patterns for value in each.cells.values() if value.sample}
        if slot is None:
            slot = next((index for index, item in enumerate(module.samples, 1)
                         if not item.pcm and index not in used), len(module.samples) + 1)
            if slot > 31:
                raise ValidationError("All 31 sample slots are in use; choose a slot with replace.", "SAMPLE_SLOT")
        if slot <= len(module.samples):
            if module.samples[slot - 1].pcm and not replace:
                raise ValidationError(f"Sample slot {slot} is occupied by {module.samples[slot - 1].name!r}; "
                                      "pass replace (CLI: --replace) to overwrite it.", "SAMPLE_SLOT")
            module.samples[slot - 1] = sample
        else:
            module.samples.append(sample)
        sample_tools.sources_of(module)[str(slot)] = entry

    written, skipped, stopped = [], [], "phrase_end"
    count = max(1, min(length, len(phrase))) if phrase else 1
    if phrase and length < len(phrase):
        stopped = "length"
    for index in range(count):
        position = row + index
        if position > 63:
            stopped = "end_of_pattern"
            break
        old = pattern.get(position, channel)
        if index and old.period:
            stopped = "next_note"
            break
        wanted = phrase[index] if index < len(phrase) else "000"
        command, param = old.command, old.param
        if wanted != "000":
            if not (old.command or old.param) or (overwrite and old.command not in _FLOW_COMMANDS):
                command, param = int(wanted[0], 16), int(wanted[1:], 16)
            else:
                skipped.append({"row": position, "existing": old.effect, "wanted": wanted,
                                "reason": "flow or timing effects (Bxx, Dxx, Fxx) are never replaced"
                                if old.command in _FLOW_COMMANDS else "an effect is already there; set overwrite"})
        if index == 0:
            value = Cell(NOTE_TO_PERIOD[note], slot, command, param)
        else:
            value = Cell(0, old.sample, command, param)
        if value != old:
            pattern.put(position, channel, value)
            written.append(position)
    return {"slot": slot, "slot_reused": reused, "instrument": instrument.get("id"), "name": instrument["name"],
            "rows_written": written, "phrase_rows": len(phrase), "stopped": stopped, "skipped": skipped,
            "sample": {"bytes": len(sample.pcm), "looped": bool(sample.loop_length), "volume": sample.volume,
                       "finetune": sample.finetune, "source": entry.get("origin")}}
