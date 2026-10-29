"""Sound-workshop helpers: sample editing on copies, recipe auditions, drawn waves and waveform summaries.

Standard library only: no Qt, no FFmpeg. The pure functions here take and return `Sample` objects (or plain
PCM), so the window, the CLI, the MCP adapter and the `sample_*` patch operations share one implementation.
Nothing here edits a module in place except `record_edit` and `guard_*`, which patch operations call.

PCM is signed 8-bit (-128..127). A sample without a loop must start with two zero bytes (the replayer's
silent "no loop" word); the editing functions never hide that rule, they refuse or, with `adapt`, prepend
two zero bytes so the original PCM bytes stay exactly as they were.
"""

from __future__ import annotations

import base64
from array import array
import copy
import dataclasses
import hashlib
import io
import math
import sys
import wave
from typing import Sequence

from . import loudness, sample_source, synth
from .model import NOTE_TO_PERIOD, NOTES, PAL_CLOCK, Sample, ValidationError, ascii_field, require_int

MAX_PCM_BYTES = 65_534
MAX_RECORDED_EDITS = 16  # per slot in metadata.sample_sources[slot]["edits"]; "edit_count" keeps the total
PREVIEW_RATE = 44_100


def _bad(message: str, code: str = "PATCH_FIELD") -> ValidationError:
    return ValidationError(message, code)


def number(value: object, label: str, minimum: float, maximum: float) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or not minimum <= value <= maximum:
        raise _bad(f"{label}: finite number in [{minimum}, {maximum}] expected.")
    return float(value)


def flag(op: dict, key: str) -> bool:
    value = op.get(key, False)
    if type(value) is not bool:
        raise _bad(f"{key}: true or false expected.")
    return value


def _round(value: float) -> int:
    """Round half away from zero, so a gain treats positive and negative bytes alike."""
    return int(math.copysign(math.floor(abs(value) + 0.5), value))


def _clamp(value: int) -> int:
    return max(-128, min(127, value))


def _with(sample: Sample, **changes) -> Sample:
    return dataclasses.replace(sample, **changes)


def pcm_bytes(pcm: Sequence[int]) -> bytes:
    return bytes(value & 255 for value in pcm)


def pcm_sha256(pcm: Sequence[int]) -> str:
    return hashlib.sha256(pcm_bytes(pcm)).hexdigest()


# --- editing ----------------------------------------------------------------------------------

def leading_zero(pcm: tuple[int, ...], adapt: bool, adaptations: list[str], action: str) -> tuple[int, ...]:
    """A sample without a loop must start with two zero bytes. Prepend them when `adapt`, else refuse."""
    if not any(pcm[:2]):
        return pcm
    if not adapt:
        raise _bad(f"{action} leaves a sample without a loop whose first two bytes are not zero. A one-shot must "
                   "start with two zero bytes (the replayer's silent no-loop word). Pass \"adapt\": true to "
                   "prepend two zero bytes; the PCM itself stays exact.", "SAMPLE_LOOP")
    if len(pcm) + 2 > MAX_PCM_BYTES:
        raise _bad(f"Prepending two zero bytes would pass {MAX_PCM_BYTES} bytes.", "SAMPLE_LENGTH")
    adaptations.append("prepend-two-zero-bytes")
    return (0, 0) + pcm


def with_loop(sample: Sample, loop_start: int, loop_length: int, adapt: bool = False) -> tuple[Sample, dict]:
    """The sample with another loop. `loop_length` 0 removes the loop (then `loop_start` must be 0).

    Points are in bytes and even. Without a loop the first two bytes must be zero: if they are not,
    `adapt` prepends two zero bytes (the PCM stays exact) and otherwise the call is refused.
    """
    count = len(sample.pcm)
    require_int(loop_start, "loop_start", 0, count, "SAMPLE_LOOP")
    require_int(loop_length, "loop_length", 0, count, "SAMPLE_LOOP")
    if loop_start % 2 or loop_length % 2:
        raise _bad("Loop points must be even (two-byte aligned).", "SAMPLE_LOOP")
    pcm, adaptations = sample.pcm, []
    if loop_length:
        if loop_length < 4 or loop_start + loop_length > count:
            raise _bad(f"A loop is at least 4 bytes and must end inside the sample ({count} bytes).", "SAMPLE_LOOP")
    else:
        if loop_start:
            raise _bad("loop_start must be 0 when loop_length is 0 (no loop).", "SAMPLE_LOOP")
        pcm = leading_zero(pcm, adapt, adaptations, "Removing the loop")
    result = _with(sample, pcm=pcm, loop_start=loop_start, loop_length=loop_length)
    report = {"loop_start": loop_start, "loop_length": loop_length, "looped": bool(loop_length),
              "bytes": len(pcm), "adaptations": adaptations}
    if loop_length:
        report["seam_jump"] = abs(pcm[loop_start + loop_length - 1] - pcm[loop_start])
    return result, report


