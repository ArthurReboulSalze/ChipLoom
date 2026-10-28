"""Deterministic PCM recipes; JSON supplies data, never executable expressions."""

from __future__ import annotations

import math
import random

from .model import SAMPLE_RATE, Sample, ValidationError, require_int


RECIPE_TYPES = ("wave", "draw", "kick", "snare", "hat", "kick_hat", "snare_hat", "pluck")


def number(value: object, name: str, minimum: float, maximum: float) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValidationError(f"{name}: expected a finite number in [{minimum}, {maximum}], got {value!r}.",
                              "RECIPE_INVALID")
    return float(value)


def quantize(values: list[float], peak: float, looped: bool) -> tuple[int, ...]:
    mean = sum(values) / len(values)
    centered = [value - mean for value in values]
    maximum = max(abs(value) for value in centered)
    if maximum < 1e-12:
        raise ValidationError("The recipe produces a silent sample.", "RECIPE_INVALID")
    if not looped:
        # The two zero bytes also provide the harmless ProTracker no-loop word.
        for index in range(min(16, len(centered) // 2)):
            centered[index] *= index / 16
            centered[-index - 1] *= index / 16
    pcm = [round(value / maximum * peak * 127) for value in centered]
    if not looped:
        pcm[0:2] = [0, 0]
        pcm[-2:] = [0, 0]
    return tuple(pcm)


def _drive(values: list[float], amount: float) -> list[float]:
    """Soft saturation: loud hits and their tails move closer in level, so the sample sounds denser."""
    if not amount:
        return values
    scale = max(abs(value) for value in values) or 1.0
    gain = 1 + 9 * amount
    return [math.tanh(gain * value / scale) / math.tanh(gain) for value in values]


def from_recipe(name: str, recipe: dict, volume: int = 40, finetune: int = 0) -> Sample:
    if not isinstance(recipe, dict):
        raise ValidationError("A sample recipe must be a JSON object such as {\"type\": \"kick\"}.", "RECIPE_INVALID")
    kind = recipe.get("type")
    if kind == "wave":
        return _wave_sample(name, recipe, volume, finetune)
    allowed = {"type", "seed", "peak", "duration", "frequency", "cycles", "points", "duty", "drive"}
    extra = set(recipe) - allowed
    if extra:
        raise ValidationError(f"Unknown recipe parameters {sorted(extra)} for type {kind!r}; allowed: {sorted(allowed)}.",
                              "RECIPE_INVALID")
    peak = number(recipe.get("peak", 0.88), "peak", 0.01, 1)
    seed = require_int(recipe.get("seed", 0), "seed", 0, 2**32 - 1)
    rng = random.Random(seed)
    looped = kind == "draw"
    if looped:
        if "drive" in recipe:
            raise ValidationError("drive only applies to one-shot recipes (drums and pluck).", "RECIPE_INVALID")
        points = recipe.get("points")
        if not isinstance(points, list) or not 4 <= len(points) <= 256:
            raise ValidationError("A drawn wave needs a list of 4 to 256 points.", "RECIPE_INVALID")
        points = [number(value, "point", -1, 1) for value in points]
        cycles = require_int(recipe.get("cycles", 16), "cycles", 1, 64)
        frequency = number(recipe.get("frequency", 261.625565), "frequency", 30, 2000)
        frames = round(SAMPLE_RATE * cycles / frequency / 2) * 2
        if not 4 <= frames <= 65_534:
            raise ValidationError("The drawn wave would be longer than 65534 bytes; use fewer cycles or a higher "
                                  "frequency.", "RECIPE_INVALID")
        values = []
        for index in range(frames):
            position = (index * cycles / frames % 1) * len(points)
            left = int(position)
            blend = position - left
            values.append(points[left] * (1 - blend) + points[(left + 1) % len(points)] * blend)
    elif kind in {"kick", "snare", "hat", "kick_hat", "snare_hat", "pluck"}:
        default_duration = {"kick": 0.24, "snare": 0.19, "hat": 0.048,
                            "kick_hat": 0.24, "snare_hat": 0.19, "pluck": 0.36}[kind]
        duration = number(recipe.get("duration", default_duration), "duration", 0.01, 1.5)
        frames = max(4, round(duration * SAMPLE_RATE / 2) * 2)
        frequency = number(recipe.get("frequency", 261.625565), "frequency", 30, 2000)
        duty = number(recipe.get("duty", 0.32), "duty", 0.1, 0.9)
        phase = 0.0
        previous_noise = 0.0
        values = []
        for index in range(frames):
            time = index / SAMPLE_RATE
            noise = rng.uniform(-1, 1)
            high_noise = noise - previous_noise * 0.85
            previous_noise = noise
            hat = (high_noise * 0.7 + math.sin(math.tau * 3187 * time) * 0.13
                   + math.sin(math.tau * 2411 * time) * 0.11) * math.exp(-time / 0.010)
            if kind in {"kick", "kick_hat"}:
                phase += math.tau * (48 + 137 * math.exp(-time / 0.014)) / SAMPLE_RATE
                sound = math.sin(phase) * math.exp(-time / 0.057)
                sound += noise * 0.10 * math.exp(-time / 0.002)
                if kind == "kick_hat":
                    sound += hat * 0.30
            elif kind in {"snare", "snare_hat"}:
                sound = high_noise * math.exp(-time / 0.037) * 0.75
                sound += (math.sin(math.tau * 185 * time) * 0.37
                          + math.sin(math.tau * 329 * time) * 0.16) * math.exp(-time / 0.033)
                if kind == "snare_hat":
                    sound += hat * 0.18
            elif kind == "hat":
                sound = hat
            else:
                # A short baked envelope. No external synthesizer is needed to play the MOD.
                phase = math.tau * frequency * time
                harmonic_limit = min(9, int(SAMPLE_RATE / 2 / frequency))
                sound = sum(
                    math.sin(math.pi * harmonic * duty) / harmonic
                    * math.sin(phase * harmonic)
                    for harmonic in range(1, harmonic_limit + 1)
                )
                sound *= (1 - math.exp(-time / 0.0015)) * math.exp(-time / 0.085)
            values.append(sound)
        if "drive" in recipe:
            values = _drive(values, number(recipe["drive"], "drive", 0, 1))
    else:
        raise ValidationError(f"Unknown recipe type {kind!r}; use one of {list(RECIPE_TYPES)}.", "RECIPE_INVALID")
    pcm = quantize(values, peak, looped)
    return Sample(name, pcm, volume, finetune, 0, len(pcm) if looped else 0, dict(recipe))


# --- looped waves ------------------------------------------------------------------------

DEFAULT_FREQUENCY = 261.625565
WAVE_SHAPES = ("pulse", "triangle", "saw", "sine", "noise")
AUTO_TUNING_CENTS = 2.0
_WAVE_COMMON = {"type", "shape", "peak"}
_WAVE_ALLOWED = {
    "pulse": _WAVE_COMMON | {"frequency", "cycles", "duty"},
    "triangle": _WAVE_COMMON | {"frequency", "cycles"},
    "saw": _WAVE_COMMON | {"frequency", "cycles"},
    "sine": _WAVE_COMMON | {"frequency", "cycles"},
    "noise": _WAVE_COMMON | {"seed", "length", "smooth", "binary"},
}


def _bad(message: str) -> ValidationError:
    return ValidationError(message, "RECIPE_INVALID")


def _wave_number(recipe: dict, name: str, default: float | None, minimum: float, maximum: float) -> float:
    value = recipe.get(name, default)
    if type(value) not in (int, float) or not math.isfinite(value) or not minimum <= value <= maximum:
        raise _bad(f"Wave recipe: {name} must be a finite number in [{minimum}, {maximum}], got {value!r}.")
    return float(value)


def _wave_integer(recipe: dict, name: str, default: int, minimum: int, maximum: int) -> int:
    value = recipe.get(name, default)
    if type(value) is not int or not minimum <= value <= maximum:
        raise _bad(f"Wave recipe: {name} must be an integer in [{minimum}, {maximum}], got {value!r}.")
    return value


def heard_frequency(cycles: int, frames: int) -> float:
    """Pitch in Hz heard when a looped sample of `frames` bytes holding `cycles` cycles plays at C-2."""
    return SAMPLE_RATE * cycles / frames


def cents(actual: float, wanted: float) -> float:
    return 1200 * math.log2(actual / wanted)


def wave_geometry(frequency: float, cycles: int | None) -> tuple[int, int]:
    """(cycles, bytes) for a tuned loop. Without `cycles`, the fewest cycles within 2 cents (else the best)."""
    best = None
    for count in ([cycles] if cycles is not None else range(1, 65)):
        frames = round(SAMPLE_RATE * count / frequency / 2) * 2
        if not 4 <= frames <= 65_534 or frames < 2 * count:
            continue
        error = abs(cents(heard_frequency(count, frames), frequency))
        if cycles is None and error <= AUTO_TUNING_CENTS:
            return count, frames
        if best is None or error < best[0]:
            best = (error, count, frames)
    if best is None:
        raise _bad(f"Wave recipe: {frequency} Hz with {cycles} cycle(s) needs a loop outside 4-65534 bytes "
                   "or fewer than 2 bytes per cycle; change frequency or cycles.")
    return best[1], best[2]


def _pulse_integral(position: float, duty: float) -> float:
    whole = math.floor(position)
    phase = position - whole
    return whole * (2 * duty - 1) + (phase if phase < duty else 2 * duty - phase)


def _saw_integral(position: float) -> float:
    phase = position - math.floor(position)
    return phase * phase - phase


def _wave_cycle_values(shape: str, frames: int, cycles: int, duty: float) -> list[float]:
    """One value per byte. Pulse and saw average each byte's time slot, which keeps hard edges to one byte."""
    values = []
    step = cycles / frames
    for index in range(frames):
        start, end = index * step, (index + 1) * step
        if shape == "pulse":
            values.append((_pulse_integral(end, duty) - _pulse_integral(start, duty)) / step)
        elif shape == "saw":
            values.append((_saw_integral(end) - _saw_integral(start)) / step)
        elif shape == "sine":
            values.append(math.sin(math.tau * start))
        else:
            phase = start - math.floor(start)
            values.append(4 * phase if phase < 0.25 else 2 - 4 * phase if phase < 0.75 else 4 * phase - 4)
    return values


def _noise_values(recipe: dict) -> list[float]:
    length = _wave_integer(recipe, "length", 2048, 64, 65_534)
    if length % 2:
        raise _bad(f"Wave recipe: length must be even, got {length}.")
    smooth = _wave_number(recipe, "smooth", 0, 0, 0.95)
    binary = recipe.get("binary", False)
    if type(binary) is not bool:
        raise _bad(f"Wave recipe: binary must be true or false, got {binary!r}.")
    if binary and smooth:
        raise _bad("Wave recipe: binary noise cannot be smoothed; remove smooth or binary.")
    seed = _wave_integer(recipe, "seed", 0, 0, 2**32 - 1)
    rng = random.Random(seed)
    values = [rng.uniform(-1, 1) for _ in range(length)]
    if binary:
        return [1.0 if value >= 0 else -1.0 for value in values]
    if smooth:
        # A one-pole low-pass run around the loop several times, so the seam is as smooth as the rest.
        state = 0.0
        for _ in range(4):
            for index, value in enumerate(values):
                state += (1 - smooth) * (value - state)
                values[index] = state
    return values


def _wave_sample(name: str, recipe: dict, volume: int, finetune: int) -> Sample:
    shape = recipe.get("shape")
    if shape not in WAVE_SHAPES:
        raise _bad(f"Wave recipe: shape must be one of {list(WAVE_SHAPES)}, got {shape!r}.")
    extra = set(recipe) - _WAVE_ALLOWED[shape]
    if extra:
        raise _bad(f"Wave recipe: parameters {sorted(extra)} do not apply to shape {shape!r}; "
                   f"allowed: {sorted(_WAVE_ALLOWED[shape] - {'type'})}.")
    peak = _wave_number(recipe, "peak", 0.88, 0.01, 1)
    if shape == "noise":
        values = _noise_values(recipe)
    else:
        frequency = _wave_number(recipe, "frequency", DEFAULT_FREQUENCY, 30, 2000)
        duty = _wave_number(recipe, "duty", 0.5, 0.05, 0.95) if shape == "pulse" else 0.5
        wanted = _wave_integer(recipe, "cycles", 1, 1, 64) if "cycles" in recipe else None
        cycles, frames = wave_geometry(frequency, wanted)
        values = _wave_cycle_values(shape, frames, cycles, duty)
    pcm = quantize(values, peak, True)
    return Sample(name, pcm, volume, finetune, 0, len(pcm), dict(recipe))


def recipe_facts(sample: Sample) -> dict:
    """Measured facts about a built recipe sample (bytes, loop, tuning of tonal loops), for agent feedback."""
    recipe = sample.recipe or {}
    facts = {"type": recipe.get("type"), "bytes": len(sample.pcm), "looped": bool(sample.loop_length),
             "loop_start": sample.loop_start, "loop_length": sample.loop_length,
             "pcm_peak": max(map(abs, sample.pcm), default=0)}
    if recipe.get("shape") == "noise":
        facts["note"] = "Unpitched noise loop; it repeats every length/8287 s at note C-2."
    elif recipe.get("type") in ("wave", "draw") and sample.loop_length:
        frequency = float(recipe.get("frequency", DEFAULT_FREQUENCY))
        if recipe["type"] == "wave":
            cycles = wave_geometry(frequency, recipe.get("cycles"))[0]
        else:
            cycles = recipe.get("cycles", 16)
        heard = heard_frequency(cycles, len(sample.pcm))
        facts.update(cycles=cycles, heard_hz_at_c2=round(heard, 3),
                     tuning_cents=round(cents(heard, frequency), 2))
    return facts


# --- discoverability ---------------------------------------------------------------------

def _param(kind: str, minimum=None, maximum=None, default=None, description: str = "", **extra) -> dict:
    return {"kind": kind, "min": minimum, "max": maximum, "default": default, "description": description, **extra}


_PEAK = _param("number", 0.01, 1, 0.88, "Fraction of full 8-bit scale used by the loudest byte.")
_SEED = _param("integer", 0, 2**32 - 1, 0, "Seed of the noise generator; the same seed gives the same bytes.")
_FREQ = _param("number", 30, 2000, DEFAULT_FREQUENCY, "Pitch in Hz heard when the sample plays at tracker note C-2.")


_DRIVE = _param("number", 0, 1, 0, "Soft saturation that evens out loud head and quiet tail: a denser, "
                "louder-in-RMS hit. 0 leaves the original sound; 0.3 suits matching a sample bank.")


def _percussion(purpose: str, duration: float) -> dict:
    return {"purpose": purpose, "looped": False,
            "parameters": {"duration": _param("number", 0.01, 1.5, duration, "Length in seconds."),
                           "peak": _PEAK, "seed": _SEED, "drive": _DRIVE}}


def recipe_types() -> list[dict]:
    """Every recipe type with its parameters, ranges, defaults and purpose (for `chiploom synth types`)."""
    tonal = ["pulse", "triangle", "saw", "sine"]
    return [
        {"type": "wave", "looped": True,
         "purpose": "Clean looped chip wave (pulse, triangle, saw, sine) tuned so note C-2 plays the stated "
                    "frequency; or a looped noise buffer for texture.",
         "parameters": {
             "shape": _param("choice", default=None, choices=list(WAVE_SHAPES), required=True,
                             description="Waveform. Noise takes seed/length/smooth; the others take frequency/cycles."),
             "frequency": {**_FREQ, "applies_to": tonal},
             "cycles": _param("integer", 1, 64, "auto",
                              "Cycles in the loop. Omit for the fewest cycles that land within 2 cents.",
                              applies_to=tonal),
             "duty": _param("number", 0.05, 0.95, 0.5, "Pulse width: 0.125, 0.25 and 0.5 are the classic ones.",
                            applies_to=["pulse"]),
             "length": _param("integer", 64, 65534, 2048, "Loop length in bytes (even).", applies_to=["noise"]),
             "smooth": _param("number", 0, 0.95, 0, "Low-pass amount: 0 is bright white noise, 0.9 is dark rumble.",
                              applies_to=["noise"]),
             "binary": _param("boolean", default=False, applies_to=["noise"],
                              description="1-bit noise (every byte at full height): the loudest, harshest texture."),
             "seed": {**_SEED, "applies_to": ["noise"]},
             "peak": _PEAK}},
        {"type": "kick", **_percussion("Low pitch-dropping thump with a click.", 0.24)},
        {"type": "snare", **_percussion("Noise burst over a short tone.", 0.19)},
        {"type": "hat", **_percussion("Very short high noise tick.", 0.048)},
        {"type": "kick_hat", **_percussion("Kick with a hat tick on top: one note, two drums.", 0.24)},
        {"type": "snare_hat", **_percussion("Snare with a hat tick on top.", 0.19)},
        {"type": "pluck", "looped": False,
         "purpose": "One-shot plucked tone with a baked decay (bass or lead); play it at C-2 for its stated pitch.",
         "parameters": {"duration": _param("number", 0.01, 1.5, 0.36, "Length in seconds."),
                        "frequency": _FREQ,
                        "duty": _param("number", 0.1, 0.9, 0.32, "Pulse width of the underlying tone."),
                        "peak": _PEAK, "seed": _SEED, "drive": _DRIVE}},
        {"type": "draw", "looped": True,
         "purpose": "Your own looped wave from 4 to 256 points between -1 and 1 (hand-drawn timbres).",
         "parameters": {"points": _param("array", -1, 1, None, "4 to 256 values along one cycle.", required=True),
                        "cycles": _param("integer", 1, 64, 16, "Cycles in the loop."),
                        "frequency": _FREQ, "peak": _PEAK}},
    ]
