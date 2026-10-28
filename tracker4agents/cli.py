"""JSON responses on stdout; structured failures on stderr with nonzero status."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

from . import __version__, audio, convert, demo, formats, mod, pixel_rush, project, sample_source
from .document import Document
from .errors import diagnostic_payload, error_payload
from .patch import pattern_grid, summarize
from .model import MOD_PROFILE_N, PROFILE, XM_PROFILE, Module, ValidationError, playback_plan, require_int, validate
from .review import write_preview
from .synth_cli import add_parser as add_synth_parser, run as run_synth
from .sample_cli import add_parser as add_sample_parser, run as run_sample
from .instrument_cli import add_parser as add_instrument_parser, run as run_instruments


def emit(value: object, stream=None) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), file=stream or sys.stdout)


def load(path: Path) -> Module:
    return project.load(path) if path.suffix.lower() == ".json" else formats.read(path)


def _profile_of(module: Module) -> str:
    if module.format == "xm":
        return XM_PROFILE
    return PROFILE if module.channels == 4 else MOD_PROFILE_N


def _sample_bytes(sample) -> bytes:
    if sample.bits == 16:
        import struct
        return struct.pack(f"<{len(sample.pcm)}h", *sample.pcm)
    return bytes(value & 255 for value in sample.pcm)


def describe(module: Module, pattern_index: int | None = None, grid: bool = False,
             row: int = 0, rows: int | None = None) -> dict:
    plan = playback_plan(module)
    result = {
        "title": module.title, "profile": _profile_of(module), "channels": module.channels,
        "orders": module.orders, "patterns": len(module.patterns),
        "duration_seconds": plan["duration_seconds"], "loop_start_seconds": plan["loop_start_seconds"],
        "warnings": audio.duration_warnings(plan["duration_seconds"]),
        "sample_count": sum(bool(sample.pcm) for sample in module.samples),
        "samples": [{
            "index": index, "name": sample.name, "bytes": len(sample.pcm) * sample.bits // 8,
            "volume": sample.volume, "finetune": sample.finetune,
            "loop_start": sample.loop_start, "loop_length": sample.loop_length,
            "sha256": hashlib.sha256(_sample_bytes(sample)).hexdigest(),
            **{key: getattr(sample, key) for key, default in (("bits", 8), ("loop_mode", "forward"), ("panning", 128),
                                                               ("relative_note", 0)) if getattr(sample, key) != default},
        } for index, sample in enumerate(module.samples, 1) if sample.pcm or sample.name],
    }
    if module.format == "xm":
        result["format"] = "xm"
    if pattern_index is None and (grid or row or rows is not None):
        raise ValidationError("--grid, --row and --rows need --pattern N.", "PATCH_FIELD")
    if pattern_index is not None:
        require_int(pattern_index, "pattern", 0, len(module.patterns) - 1)
        total = module.patterns[pattern_index].rows
        count = total - row if rows is None else rows
        if grid:
            xm = module.format == "xm"
            result["pattern"] = {"index": pattern_index, "name": module.patterns[pattern_index].name,
                                 "rows": total,
                                 "columns": "row | " + " | ".join(f"track {i + 1}" for i in range(module.channels))
                                            + (" (note instrument volume effect)" if xm else " (note sample effect)"),
                                 "grid": pattern_grid(module, pattern_index, row, count)}
        else:
            require_int(row, "row", 0, total - 1)
            require_int(count, "rows", 1, total - row)
            result["pattern"] = {
                "index": pattern_index, "name": module.patterns[pattern_index].name,
                "rows": [{"row": index, "cells": [module.patterns[pattern_index].get(index, channel).text()
                                                  for channel in range(module.channels)]}
                         for index in range(row, row + count)],
            }
    return result


def read_ops(args: argparse.Namespace) -> object:
    """Patch operations from --ops FILE ('-' reads standard input) or repeated --op JSON."""
    if (args.ops is None) == (not args.op):
        raise ValidationError("Provide either --ops FILE or one or more --op JSON.", "PATCH_FORMAT")
    try:
        if args.op:
            ops = []
            for text in args.op:
                value = json.loads(text)
                ops.extend(value if isinstance(value, list) else [value])
            return ops
        return json.loads(sys.stdin.read() if str(args.ops) == "-" else args.ops.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ValidationError(f"Patch operations are not valid JSON: {exc}", "PATCH_FORMAT") from exc


def patch_project(args: argparse.Namespace) -> dict:
    output = args.output.resolve()
    if output == args.source.resolve() and not args.in_place:
        raise ValidationError("Writing over the source needs --in-place.", "OUTPUT_PATH")
    if output.suffix.lower() != ".json":
        raise ValidationError("A patched project is written as an editable .json project.", "OUTPUT_PATH")
    document = Document(load(args.source))
    applied = document.patch(read_ops(args), args.label)
    document.save_project(output)
    plan = playback_plan(document.module)
    return {"ok": True, "output": str(output), "changed": applied["changed"], "results": applied["results"],
            "changes": summarize(applied["diff"], 40), "cells_changed": len(applied["diff"]["cells"]),
            "duration_seconds": plan["duration_seconds"], "warnings": audio.duration_warnings(plan["duration_seconds"])}


def record_feedback(args: argparse.Namespace) -> dict:
    from .report import add_feedback
    output = args.output.resolve()
    if output == args.project.resolve() or output.suffix.lower() != ".json":
        raise ValidationError("Feedback is written to a new .json project, distinct from the input.", "OUTPUT_PATH")
    module = add_feedback(load(args.project), args.text, args.rating, args.source, args.version)
    project.write_json(output, project.to_dict(module))
    return {"ok": True, "output": str(output), "feedback": module.metadata["feedback"][-1],
            "feedback_count": len(module.metadata["feedback"])}


def migrate(source: Path, output: Path) -> dict:
    """Write `source` (v1/v2 project or MOD) as a schema v2 project; the MOD it encodes is unchanged."""
    if source.resolve() == output.resolve():
        raise ValidationError("La sortie doit être distincte du fichier source.", "OUTPUT_PATH")
    if output.suffix.lower() != ".json":
        raise ValidationError("Migration outputs an editable JSON project (.json extension).", "OUTPUT_PATH")
    if source.suffix.lower() == ".json":
        data = project.read_json(source)
        module = project.from_dict(data)
        source_schema = data.get("schema")
    else:
        module, source_schema = formats.read(source), module_format_name(source)
    score = project.to_dict(module)
    if formats.encode(project.from_dict(score)) != formats.encode(module):
        raise ValidationError("Migration would change the exported MOD; nothing was written.", "MIGRATION_MISMATCH")
    project.write_json(output, score)
    return {"ok": True, "source_schema": source_schema, "schema": score["schema"],
            "output": str(output.resolve()), "source_bytes": source.stat().st_size,
            "output_bytes": output.stat().st_size, "mod_sha256": hashlib.sha256(formats.encode(module)).hexdigest()}


def module_format_name(path: Path) -> str:
    return "xm" if path.suffix.lower() == ".xm" else "mod"


def export_module(args: argparse.Namespace) -> dict:
    """`export`: write the module file. The format comes from --format, else the output extension,
    else the project's own; a project of the other format is converted first (see `convert`)."""
    module = project.load(args.source)
    target = args.format or formats.format_of_path(args.output) or module.format
    if formats.format_of_path(args.output) not in (None, target):
        raise ValidationError(f"--format {target} does not match the extension of {args.output.name}.", "OUTPUT_PATH")
    report = None
    if target != module.format:
        module, report = convert.convert(module, target)
    payload = formats.encode(module)
    project.atomic_bytes(args.output, payload)
    result = {"ok": True, "output": str(args.output.resolve()), "bytes": len(payload),
              "sha256": audio.sha256(args.output)}
    if module.format == "xm":
        result["format"] = "xm"
    if report is not None:
        result["conversion"] = report
    return result


