"""Conversion between the MOD and XM profiles.

MOD to XM keeps the notes, instruments, effects, order list and PCM of the MOD exactly (a 4-channel
MOD included) and reports what an XM cannot hold or plays differently:

* Notes move up two octaves in the labels (ProTracker C-2, period 428, is XM C-4): a MOD C-1..B-3 is
  an XM C-3..B-5. The XM uses the Amiga frequency table, so portamento, vibrato and arpeggio keep
  their Amiga meaning, and every sample gets a finetune of -20/128 semitone to cancel the 15.8 cent
  difference between the PAL Paula clock (8287 Hz at C-2) and FastTracker's 8363 Hz at C-4.
* An XM has no Amiga LED filter (E0x) and no per-channel panning: E0x cells lose that effect and the
  samples are centred (the fixed left-right-right-left Paula placement is not carried).
* E5x is remapped to the XM range; the playback plan of both modules is compared and a difference is
  reported.

XM to MOD succeeds only when the XM is exactly what a MOD can say (this is the way back for a module
that came from `mod_to_xm`); otherwise it is refused with every reason listed.
"""

from __future__ import annotations

import copy

from .model import (
    NOTES, PERIOD_TO_NOTE, Cell, Module, NOTE_TO_PERIOD, Pattern, Sample, ValidationError, XM_KEY_OFF, playback_plan,
    validate, xm_profile,
)

#: Cents between the PAL Amiga clock at period 428 (8287.1 Hz) and FastTracker II's C-4 (8363 Hz).
PAL_TUNING = -20  # in 1/128 semitone
NOTE_OFFSET = 36  # a ProTracker note index 0 (C-1) is XM note 37 (C-3)
FINETUNE_STEP = 16  # one MOD finetune step (1/8 semitone) in XM units (1/128 semitone)


class ConversionRefused(ValidationError):
    """XM to MOD cannot be done without loss; `reasons` lists every cause."""

    def __init__(self, reasons: list[dict]):
        listing = "; ".join(f"{item['code']}: {item['message']}" for item in reasons[:12])
        more = f" (and {len(reasons) - 12} more)" if len(reasons) > 12 else ""
        super().__init__(f"This XM does not fit the MOD profile ({len(reasons)} reason(s)): {listing}{more}.",
                         "CONVERT_REFUSED")
        self.reasons = reasons


def _note(notes: list, code: str, kind: str, message: str, **extra) -> None:
    notes.append({"code": code, "kind": kind, "message": message, **extra})


def _same_timeline(before: Module, after: Module) -> int | None:
    """Index of the first row where the two playback plans differ, or None if they agree."""
    left, right = playback_plan(before)["timeline"], playback_plan(after)["timeline"]
    for index, (a, b) in enumerate(zip(left, right)):
        if (a["order"], a["row"], a["speed"], a["bpm"], a.get("delay", 0)) != (b["order"], b["row"], b["speed"], b["bpm"], b.get("delay", 0)) \
                or abs(a["seconds"] - b["seconds"]) > 1e-9:
            return index
    return None if len(left) == len(right) else min(len(left), len(right))


# --- MOD to XM -----------------------------------------------------------------------------------------

