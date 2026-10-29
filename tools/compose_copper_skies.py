"""Copper Skies: a cracktro-style XM for ChipLoom, written with the Python API (the third public demo).

    python tools/compose_copper_skies.py exports/copper-skies/copper-skies.project.json

Ten channels, speed 3 at 150 BPM (eight rows per beat, 32 per bar), patterns of 128, 64, 48 and 32
rows, 22 created instruments (synthesized mode), volume and panning envelopes, auto-vibrato,
fadeout, ping-pong loops, relative notes, finetune, panning, the volume column and every XM effect
ChipLoom accepts except E6x. The song loops to the theme (restart position 1 and B01), skipping the intro.

A wave recipe's `frequency` is the pitch heard at written C-4 (MOD C-2), so the bass recipes are
written at 261.6 Hz and `relative_note -12` makes written A-3 sound A-2 (110 Hz).
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tracker4agents import project, synth_tools, xm  # noqa: E402
from tracker4agents.model import XM_NOTE_TO_NUMBER, XM_NOTES, Pattern, cell  # noqa: E402

CHANNELS = 10
DRUM, HAT, BASS, ARP_L, ARP_R, LEAD, ECHO, PAD, BELL, FX = range(CHANNELS)
UNPITCHED = {DRUM, HAT, FX}   # never transposed
BEAT, BAR = 8, 32
SPEED, BPM = 3, 150
C4 = 261.625565

# --- instruments (slot, name, role, volume, recipe, extras) -------------------------------------
KICK, SNARE, HATC, HATO, KICKHAT, SNAREHAT, BASSP, SLAP, ARP25, ARP12, LEAD25, LEAD50, LEAD12, \
    SAWA, SAWB, BELLS, PADT, NOISE, STAB, TOM, CRASH, CONTINUO = range(1, 23)

VOL_ENV = {"points": [[0, 64], [5, 50], [30, 52], [60, 52], [100, 0]], "sustain": 3, "type": 3}
ENV_LEAD = {"volume_envelope": VOL_ENV, "vibrato": {"type": 0, "sweep": 40, "depth": 3, "rate": 34}, "fadeout": 400}
ENV_LEAD_PLAIN = {"volume_envelope": VOL_ENV, "fadeout": 400}            # vibrato comes from the volume column
ENV_SAW = {"volume_envelope": {"points": [[0, 64], [8, 52], [40, 48], [90, 0]], "sustain": 2, "type": 3},
           "vibrato": {"type": 0, "sweep": 24, "depth": 2, "rate": 40}, "fadeout": 600}
ENV_BELL = {"volume_envelope": {"points": [[0, 64], [8, 48], [50, 30], [120, 0]], "sustain": 2, "type": 3},
            "fadeout": 1200}                                             # the key off (Kxx) starts the fade
ENV_PAD = {"volume_envelope": {"points": [[0, 0], [26, 56], [90, 46], [160, 46], [240, 0]], "sustain": 3, "type": 3},
           "panning_envelope": {"points": [[0, 18], [100, 46], [200, 18]], "loop_start": 0, "loop_end": 2, "type": 5},
           "fadeout": 160}
ENV_STAB = {"volume_envelope": {"points": [[0, 64], [6, 34], [34, 0]], "type": 1}}
ENV_CRASH = {"volume_envelope": {"points": [[0, 64], [30, 34], [120, 8], [170, 0]], "type": 1}}

INSTRUMENTS = [
    (KICK, "Kick", "kick", 62, {"type": "kick", "duration": 0.17, "peak": 0.95, "seed": 7101, "drive": 0.55}, {}),
    (SNARE, "Snare", "snare", 56, {"type": "snare", "duration": 0.11, "peak": 0.9, "seed": 7102, "drive": 0.35}, {}),
    (HATC, "Hat closed", "hat", 26, {"type": "hat", "duration": 0.028, "peak": 0.74, "seed": 7103, "drive": 0.3},
     {"panning": 96}),
    (HATO, "Hat open", "hat", 24, {"type": "hat", "duration": 0.11, "peak": 0.7, "seed": 7104, "drive": 0.2},
     {"panning": 96}),
    (KICKHAT, "Kick+hat", "kick", 62, {"type": "kick_hat", "duration": 0.17, "peak": 0.95, "seed": 7105, "drive": 0.55}, {}),
    (SNAREHAT, "Snare+hat", "snare", 56, {"type": "snare_hat", "duration": 0.11, "peak": 0.9, "seed": 7106, "drive": 0.35}, {}),
    (BASSP, "Pulse bass", "bass", 50, {"type": "wave", "shape": "pulse", "duty": 0.25, "frequency": C4, "peak": 0.9},
     {"relative_note": -12}),
    (SLAP, "Slap bass", "bass", 54, {"type": "pluck", "frequency": C4, "duration": 0.22, "duty": 0.3, "peak": 0.92,
                                     "seed": 7108, "drive": 0.4}, {"relative_note": -12}),
    (ARP25, "Arp pulse 25", "chord", 30, {"type": "wave", "shape": "pulse", "duty": 0.25, "frequency": C4, "peak": 0.85},
     {"panning": 56}),
    (ARP12, "Arp pulse 12", "chord", 24, {"type": "wave", "shape": "pulse", "duty": 0.125, "frequency": C4, "peak": 0.85},
     {"panning": 200}),
    (LEAD25, "Lead pulse 25", "lead", 52, {"type": "wave", "shape": "pulse", "duty": 0.25, "frequency": C4, "peak": 0.88},
     {"panning": 120, **ENV_LEAD}),
    (LEAD50, "Lead pulse 50", "lead", 50, {"type": "wave", "shape": "pulse", "duty": 0.5, "frequency": C4, "peak": 0.88},
     {"panning": 168, **ENV_LEAD_PLAIN}),
    (LEAD12, "Lead pulse 12", "lead", 52, {"type": "wave", "shape": "pulse", "duty": 0.125, "frequency": C4, "peak": 0.88},
     {"panning": 120, **ENV_LEAD}),
    (SAWA, "Saw lead A", "lead", 46, {"type": "wave", "shape": "saw", "frequency": C4, "peak": 0.86},
     {"panning": 104, "finetune": -10, **ENV_SAW}),
    (SAWB, "Saw lead B", "lead", 46, {"type": "wave", "shape": "saw", "frequency": C4, "peak": 0.86},
     {"panning": 152, "finetune": -30, **ENV_SAW}),
    (BELLS, "Bells", "lead", 34, {"type": "wave", "shape": "triangle", "frequency": C4, "peak": 0.9},
     {"panning": 72, **ENV_BELL}),
    (PADT, "Pad", "chord", 30, {"type": "wave", "shape": "triangle", "frequency": C4, "peak": 0.9},
     {"loop_mode": "pingpong", **ENV_PAD}),
    (NOISE, "Wind", "texture", 30, {"type": "wave", "shape": "noise", "length": 4096, "smooth": 0.35, "peak": 0.8, "seed": 7117},
     {"loop_mode": "pingpong", "panning": 128}),
    (STAB, "Chord stab", "chord", 40, {"type": "wave", "shape": "pulse", "duty": 0.5, "frequency": C4, "peak": 0.88},
     {"panning": 128, **ENV_STAB}),
    (TOM, "Tom", "kick", 54, {"type": "kick", "duration": 0.36, "peak": 0.9, "seed": 7120, "drive": 0.3}, {}),
    (CRASH, "Crash", "texture", 34, {"type": "wave", "shape": "noise", "length": 8192, "smooth": 0.55, "peak": 0.85, "seed": 7121},
     {"loop_mode": "pingpong", "panning": 150, **ENV_CRASH}),
    (CONTINUO, "Continuo bass", "bass", 40, {"type": "wave", "shape": "pulse", "duty": 0.4, "frequency": C4, "peak": 0.85},
     {"relative_note": -12}),   # no envelope: a steady held tone, an octave below the written note
]

MINOR, MAJOR = "037", "047"
INV1 = {MINOR: "049", MAJOR: "038"}  # first inversion, from the third
INV2 = {MINOR: "058", MAJOR: "059"}  # second inversion, from the fifth
CHORDS = {
    "Am": ("A", MINOR), "F": ("F", MAJOR), "C": ("C", MAJOR), "G": ("G", MAJOR), "E": ("E", MAJOR),
    "Em": ("E", MINOR), "D": ("D", MAJOR), "Dm": ("D", MINOR), "F#": ("F#", MAJOR),
}
PROG_A = ["Am", "F", "C", "G", "Am", "F", "G", "E"]
PROG_B = ["C", "G", "Am", "Em", "F", "C", "D", "E"]
PROG_C = ["Am", "G", "F", "E"]
PROG_C_END = ["Am", "G", "F", "F#"]   # F# major leads the key change up to B minor


# --- helpers -------------------------------------------------------------------------------------
def num(name: str) -> int:
    return XM_NOTE_TO_NUMBER[name]


def name(number: int) -> str:
    return XM_NOTES[number - 1]


def shift(note: str, semitones: int) -> str:
    return name(num(note) + semitones)


def root_note(chord: str, octave: int) -> str:
    root = CHORDS[chord][0]
    return f"{root}{octave}" if "#" in root else f"{root}-{octave}"


def third_note(chord: str, octave: int) -> str:
    return shift(root_note(chord, octave), 3 if CHORDS[chord][1] == MINOR else 4)


def fifth_note(chord: str, octave: int) -> str:
    return shift(root_note(chord, octave), 7)


def phrase(text: str) -> list[tuple[str | None, int, bool]]:
    """'A-4:4 C-5:8! r:4' -> [(note, rows, staccato)]; 'r' is a rest."""
    out = []
    for token in text.split():
        note, rows = token.split(":")
        staccato = rows.endswith("!")
        out.append((None if note == "r" else note, int(rows.rstrip("!")), staccato))
    return out


def lower(notes, semitones: int = 12):
    return [(shift(note, -semitones) if note else None, rows, staccato) for note, rows, staccato in notes]


def split(notes, rows: int = 128):
    """The notes of the first `rows` rows and the rest."""
    total, index = 0, 0
    while index < len(notes) and total < rows:
        total += notes[index][1]
        index += 1
    if total != rows:
        raise ValueError(f"phrase does not split at row {rows}: {total}")
    return notes[:index], notes[index:]


class Grid:
    def __init__(self, label: str, rows: int, transpose: int = 0):
        self.pattern = Pattern(label, {}, rows)
        self.rows = rows
        self.transpose = transpose

    def put(self, row: int, ch: int, note: str | None = None, inst: int = 0, vol: int = 0, eff: str = "000"):
        if not 0 <= row < self.rows:
            raise IndexError((self.pattern.name, row))
        if note and note != "===" and self.transpose and ch not in UNPITCHED:
            note = shift(note, self.transpose)
        old = self.pattern.get(row, ch)
        if old.period or old.sample or old.command or old.param or old.volume:
            new = cell(note, inst, eff, "xm", vol)   # merge: keep what is there, add what is new
            merged = dataclasses.replace(
                old, period=new.period or old.period, sample=new.sample or old.sample,
                command=new.command if eff != "000" else old.command,
                param=new.param if eff != "000" else old.param, volume=new.volume or old.volume)
            self.pattern.cells[(row, ch)] = merged
            return
        self.pattern.put(row, ch, cell(note, inst, eff, "xm", vol))

    def eff(self, row: int, ch: int, eff: str):
        self.put(row, ch, eff=eff)

    def vol(self, row: int, ch: int, vol: int):
        self.put(row, ch, vol=vol)

    def melody(self, ch: int, start: int, inst: int, notes, vol: int = 0x50, vibrato: bool = False,
               echo: int | None = None, echo_inst: int = 0, echo_vol: int = 0x28):
        """Notes; a staccato note is keyed off with Kxx; long notes may get volume-column vibrato
        (speed then depth); an optional echo channel repeats each note six rows later, sliding down."""
        row = start
        for note, rows, staccato in notes:
            if note is None:
                self.put(row, ch, "===")
            else:
                self.put(row, ch, note, inst, vol)
                if vibrato and rows >= 12:
                    self.vol(row + 5, ch, 0xA6)
                    for r in range(row + 6, row + rows - 1):
                        self.vol(r, ch, 0xB3)
                if staccato:
                    self.eff(row + rows - 2, ch, "K02")
                if echo is not None:
                    at = row + 6
                    if at < self.rows:
                        self.put(at, echo, note, echo_inst, echo_vol)
                    for r in range(at + 3, min(at + rows - 1, self.rows)):
                        self.vol(r, echo, 0x61)
                    if staccato and at + rows - 2 < self.rows:
                        self.put(at + rows - 2, echo, "===")
            row += rows
        return row


# --- parts ---------------------------------------------------------------------------------------
def drums(g: Grid, bars: range, fill: int | None = 0, crash: bool = False, half: bool = False, tight: bool = False):
    """Kick/snare on channel 0, hats on channel 1; `fill` 0 (toms) or 1 (snare sixteenths) in the last bar."""
    for bar in bars:
        b = bar * BAR
        if half:
            g.put(b, DRUM, "C-4", KICK, 0x50)
            g.put(b + 16, DRUM, "C-4", SNARE, 0x48)
            g.put(b + 24, DRUM, "C-4", KICK, 0x3C)
            for i in range(4, BAR, 8):
                g.put(b + i, HAT, "C-4", HATC, 0x28)
            continue
        g.put(b, DRUM, "C-4", KICKHAT, 0x50)
        g.put(b + 8, DRUM, "C-4", SNAREHAT, 0x4A)
        g.put(b + 16, DRUM, "C-4", KICK, 0x50)
        g.put(b + 20, DRUM, "C-4", KICK, 0x3C)
        g.put(b + 24, DRUM, "C-4", SNAREHAT, 0x4A)
        g.put(b + 16, HAT, "C-4", HATC, 0x28)
        for i in range(4, BAR, 8):
            open_hat = i in (12, 28)
            g.put(b + i, HAT, "C-4", HATO if open_hat else HATC, 0x30 if open_hat else 0x28,
                  "EC2" if open_hat and tight else "000")    # a tight open hat is cut after two ticks
        g.put(b + 30, HAT, "C-4", HATC, 0x20, "ED1")  # a late 32nd grace tick
    if fill is not None:
        b = bars[-1] * BAR
        if fill == 0:
            g.put(b + 24, DRUM, "C-4", SNARE, 0x40, "E91")
            g.put(b + 26, DRUM, "C-4", SNARE, 0x44, "E91")
            for r, note in ((28, "C-4"), (29, "A-3"), (30, "F-3"), (31, "D-3")):    # descending toms
                g.put(b + r, DRUM, note, TOM, 0x4C)
            g.put(b + 31, HAT, "C-4", HATO, 0x34)
        else:
            for r in range(24, 32, 2):
                g.put(b + r, DRUM, "C-4", SNARE, 0x30 + 2 * (r - 24))       # sixteenths, louder each time
            g.put(b + 28, HAT, "C-4", TOM, 0x40)
            g.put(b + 30, HAT, "C-4", TOM, 0x44)
    if crash:
        g.put(bars[0] * BAR, FX, "C-4", CRASH, 0x40)


def bass_line(g: Grid, prog: list[str], next_root: str, busy: bool = True, start_bar: int = 0):
    """Slap on the downbeat, octave hops, and two 32nds walking into the next chord (`next_root`, written
    untransposed like every note: the grid transposes it)."""
    for i, chord in enumerate(prog):
        b = (start_bar + i) * BAR
        low = root_note(chord, 3)
        high = shift(low, 12)
        fifth = shift(low, 7)
        g.put(b, BASS, low, SLAP, 0x40)
        target = num(root_note(prog[i + 1], 3)) if i + 1 < len(prog) else num(next_root)
        if busy:
            for r, note, v in ((4, high, 0x34), (8, low, 0x3C), (12, high, 0x34), (16, low, 0x40),
                               (20, fifth, 0x34), (24, low, 0x3C)):
                g.put(b + r, BASS, note, BASSP, v)
            g.put(b + 28, BASS, name(target - 2), BASSP, 0x36)
            g.put(b + 30, BASS, name(target - 1), BASSP, 0x38)
        else:
            g.put(b + 16, BASS, low, BASSP, 0x38)
            g.put(b + 26, BASS, "===")
            g.put(b + 28, BASS, name(target - 2), BASSP, 0x30)
            g.put(b + 30, BASS, name(target - 1), BASSP, 0x32)


# Arpeggios are struck on the rhythm, never held: each hit plays the chord for a few rows, drops to a
# quiet tail, and the next hit retriggers it (as Pixel Rush does with Cxx). Accents follow a 3-3-2 groove.
ACCENTS = (1, 0, 0, 1, 0, 0, 1, 0)   # per eighth: rows 0, 12 and 24 are accented
TAIL = 0x16                          # volume-column byte of a hit's tail (volume 6)


def arps(g: Grid, prog: list[str], gate: bool = False, right: bool = True, vol_l: int = 0x24, vol_r: int = 0x20):
    """Left channel: one hit per eighth (sixteenths with `gate`), 3 rows of chord then a tail, silent on the
    bar's last row. Right channel: short inverted-chord answers off the beat."""
    for i, chord in enumerate(prog):
        b = i * BAR
        kind = CHORDS[chord][1]
        step = 2 if gate else 4
        for k, r in enumerate(range(0, BAR, step)):
            accent = ACCENTS[(r // 4) % 8] and r % 4 == 0
            g.put(b + r, ARP_L, root_note(chord, 4), ARP25, vol_l + (8 if accent else -4), kind)
            for t in range(1, step):
                g.put(b + r + t, ARP_L, vol=TAIL if t == step - 1 else 0, eff=kind)
        g.vol(b + BAR - 1, ARP_L, 0x10)                       # silence before the next bar
        if right:
            inv = INV1[kind] if i % 2 == 0 else INV2[kind]
            note = third_note(chord, 4) if i % 2 == 0 else fifth_note(chord, 4)
            for r in (8, 20, 28):   # the last eighth of each 3-3-2 group: a pickup into the left channel's accent
                for t in range(1, step):
                    g.put(b + r + t, ARP_R, vol=TAIL if t == step - 1 else 0, eff=inv)
                g.put(b + r, ARP_R, note, ARP12, vol_r, inv)
            g.vol(b + BAR - 1, ARP_R, 0x10)


def pad(g: Grid, prog: list[str], octave: int = 3):
    """The low chord root struck on the 3-3-2 accents (rows 0, 12 and 24, with the left arpeggio's accents):
    three rows, a quiet tail, then silence until the next accent, so it marks the groove without filling it."""
    for i, chord in enumerate(prog):
        b = i * BAR
        for r, v in ((0, 0x34), (12, 0x2C), (24, 0x30)):
            g.put(b + r, PAD, root_note(chord, octave), CONTINUO, v)
            g.put(b + r + 3, PAD, vol=TAIL)
            g.put(b + r + 4, PAD, "===")


def bells(g: Grid, prog: list[str]):
    """Off-beat broken chords in octave 5-6, alternating sides with 8xx, each keyed off after two rows."""
    for i, chord in enumerate(prog):
        b = i * BAR
        tones = [fifth_note(chord, 5), third_note(chord, 5), root_note(chord, 6), fifth_note(chord, 5)]
        for k, r in enumerate(range(4, BAR, 8)):
            g.put(b + r, BELL, tones[k], BELLS, 0x30, "810" if k % 2 else "8E0")
            g.put(b + r + 2, BELL, eff="K01")


HOOK = phrase(
    "A-4:4 C-5:4 E-5:8 D-5:4 C-5:4 D-5:8 "
    "E-5:8 D-5:4 C-5:4 A-5:8 G-5:4 E-5:4 "
    "G-5:8 E-5:4 G-5:4 C-6:8 B-5:4 G-5:4 "
    "A-5:8 G-5:4 E-5:4 D-5:8 B-4:8 "
    "A-4:4 C-5:4 E-5:8 D-5:4 C-5:4 D-5:8 "
    "E-5:8 D-5:4 C-5:4 A-5:8 B-5:4 C-6:4 "
    "D-6:8 C-6:4 B-5:4 G-5:8 A-5:4 B-5:4 "
    "C-6:4 B-5:12 G#5:8 E-5:4! r:4")
HOOK2 = phrase(
    "A-4:4 C-5:4 E-5:8 D-5:4 C-5:4 D-5:8 "
    "E-5:8 D-5:4 C-5:4 A-5:8 G-5:4 E-5:4 "
    "G-5:8 E-5:4 G-5:4 C-6:8 B-5:4 G-5:4 "
    "A-5:8 G-5:4 E-5:4 D-5:8 B-4:8 "
    "A-4:4 C-5:4 E-5:8 D-5:4 C-5:4 D-5:8 "
    "E-5:8 D-5:4 C-5:4 A-5:8 B-5:4 C-6:4 "
    "D-6:4 E-6:4 D-6:8 C-6:4 B-5:4 A-5:8 "
    "G#5:8 B-5:8 E-6:12 r:4")
BRIDGE = phrase(
    "E-5:8 G-5:4 A-5:4 C-6:12 r:4 "
    "B-5:8 A-5:4 G-5:4 D-6:8 r:8 "
    "A-5:8 C-6:4 B-5:4 E-6:12 D-6:4 "
    "B-5:12 G-5:4 E-5:8 r:8 "
    "A-5:8 C-6:4 D-6:4 F-6:12 r:4 "
    "E-6:8 D-6:4 C-6:4 G-5:16 "
    "D-6:8 F#6:8 E-6:4 D-6:4 A-5:8 "
    "E-6:16 B-5:8 G#5:8")
SOLO1 = lower(phrase(
    "A-5:2 C-6:2 E-6:2 A-6:2 G-6:2 E-6:2 C-6:2 A-5:2 C-6:4 E-6:4 A-5:4 B-5:2 C-6:2 "
    "B-5:2 D-6:2 G-6:2 B-6:2 A-6:2 G-6:2 D-6:2 B-5:2 G-5:8 D-6:4 B-5:4 "
    "A-5:2 C-6:2 F-6:2 A-6:2 G-6:2 F-6:2 C-6:2 A-5:2 F-5:4 A-5:4 C-6:8 "
    "G#5:2 B-5:2 E-6:2 G#6:2 B-6:8 G#6:4 E-6:4 B-5:4 G#5:4 "
    "E-6:2 D-6:2 C-6:2 B-5:2 A-5:2 G-5:2 A-5:2 B-5:2 C-6:4 E-6:4 A-6:8 "
    "G-6:2 F#6:2 G-6:2 A-6:2 B-6:8 D-6:4 G-6:4 B-5:4 D-6:4 "
    "C-6:4 F-6:4 A-6:4 C-7:4 A-6:4 F-6:4 C-6:4 A-5:4 "
    "B-5:8 E-6:8 G#6:16"))
SOLO2 = lower(phrase(
    "A-6:2 G-6:2 E-6:2 C-6:2 A-5:2 C-6:2 E-6:2 G-6:2 A-6:4 E-6:4 C-6:4 E-6:2 A-6:2 "
    "B-6:2 A-6:2 G-6:2 D-6:2 B-5:2 D-6:2 G-6:2 A-6:2 B-6:8 G-6:4 D-6:4 "
    "C-7:2 A-6:2 F-6:2 C-6:2 A-5:2 C-6:2 F-6:2 A-6:2 C-7:4 A-6:4 F-6:4 A-6:4 "
    "B-6:2 G#6:2 E-6:2 B-5:2 G#5:2 B-5:2 E-6:2 G#6:2 B-6:16 "
    "A-6:4 E-6:4 C-6:4 A-5:4 E-5:2 A-5:2 C-6:2 E-6:2 A-6:2 C-7:2 E-7:4 "
    "D-7:2 B-6:2 G-6:2 D-6:2 B-5:2 D-6:2 G-6:2 B-6:2 D-7:16 "
    "C-7:4 A-6:4 F-6:4 C-6:4 F-6:4 A-6:4 C-7:4 F-7:4 "
    "E-7:32"))


def section_a(label: str, hook, next_root: str, first: bool, transpose: int = 0, bells_on: bool = False,
              fill: int | None = 0, crash: bool = True, soft_start: bool = False) -> Grid:
    """`first`: the first four bars of the theme (hook bars 1-4), else bars 5-8."""
    g = Grid(label, 128, transpose)
    prog = PROG_A[:4] if first else PROG_A[4:]
    if soft_start:   # the theme's return: half-time drums and a sparse bass for two bars, then everything
        drums(g, range(2), fill=None, half=True)
        drums(g, range(2, 4), fill=fill)
        bass_line(g, prog[:2], root_note(prog[2], 3), busy=False)
        bass_line(g, prog[2:], next_root, start_bar=2)
    else:
        drums(g, range(4), fill=fill, crash=crash)
        bass_line(g, prog, next_root)
    arps(g, prog)
    pad(g, prog)
    notes = split(hook)[0] if first else split(hook)[1]
    g.melody(LEAD, 0, LEAD25, notes, echo=ECHO, echo_inst=LEAD50)
    if bells_on:
        bells(g, prog)
    return g


def bridge(label: str, half: int, next_root: str, transpose: int = 0, slide_in_column: bool = False) -> Grid:
    g = Grid(label, 128, transpose)
    prog = PROG_B[:4] if half == 0 else PROG_B[4:]
    drums(g, range(4), fill=half, tight=True)
    bass_line(g, prog, next_root)
    arps(g, prog, gate=True)
    pad(g, prog)
    g.melody(LEAD, 0, LEAD50, split(BRIDGE)[half], vibrato=True, echo=ECHO, echo_inst=LEAD25, echo_vol=0x24)
    if half == 0:   # bar 2: G-5 slides up to D-6 (effect column here, volume column in the K bridge)
        if slide_in_column:
            for r in range(49, 56):
                g.vol(r, LEAD, 0xF2)
        else:
            for r in range(48, 56):
                g.eff(r, LEAD, "320" if r < 52 else "501")   # the slide continues with a slight fade
    else:           # the last G#5 drifts down with extra-fine portamento
        for r in range(121, 128):
            g.eff(r, LEAD, "X22")
    bells(g, prog)
    return g


# --- the song ------------------------------------------------------------------------------------
def build():
    module = xm.blank("Copper Skies", channels=CHANNELS, patterns=1, rows=64, speed=SPEED, bpm=BPM, metadata={
        "sample_source": "synthesized",
        "description": "A cracktro-style XM: pulse arpeggios, a slap bass, a square lead with its echo, "
                       "bells, a swelling pad and a detuned saw solo, then the theme a tone higher.",
        "display_description": "Cracktro chiptune in ten channels: fast arpeggios, a singing pulse lead with echo, "
                               "a detuned saw solo and a key change for the last chorus.",
        "arrangement": "Intro (2 bars), theme A (8 bars) twice (the return starts half-time, with bells), "
                       "bridge B (8 bars), a 48-row break, saw solo C (16 bars, the last bar on F# major), theme "
                       "and bridge a tone higher, a held beat, outro with a ritardando and a held final chord. "
                       "Loops to the theme (restart position 1, B01).",
        "author": "ChipLoom / agent composition",
        "channel_names": ["Kick & snare", "Hats & fills", "Bass", "Arp left", "Arp right", "Lead", "Echo / double",
                          "Pad", "Bells", "FX & tempo"],
    })
    for slot, title, role, volume, recipe, extras in INSTRUMENTS:
        synth_tools.insert_recipe(module, title, recipe, slot=slot, volume=volume, role=role)
        fields = {k: v for k, v in extras.items() if k in ("panning", "relative_note", "finetune", "loop_mode")}
        if fields:
            module.samples[slot - 1] = dataclasses.replace(module.samples[slot - 1], **fields)
        meta = {k: v for k, v in extras.items() if k in ("volume_envelope", "panning_envelope", "vibrato", "fadeout")}
        if meta:
            module.metadata["xm"].setdefault("instruments", {})[str(slot)] = meta

    patterns: list[Grid] = []
    A, Fn, C, B = "A-3", "F-3", "C-3", "B-3"   # bass roots the walk-ups aim at

    # 0 Intro (64 rows): wind rises (volume slides, sample offsets, pan slides); arps fade in; snare roll.
    g = Grid("Intro", 64)
    g.put(0, FX, "C-4", NOISE, 0x14, "F96")
    for r in range(1, 40):
        g.vol(r, FX, 0x71 if r % 2 else 0)
    for r in range(8, 40, 8):
        g.put(r, FX, "C-4", NOISE, 0x14 + r, "9%02X" % (2 + r // 8))   # retrigger further in, at the running level
    for r in range(40, 56):
        g.vol(r, FX, 0xD2 if r < 48 else 0xE2)      # pan slide left, then right
    for r in range(56, 64):
        g.eff(r, FX, "A08")                         # the wind fades out under the roll
    for r in range(0, 64, 4):                       # struck arpeggio, growing hit by hit
        g.put(r, ARP_L, "A-4", ARP25, 0x12 + r // 4 + (6 if r % 16 == 0 else 0), MINOR)
        g.put(r + 1, ARP_L, eff=MINOR)
        g.put(r + 2, ARP_L, eff=MINOR)
        g.put(r + 3, ARP_L, vol=0x14, eff=MINOR)
    for r in (40, 52, 60):                          # the right channel's pickups join in the second bar
        g.put(r, ARP_R, "C-5", ARP12, 0x18 + (r - 40) // 4, INV1[MINOR])
        g.put(r + 1, ARP_R, eff=INV1[MINOR])
        g.put(r + 2, ARP_R, eff=INV1[MINOR])
        g.put(r + 3, ARP_R, vol=0x10 if r == 60 else TAIL, eff=INV1[MINOR])
    g.put(0, PAD, "A-3", PADT, 0x30)
    g.put(60, PAD, "===")
    for r in range(32, 64, 4):
        g.put(r, HAT, "C-4", HATC, 0x1C + (r - 32) // 2)
    for r in range(48, 64):
        g.put(r, DRUM, "C-4", SNARE, 0x1C + (r - 48) * 2, "R01")   # even roll: a retrig every tick
    for r, note in ((48, "E-3"), (52, "F-3"), (56, "G-3"), (60, "G#3")):
        g.put(r, BASS, note, SLAP, 0x3C)
    g.put(62, DRUM, "C-4", KICK, 0x48, "ED1")
    patterns.append(g)

    # Theme: A1 + A2, the return (half-time start) and A3 with bells.
    patterns.append(section_a("Theme A1", HOOK, A, first=True))
    patterns.append(section_a("Theme A2", HOOK2, A, first=False, fill=1, crash=False))
    patterns.append(section_a("Theme A1b", HOOK, A, first=True, crash=False, soft_start=True))
    patterns.append(section_a("Theme A3", HOOK2, C, first=False, bells_on=True, fill=1, crash=False))
    a1 = patterns[1]
    a1.put(0, FX, eff="F96")   # restore the tempo and the global volume when the song loops here
    a1.put(0, BELL, eff="G40")

    # Bridge B (two patterns), then the break.
    patterns.append(bridge("Bridge B", 0, Fn))
    patterns.append(bridge("Bridge B2", 1, A))

    # Break (48 rows): the pad alone with tremor and tremolo, portamento lead, a snare roll on global slide.
    g = Grid("Break", 48)
    g.put(0, FX, eff="G28")
    g.put(0, PAD, "A-3", PADT, 0x3C, "E71")         # tremolo waveform: ramp down
    for r in range(1, 16):
        g.eff(r, PAD, "T20")                        # tremor: on 3 ticks, off 1
    for r in range(16, 32):
        g.eff(r, PAD, "7A4")                        # tremolo
    g.put(32, PAD, eff="L00")                       # restart the envelope: a new swell without a new note
    g.put(44, PAD, "===")
    g.put(0, LEAD, "E-6", LEAD12, 0x3C, "E54")      # finetune set on the fly: a shade flat (-35 cents)
    for r in range(2, 14):
        g.eff(r, LEAD, "208")                       # portamento down
    g.put(16, LEAD, "C-6", LEAD12, 0x3C)
    for r in range(18, 30):
        g.eff(r, LEAD, "108")                       # portamento up
    g.put(30, LEAD, "===")
    g.put(32, LEAD, "A-5", LEAD50, 0x50)
    for r in range(33, 47):
        g.eff(r, LEAD, "602")                       # vibrato + volume slide down
    g.put(47, LEAD, "===")
    g.put(0, FX, "C-4", NOISE, 0xC8)                # panning in the volume column, then pan slides
    for r in range(1, 32):
        g.eff(r, FX, "P04" if r < 16 else "P40")
    g.put(32, FX, eff="C00")
    g.put(0, BASS, "A-3", SLAP, 0x40)
    g.put(16, BASS, "A-3", SLAP, 0x40, "ED2")
    g.put(24, BASS, "E-3", BASSP, 0x30)
    g.put(28, BASS, "===")
    for r in range(0, 32, 8):
        g.put(r, DRUM, "C-4", KICK, 0x40, "ED1" if r == 24 else "000")
    for r in range(32, 48):
        g.put(r, DRUM, "C-4", SNARE, 0x18 + (r - 32) * 2, "R01")
        g.eff(r, HAT, "H10")                        # the global volume climbs back up under the roll
    for r, note in ((40, "E-3"), (42, "F-3"), (44, "G-3"), (46, "G#3")):
        g.put(r, BASS, note, BASSP, 0x38, "EA2" if r < 44 else "EB2")
    patterns.append(g)

    # Solo C1-C4: detuned saws on two channels over the Andalusian descent; C4 ends on F# major.
    solos = (("Solo C1", split(SOLO1)[0], PROG_C, A), ("Solo C2", split(SOLO1)[1], PROG_C, A),
             ("Solo C3", split(SOLO2)[0], PROG_C, A), ("Solo C4", split(SOLO2)[1], PROG_C_END, B))
    for label, notes, prog, next_root in solos:
        g = Grid(label, 128)
        drums(g, range(4), fill=int(label[-1]) % 2, crash=label.endswith(("1", "3")))
        bass_line(g, prog, next_root)
        arps(g, prog)
        pad(g, prog)
        g.melody(LEAD, 0, SAWA, notes, vol=0x40)
        row = 0
        for note, rows, _ in notes:
            if note:
                g.put(row, ECHO, note, SAWB, 0x3C)
            row += rows
        if label.endswith("1"):
            g.put(0, FX, eff="G40")
        elif label.endswith("2"):
            g.put(114, LEAD, eff="E12")                          # a fine nudge up, then vibrato on the held G#5
            for r in range(115, 128):
                g.eff(r, LEAD, "E21" if r == 118 else "4A4")  # ... and a fine nudge back down
            g.vol(118, LEAD, 0xB4)                               # the vibrato keeps running from the column
        elif label.endswith("4"):
            g.put(96, LEAD, eff="R03")
            for r in range(97, 112):
                g.eff(r, LEAD, "R03" if r < 104 else "R91")  # multi-retrig every 3 ticks, then every tick, louder
            for r in range(112, 128):
                g.eff(r, ECHO, "A02")
            g.put(120, LEAD, "===")
            g.put(120, ECHO, "===")
        patterns.append(g)

    # Key change: theme and bridge a tone higher, with bells everywhere; a held beat before the outro.
    patterns.append(section_a("Theme K1", HOOK, A, first=True, transpose=2, bells_on=True))
    patterns.append(section_a("Theme K2", HOOK2, C, first=False, transpose=2, bells_on=True, fill=1, crash=False))
    patterns.append(bridge("Bridge K3", 0, Fn, transpose=2, slide_in_column=True))
    g = bridge("Bridge K4", 1, A, transpose=2)
    g.put(127, FX, eff="EE7")                       # pattern delay: the last row is held one full beat
    g.put(127, ARP_L, vol=0x24)                     # the arpeggio rings through the held beat
    for ch in (DRUM, HAT):
        for r in range(124, 128):
            g.pattern.cells.pop((r, ch), None)      # no fill under the held beat
    g.put(124, DRUM, "C-4", SNARE, 0x48, "E91")
    g.put(126, DRUM, "C-4", KICK, 0x50)
    g.put(127, HAT, "C-4", HATO, 0x34)
    patterns.append(g)

    # Outro (64 rows, cut at row 47 with D00): stabs, ritardando, roll.
    g = Grid("Outro", 64, transpose=2)
    for r, chord in ((0, "Am"), (8, "G"), (16, "F"), (24, "E")):
        kind = CHORDS[chord][1]
        g.put(r, ARP_L, root_note(chord, 4), STAB, 0x40, kind)
        g.put(r, ARP_R, root_note(chord, 5), STAB, 0x38, kind)
        for k in range(1, 8):
            g.eff(r + k, ARP_L, kind)
            g.eff(r + k, ARP_R, kind)
        g.put(r, BASS, root_note(chord, 3), SLAP, 0x40)
        g.put(r, DRUM, "C-4", KICKHAT, 0x50)
        g.put(r + 4, DRUM, "C-4", SNAREHAT, 0x48)
    g.put(24, FX, eff="F8C")
    g.put(32, FX, eff="F82")
    g.put(40, FX, eff="F78")
    g.put(24, PAD, "E-3", PADT, 0x3C)
    g.put(24, LEAD, "B-5", LEAD50, 0x50)
    g.put(29, LEAD, vol=0xA5)
    for r in range(30, 47):
        g.vol(r, LEAD, 0xB4)
    for r in range(32, 48):
        g.put(r, DRUM, "C-4", SNARE, 0x20 + (r - 32) * 2, "R01")
        g.put(r, HAT, ("C-4", "A-3", "F-3", "D-3")[(r - 32) // 4] if r % 4 == 0 else "C-4",
              TOM if r % 4 == 0 else HATC, 0x30)
    g.put(47, FX, eff="D00")
    patterns.append(g)

    # Tail (64 rows, at the slowed tempo): the final major chord, held, the global volume fading, the jump back.
    g = Grid("Tail", 64, transpose=2)
    for k, r in enumerate((0, 8, 16, 24, 32)):      # the final chord struck on each beat, fading
        g.put(r, ARP_L, "A-4", ARP25, 0x2C - 3 * k, MAJOR)
        g.put(r, ARP_R, "C#5", ARP12, 0x26 - 3 * k, INV1[MAJOR])
        for t in range(1, 6):
            g.put(r + t, ARP_L, eff=MAJOR)
            g.put(r + t, ARP_R, eff=INV1[MAJOR])
        g.put(r + 6, ARP_L, vol=0x14, eff=MAJOR)
        g.put(r + 6, ARP_R, vol=0x10, eff=INV1[MAJOR])
    g.put(0, PAD, "A-3", PADT, 0x40)
    g.put(0, LEAD, "A-5", LEAD25, 0x50)
    g.put(0, ECHO, "E-6", LEAD50, 0x30)
    g.put(0, BELL, "A-6", BELLS, 0xCD)              # the bell sits on the right (volume-column panning)
    g.put(0, BASS, "A-3", SLAP, 0x40)
    g.put(0, DRUM, "C-4", KICK, 0x50)
    g.put(0, FX, "C-4", CRASH, 0x40)
    g.put(24, PAD, "===")
    g.put(36, LEAD, "===")
    g.put(36, ECHO, "===")
    g.put(40, BELL, eff="K01")
    for r in range(8, 44):
        g.eff(r, HAT, "H01")                        # 36 rows x 2 slide ticks: the global volume reaches zero
    g.put(63, FX, eff="B01")
    patterns.append(g)

    module.patterns = [g.pattern for g in patterns]
    names = [g.pattern.name for g in patterns]
    order_names = ["Intro", "Theme A1", "Theme A2", "Theme A1b", "Theme A3", "Bridge B", "Bridge B2", "Break",
                   "Solo C1", "Solo C2", "Solo C3", "Solo C4", "Theme K1", "Theme K2", "Bridge K3", "Bridge K4",
                   "Outro", "Tail"]
    module.orders = [names.index(n) for n in order_names]
    module.metadata["xm"]["restart_position"] = 1
    return module


def main():
    output = Path(sys.argv[1])
    module = build()
    output.parent.mkdir(parents=True, exist_ok=True)
    project.write_json(output, project.to_dict(module))
    effects, volumes = set(), set()
    for pattern in module.patterns:
        for c in pattern.cells.values():
            if c.command or c.param:
                letter = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"[c.command]
                effects.add(letter + ("%X" % (c.param >> 4) if letter == "E" else ""))
            if c.volume:
                volumes.add("%X" % (c.volume >> 4))
    print(json.dumps({"output": str(output), "patterns": [(p.name, p.rows) for p in module.patterns],
                      "orders": module.orders, "effects": sorted(effects), "volume_column": sorted(volumes)}))


if __name__ == "__main__":
    main()
