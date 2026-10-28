"""Measurements of a composition and a record of listening feedback.

Everything in :func:`analyze` is a measurement of the symbolic score, taken along
the actual playback timeline (repeated orders, jumps and tempo changes count as
played). Nothing here is an aesthetic verdict. The only estimate is the musical
key, which is labelled as such.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import math
from pathlib import Path

from . import loudness, sample_source
from .model import EFFECT_DIGITS, NOTES, PITCHES, XM_KEY_OFF, XM_NOTES, Module, ValidationError, playback_plan, xm_profile

SCHEMA = "chiploom.report.v1"
LONG_SILENCE_SECONDS = 2.0
LEVEL_WARNING_DB = 6.0
MAX_FEEDBACK_TEXT = 2000
MAX_TEMPO_EVENTS = 32
BLOCK_SIZES = (4, 8, 16)
PITCH_CLASS_NAMES = tuple(name.rstrip("-") for name in PITCHES)

# Krumhansl-Kessler (1982) probe-tone profiles, tonic first.
KK_MAJOR = (6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88)
KK_MINOR = (6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17)
KEY_MIN_NOTES = 6
KEY_MIN_PITCH_CLASSES = 3
KEY_CAVEAT = (
    "Estimate, not a fact. Tracker note names are period labels: sample tuning is unknown, so the "
    "sounding pitch can be offset from the written note. Every note start is counted, including "
    "percussion samples triggered at fixed pitches, and a major key and its relative minor often "
    "correlate almost equally (see margin)."
)
KEY_CONFIDENCE_RULE = (
    "Heuristic thresholds chosen for this tool, not perceptual data: margin >= 0.10 high, "
    ">= 0.03 medium, otherwise low. The margin is the correlation gap between the best and "
    "second-best of the 24 candidate keys."
)
SCOPE = (
    "Measurements of the symbolic score along its playback timeline (first replay cycle, including "
    "repeated orders, jumps and tempo changes). A note start is a cell with a note that is not a "
    "tone-portamento target (3xx/5xx). Sustained or looped samples can still sound where no note "
    "starts, so 'rows without a note start' is not audible silence. These numbers describe the "
    "score; they are not judgments of musical quality. Channels are numbered from 0, as in patch operations."
)


def _round(value: float, digits: int = 6) -> float:
    return round(value, digits)


def _pearson(left: tuple[float, ...] | list[float], right: tuple[float, ...] | list[float]) -> float | None:
    mean_left, mean_right = sum(left) / len(left), sum(right) / len(right)
    covariance = sum((a - mean_left) * (b - mean_right) for a, b in zip(left, right))
    spread = math.sqrt(sum((a - mean_left) ** 2 for a in left) * sum((b - mean_right) ** 2 for b in right))
    return covariance / spread if spread else None


def estimate_key(histogram: list[int] | tuple[int, ...]) -> dict:
    """Krumhansl-Kessler key estimate from a 12-bin pitch-class histogram (index 0 = C)."""
    if len(histogram) != 12:
        raise ValidationError("A pitch-class histogram needs exactly 12 bins.")
    total = sum(histogram)
    present = sum(1 for count in histogram if count)
    if total < KEY_MIN_NOTES or present < KEY_MIN_PITCH_CLASSES:
        return {"available": False, "is_estimate": True, "notes_counted": total,
                "reason": f"At least {KEY_MIN_NOTES} note starts over {KEY_MIN_PITCH_CLASSES} pitch classes "
                          "are needed for an estimate.", "caveat": KEY_CAVEAT}
    candidates = []
    for tonic in range(12):
        for mode, profile in (("major", KK_MAJOR), ("minor", KK_MINOR)):
            rotated = [profile[(pitch - tonic) % 12] for pitch in range(12)]
            correlation = _pearson(list(histogram), rotated)
            if correlation is not None:
                candidates.append((-correlation, tonic, mode))
    candidates.sort()
    best, second = candidates[0], candidates[1]
    margin = second[0] - best[0]
    confidence = "high" if margin >= 0.10 else "medium" if margin >= 0.03 else "low"

    def entry(item: tuple[float, int, str]) -> dict:
        return {"key": f"{PITCH_CLASS_NAMES[item[1]]} {item[2]}", "tonic": PITCH_CLASS_NAMES[item[1]],
                "mode": item[2], "correlation": _round(-item[0])}

    return {"available": True, "is_estimate": True, **entry(best), "margin": _round(margin),
            "confidence": confidence, "confidence_rule": KEY_CONFIDENCE_RULE,
            "runner_up": entry(second), "top_candidates": [entry(item) for item in candidates[:3]],
            "notes_counted": total, "method": "Krumhansl-Kessler profiles, Pearson correlation, 24 keys",
            "caveat": KEY_CAVEAT}


def _longest_run(flags: list[bool], seconds: list[float]) -> dict:
    """Longest stretch (by duration, first one wins ties) of consecutive rows where the flag is False."""
    best = {"rows": 0, "seconds": 0.0, "start_played_row": None}
    run_rows, run_seconds, start = 0, 0.0, 0
    for index, flag in enumerate(flags):
        if flag:
            run_rows, run_seconds = 0, 0.0
            continue
        if run_rows == 0:
            start = index
        run_rows += 1
        run_seconds += seconds[index]
        if run_seconds > best["seconds"] + 1e-12:
            best = {"rows": run_rows, "seconds": run_seconds, "start_played_row": start}
    best["seconds"] = _round(best["seconds"])
    return best


def _block_stats(signatures: list, size: int, empty_row: object) -> dict:
    blocks = [tuple(signatures[start:start + size]) for start in range(0, len(signatures) - size + 1, size)]
    empty_block = (empty_row,) * size
    distinct = {block for block in blocks if block != empty_block}
    empty = sum(block == empty_block for block in blocks)
    non_empty = len(blocks) - empty
    return {"total": len(blocks), "empty": empty, "non_empty": non_empty, "distinct": len(distinct),
            "repeated_fraction": _round(1 - len(distinct) / non_empty) if non_empty else None}


def library_mode(module: Module) -> str | None:
    """Why `module` counts as a library-mode project, or None: a declared source or recorded library IDs."""
    metadata = module.metadata if isinstance(module.metadata, dict) else {}
    if metadata.get("sample_source") == "library":
        return "metadata.sample_source is 'library'"
    sources = metadata.get("sample_sources")
    if isinstance(sources, dict) and any(isinstance(item, dict) and item.get("library_id")
                                         for item in sources.values()):
        return "metadata.sample_sources records library IDs"
    return None


def loudness_reference(module: Module, library: Path | None = None, default: Path | None = None) -> dict:
    """The loudness reference for `analyze`, with `path` and `reason` saying which one and why.

    An explicit `library` always wins. A library-mode project (see `library_mode`) uses the default bank
    (`sample_library.DEFAULT_LIBRARY`, relative to the working directory) when it exists. Otherwise the
    fixed defaults in `loudness.DEFAULT_REFERENCE_DB` are used.
    """
    from .sample_library import DEFAULT_LIBRARY
    from .synth_tools import library_exists, resolve_reference
    if library is not None:
        reference = resolve_reference("library", library)
        return {**reference, "path": str(Path(library).resolve()), "selection": "explicit",
                "reason": "--library was given."}
    default = Path(DEFAULT_LIBRARY if default is None else default)
    why = library_mode(module)
    if why is None:
        return {**resolve_reference("defaults"), "path": None, "selection": "automatic",
                "reason": "Not a library-mode project (no metadata.sample_source 'library' and no library IDs); "
                          "fixed reference levels."}
    if not library_exists(default):
        return {**resolve_reference("defaults"), "path": None, "selection": "automatic",
                "reason": f"Library-mode project ({why}) but no sample bank at {default.resolve()}; "
                          "fixed reference levels. Pass --library to use another bank."}
    return {**resolve_reference("library", default), "path": str(default.resolve()), "selection": "automatic",
            "reason": f"Library-mode project ({why}); the default sample bank was found."}


def analyze(module: Module, reference: dict | None = None) -> dict:
    """Deterministic, JSON-serializable measurements of the played score.

    `reference` (see `synth_tools.resolve_reference`) gives the loudness each group is compared with;
    without it the fixed reference levels in `loudness.DEFAULT_REFERENCE_DB` are used. Build it with
    `loudness_reference` to have the report say which reference was chosen and why.
    """
    if reference is None:
        reference_info = {"source": "defaults", "path": None, "selection": "default",
                          "reason": "No reference was given; fixed reference levels."}
    else:
        reference_info = {"source": reference.get("source", "library"), "path": reference.get("path"),
                          "selection": reference.get("selection", "explicit"),
                          "reason": reference.get("reason", "Reference passed by the caller.")}
    plan = playback_plan(module)  # Validates the module as well.
    timeline = plan["timeline"]
    rows = len(timeline)
    # An EEx pattern delay stretches its row; N channels and XM notes follow the module's own format.
    row_seconds = [item["speed"] * 2.5 / item["bpm"] * (1 + item.get("delay", 0)) for item in timeline]
    xm = module.format == "xm"
    count = module.channels
    note_names = XM_NOTES if xm else NOTES
    default_speed, default_bpm = ((xm_profile(module).get("default_speed", 6), xm_profile(module).get("default_bpm", 125))
                                  if xm else (6, 125))
    empty_signature = (0,) * (5 if xm else 4)
    duration = plan["duration_seconds"]
    loop_start_seconds = plan["loop_start_seconds"]
    loop_start_played_row = next(index for index, item in enumerate(timeline) if item["seconds"] == loop_start_seconds)

    # One pass over the played rows: cells, note starts and the sample each note uses.
    signatures: list[list[tuple[int, ...]]] = [[] for _ in range(count)]
    note_flags = [[False] * rows for _ in range(count)]
    channel_notes: list[list[int]] = [[] for _ in range(count)]
    channel_samples: list[dict[int, int]] = [{} for _ in range(count)]
    channel_effects: list[dict[str, int]] = [{} for _ in range(count)]
    channel_extended: list[dict[str, int]] = [{} for _ in range(count)]
    portamento_targets = [0] * count
    current_sample = [0] * count
    notes_without_sample = [0] * count
    sample_channels: dict[int, set[int]] = {}
    for index, item in enumerate(timeline):
        pattern = module.patterns[item["pattern"]]
        for channel in range(count):
            value = pattern.get(item["row"], channel)
            signatures[channel].append((value.period, value.sample, value.command, value.param)
                                       + ((value.volume,) if xm else ()))
            if value.sample:
                current_sample[channel] = value.sample
            if value.command or value.param:
                letter = EFFECT_DIGITS[value.command]
                channel_effects[channel][letter] = channel_effects[channel].get(letter, 0) + 1
                if value.command == 14:
                    extended = f"E{value.param >> 4:X}"
                    channel_extended[channel][extended] = channel_extended[channel].get(extended, 0) + 1
            if not value.period or value.period == XM_KEY_OFF and xm:
                continue
            if value.command in (3, 5) or (xm and value.volume >= 0xF0):
                portamento_targets[channel] += 1
                continue
            note_flags[channel][index] = True
            channel_notes[channel].append(value.period - 1 if xm else NOTES.index(value.note))
            slot = current_sample[channel]
            if slot:
                channel_samples[channel][slot] = channel_samples[channel].get(slot, 0) + 1
                sample_channels.setdefault(slot, set()).add(channel)
            else:
                notes_without_sample[channel] += 1

    channels = []
    for channel in range(count):
        notes = channel_notes[channel]
        gap = _longest_run(note_flags[channel], row_seconds)
        entry = {
            "channel": channel, "note_ons": len(notes),
            "notes_per_second": _round(len(notes) / duration) if duration else 0.0,
            "density": _round(len(notes) / rows) if rows else 0.0,
            "lowest_note": note_names[min(notes)] if notes else None,
            "highest_note": note_names[max(notes)] if notes else None,
            "range_semitones": max(notes) - min(notes) if notes else None,
            "samples_used": sorted(channel_samples[channel]),
            "effects": dict(sorted(channel_effects[channel].items())),
            "extended_effects": dict(sorted(channel_extended[channel].items())),
            "portamento_targets": portamento_targets[channel],
            "notes_without_sample": notes_without_sample[channel],
            "longest_gap_without_note": gap,
        }
        channels.append(entry)

    any_note = [any(note_flags[channel][index] for channel in range(count)) for index in range(rows)]
    no_note = _longest_run(any_note, row_seconds)
    histogram = [0] * 12
    for notes in channel_notes:
        for number in notes:
            histogram[number % 12] += 1
    total_notes = sum(histogram)

    # Timing: state after each row's commands; the replay starts at speed 6, BPM 125.
    events = []
    previous = (default_speed, default_bpm)
    change_count = 0
    for item in timeline:
        state = (item["speed"], item["bpm"])
        if state != previous:
            change_count += 1
            if len(events) < MAX_TEMPO_EVENTS:
                events.append({"seconds": item["seconds"], "order": item["order"], "row": item["row"],
                               "speed": item["speed"], "bpm": item["bpm"]})
            previous = state
    orders_played: list[int] = []
    for item in timeline:
        if item["order"] not in orders_played:
            orders_played.append(item["order"])
    timing = {
        "duration_seconds": duration, "loop_start_seconds": loop_start_seconds,
        "loop_start_played_row": loop_start_played_row, "loop_seconds": _round(duration - loop_start_seconds, 9),
        "rows_played": rows, "orders_played": len(orders_played), "default_speed": default_speed,
        "default_bpm": default_bpm,
        "speed_min": min(item["speed"] for item in timeline), "speed_max": max(item["speed"] for item in timeline),
        "bpm_min": min(item["bpm"] for item in timeline), "bpm_max": max(item["bpm"] for item in timeline),
        "tempo_changes": {"count": change_count, "events": events,
                          "truncated": change_count > len(events)},
    }

    # Repetition. Patterns are compared by content; names are ignored.
    def pattern_key(index: int) -> tuple:
        return tuple(sorted(module.patterns[index].cells.items()))

    groups: dict[tuple, list[int]] = {}
    for index in range(len(module.patterns)):
        groups.setdefault(pattern_key(index), []).append(index)
    identical = [members for members in groups.values() if len(members) > 1]
    seen_contents: set[tuple] = set()
    reusing = 0
    for position in orders_played:
        content = pattern_key(module.orders[position])
        if content in seen_contents:
            reusing += 1
        seen_contents.add(content)
    played_patterns = {item["pattern"] for item in timeline}
    blocks = {}
    combined = [tuple(signatures[channel][index] for channel in range(count)) for index in range(rows)]
    for size in BLOCK_SIZES:
        blocks[str(size)] = {
            "channels": [{"channel": channel, **_block_stats(signatures[channel], size, empty_signature)}
                         for channel in range(count)],
            "all_channels": _block_stats(combined, size, (empty_signature,) * count),
        }
    repetition = {
        "identical_pattern_groups": identical, "stored_patterns": len(module.patterns),
        "distinct_pattern_contents": len(groups),
        "order_slots_played": len(orders_played),
        "distinct_pattern_contents_played": len(seen_contents),
        "order_slots_reusing_earlier_pattern": reusing,
        "patterns_never_played": [index for index in range(len(module.patterns)) if index not in played_patterns],
        "blocks": blocks,
        "block_method": "Non-overlapping blocks aligned to the first played row, compared as exact cells "
                        "(note, sample, effect); only full blocks are counted; empty blocks are reported separately.",
    }

    # Sample usage over the whole song.
    sources = module.metadata.get("sample_sources", {}) if isinstance(module.metadata, dict) else {}
    samples = []
    never_played = []
    empty_slots = []
    for slot, sample in enumerate(module.samples, 1):
        if not sample.pcm:
            empty_slots.append(slot)
            continue
        count_played = sum(channel_samples[channel].get(slot, 0) for channel in range(count))
        recorded = sources.get(str(slot)) if isinstance(sources, dict) else None
        key = loudness.sample_role(sample, recorded.get("role") if isinstance(recorded, dict) else None)
        group = loudness.ROLES.get(key, key)
        level = loudness.measure(sample)["loudness_db"]
        wanted = loudness.target_db(key, reference)
        samples.append({"slot": slot, "name": sample.name, "bytes": len(sample.pcm), "looped": bool(sample.loop_length),
                        "volume": sample.volume, "note_ons": count_played,
                        "channels": sorted(sample_channels.get(slot, ())),
                        "source": "recipe" if sample.recipe is not None else "embedded_pcm",
                        "loudness_db": level, "peak_db": loudness.measure(sample)["peak_db"], "group": group,
                        "reference_db": wanted, "deviation_db": round(level - wanted, 2)})
        if not count_played:
            never_played.append(slot)
    found = sample_source.counts(module)
    sample_usage = {"slots_with_audio": len(samples), "empty_slots": empty_slots,
                    "never_played_slots": never_played,
                    "sources": {"recipe": found["recipe"], "embedded_pcm": found["embedded_pcm"],
                                "declared": module.metadata.get("sample_source")},
                    "loudness_note": "loudness_db: RMS of the audible PCM x volume / 64, dB re full scale, at the "
                                     "sample's default volume (Cxx and arpeggios are not applied). reference_db: "
                                     "the level of its group in the loudness_reference (median; kick p75, hat p25).",
                    "loudness_reference": reference_info,
                    "slots": samples}

    # Factual flags only.
    warnings = []
    for entry in channels:
        if not entry["note_ons"]:
            warnings.append({"code": "channel_never_plays", "channel": entry["channel"],
                             "message": f"Channel {entry['channel']} starts no note during the played timeline."})
        if entry["notes_without_sample"]:
            warnings.append({"code": "note_without_sample", "channel": entry["channel"],
                             "message": f"Channel {entry['channel']} starts {entry['notes_without_sample']} note(s) "
                                        "before any sample number was set on it."})
    for slot in never_played:
        warnings.append({"code": "sample_never_played", "slot": slot,
                         "message": f"Sample slot {slot} ({module.samples[slot - 1].name!r}) holds audio but no note plays it."})
    for entry in samples:
        if abs(entry["deviation_db"]) > LEVEL_WARNING_DB and entry["note_ons"]:
            warnings.append({"code": "sample_level_off_reference", "slot": entry["slot"],
                             "deviation_db": entry["deviation_db"],
                             "message": f"Sample slot {entry['slot']} ({entry['name']!r}) is {abs(entry['deviation_db']):.1f} dB "
                                        f"{'above' if entry['deviation_db'] > 0 else 'below'} the {entry['group']} "
                                        f"reference ({entry['reference_db']} dB); more than {LEVEL_WARNING_DB:.0f} dB apart."})
    if no_note["seconds"] > LONG_SILENCE_SECONDS:
        warnings.append({"code": "long_stretch_without_note", "seconds": no_note["seconds"],
                         "message": f"No channel starts a note for {no_note['seconds']:.2f} s "
                                    f"({no_note['rows']} rows from played-row index {no_note['start_played_row']}); "
                                    "sustained or looped samples may still sound."})
    unplayed = repetition["patterns_never_played"]
    if unplayed:
        warnings.append({"code": "pattern_never_played", "patterns": unplayed,
                         "message": f"Pattern(s) {unplayed} are stored but never reached by playback."})
    from .audio import MAX_RENDER_SECONDS
    if duration > MAX_RENDER_SECONDS:
        warnings.append({"code": "exceeds_render_limit", "seconds": duration,
                         "message": f"One cycle lasts {duration:.2f} s, above the {MAX_RENDER_SECONDS} s render limit."})

    return {
        "schema": SCHEMA, "title": module.title, "scope": SCOPE,
        "timing": timing,
        "channels": channels,
        "global": {
            "note_starts": total_notes,
            "rows_with_note_start": sum(any_note),
            "rows_without_note_start": {"total_rows": rows - sum(any_note), "longest": no_note},
            "pitch_classes": {name: histogram[number] for number, name in enumerate(PITCH_CLASS_NAMES)},
            "pitch_class_note": "Counts of note starts per pitch class of the written note name "
                                f"({'C-0' if xm else 'C-1'} = lowest).",
            "key_estimate": estimate_key(histogram),
        },
        "repetition": repetition,
        "samples": sample_usage,
        "warnings": warnings,
    }


def _text(value: object, label: str, maximum: int, required: bool = True) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise ValidationError(f"{label}: text expected.", "FEEDBACK_INVALID")
    stripped = value.strip()
    if not stripped:
        raise ValidationError(f"{label} must not be empty.", "FEEDBACK_INVALID")
    if len(stripped) > maximum:
        raise ValidationError(f"{label}: {maximum} characters maximum, got {len(stripped)}.", "FEEDBACK_INVALID")
    if any(ord(char) < 32 and char not in "\n\t" for char in stripped):
        raise ValidationError(f"{label}: control characters are not allowed.", "FEEDBACK_INVALID")
    return stripped


def add_feedback(module: Module, text: str, rating: int | None = None, source: str = "owner",
                 version_label: str | None = None, *, now: datetime | None = None) -> Module:
    """Return a deep copy of the module with one listening note appended to metadata['feedback']."""
    text = _text(text, "Feedback text", MAX_FEEDBACK_TEXT)
    source = _text(source, "Feedback source", 40)
    version = _text(version_label, "Version label", 80, required=False)
    if rating is not None and (type(rating) is not int or not 1 <= rating <= 5):
        raise ValidationError("Feedback rating must be an integer from 1 to 5, or omitted.", "FEEDBACK_INVALID")
    existing = module.metadata.get("feedback", [])
    if not isinstance(existing, list):
        raise ValidationError("metadata.feedback must be a list to append feedback.", "FEEDBACK_INVALID")
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0)
    result = copy.deepcopy(module)
    result.metadata["feedback"] = [*copy.deepcopy(existing), {
        "text": text, "rating": rating, "source": source, "version": version,
        "recorded_at": moment.isoformat().replace("+00:00", "Z"),
    }]
    return result
