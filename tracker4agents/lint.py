"""Tracker lint: cells whose effect does nothing, or not what the score suggests.

The lint follows the playback timeline (the same first cycle as `report`), so it knows the speed of
every row and the instrument playing on every channel. Each finding names the cell, the rule and the
reason, as FastTracker II and ProTracker play it. Findings are advice about the score, not validation
errors: a linted song still exports and plays.
"""
from __future__ import annotations

from .model import EFFECT_DIGITS, XM_KEY_OFF, Module, playback_plan
from .patch import cell_text
from .report import HELD_ARPEGGIO_SECONDS

SCHEMA = "chiploom.lint.v1"
MAX_FINDINGS = 500

# code: (kind, what the rule checks). "inert": the effect does nothing. "misleading": it does
# something other than what the cell suggests. "texture": it works, but tires the ear.
RULES = {
    "offset_without_note": ("inert", "9xx (sample offset) without a note in the same cell"),
    "offset_past_end": ("misleading", "9xx starting at or past the end of the sample"),
    "finetune_without_note": ("inert", "E5x (set finetune) without a note in the same cell"),
    "instrument_without_note": ("misleading", "XM: a new instrument number without a note keeps the playing sample"),
    "retrig_volume_ignored": ("misleading", "XM: Rxy volume change cancelled by a volume set in the volume column"),
    "key_off_k00": ("misleading", "XM: K00 in a cell, which FastTracker II handles inconsistently; write === instead"),
    "slide_both_nibbles": ("misleading", "Axy, 5xy, 6xy, Hxy or Pxy with both nibbles set: only one direction runs"),
    "tick_effect_after_row": ("inert", "E9x, ECx or EDx whose tick is not reached before the next row"),
    "portamento_without_note": ("inert", "tone portamento on a channel that has not played a note yet"),
    "effect_memory_empty": ("inert", "XM: an effect with parameter 00 (repeat the last value) before any value was set "
                                     "on the channel; MOD: 300, 400, 700 or 900 likewise"),
    "zero_parameter": ("inert", "MOD: 100, 200, A00, E10, E20, EA0 or EB0, which ProTracker does not remember"),
    "held_arpeggio": ("texture", f"one note held under an 0xy arpeggio for more than {HELD_ARPEGGIO_SECONDS} s"),
}
# Effect memory: an effect whose parameter is 00 repeats the last non-zero value of its memory slot on
# the channel. FastTracker II keeps one slot per effect (Axy, 5xy and 6xy share the volume-slide slot);
# ProTracker only remembers 3xx, 4xy, 7xy and 9xx.
XM_MEMORY = {"1": "1", "2": "2", "3": "3", "4": "4", "7": "7", "9": "9", "A": "A", "H": "H", "P": "P", "R": "R",
             "E1": "E1", "E2": "E2", "EA": "EA", "EB": "EB", "X1": "X1", "X2": "X2"}
MOD_MEMORY = {"3": "3", "4": "4", "7": "7", "9": "9"}
MOD_NO_MEMORY = {"1", "2", "A", "E1", "E2", "EA", "EB"}
SLIDE_LETTERS = {"A": "volume slide", "5": "tone portamento + volume slide", "6": "vibrato + volume slide",
                 "H": "global volume slide", "P": "panning slide"}


