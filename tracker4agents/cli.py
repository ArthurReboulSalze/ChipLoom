"""JSON responses on stdout; structured failures on stderr with nonzero status."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

from . import __version__, audio, demo, mod, pixel_rush, project
from .model import PROFILE, Module, ValidationError, playback_plan, require_int, validate
from .review import write_preview


def emit(value: object, stream=None) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), file=stream or sys.stdout)


def load(path: Path) -> Module:
    return project.load(path) if path.suffix.lower() == ".json" else mod.read(path)


def describe(module: Module, pattern_index: int | None = None) -> dict:
    plan = playback_plan(module)
    result = {
        "title": module.title, "profile": PROFILE, "channels": 4,
        "orders": module.orders, "patterns": len(module.patterns),
        "duration_seconds": plan["duration_seconds"], "loop_start_seconds": plan["loop_start_seconds"],
        "warnings": audio.duration_warnings(plan["duration_seconds"]),
        "sample_count": sum(bool(sample.pcm) for sample in module.samples),
        "samples": [{
            "index": index, "name": sample.name, "bytes": len(sample.pcm),
            "volume": sample.volume, "finetune": sample.finetune,
            "loop_start": sample.loop_start, "loop_length": sample.loop_length,
            "sha256": hashlib.sha256(bytes(value & 255 for value in sample.pcm)).hexdigest(),
        } for index, sample in enumerate(module.samples, 1) if sample.pcm or sample.name],
    }
    if pattern_index is not None:
        require_int(pattern_index, "pattern", 0, len(module.patterns) - 1)
        result["pattern"] = {
            "index": pattern_index, "name": module.patterns[pattern_index].name,
            "rows": [{"row": row, "cells": [module.patterns[pattern_index].get(row, channel).text()
                                              for channel in range(4)]} for row in range(64)],
        }
    return result


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
    for name in ("inspect", "validate", "export", "import", "render"):
        command = commands.add_parser(name)
        command.add_argument("source", type=Path)
        if name == "inspect":
            command.add_argument("--pattern", type=int)
        if name == "validate":
            command.add_argument("--report", action="store_true", help="Collect independent JSON project errors in one read-only report.")
        if name in ("export", "import", "render"):
            command.add_argument("--output", type=Path, required=True)
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
                errors = project.diagnose(project.read_json(args.source))
                if errors:
                    emit({"ok": False, "error": "ValidationError", "message": "Project validation failed.",
                          "errors": errors, "error_count": len(errors)}, stream=sys.stderr)
                    return 2
            module = load(args.source)
            validate(module)
            result = {"ok": True, **describe(module, getattr(args, "pattern", None))}
            if getattr(args, "report", False):
                result.update(errors=[], error_count=0)
        elif args.command in ("export", "import"):
            if args.source.resolve() == args.output.resolve():
                raise ValidationError("La sortie doit être distincte du fichier source.")
            if args.command == "export":
                payload = mod.encode(project.load(args.source))
                project.atomic_bytes(args.output, payload)
                result = {"ok": True, "output": str(args.output.resolve()), "bytes": len(payload),
                          "sha256": audio.sha256(args.output)}
            else:
                module = mod.read(args.source)
                project.write_json(args.output, project.to_dict(module, recipes=False))
                result = {"ok": True, "output": str(args.output.resolve()), **describe(module)}
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
        emit({"ok": False, "error": type(exc).__name__, "message": str(exc)}, stream=sys.stderr)
        return 2
