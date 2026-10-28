"""Playback loudness of samples and the reference levels that created samples are matched to.

Standard library only. A sample's loudness is the RMS of its audible PCM times its MOD volume / 64,
in dB relative to a full-scale 8-bit signal. It ignores the song (Cxx volume effects, arpeggios,
other channels) and the ear's frequency weighting, so it is a measurement of the sample at its
default volume, not of how loud a mix sounds.
"""

from __future__ import annotations

import math
import statistics

from .model import Sample, ValidationError

FLOOR_DB = -120.0
WINDOW = 64  # bytes per envelope window when finding the audible part of a one-shot
AUDIBLE_FRACTION = 0.1  # a window counts while its RMS is at least 10 % (-20 dB) of the loudest window
GROUPS = ("percussion", "bass", "lead", "texture")
ROLES = {"kick": "percussion", "snare": "percussion", "hat": "percussion", "bass": "bass",
         "lead": "lead", "chord": "lead", "texture": "texture"}
BASS_BELOW_HZ = 200.0  # a tonal recipe whose C-2 pitch is below this is treated as a bass

# Quartile playback loudness (dB re full scale, RMS x volume / 64) per group, from an aggregate
# measurement of a local 88-entry sample bank (module-extracted PCM at each entry's own volume).
# Plain numbers only: they let public users without a bank get balanced created samples.
DEFAULT_REFERENCE_DB = {"percussion": {"p25": -11.9, "p50": -6.2, "p75": -3.8},
                        "bass": {"p25": -8.5, "p50": -7.3, "p75": -5.0},
                        "lead": {"p25": -12.5, "p50": -9.9, "p75": -5.9},
                        "texture": {"p25": -6.2, "p50": -2.8, "p75": -1.7}}
# Inside a group, a role aims at one point of the bank's own distribution: a kick is among the louder
# percussion samples, a hat among the quieter ones. Every other role aims at the median.
ROLE_QUANTILE = {"kick": "p75", "snare": "p50", "hat": "p25"}


def _db(value: float) -> float:
    return round(20 * math.log10(value), 2) if value > 1e-9 else FLOOR_DB


def audible_region(sample: Sample) -> tuple[int, int]:
    """The loop for looped samples; for one-shots the start up to the last window within 20 dB of the loudest."""
    pcm = sample.pcm
    if sample.loop_length and sample.loop_start + sample.loop_length <= len(pcm):
        return sample.loop_start, sample.loop_start + sample.loop_length
    windows = [pcm[start:start + WINDOW] for start in range(0, len(pcm), WINDOW)]
    levels = [math.sqrt(sum(value * value for value in window) / len(window)) for window in windows]
    loudest = max(levels, default=0)
    if loudest <= 0:
        return 0, len(pcm)
    last = max(index for index, level in enumerate(levels) if level >= loudest * AUDIBLE_FRACTION)
    return 0, min(len(pcm), (last + 1) * WINDOW)


def measure(sample: Sample, volume: int | None = None) -> dict:
    """Loudness facts for `sample` at `volume` (default: its own). Values are dB re full scale (128)."""
    level = max(0, min(64, sample.volume if volume is None else volume))
    start, end = audible_region(sample)
    region = sample.pcm[start:end]
    if not region:
        return {"volume": level, "rms": 0.0, "peak": 0.0, "region": [start, end],
                "unity_rms_db": FLOOR_DB, "loudness_db": FLOOR_DB, "peak_db": FLOOR_DB}
    full_scale = 1 << (sample.bits - 1)  # 128 for a MOD sample, 32768 for a 16-bit XM sample
    rms = math.sqrt(sum(value * value for value in region) / len(region)) / full_scale
    peak = max(abs(value) for value in sample.pcm) / full_scale
    gain = level / 64
    return {"volume": level, "rms": round(rms, 6), "peak": round(peak, 6), "region": [start, end],
            "unity_rms_db": _db(rms), "loudness_db": _db(rms * gain), "peak_db": _db(peak * gain)}


def role_for_recipe(recipe: dict | None) -> str:
    """The role a recipe is most likely meant for, used when none is given."""
    recipe = recipe or {}
    kind = recipe.get("type")
    if kind in ("kick", "kick_hat"):
        return "kick"
    if kind in ("snare", "snare_hat"):
        return "snare"
    if kind == "hat":
        return "hat"
    if kind == "wave" and recipe.get("shape") == "noise":
        return "texture"
    frequency = recipe.get("frequency", 261.625565)
    if type(frequency) in (int, float) and frequency < BASS_BELOW_HZ:
        return "bass"
    return "lead"


def check_role(role: object) -> str:
    if role not in ROLES:
        raise ValidationError(f"role must be one of {sorted(ROLES)}, got {role!r}.", "RECIPE_INVALID")
    return role