def lint(module: Module) -> dict:
    plan = playback_plan(module)  # validates the module as well
    timeline = plan["timeline"]
    xm = module.format == "xm"
    fmt = "xm" if xm else "mod"
    count = module.channels
    findings: dict[tuple, dict] = {}
    playing_slot = [0] * count        # the sample of the last note started on the channel
    instrument = [0] * count          # the last instrument number written on the channel
    played_note = [False] * count
    arpeggio_run: list[list | None] = [None] * count  # [timeline index, rows, seconds]
    memory: list[dict[str, int]] = [{} for _ in range(count)]  # memory slot -> last non-zero value

    def add(code: str, index: int, channel: int, message: str, **extra) -> None:
        item = timeline[index]
        key = (code, item["pattern"], item["row"], channel)
        if key in findings:
            findings[key]["times_played"] += 1
            return
        value = module.patterns[item["pattern"]].get(item["row"], channel)
        findings[key] = {"code": code, "kind": RULES[code][0], "order": item["order"], "pattern": item["pattern"],
                         "row": item["row"], "channel": channel, "cell": cell_text(value, fmt),
                         "message": message, "times_played": 1, **extra}

    def close_arpeggio(channel: int) -> None:
        run = arpeggio_run[channel]
        if run is not None and run[2] > HELD_ARPEGGIO_SECONDS:
            add("held_arpeggio", run[0], channel,
                f"One note keeps an 0xy arpeggio for {run[2]:.2f} s ({run[1]} rows) without a new note or a cut. "
                "Strike it on the rhythm instead: a new note every few rows, a quiet tail or a cut between hits.",
                rows=run[1], seconds=round(run[2], 6))
        arpeggio_run[channel] = None

    for index, item in enumerate(timeline):
        speed = item["speed"]
        row_seconds = speed * 2.5 / item["bpm"] * (1 + item.get("delay", 0))
        pattern = module.patterns[item["pattern"]]
        for channel in range(count):
            value = pattern.get(item["row"], channel)
            letter = EFFECT_DIGITS[value.command] if value.command or value.param else ""
            high, low = value.param >> 4, value.param & 15
            key_off = xm and value.period == XM_KEY_OFF
            note = bool(value.period) and not key_off
            column_porta = xm and value.volume >= 0xF0
            portamento = letter in ("3", "5") or column_porta

            # the effect's memory slot ("E1", "X2" ... for the sub-effects) and the value it carries
            name = letter + (f"{high:X}" if letter in ("E", "X") else "")
            amount = low if letter in ("E", "X") else value.param
            slot_name = (XM_MEMORY if xm else MOD_MEMORY).get(name)
            remembered = memory[channel].get(slot_name, 0) if slot_name else 0
            if slot_name and not amount and not remembered:
                add("effect_memory_empty", index, channel,
                    f"{name} with parameter 0 repeats the last value given to it on this channel, but none was given "
                    "yet, so it does nothing.")
            elif not xm and name in MOD_NO_MEMORY and not amount:
                add("zero_parameter", index, channel,
                    f"ProTracker does not remember {name}: with parameter 0 it does nothing.")
            if letter == "9":
                offset = value.param or remembered
                if not note:
                    add("offset_without_note", index, channel,
                        "A sample offset only applies to a note in the same cell; this one does nothing.")
                elif offset:
                    slot = value.sample or instrument[channel]
                    if 0 < slot <= len(module.samples):
                        frames = len(module.samples[slot - 1].pcm)
                        if offset * 256 >= frames:
                            add("offset_past_end", index, channel,
                                f"The offset ({offset * 256} frames{'' if value.param else ', repeated from memory'}) "
                                f"is at or past the end of sample {slot:02X} ({frames} frames): FastTracker II plays "
                                "nothing and ProTracker players differ.", frames=frames)
            if slot_name and amount:
                memory[channel][slot_name] = amount
            elif xm and letter in ("5", "6") and value.param:
                memory[channel]["A"] = value.param      # FastTracker II shares the volume-slide value
            if letter == "E" and high == 5 and not note:
                add("finetune_without_note", index, channel,
                    "E5x sets the finetune of a note in the same cell; without a note it does nothing.")
            if xm and value.sample and not value.period and playing_slot[channel] and value.sample != playing_slot[channel]:
                add("instrument_without_note", index, channel,
                    f"Instrument {value.sample:02X} without a note keeps sample {playing_slot[channel]:02X} playing: "
                    "FastTracker II only resets the volume and restarts the envelope. Write a note to switch sounds.")
            if xm and letter == "R" and high not in (0, 8) and 0x10 <= value.volume <= 0x50:
                add("retrig_volume_ignored", index, channel,
                    f"The volume column sets volume {value.volume - 0x10}, which FastTracker II applies after each "
                    f"retrigger, so the volume change {high:X} of R{value.param:02X} has no effect.")
            if xm and letter == "K" and not value.param:
                add("key_off_k00", index, channel,
                    "K00 conflicts with the note and volume handling of its own cell in FastTracker II; "
                    "write === in the note column for a key off.")
            if letter in SLIDE_LETTERS and high and low:
                add("slide_both_nibbles", index, channel,
                    f"{letter}{value.param:02X}: a {SLIDE_LETTERS[letter]} with both nibbles set only runs the first "
                    f"({high:X}); the second ({low:X}) is ignored.")
            if letter == "E" and high in (9, 12, 13) and low and low >= speed:
                what = {9: "retrigger", 12: "cut the note", 13: "start the note"}[high]
                add("tick_effect_after_row", index, channel,
                    f"E{high:X}{low:X} would {what} on tick {low}, but this row has {speed} ticks (speed {speed}), "
                    + ("so the note is never played in FastTracker II and players differ." if high == 13
                       else "so it never happens."))
            if portamento and not note and not played_note[channel]:
                add("portamento_without_note", index, channel,
                    "Tone portamento slides towards a note, but this channel has not played one yet.")

            # running state, after the checks
            if value.sample:
                instrument[channel] = value.sample
            starts_note = note and not portamento
            arpeggio = value.command == 0 and value.param != 0
            silenced = bool(value.period) or (xm and value.volume == 0x10) or (letter == "C" and not value.param)
            if starts_note or silenced or not arpeggio:
                close_arpeggio(channel)
            if arpeggio and not (silenced and not starts_note):
                run = arpeggio_run[channel]
                if run is None:
                    arpeggio_run[channel] = [index, 1, row_seconds]
                else:
                    run[1] += 1
                    run[2] += row_seconds
            if starts_note:
                played_note[channel] = True
                playing_slot[channel] = value.sample or instrument[channel]
    for channel in range(count):
        close_arpeggio(channel)

    ordered = sorted(findings.values(), key=lambda item: (item["order"], item["row"], item["channel"], item["code"]))
    counts: dict[str, int] = {}
    for item in ordered:
        counts[item["code"]] = counts.get(item["code"], 0) + 1
    return {
        "schema": SCHEMA, "title": module.title, "format": fmt,
        "clean": not ordered, "count": len(ordered), "counts": dict(sorted(counts.items())),
        "findings": ordered[:MAX_FINDINGS], "truncated": len(ordered) > MAX_FINDINGS,
        "rules": {code: {"kind": kind, "checks": text} for code, (kind, text) in RULES.items()},
        "scope": "Cells of the first playback cycle (as report), each listed once with times_played. Patterns "
                 "never played are not linted. Rules follow FastTracker II for an XM and ProTracker for a MOD; "
                 "a finding is advice about the score, not a validation error.",
    }
