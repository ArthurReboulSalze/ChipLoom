"""Read-only structural study of MOD references, including variants we cannot edit.

Never converts, exports or executes a reference. Reports contain aggregate facts,
sample hashes and pattern relationships, not PCM or complete note sequences.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

from . import audio, mod
from .i18n import error_text
from .model import playback_plan
from .reference_layout import MAX_ARCHIVE, MAX_FILE, parse_layout


def _counts(values):
    return dict(Counter(values).most_common())


def _family(command, parameter):
    return f"E{parameter >> 4:X}x" if command == 14 else f"{command:X}xx"


def analyze_bytes(raw: bytes, name: str, probe: bool = False) -> dict:
    layout = parse_layout(raw)
    signature = raw[1080:1084].decode("ascii", errors="replace")
    channels, orders, headers = layout.channels, layout.orders, layout.headers
    pcm_size = sum(header[0] * 2 for header in headers)
    stride = 64 * channels * 4
    pattern_bytes, pattern_count = layout.pattern_bytes, layout.pattern_count
    patterns = []
    for index in range(pattern_count):
        events = []
        for offset in range(1084 + index * stride, 1084 + (index + 1) * stride, 4):
            a, b, c, d = raw[offset:offset + 4]
            events.append((((a & 15) << 8) | b, (a & 240) | (c >> 4), c & 15, d))
        patterns.append(events)

    def lane_stats(events):
        starts = [row for row, event in enumerate(events) if event[0]]
        effects = [(command, param) for _, _, command, param in events if command or param]
        return {
            "note_events": len(starts),
            "sample_commands_without_note": sum(bool(s) and not p for p, s, _, _ in events),
            "sample_slots": _counts(s for _, s, _, _ in events if s),
            "effect_families": _counts(_family(c, p) for c, p in effects),
            "note_spacing_rows": _counts(b - a for a, b in zip(starts, starts[1:])),
            "notes_by_16_rows": [sum(block <= row < block + 16 for row in starts) for block in range(0, len(events), 16)],
        }

    per_pattern = [{"index": index, "occurrences_in_order_list": orders.count(index),
        "channels": [lane_stats(events[channel::channels]) for channel in range(channels)]}
        for index, events in enumerate(patterns)]
    similarities = []
    for right in range(pattern_count):
        for left in range(right):
            a, b = patterns[left], patterns[right]
            occupied = [index for index in range(len(a)) if any(a[index]) or any(b[index])]
            equal = sum(a[index] == b[index] for index in occupied)
            ratio = equal / len(occupied) if occupied else 1.0
            if ratio >= .5:
                similarities.append({"patterns": [left, right], "matching_nonempty_cells_fraction": round(ratio, 4),
                    "identical_channels": [ch + 1 for ch in range(channels) if a[ch::channels] == b[ch::channels]]})
    cursor = 1084 + pattern_bytes
    samples = []
    for slot, (size, tune, volume, start, length) in enumerate(headers, 1):
        size, start, length = size * 2, start * 2, length * 2
        pcm = raw[cursor:cursor + size]
        cursor += size
        if size:
            samples.append({"slot": slot, "bytes": size, "volume": volume,
                "finetune": (tune & 15) - (16 if tune & 8 else 0),
                "loop_start": start, "loop_length": length if length > 2 else 0,
                "loop_within_sample": length <= 2 or start + length <= size,
                "distinct_amplitudes": len(set(pcm)), "pcm_sha256": hashlib.sha256(pcm).hexdigest()})
    all_events = [event for pattern in patterns for event in pattern]
    result = {
        "filename": name, "sha256": hashlib.sha256(raw).hexdigest(),
        "title": raw[:20].split(b"\0", 1)[0].decode("latin1").strip(),
        "bytes": len(raw), "signature": signature, "channels": channels, "restart_byte": raw[951],
        "orders": orders, "stored_patterns": pattern_count, "distinct_order_patterns": len(set(orders)),
        "pcm_bytes": pcm_size, "samples": samples,
        "stored_effect_families": _counts(_family(c, p) for _, _, c, p in all_events if c or p),
        "stored_timing_commands": _counts(f"F{p:02X}" for _, _, c, p in all_events if c == 15),
        "channels_stored": [lane_stats([event for pattern in patterns for event in pattern[ch::channels]]) for ch in range(channels)],
        "patterns": per_pattern, "similar_pattern_pairs": similarities,
        "duration_seconds": None, "loop_start_seconds": None,
        "duration_basis": "Unavailable: strict playback plan not applicable",
    }
    try:
        module = mod.decode(raw)
        plan = playback_plan(module)
        result.update(editable_in_current_profile=True, compatibility_error=None,
            duration_seconds=plan["duration_seconds"], loop_start_seconds=plan["loop_start_seconds"],
            duration_basis="Strict CIA playback plan, to first repeated replay state",
            played_rows=plan["rows"], timing_values=sorted(set((r["speed"], r["bpm"]) for r in plan["timeline"])))
    except ValueError as exc:
        result.update(editable_in_current_profile=False, compatibility_error=error_text("en", exc))
    if probe:
        executable = shutil.which("ffprobe")
        if not executable:
            raise RuntimeError("--probe requires ffprobe with libopenmpt on PATH.")
        # Only the MOD payload is written, to a disposable local folder. ZIP paths
        # never become filesystem destinations and archive content is never run.
        with tempfile.TemporaryDirectory(prefix="chiploom-reference-") as directory:
            path = Path(directory) / "reference.mod"
            path.write_bytes(raw)
            process = subprocess.run([executable, "-v", "error", "-f", "libopenmpt", "-i", str(path),
                "-show_entries", "format=duration", "-of", "json"],
                capture_output=True, text=True, timeout=20, **audio.SUBPROCESS_OPTIONS)
            if process.returncode:
                result["replay_probe_error"] = process.stderr[-1000:]
            else:
                value = json.loads(process.stdout).get("format", {}).get("duration")
                result["libopenmpt_duration_seconds"] = float(value) if value else None
                result["replay_probe_note"] = "FFprobe/libopenmpt duration estimate; does not establish editable round-trip compatibility."
    return result


def analyze_source(source: Path, probe: bool = False) -> dict:
    limit = MAX_ARCHIVE if source.suffix.lower() == ".zip" else MAX_FILE
    if source.stat().st_size > limit:
        raise ValueError("Reference input exceeds the analysis size limit.")
    original_hash = audio.sha256(source)
    entries = []
    def append(raw, name):
        try:
            entries.append(analyze_bytes(raw, name, probe))
        except (ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
            entries.append({"filename": name, "sha256": hashlib.sha256(raw).hexdigest(), "analysis_error": str(exc)})
    if source.suffix.lower() == ".zip":
        try:
            archive = zipfile.ZipFile(source)
        except zipfile.BadZipFile as exc:
            raise ValueError("Invalid ZIP reference archive.") from exc
        with archive:
            members = archive.infolist()
            if len(members) > 512 or sum(member.file_size for member in members) > MAX_ARCHIVE:
                raise ValueError("Archive exceeds 512 entries or 64 MiB expanded.")
            for member in members:
                if not member.is_dir() and member.filename.lower().endswith(".mod"):
                    if member.file_size > MAX_FILE:
                        raise ValueError("A MOD archive member exceeds 4 MiB.")
                    try:
                        payload = archive.read(member)
                    except (zipfile.BadZipFile, RuntimeError) as exc:
                        raise ValueError(f"Cannot read MOD archive member: {member.filename}") from exc
                    append(payload, member.filename)
    else:
        append(source.read_bytes(), source.name)
    if not entries:
        raise ValueError("No .mod references found.")
    if audio.sha256(source) != original_hash:
        raise RuntimeError("Source changed during analysis; discard this report and retry.")
    return {"ok": not any("analysis_error" in entry for entry in entries), "source": source.name,
        "source_sha256": original_hash, "source_unchanged": True,
        "scope": "Read-only structural facts. No PCM or full note sequences. Stored-pattern counts do not imply audible playback counts.",
        "modules": entries}