def convert_command(args: argparse.Namespace) -> dict:
    """`convert`: MOD to XM (lossless for the notes, effects and PCM of a MOD), or XM to MOD when it fits."""
    if args.source.resolve() == args.output.resolve():
        raise ValidationError("La sortie doit être distincte du fichier source.", "OUTPUT_PATH")
    suffix = args.output.suffix.lower()
    target = args.to or formats.format_of_path(args.output)
    if target is None:
        raise ValidationError("Give --to mod|xm, or an output ending in .mod or .xm.", "OUTPUT_PATH")
    if suffix not in (".json", f".{target}"):
        raise ValidationError(f"A {target.upper()} is written to a .{target} file (or a .json project).", "OUTPUT_PATH")
    module = load(args.source)
    converted, report = convert.convert(module, target)
    if suffix == ".json":
        project.write_json(args.output, project.to_dict(converted, recipes=False))
    else:
        project.atomic_bytes(args.output, formats.encode(converted))
    return {"ok": True, "output": str(args.output.resolve()), "from": module.format, "to": target,
            "conversion": report, **{key: value for key, value in describe(converted).items()
                                     if key in ("title", "profile", "channels", "duration_seconds")}}


def create_demo(args: argparse.Namespace) -> dict:
    if args.no_audio and (args.mp3 or args.with_xmp):
        raise ValidationError("--mp3 et --with-xmp nécessitent les rendus audio ; retire --no-audio.")
    song = args.song
    stem = song.replace("-", "_")
    module = pixel_rush.create(args.seed) if song == "pixel-rush" else demo.create(args.seed)
    directory = (args.output or Path("exports") / stem).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    source = directory / f"{stem}.project.json"
    module_path = directory / f"{stem}.mod"
    score = project.to_dict(module)
    project.write_json(source, score)
    payload = mod.encode(project.load(source))  # Build from the saved agent-editable score.
    project.atomic_bytes(module_path, payload)
    reread = mod.read(module_path)
    duration = playback_plan(reread)["duration_seconds"]
    summary = describe(reread)
    checks = {
        "profile_valid": True,
        "mod_roundtrip_byte_exact": mod.encode(reread) == payload,
        "project_rebuild_byte_exact": mod.encode(project.from_dict(score)) == payload,
        "all_samples_created_for_this_project": all(sample.recipe is not None for sample in module.samples),
    }
    for index, sample in enumerate(module.samples, 1):
        audio.sample_preview(sample, directory / "samples" / f"{index:02d}.wav")
    rendered = {}
    mp3 = None
    if not args.no_audio:
        rendered["openmpt"] = audio.render(module_path, directory / f"{stem}.wav", "openmpt", duration, ffmpeg=args.ffmpeg)
        if args.with_xmp:
            rendered["xmp"] = audio.render(module_path, directory / f"{stem}.libxmp.wav", "xmp", duration,
                                            xmp_library=args.xmp_library)
        for engine, result in rendered.items():
            metrics = result["audio"]
            checks[f"{engine}_full_cycle"] = abs(metrics["duration_seconds"] - duration) <= 1 / metrics["sample_rate"]
            checks[f"{engine}_audible_signal"] = metrics["peak"] > 0.01
            checks[f"{engine}_no_pcm_clipping"] = metrics["clipped_samples"] == 0
            checks[f"{engine}_no_long_silence"] = metrics["longest_quiet_window_seconds"] < 0.5
        if "xmp" in rendered:
            expected = playback_plan(module)["timeline"]
            actual = rendered["xmp"]["trace"]
            checks["xmp_timing_and_order_trace"] = len(expected) == len(actual) and all(
                all(left[key] == right[key] for key in ("order", "pattern", "row", "speed", "bpm"))
                and abs(left["seconds"] - right["seconds"]) <= 1 / 48000
                for left, right in zip(expected, actual)
            )
        if args.mp3:
            mp3 = audio.export_mp3(directory / f"{stem}.wav", directory / f"{stem}.mp3", args.ffmpeg)
        write_preview(module, directory / "preview.html", f"{stem}.wav", "validation.json",
                      f"{stem}.mp3" if mp3 else None)
    report = {
        "prototype_version": __version__, "status": "pass" if all(checks.values()) else "fail",
        "module": summary, "mod_sha256": audio.sha256(module_path), "mod_bytes": len(payload),
        "checks": checks, "renders": rendered, "optional_mp3": mp3,
        "not_validated": ["human musical listening", "physical audio output", "third-party module corpus"],
        "reference_note": "libopenmpt and libxmp are distinct replay implementations; their PCM is not expected to be identical.",
    }
    project.write_json(directory / "validation.json", report)
    if not all(checks.values()):
        raise ValidationError(f"Un contrôle a échoué : consulte {directory / 'validation.json'}.")
    return {"ok": True, "title": module.title, "mod": str(module_path), "project": str(source),
            "wav": str(directory / f"{stem}.wav") if rendered else None,
            "mp3": mp3["output"] if mp3 else None,
            "preview": str(directory / "preview.html") if rendered else None,
            "validation": str(directory / "validation.json"), "mod_bytes": len(payload),
            "duration_seconds": duration, "checks_passed": len(checks),
            "audio_engines": list(rendered)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="chiploom", description="ChipLoom: an agent-driven four-channel MOD tracker.")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    estimate = commands.add_parser("estimate", help="Estimate duration before writing a score (constant timing).")
    estimate.add_argument("--orders", type=int, required=True)
    estimate.add_argument("--rows", type=int, default=64, help="Rows played per order, default 64.")
    estimate.add_argument("--speed", type=int, default=6)
    estimate.add_argument("--bpm", type=int, default=125)
    desktop = commands.add_parser("gui", help="Ouvrir la fenêtre de tracker (option desktop requise).")
    desktop.add_argument("source", type=Path, nargs="?", help="MOD ou projet JSON à ouvrir.")
    desktop.add_argument("--state-dir", type=Path, help="Dossier local de session et de cache audio.")
    desktop.add_argument("--no-restore", action="store_true", help="Ne pas rouvrir le dernier fichier.")
    generate = commands.add_parser("demo", help="Créer une des compositions originales et ses samples.")
    generate.add_argument("--song", choices=("first-light", "pixel-rush"), default="first-light")
    generate.add_argument("--output", type=Path, help="Dossier de sortie (exports/nom_du_morceau par défaut).")
    generate.add_argument("--seed", type=int, default=104729)
    generate.add_argument("--no-audio", action="store_true", help="Créer le MOD et les samples sans moteur audio externe.")
    generate.add_argument("--with-xmp", action="store_true", help="Vérifier aussi la lecture dans libxmp.")
    generate.add_argument("--mp3", action="store_true", help="Ajouter une copie d'écoute MP3 au MOD.")
    generate.add_argument("--ffmpeg")
    generate.add_argument("--xmp-library", type=Path)
    preview = commands.add_parser("preview", help="Build a portable HTML listening bundle from a project or MOD.")
    preview.add_argument("source", type=Path)
    preview.add_argument("--output", type=Path, required=True, help="New output directory.")
    preview.add_argument("--mp3", action="store_true")
    preview.add_argument("--ffmpeg")
    preview.add_argument("--language", choices=("en", "fr"), default="en")
    analyze = commands.add_parser("analyze", help="Study a reference MOD or ZIP in read-only mode; does not import it for editing.")
    analyze.add_argument("source", type=Path)
    analyze.add_argument("--output", type=Path, required=True)
    analyze.add_argument("--probe", action="store_true", help="Also estimate duration with ffprobe/libopenmpt.")
    from .sample_library import CATEGORIES, DEFAULT_LIBRARY
    samples = commands.add_parser("samples", help="Local sample library: extract, search, audition and insert.")
    sample_commands = samples.add_subparsers(dest="sample_command", required=True)
    for name in ("extract", "list", "inspect", "preview", "add", "edit", "audit"):
        command = sample_commands.add_parser(name)
        command.add_argument("--library", type=Path, default=DEFAULT_LIBRARY)
        if name == "extract":
            command.add_argument("source", type=Path, help="Reference MOD or ZIP; read only.")
        if name in ("inspect", "preview", "add", "edit"):
            command.add_argument("id", help="Stable library ID, e.g. SMP-0001.")
        if name == "list":
            command.add_argument("--query", default="")
            command.add_argument("--tag", action="append", default=[])
            command.add_argument("--category", choices=CATEGORIES)
            command.add_argument("--compatible", action="store_true")
            command.add_argument("--offset", type=int, default=0)
            command.add_argument("--limit", type=int, default=20)
        if name == "preview":
            command.add_argument("--output", type=Path, required=True)
            command.add_argument("--note", default="C-2")
            command.add_argument("--seconds", type=float, default=1.0)
        if name == "add":
            command.add_argument("--project", type=Path, required=True)
            command.add_argument("--output", type=Path, required=True)
            command.add_argument("--slot", type=int)
            command.add_argument("--replace", action="store_true")
            command.add_argument("--adapt", action="store_true", help="Explicitly adapt an incompatible one-shot on a copy.")
        if name == "edit":
            command.add_argument("--name")
            command.add_argument("--category", choices=CATEGORIES)
            command.add_argument("--tag", action="append", default=None, help="Replaces tags; repeat for multiple tags.")
    add_synth_parser(commands)
    add_sample_parser(commands)
    add_instrument_parser(commands)
    migrate_parser = commands.add_parser("migrate", help="Rewrite a project (v1 or v2) or MOD as a schema v2 project.")
    migrate_parser.add_argument("source", type=Path)
    migrate_parser.add_argument("--output", type=Path, required=True, help="New .json project; must differ from the source.")
    patch = commands.add_parser("patch", help="Apply batch edit operations to a project as one validated transaction.")
    patch.add_argument("source", type=Path, help="Project JSON (or MOD) to edit; read only unless --in-place.")
    patch.add_argument("--output", type=Path, required=True, help="Edited .json project.")
    patch.add_argument("--ops", type=Path, help="JSON file with a list of operations ('-' for standard input).")
    patch.add_argument("--op", action="append", help="One operation (or a list) as JSON; repeat for several.")
    patch.add_argument("--label", default="Patch", help="Label for the change history.")
    patch.add_argument("--in-place", action="store_true", help="Allow --output to be the source project.")
    report = commands.add_parser("report", help="Measure a composition: density, ranges, gaps, repetition, estimated key.")
    report.add_argument("source", type=Path)
    report.add_argument("--library", type=Path, help="Sample bank whose median levels are the loudness reference "
                                                     "(default: fixed reference levels).")
    compare = commands.add_parser("compare", help="Build a blind A/B listening page for two versions in a new directory.")
    compare.add_argument("first", type=Path)
    compare.add_argument("second", type=Path)
    compare.add_argument("--output", type=Path, required=True)
    compare.add_argument("--mp3", action="store_true")
    compare.add_argument("--ffmpeg")
    compare.add_argument("--language", choices=("en", "fr"), default="en")
    compare.add_argument("--seed", type=int)
    compare.add_argument("--seconds", type=float, help="Render the same excerpt length from the start of both versions.")
    compare.add_argument("--labels", nargs=2, metavar=("FIRST", "SECOND"))
    feedback = commands.add_parser("feedback", help="Record listening feedback in a project's metadata.")
    feedback.add_argument("project", type=Path)
    feedback.add_argument("--text", required=True)
    feedback.add_argument("--rating", type=int, help="1 to 5.")
    feedback.add_argument("--source", default="owner", help="Who gave the feedback (default owner).")
    feedback.add_argument("--version", help="Version label the feedback refers to.")
    feedback.add_argument("--output", type=Path, required=True)
    convert_parser = commands.add_parser(
        "convert", help="Convert between MOD and XM (a MOD to XM keeps notes, effects and PCM; XM to MOD only when it fits).")
    convert_parser.add_argument("source", type=Path, help="MOD, XM or project JSON.")
    convert_parser.add_argument("--output", type=Path, required=True, help="New .mod, .xm or .json file.")
    convert_parser.add_argument("--to", choices=("mod", "xm"), help="Target format; default: the output extension.")
    mcp = commands.add_parser("mcp", help="Run the Model Context Protocol adapter on stdio (for MCP clients).")
    mcp.add_argument("--root", type=Path, help="Working directory for relative paths in tool calls.")
    from .live_cli import add_parser as add_live_parser
    add_live_parser(commands)
    for name in ("inspect", "validate", "export", "import", "render"):
        command = commands.add_parser(name)
        command.add_argument("source", type=Path)
        if name == "inspect":
            command.add_argument("--pattern", type=int)
            command.add_argument("--grid", action="store_true", help="Show the pattern as tracker grid text lines.")
            command.add_argument("--row", type=int, default=0, help="First row shown with --pattern.")
            command.add_argument("--rows", type=int, help="Number of rows shown with --pattern.")
        if name == "validate":
            command.add_argument("--report", action="store_true", help="Collect independent JSON project errors in one read-only report.")
            command.add_argument("--sample-source", choices=("synthesized", "library"),
                                 help="Require every sample to be a created recipe (synthesized) or a library sample "
                                      "(no recipe). Without it, a declared metadata.sample_source is checked.")
        if name in ("export", "import", "render"):
            command.add_argument("--output", type=Path, required=True)
        if name == "export":
            command.add_argument("--format", choices=("mod", "xm"),
                                 help="Module format; default: the output extension, else the project's own. "
                                      "A project of the other format is converted (see `convert`).")
        if name == "render":
            command.add_argument("--engine", choices=("openmpt", "xmp"), default="openmpt")
            command.add_argument("--seconds", type=float)
            command.add_argument("--from-order", type=int, help="Start at the first visit to this zero-based order; preserve prior replay state.")
            command.add_argument("--sample-rate", type=int, default=48000)
            command.add_argument("--ffmpeg")
            command.add_argument("--xmp-library", type=Path)
            command.add_argument("--mp3-output", type=Path, help="Ajouter une copie MP3 du WAV rendu.")
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    try:
        if args.command == "gui":
            try:
                from .desktop import main as desktop_main
            except ModuleNotFoundError as exc:
                if exc.name and exc.name.startswith("PySide6"):
                    raise RuntimeError("L'interface demande PySide6. Exécute python -m pip install -e '.[desktop]' dans un environnement virtuel.") from exc
                raise
            return desktop_main(args.source, args.state_dir, not args.no_restore)
        if args.command == "estimate":
            require_int(args.orders, "orders", 1, 128)
            require_int(args.rows, "rows", 1, 64)
            require_int(args.speed, "speed", 1, 31)
            require_int(args.bpm, "bpm", 33, 255)
            per_order = args.rows * args.speed * 2.5 / args.bpm
            duration = args.orders * per_order
            result = {"ok": True, "orders": args.orders, "rows_per_order": args.rows,
                      "speed": args.speed, "bpm": args.bpm, "seconds_per_order": round(per_order, 9),
                      "duration_seconds": round(duration, 9), "warnings": audio.duration_warnings(duration),
                      "assumptions": "Constant speed/BPM, no jumps or early breaks. Validate the finished score for its playback plan."}
        elif args.command == "demo":
            result = create_demo(args)
        elif args.command == "preview":
            from .preview import create_bundle
            result = create_bundle(args.source, args.output, args.mp3, args.ffmpeg, args.language)
        elif args.command == "samples":
            from .sample_library import SampleLibrary
            bank = SampleLibrary(args.library)
            action = args.sample_command
            if action == "extract":
                result = bank.extract(args.source)
            elif action == "list":
                result = bank.search(args.query, args.tag, args.category, args.compatible, args.offset, args.limit)
            elif action == "inspect":
                result = {"ok": True, "sample": bank.get(args.id)}
            elif action == "audit":
                result = bank.audit()
            elif action == "preview":
                result = bank.audition(args.id, args.output, args.note, args.seconds)
            elif action == "edit":
                if args.name is None and args.category is None and args.tag is None:
                    raise ValidationError("Provide --name, --category or --tag to edit a library entry.")
                result = {"ok": True, "sample": bank.edit(args.id, args.name, args.category, args.tag)}
            elif action == "add":
                output = args.output.resolve()
                if output == args.project.resolve() or output.is_relative_to(bank.path):
                    raise ValidationError("Output must differ from the input project and be outside the sample bank.")
                if output.suffix.lower() != ".json":
                    raise ValidationError("Sample insertion outputs an editable JSON project.")
                module, info = bank.insert(project.load(args.project), args.id, args.slot, args.replace, args.adapt)
                project.write_json(output, project.to_dict(module))
                result = {"ok": True, "output": str(output), **info}
        elif args.command == "synth":
            result = run_synth(args)
        elif args.command == "sample":
            result = run_sample(args)
        elif args.command == "instruments":
            result = run_instruments(args)
        elif args.command == "analyze":
            from .references import analyze_source
            if args.source.resolve() == args.output.resolve():
                raise ValueError("Analysis output must differ from the source.")
            result = analyze_source(args.source, args.probe)
            project.write_json(args.output, result)
            emit({"ok": result["ok"], "output": str(args.output.resolve()), "modules": len(result["modules"]),
                  "editable_modules": sum(entry.get("editable_in_current_profile", False) for entry in result["modules"]),
                  "source_unchanged": result["source_unchanged"]})
            return 0 if result["ok"] else 2
        elif args.command in ("inspect", "validate"):
            if args.command == "validate" and args.report and args.source.suffix.lower() == ".json":
                data = project.read_json(args.source)
                entries = [diagnostic_payload(entry) for entry in project.diagnose(data)]
                if not entries:
                    try:
                        _, problems = sample_source.violations(project.from_dict(data), args.sample_source)
                    except sample_source.SampleSourceError as exc:
                        problems = exc.violations
                    entries = [{"path": f"samples[{item['slot'] - 1}]" if item.get("slot") else "metadata.sample_source",
                                "code": "SAMPLE_SOURCE",
                                "message": item["reason"] + (f" ({item['name']!r})" if item.get("name") else "")}
                               for item in problems]
                if entries:
                    emit({"ok": False, "error": "ValidationError", "code": "PROJECT_INVALID",
                          "message": "Project validation failed.",
                          "errors": entries, "error_count": len(entries)}, stream=sys.stderr)
                    return 2
            module = load(args.source)
            validate(module)
            source_check = sample_source.enforce(module, getattr(args, "sample_source", None))                 if args.command == "validate" else None
            result = {"ok": True, **describe(module, getattr(args, "pattern", None), getattr(args, "grid", False),
                                             getattr(args, "row", 0), getattr(args, "rows", None))}
            if source_check is not None:
                result["sample_source"] = source_check
            if getattr(args, "report", False):
                result.update(errors=[], error_count=0)
        elif args.command in ("export", "import"):
            if args.source.resolve() == args.output.resolve():
                raise ValidationError("La sortie doit être distincte du fichier source.")
            if args.command == "export":
                result = export_module(args)
            else:
                module = formats.read(args.source)
                project.write_json(args.output, project.to_dict(module, recipes=False))
                result = {"ok": True, "output": str(args.output.resolve()), "schema": project.SCHEMA_V2,
                          **describe(module), "import_notes": formats.import_notes(module)}
        elif args.command == "convert":
            result = convert_command(args)
        elif args.command == "patch":
            result = patch_project(args)
        elif args.command == "report":
            from .report import analyze
            reference = None
            if args.library is not None:
                from .synth_tools import resolve_reference
                reference = resolve_reference("library", args.library)
            result = {"ok": True, **analyze(load(args.source), reference)}
        elif args.command == "compare":
            from .compare import create_comparison
            result = create_comparison(args.first, args.second, args.output, mp3=args.mp3, ffmpeg=args.ffmpeg,
                                       language=args.language, seed=args.seed, seconds=args.seconds,
                                       labels=tuple(args.labels) if args.labels else None)
        elif args.command == "feedback":
            result = record_feedback(args)
        elif args.command == "mcp":
            from .mcp_server import main as mcp_main
            return mcp_main(args.root.resolve() if args.root else None)
        elif args.command == "live":
            from .live_cli import run as run_live
            result = run_live(args)
        elif args.command == "migrate":
            result = migrate(args.source, args.output)
        elif args.command == "render":
            result = {"ok": True, **audio.render(
                args.source, args.output, args.engine, args.seconds, args.sample_rate,
                args.ffmpeg, args.xmp_library, from_order=args.from_order,
            )}
            if args.mp3_output:
                result["optional_mp3"] = audio.export_mp3(args.output, args.mp3_output, args.ffmpeg)
        emit(result)
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        emit(error_payload(exc), stream=sys.stderr)
        return 2
