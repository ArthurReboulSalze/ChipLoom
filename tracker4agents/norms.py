"""Articulation norms measured on the owner's reference modules (MOD and XM), for the agent skill to cite.

`measure(module)` follows the playback timeline (as `report` does) and returns durations and proportions only:
how long a note keeps an `0xy` arpeggio before it is struck again or cut, how notes end (the next note, a key off,
a cut), how much of the song each channel sounds and how often it rests, how dense each channel is. No note
names, sequences or patterns are kept, so nothing here can reproduce a reference: the numbers describe how the
references *play*, not what they play.

`norms(sources)` reads files, folders and ZIP archives, measures every module the importer accepts (others are
counted by reason), and aggregates the measurements into percentiles over the whole selection and over the
per-module medians, so a long song does not outweigh the others. With `details=True` the per-module results
(with file names) are included; they are for local use only. Publish the aggregate, which names no file.
"""
from __future__ import annotations

import statistics
import zipfile
from pathlib import Path

from . import formats
from .model import XM_KEY_OFF, Module, ValidationError, playback_plan
from .report import analyze

SCHEMA = "chiploom.norms.v1"
MAX_FILE = 8 * 1024 * 1024
MAX_ARCHIVE = 256 * 1024 * 1024
MAX_MODULES = 1000
EXTENSIONS = (".mod", ".xm")
PERCENTILES = (10, 25, 50, 75, 90)


def _percentiles(values: list[float]) -> dict | None:
    if not values:
        return None
    ordered = sorted(values)
    result = {"count": len(ordered)}
    for p in PERCENTILES:
        position = (len(ordered) - 1) * p / 100
        low, high = int(position), min(int(position) + 1, len(ordered) - 1)
        result[f"p{p}"] = round(ordered[low] + (ordered[high] - ordered[low]) * (position - low), 4)
    return result


def _median(values: list[float]) -> float | None:
    return round(statistics.median(values), 4) if values else None


