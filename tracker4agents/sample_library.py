"""Portable local sample banks: exact PCM, playback variants, readable labels, roles and palettes.

No Qt, model provider or audio decoder is required. A bank is the owner's local data (never published): an
entry keeps the sample's own name (cleaned to 22 printable ASCII characters, or a neutral name when it has
none) and a readable `source` (file, slot, original name); private/provenance.json keeps every occurrence for
the roles and palettes. Imported PCM is never normalized. `add_entry` adds one sample with the name, role
and tags the owner chose (see `sample_intake` for module slots and WAV files).

Entries come from MOD and XM modules (files, ZIP archives, folders). An 8-bit sample is stored
as `pcm/<sha256>.pcm` (signed bytes), a 16-bit one as `pcm/<sha256>.pcm16` (signed little-endian
16-bit frames); `bits`, `loop_mode`, `panning`, `relative_note` and `format_origin` say what the
sample is, `envelope` keeps the XM instrument facts an agent can use (sustain, vibrato, fadeout),
and `role` / `role_confidence` / `role_evidence` say what the sample is *for*, scored by
`usage.study` on the module that plays it (or from the PCM alone when the module is gone).
`palettes.json` (see `sample_palettes`) remembers which entries played together and how each
song is built. Schema v2; a v1 manifest is read and rewritten as v2 on the next update.
"""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
import copy
import hashlib
import io
import math
from operator import mul
from pathlib import Path
import re
import struct
import zipfile

from . import formats, mod, project, sample_source, xm
from .model import (NOTE_TO_PERIOD, PAL_CLOCK, Module, Sample, ValidationError,
                    ascii_field, require_int, validate, validate_sample)
from .reference_layout import MAX_ARCHIVE, MAX_FILE, parse_layout

SCHEMA = "chiploom.sample-library.v2"
SCHEMAS = ("chiploom.sample-library.v1", SCHEMA)
PROVENANCE_SCHEMA = "chiploom.sample-provenance.v1"
DEFAULT_LIBRARY = Path("exports/sample_library")
MAX_ENTRIES = 10_000
MAX_PCM = 131_070  # A 16-bit length in words in a 31-sample reference header.
MAX_FRAMES = xm.MAX_SAMPLE_FRAMES      # loop points of an XM sample, in frames
MAX_PCM_BYTES = 2 * MAX_FRAMES        # a 16-bit XM sample of the longest accepted length
MAX_FOLDER = 256 * 1024 * 1024        # bytes read from a folder in one extraction
MAX_MOD_LENGTH = 65_534               # bytes of a MOD sample
CATEGORIES = ("cycle", "percussion", "texture", "effect", "unclassified", "silent")
SETTINGS = ("pcm_sha256", "loop_start", "loop_length", "finetune", "volume", "bits", "loop_mode", "panning",
            "relative_note")
# Fields a v1 entry lacks: a v1 bank holds 8-bit MOD samples without roles.
ENTRY_DEFAULTS = {"format_origin": "mod", "bits": 8, "loop_mode": "forward", "panning": 128, "relative_note": 0,
                  "envelope": None, "role": None, "role_confidence": None, "role_evidence": [],
                  "role_occurrences": 0, "role_source": None, "retune": None}
MAX_RETUNE_SEMITONES = 48   # the owner's tuning correction of an entry: up to four octaves either way
XM_C4_RATE = 8363.0  # FastTracker II plays C-4 of an untransposed sample at this rate
MODULE_SUFFIXES = (".mod", ".xm")
SOURCE_SUFFIXES = MODULE_SUFFIXES + (".zip",)


def _limit(suffix: str) -> int:
    """Size limit of one input by extension (a MOD 4 MiB, an XM 24 MiB, a ZIP 64 MiB; others as a MOD)."""
    return {".xm": xm.MAX_XM_BYTES, ".zip": MAX_ARCHIVE}.get(suffix.lower(), MAX_FILE)

# Pitch estimates. C-2 periods for finetunes 0..7 then -8..-1 (ProTracker tuning, the same table as
# audio.sample_preview); a sample plays PAL_CLOCK / period bytes per second at tracker note C-2.
C2_PERIODS = (428, 425, 422, 419, 416, 413, 410, 407, 453, 450, 447, 444, 441, 437, 434, 431)
PITCH_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
MAX_CYCLE_LOOP = 1024  # loops up to this length are searched for whole cycles; longer ones use autocorrelation
CYCLE_CORRELATION = 0.85  # every shift by a multiple of the cycle must correlate at least this much
MIN_PITCH_HZ = 20.0
MAX_ANALYSIS = 1024  # samples compared per lag in the autocorrelation estimate
APERIODICITY_LIMIT = 0.2  # YIN threshold on the cumulative-mean-normalized difference
PITCH_NOTE = ("Measured estimate, not a listening judgment: fundamental frequency when the sample plays at "
              "tracker note C-2 with its finetune (PAL ProTracker periods). nearest_note uses scientific pitch "
              "names (A4 = 440 Hz); transpose_semitones is the pitch-class offset from the written note to the "
              "heard one (+2: a written C sounds D). Each semitone up multiplies the frequency by 2^(1/12).")


def clean_name(text: str | None) -> str | None:
    """A sample name usable in the bank: printable ASCII, spaces collapsed, at most 22 characters; None when
    nothing is left. The text is source data, kept as a label only."""
    cleaned = " ".join("".join(char if 32 <= ord(char) < 127 else " " for char in str(text or "")).split())
    return cleaned[:22].rstrip() or None


def check_retune(value: dict) -> dict:
    """An entry's tuning correction: whole `semitones` (an octave is 12) and `cents` (-100..100)."""
    if not isinstance(value, dict) or set(value) != {"semitones", "cents"}:
        raise ValidationError("retune: {semitones, cents} expected.", "SAMPLE_LIBRARY")
    require_int(value["semitones"], "retune.semitones", -MAX_RETUNE_SEMITONES, MAX_RETUNE_SEMITONES)
    require_int(value["cents"], "retune.cents", -100, 100)
    return value


def apply_retune(sample: Sample, retune: dict | None, fmt: str) -> tuple[Sample, dict | None]:
    """The sample with the owner's tuning correction applied for a song of format `fmt`: an XM takes it in its
    relative note and finetune (1/128 semitone); a MOD takes the cents in its finetune (1/8 semitone) and cannot
    hold whole semitones, so the result says how many semitones to transpose the notes. The PCM is not touched."""
    import dataclasses
    if not retune or (not retune["semitones"] and not retune["cents"]):
        return sample, None
    if fmt == "xm":
        steps = sample.relative_note * 128 + sample.finetune + retune["semitones"] * 128 + round(retune["cents"] * 1.28)
        relative = max(-96, min(95, round(steps / 128)))
        finetune = max(-128, min(127, steps - relative * 128))
        return dataclasses.replace(sample, relative_note=relative, finetune=finetune), {
            **retune, "applied": "relative_note and finetune", "transpose_notes": 0}
    finetune = max(-8, min(7, sample.finetune + round(retune["cents"] / 12.5)))
    return dataclasses.replace(sample, finetune=finetune), {
        **retune, "applied": "finetune" if retune["cents"] else "none", "transpose_notes": retune["semitones"],
        "note": "A MOD sample has no relative note: transpose its notes by transpose_notes semitones."
                if retune["semitones"] else None}


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


