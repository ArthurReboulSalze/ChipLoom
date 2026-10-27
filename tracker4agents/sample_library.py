"""Portable local sample banks: exact PCM, playback variants and neutral labels.

No Qt, model provider or audio decoder is required. Source labels live only in
private/provenance.json. Imported PCM is never normalized during extraction.
"""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
import copy
import hashlib
import io
import math
from pathlib import Path
import re
import zipfile

from . import project, sample_source
from .model import (NOTE_TO_PERIOD, Module, Sample, ValidationError,
                    ascii_field, require_int, validate, validate_sample)
from .reference_layout import MAX_ARCHIVE, MAX_FILE, parse_layout

SCHEMA = "chiploom.sample-library.v1"
DEFAULT_LIBRARY = Path("exports/sample_library")
MAX_ENTRIES = 10_000
MAX_PCM = 131_070  # A 16-bit length in words in a 31-sample reference header.
CATEGORIES = ("cycle", "percussion", "texture", "effect", "unclassified", "silent")
SETTINGS = ("pcm_sha256", "loop_start", "loop_length", "finetune", "volume")


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _signed(raw: bytes) -> tuple[int, ...]:
    return tuple(value if value < 128 else value - 256 for value in raw)


def _tags(values: list[str]) -> list[str]:
    if not isinstance(values, list) or len(values) > 32 or any(
        not isinstance(tag, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}", tag)
        for tag in values
    ):
        raise ValidationError("Tags must be up to 32 lowercase ASCII words (hyphens allowed).")
    return sorted(set(values))


def _sample(entry: dict, raw: bytes) -> Sample:
    return Sample(entry["name"], _signed(raw), entry["volume"], entry["finetune"],
                  entry["loop_start"], entry["loop_length"])


def _compatibility(entry: dict, raw: bytes) -> dict:
    try:
        validate_sample(_sample(entry, raw))
    except ValueError as exc:
        return {"compatible": False, "issue": str(exc)}
    return {"compatible": True, "issue": None}


def characterize(raw: bytes, loop_start: int, loop_length: int) -> tuple[dict, str, str, list[str]]:
    """Measured signal facts plus explicitly provisional descriptive labels."""
    values = _signed(raw)
    peak = max(map(abs, values), default=0)
    mean = sum(values) / len(values) if values else 0
    rms = math.sqrt(sum(value * value for value in values) / max(1, len(values)))
    region = values[loop_start:loop_start + loop_length] if loop_length else values
    steps = [b - a for a, b in zip(region, region[1:])]
    crossing = sum((a < 0) != (b < 0) for a, b in zip(region, region[1:])) / max(1, len(steps))
    plateau = sum(step == 0 for step in steps) / max(1, len(steps))
    roughness = sum(map(abs, steps)) / max(1, len(steps)) / max(1, peak)
    metrics = {"peak": round(peak / 128, 6), "rms": round(rms / 128, 6),
               "dc_mean": round(mean / 128, 6), "distinct_amplitudes": len(set(values)),
               "zero_crossing_rate": round(crossing, 6), "roughness": round(roughness, 6),
               "plateau_fraction": round(plateau, 6)}
    tags = ["looped" if loop_length else "one-shot", "short" if len(raw) <= 128 else "long"]
    if not peak:
        return metrics, "silent", "Silent", tags + ["silent"]
    if abs(mean) > max(4, rms * .3):
        tags.append("dc-offset")
    if loop_length and loop_length <= 256:
        category = "cycle"
        if len(set(region)) <= 4 or plateau > .6:
            prefix = "Cycle Pulse"
            tags += ["pulse", "bass-candidate", "lead-candidate"]
        elif roughness < .25 and crossing < .2:
            prefix = "Cycle Smooth"
            tags += ["smooth", "bass-candidate", "lead-candidate"]
        else:
            prefix = "Cycle Bright"
            tags += ["bright", "lead-candidate", "arpeggio-candidate"]
    elif loop_length:
        category, prefix = "texture", "Texture Loop"
        tags.append("sustained")
    elif crossing > .25:
        category, prefix = "percussion", "Noise Hit"
        tags += ["noise", "percussion-candidate"]
    elif len(raw) > 256 and roughness < .15:
        category, prefix = "percussion", "Tonal Hit"
        tags += ["tonal", "percussion-candidate"]
    else:
        category, prefix = "effect", "FX Short"
        tags.append("transient")
    return metrics, category, prefix, _tags(tags)


