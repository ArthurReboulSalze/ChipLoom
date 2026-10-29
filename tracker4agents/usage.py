"""How a module uses its samples: a role for every slot, a role layout for its channels, its palette and structure.

`study(module)` follows the playback timeline (as `report`) and, for each sample slot, gathers evidence of what
it is for: how the song plays it (fixed note or melody, arpeggiated, held or struck, register, density), what the
PCM looks like (`sample_library.characterize`), what the XM instrument says (envelope sustain, auto-vibrato) and a
keyword found in the slot's own name (kept only as a category, never the name). The register is the heard one:
the sample's pitch estimate (`sample_library.estimate_pitch`, relative note included) moved to the median note
the song writes for it, so a cycle written high but tuned an octave down still counts as a bass part. The evidence is scored into a
`role` (kick, snare, hat, clap, tom, cymbal, perc, bass, lead, chord, pad, pluck, texture, fx) with a
`confidence` and the reasons, so the bank can say what each sample is *for* and an agent does not pick samples
at random. The channel layout (which role each channel carries) and the structure (sections of the order list,
when channels enter and leave) describe how the song is built, without any note sequence.
"""
from __future__ import annotations

import re
import statistics

from . import loudness
from .model import NOTES, XM_KEY_OFF, Module, playback_plan
from .report import analyze
from .sample_library import characterize, estimate_pitch

ROLE_GROUPS = {**loudness.ROLES, "clap": "percussion", "tom": "percussion", "cymbal": "percussion",
               "perc": "percussion", "pad": "texture", "pluck": "lead", "fx": "texture", "unknown": "lead"}
PERCUSSION = {"kick", "snare", "hat", "clap", "tom", "cymbal", "perc"}
# The order a palette is laid into a project: drums, bass, chords, leads, pads, textures and effects.
ROLE_ORDER = ("kick", "snare", "hat", "clap", "tom", "cymbal", "perc", "bass", "chord", "lead", "pluck", "pad",
              "texture", "fx", "unknown")
ROLE_NAMES = frozenset(ROLE_ORDER)
CONFIDENCE_RANK = {"high": 2, "medium": 1, "low": 0}
# Keyword families in sample names (any language's common tracker shorthand); the name itself is never kept.
NAME_HINTS = (
    ("kick", r"kick|bdrum|bassdrum|bass drum|\bbd\b|\bkik\b|\bboom\b"),
    ("snare", r"snare|\bsd\b|\bsnr\b|\bsn\b"),
    ("hat", r"hat|\bhh\b|hihat|hi-hat|\bch\b|\boh\b"),
    ("clap", r"clap|\bclp\b"),
    ("tom", r"\btom"),
    ("cymbal", r"crash|ride|cymb|\bcym\b"),
    ("perc", r"perc|shaker|cowbell|\brim|tamb|conga|bongo"),
    ("bass", r"bass|\bbas\b|\bsub\b"),
    ("chord", r"chord|\barp|stab|\bacc\b"),
    ("pad", r"\bpad|string|choir|ambient|wash|atmo"),
    ("pluck", r"pluck|\bplk\b|piano|harp|bell|marimba|xylo"),
    ("texture", r"noise|wind|rain|hiss|\bsfx\b"),
    ("fx", r"\bfx\b|effect|\bhit\b|\bzap|laser|explo|sweep|riser"),
    ("lead", r"lead|solo|melod|\bsq\b|square|\bsaw|pulse|flute|trump|guitar|organ|synth|voice|vox"),
)
LOW_NOTE, HIGH_NOTE = 49, 73   # XM note numbers: below C-4 is a low register, from C-6 a high one
REFERENCE_NOTE = 49            # the note the pitch estimate stands at: XM C-4, or MOD C-2 (period 428) in XM numbering
LOW_HZ = 130.0                 # a melodic part whose heard median fundamental is below C-3 plays a bass part


def _name_hint(name: str) -> str | None:
    text = (name or "").casefold()
    for role, pattern in NAME_HINTS:
        if re.search(pattern, text):
            return role
    return None


def _mod_note_number(note: str) -> int:
    return NOTES.index(note) + 37   # MOD C-1 sounds as XM C-3 (number 37) on an untuned sample