def trim(sample: Sample, start: int | None = None, end: int | None = None, adjust_loop: bool = False,
         adapt: bool = False) -> tuple[Sample, dict]:
    """Keep `pcm[start:end]` byte for byte. `start` and `end` are even; the default is the whole side.

    A loop that stays whole inside the range just moves with it. Cutting into the loop (or removing it
    from the range) is refused unless `adjust_loop`, which keeps the part of the loop inside the range
    (at least 4 bytes, else the loop is removed). A result without a loop must start with two zero bytes:
    with `adapt` two zero bytes are prepended in front of the kept PCM, otherwise it is refused.
    """
    count = len(sample.pcm)
    start = 0 if start is None else start
    end = count if end is None else end
    require_int(start, "start", 0, count, "SAMPLE_LENGTH")
    require_int(end, "end", 0, count, "SAMPLE_LENGTH")
    if start % 2 or end % 2:
        raise _bad("start and end must be even so loop points and the sample length stay two-byte aligned.",
                   "SAMPLE_LENGTH")
    if end - start < 4:
        raise _bad(f"The kept range [{start}, {end}) is shorter than 4 bytes.", "SAMPLE_LENGTH")
    kept = sample.pcm[start:end]
    loop_start, loop_length, adaptations = 0, 0, []
    if sample.loop_length:
        first, last = sample.loop_start, sample.loop_start + sample.loop_length
        if start <= first and last <= end:
            loop_start, loop_length = first - start, sample.loop_length
        elif not adjust_loop:
            raise _bad(f"The range [{start}, {end}) cuts the loop [{first}, {last}). Keep the whole loop, or pass "
                       "\"adjust_loop\": true to keep only the part of the loop inside the range.", "SAMPLE_LOOP")
        else:
            low, high = max(first, start), min(last, end)
            if high - low >= 4:
                loop_start, loop_length = low - start, high - low
                adaptations.append("loop-shortened")
            else:
                adaptations.append("loop-removed")
    if not loop_length:
        kept = leading_zero(kept, adapt, adaptations, "Trimming")
    result = _with(sample, pcm=kept, loop_start=loop_start, loop_length=loop_length)
    return result, {"start": start, "end": end, "bytes_before": count, "bytes": len(kept),
                    "loop_start": loop_start, "loop_length": loop_length, "adaptations": adaptations}


def _headroom_factor(pcm: Sequence[int]) -> float | None:
    ratios = [127 / value if value > 0 else 128 / -value for value in pcm if value]
    return min(ratios) if ratios else None


def headroom_db(pcm: Sequence[int]) -> float | None:
    """The largest gain in dB that keeps every byte inside -128..127 (None for silence)."""
    room = _headroom_factor(pcm)
    return round(20 * math.log10(room), 3) if room else None


def gain(sample: Sample, db: float, allow_clip: bool = False) -> tuple[Sample, dict]:
    """Scale the PCM by `db` decibels, rounding to the nearest byte (halves away from zero).

    If any byte would leave -128..127 the call is refused (`SAMPLE_CLIP`, with the clean headroom) unless
    `allow_clip`, which clamps those bytes and reports how many.
    """
    db = number(db, "db", -60, 60)
    factor = 10 ** (db / 20)
    scaled = [_round(value * factor) for value in sample.pcm]
    clipped = sum(1 for value in scaled if value > 127 or value < -128)
    room = headroom_db(sample.pcm)
    if clipped and not allow_clip:
        raise _bad(f"A gain of {db:+g} dB would clip {clipped} byte(s). The largest clean gain for this sample is "
                   f"{room:+g} dB; lower the gain, or pass \"allow_clip\": true to clamp.", "SAMPLE_CLIP")
    pcm = tuple(_clamp(value) for value in scaled)
    changed = sum(1 for before, after in zip(sample.pcm, pcm) if before != after)
    return _with(sample, pcm=pcm), {
        "db": db, "factor": round(factor, 6), "peak_before": max(map(abs, sample.pcm), default=0),
        "peak_after": max(map(abs, pcm), default=0), "clipped": clipped, "changed_bytes": changed,
        "headroom_db": room}


