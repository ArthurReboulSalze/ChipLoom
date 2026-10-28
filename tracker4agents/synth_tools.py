"""Created-samples workflow: recipe insertion, loudness matching, the starter palette and auditions.

Standard library only. Used by the `recipe_sample` patch operation, `chiploom synth ...` and the MCP
adapter. Created samples are stored as recipes, so a project stays small and rebuilds identical PCM.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from . import loudness, sample_source
from .model import Module, Pattern, Sample, ValidationError, ascii_field, require_int, validate
from .synth import from_recipe, recipe_facts

MATCH_MODES = ("library", "defaults", "none")
DEFAULT_VOLUME = 40  # without matching and without an explicit volume, as everywhere else in the score
STYLES = ("default",)
EMPTY_SLOT = Sample("", (), 0, 0, 0, 0)


def parse_recipe(text: str) -> dict:
    """A recipe from inline JSON, or from a file with `@path` (handy where shell quoting is awkward)."""
    try:
        if text.startswith("@"):
            text = Path(text[1:]).read_text(encoding="utf-8")
        value = json.loads(text)
    except (OSError, ValueError) as exc:
        raise ValidationError(f"The recipe is not valid JSON: {exc}", "RECIPE_INVALID") from exc
    if not isinstance(value, dict):
        raise ValidationError("A recipe is a JSON object such as {\"type\": \"kick\"}.", "RECIPE_INVALID")
    return value


def library_exists(path: Path) -> bool:
    return (Path(path) / "library.json").is_file()


def resolve_reference(mode: str, library: Path | str | None = None) -> dict:
    """Levels to match to: a sample bank's medians, the fixed defaults, or nothing."""
    if mode not in MATCH_MODES:
        raise ValidationError(f"match must be one of {list(MATCH_MODES)}, got {mode!r}.", "PATCH_FIELD")
    if mode == "none":
        return {"source": "none", "groups": {}}
    if mode == "defaults":
        return {"source": "defaults", "groups": {group: loudness.default_group(group)
                                                  for group in loudness.GROUPS}}
    from .sample_library import SampleLibrary
    if library is None:
        raise ValidationError("match 'library' needs the bank folder in 'library'.", "PATCH_FIELD")
    if not library_exists(Path(library)):
        raise ValidationError(f"No sample bank at {Path(library)}; use match 'defaults' or build one.",
                              "SAMPLE_LIBRARY")
    reference = loudness.reference_from_library(SampleLibrary(Path(library)))
    # Groups the bank does not cover fall back to the fixed defaults.
    for group in loudness.GROUPS:
        reference["groups"].setdefault(group, loudness.default_group(group))
    return {"source": "library", **reference}


def automatic_reference(library: Path | str | None = None, default: Path | str | None = None) -> dict:
    """The loudness reference used when no match mode is forced, with `path`, `selection` and `reason`.

    One rule for `report`, `sample_match_level`, `synth add` and `synth palette`: an explicit `library`
    wins (it must exist); else the default bank (`sample_library.DEFAULT_LIBRARY`, relative to the working
    directory, or `default`) when it exists, for library and synthesized projects alike; else the fixed
    defaults in `loudness.DEFAULT_REFERENCE_DB`.
    """
    from . import sample_library
    if library is not None:
        return {**resolve_reference("library", library), "path": str(Path(library).resolve()),
                "selection": "explicit", "reason": "A sample bank was given explicitly."}
    folder = Path(sample_library.DEFAULT_LIBRARY if default is None else default)
    if library_exists(folder):
        return {**resolve_reference("library", folder), "path": str(folder.resolve()), "selection": "automatic",
                "reason": f"No bank was given; the default sample bank exists at {folder.resolve()}."}
    return {**resolve_reference("defaults"), "path": None, "selection": "automatic",
            "reason": f"No bank was given and there is no sample bank at {folder.resolve()}; fixed reference levels."}


def bank_entries(reference: dict | None) -> dict:
    """Manifest entries (id -> entry) of the bank behind a library `reference`, or {} for other references."""
    if not reference or reference.get("source") != "library" or not reference.get("path"):
        return {}
    from .sample_library import SampleLibrary
    try:
        return {entry["id"]: entry for entry in SampleLibrary(Path(reference["path"]))._manifest()["samples"]}
    except (OSError, ValueError, KeyError, ValidationError):
        return {}


