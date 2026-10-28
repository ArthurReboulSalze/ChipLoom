"""`chiploom synth ...`: songs made only with created samples (recipes), audition and loudness matching."""

from __future__ import annotations

import argparse
from pathlib import Path

from . import project, synth_tools
from .document import Document
from .model import ValidationError, playback_plan
from .sample_library import DEFAULT_LIBRARY
from .synth import recipe_types


def _match_options(command: argparse.ArgumentParser) -> None:
    group = command.add_mutually_exclusive_group()
    group.add_argument("--match-library", nargs="?", const=DEFAULT_LIBRARY, type=Path, metavar="PATH",
                       help="Match loudness to the median levels of a sample bank (default bank: "
                            f"{DEFAULT_LIBRARY}). This is the default when that bank exists; without a bank the "
                            "fixed reference levels are used.")
    group.add_argument("--no-match", action="store_true",
                       help="Do not match loudness: keep the stated or default volumes.")


def add_parser(subparsers) -> argparse.ArgumentParser:
    synth = subparsers.add_parser("synth", help="Songs made only with created samples: recipes, audition, palette.")
    commands = synth.add_subparsers(dest="synth_command", required=True)
    commands.add_parser("types", help="List recipe types with parameters, ranges, defaults and purpose.")
    levels = commands.add_parser("levels", help="Reference loudness per role group, from a sample bank or defaults.")
    levels.add_argument("--library", type=Path, help=f"Sample bank (default {DEFAULT_LIBRARY} when it exists).")
    preview = commands.add_parser("preview", help="Render a recipe to a WAV at a tracker note.")
    preview.add_argument("--recipe", required=True, help="Recipe JSON, or @file.json.")
    preview.add_argument("--name", default="Preview")
    preview.add_argument("--output", type=Path, required=True, help="Output .wav file.")
    preview.add_argument("--note", default="C-2")
    preview.add_argument("--seconds", type=float, default=1.0)
    preview.add_argument("--volume", type=int, default=64)
    preview.add_argument("--finetune", type=int, default=0)
    preview.add_argument("--role", choices=sorted(synth_tools.loudness.ROLES))
    add = commands.add_parser("add", help="Insert a created sample into a project (a new project is written).")
    add.add_argument("project", type=Path)
    add.add_argument("--recipe", required=True, help="Recipe JSON, or @file.json.")
    add.add_argument("--name", required=True)
    add.add_argument("--output", type=Path, required=True, help="New .json project, different from the input.")
    add.add_argument("--slot", type=int, help="Slot 1-31; default: the first free slot.")
    add.add_argument("--replace", action="store_true", help="Allow overwriting an occupied slot.")
    add.add_argument("--volume", type=int, help="Explicit MOD volume 0-64; disables loudness matching.")
    add.add_argument("--finetune", type=int, default=0)
    add.add_argument("--role", choices=sorted(synth_tools.loudness.ROLES),
                     help="Mix role for loudness matching (default: inferred from the recipe).")
    _match_options(add)
    starter = commands.add_parser("palette", help="Write a new project holding a starter set of created samples.")
    starter.add_argument("--output", type=Path, required=True, help="New .json project; must not exist.")
    starter.add_argument("--title", default="Synth Palette")
    starter.add_argument("--style", choices=synth_tools.STYLES, default="default")
    starter.add_argument("--channels", type=int, default=4, help="Channel count, 2 to 32 (default 4).")
    starter.add_argument("--format", choices=("mod", "xm"), default="mod",
                         help="mod (default) or xm: an XM with the same recipes, converted like `convert` does.")
    _match_options(starter)
    return synth


def _reference(args: argparse.Namespace, volume_given: bool = False) -> tuple[str, Path | None]:
    """(match mode, bank) from --match-library / --no-match; the default is the local bank when it exists."""
    if args.no_match or volume_given:
        return "none", None
    if args.match_library is not None:
        return "library", args.match_library
    if synth_tools.library_exists(DEFAULT_LIBRARY):
        return "library", DEFAULT_LIBRARY
    return "defaults", None


def _new_json(output: Path, source: Path | None = None) -> Path:
    output = output.resolve()
    if output.suffix.lower() != ".json":
        raise ValidationError("A project is written as an editable .json file.", "OUTPUT_PATH")
    if source is not None and output == source.resolve():
        raise ValidationError("The output must differ from the input project; use `patch --in-place` to edit in place.",
                              "OUTPUT_PATH")
    return output


def run(args: argparse.Namespace) -> dict:
    action = args.synth_command
    if action == "types":
        types = recipe_types()
        return {"ok": True, "count": len(types), "types": types,
                "pitch": "frequency is the pitch heard when the sample plays at tracker note C-2 (period 428).",
                "roles": synth_tools.loudness.ROLES}
    if action == "levels":
        library = args.library if args.library is not None else DEFAULT_LIBRARY
        return synth_tools.levels(library, args.library is not None)
    if action == "preview":
        recipe = synth_tools.parse_recipe(args.recipe)
        return synth_tools.preview(recipe, args.name, args.output, args.note, args.seconds,
                                   args.volume, args.finetune, args.role)
    if action == "add":
        output = _new_json(args.output, args.project)
        recipe = synth_tools.parse_recipe(args.recipe)
        mode, library = _reference(args, args.volume is not None)
        op = {"op": "recipe_sample", "name": args.name, "recipe": recipe, "finetune": args.finetune,
              "replace": args.replace, "match": mode}
        for key, value in (("slot", args.slot), ("volume", args.volume), ("role", args.role),
                           ("library", str(library) if library else None)):
            if value is not None:
                op[key] = value
        document = Document(project.load(args.project))
        try:
            applied = document.patch([op], "Add created sample")
        except ValidationError as exc:
            # The command runs one internal patch operation; its "ops[0] (recipe_sample): " prefix
            # would point at a patch the user never wrote.
            prefix = "ops[0] (recipe_sample): "
            if str(exc).startswith(prefix):
                exc.args = (str(exc)[len(prefix):],)
            raise
        document.save_project(output)
        info = {key: value for key, value in applied["results"][0].items() if key != "op"}
        plan = playback_plan(document.module)
        return {"ok": True, "output": str(output), **info,
                "reference": mode if args.volume is None else "explicit volume",
                "duration_seconds": plan["duration_seconds"]}
    if action == "palette":
        output = _new_json(args.output)
        if output.exists():
            raise ValidationError(f"{output} already exists; the palette writes a new project.", "OUTPUT_PATH")
        mode, library = _reference(args)
        reference = None if mode == "none" else synth_tools.resolve_reference(mode, library)
        module, info = synth_tools.palette(args.title, args.style, reference, args.channels, args.format)
        project.write_json(output, project.to_dict(module))
        return {"ok": True, "output": str(output), "title": module.title, "format": module.format,
                "channels": module.channels, "sample_source": "synthesized",
                "reference": "none (hand-set volumes)" if reference is None else reference["source"],
                **info,
                "next": ["Compose with patch ops on this project (write/set cells with the slot numbers above).",
                         "Audition a timbre: chiploom synth preview --recipe @file.json --output x.wav --note C-2.",
                         "Check: chiploom validate OUT --sample-source synthesized, then export."],
                **({"notation": "XM note labels sit two octaves above MOD ones: where a slot's use says C-2 "
                                "(MOD), write C-4 in this XM; octaves 1-2 become 3-4."} if module.format == "xm" else {})}
    raise ValidationError(f"Unknown synth command {action!r}.", "INVALID_VALUE")