def mod_to_xm(module: Module) -> tuple[Module, dict]:
    from .xm import TRACKER_NAME
    validate(module)
    notes: list[dict] = []
    samples = []
    for sample in module.samples:
        tune = sample.finetune * FINETUNE_STEP + PAL_TUNING
        relative = 0
        if tune < -128:
            relative, tune = -1, tune + 128
        # Instruments without audio carry no volume in an XM; keep the model's own default.
        samples.append(Sample(sample.name, sample.pcm, sample.volume if sample.pcm else 64, tune if sample.pcm else 0,
                              sample.loop_start, sample.loop_length, None, 8, "forward", 128, relative if sample.pcm else 0))
    filter_cells = remapped = 0
    patterns = []
    for pattern in module.patterns:
        converted = Pattern(pattern.name, {}, 64)
        for (row, channel), value in pattern.cells.items():
            number = NOTES.index(PERIOD_TO_NOTE[value.period]) + NOTE_OFFSET + 1 if value.period else 0
            command, param = value.command, value.param
            if command == 14 and param >> 4 == 0:  # E0x, the Amiga LED filter, does not exist in an XM
                command, param = 0, 0
                filter_cells += 1
            elif command == 14 and param >> 4 == 5:  # E5x: MOD finetune -8..7 (0 is centre), XM 0..15 (8 is centre)
                signed = (param & 15) - 16 if param & 8 else param & 15
                param = 0x50 | (signed + 8)
                remapped += 1
            converted.put(row, channel, Cell(number, value.sample, command, param))
        patterns.append(converted)
    block = {"tracker_name": TRACKER_NAME, "frequency_table": "amiga", "restart_position": 0,
             "default_speed": 6, "default_bpm": 125}
    _note(notes, "NOTES_TRANSPOSED", "preserved",
          "MOD notes C-1..B-3 became XM C-3..B-5 (ProTracker C-2 is XM C-4); the sound is the same.")
    _note(notes, "PITCH_TUNING", "preserved",
          f"Every sample received a finetune offset of {PAL_TUNING}/128 semitone so that XM C-4 (8363 Hz) plays "
          "like the PAL Paula period 428 (8287 Hz).")
    _note(notes, "FREQUENCY_TABLE_AMIGA", "preserved",
          "The XM uses the Amiga frequency table, so slides, vibrato and arpeggio keep their MOD meaning.")
    _note(notes, "PANNING_NOT_CARRIED", "preserved",
          "A MOD file stores no panning: players place its channels left-right-right-left. An XM has no fixed "
          "per-channel panning, so every sample is centred; no data was lost, the stereo image differs.")
    if filter_cells:
        _note(notes, "FILTER_EFFECT_DROPPED", "converted",
              f"{filter_cells} E0x (Amiga LED filter) effect(s) were removed; an XM has no such filter.",
              details={"cells": filter_cells})
    if remapped:
        _note(notes, "E5X_REMAPPED", "converted",
              f"{remapped} E5x finetune effect(s) were remapped to the XM scale (8 is the centre); the 0.8 cent "
              "pitch tuning above is not applied to them.", details={"cells": remapped})
    metadata = {key: copy.deepcopy(value) for key, value in module.metadata.items() if key != "mod"}
    result = Module(module.title, samples, patterns, list(module.orders), metadata, module.channels, "xm")
    result.metadata["xm"] = block
    difference = _same_timeline_safe(module, result)
    if difference is not None:
        _note(notes, "TIMING_DIFFERS", "converted",
              f"The playback timelines differ from played row {difference} (a MOD-only flow quirk such as a break "
              "on a pattern-delay row).", details={"first_difference": difference})
    result.metadata["xm"]["import_notes"] = [dict(item) for item in notes]
    validate(result)
    return result, _report(module, result, notes)


def _same_timeline_safe(before: Module, after: Module) -> int | None:
    try:
        return _same_timeline(before, after)
    except ValidationError:
        return 0


# --- XM to MOD -----------------------------------------------------------------------------------------