def build(name: str, recipe: dict, finetune: int, role: str, reference: dict,
          volume: int | None = None) -> tuple[Sample, dict]:
    """Build the sample, set its MOD volume (and the recipe peak if needed) and describe the result."""
    recipe = copy.deepcopy(recipe)
    group = loudness.ROLES[role]
    start_peak = recipe.get("peak", 0.88)
    sample = from_recipe(name, recipe, DEFAULT_VOLUME if volume is None else volume, finetune)
    unmatched = loudness.measure(sample)
    record = {"role": role, "group": group, "reference": "explicit volume" if volume is not None
              else reference["source"], "target_db": None, "unmatched_db": unmatched["loudness_db"]}
    if volume is None and reference["source"] != "none":
        target = loudness.target_db(role, reference)
        record["target_db"] = target
        for _ in range(3):
            level, needed = loudness.volume_for(sample, target)
            peak = recipe.get("peak", 0.88)
            if needed <= 64.5 or peak >= 1:
                break
            recipe["peak"] = round(min(1.0, peak * needed / 64 * 1.002), 4)
            sample = from_recipe(name, recipe, 64, finetune)
        sample.volume = level
        record["limited_by_peak"] = needed > 64.5
    final = loudness.measure(sample)
    record.update(volume=sample.volume, measured_db=final["loudness_db"], peak_db=final["peak_db"])
    if record["target_db"] is not None:
        record["deviation_db"] = round(final["loudness_db"] - record["target_db"], 2)
    if recipe.get("peak", 0.88) != start_peak:
        record["peak_raised_from"] = start_peak
        record["peak"] = recipe["peak"]
    return sample, record


def insert_recipe(module: Module, name: str, recipe: object, slot: int | None = None, volume: int | None = None,
                  finetune: int = 0, replace: bool = False, role: str | None = None,
                  reference: dict | None = None) -> dict:
    """Put a created sample in a slot of `module` (in place). Returns the facts to report.

    `volume` given: used as is. Otherwise the volume is set from `reference` (see `resolve_reference`);
    without a reference it stays at the score default. Occupied slots need `replace`.

    In an XM the sample is converted like `convert` converts a MOD sample (`finetune` is still the MOD
    finetune -8..7, stored as 16 x finetune - 20) and keeps its recipe; instruments go up to 128.
    """
    sample_source.guard_insert(module, "recipe")
    ascii_field(name, 22, "Sample name")
    if not isinstance(recipe, dict):
        raise ValidationError("A recipe is a JSON object such as {\"type\": \"kick\"}.", "RECIPE_INVALID")
    require_int(finetune, "finetune", -8, 7)
    if volume is not None:
        require_int(volume, "volume", 0, 64)
    if type(replace) is not bool:
        raise ValidationError("replace must be true or false.", "PATCH_FIELD")
    role = loudness.role_for_recipe(recipe) if role is None else loudness.check_role(role)
    sample, record = build(name, recipe, finetune, role, reference or {"source": "none"}, volume)
    limit = 31
    if module.format == "xm":
        from .convert import mod_sample_to_xm
        sample, limit = mod_sample_to_xm(sample), 128
    used = {value.sample for pattern in module.patterns for value in pattern.cells.values() if value.sample}
    if slot is None:
        slot = next((index for index, item in enumerate(module.samples, 1)
                     if not item.pcm and index not in used), len(module.samples) + 1)
        if slot > limit:
            raise ValidationError(f"All {limit} sample slots are in use; choose a slot with replace.", "SAMPLE_SLOT")
    require_int(slot, "slot", 1, limit, "SAMPLE_SLOT")
    if slot > len(module.samples) + 1:
        raise ValidationError(f"Choose an existing slot or the next free one ({len(module.samples) + 1}); "
                              "gaps are not inserted.", "SAMPLE_SLOT")
    if slot <= len(module.samples):
        existing = module.samples[slot - 1]
        if existing.pcm and not replace:
            raise ValidationError(f"Sample slot {slot} is occupied by {existing.name!r}; "
                                  "pass replace (CLI: --replace) to overwrite it.", "SAMPLE_SLOT")
        module.samples[slot - 1] = sample
    else:
        module.samples.append(sample)
    sources = module.metadata.setdefault("sample_sources", {})
    if not isinstance(sources, dict):
        raise ValidationError("Project metadata.sample_sources must be an object.", "SCHEMA")
    sources[str(slot)] = {"origin": "synthesized", "recipe_type": sample.recipe.get("type"), "role": role}
    return {"slot": slot, "name": name, "origin": "synthesized", "role": role,
            "sample": recipe_facts(sample), "loudness": record}


# --- the starter palette --------------------------------------------------------------------