def measure(module: Module) -> dict:
    """Durations and proportions of one module along its playback timeline (no notes, no patterns)."""
    plan = playback_plan(module)
    timeline = plan["timeline"]
    xm = module.format == "xm"
    count = module.channels
    note_seconds: list[float] = []
    endings = {"next_note": 0, "key_off": 0, "cut": 0, "song_end": 0}
    arpeggio_runs: list[tuple[int, float, float]] = []   # (rows, seconds, ticks) of every run, short or long
    open_note: list[float | None] = [None] * count      # seconds since the channel's note started
    arp_run: list[list | None] = [None] * count          # [rows, seconds, ticks]
    note_starts = [0] * count
    arpeggio_starts = [0] * count
    rows_with_arpeggio = [0] * count

    def end_note(channel: int, kind: str, extra: float = 0.0) -> None:
        if open_note[channel] is not None:
            note_seconds.append(open_note[channel] + extra)
            endings[kind] += 1
            open_note[channel] = None

    def end_run(channel: int) -> None:
        if arp_run[channel] is not None:
            arpeggio_runs.append(tuple(arp_run[channel]))
            arp_run[channel] = None

    for item in timeline:
        tick = 2.5 / item["bpm"]
        row_ticks = item["speed"] * (1 + item.get("delay", 0))
        row_seconds = row_ticks * tick
        pattern = module.patterns[item["pattern"]]
        for channel in range(count):
            value = pattern.get(item["row"], channel)
            portamento = value.command in (3, 5) or (xm and value.volume >= 0xF0)
            key_off = xm and value.period == XM_KEY_OFF
            starts = bool(value.period) and not key_off and not portamento
            arpeggio = value.command == 0 and value.param != 0
            cut_now = (value.command == 12 and value.param == 0) or (xm and value.volume == 0x10)
            cut_tick = value.param & 15 if value.command == 14 and value.param >> 4 == 12 else None
            if starts:
                end_note(channel, "next_note")
                end_run(channel)
                open_note[channel] = 0.0
                note_starts[channel] += 1
                if arpeggio:
                    arpeggio_starts[channel] += 1
            elif key_off:
                end_note(channel, "key_off")
                end_run(channel)
            elif cut_now:
                end_note(channel, "cut")
                end_run(channel)
            if arpeggio and open_note[channel] is not None and not cut_now:
                rows_with_arpeggio[channel] += 1
                run = arp_run[channel]
                if run is None:
                    arp_run[channel] = [1, row_seconds, row_ticks]
                else:
                    run[0] += 1
                    run[1] += row_seconds
                    run[2] += row_ticks
            elif not starts:
                end_run(channel)
            if cut_tick is not None and open_note[channel] is not None and cut_tick < item["speed"]:
                end_note(channel, "cut", cut_tick * tick)
                end_run(channel)
            elif open_note[channel] is not None:
                open_note[channel] += row_seconds
    for channel in range(count):
        end_note(channel, "song_end")
        end_run(channel)

    report = analyze(module)
    channels = []
    duration = plan["duration_seconds"] or 1.0
    for entry in report["channels"]:
        index = entry["channel"]
        if not entry["note_ons"]:
            continue
        sounding = entry.get("sounding") or {}
        channels.append({
            "notes_per_second": entry["notes_per_second"],
            "sounding_fraction": sounding.get("fraction"),
            "longest_run_seconds": sounding.get("longest_run_seconds"),
            "rests_per_minute": round(sounding.get("rests", 0) * 60 / duration, 3) if sounding else None,
            "arpeggio_note_share": round(arpeggio_starts[index] / note_starts[index], 4) if note_starts[index] else 0.0,
            "arpeggio_rows": rows_with_arpeggio[index],
        })
    ended = sum(endings.values()) or 1
    sustain = report["global"].get("sustain") or {}
    return {
        "format": module.format, "channels": module.channels, "duration_seconds": round(plan["duration_seconds"], 3),
        "speed": timeline[0]["speed"], "bpm": timeline[0]["bpm"],
        "note_seconds": [round(value, 4) for value in note_seconds],
        "note_endings": {key: round(value / ended, 4) for key, value in endings.items()},
        "arpeggio_run_rows": [rows for rows, _, _ in arpeggio_runs],
        "arpeggio_run_seconds": [round(seconds, 4) for _, seconds, _ in arpeggio_runs],
        "arpeggio_run_ticks": [ticks for _, _, ticks in arpeggio_runs],
        "channel_measures": channels,
        "crowded_sustain_seconds": sustain.get("longest_seconds"),
    }


def _payloads(source: Path):
    """(name, bytes) of every .mod/.xm in a file, folder (recursive) or ZIP archive."""
    if source.is_dir():
        for path in sorted(source.rglob("*")):
            if path.is_file() and path.suffix.lower() in EXTENSIONS + (".zip",):
                yield from _payloads(path)
        return
    if source.suffix.lower() == ".zip":
        if source.stat().st_size > MAX_ARCHIVE:
            raise ValidationError(f"{source.name}: archive above {MAX_ARCHIVE // 2**20} MiB.", "NORMS_INPUT")
        try:
            with zipfile.ZipFile(source) as archive:
                for member in archive.infolist():
                    if member.is_dir() or not member.filename.lower().endswith(EXTENSIONS):
                        continue
                    if member.file_size > MAX_FILE:
                        yield f"{source.name}/{member.filename}", None
                        continue
                    yield f"{source.name}/{member.filename}", archive.read(member)
        except zipfile.BadZipFile as exc:
            raise ValidationError(f"{source.name}: not a readable ZIP archive.", "NORMS_INPUT") from exc
        return
    if source.suffix.lower() in EXTENSIONS:
        yield source.name, source.read_bytes() if source.stat().st_size <= MAX_FILE else None