def fade(sample: Sample, fade_in: int = 0, fade_out: int = 0, allow_loop: bool = False) -> tuple[Sample, dict]:
    """Linear fade-in over the first `fade_in` bytes and fade-out over the last `fade_out` bytes.

    On a looped sample the fades must stay outside the loop (before its start and after its end), because a
    fade inside the loop would make every repeat dip; `allow_loop` accepts that anyway.
    """
    count = len(sample.pcm)
    require_int(fade_in, "fade_in", 0, count)
    require_int(fade_out, "fade_out", 0, count)
    if not fade_in and not fade_out:
        raise _bad("Give fade_in and/or fade_out in bytes.")
    if fade_in + fade_out > count:
        raise _bad(f"fade_in + fade_out ({fade_in + fade_out}) is longer than the sample ({count} bytes).")
    touches = False
    if sample.loop_length:
        touches = (fade_in > sample.loop_start
                   or (fade_out and count - fade_out < sample.loop_start + sample.loop_length))
        if touches and not allow_loop:
            raise _bad("This fade reaches into the loop, so every repeat would dip. Keep fade_in within the bytes "
                       "before loop_start and fade_out within the bytes after the loop end, or pass "
                       "\"allow_loop\": true.", "SAMPLE_LOOP")
    values = list(sample.pcm)
    for index in range(fade_in):
        values[index] = _round(values[index] * index / fade_in)
    for position in range(fade_out):  # position 0 is the last byte, which fades to silence
        values[count - 1 - position] = _round(values[count - 1 - position] * position / fade_out)
    pcm = tuple(values)
    return _with(sample, pcm=pcm), {"fade_in": fade_in, "fade_out": fade_out, "touches_loop": bool(touches),
                                    "changed_bytes": sum(1 for a, b in zip(sample.pcm, pcm) if a != b)}


def match_level(sample: Sample, role: str, reference: dict) -> tuple[Sample, dict]:
    """Set the volume of a PCM sample to its role's reference level, adding clean gain only if volume 64 is short.

    `role` is a role (kick, bass, ...) or a group name; `reference` comes from `synth_tools.resolve_reference`.
    The gain never clips: when the peak limits it, volume stays at 64 and `limited_by_peak` is true.
    """
    target = loudness.target_db(role, reference)
    level, needed = loudness.volume_for(sample, target)
    applied = 0.0
    result = _with(sample, volume=level)
    if needed > 64.5:
        room = _headroom_factor(sample.pcm) or 1.0
        factor = min(needed / 64, room * (1 - 1e-9))
        if factor > 1:
            applied = round(20 * math.log10(factor), 3)
            result, _ = gain(sample, applied)
            # Rounding to bytes moves the level a hair: take the volume from the edited PCM.
            level, needed = loudness.volume_for(result, target)
            result = _with(result, volume=level)
    measured = loudness.measure(result)
    return result, {"role": role, "group": loudness.ROLES.get(role, role), "reference": reference["source"],
                    "target_db": target, "volume_before": sample.volume, "volume": result.volume,
                    "gain_db": applied, "measured_db": measured["loudness_db"], "peak_db": measured["peak_db"],
                    "deviation_db": round(measured["loudness_db"] - target, 2),
                    "limited_by_peak": needed > 64.5}


# --- provenance and source rules -------------------------------------------------------------------

def guard_edit(module, sample: Sample, slot: int) -> None:
    """Refuse to edit an empty slot, and to drop the recipe of a sample in a `synthesized` project."""
    if not sample.pcm:
        raise _bad(f"Sample slot {slot} is empty; there is nothing to edit.", "SAMPLE_SLOT")
    if sample.recipe is not None and sample_source.declared(module) == "synthesized":
        raise sample_source.SampleSourceError(
            f"Slot {slot} is a recipe sample in a project that declares sample_source 'synthesized'. Editing its PCM "
            "would drop the recipe and fail validation. Change the recipe instead (recipe_sample with replace), "
            "use sample_match_level for loudness, or set metadata.sample_source to 'mixed' only if the owner asks.",
            [{"slot": slot, "reason": "PCM edit of a recipe sample in a synthesized project"}])


def guard_new_pcm(module) -> None:
    """Drawn or embedded PCM is neither a library sample nor a recipe: only undeclared and mixed projects take it."""
    found = sample_source.declared(module)
    if found in ("library", "synthesized"):
        raise sample_source.SampleSourceError(
            f"This project declares sample_source {found!r}; drawn or embedded PCM is refused. "
            + ("Use a library sample, or draw with a recipe (a 'draw' recipe via recipe_sample)."
               if found == "synthesized" else "Use a library sample.")
            + " Set metadata.sample_source to 'mixed' only if the owner asks for both.",
            [{"slot": None, "reason": f"drawn PCM into a {found} project"}])


