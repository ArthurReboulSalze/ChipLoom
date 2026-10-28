"""`chiploom instruments ...`: a folder of instruments (sample + settings + effect phrase) and applying them."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .instruments import (DEFAULT_LIBRARY, InstrumentLibrary, from_slot, normalize, parse_phrase, summary)
from .model import ValidationError
from .sample_cli import load_source, run_ops
from .sample_library import DEFAULT_LIBRARY as DEFAULT_SAMPLE_BANK


def _folder(command: argparse.ArgumentParser) -> None:
    command.add_argument("--dir", type=Path, default=DEFAULT_LIBRARY, help=f"Instrument folder (default {DEFAULT_LIBRARY}).")


def add_parser(subparsers) -> argparse.ArgumentParser:
    instruments = subparsers.add_parser("instruments", help="Instruments: a sample, its settings and an effect phrase.")
    commands = instruments.add_subparsers(dest="instrument_command", required=True)
    listing = commands.add_parser("list", help="List the instruments of the folder.")
    listing.add_argument("--query", default="")
    listing.add_argument("--tag", action="append", default=[])
    listing.add_argument("--role")
    listing.add_argument("--offset", type=int, default=0)
    listing.add_argument("--limit", type=int, default=50)
    _folder(listing)
    show = commands.add_parser("show", help="Show one instrument.")
    show.add_argument("id", help="Instrument ID, e.g. INS-0001.")
    show.add_argument("--full", action="store_true", help="Include embedded PCM (base64).")
    _folder(show)
    save = commands.add_parser("save", help="Save an instrument from a project slot, a recipe, a library ID or JSON.")
    save.add_argument("--name", help="Instrument name (ASCII, at most 22 characters).")
    source = save.add_mutually_exclusive_group(required=True)
    source.add_argument("--project", type=Path, help="Capture the sample of --slot from this project.")
    source.add_argument("--recipe", help="Recipe JSON (or @file.json) as the sample.")
    source.add_argument("--library-id", help="A sample-bank ID such as SMP-0001 as the sample.")
    source.add_argument("--json", help="A whole instrument as JSON (or @file.json); other options are ignored.")
    save.add_argument("--slot", type=int, help="Slot of --project.")
    save.add_argument("--phrase", default="", help="Effect rows after the note: '000,C30,C20,C10' or a JSON list (max 32).")
    save.add_argument("--role")
    save.add_argument("--tag", action="append", default=[])
    save.add_argument("--volume", type=int)
    save.add_argument("--finetune", type=int)
    save.add_argument("--embed", action="store_true", help="Keep the PCM in the instrument even for recipe or library samples.")
    save.add_argument("--id", help="Overwrite this instrument ID (needs --replace).")
    save.add_argument("--replace", action="store_true")
    _folder(save)
    delete = commands.add_parser("delete", help="Delete one instrument file.")
    delete.add_argument("id")
    _folder(delete)
    apply = commands.add_parser("apply", help="Write an instrument's note and phrase into a project; writes a new project.")
    apply.add_argument("project", type=Path)
    apply.add_argument("--output", type=Path, required=True)
    apply.add_argument("--instrument", help="Instrument ID in --dir.")
    apply.add_argument("--inline", help="An instrument as JSON (or @file.json) instead of --instrument.")
    apply.add_argument("--pattern", type=int, required=True)
    apply.add_argument("--channel", type=int, required=True, help="Channel 0-3.")
    apply.add_argument("--row", type=int, required=True)
    apply.add_argument("--note", required=True, help="C-1 to B-3, e.g. C-2 or G#2.")
    apply.add_argument("--slot", type=int, help="Sample slot to use or fill (default: an identical sample, else the first free).")
    apply.add_argument("--replace", action="store_true", help="Allow overwriting an occupied --slot.")
    apply.add_argument("--length", type=int, help="Rows the phrase may run (default: the phrase length).")
    apply.add_argument("--overwrite", action="store_true", help="Replace existing (non-flow) effects on the phrase rows.")
    apply.add_argument("--library", type=Path, default=DEFAULT_SAMPLE_BANK, help="Sample bank for library instruments.")
    apply.add_argument("--label", default="Apply instrument")
    _folder(apply)
    return instruments


def _json_arg(text: str) -> object:
    try:
        if text.startswith("@"):
            text = Path(text[1:]).read_text(encoding="utf-8")
        return json.loads(text)
    except (OSError, ValueError) as exc:
        raise ValidationError(f"Not valid JSON: {exc}", "INSTRUMENT_INVALID") from exc


def _shown(instrument: dict, full: bool) -> dict:
    return instrument if full else summary(instrument)


def run(args: argparse.Namespace) -> dict:
    action = args.instrument_command
    folder = InstrumentLibrary(args.dir)
    if action == "list":
        return folder.list(args.query, args.tag, args.role, args.offset, args.limit)
    if action == "show":
        return {"ok": True, "instrument": _shown(folder.get(args.id), args.full)}
    if action == "delete":
        return folder.delete(args.id)
    if action == "save":
        if args.json is not None:
            data = _json_arg(args.json)
        else:
            if not args.name:
                raise ValidationError("--name is required.", "INSTRUMENT_INVALID")
            phrase = parse_phrase(args.phrase)
            if args.project is not None:
                if args.slot is None:
                    raise ValidationError("--slot is required with --project.", "SAMPLE_SLOT")
                data = from_slot(load_source(args.project), args.slot, args.name, phrase, args.role, args.tag,
                                 args.volume, args.finetune, args.embed)
            else:
                from .synth_tools import parse_recipe
                spec = ({"kind": "recipe", "recipe": parse_recipe(args.recipe)} if args.recipe is not None
                        else {"kind": "library", "library_id": args.library_id})
                data = {"name": args.name, "phrase": phrase, "tags": args.tag, "sample": spec}
                for key, value in (("role", args.role), ("volume", args.volume), ("finetune", args.finetune)):
                    if value is not None:
                        data[key] = value
        if args.id:
            data = {**(data if isinstance(data, dict) else {}), "id": args.id}
        saved = folder.save(normalize(data), args.replace)
        return {"ok": True, "folder": str(folder.path), "instrument": summary(saved)}
    if action == "apply":
        if (args.instrument is None) == (args.inline is None):
            raise ValidationError("Give either --instrument ID or --inline JSON.", "PATCH_FIELD")
        op = {"op": "apply_instrument", "pattern": args.pattern, "channel": args.channel, "row": args.row,
              "note": args.note, "replace": args.replace, "overwrite": args.overwrite,
              "instrument": args.instrument if args.instrument is not None else _json_arg(args.inline),
              "instruments": str(args.dir), "library": str(args.library)}
        if args.slot is not None:
            op["slot"] = args.slot
        if args.length is not None:
            op["length"] = args.length
        result = run_ops(args.project, args.output, [op], args.label)
        result["applied"] = result.pop("results")[0]
        return result
    raise ValidationError(f"Unknown instruments command {action!r}.", "INVALID_VALUE")
