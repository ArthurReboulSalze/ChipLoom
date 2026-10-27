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

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
COMMAND_TIMEOUT = 600

S = {"type": "string"}
I = {"type": "integer"}
N = {"type": "number"}
B = {"type": "boolean"}
OPS = {"type": "array", "items": {"type": "object"},
       "description": "Patch operations, e.g. {\"op\": \"write\", \"pattern\": 0, \"channel\": 1, \"row\": 0, "
                      "\"cells\": [\"C-2 01 ...\", \"\", \"E-2 01 C20\"]}. See docs/CLI.md#patch-operations."}
LIBRARY = {"type": "string", "description": "Sample library folder (default exports/sample_library)."}


def _tool(name, description, properties, required=(), argv=None, read_only=False):
    return {"name": name, "description": description, "argv": argv,
            "inputSchema": {"type": "object", "properties": properties, "required": list(required),
                            "additionalProperties": False},
            "annotations": {"readOnlyHint": read_only}}


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
    # Operations travel through a temporary file: command lines are short on Windows.
    return ["--ops", arguments["ops_file"]]


TOOLS = [
    _tool("estimate", "Plan a song's duration before writing it (constant speed/BPM).",
          {"orders": I, "rows": I, "speed": I, "bpm": I}, ["orders"],
          lambda a: ["estimate", *_flags(a, {"orders": "--orders", "rows": "--rows", "speed": "--speed", "bpm": "--bpm"})], True),
    _tool("validate", "Validate a JSON project or MOD; with report=true, list every independent problem with codes.",
          {"source": S, "report": B}, ["source"],
          lambda a: ["validate", a["source"], *_flags(a, {"report": "--report"})], True),
    _tool("inspect", "Summarize a project or MOD. With pattern (and grid=true), show that pattern as tracker grid text.",
          {"source": S, "pattern": I, "grid": B, "row": I, "rows": I}, ["source"],
          lambda a: ["inspect", a["source"], *_flags(a, {"pattern": "--pattern", "grid": "--grid", "row": "--row", "rows": "--rows"})], True),
    _tool("patch", "Apply patch operations to a project as one validated transaction and write the result.",
          {"source": S, "output": S, "ops": OPS, "label": S}, ["source", "output", "ops"],
          lambda a: ["patch", a["source"], "--output", a["output"], *_ops_json(a), *_flags(a, {"label": "--label"})]),
    _tool("export", "Export a validated project to a real MOD file.", {"source": S, "output": S}, ["source", "output"],
          lambda a: ["export", a["source"], "--output", a["output"]]),
    _tool("render", "Render a MOD or project to WAV (FFmpeg/libopenmpt), optionally an excerpt and an MP3 copy.",
          {"source": S, "output": S, "seconds": N, "from_order": I, "engine": {"enum": ["openmpt", "xmp"]}, "mp3_output": S},
          ["source", "output"],
          lambda a: ["render", a["source"], "--output", a["output"], *_flags(a, {
              "seconds": "--seconds", "from_order": "--from-order", "engine": "--engine", "mp3_output": "--mp3-output"})]),
    _tool("preview", "Build a portable HTML listening bundle in a new directory.",
          {"source": S, "output": S, "mp3": B, "language": {"enum": ["en", "fr"]}}, ["source", "output"],
          lambda a: ["preview", a["source"], "--output", a["output"], *_flags(a, {"mp3": "--mp3", "language": "--language"})]),
    _tool("report", "Measure a composition: density, ranges, gaps, repetition, estimated key, unused samples.",
          {"source": S}, ["source"], lambda a: ["report", a["source"]], True),
    _tool("compare", "Build a blind A/B listening page comparing two versions in a new directory.",
          {"first": S, "second": S, "output": S, "mp3": B, "language": {"enum": ["en", "fr"]}, "seed": I, "seconds": N},
          ["first", "second", "output"],
          lambda a: ["compare", a["first"], a["second"], "--output", a["output"], *_flags(a, {
              "mp3": "--mp3", "language": "--language", "seed": "--seed", "seconds": "--seconds"})]),
    _tool("feedback", "Record listening feedback in a project's metadata, written to a new project file.",
          {"project": S, "text": S, "rating": I, "output": S, "version": S}, ["project", "text", "output"],
          lambda a: ["feedback", a["project"], "--output", a["output"], *_flags(a, {
              "text": "--text", "rating": "--rating", "version": "--version"})]),
    _tool("migrate", "Rewrite a v1 project (or a MOD) as a compact v2 project.", {"source": S, "output": S},
          ["source", "output"], lambda a: ["migrate", a["source"], "--output", a["output"]]),
    _tool("samples_list", "Search the local sample library by text, tags, category and MOD compatibility.",
          {"library": LIBRARY, "query": S, "tag": {"type": "array", "items": S}, "category": S, "compatible": B,
           "offset": I, "limit": I}, (),
          lambda a: ["samples", "list", *_flags(a, {"library": "--library", "query": "--query", "tag": "--tag",
                                                    "category": "--category", "compatible": "--compatible",
                                                    "offset": "--offset", "limit": "--limit"})], True),
    _tool("samples_inspect", "Show one library sample's measurements, labels and compatibility.",
          {"library": LIBRARY, "id": S}, ["id"],
          lambda a: ["samples", "inspect", a["id"], *_flags(a, {"library": "--library"})], True),
    _tool("samples_preview", "Render a library sample at a note to a WAV file for audition.",
          {"library": LIBRARY, "id": S, "output": S, "note": S, "seconds": N}, ["id", "output"],
          lambda a: ["samples", "preview", a["id"], "--output", a["output"], *_flags(a, {
              "library": "--library", "note": "--note", "seconds": "--seconds"})]),
    _tool("samples_add", "Insert a library sample into a project slot and write a new project.",
          {"library": LIBRARY, "id": S, "project": S, "output": S, "slot": I, "replace": B, "adapt": B},
          ["id", "project", "output"],
          lambda a: ["samples", "add", a["id"], "--project", a["project"], "--output", a["output"], *_flags(a, {
              "library": "--library", "slot": "--slot", "replace": "--replace", "adapt": "--adapt"})]),
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
          {"session": S, "ops": OPS, "label": S, "base_revision": I, "propose": B, "author": S}, ["ops"],
          lambda a: ["live", *_flags(a, {"session": "--session"}), "patch", *_ops_json(a), *_flags(a, {
              "label": "--label", "base_revision": "--base", "propose": "--propose", "author": "--author"})]),
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
    missing = [key for key in schema["required"] if key not in arguments]
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


def run_command(argv: list[str], cwd: Path | None = None) -> tuple[bool, dict]:
    """Run one CLI command in a child process and return (ok, JSON payload)."""
    environment = dict(os.environ, PYTHONIOENCODING="utf-8")
    try:
        completed = subprocess.run([sys.executable, "-m", "tracker4agents", *argv], cwd=cwd, capture_output=True,
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
                "instructions": "ChipLoom composes four-channel MOD music. Plan with estimate, write a JSON project, "
                                "edit it with patch operations, validate, export the real MOD, render to listen. "
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
                return self._error(identifier, -32602, f"{tool['name']}: {exc}")
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
            return self._result(identifier, {
                "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)}],
                "structuredContent": payload, "isError": not ok})
        return self._error(identifier, -32601, f"Method not found: {method}")

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
    for stream in (sys.stdin, sys.stdout):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    return Server(cwd).serve()
