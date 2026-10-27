"""`chiploom live ...`: talk to a running ChipLoom session (the window or a headless server)."""

from __future__ import annotations

import argparse
import json
import sys
import threading
from pathlib import Path
from typing import Callable

from .document import Document
from .live import LiveClient, LiveServer, LiveSession, discover, live_home
from .model import ValidationError


def add_parser(subparsers) -> argparse.ArgumentParser:
    """Register `live` with its sub-commands on the main CLI's subparsers object."""
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--session", default=argparse.SUPPRESS, metavar="PID_OR_URL",
                        help="Session to use (see `live sessions`); default: the newest.")
    live = subparsers.add_parser("live", parents=[common], help="Compose together with the open ChipLoom window.")
    commands = live.add_subparsers(dest="live_command", required=True)

    def command(name: str, help: str, **kwargs) -> argparse.ArgumentParser:
        return commands.add_parser(name, parents=[common], help=help, **kwargs)

    command("sessions", "List running sessions (window or headless).")
    command("status", "Window state: file, cursor, selection, playback, revision, pending proposals.")
    score = command("score", "Read the score: an overview, or one pattern as grid lines.")
    score.add_argument("--pattern", type=int)
    score.add_argument("--row", type=int, default=0)
    score.add_argument("--rows", type=int, default=64)
    patch = command("patch", "Apply (or --propose) a batch of edit operations.")
    source = patch.add_mutually_exclusive_group(required=True)
    source.add_argument("--ops", type=Path, help="JSON file with the operations ('-' reads stdin).")
    source.add_argument("--op", action="append", help="One operation as JSON; repeat for several.")
    patch.add_argument("--base", type=int, help="Revision you last read; a conflict with newer human edits is refused.")
    patch.add_argument("--label", help="Name shown in the journal and the undo history.")
    patch.add_argument("--propose", action="store_true", help="Let the owner preview and accept instead of applying.")
    patch.add_argument("--author", default="agent", help="Who is editing (default: agent).")
    changes = command("changes", "Journal of edits (human and agent) after a revision.")
    changes.add_argument("--since", type=int, default=0)
    changes.add_argument("--author")
    command("proposals", "Pending proposals waiting for the owner.")
    withdraw = command("withdraw", "Withdraw one of your pending proposals.")
    withdraw.add_argument("id")
    take = command("take", "Offer a saved version (project or MOD) as a take the owner can open.")
    take.add_argument("path", type=Path)
    take.add_argument("--label", required=True)
    command("takes", "List takes.")
    open_ = command("open", "Ask the window to open a file or a take.")
    open_.add_argument("path", nargs="?", type=Path)
    open_.add_argument("--take", help="Take id such as t1.")
    play = command("play", "Start playback in the window.")
    play.add_argument("--order", type=int, help="Start at this order position.")
    command("stop", "Stop playback in the window.")
    select = command("select", "Move the window's cursor / selection.")
    select.add_argument("--pattern", type=int, required=True)
    select.add_argument("--row", type=int, required=True)
    select.add_argument("--rows", type=int)
    select.add_argument("--channel", type=int, required=True)
    select.add_argument("--channels", type=int)
    save = command("save", "Save the project JSON (default: the open file).")
    save.add_argument("--output", type=Path)
    serve = command("serve", "Host a headless session on a project or MOD until Ctrl+C.")
    serve.add_argument("source", type=Path)
    serve.add_argument("--port", type=int, default=0)
    return live


def _read_ops(args: argparse.Namespace) -> object:
    if args.op:
        try:
            return [json.loads(text) for text in args.op]
        except ValueError as exc:
            raise ValidationError(f"--op: invalid JSON ({exc}).", "PATCH_FORMAT") from exc
    try:
        text = sys.stdin.read() if str(args.ops) == "-" else args.ops.read_text(encoding="utf-8")
        return json.loads(text)
    except ValueError as exc:
        raise ValidationError(f"--ops: invalid JSON ({exc}).", "PATCH_FORMAT") from exc


def _absolute_libraries(ops: object) -> object:
    """The session runs elsewhere: make relative `library` paths absolute from this shell's directory."""
    items = ops.get("ops") if isinstance(ops, dict) and isinstance(ops.get("ops"), list) else ops
    for item in items if isinstance(items, list) else [items]:
        if isinstance(item, dict) and isinstance(item.get("library"), str):
            item["library"] = str(Path(item["library"]).resolve())
    return ops


def _public(entry: dict) -> dict:
    return {key: value for key, value in entry.items() if key != "token"}


def _serve(args: argparse.Namespace, stop: threading.Event | None, announce: Callable[[dict], None] | None) -> dict:
    document = Document.open(args.source.resolve())
    session = LiveSession(document)
    server = LiveServer(session, port=args.port, kind="headless").start()
    stop = stop or threading.Event()
    try:
        info = {"ok": True, "event": "listening", **server.info(secret=False),
                "discovery_file": str(live_home() / "live"), "stop": "Ctrl+C"}
        (announce or (lambda value: print(json.dumps(value, ensure_ascii=False), flush=True)))(info)
        while not stop.wait(0.25):
            pass
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
    return {"ok": True, "event": "stopped", "revision": session.revision, "dirty": document.dirty,
            "note": "Unsaved changes were not written; use `live save` while the session runs." if document.dirty else ""}


def run(args: argparse.Namespace, stop: threading.Event | None = None,
        announce: Callable[[dict], None] | None = None) -> dict:
    """Execute a `live` command and return the JSON to print. `serve` blocks until Ctrl+C (or `stop`)."""
    name = args.live_command
    if name == "serve":
        return _serve(args, stop, announce)
    if name == "sessions":
        return {"ok": True, "sessions": [_public(item) for item in discover()]}
    client = LiveClient.discover(getattr(args, "session", None))
    if name == "status":
        return client.call("status")
    if name == "score":
        return client.call("score", pattern=args.pattern, start=args.row if args.pattern is not None else None,
                           rows=args.rows if args.pattern is not None else None)
    if name == "patch":
        ops = _absolute_libraries(_read_ops(args))
        base, label = args.base, args.label
        if isinstance(ops, dict) and "ops" in ops:  # {"ops": [...], "base_revision": N, "label": "..."}
            base = ops.get("base_revision") if base is None else base
            label = ops.get("label") if label is None else label
            ops = ops["ops"]
        return client.call("patch", ops=ops, base_revision=base, label=label, author=args.author,
                           propose=True if args.propose else None)
    if name == "changes":
        return client.call("changes", since=args.since, author=args.author)
    if name == "proposals":
        return client.call("proposals")
    if name == "withdraw":
        return client.call("withdraw", id=args.id)
    if name == "take":
        return client.call("take", path=str(args.path.resolve()), label=args.label)
    if name == "takes":
        return client.call("takes")
    if name == "open":
        if (args.path is None) == (args.take is None):
            raise ValidationError("Give exactly one of a PATH or --take ID.", "LIVE_OPEN")
        return client.call("open", path=str(args.path.resolve()) if args.path else None, take=args.take)
    if name == "play":
        return client.call("play", order=args.order)
    if name == "stop":
        return client.call("stop")
    if name == "select":
        return client.call("select", pattern=args.pattern, row=args.row, rows=args.rows,
                           channel=args.channel, channels=args.channels)
    if name == "save":
        return client.call("save", path=str(args.output.resolve()) if args.output else None)
    raise ValidationError(f"Unknown live command {name!r}.", "LIVE_COMMAND")