def sources_of(module) -> dict:
    sources = module.metadata.setdefault("sample_sources", {})
    if not isinstance(sources, dict):
        raise _bad("Project metadata.sample_sources must be an object.", "SCHEMA")
    return sources


def record_edit(module, slot: int, before: Sample, edit: dict) -> dict:
    """Write the provenance of an edited slot into `metadata.sample_sources[str(slot)]` and return it.

    A recipe sample becomes `{"origin": "derived", "derived_from": "recipe", "recipe": {...}}` (the recipe that
    built the PCM before the first edit). A library sample keeps its `library_id` and gets `"edited": true`.
    Plain embedded PCM gets `{"origin": "embedded-pcm", "edited": true}`. Every kind keeps the last
    `MAX_RECORDED_EDITS` edits (`edits`) and the total (`edit_count`).
    """
    sources = sources_of(module)
    entry = dict(sources[str(slot)]) if isinstance(sources.get(str(slot)), dict) else {}
    if before.recipe is not None:
        role = entry.get("role")
        entry = {"origin": "derived", "derived_from": "recipe", "recipe": copy.deepcopy(before.recipe)}
        if before.recipe.get("type"):
            entry["recipe_type"] = before.recipe["type"]
        if role:
            entry["role"] = role
    elif not entry:
        entry = {"origin": "embedded-pcm"}
    entry["edited"] = True
    entry["edits"] = [*entry.get("edits", []), {key: value for key, value in edit.items() if value is not None}][
        -MAX_RECORDED_EDITS:]
    entry["edit_count"] = int(entry.get("edit_count", 0)) + 1
    sources[str(slot)] = entry
    return entry


# --- drawn waves and summaries ---------------------------------------------------------------------

def draw_to_pcm(points: Sequence[float], cycles: int = 16, frequency: float = synth.DEFAULT_FREQUENCY,
                peak: float = 0.88) -> tuple[int, ...]:
    """PCM for a looped hand-drawn wave: `points` (4-256 values in -1..1) along one cycle, repeated `cycles` times.

    The whole result is the loop (`loop_start` 0, `loop_length` = its length); `frequency` is the pitch heard at
    note C-2. The same maths as the `draw` recipe, so a drawing can be kept either as PCM or as that recipe.
    """
    recipe = {"type": "draw", "points": list(points), "cycles": cycles, "frequency": frequency, "peak": peak}
    return synth.from_recipe("Drawn", recipe).pcm


def pcm_fields(pcm: Sequence[int], loop_start: int = 0, loop_length: int | None = None) -> dict:
    """The fields of a `sample_set_pcm` operation for `pcm` (default loop: the whole sample)."""
    return {"pcm_base64": base64.b64encode(pcm_bytes(pcm)).decode("ascii"), "pcm_sha256": pcm_sha256(pcm),
            "loop_start": loop_start, "loop_length": len(pcm) if loop_length is None else loop_length}


