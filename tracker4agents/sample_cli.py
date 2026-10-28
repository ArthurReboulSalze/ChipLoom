"""`chiploom sample ...`: edit a project's samples on a copy, draw waves, summarize waveforms, list recipe forms.

Every edit is a `sample_*` patch operation, so the CLI, the window and the MCP adapter share one code path.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import loudness, mod, project, sample_tools
from .document import Document
from .model import Module, ValidationError, playback_plan
from .patch import summarize
from .synth_tools import parse_recipe


def load_source(path: Path) -> Module:
    return project.load(path) if path.suffix.lower() == ".json" else mod.read(path)


def new_json(output: Path, source: Path | None = None) -> Path:
    output = output.resolve()
    if output.suffix.lower() != ".json":
        raise ValidationError("A project is written as an editable .json file.", "OUTPUT_PATH")
    if source is not None and output == source.resolve():
        raise ValidationError("The output must differ from the input project; use `patch --in-place` to edit in place.",
                              "OUTPUT_PATH")
    return output


def sample_facts(module: Module, slot: int) -> dict:
    sample = module.samples[slot - 1]
    sources = module.metadata.get("sample_sources") if isinstance(module.metadata, dict) else None
    recorded = sources.get(str(slot)) if isinstance(sources, dict) else None
    level = loudness.measure(sample)
    return {"slot": slot, "name": sample.name, "bytes": len(sample.pcm), "volume": sample.volume,
            "finetune": sample.finetune, "loop_start": sample.loop_start, "loop_length": sample.loop_length,
            "looped": bool(sample.loop_length), "recipe": sample.recipe is not None,
            "pcm_sha256": sample_tools.pcm_sha256(sample.pcm), "peak": level["peak"],
            "loudness_db": level["loudness_db"], "provenance": recorded}


def run_ops(source: Path, output: Path, ops: list[dict], label: str, slot: int | None = None) -> dict:
    """Apply sample operations to a copy of `source`, write `output`, and report what changed."""
    output = new_json(output, source)
    document = Document(load_source(source))
    applied = document.patch(ops, label)
    document.save_project(output)
    result = {"ok": True, "output": str(output), "changed": applied["changed"],
              "results": [{key: value for key, value in item.items() if key != "op"} for item in applied["results"]],
              "duration_seconds": playback_plan(document.module)["duration_seconds"],
              "changes": summarize(applied["diff"], 12)}
    if slot is not None:
        result["sample"] = sample_facts(document.module, slot)
    return result


def _points(text: str) -> list[float]:
    try:
        if text.startswith("@"):
            text = Path(text[1:]).read_text(encoding="utf-8")
        value = json.loads(text)
    except (OSError, ValueError) as exc:
        raise ValidationError(f"The points are not valid JSON: {exc}", "RECIPE_INVALID") from exc
    if not isinstance(value, list):
        raise ValidationError("points: a JSON list of 4 to 256 numbers between -1 and 1.", "RECIPE_INVALID")
    return value


def add_parser(subparsers) -> argparse.ArgumentParser:
    sample = subparsers.add_parser("sample", help="Edit samples on a copy (loop, trim, gain, fade), draw waves, "
                                                  "waveform summaries, recipe form schema.")
    commands = sample.add_subparsers(dest="sample_tool_command", required=True)
    edit = commands.add_parser("edit", help="Loop, trim, fade, gain or level-match one sample; writes a new project.")
    edit.add_argument("project", type=Path)
    edit.add_argument("--slot", type=int, required=True, help="Sample slot 1-31.")
    edit.add_argument("--output", type=Path, required=True, help="New .json project, different from the input.")
    edit.add_argument("--trim", nargs=2, type=int, metavar=("START", "END"),
                      help="Keep the PCM bytes in [START, END) (even offsets).")
    loop = edit.add_mutually_exclusive_group()
    loop.add_argument("--loop", nargs=2, type=int, metavar=("START", "LENGTH"), help="Loop start and length in bytes.")
    loop.add_argument("--no-loop", action="store_true", help="Remove the loop.")
    edit.add_argument("--fade", nargs=2, type=int, metavar=("IN", "OUT"), help="Fade-in and fade-out lengths in bytes.")
    edit.add_argument("--gain", type=float, metavar="DB", help="Gain in dB, refused if it would clip.")
    edit.add_argument("--match-level", action="store_true",
                      help="Set the volume (and gain if needed) to the role's reference level.")
    edit.add_argument("--role", choices=sorted(loudness.ROLES), help="Role for --match-level.")
    edit.add_argument("--library", type=Path, help="Sample bank whose levels --match-level uses (default: fixed levels).")
    edit.add_argument("--adjust-loop", action="store_true", help="Let --trim cut into the loop and keep what is left.")
    edit.add_argument("--adapt", action="store_true",
                      help="Prepend two zero bytes when a sample without a loop would not start with them.")
    edit.add_argument("--allow-clip", action="store_true", help="Let --gain clamp bytes instead of refusing.")
    edit.add_argument("--allow-loop", action="store_true", help="Let --fade reach into the loop.")
    edit.add_argument("--label", default="Edit sample")
    draw = commands.add_parser("draw", help="Put a hand-drawn looped wave into a slot of a new project.")
    draw.add_argument("project", type=Path)
    draw.add_argument("--slot", type=int, required=True)
    draw.add_argument("--points", required=True, help="JSON list of 4-256 values in -1..1, or @file.json.")
    draw.add_argument("--output", type=Path, required=True)
    draw.add_argument("--cycles", type=int, default=16)
    draw.add_argument("--frequency", type=float, default=261.625565, help="Pitch heard at note C-2.")
    draw.add_argument("--peak", type=float, default=0.88)
    draw.add_argument("--name", default="Drawn")
    draw.add_argument("--volume", type=int)
    draw.add_argument("--finetune", type=int)
    draw.add_argument("--replace", action="store_true", help="Overwrite an occupied slot.")
    draw.add_argument("--as-recipe", action="store_true",
                      help="Keep the drawing as a 'draw' recipe instead of embedded PCM (works in synthesized projects).")
    waveform = commands.add_parser("waveform", help="Min/max per bucket of a slot's PCM (or of a recipe) for drawing.")
    waveform.add_argument("source", type=Path, nargs="?", help="Project or MOD (with --slot).")
    waveform.add_argument("--slot", type=int)
    waveform.add_argument("--recipe", help="Recipe JSON, or @file.json, instead of a project slot.")
    waveform.add_argument("--buckets", type=int, default=128)
    commands.add_parser("schema", help="Recipe types, parameters, ranges, defaults and limits for building a form.")
    return sample


def _edit_ops(args: argparse.Namespace) -> list[dict]:
    slot = {"slot": args.slot}
    ops = []
    if args.trim:
        ops.append({"op": "sample_trim", **slot, "start": args.trim[0], "end": args.trim[1],
                    "adjust_loop": args.adjust_loop, "adapt": args.adapt})
    if args.loop:
        ops.append({"op": "sample_loop", **slot, "loop_start": args.loop[0], "loop_length": args.loop[1],
                    "adapt": args.adapt})
    if args.no_loop:
        ops.append({"op": "sample_loop", **slot, "loop_start": 0, "loop_length": 0, "adapt": args.adapt})
    if args.fade:
        ops.append({"op": "sample_fade", **slot, "fade_in": args.fade[0], "fade_out": args.fade[1],
                    "allow_loop": args.allow_loop})
    if args.gain is not None:
        ops.append({"op": "sample_gain", **slot, "db": args.gain, "allow_clip": args.allow_clip})
    if args.match_level:
        op = {"op": "sample_match_level", **slot}
        if args.role:
            op["role"] = args.role
        if args.library:
            op["library"] = str(args.library)
        ops.append(op)
    if not ops:
        raise ValidationError("Give at least one of --trim, --loop, --no-loop, --fade, --gain, --match-level.",
                              "PATCH_FIELD")
    return ops


def run(args: argparse.Namespace) -> dict:
    action = args.sample_tool_command
    if action == "schema":
        return sample_tools.recipe_schema()
    if action == "edit":
        return run_ops(args.project, args.output, _edit_ops(args), args.label, args.slot)
    if action == "draw":
        points = _points(args.points)
        if args.as_recipe:
            recipe = {"type": "draw", "points": points, "cycles": args.cycles, "frequency": args.frequency,
                      "peak": args.peak}
            op = {"op": "recipe_sample", "name": args.name, "recipe": recipe, "slot": args.slot,
                  "replace": args.replace}
            for key, value in (("volume", args.volume), ("finetune", args.finetune)):
                if value is not None:
                    op[key] = value
        else:
            pcm = sample_tools.draw_to_pcm(points, args.cycles, args.frequency, args.peak)
            op = {"op": "sample_set_pcm", "slot": args.slot, "name": args.name, "replace": args.replace,
                  **sample_tools.pcm_fields(pcm)}
            for key, value in (("volume", args.volume), ("finetune", args.finetune)):
                if value is not None:
                    op[key] = value
        return run_ops(args.project, args.output, [op], "Draw sample", args.slot)
    if action == "waveform":
        if (args.recipe is None) == (args.source is None):
            raise ValidationError("Give either a project/MOD with --slot, or --recipe.", "PATCH_FIELD")
        if args.recipe is not None:
            from .synth import from_recipe
            sample = from_recipe("Wave", parse_recipe(args.recipe))
            where = {"recipe": sample.recipe}
        else:
            module = load_source(args.source)
            if args.slot is None or not 1 <= args.slot <= len(module.samples):
                raise ValidationError(f"--slot 1-{len(module.samples)} is required with a project.", "SAMPLE_SLOT")
            sample, where = module.samples[args.slot - 1], {"slot": args.slot}
        if not sample.pcm:
            raise ValidationError("That sample slot is empty.", "SAMPLE_SLOT")
        buckets = sample_tools.waveform_summary(sample.pcm, args.buckets)
        return {"ok": True, **where, "bytes": len(sample.pcm), "loop_start": sample.loop_start,
                "loop_length": sample.loop_length, "bucket_count": len(buckets),
                "buckets": [list(item) for item in buckets],
                "note": "Each bucket is [min, max] of the signed 8-bit PCM (-128..127) over an equal share of the sample."}
    raise ValidationError(f"Unknown sample command {action!r}.", "INVALID_VALUE")