# (name, role, hand-set volume, recipe, use). The hand-set volumes and the drum recipes come from the
# Pixel Rush palette; the waves are the same timbres as its drawn cycles, now tuned. Seeds are fixed.
PALETTE = (
    ("Kick", "kick", 56, {"type": "kick", "duration": 0.16, "peak": 0.93, "seed": 104740, "drive": 0.5},
     "Drums: low thump. Pitch is irrelevant; trigger at C-2."),
    ("Snare", "snare", 49, {"type": "snare", "duration": 0.09, "peak": 0.86, "seed": 104741, "drive": 0.3},
     "Drums: noise snare. Trigger at C-2."),
    ("Hat", "hat", 24, {"type": "hat", "duration": 0.025, "peak": 0.74, "seed": 104742, "drive": 0.3},
     "Drums: closed hat tick. Trigger at C-2; keep it off the beat for movement."),
    ("Kick+hat", "kick", 56, {"type": "kick_hat", "duration": 0.16, "peak": 0.93, "seed": 104743, "drive": 0.5},
     "Drums: kick with a hat on top: two hits from one drum channel."),
    ("Snare+hat", "snare", 49, {"type": "snare_hat", "duration": 0.09, "peak": 0.86, "seed": 104744, "drive": 0.3},
     "Drums: snare with a hat on top."),
    ("Triangle bass", "bass", 43, {"type": "wave", "shape": "triangle", "frequency": 130.812783, "peak": 0.88},
     "Bass: soft round low line; notes in octaves 1-2. Cut notes with C00 for staccato."),
    ("Pulse bass", "bass", 36, {"type": "wave", "shape": "pulse", "duty": 0.25, "frequency": 130.812783,
                                "peak": 0.82},
     "Bass: brighter 25 % pulse for accents; mix with the triangle bass."),
    ("Pulse 12 lead", "lead", 39, {"type": "wave", "shape": "pulse", "duty": 0.125, "frequency": 261.625565,
                                   "peak": 0.82},
     "Lead: thin reedy 12.5 % pulse. Switch between the pulse leads mid-note for pulse-width movement."),
    ("Pulse 25 lead", "lead", 39, {"type": "wave", "shape": "pulse", "duty": 0.25, "frequency": 261.625565,
                                   "peak": 0.82},
     "Lead: the all-round 25 % pulse."),
    ("Pulse 50 lead", "lead", 39, {"type": "wave", "shape": "pulse", "duty": 0.5, "frequency": 261.625565,
                                   "peak": 0.82},
     "Lead: hollow square, the fullest of the pulses."),
    ("Triangle chord", "chord", 26, {"type": "wave", "shape": "triangle", "frequency": 261.625565,
                                     "peak": 0.78},
     "Chords and arpeggios: soft; use 037/047 arpeggio effects at note starts."),
    ("Noise texture", "texture", 20, {"type": "wave", "shape": "noise", "binary": True, "length": 2048,
                                      "peak": 0.75, "seed": 104749},
     "Texture: looped 1-bit noise bed or riser; stop it with C00. Higher notes sound brighter."),
    ("Pluck lead", "lead", 39, {"type": "pluck", "frequency": 261.625565, "duration": 0.36, "duty": 0.3,
                                "peak": 0.86, "seed": 104747, "drive": 0.3},
     "Lead: one-shot pluck with a baked decay; re-trigger each note."),
)


def palette(title: str = "Synth Palette", style: str = "default", reference: dict | None = None,
            channels: int = 4, fmt: str = "mod") -> tuple[Module, dict]:
    """A new empty-song project holding the starter palette, plus a report of every slot.

    With a `reference` (see `resolve_reference`) each slot's volume is matched to its role's level;
    with `reference=None` the hand-set Pixel Rush volumes are kept. `channels` is 2-32; with `fmt="xm"`
    the project is an XM (see `xm.blank`) whose instruments are converted like `convert` does.
    """
    if style not in STYLES:
        raise ValidationError(f"style must be one of {list(STYLES)}, got {style!r}.", "PATCH_FIELD")
    if fmt not in ("mod", "xm"):
        raise ValidationError(f"format must be mod or xm, got {fmt!r}.", "FORMAT")
    require_int(channels, "channels", 2, 32, "CHANNELS")
    ascii_field(title, 20, "Song title")
    metadata = {
        "sample_source": "synthesized",
        "description": "Songs made only with created samples. Every sample is a ChipLoom recipe.",
        "palette": {"style": style, "reference": (reference or {"source": "none"})["source"]},
    }
    if fmt == "xm":
        from .xm import blank
        module = blank(title, channels, metadata=metadata)
    else:
        module = Module(title, [copy.deepcopy(EMPTY_SLOT)], [Pattern("Pattern 00")], [0], metadata, channels)
    slots = []
    for name, role, hand_volume, recipe, use in PALETTE:
        if reference is None:
            info = insert_recipe(module, name, recipe, volume=hand_volume, role=role)
        else:
            info = insert_recipe(module, name, recipe, role=role, reference=reference)
        hand = loudness.measure(from_recipe(name, recipe, hand_volume))["loudness_db"]
        loud = info["loudness"]
        slots.append({"slot": info["slot"], "name": name, "role": role, "use": use, "recipe": module.samples[
            info["slot"] - 1].recipe, "volume": loud["volume"], "hand_set_volume": hand_volume,
            "hand_set_db": hand, "target_db": loud["target_db"], "measured_db": loud["measured_db"],
            "deviation_db": loud.get("deviation_db"), "limited_by_peak": loud.get("limited_by_peak", False),
            "bytes": info["sample"]["bytes"], "looped": info["sample"]["looped"],
            "tuning_cents": info["sample"].get("tuning_cents")})
    module.metadata["palette"]["roles"] = {str(entry["slot"]): f"{entry['role']}: {entry['name']}"
                                           for entry in slots}
    validate(module)
    return module, {"slots": slots, "free_slots": f"{len(slots) + 1}-{128 if fmt == 'xm' else 31}"}