def _slot_facts(module: Module) -> dict[int, dict]:
    """Per slot, what the timeline does with it: note starts, notes, arpeggios, lengths, channels."""
    plan = playback_plan(module)
    xm = module.format == "xm"
    count = module.channels
    current = [0] * count
    open_note: list[tuple[int, float] | None] = [None] * count   # (slot, seconds so far)
    facts: dict[int, dict] = {}

    def slot_entry(slot: int) -> dict:
        return facts.setdefault(slot, {"note_starts": 0, "notes": [], "arpeggio_starts": 0, "lengths": [],
                                       "channels": set(), "row_starts": 0})

    def close(channel: int) -> None:
        if open_note[channel] is not None:
            slot, seconds = open_note[channel]
            slot_entry(slot)["lengths"].append(seconds)
            open_note[channel] = None

    for item in plan["timeline"]:
        row_seconds = item["speed"] * 2.5 / item["bpm"] * (1 + item.get("delay", 0))
        pattern = module.patterns[item["pattern"]]
        for channel in range(count):
            value = pattern.get(item["row"], channel)
            if value.sample:
                current[channel] = value.sample
            key_off = xm and value.period == XM_KEY_OFF
            portamento = value.command in (3, 5) or (xm and value.volume >= 0xF0)
            starts = bool(value.period) and not key_off and not portamento
            cut = key_off or (value.command == 12 and not value.param) or (xm and value.volume == 0x10)
            if starts:
                close(channel)
                slot = current[channel]
                if slot:
                    entry = slot_entry(slot)
                    entry["note_starts"] += 1
                    entry["notes"].append(value.period if xm else _mod_note_number(value.note))
                    entry["channels"].add(channel)
                    if value.command == 0 and value.param:
                        entry["arpeggio_starts"] += 1
                    open_note[channel] = (slot, 0.0)
            elif cut:
                close(channel)
            if open_note[channel] is not None:
                open_note[channel] = (open_note[channel][0], open_note[channel][1] + row_seconds)
    for channel in range(count):
        close(channel)
    return facts


def _heard_hz(sample, median_note: float, fmt: str) -> float | None:
    """The median fundamental the song makes the sample sound at: its pitch estimate (at XM C-4 or MOD C-2,
    relative note and finetune included) moved to the median written note; None when no pitch is estimable."""
    estimate = estimate_pitch(sample, fmt)["estimated_hz_at_c2"]
    if estimate is None:
        return None
    return estimate * 2 ** ((median_note - REFERENCE_NOTE) / 12)


