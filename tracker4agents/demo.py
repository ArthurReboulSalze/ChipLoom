"""First Light: an original 16-bar, four-channel Amiga-style test loop."""

from __future__ import annotations

from .model import Module, Pattern, cell, require_int, validate
from .synth import from_recipe


def create(seed: int = 104729) -> Module:
    require_int(seed, "seed", 0, 2**32 - 32)
    recipes = [
        ("01 Pulse kick", 52, {"type": "kick", "seed": seed}),
        ("02 Noise snare", 43, {"type": "snare", "seed": seed + 1}),
        ("03 Closed hat", 23, {"type": "hat", "seed": seed + 2}),
        ("04 Kick and hat", 52, {"type": "kick_hat", "seed": seed + 3}),
        ("05 Snare and hat", 43, {"type": "snare_hat", "seed": seed + 4}),
        ("06 Drawn bass", 34, {"type": "draw", "frequency": 130.812783, "cycles": 16,
                               "peak": 0.82, "points": [0, 0.85, 1, 0.95, 0.55, -0.6, -0.8, -0.75,
                                                        -0.7, -0.65, -0.6, -0.55, -0.5, -0.4, -0.25, -0.1]}),
        ("07 Glass arpeggio", 21, {"type": "draw", "frequency": 261.625565, "cycles": 16,
                                   "peak": 0.78, "points": [0, 0.7, 1, 0.6, 0, -0.15, 0, 0.15,
                                                            0, -0.6, -1, -0.7, 0, 0.15, 0, -0.15]}),
        ("08 Amber lead", 39, {"type": "pluck", "frequency": 261.625565, "duration": 0.36,
                              "duty": 0.30, "peak": 0.86, "seed": seed + 7}),
    ]
    samples = [from_recipe(name, recipe, volume) for name, volume, recipe in recipes]
    roots = ("A-1", "F-1", "C-2", "G-1")
    fifths = ("E-2", "C-2", "G-2", "D-2")
    melody = (
        (("A-2", "C-3", "E-3", "B-2"), ("A-2", "C-3", "A-2", "G-2"),
         ("G-2", "E-3", "D-3", "C-3"), ("B-2", "D-3", "G-2", "E-2")),
        (("A-2", "E-3", "C-3", "B-2", "A-2", "C-3", "E-3", "D-3"),
         ("A-2", "C-3", "E-3", "C-3", "A-2", "G-2", "F-2", "G-2"),
         ("G-2", "C-3", "E-3", "G-3", "E-3", "D-3", "C-3", "E-3"),
         ("D-3", "B-2", "G-2", "D-3", "G-3", "F-3", "D-3", "B-2")),
        (("E-3", "C-3", "A-2", "G-2"), ("F-2", "A-2", "C-3", "E-3"),
         ("E-3", "G-3", "E-3", "C-3"), ("D-3", "B-2", "G-2", "B-2")),
        (("A-2", "C-3", "E-3", "G-3"), ("E-3", "C-3", "A-2", "F-2"),
         ("G-2", "C-3", "E-3", "D-3", "C-3", "G-2", "E-2", "G-2"),
         ("B-2", "D-3", "G-3", "D-3", "B-2", "A-2", "G-2", "E-2")),
    )
    patterns = []
    for section, name in enumerate(("A - Signal", "B - Main theme", "C - Answer", "D - Turnaround")):
        pattern = Pattern(name)
        for bar in range(4):
            start = bar * 16
            for step in range(0, 16, 2):
                if step in (0, 8) or (section in (1, 3) and step == 6 and bar % 2):
                    sample = 4
                elif step in (4, 12):
                    sample = 5
                else:
                    sample = 3
                if section == 0 and bar == 0 and step in (6, 14):
                    continue
                pattern.put(start + step, 0, cell("C-2", sample))
            if section == 3 and bar == 3:
                for step, volume in ((12, 36), (14, 28), (15, 21)):
                    pattern.put(start + step, 0, cell("C-2", 2, f"C{volume:02X}"))

            # Staccato bass with a fifth on the offbeat; volume is a tracker command.
            for step in (0, 3, 6, 8, 11, 14):
                note = fifths[bar] if step in (6, 14) else roots[bar]
                pattern.put(start + step, 1, cell(note, 6, "C22" if step in (0, 8) else "C1B"))
                if step + 2 < 16:
                    pattern.put(start + step + 2, 1, cell(effect="C00"))
            pattern.put(start + 15, 1, cell(effect="C00"))

            arpeggio = "037" if bar == 0 else "047"
            for step in range(16):
                pattern.put(start + step, 2, cell(
                    roots[bar] if step % 4 == 0 else None,
                    7 if step % 4 == 0 else 0,
                    arpeggio,
                ))
            # Short reductions let the melody breathe without extra channels.
            pattern.put(start + 15, 2, cell(effect="C00"))
            phrase = melody[section][bar]
            stride = 16 // len(phrase)
            for index, note in enumerate(phrase):
                row = start + index * stride
                volume = 39 if index % 2 == 0 else 32
                pattern.put(row, 3, cell(note, 8, f"C{volume:02X}"))
                if stride >= 4:
                    pattern.put(row + 1, 3, cell(effect="412"))
                    pattern.put(row + 3, 3, cell(effect="C00"))
        patterns.append(pattern)

    # Reinitialise both timing parameters on every cycle; use CIA/PAL timing.
    patterns[0].put(0, 0, cell("C-2", 4, "F06"))
    patterns[0].put(0, 1, cell("A-1", 6, "F7D"))
    # Lead's default volume is already 39: this cell can disable the LED filter
    # from the very first row without displacing a musical volume change.
    patterns[0].put(0, 3, cell("A-2", 8, "E01"))
    patterns[-1].put(63, 0, cell(effect="B00"))
    patterns[-1].put(63, 3, cell(effect="C00"))
    module = Module(
        "First Light", samples, patterns, [0, 1, 2, 3],
        {
            "description": "Original 16-bar Amiga/cracktro test loop; no imported music or samples.",
            "display_description": "Une boucle Amiga composée par l’agent. Huit samples dessinés ou synthétisés pour le projet, quatre voies et seize mesures.",
            "arrangement": "Progression Am – F – C – G. La seconde moitié développe la mélodie, puis un roulement ramène au début.",
            "bars": 16,
            "seed": seed, "author": "tracker4agents / agent prototype",
            "channel_names": ["Drums", "Bass", "Arpeggio", "Lead"],
            "note_convention": "ProTracker C-1..B-3, not scientific octave numbers",
            "timing": {"mode": "PAL CIA", "speed": 6, "bpm": 125},
            "sample_reference": "C-2 period 428 at PAL clock 3546895 Hz",
        },
    )
    validate(module)
    return module