def pcm_values(raw: bytes, bits: int = 8) -> tuple[int, ...]:
    """Signed frames of stored PCM: one byte each, or little-endian 16-bit words."""
    if bits == 16:
        return struct.unpack(f"<{len(raw) // 2}h", raw[:len(raw) // 2 * 2])
    return _signed(raw)


def pcm_bytes(values: tuple[int, ...], bits: int = 8) -> bytes:
    if bits == 16:
        return struct.pack(f"<{len(values)}h", *values)
    return bytes(value & 255 for value in values)


def high_bytes(raw: bytes, bits: int) -> bytes:
    """An 8-bit view of stored PCM for the signal heuristics (the high byte of each 16-bit frame)."""
    return raw[1::2] if bits == 16 else raw


def xm_c4_rate(sample: Sample) -> float:
    """Frames per second an XM plays this sample at note C-4 (relative note and finetune in 1/128 semitone)."""
    return XM_C4_RATE * 2 ** (sample.relative_note / 12 + sample.finetune / (128 * 12))


def _sample(entry: dict, raw: bytes) -> Sample:
    bits = entry.get("bits", 8)
    return Sample(entry["name"], pcm_values(raw, bits), entry["volume"], entry["finetune"],
                  entry["loop_start"], entry["loop_length"], None, bits, entry.get("loop_mode", "forward"),
                  entry.get("panning", 128), entry.get("relative_note", 0))


def mod_adaptations(sample: Sample) -> list[str]:
    """What `adapt` would change to fit this sample into a MOD, in the order `adapt_for_mod` applies it; empty
    when the sample already fits. Raises when no adaptation can make it fit (too long, invalid loop)."""
    changes = []
    length = len(sample.pcm)
    if sample.bits == 16:
        changes.append("convert-16-bit-to-8-bit")
    looped = bool(sample.loop_length)
    if looped and sample.loop_start + sample.loop_length > length:
        raise ValidationError("invalid loop (runs past the end of the sample); it is not adapted.", "SAMPLE_LOOP")
    if looped and sample.loop_mode == "pingpong":
        changes.append("unfold-pingpong-loop")
        length = sample.loop_start + 2 * sample.loop_length + max(0, length - sample.loop_start - sample.loop_length)
    if sample.panning != 128:
        changes.append("drop-panning")
    if sample.relative_note or not -8 <= sample.finetune <= 7:
        changes.append("map-xm-tuning")
    if length % 2 or (looped and (sample.loop_start % 2 or sample.loop_length % 2)):
        changes.append("align-to-even-bytes")
        length += length % 2
    if not looped:
        if sample.loop_start:
            changes.append("clear-inactive-loop-start")
        if any(sample.pcm[:2]):
            changes.append("prepend-two-zero-bytes")
            length += 2
    if length > MAX_MOD_LENGTH or length < 4:
        raise ValidationError(f"{length} bytes: a MOD sample holds 4 to {MAX_MOD_LENGTH} bytes; it is not adapted.",
                              "SAMPLE_LENGTH")
    return changes


def adapt_for_mod(sample: Sample) -> tuple[Sample, list[str]]:
    """A copy of `sample` that fits the MOD profile, with what changed (see `mod_adaptations`). The PCM is
    reduced to 8 bits (high byte), a ping-pong loop is unfolded (the loop then its reverse, twice as long),
    panning is dropped, the XM tuning becomes the nearest MOD finetune (the relative note is reported, not
    applied: transpose the notes instead), loop points and the length are aligned to even bytes."""
    changes = mod_adaptations(sample)
    out = copy.deepcopy(sample)
    pcm = list(out.pcm)
    if "convert-16-bit-to-8-bit" in changes:
        pcm = [value >> 8 for value in pcm]
        out.bits = 8
    if "unfold-pingpong-loop" in changes:
        start, end = out.loop_start, out.loop_start + out.loop_length
        pcm = pcm[:end] + pcm[start:end][::-1] + pcm[end:]
        out.loop_length *= 2
        out.loop_mode = "forward"
    if "drop-panning" in changes:
        out.panning = 128
    if "map-xm-tuning" in changes:
        tune = max(-8, min(7, round(out.finetune / 16)))
        detail = f"finetune {out.finetune}/128 -> {tune}/8"
        if out.relative_note:
            sign = "+" if out.relative_note > 0 else ""
            detail += f"; relative note {sign}{out.relative_note} dropped: write notes {sign}{out.relative_note} semitones"
        changes[changes.index("map-xm-tuning")] = f"map-xm-tuning ({detail})"
        out.finetune, out.relative_note = tune, 0
    if "align-to-even-bytes" in changes:
        if out.loop_length:
            if out.loop_start % 2:
                out.loop_start -= 1
                out.loop_length += 1
            if out.loop_length % 2:
                out.loop_length -= 1
        if len(pcm) % 2:
            pcm.append(0)
    if "clear-inactive-loop-start" in changes:
        out.loop_start = 0
    if "prepend-two-zero-bytes" in changes:
        pcm = [0, 0] + pcm
    out.pcm = tuple(pcm)
    return out, changes


def _compatibility(entry: dict, raw: bytes) -> dict:
    """Does the entry fit a MOD as it is; if not, why, and what `adapt` would do (null when nothing can)."""
    sample = _sample(entry, raw)
    try:
        validate_sample(sample)
    except ValueError as exc:
        try:
            adapt = mod_adaptations(sample)
        except ValidationError:
            adapt = None
        return {"compatible": False, "issue": str(exc), "adapt": adapt}
    return {"compatible": True, "issue": None, "adapt": []}


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


def c2_playback_rate(finetune: int) -> float:
    """Bytes per second played at tracker note C-2 for a MOD finetune (-8..7)."""
    return PAL_CLOCK / C2_PERIODS[finetune & 15]


def _nearest(frequency: float) -> dict:
    position = 69 + 12 * math.log2(frequency / 440)
    number = round(position)
    pitch_class = number % 12
    return {"nearest_note": f"{PITCH_NAMES[pitch_class]}{number // 12 - 1}", "pitch_class": PITCH_NAMES[pitch_class],
            "cents": round((position - number) * 100, 1), "transpose_semitones": (pitch_class + 5) % 12 - 5}


def _loop_cycles(loop: list[float]) -> tuple[int, float] | None:
    """(whole cycles inside a circular loop, worst correlation of its shifts); None for a flat loop.

    The loop holds k cycles when shifting it by every multiple of length/k reproduces it; the
    largest such k wins. Fractional shifts interpolate the integer-lag circular autocorrelation.
    """
    size = len(loop)
    energy = sum(map(mul, loop, loop))
    if energy <= 1e-9:
        return None
    correlation = [sum(map(mul, loop, loop[lag:] + loop[:lag])) / energy for lag in range(size)]

    def at(lag: float) -> float:
        low = int(lag)
        fraction = lag - low
        return correlation[low % size] * (1 - fraction) + correlation[(low + 1) % size] * fraction

    for cycles in range(size // 2, 1, -1):
        step = size / cycles
        worst = 1.0
        for multiple in range(1, cycles):
            worst = min(worst, at(step * multiple))
            if worst < CYCLE_CORRELATION:
                break
        else:
            return cycles, worst
    return 1, 1.0


def _yin(values: list[float], rate: float) -> tuple[float, float] | None:
    """(period in samples, aperiodicity) from YIN's normalized difference; None without a clear period."""
    max_lag = min(int(rate / MIN_PITCH_HZ), len(values) // 2)
    width = min(MAX_ANALYSIS, len(values) - max_lag)
    if max_lag < 8 or width < 64:
        return None
    count = width + max_lag
    mean = sum(values[:count]) / count
    values = [value - mean for value in values[:count]]
    head = values[:width]
    head_energy = sum(map(mul, head, head))
    squares = [0.0]
    for value in values:
        squares.append(squares[-1] + value * value)
    normalized = [1.0]
    running = 0.0
    for lag in range(1, max_lag + 1):
        tail = values[lag:lag + width]
        difference = head_energy + squares[lag + width] - squares[lag] - 2 * sum(map(mul, head, tail))
        running += difference
        normalized.append(difference * lag / running if running > 1e-9 else 1.0)
    lag = next((index for index in range(2, max_lag) if normalized[index] < APERIODICITY_LIMIT), None)
    if lag is None:
        return None
    while lag + 1 < max_lag and normalized[lag + 1] < normalized[lag]:
        lag += 1
    before, here, after = normalized[lag - 1], normalized[lag], normalized[lag + 1]
    bend = before - 2 * here + after
    offset = (before - after) / (2 * bend) if bend > 1e-12 else 0.0
    return lag + max(-.5, min(.5, offset)), max(0.0, here)


def playback_rate(sample: Sample, origin: str = "mod") -> tuple[float, str]:
    """(frames per second, reference note) of a bank sample: ProTracker C-2 for a MOD sample, FastTracker C-4
    (relative note and 1/128-semitone finetune applied) for an XM one."""
    if origin == "xm":
        return xm_c4_rate(sample), "C-4"
    return c2_playback_rate(sample.finetune), "C-2"


def estimate_pitch(sample: Sample, origin: str = "mod") -> dict:
    """Estimated fundamental of a sample at its reference note (`playback_rate`): a measurement with its method,
    or null and a reason. `estimated_hz_at_c2` keeps its name for an XM sample too (the reference is then C-4).

    Looped samples up to MAX_CYCLE_LOOP bytes: playback rate x whole cycles in the loop / loop length.
    Other samples: YIN autocorrelation over the loop or, for a one-shot, over the part after its loudest attack.
    """
    rate, reference = playback_rate(sample, origin)
    pcm = sample.pcm
    looped = bool(sample.loop_length) and sample.loop_start + sample.loop_length <= len(pcm)
    result = {"measurement": "estimate", "method": None, "reference_note": reference, "finetune": sample.finetune,
              "playback_rate_hz": round(rate, 3), "loop_length": sample.loop_length if looped else None,
              "loop_cycles": None, "cycle_length": None, "periodicity": None, "region": None,
              "estimated_hz_at_c2": None, "nearest_note": None, "pitch_class": None, "cents": None,
              "transpose_semitones": None, "reason": None, "note": PITCH_NOTE}
    if not any(pcm):
        result["reason"] = "silent sample"
        return result
    found = None
    if looped and sample.loop_length <= MAX_CYCLE_LOOP:
        start, end = sample.loop_start, sample.loop_start + sample.loop_length
        loop = pcm[start:end]
        mean = sum(loop) / len(loop)
        cycles = _loop_cycles([value - mean for value in loop])
        result["region"] = [start, end]
        if cycles is None:
            result["reason"] = "the loop is flat (constant level): no pitch"
            return result
        frequency = rate * cycles[0] / sample.loop_length
        if frequency < MIN_PITCH_HZ:
            result["reason"] = (f"the loop repeats at {frequency:.2f} Hz, below the pitch range "
                                "(a noise or texture loop)")
            return result
        result.update(method="loop-cycles", loop_cycles=cycles[0],
                      cycle_length=round(sample.loop_length / cycles[0], 3), periodicity=round(cycles[1], 3),
                      estimated_hz_at_c2=round(frequency, 3), **_nearest(frequency))
        return result
    if looped:
        start, end = sample.loop_start, sample.loop_start + sample.loop_length
        loop = [float(value) for value in pcm[start:end]]
        needed = MAX_ANALYSIS + int(rate / MIN_PITCH_HZ)
        found = _yin((loop * (needed // len(loop) + 1))[:needed], rate)
        reason = "no stable periodicity in the loop (noise or inharmonic sound)"
    else:
        from .loudness import WINDOW, audible_region
        begin, end = audible_region(Sample(sample.name, pcm, sample.volume, sample.finetune, 0, 0))
        energies = [sum(value * value for value in pcm[index:index + WINDOW]) for index in range(begin, end, WINDOW)]
        loudest = begin + WINDOW * max(range(len(energies)), key=energies.__getitem__)
        # Skip the loudest window (the attack) when enough of the sound remains after it.
        start = loudest + WINDOW if end - loudest - WINDOW >= 512 else loudest
        found = _yin([float(value) for value in pcm[start:end]], rate)
        reason = "no stable periodicity after the attack (noise, drum, or too short to measure)"
    result["region"] = [start, end]
    if found is None:
        result["reason"] = reason
        return result
    period, aperiodicity = found
    frequency = rate / period
    result.update(method="autocorrelation", cycle_length=round(period, 3), periodicity=round(1 - aperiodicity, 3),
                  estimated_hz_at_c2=round(frequency, 3), **_nearest(frequency))
    return result


def pitch_at_note(pitch: dict, note: str) -> dict | None:
    """The C-2 estimate moved to another tracker note (period ratio, finetune kept); None without an estimate."""
    if pitch.get("estimated_hz_at_c2") is None:
        return None
    frequency = pitch["estimated_hz_at_c2"] * NOTE_TO_PERIOD["C-2"] / NOTE_TO_PERIOD[note]
    return {"note": note, "estimated_hz": round(frequency, 3), **_nearest(frequency)}


def _pitch_summary(sample: Sample, origin: str = "mod") -> dict | None:
    """Compact list-view estimate: only the cheap loop-cycle method on short loops; None otherwise."""
    if not sample.loop_length or sample.loop_length > MAX_CYCLE_LOOP:
        return None
    pitch = estimate_pitch(sample, origin)
    if pitch["method"] != "loop-cycles":
        return None
    return {key: pitch[key] for key in ("estimated_hz_at_c2", "nearest_note", "cents", "transpose_semitones",
                                        "loop_cycles")}


def _zip_members(original: bytes) -> list[tuple[str, bytes]]:
    try:
        with zipfile.ZipFile(io.BytesIO(original)) as archive:
            members = archive.infolist()
            if len(members) > 512 or sum(item.file_size for item in members) > MAX_ARCHIVE:
                raise ValidationError("Archive exceeds 512 entries or 64 MiB expanded.")
            inputs = []
            for item in members:
                suffix = Path(item.filename).suffix.lower()
                if not item.is_dir() and suffix in MODULE_SUFFIXES:
                    if item.file_size > _limit(suffix):
                        raise ValidationError(f"A {suffix} archive member exceeds {_limit(suffix) >> 20} MiB.")
                    inputs.append((item.filename, archive.read(item)))
    except (zipfile.BadZipFile, RuntimeError) as exc:
        raise ValidationError("Cannot read reference ZIP.") from exc
    return inputs


def _folder_files(source: Path) -> list[Path]:
    files = [path for path in sorted(source.rglob("*"))
             if path.is_file() and path.suffix.lower() in SOURCE_SUFFIXES and not path.is_symlink()]
    if sum(path.stat().st_size for path in files) > MAX_FOLDER:
        raise ValidationError(f"The folder holds more than {MAX_FOLDER >> 20} MiB of modules and archives.")
    return files


def _folder_digest(source: Path, files: list[Path]) -> str:
    listing = "".join(f"{path.relative_to(source).as_posix()}\0{_digest(path.read_bytes())}\n" for path in files)
    return _digest(listing.encode("utf-8"))


def _read_sources(source: Path) -> tuple[str, list[tuple[str, bytes]]]:
    """(source fingerprint, [(name, bytes)] of every .mod/.xm) of a module, a ZIP or a folder (recursive;
    its ZIPs are opened too). Names are the file or member names; they go to the private provenance only."""
    if source.is_dir():
        files = _folder_files(source)
        digest = _folder_digest(source, files)
        inputs = []
        for path in files:
            name = path.relative_to(source).as_posix()
            raw = path.read_bytes()
            if len(raw) > _limit(path.suffix):
                raise ValidationError(f"{path.suffix.lower()} file above the size limit in the folder.")
            if path.suffix.lower() == ".zip":
                inputs += [(f"{name}/{member}", payload) for member, payload in _zip_members(raw)]
            else:
                inputs.append((name, raw))
        if not inputs:
            raise ValidationError("No .mod or .xm references found.")
        if _folder_digest(source, _folder_files(source)) != digest:
            raise ValidationError("Source changed during extraction; no bank update was made.")
        return digest, inputs
    limit = _limit(source.suffix)
    if source.stat().st_size > limit:
        raise ValidationError("Reference input exceeds the analysis size limit.")
    original = source.read_bytes()
    if len(original) > limit:
        raise ValidationError("Reference input exceeds the analysis size limit.")
    if source.suffix.lower() == ".zip":
        inputs = _zip_members(original)
    else:
        inputs = [(source.name, original)]
    if not inputs:
        raise ValidationError("No .mod or .xm references found.")
    if source.read_bytes() != original:
        raise ValidationError("Source changed during extraction; no bank update was made.")
    return _digest(original), inputs


def _source_unchanged(source: Path, digest: str) -> bool:
    if source.is_dir():
        return _folder_digest(source, _folder_files(source)) == digest
    return _digest(source.read_bytes()) == digest


def _envelope_facts(item: dict) -> dict:
    """What an agent can use of an XM instrument, without copying it: does the volume envelope sustain, is
    there auto-vibrato, how long the fadeout is (0: none)."""
    envelope = item.get("volume_envelope") or {}
    return {"volume_envelope": bool(envelope.get("type", 0) & 1 and envelope.get("points")),
            "sustained": bool(envelope.get("type", 0) & 2 and envelope.get("points")),
            "vibrato": bool((item.get("vibrato") or {}).get("depth")), "fadeout": int(item.get("fadeout", 0))}


def _load_mod(filename: str, raw: bytes) -> dict:
    try:
        layout = parse_layout(raw)
    except ValueError as exc:
        raise ValidationError(str(exc), "MOD_LAYOUT") from exc
    module, error = None, None
    try:
        module = mod.decode(raw)
    except ValidationError as exc:
        error = exc.code or "MOD_FORMAT"
    cursor = 1084 + layout.pattern_bytes
    samples = []
    for slot, (words, tune, volume, start, length) in enumerate(layout.headers, 1):
        payload = raw[cursor:cursor + words * 2]
        cursor += words * 2
        if not payload:
            continue
        settings = {"pcm_sha256": _digest(payload), "loop_start": start * 2, "loop_length": length * 2 if length > 1 else 0,
                    "finetune": (tune & 15) - (16 if tune & 8 else 0), "volume": volume, "bits": 8,
                    "loop_mode": "forward", "panning": 128, "relative_note": 0}
        samples.append({"slot": slot, "index": 0, "payload": payload, "settings": settings, "played": True,
                        "original_name": raw[20 + (slot - 1) * 30:42 + (slot - 1) * 30].decode("latin1").rstrip("\0 "),
                        "original_header": list(layout.headers[slot - 1]), "xm_meta": {}, "envelope": None})
    return {"name": filename, "digest": _digest(raw), "format": "mod", "module": module, "decode_error": error,
            "title": raw[:20].decode("latin1").rstrip("\0 "), "samples": samples}


def _load_xm(filename: str, raw: bytes) -> dict:
    items = xm.read_samples(raw)
    module, error = None, None
    try:
        module = xm.decode(raw)
    except ValidationError as exc:
        error = exc.code or "XM_FORMAT"
    samples = []
    for item in items:
        if not item["pcm"]:
            continue
        payload = pcm_bytes(item["pcm"], item["bits"])
        looped = item["loop_mode"] != "none" and item["loop_length"] > 0
        settings = {"pcm_sha256": _digest(payload), "loop_start": item["loop_start"] if looped else 0,
                    "loop_length": item["loop_length"] if looped else 0, "finetune": item["finetune"],
                    "volume": item["volume"], "bits": item["bits"],
                    "loop_mode": item["loop_mode"] if looped else "forward", "panning": item["panning"],
                    "relative_note": item["relative_note"]}
        kept = module is not None and item["instrument"] <= len(module.samples) \
            and module.samples[item["instrument"] - 1].pcm == tuple(item["pcm"])
        samples.append({"slot": item["instrument"], "index": item["index"], "payload": payload, "settings": settings,
                        "played": kept, "original_name": item["name"],
                        "original_header": {key: item[key] for key in ("bits", "loop_start", "loop_length", "loop_mode",
                                                                       "volume", "finetune", "panning", "relative_note",
                                                                       "keymap_notes")},
                        "xm_meta": {key: item[key] for key in ("volume_envelope", "vibrato", "fadeout") if item.get(key)},
                        "envelope": _envelope_facts(item)})
    return {"name": filename, "digest": _digest(raw), "format": "xm", "module": module, "decode_error": error,
            "title": raw[17:37].decode("latin1").rstrip("\0 "), "samples": samples}


def _load_module(filename: str, raw: bytes) -> dict:
    """The samples of one module for the bank, and its decoded form (None, with the code, when the importer refuses
    it: the samples are still extracted, the roles then come from the PCM alone and there is no palette)."""
    formats.refuse_other_trackers(raw[:48])
    if formats.detect(raw) == "xm":
        return _load_xm(filename, raw)
    return _load_mod(filename, raw)


def _study(module: Module) -> dict | None:
    """`usage.study` on a decoded module; None when the study fails (the bank update does not depend on it)."""
    from .usage import study
    try:
        return study(module)
    except Exception:  # noqa: BLE001 - a reference that the study cannot follow still yields its samples
        return None


def _best_role(occurrences: list[dict]) -> dict | None:
    """The role with the most evidence among an entry's occurrences, and how many occurrences agree with it."""
    from .usage import CONFIDENCE_RANK
    scored = [item for item in occurrences if item.get("role")]
    if not scored:
        return None
    best = max(scored, key=lambda item: (CONFIDENCE_RANK.get(item.get("role_confidence"), 0),
                                         len(item.get("role_evidence") or []), item.get("note_starts", 0)))
    return {"role": best["role"], "role_confidence": best.get("role_confidence", "low"),
            "role_evidence": list(best.get("role_evidence") or [])[:8],
            "role_occurrences": sum(item["role"] == best["role"] for item in scored),
            "role_source": best.get("role_source", "song")}


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
        if not isinstance(value, dict) or value.get("schema") not in SCHEMAS:
            raise ValidationError("Unsupported sample library schema.")
        entries = value.get("samples")
        if not isinstance(entries, list) or len(entries) > MAX_ENTRIES:
            raise ValidationError("Invalid sample library entries.")
        from .usage import ROLE_NAMES
        seen = set()
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValidationError("Invalid sample entry.")
            for key, default in ENTRY_DEFAULTS.items():   # a v1 entry: an 8-bit MOD sample without a role
                entry.setdefault(key, copy.deepcopy(default))
            sample_id = entry.get("id")
            if not isinstance(sample_id, str) or not re.fullmatch(r"SMP-[0-9]{4,6}", sample_id) or sample_id in seen:
                raise ValidationError("Invalid or duplicate sample ID.")
            seen.add(sample_id)
            digest = entry.get("pcm_sha256")
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValidationError("Invalid PCM digest.")
            if entry["bits"] not in (8, 16) or entry["loop_mode"] not in ("forward", "pingpong") \
                    or entry["format_origin"] not in ("mod", "xm"):
                raise ValidationError("Invalid bits, loop_mode or format_origin.")
            if entry.get("pcm") != f"pcm/{digest}.pcm{'16' if entry['bits'] == 16 else ''}":
                raise ValidationError("Invalid PCM path; expected content-addressed local data.")
            ascii_field(entry.get("name"), 22, "Sample name")
            _tags(entry.get("tags"))
            if entry.get("category") not in CATEGORIES:
                raise ValidationError("Invalid sample category.")
            for key, maximum in (("bytes", MAX_PCM_BYTES), ("loop_start", MAX_FRAMES), ("loop_length", MAX_FRAMES),
                                 ("volume", 255), ("panning", 255), ("role_occurrences", MAX_ENTRIES * 64)):
                require_int(entry.get(key), key, 0, maximum)
            require_int(entry.get("finetune"), "finetune", *((-128, 127) if entry["format_origin"] == "xm" else (-8, 7)))
            require_int(entry["relative_note"], "relative_note", -96, 95)
            if entry["role"] is not None and (entry["role"] not in ROLE_NAMES
                                              or entry["role_confidence"] not in ("high", "medium", "low")
                                              or not isinstance(entry["role_evidence"], list)):
                raise ValidationError("Invalid sample role.")
            if entry["envelope"] is not None and not isinstance(entry["envelope"], dict):
                raise ValidationError("Invalid envelope facts.")
            if entry["retune"] is not None:
                check_retune(entry["retune"])
        value["schema"] = SCHEMA
        return value

    def _provenance(self) -> dict:
        path = self._path("private/provenance.json")
        provenance = project.read_json(path) if path.exists() else {
            "schema": PROVENANCE_SCHEMA, "sources": {}, "occurrences": {}, "palettes": {}}
        if (not isinstance(provenance, dict) or provenance.get("schema") != PROVENANCE_SCHEMA
                or not isinstance(provenance.get("sources"), dict) or not isinstance(provenance.get("occurrences"), dict)
                or not isinstance(provenance.setdefault("palettes", {}), dict)):
            raise ValidationError("Invalid private provenance file.")
        if any(not isinstance(item, dict) or not isinstance(item.get("entry_id"), str)
               for item in provenance["occurrences"].values()):
            raise ValidationError("Invalid private sample occurrences.")
        return provenance

    def _roles_from_pcm(self, manifest: dict) -> int:
        """Give every entry without a role one scored from its PCM alone (the module is not on disk)."""
        from .usage import sample_role
        count = 0
        for entry in manifest["samples"]:
            if entry.get("role"):
                continue
            role, confidence, evidence = sample_role(_sample(entry, self._pcm(entry)))
            entry.update(role=role, role_confidence=confidence, role_occurrences=0, role_source="pcm",
                         role_evidence=evidence[:7] + ["module unavailable: role from the PCM alone, no song evidence"])
            count += 1
        return count

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
            raise ValidationError(f"Unknown library sample: {sample_id}.", "SAMPLE_LIBRARY")
        result = copy.deepcopy(entry)
        result["compatibility"] = _compatibility(entry, self._pcm(entry))
        return result

    def search(self, query: str = "", tags: list[str] | None = None, category: str | None = None,
               compatible_only: bool = False, offset: int = 0, limit: int = 50, role: str | None = None,
               fmt: str | None = None) -> dict:
        from .usage import ROLE_NAMES
        require_int(offset, "offset", 0, MAX_ENTRIES)
        require_int(limit, "limit", 1, 500)
        wanted = set(_tags(tags or []))
        if category is not None and category not in CATEGORIES:
            raise ValidationError("Unknown category.")
        if role is not None and role not in ROLE_NAMES:
            raise ValidationError(f"Unknown role; expected one of {', '.join(sorted(ROLE_NAMES))}.")
        if fmt is not None and fmt not in ("mod", "xm"):
            raise ValidationError("format: mod or xm expected.")
        results = []
        for item in self._manifest()["samples"]:
            if category and item["category"] != category or not wanted.issubset(item["tags"]):
                continue
            if role and item["role"] != role or fmt and item["format_origin"] != fmt:
                continue
            text = " ".join([item["id"], item["name"], item["category"], item["role"] or "", *item["tags"]]).casefold()
            if not all(word in text for word in query.casefold().split()):
                continue
            raw = self._pcm(item)
            compatible = _compatibility(item, raw)["compatible"]
            if compatible_only and not compatible:
                continue
            summary = {key: copy.deepcopy(item[key]) for key in
                       ("id", "name", "category", "tags", "bytes", "volume", "finetune", "loop_start", "loop_length",
                        "bits", "loop_mode", "relative_note", "format_origin", "role", "role_confidence")}
            summary["compatible"] = compatible
            summary["retune"] = copy.deepcopy(item.get("retune"))   # the owner's tuning correction, shown in lists
            results.append((summary, raw))
        page = results[offset:offset + limit]
        for summary, raw in page:
            summary["pitch"] = _pitch_summary(_sample(summary, raw), summary["format_origin"])
        return {"ok": True, "total": len(results), "offset": offset,
                "samples": [summary for summary, _ in page],
                "pitch_note": "pitch: estimated fundamental at C-2 (XM samples: at C-4) for loops up to "
                              f"{MAX_CYCLE_LOOP} frames (null otherwise; samples inspect also estimates one-shots). "
                              "A measurement, not a listening judgment.",
                "role_note": "role: scored from how a reference song plays the sample and from its sound "
                             "(role_evidence lists why); a suggestion to confirm by listening."}

    def extract(self, source: Path) -> dict:
        """Add every sample of a MOD, an XM, a ZIP or a folder (recursive) to the bank, with its role, and
        remember each readable module as a palette. Modules the importer refuses are counted by code (a single
        refused file is an error); the other modules of a ZIP or folder are imported."""
        from .sample_palettes import build_palette, read_palettes, write_palettes
        source = Path(source).resolve()
        if source.is_relative_to(self.path):
            raise ValidationError("Reference source must be outside the sample bank.")
        source_digest, inputs = _read_sources(source)
        # Read every module before writing any bank data; a refusal is counted, not partial.
        modules, refused, errors = [], Counter(), []
        for filename, raw in inputs:
            try:
                modules.append(_load_module(filename, raw))
            except ValidationError as exc:
                refused[exc.code or "INVALID"] += 1
                errors.append(exc)
        if not modules:
            raise errors[0]
        studies = {}
        for index, item in enumerate(modules):
            if item["module"] is not None:
                studies[index] = _study(item["module"])
        with self._writer():
            manifest = self._manifest(create=True)
            provenance = self._provenance()
            palettes = read_palettes(self.path) if self._path("palettes.json").exists() else []
            known = {tuple(entry[key] for key in SETTINGS): entry for entry in manifest["samples"]}
            # Verify existing PCM before updating an existing bank, and refresh the stored compatibility
            # (an older bank's entries lack its `adapt` list).
            for entry in manifest["samples"]:
                entry["compatibility"] = _compatibility(entry, self._pcm(entry))
            next_id = max((int(entry["id"][4:]) for entry in manifest["samples"]), default=0) + 1
            start_count = len(manifest["samples"])
            payloads: dict[tuple[str, int], bytes] = {}
            slots = 0
            provenance["sources"][source_digest] = {"filename": source.name, "modules": len(modules),
                                                    "refused": dict(refused)}
            by_module = {}   # palette id -> (module item, study, {slot: [entry ids]}, {entry id: occurrence})
            for module_index, item in enumerate(modules):
                study = studies.get(module_index)
                slot_roles = {slot["slot"]: slot for slot in (study or {}).get("slots", [])}
                entry_ids: dict[int, list[str]] = {}
                occurrences: dict[str, dict] = {}
                for found in item["samples"]:
                    slots += 1
                    settings, payload = found["settings"], found["payload"]
                    key = tuple(settings[field] for field in SETTINGS)
                    entry = known.get(key)
                    if entry is None:
                        if len(manifest["samples"]) >= MAX_ENTRIES:
                            raise ValidationError("Sample library entry limit exceeded.")
                        metrics, category, prefix, tags = characterize(
                            high_bytes(payload, settings["bits"]), settings["loop_start"], settings["loop_length"])
                        # The sample's own name (a label only, never read as an instruction), else a neutral one.
                        entry = {"id": f"SMP-{next_id:04d}",
                                 "name": clean_name(found["original_name"]) or f"{prefix} {next_id:02d}", **settings,
                                 "pcm": f"pcm/{settings['pcm_sha256']}.pcm{'16' if settings['bits'] == 16 else ''}",
                                 "bytes": len(payload), "category": category, "tags": tags, "metrics": metrics,
                                 "origin": "module-extracted", "classification": "heuristic-v1",
                                 "format_origin": item["format"], "envelope": found["envelope"],
                                 "source": {"file": item["name"], "slot": found["slot"],
                                            "name": clean_name(found["original_name"])},
                                 **{key: copy.deepcopy(ENTRY_DEFAULTS[key]) for key in
                                    ("role", "role_confidence", "role_evidence", "role_occurrences", "role_source")}}
                        entry["compatibility"] = _compatibility(entry, payload)
                        manifest["samples"].append(entry)
                        known[key] = entry
                        next_id += 1
                    elif entry["envelope"] is None and found["envelope"]:
                        entry["envelope"] = found["envelope"]
                    payloads[settings["pcm_sha256"], settings["bits"]] = payload
                    occurrence = {
                        "entry_id": entry["id"], "module_sha256": item["digest"], "filename": item["name"],
                        "module_title": item["title"], "format": item["format"], "slot": found["slot"],
                        "sample_index": found["index"], "original_name": found["original_name"],
                        "original_header": found["original_header"], "archive_sha256": source_digest,
                        "role": None, "role_confidence": None, "role_evidence": [], "role_source": None,
                        "note_starts": 0}
                    scored = slot_roles.get(found["slot"]) if found["played"] else None
                    if scored is not None:
                        occurrence.update(role=scored["role"], role_confidence=scored["confidence"],
                                          role_evidence=scored["evidence"][:8], note_starts=scored["note_starts"],
                                          role_source="song" if scored["note_starts"] else "sound")
                    else:
                        from .usage import sample_role
                        role, confidence, evidence = sample_role(_sample(entry, payload), found["xm_meta"],
                                                                 found["original_name"])
                        why = ("dropped from a multi-sample instrument: role from its sound and instrument only"
                               if not found["played"] else
                               f"module not decoded ({item['decode_error'] or 'no study'}): role from the sound alone")
                        occurrence.update(role=role, role_confidence=confidence, role_evidence=evidence[:7] + [why],
                                          role_source="sound")
                    # The same key as earlier banks for a MOD slot, so a re-extraction of a source updates it.
                    key = f"{source_digest}:{module_index}:{found['slot']}"
                    occurrences[key if item["format"] == "mod" else f"{key}:{found['index']}"] = occurrence
                    entry_ids.setdefault(found["slot"], []).append((entry["id"], found["played"]))
                provenance["occurrences"].update(occurrences)
                if study is not None:
                    by_module[item["digest"]] = (item, study, entry_ids, occurrences)
            if not _source_unchanged(source, source_digest):
                raise ValidationError("Source changed during extraction; bank manifest was not updated.")
            for (digest, bits), payload in payloads.items():
                destination = self._path(f"pcm/{digest}.pcm{'16' if bits == 16 else ''}")
                if destination.exists():
                    if destination.read_bytes() != payload:
                        raise ValidationError("Existing PCM differs from its content digest.")
                else:
                    project.atomic_bytes(destination, payload)
            # Roles: the best-evidenced occurrence of each entry; the PCM alone for entries without one.
            per_entry: dict[str, list[dict]] = {}
            for occurrence in provenance["occurrences"].values():
                per_entry.setdefault(occurrence["entry_id"], []).append(occurrence)
            for entry in manifest["samples"]:
                entry["source_occurrences"] = len(per_entry.get(entry["id"], []))
                best = _best_role(per_entry.get(entry["id"], []))
                if best is not None:
                    entry.update(best)
            pcm_roles = self._roles_from_pcm(manifest)
            # Palettes: one per decoded module, its ID kept across re-extractions of the same module.
            by_digest = {info["module_sha256"]: palette_id for palette_id, info in provenance["palettes"].items()
                         if isinstance(info, dict)}
            next_palette = max((int(key[4:]) for key in provenance["palettes"]), default=0) + 1
            new_palettes = 0
            for digest, (item, study, entry_ids, occurrences) in by_module.items():
                palette_id = by_digest.get(digest)
                if palette_id is None:
                    palette_id, next_palette = f"PAL-{next_palette:04d}", next_palette + 1
                    new_palettes += 1
                provenance["palettes"][palette_id] = {"module_sha256": digest, "filename": item["name"],
                                                      "module_title": item["title"], "archive_sha256": source_digest}
                palette = build_palette(palette_id, item["module"], study, entry_ids, occurrences)
                palettes = [existing for existing in palettes if existing["id"] != palette_id] + [palette]
            palettes.sort(key=lambda palette: palette["id"])
            project.atomic_bytes(self._path(".gitignore"), b"*\n!.gitignore\n")
            project.write_json(self._path("private/provenance.json"), provenance)
            write_palettes(self.path, palettes)
            project.write_json(self._path("library.json"), manifest)
        new_entries = manifest["samples"][start_count:]
        return {"ok": True, "library": str(self.path), "modules": len(modules), "refused": dict(refused),
                "sample_slots": slots, "new_entries": len(new_entries), "entries": len(manifest["samples"]),
                "unique_pcm": len({item["pcm_sha256"] for item in manifest["samples"]}),
                "roles": dict(Counter(entry["role"] for entry in new_entries)),
                "roles_from_pcm_alone": pcm_roles, "palettes_new": new_palettes, "palettes": len(palettes),
                "modules_without_palette": len(modules) - len(by_module), "source_unchanged": True}

    def create(self) -> dict:
        """Start an empty bank in a new or empty directory."""
        with self._writer():
            if self._path("library.json").exists():
                raise ValidationError("This folder already holds a sample bank.", "SAMPLE_LIBRARY")
            manifest = self._manifest(create=True)
            project.atomic_bytes(self._path(".gitignore"), b"*\n!.gitignore\n")
            project.write_json(self._path("library.json"), manifest)
        return {"ok": True, "library": str(self.path), "entries": 0}

    def add_entry(self, sample: Sample, fmt: str = "mod", name: str | None = None, role: str | None = None,
                  category: str | None = None, tags: list[str] | None = None, origin: str = "module-added",
                  source: dict | None = None, envelope: dict | None = None, xm_meta: dict | None = None,
                  role_scored: tuple[str, str, list[str]] | None = None) -> dict:
        """Add one sample with the name, role, category and tags the owner chose. A sample already in the bank
        (same PCM and playback settings) is not added twice: the result names the existing entry. Without a
        role, `role_scored` (from the song) or the sound alone (`usage.sample_role`) gives one."""
        from .usage import ROLE_NAMES, sample_role
        if fmt not in ("mod", "xm"):
            raise ValidationError("format: mod or xm expected.")
        xm.validate_xm_sample(sample, 1) if fmt == "xm" else validate_sample(sample, 1)
        if not sample.pcm:
            raise ValidationError("An empty sample cannot enter the bank.", "SAMPLE_LIBRARY")
        if role is not None and role not in ROLE_NAMES:
            raise ValidationError(f"Unknown role; expected one of {', '.join(sorted(ROLE_NAMES))}.")
        if category is not None and category not in CATEGORIES:
            raise ValidationError("Unknown category.")
        if name is not None:
            ascii_field(name, 22, "Sample name")
            name = name.strip() or None
        payload = pcm_bytes(sample.pcm, sample.bits)
        looped = bool(sample.loop_length)
        settings = {"pcm_sha256": _digest(payload), "loop_start": sample.loop_start if looped else 0,
                    "loop_length": sample.loop_length if looped else 0, "finetune": sample.finetune,
                    "volume": sample.volume, "bits": sample.bits,
                    "loop_mode": sample.loop_mode if looped else "forward", "panning": sample.panning,
                    "relative_note": sample.relative_note}
        with self._writer():
            manifest = self._manifest(create=True)
            key = tuple(settings[field] for field in SETTINGS)
            existing = next((entry for entry in manifest["samples"]
                             if tuple(entry[field] for field in SETTINGS) == key), None)
            if existing is not None:
                return {"ok": True, "created": False, "library": str(self.path), "id": existing["id"],
                        "entry": copy.deepcopy(existing),
                        "note": "This sample is already in the bank (same PCM and playback settings)."}
            if len(manifest["samples"]) >= MAX_ENTRIES:
                raise ValidationError("Sample library entry limit exceeded.")
            next_id = max((int(entry["id"][4:]) for entry in manifest["samples"]), default=0) + 1
            metrics, measured_category, prefix, measured_tags = characterize(
                high_bytes(payload, sample.bits), settings["loop_start"], settings["loop_length"])
            if role is not None:
                role_fields = {"role": role, "role_confidence": "high", "role_evidence": ["chosen by the owner"],
                               "role_occurrences": 1, "role_source": "owner"}
            else:
                scored = role_scored or sample_role(sample, xm_meta, (source or {}).get("name"))
                role_fields = {"role": scored[0], "role_confidence": scored[1], "role_evidence": list(scored[2])[:8],
                               "role_occurrences": 1, "role_source": "song" if role_scored else "sound"}
            entry = {"id": f"SMP-{next_id:04d}", "name": name or f"{prefix} {next_id:02d}", **settings,
                     "pcm": f"pcm/{settings['pcm_sha256']}.pcm{'16' if sample.bits == 16 else ''}",
                     "bytes": len(payload), "category": category or measured_category,
                     "tags": _tags(list(tags or []) + measured_tags), "metrics": metrics, "origin": origin,
                     "classification": "user-added", "format_origin": fmt, "envelope": envelope,
                     "source": source, **role_fields, "source_occurrences": 1}
            entry["compatibility"] = _compatibility(entry, payload)
            destination = self._path(entry["pcm"])
            if destination.exists():
                if destination.read_bytes() != payload:
                    raise ValidationError("Existing PCM differs from its content digest.")
            else:
                project.atomic_bytes(destination, payload)
            manifest["samples"].append(entry)
            project.atomic_bytes(self._path(".gitignore"), b"*\n!.gitignore\n")
            project.write_json(self._path("library.json"), manifest)
        return {"ok": True, "created": True, "library": str(self.path), "id": entry["id"], "entry": copy.deepcopy(entry)}

    def edit(self, sample_id: str, name: str | None = None, category: str | None = None,
             tags: list[str] | None = None, role: str | None = None, retune: dict | None = None) -> dict:
        with self._writer():
            manifest = self._manifest()
            entry = next((item for item in manifest["samples"] if item["id"] == sample_id), None)
            if entry is None:
                raise ValidationError(f"Unknown library sample: {sample_id}.", "SAMPLE_LIBRARY")
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
            if role is not None:
                from .usage import ROLE_NAMES
                if role not in ROLE_NAMES:
                    raise ValidationError(f"Unknown role; expected one of {', '.join(sorted(ROLE_NAMES))}.")
                entry.update(role=role, role_confidence="high", role_evidence=["chosen by the owner"],
                             role_source="owner")
            if retune is not None:   # {semitones: 0, cents: 0} clears it
                check_retune(retune)
                entry["retune"] = retune if retune["semitones"] or retune["cents"] else None
            entry["classification"] = "user-edited"
            project.write_json(self._path("library.json"), manifest)
        return self.get(sample_id)

    def inspect(self, sample_id: str) -> dict:
        """The entry with its compatibility and an estimated pitch at C-2 (XM: C-4; see `estimate_pitch`)."""
        entry = self.get(sample_id)
        entry["pitch"] = estimate_pitch(_sample(entry, self._pcm(entry)), entry["format_origin"])
        return entry

    def read_sample(self, sample_id: str) -> Sample:
        """Verified stored PCM for inspection; it may be outside the MOD profile."""
        entry = self.get(sample_id)
        return _sample(entry, self._pcm(entry))

    def sample(self, sample_id: str, adapt: bool = False, fmt: str = "mod") -> tuple[Sample, list[str]]:
        """The library sample ready for a module of format `fmt`, with what `adapt` changed.

        Into an XM: an XM-origin sample stays native (bits, loop mode, panning, relative note, finetune); a
        MOD-origin one is converted exactly like `convert` converts a MOD sample (`convert.mod_sample_to_xm`).
        Into a MOD: a sample outside the MOD profile (16-bit, ping-pong, panned, XM tuning, odd length, one-shot
        head) is refused unless `adapt`, which applies `adapt_for_mod` on a copy; the bank PCM is untouched."""
        entry = self.get(sample_id)
        sample = _sample(entry, self._pcm(entry))
        if fmt == "xm":
            if entry["format_origin"] == "xm":
                return sample, []
            changes = []
            if adapt and not sample.loop_length and any(sample.pcm[:2]):
                sample.pcm = (0, 0) + sample.pcm
                changes.append("prepend-two-zero-bytes")
            from .convert import mod_sample_to_xm
            return mod_sample_to_xm(sample), changes
        if adapt:
            sample, changes = adapt_for_mod(sample)
        else:
            changes = []
        try:
            validate_sample(sample)
        except ValueError as exc:
            hint = ""
            if not adapt:
                try:
                    hint = f" Pass adapt (CLI: --adapt) to apply: {', '.join(mod_adaptations(sample))}."
                except ValidationError as why:
                    hint = f" It cannot be adapted: {why}"
            raise ValidationError(f"{sample_id} is incompatible with the current MOD profile: {exc}{hint}",
                                  "SAMPLE_INCOMPATIBLE") from exc
        return sample, changes

    def insert(self, module: Module, sample_id: str, slot: int | None = None,
               replace: bool = False, adapt: bool = False) -> tuple[Module, dict]:
        validate(module)
        sample_source.guard_insert(module, "library")
        xm = module.format == "xm"
        entry = self.get(sample_id)
        sample, changes = self.sample(sample_id, adapt, module.format)
        sample, retuned = apply_retune(sample, entry.get("retune"), module.format)
        result = copy.deepcopy(module)
        used = {value.sample for pattern in result.patterns for value in pattern.cells.values() if value.sample}
        if slot is None:
            slot = next((index for index, item in enumerate(result.samples, 1)
                         if not item.pcm and index not in used), len(result.samples) + 1)
        require_int(slot, "slot", 1, 128 if xm else 31, "SAMPLE_SLOT")
        if slot > len(result.samples) + 1:
            raise ValidationError("Choose an existing slot or the next slot; gaps are not inserted.", "SAMPLE_SLOT")
        if slot <= len(result.samples):
            if result.samples[slot - 1].pcm and not replace:
                raise ValidationError(f"Sample slot {slot} is occupied; pass replace (CLI: --replace) to overwrite it.",
                                      "SAMPLE_SLOT")
            result.samples[slot - 1] = sample
        else:
            result.samples.append(sample)
        info = {"library_id": sample_id, "origin": entry.get("origin", "module-extracted"), "adaptations": changes}
        if retuned:
            info["retune"] = retuned
        if entry.get("role"):
            info["role"] = entry["role"]
        sources = result.metadata.setdefault("sample_sources", {})
        if not isinstance(sources, dict):
            raise ValidationError("Project metadata.sample_sources must be an object.")
        sources[str(slot)] = info
        validate(result)
        if xm:  # what the conversion did, for the caller (not stored: the library ID is the provenance)
            native = entry["format_origin"] == "xm"
            return result, {"slot": slot, **info, "xm": {
                "native": native, "bits": sample.bits, "loop_mode": sample.loop_mode,
                "finetune": sample.finetune, "relative_note": sample.relative_note,
                "note": "Kept as the XM reference stored it: bits, loop mode, panning, relative note, finetune."
                        if native else
                        "Converted like `convert` converts a MOD sample: finetune 16 x MOD finetune - 20, "
                        "8-bit, forward loop, centred. Play it at XM C-4 for the MOD's C-2."}}
        return result, {"slot": slot, **info}

    def audition(self, sample_id: str, output: Path, note: str = "C-2", seconds: float = 1.0) -> dict:
        """Raw sample audition: no tracker effects; not a claimed original pitch."""
        from .audio import audition_sample
        from .synth_tools import check_preview_note
        check_preview_note(note)
        if note not in NOTE_TO_PERIOD or not math.isfinite(seconds) or not .05 <= seconds <= 5:
            raise ValidationError("Audition requires a tracker note C-1..B-3 and 0.05–5 seconds.")
        output = Path(output).resolve()
        if output.suffix.lower() != ".wav" or output.is_relative_to(self.path):
            raise ValidationError("Audition output must be a WAV outside the sample bank.")
        from . import loudness
        from .synth_tools import audition_measurements
        entry = self.get(sample_id)
        require_int(entry["volume"], "volume", 0, 64)
        sample = _sample(entry, self._pcm(entry))
        origin = entry["format_origin"]
        # An XM sample is played so that tracker note C-2 sounds like the XM's C-4 (its own rate).
        rate = xm_c4_rate(sample) if origin == "xm" else None
        result = audition_sample(sample, output, note, seconds, rate)
        pitch = estimate_pitch(sample, origin)
        pitch["at_preview_note"] = pitch_at_note(pitch, note)
        facts = {"bytes": len(sample.pcm) * sample.bits // 8, "frames": len(sample.pcm), "bits": sample.bits,
                 "looped": bool(sample.loop_length), "loop_start": sample.loop_start,
                 "loop_length": sample.loop_length, "loop_mode": sample.loop_mode if sample.loop_length else None,
                 "pcm_peak": max(map(abs, sample.pcm), default=0)}
        return {"ok": True, "id": sample_id, **result, "volume": sample.volume, "finetune": sample.finetune,
                "format_origin": origin, "sample": facts,
                **audition_measurements(sample, output, None, loudness.library_group(entry)), "pitch": pitch}

    def _palettes(self) -> list[dict]:
        from .sample_palettes import read_palettes
        self._manifest()
        if not self._path("palettes.json").exists():
            return []
        return read_palettes(self.path)

    def palettes(self, role: str | None = None, fmt: str | None = None, channels: int | None = None) -> dict:
        """The palettes (reference songs' sample sets) with a one-line role summary each."""
        from .sample_palettes import list_palettes
        return list_palettes(self._palettes(), role, fmt, channels)

    def palette(self, palette_id: str) -> dict:
        from .sample_palettes import find_palette
        return copy.deepcopy(find_palette(self._palettes(), palette_id))

    def use_palette(self, palette_id: str, module: Module, slots: list[int] | None = None, adapt: bool = False,
                    include_unplayed: bool = False, retune: bool = False) -> tuple[Module, dict]:
        """Insert a palette's entries into a library-mode project in role order (see `sample_palettes.use_palette`),
        with a measured `tuning` check of its pitched entries; `retune` aligns them in an XM."""
        from . import sample_intake
        from .sample_palettes import find_palette, use_palette
        palette = find_palette(self._palettes(), palette_id)
        result, info = use_palette(self, palette, module, slots, adapt, include_unplayed)
        info["tuning"] = sample_intake.palette_tuning(self, palette)
        if retune:
            info["retuned"] = sample_intake.retune(result, info["slot_map"], info["tuning"])
            validate(result)
        return result, info

    def audit(self) -> dict:
        entries = self._manifest()["samples"]
        compatible, categories, roles, confidences = 0, Counter(), Counter(), Counter()
        bits, loops, origins, sources = Counter(), Counter(), Counter(), Counter()
        for entry in entries:
            raw = self._pcm(entry)
            compatible += _compatibility(entry, raw)["compatible"]
            categories[entry["category"]] += 1
            roles[entry["role"] or "none"] += 1
            confidences[entry["role_confidence"] or "none"] += 1
            bits[str(entry["bits"])] += 1
            loops[entry["loop_mode"] if entry["loop_length"] else "one-shot"] += 1
            origins[entry["format_origin"]] += 1
            sources[entry["role_source"] or "none"] += 1
        palettes = self._path("palettes.json")
        count = 0
        if palettes.exists():
            from .sample_palettes import read_palettes
            count = len(read_palettes(self.path))
        return {"ok": True, "entries": len(entries),
                "unique_pcm": len({entry["pcm_sha256"] for entry in entries}),
                "source_occurrences": sum(entry.get("source_occurrences", 0) for entry in entries),
                "compatible_entries": compatible, "incompatible_entries": len(entries) - compatible,
                "categories": dict(categories), "roles": dict(roles), "role_confidence": dict(confidences),
                "role_source": dict(sources), "bits": dict(bits), "loop_mode": dict(loops),
                "format_origin": dict(origins), "palettes": count, "classification_note":
                "Heuristic labels are editable; roles are evidence-based suggestions; no human listening "
                "validation is implied."}
