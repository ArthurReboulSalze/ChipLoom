"""Model Context Protocol adapter: ChipLoom's CLI commands as MCP tools over stdio.

The adapter speaks JSON-RPC 2.0, one message per line, on stdin/stdout. Each tool
call runs the matching `chiploom` command in a child process, so the adapter keeps
the CLI's exact JSON contract and nothing a command prints can corrupt the protocol
stream. It has no dependency beyond the standard library and is independent of any
agent provider.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from . import __version__

PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
COMMAND_TIMEOUT = 600

S = {"type": "string"}
I = {"type": "integer"}
N = {"type": "number"}
B = {"type": "boolean"}
OPS = {"type": "array", "items": {"type": "object"},
       "description": "Patch operations, e.g. {\"op\": \"write\", \"pattern\": 0, \"channel\": 1, \"row\": 0, "
                      "\"cells\": [\"C-2 01 ...\", \"\", \"E-2 01 C20\"]}. Channels, rows, patterns and orders "
                      "count from 0, sample slots from 1. A MOD cell is 'NOTE SS EEE' (notes C-1..B-3, sharps C#2, "
                      "sample in hex, effect as 3 hex digits, '...' for none); an XM cell is 'NOTE II VV EEE' (C-0..B-7, "
                      "volume-column byte VV). Cell ops: set, write (cells down a channel, or lines across all channels), "
                      "clear, copy, move, transpose. Structure: add_pattern, remove_pattern, rename_pattern, set_orders, "
                      "insert_order, remove_order, move_order, title, timing (bpm and/or speed). Samples: sample, "
                      "library_sample, recipe_sample, apply_instrument, sample_loop/trim/gain/fade/set_pcm/match_level. "
                      "An unknown field or op is refused with the list of valid ones. Give ops or ops_file. "
                      "Fields: docs/CLI.md#operations."}
OPS_FILE = {"type": "string", "description": "Path to a JSON file holding the operations list (instead of ops), "
                                            "for large generated patches; relative to the server's root."}
RECIPE = {"type": "object", "description": "Sample recipe, e.g. {\"type\": \"wave\", \"shape\": \"pulse\", "
          "\"duty\": 0.25, \"frequency\": 130.81}. See synth_types."}


def _enum(*values: str) -> dict:
    # Typed enums: several clients (and function-calling schema converters) reject a bare "enum".
    return {"type": "string", "enum": list(values)}


ROLE = _enum("kick", "snare", "hat", "bass", "lead", "chord", "texture")
LIBRARY = {"type": "string", "description": "Sample bank folder (default: the active bank chosen in the window or "
                                            "with samples_bank, else exports/sample_library)."}


def _tool(name, description, properties, required=(), argv=None, read_only=False):
    schema = {"type": "object", "properties": properties, "additionalProperties": False}
    if required:  # An empty "required" array is rejected by draft-04 validators; leave it out.
        schema["required"] = list(required)
    return {"name": name, "description": description, "argv": argv, "inputSchema": schema,
            "annotations": {"readOnlyHint": read_only, "openWorldHint": False}}


def _flags(arguments: dict, mapping: dict) -> list[str]:
    """Turn tool arguments into CLI flags: True → --flag, lists → repeated flags."""
    result = []
    for key, flag in mapping.items():
        value = arguments.get(key)
        if value is None or value is False:
            continue
        if value is True:
            result.append(flag)
        elif isinstance(value, list):
            for item in value:
                result += [flag, str(item)]
        else:
            result += [flag, value if isinstance(value, str) else json.dumps(value) if isinstance(value, (dict, list)) else str(value)]
    return result


def _ops_json(arguments: dict) -> list[str]:
    # Operations travel through a file (a temporary one for inline ops): command lines are short on Windows.
    return ["--ops", arguments["ops_file"]]


TOOLS = [
    _tool("estimate", "Plan a song's duration before writing it (constant speed/BPM). rows is the rows played per "
          "order: 64 in a MOD, 1-256 in an XM.",
          {"orders": I, "rows": I, "speed": I, "bpm": I}, ["orders"],
          lambda a: ["estimate", *_flags(a, {"orders": "--orders", "rows": "--rows", "speed": "--speed", "bpm": "--bpm"})], True),
    _tool("validate", "Validate a JSON project or MOD; with report=true, list every independent problem with codes.",
          {"source": S, "report": B, "sample_source": _enum("synthesized", "library")}, ["source"],
          lambda a: ["validate", a["source"], *_flags(a, {"report": "--report", "sample_source": "--sample-source"})], True),
    _tool("inspect", "Summarize a project or MOD. With pattern (and grid=true), show that pattern as tracker grid text.",
          {"source": S, "pattern": I, "grid": B, "row": I, "rows": I}, ["source"],
          lambda a: ["inspect", a["source"], *_flags(a, {"pattern": "--pattern", "grid": "--grid", "row": "--row", "rows": "--rows"})], True),
    _tool("patch", "Apply patch operations to a project as one validated transaction and write the result to a new file. "
          "Read duration_seconds and warnings in the result.",
          {"source": S, "output": S, "ops": OPS, "ops_file": OPS_FILE, "label": S,
           "overwrite": {"type": "boolean", "description": "Allow output to replace an existing file (never the source)."}},
          ["source", "output"],
          lambda a: ["patch", a["source"], "--output", a["output"], *_ops_json(a),
                     *_flags(a, {"label": "--label", "overwrite": "--overwrite"})]),
    _tool("export", "Export a validated project to a real MOD file.", {"source": S, "output": S}, ["source", "output"],
          lambda a: ["export", a["source"], "--output", a["output"]]),
    _tool("render", "Render a MOD, XM or project to WAV (FFmpeg/libopenmpt), optionally an excerpt and an MP3 "
          "listening copy; mp3_normalize scales the copy to a -1 dBFS peak (the WAV keeps the engine's level).",
          {"source": S, "output": S, "seconds": N, "from_order": I, "engine": _enum("openmpt", "xmp"), "mp3_output": S,
           "mp3_normalize": B},
          ["source", "output"],
          lambda a: ["render", a["source"], "--output", a["output"], *_flags(a, {
              "seconds": "--seconds", "from_order": "--from-order", "engine": "--engine", "mp3_output": "--mp3-output",
              "mp3_normalize": "--mp3-normalize"})]),
    _tool("preview", "Build a portable HTML listening bundle in a new directory.",
          {"source": S, "output": S, "mp3": B, "language": _enum("en", "fr")}, ["source", "output"],
          lambda a: ["preview", a["source"], "--output", a["output"], *_flags(a, {"mp3": "--mp3", "language": "--language"})]),
    _tool("lint", "List cells whose effect does nothing or not what the score suggests (a 9xx or E5x without a "
          "note, an XM instrument number without a note, Rxy cancelled by the volume column, K00, slides with both "
          "nibbles, E9x/ECx/EDx past the row's ticks, portamento with no note, held 0xy arpeggios), with the reason.",
          {"source": S}, ["source"], lambda a: ["lint", a["source"]], True),
    _tool("report", "Measure a composition: density, ranges, gaps, repetition, held arpeggios, estimated key, unused samples, "
          "sample sources and loudness against the reference levels (exports/sample_library when it exists, "
          "unless library is given; else fixed levels). The key estimate leaves out percussion slots. "
          "Channels count from 0.",
          {"source": S, "library": LIBRARY}, ["source"],
          lambda a: ["report", a["source"], *_flags(a, {"library": "--library"})], True),
    _tool("compare", "Build a blind A/B listening page comparing two versions in a new directory. The X/Y answer "
          "is written to answer_key.json (path in answer_key_file), not returned; do not read it before the "
          "owner has listened. equalize=true matches both renders to the same integrated loudness.",
          {"first": S, "second": S, "output": S, "mp3": B, "language": _enum("en", "fr"), "seed": I, "seconds": N,
           "equalize": B},
          ["first", "second", "output"],
          lambda a: ["compare", a["first"], a["second"], "--output", a["output"], *_flags(a, {
              "mp3": "--mp3", "language": "--language", "seed": "--seed", "seconds": "--seconds",
              "equalize": "--equalize"})]),
    _tool("feedback", "Record listening feedback in a project's metadata, written to a new project file; pattern "
          "(with row, rows, channel, channels) ties it to a block of the score.",
          {"project": S, "text": S, "rating": I, "output": S, "version": S, "pattern": I, "row": I, "rows": I,
           "channel": I, "channels": I}, ["project", "text", "output"],
          lambda a: ["feedback", a["project"], "--output", a["output"], *_flags(a, {
              "text": "--text", "rating": "--rating", "version": "--version", "pattern": "--pattern",
              "row": "--row", "rows": "--rows", "channel": "--channel", "channels": "--channels"})]),
    _tool("migrate", "Rewrite a v1 project (or a MOD) as a compact v2 project.", {"source": S, "output": S},
          ["source", "output"], lambda a: ["migrate", a["source"], "--output", a["output"]]),
    _tool("samples_list", "Search the local sample library by text, tags, category, scored role (kick, snare, hat, "
          "clap, tom, cymbal, perc, bass, chord, lead, pluck, pad, texture, fx), origin format and MOD compatibility.",
          {"library": LIBRARY, "query": S, "tag": {"type": "array", "items": S}, "category": S, "role": S,
           "format": _enum("mod", "xm"), "compatible": B, "offset": I, "limit": I}, (),
          lambda a: ["samples", "list", *_flags(a, {"library": "--library", "query": "--query", "tag": "--tag",
                                                    "category": "--category", "role": "--role", "format": "--format",
                                                    "compatible": "--compatible", "offset": "--offset",
                                                    "limit": "--limit"})], True),
    _tool("samples_palettes", "List the bank's palettes: for each reference song, the entries it played together "
          "(one-line role summary such as 'kick snare hat · bass · chord · lead×2'), format, channels, speed, BPM "
          "and duration. Pick a palette (or samples by role) instead of samples at random.",
          {"library": LIBRARY, "role": S, "format": _enum("mod", "xm"), "channels": I}, (),
          lambda a: ["samples", "palettes", *_flags(a, {"library": "--library", "role": "--role", "format": "--format",
                                                        "channels": "--channels"})], True),
    _tool("samples_palette", "Show one palette: its entries with role, confidence and how much the song plays them, "
          "the role of every channel, and the structure (orders, distinct patterns, sections, channel entry order). "
          "Insert it with the CLI `samples use-palette` or one samples_add per entry in role order.",
          {"library": LIBRARY, "id": S}, ["id"],
          lambda a: ["samples", "palette", a["id"], *_flags(a, {"library": "--library"})], True),
    _tool("samples_inspect", "Show one library sample's measurements, labels, compatibility and estimated pitch at C-2 "
          "(for a looped cycle it follows the loop length).",
          {"library": LIBRARY, "id": S}, ["id"],
          lambda a: ["samples", "inspect", a["id"], *_flags(a, {"library": "--library"})], True),
    _tool("samples_preview", "Render a library sample at a note to a WAV file for audition, with measured peak, RMS, "
          "loudness and estimated pitch.",
          {"library": LIBRARY, "id": S, "output": S, "note": S, "seconds": N}, ["id", "output"],
          lambda a: ["samples", "preview", a["id"], "--output", a["output"], *_flags(a, {
              "library": "--library", "note": "--note", "seconds": "--seconds"})]),
    _tool("samples_add", "Insert a library sample into a project slot and write a new project.",
          {"library": LIBRARY, "id": S, "project": S, "output": S, "slot": I, "replace": B, "adapt": B},
          ["id", "project", "output"],
          lambda a: ["samples", "add", a["id"], "--project", a["project"], "--output", a["output"], *_flags(a, {
              "library": "--library", "slot": "--slot", "replace": "--replace", "adapt": "--adapt"})]),
    _tool("samples_bank", "Show the active sample bank (the one the window and the agent share: path, entry count, "
          "recent banks), or make another folder the active bank with `set`, or create an empty one with `new`.",
          {"set": S, "new": S}, (),
          lambda a: ["samples", "bank", *_flags(a, {"set": "--set", "new": "--new"})]),
    _tool("samples_slots", "List the samples of a MOD, XM or JSON project: name, frames, bits, loop, the role scored "
          "from how the song plays it, the measured tuning (the note it sounds when C is written) and the bank entry "
          "that already holds it.",
          {"library": LIBRARY, "module": S}, ["module"],
          lambda a: ["samples", "slots", a["module"], *_flags(a, {"library": "--library"})], True),
    _tool("samples_import_slot", "Add one sample of a MOD, XM or JSON project to the bank with the owner's name, role, "
          "category and tags (defaults: its own name, the scored role). A sample already in the bank is not added "
          "twice.",
          {"library": LIBRARY, "module": S, "slot": I, "name": S, "role": S, "category": S,
           "tag": {"type": "array", "items": S}}, ["module", "slot"],
          lambda a: ["samples", "import-slot", a["module"], "--slot", str(a["slot"]), *_flags(a, {
              "library": "--library", "name": "--name", "role": "--role", "category": "--category", "tag": "--tag"})]),
    _tool("samples_import_wav", "Add a PCM WAV file to the bank (mixed to mono; 16-bit when the file has more than 8 "
          "bits; C-4 plays it at its own rate), with name, role, category, tags and an optional loop in frames.",
          {"library": LIBRARY, "wav": S, "name": S, "role": S, "category": S, "tag": {"type": "array", "items": S},
           "loop_start": I, "loop_length": I}, ["wav"],
          lambda a: ["samples", "import-wav", a["wav"], *_flags(a, {
              "library": "--library", "name": "--name", "role": "--role", "category": "--category", "tag": "--tag",
              "loop_start": "--loop-start", "loop_length": "--loop-length"})]),
    _tool("samples_edit", "Rename a bank entry, set its category, tags or role, or store a tuning correction "
          "(`semitones`, 12 = an octave; `cents` -100..100) applied whenever it is inserted.",
          {"library": LIBRARY, "id": S, "name": S, "category": S, "tag": {"type": "array", "items": S}, "role": S,
           "semitones": I, "cents": I}, ["id"],
          lambda a: ["samples", "edit", a["id"], *_flags(a, {
              "library": "--library", "name": "--name", "category": "--category", "tag": "--tag", "role": "--role",
              "semitones": "--semitones", "cents": "--cents"})]),
    _tool("samples_use_palette", "Insert a palette's entries into a library-mode project in role order and write a new "
          "project. The result's `tuning` says how each pitched entry is tuned against the most played one; `retune` "
          "aligns them in an XM (relative note and finetune, PCM untouched).",
          {"library": LIBRARY, "id": S, "project": S, "output": S, "slots": {"type": "array", "items": I},
           "adapt": B, "all": B, "retune": B}, ["id", "project", "output"],
          lambda a: ["samples", "use-palette", a["id"], a["project"], "--output", a["output"],
                     *(["--slots", *map(str, a["slots"])] if a.get("slots") else []), *_flags(a, {
                         "library": "--library", "adapt": "--adapt", "all": "--all", "retune": "--retune"})]),
    # Songs made only with created samples (owner's request; library samples stay the default).
    _tool("synth_types", "List the sample recipe types with parameters, ranges, defaults and purpose.", {}, (),
          lambda a: ["synth", "types"], True),
    _tool("synth_levels", "Reference loudness per role group (aggregate medians of a sample bank, or fixed defaults).",
          {"library": LIBRARY}, (), lambda a: ["synth", "levels", *_flags(a, {"library": "--library"})], True),
    _tool("synth_preview", "Render a recipe to a WAV at a tracker note, with measured peak, RMS and loudness.",
          {"recipe": RECIPE, "name": S, "output": S, "note": S, "seconds": N, "volume": I, "finetune": I, "role": ROLE},
          ["recipe", "output"],
          lambda a: ["synth", "preview", *_flags(a, {"recipe": "--recipe", "name": "--name", "output": "--output",
                                                    "note": "--note", "seconds": "--seconds", "volume": "--volume",
                                                    "finetune": "--finetune", "role": "--role"})]),
    _tool("synth_add", "Insert a created sample (recipe) into a project and write a new project; the volume is "
          "matched to the reference level of its role unless volume is given.",
          {"project": S, "recipe": RECIPE, "name": S, "output": S, "slot": I, "replace": B, "volume": I,
           "finetune": I, "role": ROLE, "match_library": LIBRARY, "no_match": B},
          ["project", "recipe", "name", "output"],
          lambda a: ["synth", "add", a["project"], *_flags(a, {
              "recipe": "--recipe", "name": "--name", "output": "--output", "slot": "--slot", "replace": "--replace",
              "volume": "--volume", "finetune": "--finetune", "role": "--role", "match_library": "--match-library",
              "no_match": "--no-match"})]),
    _tool("synth_palette", "Write a new project holding a starter palette of created samples "
          "(sample_source 'synthesized') with loudness-matched volumes. channels is 2-32 (default 4); "
          "format xm writes an XM whose instruments keep their recipes.",
          {"output": S, "title": S, "style": _enum("default"), "match_library": LIBRARY, "no_match": B,
           "channels": I, "format": _enum("mod", "xm")},
          ["output"],
          lambda a: ["synth", "palette", *_flags(a, {"output": "--output", "title": "--title", "style": "--style",
                                                    "match_library": "--match-library", "no_match": "--no-match",
                                                    "channels": "--channels", "format": "--format"})]),
    # Live session with the open ChipLoom window (or a headless `chiploom live serve`).
    _tool("live_sessions", "List running live sessions (open ChipLoom windows or headless servers).", {}, (),
          lambda a: ["live", "sessions"], True),
    _tool("live_status", "What the owner is doing in the window: open file, order, pattern, selection, playback.",
          {"session": S}, (), lambda a: ["live", *_flags(a, {"session": "--session"}), "status"], True),
    _tool("live_score", "Read the live song: overview, or one pattern as grid text.",
          {"session": S, "pattern": I, "row": I, "rows": I}, (),
          lambda a: ["live", *_flags(a, {"session": "--session"}), "score",
                     *_flags(a, {"pattern": "--pattern", "row": "--row", "rows": "--rows"})], True),
    _tool("live_patch", "Apply patch operations to the live song (visible immediately and undoable in the window). "
          "Pass base_revision from live_changes/live_status so edits that overlap the owner's newer changes are "
          "refused instead of overwriting them. With propose=true the owner accepts or rejects it in the window.",
          {"session": S, "ops": OPS, "ops_file": OPS_FILE, "label": S, "base_revision": I, "propose": B, "author": S},
          (),
          lambda a: ["live", *_flags(a, {"session": "--session"}), "patch", *_ops_json(a), *_flags(a, {
              "label": "--label", "base_revision": "--base", "propose": "--propose", "author": "--author"})]),
    _tool("live_comments", "Read the comments the owner (or an agent) attached to places in the live song: id, text, "
          "place (pattern, row, rows, channel, channels; null = whole song), the cells as they were, status, replies.",
          {"session": S, "status": _enum("open", "resolved", "all")}, (),
          lambda a: ["live", *_flags(a, {"session": "--session"}), "comments", *_flags(a, {"status": "--status"})], True),
    _tool("live_comment", "Attach a comment to a block of the live song (pattern with row, rows, channel, channels), "
          "or to the whole song when pattern is omitted. Reply to an existing comment with live_reply instead.",
          {"session": S, "text": S, "pattern": I, "row": I, "rows": I, "channel": I, "channels": I, "author": S},
          ["text"],
          lambda a: ["live", *_flags(a, {"session": "--session"}), "comment", a["text"], *_flags(a, {
              "pattern": "--pattern", "row": "--row", "rows": "--rows", "channel": "--channel",
              "channels": "--channels", "author": "--author"})]),
    _tool("live_reply", "Reply to a comment in the live song; resolve=true also marks it resolved (say what you "
          "changed), reopen=true reopens a resolved one.",
          {"session": S, "id": S, "text": S, "resolve": B, "reopen": B, "author": S}, ["id"],
          lambda a: (["live", *_flags(a, {"session": "--session"}), "resolve", a["id"],
                      *_flags(a, {"text": "--text", "reopen": "--reopen", "author": "--author"})]
                     if a.get("resolve") or a.get("reopen") else
                     ["live", *_flags(a, {"session": "--session"}), "reply", a["id"], a.get("text", ""),
                      *_flags(a, {"author": "--author"})])),
    _tool("live_sync", "Bring a project file into the live song: the differences go as undoable patches (samples, "
          "structure and order list, then one patch per changed pattern), each checked against the revision read "
          "first so the owner's newer edits stop the sync instead of being overwritten. Lists what patches cannot "
          "carry (XM envelopes, PCM edits, metadata) under not_synced and verifies the result. dry_run only plans.",
          {"session": S, "project": S, "dry_run": B, "label": S}, ["project"],
          lambda a: ["live", *_flags(a, {"session": "--session"}), "sync", a["project"], *_flags(a, {
              "dry_run": "--dry-run", "label": "--label"})]),
    _tool("live_changes", "Changes since a revision, by author (owner or agent), as readable cell summaries.",
          {"session": S, "since": I}, (),
          lambda a: ["live", *_flags(a, {"session": "--session"}), "changes", *_flags(a, {"since": "--since"})], True),
    _tool("live_proposals", "List pending proposals and their status.", {"session": S}, (),
          lambda a: ["live", *_flags(a, {"session": "--session"}), "proposals"], True),
    _tool("live_withdraw", "Withdraw one of your pending proposals.", {"session": S, "id": S}, ["id"],
          lambda a: ["live", *_flags(a, {"session": "--session"}), "withdraw", a["id"]]),
    _tool("live_take", "Announce a new version (project file) so it appears in the window's version list.",
          {"session": S, "path": S, "label": S}, ["path", "label"],
          lambda a: ["live", *_flags(a, {"session": "--session"}), "take", a["path"], "--label", a["label"]]),
    _tool("live_takes", "List versions announced in this session.", {"session": S}, (),
          lambda a: ["live", *_flags(a, {"session": "--session"}), "takes"], True),
    _tool("live_open", "Ask the window to open a project or MOD path.", {"session": S, "path": S}, ["path"],
          lambda a: ["live", *_flags(a, {"session": "--session"}), "open", a["path"]]),
    _tool("live_play", "Start playback in the window, optionally from an order.", {"session": S, "order": I}, (),
          lambda a: ["live", *_flags(a, {"session": "--session"}), "play", *_flags(a, {"order": "--order"})]),
    _tool("live_stop", "Stop playback in the window.", {"session": S}, (),
          lambda a: ["live", *_flags(a, {"session": "--session"}), "stop"]),
    _tool("live_select", "Move the window's selection to show the owner a passage.",
          {"session": S, "pattern": I, "row": I, "rows": I, "channel": I, "channels": I}, ["pattern", "row", "channel"],
          lambda a: ["live", *_flags(a, {"session": "--session"}), "select", *_flags(a, {
              "pattern": "--pattern", "row": "--row", "rows": "--rows", "channel": "--channel", "channels": "--channels"})]),
    _tool("live_save", "Save the live song as a JSON project (its own path by default).", {"session": S, "output": S}, (),
          lambda a: ["live", *_flags(a, {"session": "--session"}), "save", *_flags(a, {"output": "--output"})]),
    # Sound workshop: sample editing on copies, drawn waves, waveform summaries and instruments.
    # Every edit is also available as a patch operation (sample_loop, sample_trim, sample_gain, sample_fade,
    # sample_set_pcm, sample_match_level, apply_instrument): see docs/CLI.md#sound-workshop.
    _tool("sample_schema", "Recipe types with parameters, ranges, defaults and limits, to build a sound form.", {}, (),
          lambda a: ["sample", "schema"], True),
    _tool("sample_edit", "Edit one sample of a project on a copy and write a new project: trim, loop, fade, gain "
          "or level-match. Order: trim, loop, fade, gain, match_level. Editing a recipe sample drops its recipe and "
          "records where it came from.",
          {"project": S, "slot": I, "output": S, "trim": {"type": "array", "items": I},
           "loop": {"type": "array", "items": I}, "no_loop": B, "fade": {"type": "array", "items": I}, "gain": N,
           "match_level": B, "role": ROLE, "library": LIBRARY, "adjust_loop": B, "adapt": B, "allow_clip": B,
           "allow_loop": B, "label": S},
          ["project", "slot", "output"],
          lambda a: ["sample", "edit", a["project"], "--slot", str(a["slot"]), "--output", a["output"],
                     *(["--trim", *map(str, a["trim"])] if "trim" in a else []),
                     *(["--loop", *map(str, a["loop"])] if "loop" in a else []),
                     *(["--fade", *map(str, a["fade"])] if "fade" in a else []),
                     *_flags(a, {"no_loop": "--no-loop", "gain": "--gain", "match_level": "--match-level",
                                 "role": "--role", "library": "--library", "adjust_loop": "--adjust-loop",
                                 "adapt": "--adapt", "allow_clip": "--allow-clip", "allow_loop": "--allow-loop",
                                 "label": "--label"})]),
    _tool("sample_draw", "Put a hand-drawn looped wave (4-256 points between -1 and 1) into a slot of a new project, "
          "as embedded PCM or, with as_recipe, as a 'draw' recipe.",
          {"project": S, "slot": I, "points": {"type": "array", "items": N}, "output": S, "cycles": I, "frequency": N,
           "peak": N, "name": S, "volume": I, "finetune": I, "replace": B, "as_recipe": B},
          ["project", "slot", "points", "output"],
          lambda a: ["sample", "draw", a["project"], "--slot", str(a["slot"]), "--points", json.dumps(a["points"]),
                     "--output", a["output"], *_flags(a, {
                         "cycles": "--cycles", "frequency": "--frequency", "peak": "--peak", "name": "--name",
                         "volume": "--volume", "finetune": "--finetune", "replace": "--replace",
                         "as_recipe": "--as-recipe"})]),
    _tool("sample_waveform", "Min/max per bucket of a slot's 8-bit PCM (or of a recipe), for drawing or for a "
          "reader that cannot listen.", {"source": S, "slot": I, "recipe": RECIPE, "buckets": I}, (),
          lambda a: ["sample", "waveform", *([a["source"]] if "source" in a else []),
                     *_flags(a, {"slot": "--slot", "recipe": "--recipe", "buckets": "--buckets"})], True),
    _tool("instruments_list", "List the instruments of an instrument folder (default exports/instruments).",
          {"dir": S, "query": S, "tag": {"type": "array", "items": S}, "role": ROLE, "offset": I, "limit": I}, (),
          lambda a: ["instruments", "list", *_flags(a, {"dir": "--dir", "query": "--query", "tag": "--tag",
                                                        "role": "--role", "offset": "--offset", "limit": "--limit"})],
          True),
    _tool("instruments_show", "Show one instrument; full=true includes embedded PCM.",
          {"dir": S, "id": S, "full": B}, ["id"],
          lambda a: ["instruments", "show", a["id"], *_flags(a, {"dir": "--dir", "full": "--full"})], True),
    _tool("instruments_save", "Save an instrument (a sample, volume, fine tune and an effect phrase) captured from a "
          "project slot, a recipe or a library ID.",
          {"dir": S, "name": S, "project": S, "slot": I, "recipe": RECIPE, "library_id": S,
           "phrase": {"type": "array", "items": S}, "role": ROLE, "tag": {"type": "array", "items": S},
           "volume": I, "finetune": I, "embed": B, "id": S, "replace": B},
          ["name"],
          lambda a: ["instruments", "save", *_flags(a, {
              "dir": "--dir", "name": "--name", "project": "--project", "slot": "--slot", "recipe": "--recipe",
              "library_id": "--library-id", "role": "--role", "tag": "--tag", "volume": "--volume",
              "finetune": "--finetune", "embed": "--embed", "id": "--id", "replace": "--replace"}),
              *(["--phrase", json.dumps(a["phrase"])] if "phrase" in a else [])]),
    _tool("instruments_delete", "Delete one instrument file from the instrument folder.",
          {"dir": S, "id": S}, ["id"],
          lambda a: ["instruments", "delete", a["id"], *_flags(a, {"dir": "--dir"})]),
    _tool("instruments_apply", "Write an instrument's note and effect phrase into a pattern channel of a project "
          "(inserting or reusing its sample) and write a new project.",
          {"project": S, "output": S, "pattern": I, "channel": I, "row": I, "note": S, "instrument": S,
           "inline": {"type": "object"}, "slot": I, "replace": B, "length": I, "overwrite": B, "library": LIBRARY,
           "dir": S, "label": S},
          ["project", "output", "pattern", "channel", "row", "note"],
          lambda a: ["instruments", "apply", a["project"], "--output", a["output"], *_flags(a, {
              "pattern": "--pattern", "channel": "--channel", "row": "--row", "note": "--note",
              "instrument": "--instrument", "inline": "--inline", "slot": "--slot", "replace": "--replace",
              "length": "--length", "overwrite": "--overwrite", "library": "--library", "dir": "--dir",
              "label": "--label"})]),
    # Multi-channel MOD and XM (appended: existing tools keep their order and schemas).
    _tool("convert", "Convert between MOD and XM: a MOD to XM keeps its notes, effects and PCM (the report lists what an XM "
          "plays differently) and its sample recipes; an XM to MOD only when it fits, otherwise refused with a list "
          "of reasons. The output extension (.mod or .xm) or `to` picks the target; a .json output without `to` "
          "gets the other format than the source's.",
          {"source": S, "output": S, "to": _enum("mod", "xm")}, ["source", "output"],
          lambda a: ["convert", a["source"], "--output", a["output"], *_flags(a, {"to": "--to"})]),
    _tool("export_format", "Export a project as a MOD or an XM file (a project of the other format is converted first). "
          "`format` defaults to the output extension.",
          {"source": S, "output": S, "format": _enum("mod", "xm")}, ["source", "output"],
          lambda a: ["export", a["source"], "--output", a["output"], *_flags(a, {"format": "--format"})]),
    _tool("new_project", "Write a blank project to start a song: empty patterns in order, one empty sample slot, "
          "initial speed/BPM and the channel count (4 by default; 2-32, other counts than 4 use the "
          "protracker-nch-pal-v1 profile). sample_source defaults to library (fill slots with samples_add or "
          "library_sample); use synth_palette instead for a synthesized-only song. format xm writes an XM: "
          "patterns of rows rows (1-256, default 64) and speed/BPM in its header.",
          {"output": S, "title": S, "format": _enum("mod", "xm"), "channels": I, "patterns": I, "rows": I,
           "speed": I, "bpm": I, "sample_source": _enum("library", "synthesized", "mixed", "none")}, ["output"],
          lambda a: ["new", "--output", a["output"], *_flags(a, {
              "title": "--title", "format": "--format", "channels": "--channels", "patterns": "--patterns",
              "rows": "--rows", "speed": "--speed", "bpm": "--bpm", "sample_source": "--sample-source"})]),
]
TOOLS_BY_NAME = {tool["name"]: tool for tool in TOOLS}


def _check(arguments: object, schema: dict) -> dict:
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise ValueError("arguments must be an object.")
    unknown = set(arguments) - set(schema["properties"])
    if unknown:
        raise ValueError(f"unknown arguments {sorted(unknown)}.")
    missing = [key for key in schema.get("required", ()) if key not in arguments]
    if missing:
        raise ValueError(f"missing arguments {missing}.")
    kinds = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list, "object": dict}
    for key, value in arguments.items():
        expected = schema["properties"][key]
        kind = expected.get("type")
        if "enum" in expected and value not in expected["enum"]:
            raise ValueError(f"{key}: one of {expected['enum']} expected.")
        if kind and (not isinstance(value, kinds[kind]) or (kind in ("integer", "number") and isinstance(value, bool))):
            raise ValueError(f"{key}: {kind} expected.")
    return arguments


def cli_prefix() -> list[str]:
    """How to start the CLI: the interpreter with `-m`, or the frozen chiploom-cli itself, which takes no `-m`."""
    return [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, "-m", "tracker4agents"]


def run_command(argv: list[str], cwd: Path | None = None) -> tuple[bool, dict]:
    """Run one CLI command in a child process and return (ok, JSON payload)."""
    environment = dict(os.environ, PYTHONIOENCODING="utf-8")
    try:
        completed = subprocess.run([*cli_prefix(), *argv], cwd=cwd, capture_output=True,
                                   text=True, encoding="utf-8", timeout=COMMAND_TIMEOUT, env=environment,
                                   stdin=subprocess.DEVNULL,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    except subprocess.TimeoutExpired:
        return False, {"ok": False, "code": "TIMEOUT", "message": f"Command exceeded {COMMAND_TIMEOUT} seconds."}
    text = completed.stdout if completed.returncode == 0 else completed.stderr
    try:
        payload = json.loads(text)
    except ValueError:
        payload = {"ok": completed.returncode == 0, "output": text.strip()[-4000:]}
        if completed.returncode:
            payload.update(code="CLI_ERROR", message=(completed.stderr or completed.stdout).strip()[-4000:])
    return completed.returncode == 0, payload


class Server:
    def __init__(self, cwd: Path | None = None):
        self.cwd = cwd
        self.protocol = PROTOCOL_VERSIONS[0]

    def handle(self, message: object) -> dict | None:
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return self._error(None, -32600, "Invalid Request")
        identifier, method = message.get("id"), message.get("method")
        if "method" not in message and ("result" in message or "error" in message):
            return None  # A client's answer to a request we never send: nothing to reply to.
        if not isinstance(method, str):
            return self._error(identifier, -32600, "Invalid Request") if "id" in message else None
        if "id" not in message:
            return None  # Notifications such as notifications/initialized need no answer.
        params = message.get("params") or {}
        if method == "initialize":
            requested = params.get("protocolVersion") if isinstance(params, dict) else None
            self.protocol = requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
            return self._result(identifier, {
                "protocolVersion": self.protocol, "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "chiploom", "title": "ChipLoom", "version": __version__},
                "instructions": "ChipLoom composes tracker music: MOD with 4 channels by default or up to 32, and XM. "
                                "Plan with estimate, start with new_project (channels, speed, BPM; library samples by "
                                "default) or synth_palette (synthesized-only), edit with patch operations (channels "
                                "count from 0, sample slots from 1), validate, export the real MOD, render to listen. "
                                "When the owner has the ChipLoom window open, use the live_* tools to compose together; "
                                "read live_changes before editing and pass base_revision to respect their edits."})
        if method == "ping":
            return self._result(identifier, {})
        if method == "tools/list":
            tools = [{key: tool[key] for key in ("name", "description", "inputSchema", "annotations")} for tool in TOOLS]
            return self._result(identifier, {"tools": tools})
        if method == "tools/call":
            if not isinstance(params, dict) or params.get("name") not in TOOLS_BY_NAME:
                return self._error(identifier, -32602, f"Unknown tool: {params.get('name') if isinstance(params, dict) else None}")
            tool = TOOLS_BY_NAME[params["name"]]
            try:
                arguments = _check(params.get("arguments"), tool["inputSchema"])
            except ValueError as exc:
                # Since protocol 2025-11-25 a bad argument is a tool execution error the model can read and
                # correct, not a protocol error; the other versions allow the same result shape.
                message_text = f"{tool['name']}: {exc}"
                return self._result(identifier, self._tool_result(False, {
                    "ok": False, "error": "InvalidArguments", "code": "INVALID_ARGUMENTS", "message": message_text}))
            if "ops" in tool["inputSchema"]["properties"] and ("ops" in arguments) == ("ops_file" in arguments):
                return self._result(identifier, self._tool_result(False, {
                    "ok": False, "error": "InvalidArguments", "code": "INVALID_ARGUMENTS",
                    "message": f"{tool['name']}: give either ops or ops_file."}))
            ops_file = None
            try:
                if "ops" in arguments:
                    descriptor, ops_file = tempfile.mkstemp(prefix="chiploom-ops-", suffix=".json")
                    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                        json.dump(arguments["ops"], stream, ensure_ascii=False)
                    arguments = {**arguments, "ops_file": ops_file}
                ok, payload = run_command(tool["argv"](arguments), self.cwd)
            finally:
                if ops_file:
                    os.unlink(ops_file)
            return self._result(identifier, self._tool_result(ok, payload))
        return self._error(identifier, -32601, f"Method not found: {method}")

    @staticmethod
    def _tool_result(ok: bool, payload: object) -> dict:
        if not isinstance(payload, dict):  # structuredContent must be a JSON object.
            payload = {"result": payload}
        return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)}],
                "structuredContent": payload, "isError": not ok}

    @staticmethod
    def _result(identifier, result):
        return {"jsonrpc": "2.0", "id": identifier, "result": result}

    @staticmethod
    def _error(identifier, code, message):
        return {"jsonrpc": "2.0", "id": identifier, "error": {"code": code, "message": message}}

    def serve(self, stdin=None, stdout=None) -> int:
        stdin = stdin or sys.stdin
        stdout = stdout or sys.stdout
        for line in stdin:
            if not line.strip():
                continue
            try:
                message = json.loads(line)
            except ValueError:
                response = self._error(None, -32700, "Parse error")
            else:
                if isinstance(message, list):
                    responses = [answer for item in message if (answer := self.handle(item)) is not None]
                    response = responses or None
                else:
                    response = self.handle(message)
            if response is not None:
                stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
                stdout.flush()
        return 0


def main(cwd: Path | None = None) -> int:
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        # Exactly LF between messages: Windows text mode would otherwise write CR LF.
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    return Server(cwd).serve()