def waveform_summary(pcm: Sequence[int] | bytes, buckets: int = 128) -> list[tuple[int, int]]:
    """(min, max) of the signed PCM per bucket, `buckets` buckets covering the whole sample.

    Raw `bytes` are read as unsigned MOD bytes. A sample shorter than `buckets` gives one bucket per byte.
    """
    require_int(buckets, "buckets", 1, 8192)
    values = [value - 256 if value > 127 else value for value in pcm] if isinstance(pcm, (bytes, bytearray)) else list(pcm)
    count = len(values)
    result = []
    for index in range(min(buckets, count)):
        low = index * count // min(buckets, count)
        high = max(low + 1, (index + 1) * count // min(buckets, count))
        part = values[low:high]
        result.append((min(part), max(part)))
    return result


# --- audition without FFmpeg -------------------------------------------------------------------------

def render_wav(sample: Sample, note: str = "C-2", seconds: float = 1.0) -> tuple[bytes, array]:
    """A mono 16-bit 44.1 kHz WAV of the sample at a tracker note (volume, fine tune and loop honoured).

    Same output as `audio.audition_sample`, in memory. Returns (wav bytes, the 16-bit values).
    """
    if note not in NOTE_TO_PERIOD or type(seconds) not in (int, float) or not math.isfinite(seconds) \
            or not .05 <= seconds <= 5:
        raise ValidationError("Audition requires a tracker note C-1..B-3 and 0.05-5 seconds.", "INVALID_VALUE")
    values, start, length = sample.pcm, sample.loop_start, sample.loop_length
    rate = PAL_CLOCK / NOTE_TO_PERIOD[note] * 2 ** (sample.finetune / 96)
    frames = round(seconds * PREVIEW_RATE)
    out = array("h")
    for frame in range(frames):
        position = frame * rate / PREVIEW_RATE
        if length and position >= start + length:
            position = start + (position - start) % length
        index = int(position)
        out.append(round((values[index] if index < len(values) else 0) * 256 * sample.volume / 64))
    payload = array("h", out)
    if sys.byteorder != "little":
        payload.byteswap()
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setparams((1, 2, PREVIEW_RATE, frames, "NONE", "not compressed"))
        writer.writeframes(payload.tobytes())
    return buffer.getvalue(), out


def wav_metrics(values: Sequence[int]) -> dict:
    peak = max(map(abs, values), default=0)
    rms = math.sqrt(sum(value * value for value in values) / len(values)) / 32768 if values else 0
    return {"peak": round(peak / 32768, 6), "peak_dbfs": round(20 * math.log10(peak / 32768), 3) if peak else None,
            "rms_dbfs": round(20 * math.log10(rms), 3) if rms else None,
            "clipped_samples": sum(1 for value in values if value >= 32767 or value <= -32768)}


def preview_recipe(recipe: dict, note: str = "C-2", seconds: float = 1.0, volume: int = 64, finetune: int = 0,
                   name: str = "Preview", role: str | None = None) -> tuple[bytes, dict]:
    """Audition a recipe in memory: (WAV bytes, measurements). No FFmpeg and no file is written.

    The measurements match `chiploom synth preview` (sample facts, loudness, peak/RMS of the WAV) for an agent
    that cannot listen.
    """
    require_int(volume, "volume", 0, 64)
    require_int(finetune, "finetune", -8, 7)
    ascii_field(name, 22, "Sample name")
    recipe = synth.smooth_start(recipe)
    sample = synth.from_recipe(name, recipe, volume, finetune)
    wav, values = render_wav(sample, note, float(seconds))
    role = loudness.role_for_recipe(recipe) if role is None else loudness.check_role(role)
    level = loudness.measure(sample)
    return wav, {"ok": True, "name": name, "recipe": recipe, "note": note, "seconds": float(seconds),
                 "sample_rate": PREVIEW_RATE, "volume": volume, "finetune": finetune,
                 "playback_rate": PAL_CLOCK / NOTE_TO_PERIOD[note] * 2 ** (finetune / 96),
                 "sample": synth.recipe_facts(sample),
                 "loudness": {"role": role, "group": loudness.ROLES[role], "loudness_db": level["loudness_db"],
                              "peak_db": level["peak_db"], "default_reference_db": loudness.target_db(role)},
                 "audio": wav_metrics(values)}


def _default_recipe(entry: dict) -> dict:
    recipe: dict = {"type": entry["type"]}
    shape = None
    for name, spec in entry["parameters"].items():
        if name == "points":
            recipe["points"] = [round(math.sin(math.tau * index / 16), 4) for index in range(16)]
            continue
        default = spec.get("default")
        if spec.get("required") and spec["kind"] == "choice":
            shape = recipe[name] = "pulse" if "pulse" in spec["choices"] else spec["choices"][0]
        elif default is not None and default != "auto":
            recipe[name] = default
    # Parameters that do not apply to the chosen shape are removed (e.g. noise-only ones on a pulse).
    for name, spec in entry["parameters"].items():
        if shape and spec.get("applies_to") and shape not in spec["applies_to"]:
            recipe.pop(name, None)
    return recipe


def recipe_schema() -> dict:
    """Everything a form needs to build and check a recipe: the types with their parameters, ranges and defaults.

    `types[i]["default_recipe"]` is a valid starting recipe for the type; `limits` holds the sample and note ranges.
    """
    types = []
    for entry in synth.recipe_types():
        types.append({**entry, "default_recipe": _default_recipe(entry)})
    return {"ok": True, "types": types, "roles": dict(loudness.ROLES), "notes": list(NOTES),
            "limits": {"volume": [0, 64], "finetune": [-8, 7], "name_length": 22, "max_bytes": MAX_PCM_BYTES,
                       "preview_seconds": [0.05, 5], "preview_sample_rate": PREVIEW_RATE,
                       "draw_points": [4, 256], "draw_cycles": [1, 64]},
            "pitch": "frequency is the pitch heard when the sample plays at tracker note C-2 (period 428)."}
