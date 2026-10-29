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
    sync = command("sync", "Send the differences between a project file and the session as undoable patches.")
    sync.add_argument("project", type=Path, help="Project JSON (or MOD/XM) to bring into the session.")
    sync.add_argument("--dry-run", action="store_true", help="Print the planned patches without sending them.")
    sync.add_argument("--label", help="Label prefix of the patches (default: Sync).")
    sync.add_argument("--author", default="agent", help="Who is editing (default: agent).")
    sync.add_argument("--library", type=Path,
                      help="Sample library for library samples (default exports/sample_library).")
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
    comments = command("comments", "Comments attached to places in the score (open ones by default).")
    comments.add_argument("--status", choices=("open", "resolved", "all"), default="open")
    comment = command("comment", "Attach a comment to a block of the score (or to the whole song).")
    comment.add_argument("text")
    comment.add_argument("--pattern", type=int, help="Pattern of the block; omit for the whole song.")
    comment.add_argument("--row", type=int, default=0)
    comment.add_argument("--rows", type=int, default=1)
    comment.add_argument("--channel", type=int, default=0)
    comment.add_argument("--channels", type=int, default=1)
    comment.add_argument("--author", default="agent", help="Who is writing (default: agent).")
    reply = command("reply", "Reply to a comment.")
    reply.add_argument("id", help="Comment id such as c1.")
    reply.add_argument("text")
    reply.add_argument("--author", default="agent")
    resolve = command("resolve", "Mark a comment resolved (or --reopen it), with an optional closing reply.")
    resolve.add_argument("id")
    resolve.add_argument("--text", help="A closing reply, such as what you changed.")
    resolve.add_argument("--reopen", action="store_true")
    resolve.add_argument("--author", default="agent")
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
    serve.add_argument("--web", action="store_true",
                       help="Also print the address of the browser studio (/web/); no code is needed.")
    serve.add_argument("--lan", action="store_true",
                       help="Offer the browser studio to other devices on your private network (implies --web). "
                            "Plain HTTP; only the studio is exposed, never the agent API.")
    serve.add_argument("--lan-host", metavar="ADDRESS", help="Restrict --lan to one private IPv4 address of this computer.")
    serve.add_argument("--lan-port", type=int, default=0, help="Port for the LAN listener (default: any free port).")
    serve.add_argument("--no-web", action="store_true", help="Turn the browser studio off for this session.")
    web = command("web", "Print the address of the browser studio of the running session (no code needed).")
    web.add_argument("--status", action="store_true", help="List the connected browsers instead of printing the address.")
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


def _web_announcement(server: LiveServer) -> dict:
    """The studio address(es) for the owner to open in a browser."""
    urls = server.web_urls()
    address = (urls["lan"] or [urls["local"]])[0]
    return {**{key: value for key, value in server.web_info().items() if key != "devices"},
            "message": f"Open {address} in a browser."}


def _serve(args: argparse.Namespace, stop: threading.Event | None, announce: Callable[[dict], None] | None) -> dict:
    if args.no_web and (args.web or args.lan):
        raise ValidationError("--no-web cannot be combined with --web or --lan.", "LIVE_PARAMS")
    if args.lan_host and not args.lan:
        raise ValidationError("--lan-host needs --lan.", "LIVE_PARAMS")
    document = Document.open(args.source.resolve())
    session = LiveSession(document)
    server = LiveServer(session, port=args.port, kind="headless", web=not args.no_web, lan=args.lan,
                        lan_port=args.lan_port)
    if args.lan_host:
        server.enable_lan(True, args.lan_host, args.lan_port)
    server.start()
    stop = stop or threading.Event()
    try:
        info = {"ok": True, "event": "listening", **server.info(secret=False),
                "discovery_file": str(live_home() / "live"), "stop": "Ctrl+C"}
        if args.web or args.lan:
            info["web"] = _web_announcement(server)
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
    if name == "web":
        if args.status:
            return client.call("web_status")
        info = client.call("web_status")
        if not info.get("enabled"):
            raise ValidationError("The browser studio is turned off on this session.", "LIVE_WEB_OFF")
        address = (info["lan"] or [info["local"]])[0]
        return {**{key: value for key, value in info.items() if key != "devices"}, "message": f"Open {address} in a browser."}
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
    if name == "sync":
        from .live_sync import sync
        return sync(client, args.project, dry_run=args.dry_run, label=args.label, author=args.author,
                    library=args.library)
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
    if name == "comments":
        return client.call("comments", status=args.status)
    if name == "comment":
        place = None if args.pattern is None else {"pattern": args.pattern, "row": args.row, "rows": args.rows,
                                                   "channel": args.channel, "channels": args.channels}
        return client.call("comment", text=args.text, place=place, author=args.author)
    if name == "reply":
        return client.call("reply", id=args.id, text=args.text, author=args.author)
    if name == "resolve":
        return client.call("resolve", id=args.id, text=args.text, reopen=True if args.reopen else None,
                           author=args.author)
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