def norms(sources: list[Path], details: bool = False) -> dict:
    measured, skipped, entries = [], {}, []
    for source in sources:
        if not source.exists():
            raise ValidationError(f"{source}: no such file or folder.", "NORMS_INPUT")
        for name, payload in _payloads(source):
            if len(measured) + sum(skipped.values()) >= MAX_MODULES:
                break
            if payload is None:
                skipped["too_large"] = skipped.get("too_large", 0) + 1
                continue
            try:
                result = measure(formats.decode(payload))
            except (ValidationError, ValueError) as exc:
                code = getattr(exc, "code", None) or "unreadable"
                skipped[code] = skipped.get(code, 0) + 1
                continue
            measured.append(result)
            if details:
                entries.append({"file": name, **{key: value for key, value in result.items()
                                                 if key not in ("note_seconds", "arpeggio_run_rows",
                                                                "arpeggio_run_seconds", "arpeggio_run_ticks")}})
    if not measured:
        raise ValidationError("No MOD or XM module could be measured in the given sources.", "NORMS_INPUT")

    def pooled(key: str) -> list[float]:
        return [value for item in measured for value in item[key]]

    def per_channel(key: str) -> list[float]:
        return [channel[key] for item in measured for channel in item["channel_measures"] if channel[key] is not None]

    def per_module_median(key: str, channel_key: str | None = None) -> list[float]:
        values = []
        for item in measured:
            sample = ([channel[channel_key] for channel in item["channel_measures"] if channel[channel_key] is not None]
                      if channel_key else item[key])
            if sample:
                values.append(statistics.median(sample))
        return values

    arpeggio_channels = [channel for item in measured for channel in item["channel_measures"]
                         if channel["arpeggio_note_share"] >= 0.1]
    ending_totals = {key: _median([item["note_endings"][key] for item in measured]) for key in measured[0]["note_endings"]}
    formats_count, channel_counts = {}, {}
    for item in measured:
        formats_count[item["format"]] = formats_count.get(item["format"], 0) + 1
        channel_counts[str(item["channels"])] = channel_counts.get(str(item["channels"]), 0) + 1
    result = {
        "schema": SCHEMA,
        "modules": {"measured": len(measured), "skipped": skipped, "formats": formats_count,
                    "channels": dict(sorted(channel_counts.items(), key=lambda pair: int(pair[0])))},
        "arpeggio": {
            "run_rows": _percentiles(pooled("arpeggio_run_rows")),
            "run_seconds": _percentiles(pooled("arpeggio_run_seconds")),
            "run_ticks": _percentiles(pooled("arpeggio_run_ticks")),
            "run_rows_module_median": _percentiles(per_module_median("arpeggio_run_rows")),
            "modules_with_arpeggios": sum(1 for item in measured if item["arpeggio_run_rows"]),
            "channel_note_share": _percentiles([channel["arpeggio_note_share"] for channel in arpeggio_channels]),
        },
        "notes": {
            "seconds": _percentiles(pooled("note_seconds")),
            "seconds_module_median": _percentiles(per_module_median("note_seconds")),
            "endings_module_median": ending_totals,
        },
        "channels": {
            "sounding_fraction": _percentiles(per_channel("sounding_fraction")),
            "longest_run_seconds": _percentiles(per_channel("longest_run_seconds")),
            "rests_per_minute": _percentiles(per_channel("rests_per_minute")),
            "notes_per_second": _percentiles(per_channel("notes_per_second")),
        },
        "crowded_sustain_seconds": _percentiles([item["crowded_sustain_seconds"] for item in measured
                                                 if item["crowded_sustain_seconds"] is not None]),
        "tempo": {"speed": _percentiles([item["speed"] for item in measured]),
                  "bpm": _percentiles([item["bpm"] for item in measured])},
        "method": "Measured along each module's first playback cycle (as report). An arpeggio run is the rows (and ticks: "
                  "rows x speed, comparable across speeds) one note "
                  "keeps an 0xy effect before a new note, a key off or a cut (C00, XM volume 10, ECx); a note lasts "
                  "until the next note, a key off or a cut on its channel (one-shot sample ends and envelopes are "
                  "not modelled here); sounding, rests and the crowded-sustain stretch come from report. "
                  "Percentiles pool every run, note or channel of the selection; the *_module_median lines take one "
                  "median per module, so long songs do not outweigh short ones. arpeggio.channel_note_share covers "
                  "channels where at least 10% of note starts carry an arpeggio.",
        "privacy": "Aggregate durations and proportions only: no file names, titles, notes, sequences or patterns.",
    }
    if details:
        result["details"] = entries
        result["privacy"] = ("details lists file names and per-module measures for local use; publish the "
                             "aggregate without it.")
    return result