# --- audition -------------------------------------------------------------------------------

def check_preview_note(note: object) -> None:
    """Previews take MOD note labels (C-1..B-3). Explain the XM labels, which sit two octaves higher."""
    from .model import NOTE_TO_PERIOD, NOTES, XM_NOTE_TO_NUMBER
    if note in NOTE_TO_PERIOD:
        return
    hint = ""
    if isinstance(note, str) and note in XM_NOTE_TO_NUMBER:
        index = XM_NOTE_TO_NUMBER[note] - 37  # XM C-4 (number 49) is MOD C-2 (index 12), as in `convert`
        if 0 <= index < len(NOTES):
            hint = f" {note} (XM) is {NOTES[index]} (MOD): XM labels sit two octaves above MOD ones."
        else:
            hint = f" {note} (XM) is outside the MOD range C-3..B-5 (XM) that previews cover."
    raise ValidationError(f"Previews use MOD note labels C-1..B-3 (C-2 is the sample's base note), got {note!r}."
                          f"{hint}", "NOTE_UNKNOWN")


def preview(recipe: dict, name: str, output: Path, note: str = "C-2", seconds: float = 1.0,
            volume: int = 64, finetune: int = 0, role: str | None = None) -> dict:
    """Render a recipe to a WAV at a tracker note, with measurements for an agent that cannot listen."""
    from . import audio
    output = Path(output).resolve()
    if output.suffix.lower() != ".wav":
        raise ValidationError("A preview is written as a .wav file.", "OUTPUT_PATH")
    require_int(volume, "volume", 0, 64)
    require_int(finetune, "finetune", -8, 7)
    ascii_field(name, 22, "Sample name")
    check_preview_note(note)
    sample = from_recipe(name, recipe, volume, finetune)
    result = audio.audition_sample(sample, output, note, seconds)
    role = loudness.role_for_recipe(recipe) if role is None else loudness.check_role(role)
    return {"ok": True, "name": name, "recipe": recipe, **result, "volume": volume, "finetune": finetune,
            "sample": recipe_facts(sample), **audition_measurements(sample, output, role)}


def audition_measurements(sample: Sample, output: Path, role: str | None, group: str | None = None) -> dict:
    """The `loudness` and `audio` blocks shared by synth and library previews.

    `role` is a recipe role; a library sample has none and passes its loudness `group` instead.
    """
    from . import audio
    metrics = audio.analyze_wav(output)
    level = loudness.measure(sample)
    key = role if role is not None else group
    return {"loudness": {"role": role, "group": loudness.ROLES.get(key, key), "loudness_db": level["loudness_db"],
                         "peak_db": level["peak_db"], "default_reference_db": loudness.target_db(key),
                         "note": "Sample loudness at this volume (RMS of its audible part), dB re full scale."},
            "audio": {key: metrics[key] for key in ("peak", "peak_dbfs", "rms_dbfs", "clipped_samples")}}


def levels(library: Path | None, explicit: bool) -> dict:
    """Reference levels per group: aggregate only (counts, medians, spread), never names or IDs."""
    use_library = library is not None and (explicit or library_exists(library))
    reference = resolve_reference("library", library) if use_library else resolve_reference("defaults")
    return {"ok": True, "source": reference["source"], "groups": reference["groups"],
            "role_targets_db": loudness.role_targets(reference), "role_points": {
                role: loudness.ROLE_QUANTILE.get(role, "p50") for role in loudness.ROLES},
            "defaults_db": loudness.DEFAULT_REFERENCE_DB, "roles": loudness.ROLES,
            "measure": "RMS of the audible PCM x volume / 64, dB re full scale (128). "
                       "Audible part: the loop, or a one-shot up to its last window within 20 dB of the loudest.",
            "notes": "Groups come from heuristic categories and tags. Kick targets p75, hat p25 and every other role the "
                     "median (p50) of its group."}