def _read_sources(source: Path) -> tuple[str, list[tuple[str, bytes]]]:
    limit = MAX_ARCHIVE if source.suffix.lower() == ".zip" else MAX_FILE
    if source.stat().st_size > limit:
        raise ValidationError("Reference input exceeds the analysis size limit.")
    original = source.read_bytes()
    if len(original) > limit:
        raise ValidationError("Reference input exceeds the analysis size limit.")
    if source.suffix.lower() == ".zip":
        try:
            with zipfile.ZipFile(io.BytesIO(original)) as archive:
                members = archive.infolist()
                if len(members) > 512 or sum(item.file_size for item in members) > MAX_ARCHIVE:
                    raise ValidationError("Archive exceeds 512 entries or 64 MiB expanded.")
                inputs = []
                for item in members:
                    if not item.is_dir() and item.filename.lower().endswith(".mod"):
                        if item.file_size > MAX_FILE:
                            raise ValidationError("A MOD archive member exceeds 4 MiB.")
                        inputs.append((item.filename, archive.read(item)))
        except (zipfile.BadZipFile, RuntimeError) as exc:
            raise ValidationError("Cannot read reference ZIP.") from exc
    else:
        inputs = [(source.name, original)]
    if not inputs:
        raise ValidationError("No .mod references found.")
    if source.read_bytes() != original:
        raise ValidationError("Source changed during extraction; no bank update was made.")
    return _digest(original), inputs