def _score_role(slot: int, sample, usage: dict | None, xm_meta: dict, hint: str | None,
                fmt: str = "mod") -> tuple[str, str, list[str]]:
    """(role, confidence, evidence) from the PCM, the XM instrument, the name hint and the song's use."""
    scores: dict[str, float] = {}
    evidence: list[str] = []

    def vote(role: str, weight: float, why: str) -> None:
        scores[role] = scores.get(role, 0.0) + weight
        evidence.append(f"{role} +{weight:g}: {why}")

    raw = bytes(value & 255 for value in sample.pcm) if sample.bits == 8 else \
        bytes(((value >> 8) & 255) for value in sample.pcm)
    loop_length = sample.loop_length if sample.loop_length else 0
    metrics, category, _, tags = characterize(raw, sample.loop_start, loop_length) if raw else ({}, "silent", "", [])
    envelope = xm_meta.get("volume_envelope") or {}
    sustains = bool(envelope.get("type", 0) & 2) and bool(envelope.get("points"))
    vibrato = bool((xm_meta.get("vibrato") or {}).get("depth"))
    looped = loop_length > 0
    frames = len(sample.pcm)

    # 1. the PCM shape
    if category == "cycle":
        vote("lead", 1.0, "short looped cycle")
        if "pulse" in tags or "smooth" in tags:
            vote("bass", 0.5, "pulse or smooth cycle")
        if "bright" in tags:
            vote("chord", 0.5, "bright cycle")
    elif category == "texture":
        vote("pad", 1.0, "long loop")
        vote("texture", 0.5, "long loop")
    elif category == "percussion":
        if "noise" in tags:
            vote("hat" if frames <= 600 else "snare", 1.0, f"noise one-shot of {frames} frames")
        else:
            vote("kick" if frames >= 1000 else "tom", 1.0, f"tonal one-shot of {frames} frames")
    elif category == "effect":
        vote("fx", 0.5, "short transient")
        vote("hat", 0.5, "short transient")
    # 2. the XM instrument
    if sustains and looped:
        vote("pad", 0.7, "volume envelope with a sustain point on a loop")
        vote("lead", 0.3, "volume envelope with a sustain point")
    if vibrato:
        vote("lead", 0.7, "auto-vibrato")
    # 3. the name
    if hint:
        vote(hint, 1.5, "name keyword")
    # 4. the song's use
    if usage and usage["note_starts"]:
        notes = usage["notes"]
        distinct = len(set(notes))
        dominant = max(notes.count(value) for value in set(notes)) / len(notes)
        median_note = statistics.median(notes)
        median_length = statistics.median(usage["lengths"]) if usage["lengths"] else 0.0
        arp_share = usage["arpeggio_starts"] / usage["note_starts"]
        if dominant >= 0.9 and usage["note_starts"] >= 4 and not looped:
            crossing = metrics.get("zero_crossing_rate", 0.5)
            if crossing < 0.1:
                guess = "kick" if frames >= 1000 else "tom"
            elif crossing > 0.25:
                guess = "hat" if frames <= 600 else "snare"
            else:
                guess = "snare" if frames <= 6000 else "cymbal"
            vote(guess, 1.5, f"always the same note ({usage['note_starts']} starts), one-shot")
        elif 2 <= distinct <= 4 and not looped and usage["note_starts"] >= 4 and metrics.get("zero_crossing_rate", 1) < 0.1:
            vote("tom", 1.2, f"tonal one-shot on {distinct} pitches")
        if arp_share >= 0.3 and looped:
            vote("chord", 1.5, f"{arp_share:.0%} of its notes carry an arpeggio")
        # The register is the heard one when the sample's pitch is estimable (a looped cycle written at C-4
        # with a relative note of -12, or a long loop, sounds an octave lower than written); else the written
        # note moved by the relative note.
        heard = _heard_hz(sample, median_note, fmt) if distinct >= 5 else None
        if heard is not None:
            low = heard < LOW_HZ
            register = f"heard median ~{heard:.0f} Hz"
        else:
            low = median_note + sample.relative_note < LOW_NOTE
            register = f"median written note {median_note:.0f}" + (f" {sample.relative_note:+d}" if sample.relative_note else "")
        if looped and distinct >= 5:
            if low:
                vote("bass", 1.5, f"melodic, low register ({register})")
            elif median_length >= 1.0:
                vote("pad", 1.2, f"melodic, notes held {median_length:.1f} s ({register})")
            else:
                vote("lead", 1.2, f"melodic ({distinct} pitches), notes of {median_length:.2f} s ({register})")
        if not looped and distinct >= 5:
            if low:
                vote("bass", 1.2, f"one-shot played melodically in the low register ({register})")
            else:
                vote("pluck", 1.0, f"one-shot played melodically ({distinct} pitches, {register})")
        if looped and distinct <= 2 and median_length >= 2.0:
            vote("texture", 0.8, "one or two notes held for seconds")
    if not scores:
        return "unknown", "low", evidence
    role = max(scores, key=scores.get)
    ordered = sorted(scores.values(), reverse=True)
    margin = ordered[0] - (ordered[1] if len(ordered) > 1 else 0.0)
    confidence = "high" if margin >= 1.5 or (hint == role and ordered[0] >= 2.5) else "medium" if margin >= 0.7 else "low"
    return role, confidence, evidence


def sample_role(sample, xm_meta: dict | None = None, name: str | None = None) -> tuple[str, str, list[str]]:
    """(role, confidence, evidence) of a sample outside any song: its PCM shape, the XM instrument facts
    (`volume_envelope`, `vibrato` as the importer stores them) and a keyword family of `name` (not kept)."""
    return _score_role(0, sample, None, xm_meta or {}, _name_hint(name or ""))


def role_summary(roles: list[str]) -> str:
    """One line such as `kick snare hat · bass · chord · lead×2`: roles in palette order, grouped."""
    counts = {role: roles.count(role) for role in ROLE_ORDER if role in roles}
    groups = (("kick", "snare", "hat", "clap", "tom", "cymbal", "perc"), ("bass",), ("chord",), ("lead", "pluck"),
              ("pad", "texture"), ("fx", "unknown"))
    parts = []
    for group in groups:
        words = [f"{role}×{counts[role]}" if counts[role] > 1 else role for role in group if role in counts]
        if words:
            parts.append(" ".join(words))
    return " · ".join(parts)