def xm_to_mod(module: Module) -> tuple[Module, dict]:
    validate(module)
    reasons: list[dict] = []

    def refuse(code: str, message: str, **where) -> None:
        reasons.append({"code": code, "message": message, **where})

    info = xm_profile(module)
    if len(module.samples) > 31:
        refuse("TOO_MANY_INSTRUMENTS", f"{len(module.samples)} instruments; a MOD has 31 sample slots.")
    if len(module.patterns) > 100:
        refuse("TOO_MANY_PATTERNS", f"{len(module.patterns)} patterns; the MOD profile holds 100.")
    if len(module.orders) > 128:
        refuse("TOO_MANY_ORDERS", f"{len(module.orders)} orders; a MOD holds 128.")
    if info.get("frequency_table", "linear") != "amiga":
        refuse("FREQUENCY_TABLE", "The linear frequency table slides pitch differently from a MOD; only the Amiga "
               "table converts.")
    if info.get("default_speed", 6) != 6 or info.get("default_bpm", 125) != 125:
        refuse("DEFAULT_TIMING", "The song does not start at speed 6 / 125 BPM, which is all a MOD can assume.")
    if info.get("restart_position", 0) != 0:
        refuse("RESTART_POSITION", "A restart position other than 0 has no MOD equivalent.")
    tunings = []
    for slot, sample in enumerate(module.samples, 1):
        extra = info.get("instruments", {}).get(str(slot), {})
        if any(extra.get(key) for key in ("volume_envelope", "panning_envelope", "vibrato", "fadeout")):
            refuse("INSTRUMENT_EXTRAS", "Envelopes, auto-vibrato and fadeout cannot be written in a MOD.", instrument=slot)
        if not sample.pcm:
            tunings.append(0)
            continue
        if sample.bits != 8:
            refuse("SAMPLE_16_BIT", "A MOD sample is 8-bit.", instrument=slot)
        if sample.loop_mode != "forward":
            refuse("PINGPONG_LOOP", "A MOD loop only runs forward.", instrument=slot)
        if sample.panning != 128:
            refuse("SAMPLE_PANNING", "A MOD sample has no panning.", instrument=slot)
        total = sample.finetune + 128 * sample.relative_note - PAL_TUNING
        if total % FINETUNE_STEP or not -8 <= total // FINETUNE_STEP <= 7:
            refuse("SAMPLE_TUNING", "Finetune and relative note do not map to a MOD finetune (-8..7) exactly.",
                   instrument=slot)
        tunings.append(total // FINETUNE_STEP if total % FINETUNE_STEP == 0 else 0)
        if len(sample.pcm) % 2 or len(sample.pcm) < 4 or len(sample.pcm) > 65534:
            refuse("SAMPLE_LENGTH", "A MOD sample has an even length of 4 to 65534 bytes.", instrument=slot)
        if sample.loop_length and (sample.loop_start % 2 or sample.loop_length % 2 or sample.loop_length < 4):
            refuse("SAMPLE_LOOP", "MOD loop points are even and the loop is at least 4 bytes.", instrument=slot)
        if not sample.loop_length and any(sample.pcm[:2]):
            refuse("SAMPLE_HEAD", "An unlooped MOD sample starts with two zero bytes.", instrument=slot)
    for index, pattern in enumerate(module.patterns):
        if pattern.rows != 64:
            refuse("PATTERN_LENGTH", f"Pattern {index} has {pattern.rows} rows; a MOD pattern has 64.", pattern=index)
        for (row, channel), value in sorted(pattern.cells.items()):
            where = {"pattern": index, "row": row, "channel": channel}
            if value.period == XM_KEY_OFF:
                refuse("KEY_OFF", "A key-off note has no MOD equivalent.", **where)
            elif value.period and not 37 <= value.period <= 72:
                refuse("NOTE_RANGE", f"Note {value.note} is outside the MOD range C-3..B-5 of an XM.", **where)
            if value.volume:
                refuse("VOLUME_COLUMN", "A MOD has no volume column.", **where)
            if value.command > 15 or value.command == 14 and value.param >> 4 in (0, 3, 7, 8, 15) or value.command in (8,):
                refuse("EFFECT", f"Effect {value.effect} is not in the MOD profile.", **where)
            if len(reasons) > 200:
                break
        if len(reasons) > 200:
            break
    if reasons:
        raise ConversionRefused(reasons)
    samples = []
    for sample, tune in zip(module.samples, tunings):
        samples.append(Sample(sample.name, sample.pcm, sample.volume if sample.pcm else 0, tune, sample.loop_start,
                              sample.loop_length))
    patterns = []
    for pattern in module.patterns:
        converted = Pattern(pattern.name)
        for (row, channel), value in pattern.cells.items():
            period = NOTE_TO_PERIOD[NOTES[value.period - NOTE_OFFSET - 1]] if value.period else 0
            command, param = value.command, value.param
            if command == 14 and param >> 4 == 5:
                signed = (param & 15) - 8
                param = 0x50 | (signed & 15)
            converted.put(row, channel, Cell(period, value.sample, command, param))
        patterns.append(converted)
    metadata = {key: copy.deepcopy(value) for key, value in module.metadata.items() if key != "xm"}
    result = Module(module.title, samples, patterns, list(module.orders), metadata, module.channels, "mod")
    validate(result)
    difference = _same_timeline_safe(module, result)
    if difference is not None:
        raise ConversionRefused([{"code": "TIMING", "message": f"The MOD would play differently from played row "
                                                               f"{difference} (flow quirks differ between the formats)."}])
    notes: list[dict] = []
    _note(notes, "NOTES_TRANSPOSED", "preserved", "XM C-3..B-5 became MOD C-1..B-3.")
    return result, _report(module, result, notes)


def _report(before: Module, after: Module, notes: list[dict]) -> dict:
    lost = [item["code"] for item in notes if item["kind"] == "converted"]
    return {"from": before.format, "to": after.format, "channels": after.channels,
            "lossless": not lost, "converted": lost, "notes": notes}


def convert(module: Module, target: str) -> tuple[Module, dict]:
    """Convert `module` to `target` ("mod" or "xm"); returns (new module, report). Same format: a copy."""
    if target not in ("mod", "xm"):
        raise ValidationError(f"Unknown target format {target!r}; expected mod or xm.", "FORMAT")
    if target == module.format:
        return copy.deepcopy(module), {"from": module.format, "to": target, "channels": module.channels,
                                       "lossless": True, "converted": [], "notes": []}
    return mod_to_xm(module) if target == "xm" else xm_to_mod(module)