class SampleLibrary:
    def __init__(self, path: Path = DEFAULT_LIBRARY):
        self.path = Path(path).resolve()

    def _path(self, relative: str) -> Path:
        path = self.path / relative
        if not path.resolve().is_relative_to(self.path):
            raise ValidationError("Library path escapes the sample bank.")
        return path

    @contextmanager
    def _writer(self):
        self.path.mkdir(parents=True, exist_ok=True)
        lock = self._path(".write.lock")
        try:
            handle = lock.open("x", encoding="utf-8")
        except FileExistsError as exc:
            raise ValidationError("Sample library is busy (.write.lock exists).") from exc
        try:
            with handle:
                handle.write("ChipLoom library writer\n")
                yield
        finally:
            lock.unlink()

    def _manifest(self, create: bool = False) -> dict:
        path = self._path("library.json")
        if create and not path.exists():
            if any(item.name != ".write.lock" for item in self.path.iterdir()):
                raise ValidationError("A new sample bank requires an empty directory.")
            return {"schema": SCHEMA, "samples": [], "classification_note":
                    "Signal-based suggestions; musical roles require listening. Categories and tags are editable."}
        value = project.read_json(path)
        if not isinstance(value, dict) or value.get("schema") != SCHEMA:
            raise ValidationError("Unsupported sample library schema.")
        entries = value.get("samples")
        if not isinstance(entries, list) or len(entries) > MAX_ENTRIES:
            raise ValidationError("Invalid sample library entries.")
        seen = set()
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValidationError("Invalid sample entry.")
            sample_id = entry.get("id")
            if not isinstance(sample_id, str) or not re.fullmatch(r"SMP-[0-9]{4,6}", sample_id) or sample_id in seen:
                raise ValidationError("Invalid or duplicate sample ID.")
            seen.add(sample_id)
            digest = entry.get("pcm_sha256")
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValidationError("Invalid PCM digest.")
            if entry.get("pcm") != f"pcm/{digest}.pcm":
                raise ValidationError("Invalid PCM path; expected content-addressed local data.")
            ascii_field(entry.get("name"), 22, "Sample name")
            _tags(entry.get("tags"))
            if entry.get("category") not in CATEGORIES:
                raise ValidationError("Invalid sample category.")
            for key, maximum in (("bytes", MAX_PCM), ("loop_start", MAX_PCM), ("loop_length", MAX_PCM),
                                 ("volume", 255)):
                require_int(entry.get(key), key, 0, maximum)
            require_int(entry.get("finetune"), "finetune", -8, 7)
        return value

    def _pcm(self, entry: dict) -> bytes:
        path = self._path(entry["pcm"])
        if path.stat().st_size != entry["bytes"]:
            raise ValidationError(f"PCM size mismatch: {entry['id']}.")
        raw = path.read_bytes()
        if _digest(raw) != entry["pcm_sha256"]:
            raise ValidationError(f"PCM hash mismatch: {entry['id']}.")
        return raw

    def get(self, sample_id: str) -> dict:
        entry = next((item for item in self._manifest()["samples"] if item["id"] == sample_id), None)
        if entry is None:
            raise ValidationError(f"Unknown library sample: {sample_id}.")
        result = copy.deepcopy(entry)
        result["compatibility"] = _compatibility(entry, self._pcm(entry))
        return result

    def search(self, query: str = "", tags: list[str] | None = None, category: str | None = None,
               compatible_only: bool = False, offset: int = 0, limit: int = 50) -> dict:
        require_int(offset, "offset", 0, MAX_ENTRIES)
        require_int(limit, "limit", 1, 500)
        wanted = set(_tags(tags or []))
        if category is not None and category not in CATEGORIES:
            raise ValidationError("Unknown category.")
        results = []
        for item in self._manifest()["samples"]:
            if category and item["category"] != category or not wanted.issubset(item["tags"]):
                continue
            text = " ".join([item["id"], item["name"], item["category"], *item["tags"]]).casefold()
            if not all(word in text for word in query.casefold().split()):
                continue
            compatible = _compatibility(item, self._pcm(item))["compatible"]
            if compatible_only and not compatible:
                continue
            summary = {key: copy.deepcopy(item[key]) for key in
                       ("id", "name", "category", "tags", "bytes", "volume", "finetune", "loop_start", "loop_length")}
            summary["compatible"] = compatible
            results.append(summary)
        return {"ok": True, "total": len(results), "offset": offset,
                "samples": results[offset:offset + limit]}

    def extract(self, source: Path) -> dict:
        source = Path(source).resolve()
        if source.is_relative_to(self.path):
            raise ValidationError("Reference source must be outside the sample bank.")
        source_digest, inputs = _read_sources(source)
        # Validate every layout before writing any bank data. Unsupported patterns
        # and restart bytes do not prevent reading the original sample payloads.
        layouts = [(name, raw, parse_layout(raw)) for name, raw in inputs]
        with self._writer():
            manifest = self._manifest(create=True)
            provenance_path = self._path("private/provenance.json")
            provenance = project.read_json(provenance_path) if provenance_path.exists() else {
                "schema": "chiploom.sample-provenance.v1", "sources": {}, "occurrences": {}}
            if not isinstance(provenance, dict) or provenance.get("schema") != "chiploom.sample-provenance.v1" or not isinstance(provenance.get("sources"), dict) or not isinstance(provenance.get("occurrences"), dict):
                raise ValidationError("Invalid private provenance file.")
            known = {tuple(entry[key] for key in SETTINGS): entry for entry in manifest["samples"]}
            # Verify existing PCM before updating an existing bank.
            for entry in manifest["samples"]:
                self._pcm(entry)
            next_id = max((int(entry["id"][4:]) for entry in manifest["samples"]), default=0) + 1
            start_count = len(manifest["samples"])
            payloads = {}
            slots = 0
            provenance["sources"][source_digest] = {"filename": source.name, "modules": len(inputs)}
            for module_index, (filename, raw, layout) in enumerate(layouts):
                module_digest = _digest(raw)
                cursor = 1084 + layout.pattern_bytes
                for slot, (words, tune, volume, start, length) in enumerate(layout.headers, 1):
                    payload = raw[cursor:cursor + words * 2]
                    cursor += words * 2
                    if not payload:
                        continue
                    slots += 1
                    digest = _digest(payload)
                    settings = {"pcm_sha256": digest, "loop_start": start * 2,
                                "loop_length": length * 2 if length > 1 else 0,
                                "finetune": (tune & 15) - (16 if tune & 8 else 0), "volume": volume}
                    key = tuple(settings[field] for field in SETTINGS)
                    entry = known.get(key)
                    if entry is None:
                        if len(manifest["samples"]) >= MAX_ENTRIES:
                            raise ValidationError("Sample library entry limit exceeded.")
                        metrics, category, prefix, tags = characterize(payload, settings["loop_start"], settings["loop_length"])
                        # Names do not depend on an untrusted source label.
                        name = f"{prefix} {next_id:02d}"
                        entry = {"id": f"SMP-{next_id:04d}", "name": name, **settings,
                                 "pcm": f"pcm/{digest}.pcm", "bytes": len(payload),
                                 "category": category, "tags": tags, "metrics": metrics,
                                 "origin": "module-extracted", "classification": "heuristic-v1"}
                        entry["compatibility"] = _compatibility(entry, payload)
                        manifest["samples"].append(entry)
                        known[key] = entry
                        next_id += 1
                    payloads[digest] = payload
                    occurrence_id = f"{source_digest}:{module_index}:{slot}"
                    provenance["occurrences"][occurrence_id] = {
                        "entry_id": entry["id"], "module_sha256": module_digest, "filename": filename,
                        "module_title": raw[:20].decode("latin1").rstrip("\0 "), "slot": slot,
                        "original_name": raw[20 + (slot - 1) * 30:42 + (slot - 1) * 30].decode("latin1").rstrip("\0 "),
                        "original_header": list(layout.headers[slot - 1]), "archive_sha256": source_digest}
            if _digest(source.read_bytes()) != source_digest:
                raise ValidationError("Source changed during extraction; bank manifest was not updated.")
            for digest, payload in payloads.items():
                destination = self._path(f"pcm/{digest}.pcm")
                if destination.exists():
                    if destination.read_bytes() != payload:
                        raise ValidationError("Existing PCM differs from its content digest.")
                else:
                    project.atomic_bytes(destination, payload)
            if any(not isinstance(item, dict) or not isinstance(item.get("entry_id"), str)
                   for item in provenance["occurrences"].values()):
                raise ValidationError("Invalid private sample occurrences.")
            counts = Counter(item["entry_id"] for item in provenance["occurrences"].values())
            for entry in manifest["samples"]:
                entry["source_occurrences"] = counts[entry["id"]]
            project.atomic_bytes(self._path(".gitignore"), b"*\n!.gitignore\n")
            project.write_json(provenance_path, provenance)
            project.write_json(self._path("library.json"), manifest)
        return {"ok": True, "library": str(self.path), "modules": len(inputs), "sample_slots": slots,
                "new_entries": len(manifest["samples"]) - start_count, "entries": len(manifest["samples"]),
                "unique_pcm": len({item["pcm_sha256"] for item in manifest["samples"]}), "source_unchanged": True}

    def edit(self, sample_id: str, name: str | None = None, category: str | None = None,
             tags: list[str] | None = None) -> dict:
        with self._writer():
            manifest = self._manifest()
            entry = next((item for item in manifest["samples"] if item["id"] == sample_id), None)
            if entry is None:
                raise ValidationError(f"Unknown library sample: {sample_id}.")
            if name is not None:
                ascii_field(name, 22, "Sample name")
                if not name.strip():
                    raise ValidationError("Sample name must not be empty.")
                entry["name"] = name
            if category is not None:
                if category not in CATEGORIES:
                    raise ValidationError("Unknown category.")
                entry["category"] = category
            if tags is not None:
                entry["tags"] = _tags(tags)
            entry["classification"] = "user-edited"
            project.write_json(self._path("library.json"), manifest)
        return self.get(sample_id)

    def read_sample(self, sample_id: str) -> Sample:
        """Verified stored PCM for inspection; it may be outside the MOD profile."""
        entry = self.get(sample_id)
        return _sample(entry, self._pcm(entry))

    def sample(self, sample_id: str, adapt: bool = False) -> tuple[Sample, list[str]]:
        sample = self.read_sample(sample_id)
        changes = []
        if adapt and not sample.loop_length:
            if sample.loop_start:
                sample.loop_start = 0
                changes.append("clear-inactive-loop-start")
            if any(sample.pcm[:2]):
                sample.pcm = (0, 0) + sample.pcm
                changes.append("prepend-two-zero-bytes")
        try:
            validate_sample(sample)
        except ValueError as exc:
            raise ValidationError(f"{sample_id} is incompatible with the current MOD profile: {exc}") from exc
        return sample, changes

    def insert(self, module: Module, sample_id: str, slot: int | None = None,
               replace: bool = False, adapt: bool = False) -> tuple[Module, dict]:
        validate(module)
        sample_source.guard_insert(module, "library")
        sample, changes = self.sample(sample_id, adapt)
        result = copy.deepcopy(module)
        used = {value.sample for pattern in result.patterns for value in pattern.cells.values() if value.sample}
        if slot is None:
            slot = next((index for index, item in enumerate(result.samples, 1)
                         if not item.pcm and index not in used), len(result.samples) + 1)
        require_int(slot, "slot", 1, 31)
        if slot > len(result.samples) + 1:
            raise ValidationError("Choose an existing slot or the next slot; gaps are not inserted.")
        if slot <= len(result.samples):
            if result.samples[slot - 1].pcm and not replace:
                raise ValidationError("Sample slot is occupied; --replace is required.")
            result.samples[slot - 1] = sample
        else:
            result.samples.append(sample)
        info = {"library_id": sample_id, "origin": "module-extracted", "adaptations": changes}
        sources = result.metadata.setdefault("sample_sources", {})
        if not isinstance(sources, dict):
            raise ValidationError("Project metadata.sample_sources must be an object.")
        sources[str(slot)] = info
        validate(result)
        return result, {"slot": slot, **info}

    def audition(self, sample_id: str, output: Path, note: str = "C-2", seconds: float = 1.0) -> dict:
        """Raw sample audition: no tracker effects; not a claimed original pitch."""
        from .audio import audition_sample
        if note not in NOTE_TO_PERIOD or not math.isfinite(seconds) or not .05 <= seconds <= 5:
            raise ValidationError("Audition requires a tracker note C-1..B-3 and 0.05–5 seconds.")
        output = Path(output).resolve()
        if output.suffix.lower() != ".wav" or output.is_relative_to(self.path):
            raise ValidationError("Audition output must be a WAV outside the sample bank.")
        entry = self.get(sample_id)
        require_int(entry["volume"], "volume", 0, 64)
        sample = _sample(entry, self._pcm(entry))
        result = audition_sample(sample, output, note, seconds)
        return {"ok": True, "id": sample_id, **result}

    def audit(self) -> dict:
        entries = self._manifest()["samples"]
        compatible, categories = 0, Counter()
        for entry in entries:
            raw = self._pcm(entry)
            compatible += _compatibility(entry, raw)["compatible"]
            categories[entry["category"]] += 1
        return {"ok": True, "entries": len(entries),
                "unique_pcm": len({entry["pcm_sha256"] for entry in entries}),
                "source_occurrences": sum(entry.get("source_occurrences", 0) for entry in entries),
                "compatible_entries": compatible, "incompatible_entries": len(entries) - compatible,
                "categories": dict(categories), "classification_note":
                "Heuristic labels are editable; no human listening validation is implied."}