def study(module: Module) -> dict:
    report = analyze(module)
    usage = _slot_facts(module)
    xm_instruments = (module.metadata.get("xm", {}) or {}).get("instruments", {}) if isinstance(module.metadata, dict) else {}
    slots = []
    for index, sample in enumerate(module.samples, 1):
        if not sample.pcm:
            continue
        use = usage.get(index)
        meta = xm_instruments.get(str(index), {}) if isinstance(xm_instruments, dict) else {}
        hint = _name_hint(sample.name) or _name_hint(str(meta.get("sample_name", "")))   # instrument, then sample name
        role, confidence, evidence = _score_role(index, sample, use, meta, hint, module.format)
        entry = {"slot": index, "role": role, "group": ROLE_GROUPS.get(role, "lead"), "confidence": confidence,
                 "name_hint": hint, "evidence": evidence, "frames": len(sample.pcm), "bits": sample.bits,
                 "looped": bool(sample.loop_length), "loop_mode": sample.loop_mode if sample.loop_length else None,
                 "note_starts": use["note_starts"] if use else 0,
                 "channels": sorted(use["channels"]) if use else [],
                 "distinct_notes": len(set(use["notes"])) if use else 0,
                 "median_note": round(statistics.median(use["notes"]), 1) if use and use["notes"] else None,
                 "median_note_seconds": round(statistics.median(use["lengths"]), 4) if use and use["lengths"] else None,
                 "arpeggio_share": round(use["arpeggio_starts"] / use["note_starts"], 3) if use and use["note_starts"] else 0.0}
        slots.append(entry)
    by_slot = {entry["slot"]: entry for entry in slots}

    channels = []
    for entry in report["channels"]:
        starts = {slot: use for slot, use in usage.items() if entry["channel"] in use["channels"]}
        played = sorted(starts, key=lambda slot: -starts[slot]["note_starts"])
        roles = [by_slot[slot]["role"] for slot in played if slot in by_slot]
        sounding = entry.get("sounding") or {}
        channels.append({"channel": entry["channel"], "role": roles[0] if roles else None,
                         "roles": sorted(set(roles)), "slots": played, "note_ons": entry["note_ons"],
                         "notes_per_second": entry["notes_per_second"],
                         "sounding_fraction": sounding.get("fraction")})

    # structure: sections of the order list where the set of playing channels stays the same
    plan = playback_plan(module)
    active_per_order: dict[int, set[int]] = {}
    seconds_per_order: dict[int, float] = {}
    for item in plan["timeline"]:
        order = item["order"]
        seconds_per_order[order] = seconds_per_order.get(order, 0.0) + item["speed"] * 2.5 / item["bpm"] * (1 + item.get("delay", 0))
        pattern = module.patterns[item["pattern"]]
        active = active_per_order.setdefault(order, set())
        for channel in range(module.channels):
            value = pattern.get(item["row"], channel)
            if value.period and not (module.format == "xm" and value.period == XM_KEY_OFF):
                active.add(channel)
    orders_played = sorted(active_per_order)
    sections = []
    for order in orders_played:
        active = active_per_order[order]
        if sections and sections[-1]["_active"] == active:
            sections[-1]["orders"] += 1
            sections[-1]["seconds"] += seconds_per_order[order]
            continue
        sections.append({"start_order": order, "orders": 1, "seconds": seconds_per_order[order],
                         "active_channels": sorted(active), "_active": active})
    for section in sections:
        section.pop("_active")
        section["seconds"] = round(section["seconds"], 3)
        section["channel_roles"] = [channels[channel]["role"] for channel in section["active_channels"]]
    entry_order = {channel["channel"]: next((order for order in orders_played if channel["channel"] in active_per_order[order]), None)
                   for channel in channels}
    structure = {"orders": len(module.orders), "orders_played": len(orders_played),
                 "distinct_patterns": len(set(module.orders)), "patterns_stored": len(module.patterns),
                 "order_patterns": list(module.orders), "duration_seconds": round(plan["duration_seconds"], 3),
                 "sections": sections, "channel_entry_order": entry_order,
                 "loop_start_seconds": plan["loop_start_seconds"]}
    layout = [channel["role"] for channel in channels]
    return {"format": module.format, "channels": module.channels, "slots": slots, "channel_layout": layout,
            "channel_details": channels, "structure": structure,
            "palette": [{"slot": entry["slot"], "role": entry["role"], "group": entry["group"],
                         "confidence": entry["confidence"]} for entry in slots if entry["note_starts"]],
            "scope": "Roles are scored from the PCM shape, the XM instrument, a keyword family of the slot's name "
                     "(the name is not kept) and how the song plays the slot; they are suggestions with their "
                     "evidence, not a listening. The structure keeps order indices, section lengths and active "
                     "channels, never notes."}
