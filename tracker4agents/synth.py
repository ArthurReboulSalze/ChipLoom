"""Deterministic PCM recipes; JSON supplies data, never executable expressions."""

from __future__ import annotations

import math
import random

from .model import SAMPLE_RATE, Sample, ValidationError, require_int


def number(value: object, name: str, minimum: float, maximum: float) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValidationError(f"{name}: nombre fini attendu dans [{minimum}, {maximum}].")
    return float(value)


def quantize(values: list[float], peak: float, looped: bool) -> tuple[int, ...]:
    mean = sum(values) / len(values)
    centered = [value - mean for value in values]
    maximum = max(abs(value) for value in centered)
    if maximum < 1e-12:
        raise ValidationError("La recette produit un sample silencieux.")
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


def from_recipe(name: str, recipe: dict, volume: int = 40, finetune: int = 0) -> Sample:
    if not isinstance(recipe, dict):
        raise ValidationError("Une recette de sample doit être un objet JSON.")
    kind = recipe.get("type")
    allowed = {"type", "seed", "peak", "duration", "frequency", "cycles", "points", "duty"}
    extra = set(recipe) - allowed
    if extra:
        raise ValidationError(f"Paramètres de synthèse inconnus : {sorted(extra)}.")
    peak = number(recipe.get("peak", 0.88), "peak", 0.01, 1)
    seed = require_int(recipe.get("seed", 0), "seed", 0, 2**32 - 1)
    rng = random.Random(seed)
    looped = kind == "draw"
    if looped:
        points = recipe.get("points")
        if not isinstance(points, list) or not 4 <= len(points) <= 256:
            raise ValidationError("Une onde dessinée attend de 4 à 256 points.")
        points = [number(value, "point", -1, 1) for value in points]
        cycles = require_int(recipe.get("cycles", 16), "cycles", 1, 64)
        frequency = number(recipe.get("frequency", 261.625565), "frequency", 30, 2000)
        frames = round(SAMPLE_RATE * cycles / frequency / 2) * 2
        if not 4 <= frames <= 65_534:
            raise ValidationError("L'onde dessinée dépasse la longueur autorisée.")
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
    else:
        raise ValidationError(f"Type de sample inconnu : {kind!r}.")
    pcm = quantize(values, peak, looped)
    return Sample(name, pcm, volume, finetune, 0, len(pcm) if looped else 0, dict(recipe))