def library_group(entry: dict) -> str:
    """Group of a sample-bank entry from its category and tags (heuristic labels, not listening)."""
    category, tags = entry.get("category"), set(entry.get("tags", ()))
    if category == "percussion":
        return "percussion"
    if category == "cycle":
        return "bass" if "bass-candidate" in tags and "bright" not in tags else "lead"
    return "texture"


def sample_role(sample: Sample, role: str | None = None) -> str:
    """Role (or, for plain PCM, a group name) used when reporting on a sample in a song."""
    if role in ROLES or role in GROUPS:
        return role
    if sample.recipe is not None:
        return role_for_recipe(sample.recipe)
    if not sample.loop_length:
        return "percussion"
    return "texture" if sample.loop_length > 256 else "lead"


def sample_group(sample: Sample, role: str | None = None) -> str:
    key = sample_role(sample, role)
    return ROLES.get(key, key)


def slot_role(sample: Sample, recorded: dict | None = None, bank: dict | None = None) -> tuple[str, str]:
    """(role or group, where it came from) for a sample slot of a song.

    In order: the role recorded in `metadata.sample_sources[slot]` ("recorded"), the recipe ("recipe"), the
    bank category of the slot's `library_id` when `bank` (id -> manifest entry) holds it ("library"), else
    the loop-length heuristic of `sample_role` ("heuristic").
    """
    recorded = recorded if isinstance(recorded, dict) else {}
    role = recorded.get("role")
    if role in ROLES or role in GROUPS:
        return role, "recorded"
    if sample.recipe is not None:
        return role_for_recipe(sample.recipe), "recipe"
    entry = bank.get(recorded.get("library_id")) if bank and isinstance(recorded.get("library_id"), str) else None
    if isinstance(entry, dict):
        return library_group(entry), "library"
    return sample_role(sample), "heuristic"


def is_percussion(role: str) -> bool:
    return ROLES.get(role, role) == "percussion"


def reachable_db(sample: Sample) -> float:
    """The loudest level the sample can reach without clipping: volume 64 and its peak at full scale."""
    facts = measure(sample, 64)
    if facts["peak"] <= 0:
        return FLOOR_DB
    return round(facts["loudness_db"] - _db(facts["peak"]), 2)


def _quantile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def reference_from_library(library) -> dict:
    """Aggregate levels per group from a SampleLibrary: count, median, spread and range. No names or IDs."""
    levels: dict[str, list[float]] = {group: [] for group in GROUPS}
    for entry in library._manifest()["samples"]:
        sample = library.read_sample(entry["id"])
        if not sample.pcm or not any(sample.pcm):
            continue
        result = measure(sample)
        if result["loudness_db"] > FLOOR_DB:
            levels[library_group(entry)].append(result["loudness_db"])
    groups = {}
    for group, values in levels.items():
        if not values:
            continue
        low, high = _quantile(values, .25), _quantile(values, .75)
        groups[group] = {"count": len(values), "p25_db": round(low, 2),
                         "p50_db": round(statistics.median(values), 2), "p75_db": round(high, 2),
                         "median_db": round(statistics.median(values), 2), "spread_db": round(high - low, 2),
                         "min_db": min(values), "max_db": max(values)}
    return {"groups": groups, "measure": "RMS of the audible PCM x volume / 64, dB re full scale",
            "spread": "interquartile range in dB"}


def default_group(group: str) -> dict:
    """The fixed fallback for one group in the same shape as a bank's: p25_db, p50_db, p75_db, median_db."""
    values = DEFAULT_REFERENCE_DB[group]
    return {"count": 0, "p25_db": values["p25"], "p50_db": values["p50"], "p75_db": values["p75"],
            "median_db": values["p50"]}


def target_db(key: str, reference: dict | None = None) -> float:
    """The level for a role (kick/snare/hat at their own quartile) or a group (median).

    `reference` is a library reference (see `reference_from_library`) or None for the fixed defaults.
    """
    group = ROLES.get(key, key)
    quantile = ROLE_QUANTILE.get(key, "p50")
    entry = reference["groups"].get(group) if reference else None
    entry = entry if entry and f"{quantile}_db" in entry else default_group(group)
    return float(entry[f"{quantile}_db"])


def role_targets(reference: dict | None = None) -> dict:
    return {role: target_db(role, reference) for role in ROLES}


def volume_for(sample: Sample, target: float) -> tuple[int, float]:
    """(volume 0-64, volume that would be needed) putting the sample's loudness on `target` dB."""
    unity = measure(sample)["unity_rms_db"]
    needed = 64 * 10 ** ((target - unity) / 20)
    return max(0, min(64, round(needed))), needed
