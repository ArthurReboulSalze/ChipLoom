"""Pixel Rush: original fast chip music with short waveforms and tracker articulation."""

from __future__ import annotations

from .model import Module, Pattern, cell, require_int, validate
from .synth import from_recipe


def pulse(width: int) -> list[float]:
    """One hand-defined 32-point pulse cycle, independent of reference PCM."""
    return [0.0] + [1.0] * (width - 1) + [0.0] + [-1.0] * (31 - width)


def create(seed: int = 104729) -> Module:
    require_int(seed, "seed", 0, 2**32 - 32)
    recipes = [
        ("01 Chip kick", 56, 0, {"type": "kick", "duration": 0.16, "peak": 0.93, "seed": seed + 11}),
        ("02 Chip snare", 49, 0, {"type": "snare", "duration": 0.09, "peak": 0.86, "seed": seed + 12}),
        ("03 Noise tick", 24, 0, {"type": "hat", "duration": 0.025, "peak": 0.74, "seed": seed + 13}),
        ("04 Kick tick", 56, 0, {"type": "kick_hat", "duration": 0.16, "peak": 0.93, "seed": seed + 14}),
        ("05 Snare tick", 49, 0, {"type": "snare_hat", "duration": 0.09, "peak": 0.86, "seed": seed + 15}),
        ("06 Triangle bass", 43, 1, {"type": "draw", "frequency": 130.812783, "cycles": 1,
                                    "peak": 0.88, "points": [0, 1, 0, -1]}),
        ("07 Pulse bass", 36, 1, {"type": "draw", "frequency": 130.812783, "cycles": 1,
                                 "peak": 0.82, "points": pulse(8)}),
        ("08 Narrow chord", 22, 1, {"type": "draw", "frequency": 261.625565, "cycles": 1,
                                   "peak": 0.72, "points": pulse(4)}),
        ("09 Triangle chord", 26, 1, {"type": "draw", "frequency": 261.625565, "cycles": 1,
                                     "peak": 0.78, "points": [0, 1, 0, -1]}),
        ("0A Lead pulse 12", 39, 1, {"type": "draw", "frequency": 261.625565, "cycles": 1,
                                    "peak": 0.82, "points": pulse(4)}),
        ("0B Lead pulse 25", 39, 1, {"type": "draw", "frequency": 261.625565, "cycles": 1,
                                    "peak": 0.82, "points": pulse(8)}),
        ("0C Lead pulse 37", 39, 1, {"type": "draw", "frequency": 261.625565, "cycles": 1,
                                    "peak": 0.82, "points": pulse(12)}),
        ("0D Lead pulse 50", 39, 1, {"type": "draw", "frequency": 261.625565, "cycles": 1,
                                    "peak": 0.82, "points": pulse(16)}),
    ]
    samples = [from_recipe(name, recipe, volume, tune) for name, volume, tune, recipe in recipes]
    # Chord root, octave, fifth and arpeggio: all pitches are newly composed.
    harmony = {
        "Em": ("E-1", "E-2", "B-1", "037"),
        "D": ("D-1", "D-2", "A-1", "047"),
        "C": ("C-1", "C-2", "G-1", "047"),
        "B": ("B-1", "B-2", "F#2", "047"),
        "G": ("G-1", "G-2", "D-2", "047"),
        "Am": ("A-1", "A-2", "E-2", "037"),
    }
    chords = [
        ("Em", "D", "C", "B"), ("Em", "C", "G", "D"),
        ("Em", "C", "Am", "B"), ("G", "D", "C", "B"),
        ("Am", "C", "D", "B"), ("Em", "C", "Am", "B"),
        ("Em", "D", "C", "B"),
    ]
    # Each pair is (sixteenth-note offset, pitch). Repetition and answers make a hook.
    hook = (
        ((0, "E-2"), (2, "B-2"), (3, "E-3"), (6, "G-3"), (8, "F#3"), (10, "E-3"), (12, "B-2"), (14, "G-2")),
        ((0, "E-3"), (3, "G-3"), (6, "E-3"), (8, "D-3"), (10, "C-3"), (12, "G-2"), (14, "C-3")),
        ((0, "B-2"), (2, "D-3"), (4, "G-3"), (7, "F#3"), (8, "D-3"), (11, "B-2"), (12, "A-2"), (14, "G-2")),
        ((0, "A-2"), (2, "D-3"), (4, "F#3"), (6, "E-3"), (8, "D-3"), (10, "A-2"), (12, "F#2"), (14, "D-2")),
    )
    answer = (
        ((0, "G-3"), (3, "F#3"), (4, "E-3"), (6, "B-2"), (8, "E-3"), (11, "D-3"), (12, "B-2"), (14, "G-2")),
        ((0, "G-2"), (2, "C-3"), (4, "E-3"), (7, "D-3"), (8, "C-3"), (10, "E-3"), (12, "G-3"), (14, "E-3")),
        ((0, "E-3"), (3, "C-3"), (4, "A-2"), (6, "C-3"), (8, "E-3"), (10, "G-3"), (12, "E-3"), (14, "C-3")),
        ((0, "F#3"), (2, "D#3"), (4, "B-2"), (6, "F#2"), (8, "B-2"), (10, "D#3"), (12, "F#3"), (14, "D#3")),
    )
    intro = (
        ((0, "E-2"), (4, "B-2"), (8, "G-2"), (12, "B-2")),
        ((0, "D-2"), (4, "A-2"), (8, "F#2"), (12, "A-2")),
        ((0, "C-2"), (4, "G-2"), (8, "E-2"), (12, "G-2")),
        ((0, "B-2"), (3, "D#3"), (6, "F#3"), (8, "E-3"), (10, "D#3"), (12, "B-2"), (14, "F#2")),
    )
    bridge = (
        ((0, "D-3"), (4, "B-2"), (8, "G-2"), (12, "B-2")),
        ((0, "A-2"), (4, "F#2"), (8, "E-2"), (12, "F#2")),
        ((0, "G-2"), (4, "E-2"), (8, "D-2"), (12, "E-2")),
        ((0, "F#2"), (4, "B-2"), (8, "D#3"), (12, "F#3")),
    )
    lift = (
        ((0, "A-2"), (4, "C-3"), (8, "E-3"), (12, "G-3")),
        ((0, "G-2"), (3, "C-3"), (6, "E-3"), (8, "G-3"), (12, "E-3")),
        ((0, "A-2"), (2, "D-3"), (4, "F#3"), (8, "A-3"), (10, "G-3"), (12, "F#3"), (14, "E-3")),
        ((0, "F#2"), (2, "B-2"), (4, "D#3"), (6, "F#3"), (8, "A-3"), (10, "F#3"), (12, "D#3"), (14, "B-2")),
    )
    phrases = (intro, hook, answer, bridge, lift, answer, intro)
    names = ("Boot", "A - Hook", "A - Answer", "B - Open space", "Build", "A - Final run", "Turnaround")
    patterns = []
    for section, name in enumerate(names):
        pattern = Pattern(name)
        for bar, chord in enumerate(chords[section]):
            start = bar * 16
            root, octave, fifth, arpeggio = harmony[chord]
            # One percussion lane; offbeat kicks and quiet noise notes add momentum.
            rhythm = {0: (4, 56), 2: (3, 22), 4: (5, 49), 6: (4, 48), 7: (3, 10),
                      8: (4, 56), 10: (3, 22), 11: (1, 27), 12: (5, 49), 14: (3, 24)}
            if section == 0 and bar < 2:
                rhythm = {step: value for step, value in rhythm.items() if step in (0, 4, 8, 12)}
            if section == 3:
                rhythm = {0: (4, 47), 4: (3, 19), 8: (5, 42), 12: (3, 19), 14: (3, 14)}
            if section in (2, 4, 5, 6) and bar == 3:
                rhythm.update({12: (2, 45), 13: (2, 24), 14: (2, 37), 15: (2, 29)})
            for step, (sample, volume) in rhythm.items():
                pattern.put(start + step, 0, cell("C-2", sample, f"C{volume:02X}"))

            bass_steps = ((0, root), (3, root), (6, octave), (8, root), (10, fifth), (12, root), (14, octave))
            if section == 3:
                bass_steps = ((0, root), (6, fifth), (8, root), (12, octave))
            for index, (step, note) in enumerate(bass_steps):
                voice = 7 if section in (1, 2, 5) and index % 3 == 2 else 6
                pattern.put(start + step, 1, cell(note, voice, "C2B" if step in (0, 8) else "C22"))
                if step + 1 < 16:
                    pattern.put(start + step + 1, 1, cell(effect="A03"))
                if step + 2 < 16:
                    pattern.put(start + step + 2, 1, cell(effect="C00"))
            pattern.put(start + 15, 1, cell(effect="C00"))

            # Alternate short drawn waves and quieter arpeggio echoes.
            arp_note = octave if chord != "B" else root
            for step in range(16):
                trigger = step % 4 == 0
                voice = 9 if section == 3 else 8
                if section in (2, 5) and step % 8 == 4:
                    voice = 9
                pattern.put(start + step, 2, cell(arp_note if trigger else None, voice if trigger else 0, arpeggio))
            for step in (3, 7, 11):
                pattern.put(start + step, 2, cell(effect="C0E"))
            pattern.put(start + 15, 2, cell(effect="C00"))

            phrase = phrases[section][bar]
            if section == 5 and bar in (0, 2):
                ending = ("B-2", "E-3", "F#3", "G-3") if bar == 0 else ("A-2", "C-3", "E-3", "G-3")
                phrase = tuple(pair for pair in phrase if pair[0] < 12) + tuple(zip(range(12, 16), ending))
            for index, (step, note) in enumerate(phrase):
                voice = 10 + (index + section) % 4
                next_step = phrase[index + 1][0] if index + 1 < len(phrase) else 16
                gap = next_step - step
                pattern.put(start + step, 3, cell(note, voice, "C27" if index % 2 == 0 else "C21"))
                if gap >= 2:
                    # Same note, new pulse width: a tracker-style timbre change.
                    effect = "412" if gap >= 3 else "A03"
                    pattern.put(start + step + 1, 3, cell(sample=10 + (index + section + 1) % 4, effect=effect))
                if gap >= 3:
                    pattern.put(start + step + 2, 3, cell(effect="603"))
                if gap >= 4 and section in (3, 4) and index + 1 < len(phrase):
                    # Anticipate the next pitch with a real tone-portamento tail.
                    pattern.put(start + step + 1, 3, cell(phrase[index + 1][1], 0, "304"))
                    pattern.put(start + step + 2, 3, cell(effect="300"))
                if gap >= 4:
                    pattern.put(start + next_step - 1, 3, cell(effect="C00"))
            if not pattern.get(start + 15, 3).period:
                pattern.put(start + 15, 3, cell(effect="C00"))
        patterns.append(pattern)

    patterns[0].put(0, 0, cell("C-2", 4, "F06"))
    patterns[0].put(0, 1, cell("E-1", 6, "FA0"))
    patterns[0].put(0, 3, cell("E-2", 10, "E01"))
    patterns[-1].put(63, 0, cell(effect="B00"))
    module = Module("Pixel Rush", samples, patterns, [0, 1, 2, 3, 4, 1, 5, 6], {
        "description": "Original fast chip piece, composed with newly drawn waves and synthetic percussion.",
        "display_description": "A fast chiptune piece: triangle basses, arpeggios and a square-wave melody whose timbre changes during the notes.",
        "arrangement": "32 bars: intro, theme and answer, a lighter passage, a build-up, the theme's return, then a restart. Patterns are reused as in the references.",
        "bars": 32, "seed": seed, "author": "tracker4agents / agent composition",
        "channel_names": ["Chip drums", "Triangle bass", "Pulse arpeggio", "PWM lead"],
        "note_convention": "ProTracker C-1..B-3, not scientific octave numbers",
        "timing": {"mode": "PAL CIA", "speed": 6, "bpm": 160},
        "sample_reference": "C-2 period 428; tiny drawn waves use finetune +1",
        "reference_use": "Arrangement, short waveforms and tracker articulation only; no reference PCM or note sequence imported.",
        "reference_studies": ["A01", "A02"],
    })
    validate(module)
    return module
