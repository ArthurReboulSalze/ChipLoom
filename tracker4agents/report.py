"""Measurements of a composition and a record of listening feedback.

Everything in :func:`analyze` is a measurement of the symbolic score, taken along
the actual playback timeline (repeated orders, jumps and tempo changes count as
played). Nothing here is an aesthetic verdict. Two values are estimates and are
labelled as such: the musical key, and the PCM pitch estimate behind the heard
pitch of slots without a recipe. When a channel sounds (note starts, cuts, key
offs, one-shot lengths) is computed with the simplifications in SOUNDING_NOTE.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
import copy
import dataclasses
from datetime import datetime, timezone
import math
from pathlib import Path

from . import loudness, sample_source
from .model import (
    EFFECT_DIGITS, NOTES, PAL_CLOCK, PITCHES, REFERENCE_PERIOD, SAMPLE_RATE, XM_KEY_OFF, XM_NOTES, Module, Sample,
    ValidationError, playback_plan, xm_profile,
)

SCHEMA = "chiploom.report.v1"
LONG_SILENCE_SECONDS = 2.0
LEVEL_WARNING_DB = 6.0
# One note held under an arpeggio (0xy) for longer than this buzzes without pause; struck arpeggios
# (a new note every few rows, or a cut) stay well below it.
HELD_ARPEGGIO_SECONDS = 1.2
# Behaviour over time. A silence shorter than MIN_REST_SECONDS (a retrigger, a one-shot ending just before the
# next note) does not count as a rest; runs longer than NEVER_RESTS_SECONDS are flagged.
MIN_REST_SECONDS = 0.05
NEVER_RESTS_SECONDS = 16.0
SUSTAIN_MIN_CHANNELS = 4
SUSTAIN_CHANNEL_FRACTION = 0.6
# Heard fundamentals outside this range are flagged (a bass two octaves too low, a lead in the whistle range).
PITCH_LOW_HZ = 40.0
PITCH_HIGH_HZ = 3000.0
XM_C4_RATE = 8363.0  # FastTracker II plays an XM sample at note C-4 (number 49) at 8363 Hz
XM_REFERENCE_NUMBER = 49
PITCHED_RECIPES = ("wave", "draw", "pluck")
SOUNDING_NOTE = (
    "A channel sounds from a note start until it is silenced: a key off (XM ===, or Kxx at its tick; with or "
    "without a volume envelope the key off is taken as the end, release and fadeout are ignored), a note cut "
    "ECx at its tick, C00 or XM volume column 10 (a later Cxx, volume-column volume or sample number brings a "
    "voice that is still playing back), or a one-shot (unlooped) sample running out: its length in frames "
    "(minus a 9xx offset) at its playback rate at the written note (MOD: PAL clock / period with finetune; XM: "
    "8363 Hz x 2^((note - 49 + relative_note) / 12 + finetune / 1536), the linear table). A looped sample sounds "
    "until silenced or replaced. An XM volume envelope (no loop) that falls to 0 before any sustain point ends "
    "the note there, counted in ticks at the BPM of the note start. Volume slides, other envelope shapes, "
    "fadeout, note delays and pitch effects are not applied, and a one-shot counts until its last frame, quiet "
    "tail included. The XM Amiga frequency table is read as linear. A rest is a silence of at least "
    f"{MIN_REST_SECONDS} s after the channel's first note; shorter gaps join the runs on both sides. The song "
    "ends at the end of the first replay cycle."
)
PITCH_NOTE = (
    "Heard fundamental of each pitched note start (percussion slots left out): the slot's frequency at its "
    "reference note (MOD C-2, XM C-4, with its own finetune and relative_note) moved by the written note. "
    "samples.slots[].pitch says where that frequency comes from: 'recipe' (the frequency of a wave, draw or "
    "pluck recipe, heard at C-2 finetune 0, i.e. at 8287 Hz) or 'estimate' (the PCM pitch estimate of "
    "'samples inspect'). Slots without an estimate are skipped (estimated: false, with a reason). Portamento, "
    "arpeggio and vibrato are not applied, and an estimate can land on an octave of the fundamental."
)
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
    "sounding pitch can be offset from the written note. The report leaves out note starts that play a "
    "percussion sample (see percussion_excluded: a slot's role is recorded or inferred, so check that list), "
    "and a major key and its relative minor often correlate almost equally (see margin)."
)
RELATIVE_HIGH_MARGIN = 0.20
KEY_CONFIDENCE_RULE = (
    "Heuristic thresholds chosen for this tool, not perceptual data: margin >= 0.10 high, "
    ">= 0.03 medium, otherwise low. The margin is the correlation gap between the best and "
    "second-best of the 24 candidate keys. When the second-best is the relative major or minor "
    f"(the same scale), high needs margin >= {RELATIVE_HIGH_MARGIN:.2f}: a loop such as Am-F-C-G counts "
    "almost the same pitch classes in both keys."
)
SCOPE = (
    "Measurements of the symbolic score along its playback timeline (first replay cycle, including "
    "repeated orders, jumps and tempo changes). A note start is a cell with a note that is not a "
    "tone-portamento target (3xx/5xx). Sustained or looped samples can still sound where no note "
    "starts, so 'rows without a note start' is not audible silence. These numbers describe the "
    "score; they are not judgments of musical quality. Channels are numbered from 0, as in patch operations. "
    "channels[].sounding follows when each channel is heard (note starts, cuts, key offs, one-shot lengths) "
    "with stated simplifications (global.sounding_note); channels[].pitch gives heard fundamentals in Hz from "
    "recipe frequencies or PCM pitch estimates (global.pitch_note)."
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
    # The relative key of a major tonic t is the minor on t + 9 (and the other way round).
    relative = second[2] != best[2] and second[1] == (best[1] + (9 if best[2] == "major" else 3)) % 12
    if relative and confidence == "high" and margin < RELATIVE_HIGH_MARGIN:
        confidence = "medium"

    def entry(item: tuple[float, int, str]) -> dict:
        return {"key": f"{PITCH_CLASS_NAMES[item[1]]} {item[2]}", "tonic": PITCH_CLASS_NAMES[item[1]],
                "mode": item[2], "correlation": _round(-item[0])}

    return {"available": True, "is_estimate": True, **entry(best), "margin": _round(margin),
            "confidence": confidence, "confidence_rule": KEY_CONFIDENCE_RULE,
            "runner_up": entry(second), "runner_up_is_relative": relative,
            "top_candidates": [entry(item) for item in candidates[:3]],
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


def _playback_rate(sample: Sample, period: int, xm: bool) -> float:
    """Frames per second a sample plays at a written note: an XM note number (linear table) or a MOD period."""
    if xm:
        return XM_C4_RATE * 2 ** ((period - XM_REFERENCE_NUMBER + sample.relative_note) / 12 + sample.finetune / 1536)
    return PAL_CLOCK / period * 2 ** (sample.finetune / 96)


def _slot_pitch(sample: Sample, xm: bool) -> tuple[dict, float | None]:
    """(the slot's `pitch` block, cycles per PCM frame or None) for a slot that is not percussion."""
    from .sample_library import estimate_pitch
    from .synth import recipe_facts
    block = {"estimated": False, "method": None, "reference_note": "C-4" if xm else "C-2",
             "hz_at_reference": None, "reason": None}
    recipe = sample.recipe if isinstance(sample.recipe, dict) else None
    per_frame = None
    if recipe is not None and recipe.get("type") in PITCHED_RECIPES and recipe.get("shape") != "noise":
        if recipe["type"] == "pluck":
            per_frame = float(recipe.get("frequency", 261.625565)) / SAMPLE_RATE
        else:  # a tuned loop: whole cycles over the loop, within 2 cents of the recipe frequency
            heard = recipe_facts(sample).get("heard_hz_at_c2")
            per_frame = heard / SAMPLE_RATE if heard else None
        method = "recipe"
        block["reason"] = None if per_frame else "the recipe has no tuned loop"
    elif recipe is not None and recipe.get("shape") == "noise":
        method, block["reason"] = None, "unpitched noise recipe"
    else:
        estimate = estimate_pitch(dataclasses.replace(sample, finetune=0))
        if estimate["estimated_hz_at_c2"]:
            per_frame = estimate["estimated_hz_at_c2"] / estimate["playback_rate_hz"]
        method, block["reason"] = "estimate", estimate["reason"]
    if per_frame:
        reference = XM_REFERENCE_NUMBER if xm else REFERENCE_PERIOD
        block.update(estimated=True, method=method,
                     hz_at_reference=_round(per_frame * _playback_rate(sample, reference, xm), 3))
    return block, per_frame


def _envelope_ends(module: Module) -> dict[int, int]:
    """Ticks after which an XM instrument's volume envelope has fallen to 0 for good, by slot: only enabled
    envelopes without a loop whose zero tail starts before any sustain point (a note held at a sustain point
    waits for its key off)."""
    instruments = xm_profile(module).get("instruments")
    ends: dict[int, int] = {}
    for key, instrument in (instruments.items() if isinstance(instruments, dict) else ()):
        envelope = instrument.get("volume_envelope") if isinstance(instrument, dict) else None
        if not isinstance(envelope, dict) or not str(key).isdigit():
            continue
        kind, points = envelope.get("type", 0), envelope.get("points") or []
        if not kind & 1 or kind & 4 or not points:
            continue
        zero = len(points)
        while zero and points[zero - 1][1] == 0:
            zero -= 1
        if zero < len(points) and (not kind & 2 or zero <= envelope.get("sustain", 0)):
            ends[int(key)] = points[zero][0]
    return ends


def _sounding_runs(segments: list[list], gap: float) -> list[list]:
    """Join sounding segments [start, end, percussion one-shot] separated by less than `gap` seconds into runs
    [start, end, percussion only]."""
    runs: list[list] = []
    for start, end, percussive in segments:
        if runs and start - runs[-1][1] < gap - 1e-9:
            runs[-1][1] = max(runs[-1][1], end)
            runs[-1][2] = runs[-1][2] and percussive
        else:
            runs.append([start, end, percussive])
    return runs


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

    The same rule as `sample_match_level`, `synth add` and `synth palette` (see
    `synth_tools.automatic_reference`): an explicit `library` wins; else the default bank
    (`sample_library.DEFAULT_LIBRARY`, relative to the working directory, or `default`) when it exists, for
    library and synthesized projects alike; else the fixed defaults in `loudness.DEFAULT_REFERENCE_DB`.
    `module` only adds context to the reason.
    """
    from .synth_tools import automatic_reference
    reference = automatic_reference(library, default)
    if library is not None:
        reference["reason"] = "--library was given."
    elif reference["source"] == "defaults" and library_mode(module):
        reference["reason"] += " Pass --library to compare with another bank."
    return reference


def analyze(module: Module, reference: dict | None = None) -> dict:
    """Deterministic, JSON-serializable measurements of the played score.

    `reference` (see `synth_tools.resolve_reference`) gives the loudness each group is compared with;
    without it the fixed reference levels in `loudness.DEFAULT_REFERENCE_DB` are used. Build it with
    `loudness_reference` to have the report say which reference was chosen and why.
    """
    if reference is None:
        reference_info = {"source": "defaults", "path": None, "selection": "default",
                          "reason": "No reference was given; fixed reference levels."}
        bank = {}
    else:
        from .synth_tools import bank_entries
        bank = bank_entries(reference)  # library IDs without a recorded role use the bank's category
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

    # The role of every slot (recorded, recipe, bank category or loop heuristic), shared by the key
    # estimate and the sounding pitch (percussion is left out of both), the sounding runs and the loudness
    # comparison.
    sources = module.metadata.get("sample_sources", {}) if isinstance(module.metadata, dict) else {}
    sources = sources if isinstance(sources, dict) else {}
    roles: dict[int, tuple[str, str]] = {}
    for slot, sample in enumerate(module.samples, 1):
        if sample.pcm:
            roles[slot] = loudness.slot_role(sample, sources.get(str(slot)), bank)
    percussion = {slot for slot, (role, _) in roles.items() if loudness.is_percussion(role)}
    envelope_ticks = _envelope_ends(module) if xm else {}
    # Slot pitches are measured on demand: only slots that a pitched note start plays (an estimate costs time).
    slot_pitches: dict[int, dict] = {}
    cycles_per_frame: dict[int, float | None] = {}

    def slot_cycles(slot: int) -> float | None:
        if slot not in cycles_per_frame:
            slot_pitches[slot], cycles_per_frame[slot] = _slot_pitch(module.samples[slot - 1], xm)
        return cycles_per_frame[slot]

    # One pass over the played rows: cells, note starts and the sample each note uses.
    signatures: list[list[tuple[int, ...]]] = [[] for _ in range(count)]
    note_flags = [[False] * rows for _ in range(count)]
    channel_notes: list[list[int]] = [[] for _ in range(count)]
    channel_samples: list[dict[int, int]] = [{} for _ in range(count)]
    channel_effects: list[dict[str, int]] = [{} for _ in range(count)]
    channel_extended: list[dict[str, int]] = [{} for _ in range(count)]
    portamento_targets = [0] * count
    current_sample = [0] * count
    note_slots: list[tuple[int, int]] = []  # (slot, note number) of each note start, for the key histogram
    sample_changes: dict[int, int] = {}  # cells that select a slot without starting a note (sample switching)
    notes_without_sample = [0] * count
    sample_channels: dict[int, set[int]] = {}
    # Arpeggio runs: played rows where one note keeps an 0xy effect without a new note or a cut.
    arpeggio_run: list[list | None] = [None] * count   # [start played row, rows, seconds]
    held_arpeggios: list[list[list]] = [[] for _ in range(count)]
    # Sounding state: when the playing voice runs out (inf when looped, None without a voice), whether the
    # channel volume is above 0, the open segment's start and whether it plays a percussion one-shot.
    voice_end: list[float | None] = [None] * count
    audible = [False] * count
    segment_start: list[float | None] = [None] * count
    segment_percussive = [False] * count
    segments: list[list[list]] = [[] for _ in range(count)]
    lowest_pitch: list[dict | None] = [None] * count
    highest_pitch: list[dict | None] = [None] * count
    pitch_counts = [[0, 0] for _ in range(count)]  # pitched note starts: measured, slot without an estimate

    def close_segment(channel: int, moment: float) -> None:
        start, end = segment_start[channel], voice_end[channel]
        if start is not None and end is not None and min(moment, end) > start + 1e-9:
            segments[channel].append([start, min(moment, end), segment_percussive[channel]])
        segment_start[channel] = None

    def set_volume(channel: int, moment: float, positive: bool) -> None:
        if not positive:
            close_segment(channel, moment)
        elif not audible[channel] and voice_end[channel] is not None and voice_end[channel] > moment:
            segment_start[channel] = moment
        audible[channel] = positive

    def close_arpeggio(channel: int) -> None:
        run = arpeggio_run[channel]
        if run is not None and run[2] > HELD_ARPEGGIO_SECONDS:
            held_arpeggios[channel].append(run)
        arpeggio_run[channel] = None

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
            starts_note = bool(value.period) and not (xm and value.period == XM_KEY_OFF)
            if starts_note and (value.command in (3, 5) or (xm and value.volume >= 0xF0)):
                portamento_targets[channel] += 1
                starts_note = False
            arpeggio = value.command == 0 and value.param != 0
            silenced = bool(value.period) or (xm and value.volume == 0x10) or (value.command == 0xC and not value.param)
            if starts_note or silenced or not arpeggio:
                close_arpeggio(channel)
            if arpeggio and not (silenced and not starts_note):
                run = arpeggio_run[channel]
                if run is None:
                    arpeggio_run[channel] = [index, 1, row_seconds[index]]
                else:
                    run[1] += 1
                    run[2] += row_seconds[index]
            # Sounding: key off, note start, volume set at tick 0, then a cut or key off at a later tick.
            moment, tick, speed = item["seconds"], 2.5 / item["bpm"], item["speed"]
            if xm and value.period == XM_KEY_OFF:
                close_segment(channel, moment)
                voice_end[channel] = None
            if starts_note:
                close_segment(channel, moment)
                voice_end[channel] = None
                slot = current_sample[channel]
                sample = module.samples[slot - 1] if 0 < slot <= len(module.samples) else None
                if sample is not None and sample.pcm:
                    rate = _playback_rate(sample, value.period, xm)
                    offset = value.param * 256 if value.command == 9 else 0
                    if sample.loop_length:
                        voice_end[channel] = math.inf
                    elif len(sample.pcm) > offset:
                        voice_end[channel] = moment + (len(sample.pcm) - offset) / rate
                    if slot in envelope_ticks and voice_end[channel] is not None:
                        voice_end[channel] = min(voice_end[channel], moment + envelope_ticks[slot] * tick)
                    segment_percussive[channel] = slot in percussion and not sample.loop_length
                    if slot not in percussion:
                        per_frame = slot_cycles(slot)
                        pitch_counts[channel][per_frame is None] += 1
                        if per_frame:
                            heard = {"hz": _round(per_frame * rate, 3), "note": value.note, "slot": slot}
                            if lowest_pitch[channel] is None or heard["hz"] < lowest_pitch[channel]["hz"]:
                                lowest_pitch[channel] = heard
                            if highest_pitch[channel] is None or heard["hz"] > highest_pitch[channel]["hz"]:
                                highest_pitch[channel] = heard
                if value.sample:
                    audible[channel] = False  # reopened below by the sample's default volume
                elif audible[channel] and voice_end[channel] is not None:
                    segment_start[channel] = moment  # a note without a sample number keeps the channel volume
            if value.sample and 0 < value.sample <= len(module.samples):
                # A sample number resets the volume to the sample's default, with or without a note.
                set_volume(channel, moment, module.samples[value.sample - 1].volume > 0)
            if xm and 0x10 <= value.volume <= 0x50:
                set_volume(channel, moment, value.volume > 0x10)
            if value.command == 0xC:
                set_volume(channel, moment, value.param > 0)
            if value.command == 14 and value.param >> 4 == 0xC and (value.param & 15) < speed:
                set_volume(channel, moment + (value.param & 15) * tick, False)
            if xm and value.command == 20 and value.param < speed:
                close_segment(channel, moment + value.param * tick)
                voice_end[channel] = None
            if not starts_note:
                if value.sample:
                    sample_changes[value.sample] = sample_changes.get(value.sample, 0) + 1
                    sample_channels.setdefault(value.sample, set()).add(channel)
                continue
            note_flags[channel][index] = True
            number = value.period - 1 if xm else NOTES.index(value.note)
            channel_notes[channel].append(number)
            slot = current_sample[channel]
            note_slots.append((slot, number))
            if slot:
                channel_samples[channel][slot] = channel_samples[channel].get(slot, 0) + 1
                sample_channels.setdefault(slot, set()).add(channel)
            else:
                notes_without_sample[channel] += 1

    for channel in range(count):
        close_arpeggio(channel)
        close_segment(channel, duration)
    row_starts = [item["seconds"] for item in timeline]

    def run_entry(run: list | None) -> dict | None:
        if run is None:
            return None
        first = bisect_right(row_starts, run[0] + 1e-9) - 1
        last = bisect_left(row_starts, run[1] - 1e-9) - 1
        return {"start_played_row": first, "start_seconds": _round(run[0]), "rows": last - first + 1,
                "seconds": _round(run[1] - run[0]), "percussion_only": run[2]}

    channel_runs = [_sounding_runs(segments[channel], MIN_REST_SECONDS) for channel in range(count)]
    channels = []
    for channel in range(count):
        notes = channel_notes[channel]
        gap = _longest_run(note_flags[channel], row_seconds)
        held = max(held_arpeggios[channel], key=lambda run: run[2], default=None)
        runs = channel_runs[channel]
        longest = max(runs, key=lambda run: run[1] - run[0], default=None)
        counted = max((run for run in runs if not run[2]), key=lambda run: run[1] - run[0], default=None)
        sounding_seconds = sum(end - start for start, end, _ in segments[channel])
        sounding = {
            "fraction": _round(min(1.0, sounding_seconds / duration)) if duration else 0.0,
            "seconds": _round(sounding_seconds),
            "longest_run_seconds": _round(longest[1] - longest[0]) if longest else 0.0,
            "longest_run": run_entry(longest),
            "longest_non_percussion_run": run_entry(counted),
            "rests": max(0, len(runs) - 1) + (1 if runs and duration - runs[-1][1] >= MIN_REST_SECONDS else 0),
        }
        measured, unmeasured = pitch_counts[channel]
        pitch = {"lowest": lowest_pitch[channel], "highest": highest_pitch[channel],
                 "note_starts_measured": measured, "note_starts_without_estimate": unmeasured}
        entry = {
            "channel": channel, "note_ons": len(notes),
            "notes_per_second": _round(len(notes) / duration) if duration else 0.0,
            "density": _round(len(notes) / rows) if rows else 0.0,
            "lowest_note": note_names[min(notes)] if notes else None,
            "highest_note": note_names[max(notes)] if notes else None,
            "range_semitones": max(notes) - min(notes) if notes else None,
            "samples_used": sorted(set(channel_samples[channel])
                                   | {slot for slot, used in sample_channels.items() if channel in used}),
            "effects": dict(sorted(channel_effects[channel].items())),
            "extended_effects": dict(sorted(channel_extended[channel].items())),
            "portamento_targets": portamento_targets[channel],
            "notes_without_sample": notes_without_sample[channel],
            "longest_gap_without_note": gap,
            "held_arpeggios": {"count": len(held_arpeggios[channel]),
                               "longest": {"start_played_row": held[0], "rows": held[1],
                                           "seconds": _round(held[2])} if held else None},
            "sounding": sounding,
            "pitch": pitch,
        }
        channels.append(entry)

    # The longest stretch during which at least `threshold` channels sound together (runs, short gaps joined).
    threshold = max(SUSTAIN_MIN_CHANNELS, math.ceil(SUSTAIN_CHANNEL_FRACTION * count))
    changes: dict[float, int] = {}
    for runs in channel_runs:
        for start, end, _ in runs:
            changes[start] = changes.get(start, 0) + 1
            changes[end] = changes.get(end, 0) - 1
    crowded: list | None = None
    level, since = 0, None
    for moment in sorted(changes):  # every change at one moment at once: a hand-over is not a break
        level += changes[moment]
        if level >= threshold and since is None:
            since = moment
        elif level < threshold and since is not None:
            if crowded is None or moment - since > crowded[1] - crowded[0] + 1e-9:
                crowded = [since, moment, False]
            since = None
    crowded_entry = run_entry(crowded)
    sustain = {"threshold_channels": threshold, "channels": count,
               "longest_seconds": crowded_entry["seconds"] if crowded_entry else 0.0,
               "start_played_row": crowded_entry["start_played_row"] if crowded_entry else None,
               "start_seconds": crowded_entry["start_seconds"] if crowded_entry else None,
               "rows": crowded_entry["rows"] if crowded_entry else 0,
               "rule": f"At least max({SUSTAIN_MIN_CHANNELS}, ceil({SUSTAIN_CHANNEL_FRACTION} x channels)) channels "
                       "sounding at the same time (see sounding_note)."}

    any_note = [any(note_flags[channel][index] for channel in range(count)) for index in range(rows)]
    no_note = _longest_run(any_note, row_seconds)
    histogram = [0] * 12
    for notes in channel_notes:
        for number in notes:
            histogram[number % 12] += 1
    total_notes = sum(histogram)

    key_histogram = [0] * 12
    excluded_counts: dict[int, int] = {}
    for slot, number in note_slots:
        if slot in percussion:
            excluded_counts[slot] = excluded_counts.get(slot, 0) + 1
        else:
            key_histogram[number % 12] += 1
    key_estimate = estimate_key(key_histogram)
    key_estimate["percussion_excluded"] = {
        "note_starts": sum(excluded_counts.values()),
        "slots": [{"slot": slot, "name": module.samples[slot - 1].name, "role": roles[slot][0],
                   "role_source": roles[slot][1], "note_starts": excluded_counts[slot]}
                  for slot in sorted(excluded_counts)],
        "rule": "Note starts that play a slot whose role is percussion (kick, snare, hat or the percussion "
                "group) are not counted. Role order: metadata.sample_sources[slot].role, the recipe, the bank "
                "category of the slot's library_id (when a bank is the loudness reference), the loop heuristic "
                "(a one-shot PCM sample counts as percussion).",
    }
    key_estimate["pitch_classes_counted"] = {name: key_histogram[number]
                                             for number, name in enumerate(PITCH_CLASS_NAMES)}

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
    samples = []
    never_played = []
    empty_slots = []
    for slot, sample in enumerate(module.samples, 1):
        if not sample.pcm:
            empty_slots.append(slot)
            continue
        count_played = sum(channel_samples[channel].get(slot, 0) for channel in range(count))
        changes = sample_changes.get(slot, 0)
        recorded = sources.get(str(slot))
        recorded = recorded if isinstance(recorded, dict) else {}
        key, role_source = roles[slot]
        group = loudness.ROLES.get(key, key)
        facts = loudness.measure(sample)
        level = facts["loudness_db"]
        wanted = loudness.target_db(key, reference)
        reachable = loudness.reachable_db(sample)
        samples.append({"slot": slot, "name": sample.name, "bytes": len(sample.pcm), "looped": bool(sample.loop_length),
                        "volume": sample.volume, "note_ons": count_played, "sample_changes": changes,
                        "channels": sorted(sample_channels.get(slot, ())),
                        "source": "recipe" if sample.recipe is not None else "embedded_pcm",
                        "library_id": recorded.get("library_id") if isinstance(recorded.get("library_id"), str) else None,
                        "role": key, "role_source": role_source,
                        "loudness_db": level, "peak_db": facts["peak_db"], "group": group,
                        "reference_db": wanted, "deviation_db": round(level - wanted, 2),
                        "reachable_db": reachable, "limited_by_peak": wanted > reachable + 0.05,
                        "pitch": slot_pitches.get(slot) or {
                            "estimated": False, "method": None, "reference_note": "C-4" if xm else "C-2",
                            "hz_at_reference": None,
                            "reason": "percussion slot: not measured" if slot in percussion
                                      else "no note start plays this slot: not measured"}})
        if not count_played and not changes:
            never_played.append(slot)
    found = sample_source.counts(module)
    sample_usage = {"slots_with_audio": len(samples), "empty_slots": empty_slots,
                    "never_played_slots": never_played,
                    "sources": {"recipe": found["recipe"], "embedded_pcm": found["embedded_pcm"],
                                "declared": module.metadata.get("sample_source")},
                    "loudness_note": "loudness_db: RMS of the audible PCM x volume / 64, dB re full scale, at the "
                                     "sample's default volume (Cxx and arpeggios are not applied). reference_db: "
                                     "the level of its group in the loudness_reference (median; kick p75, hat p25). "
                                     "reachable_db: the level at volume 64 with the peak at full scale; "
                                     "limited_by_peak: the reference is above it.",
                    "usage_note": "note_ons: note starts that play the slot. sample_changes: cells that select the "
                                  "slot without starting a note (sample switching mid-note, a key-off or a "
                                  "tone-portamento target). A slot is never played when neither happens.",
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
        held = entry["held_arpeggios"]
        if held["count"]:
            longest = held["longest"]
            warnings.append({"code": "held_arpeggio", "channel": entry["channel"], "count": held["count"],
                             "longest_seconds": longest["seconds"],
                             "message": f"Channel {entry['channel']} holds one note under an arpeggio (0xy) for more "
                                        f"than {HELD_ARPEGGIO_SECONDS} s {held['count']} time(s), the longest "
                                        f"{longest['seconds']:.2f} s ({longest['rows']} rows from played-row index "
                                        f"{longest['start_played_row']}). Struck arpeggios (a new note every few "
                                        "rows, or a cut between hits) do not trigger this."})
        run = entry["sounding"]["longest_non_percussion_run"]
        if run and run["seconds"] > NEVER_RESTS_SECONDS:
            warnings.append({"code": "channel_never_rests", "channel": entry["channel"], "seconds": run["seconds"],
                             "start_played_row": run["start_played_row"],
                             "message": f"Channel {entry['channel']} sounds for {run['seconds']:.2f} s without a rest "
                                        f"of {MIN_REST_SECONDS} s or more ({run['rows']} rows from played-row index "
                                        f"{run['start_played_row']}), above {NEVER_RESTS_SECONDS:.0f} s. A rest needs "
                                        "a key off, a note cut (ECx), C00 or XM volume 10, or a one-shot sample "
                                        "that runs out; runs of percussion one-shots only are not counted."})
        for code, end, compare, limit in (("pitch_too_low", "lowest", float.__lt__, PITCH_LOW_HZ),
                                          ("pitch_too_high", "highest", float.__gt__, PITCH_HIGH_HZ)):
            heard = entry["pitch"][end]
            if heard and compare(float(heard["hz"]), limit):
                warnings.append({"code": code, "channel": entry["channel"], "note": heard["note"],
                                 "slot": heard["slot"], "hz": heard["hz"],
                                 "message": f"Channel {entry['channel']} plays {heard['note']} on slot {heard['slot']} "
                                            f"with a heard fundamental of {heard['hz']:.1f} Hz, "
                                            f"{'below' if end == 'lowest' else 'above'} {limit:.0f} Hz (the slot's "
                                            "frequency at its reference note, moved by the written note; see "
                                            "global.pitch_note)."})
    if sustain["longest_seconds"] > NEVER_RESTS_SECONDS:
        warnings.append({"code": "crowded_sustain", "seconds": sustain["longest_seconds"],
                         "threshold_channels": threshold, "start_played_row": sustain["start_played_row"],
                         "message": f"At least {threshold} of {count} channels sound together for "
                                    f"{sustain['longest_seconds']:.2f} s ({sustain['rows']} rows from played-row index "
                                    f"{sustain['start_played_row']}), above {NEVER_RESTS_SECONDS:.0f} s."})
    for slot in never_played:
        warnings.append({"code": "sample_never_played", "slot": slot,
                         "message": f"Sample slot {slot} ({module.samples[slot - 1].name!r}) holds audio but no cell of "
                                    "the played timeline selects it."})
    for entry in samples:
        if abs(entry["deviation_db"]) > LEVEL_WARNING_DB and (entry["note_ons"] or entry["sample_changes"]):
            below = entry["deviation_db"] < 0
            message = (f"Sample slot {entry['slot']} ({entry['name']!r}) is {abs(entry['deviation_db']):.1f} dB "
                       f"{'below' if below else 'above'} the {entry['group']} "
                       f"reference ({entry['reference_db']} dB); more than {LEVEL_WARNING_DB:.0f} dB apart.")
            item = {"code": "sample_level_off_reference", "slot": entry["slot"], "deviation_db": entry["deviation_db"]}
            if below and entry["limited_by_peak"]:
                message += (f" The reference is out of reach (limited by peak): at volume 64 with its peak at full "
                            f"scale it would measure {entry['reachable_db']} dB.")
                item["limited_by_peak"] = True
            warnings.append({**item, "message": message})
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
            "pitch_class_note": "Counts of every note start (percussion included) per pitch class of the written "
                                f"note name ({'C-0' if xm else 'C-1'} = lowest). The key estimate counts only the "
                                "note starts in key_estimate.pitch_classes_counted.",
            "key_estimate": key_estimate,
            "sustain": sustain,
            "sounding_note": SOUNDING_NOTE,
            "pitch_note": PITCH_NOTE,
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
