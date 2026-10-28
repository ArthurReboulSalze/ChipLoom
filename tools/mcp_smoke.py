"""Exercise `chiploom mcp` with the official Python MCP SDK acting as a real client.

Run this file with a Python interpreter that has the `mcp` package installed (ChipLoom does
not depend on it; use a separate virtual environment). The server is launched over stdio with
the SDK's `stdio_client` + `ClientSession`:

    <python-with-mcp> tools/mcp_smoke.py [--server-python PYTHON] [--repo DIR]

`--server-python` is the interpreter that runs `python -m tracker4agents mcp` (default: this
one); `--repo` is the checkout whose `tracker4agents` package it imports (default: this repo).
A JSON summary goes to stdout and the exit status is non-zero when any check failed. Everything
happens in a temporary directory, including `CHIPLOOM_HOME`; the only process started besides
the MCP server is a headless `live serve`, which is stopped by its PID.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import AsyncExitStack
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from importlib import metadata

REPO = Path(__file__).resolve().parents[1]


def attr(obj, snake: str, camel: str, default=None):
    """Read a field from SDK objects across SDK generations (snake_case in 2.x, camelCase in 1.x)."""
    value = getattr(obj, snake, None)
    return value if value is not None else getattr(obj, camel, default)


def error_code(exc: BaseException):
    code = getattr(exc, "code", None)
    if code is None:
        code = getattr(getattr(exc, "error", None), "code", None)
    return code


def text_of(result) -> str:
    return "".join(getattr(block, "text", "") for block in result.content)


class Checks:
    def __init__(self) -> None:
        self.passed: list[str] = []
        self.failed: list[str] = []

    def check(self, name: str, condition: bool, detail: object = None) -> None:
        if condition:
            self.passed.append(name)
        else:
            self.failed.append(f"{name}: {detail!r}" if detail is not None else name)


def start_live_server(python: str, environment: dict, source: Path, cwd: Path) -> tuple[subprocess.Popen, dict]:
    process = subprocess.Popen([python, "-m", "tracker4agents", "live", "serve", str(source)], cwd=cwd, env=environment,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                               stdin=subprocess.DEVNULL)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        line = process.stdout.readline()
        if line.strip():
            info = json.loads(line)
            if info.get("event") == "listening":
                return process, info
        elif process.poll() is not None:
            break
    stop_process(process, None)
    raise RuntimeError("live serve did not start: " + (process.stderr.read() if process.stderr else ""))


def stop_process(process: subprocess.Popen, reported_pid: int | None) -> None:
    """Stop the processes this script started, by PID: the one spawned and the interpreter it reported."""
    for pid in {process.pid, reported_pid} - {None}:
        try:
            os.kill(pid, signal.SIGTERM)
        except (OSError, ValueError):
            pass
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=20)
    for stream in (process.stdout, process.stderr):
        if stream:
            stream.close()


async def run(server_python: str, repo: Path, work: Path, checks: Checks) -> dict:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    home = work / "chiploom-home"
    home.mkdir()
    project = work / "song.project.json"
    shutil.copyfile(repo / "examples" / "pixel_rush.project.json", project)
    environment = {**os.environ, "CHIPLOOM_HOME": str(home), "PYTHONPATH": str(repo), "PYTHONIOENCODING": "utf-8"}
    live_process, live_info = start_live_server(server_python, environment, project, work)
    summary: dict = {}
    try:
        parameters = StdioServerParameters(command=server_python, args=["-m", "tracker4agents", "mcp", "--root", str(work)],
                                           env={"CHIPLOOM_HOME": str(home), "PYTHONPATH": str(repo),
                                                "PYTHONIOENCODING": "utf-8"}, cwd=str(work))
        log_path = work / "mcp-server.stderr.txt"
        async with AsyncExitStack() as stack:
            stderr_log = stack.enter_context(log_path.open("w", encoding="utf-8"))
            streams = await stack.enter_async_context(stdio_client(parameters, errlog=stderr_log))
            read, write = streams[:2]
            session = await stack.enter_async_context(ClientSession(read, write))
            # Newer SDKs probe `server/discover` first; a server without it must answer -32601 and the
            # client falls back to `initialize`. Do the same here by hand.
            if hasattr(session, "discover"):
                try:
                    await session.discover()
                    checks.check("discover probe is refused by the legacy server", False)
                except Exception as exc:  # noqa: BLE001 - the SDK's error class differs between versions
                    checks.check("discover probe answered -32601 (client falls back)", error_code(exc) == -32601, repr(exc))
            hello = await session.initialize()
            info = attr(hello, "server_info", "serverInfo")
            summary["protocol_version"] = attr(hello, "protocol_version", "protocolVersion")
            summary["server"] = {"name": info.name, "version": info.version, "title": getattr(info, "title", None)}
            capabilities = hello.capabilities
            checks.check("initialize negotiates a version", bool(summary["protocol_version"]))
            checks.check("server name", info.name == "chiploom")
            checks.check("tools capability declared", capabilities.tools is not None)
            checks.check("instructions delivered", bool(hello.instructions))

            await session.send_ping()
            listing = await session.list_tools()
            names = [tool.name for tool in listing.tools]
            summary["tool_count"] = len(names)
            checks.check("tools listed with unique names", len(names) >= 34 and len(set(names)) == len(names), names)
            checks.check("every tool is described", all(tool.description for tool in listing.tools))
            checks.check("every tool has an object input schema",
                         all((attr(tool, "input_schema", "inputSchema") or {}).get("type") == "object" for tool in listing.tools))

            async def call(name: str, arguments: dict | None = None):
                result = await session.call_tool(name, arguments or {})
                structured = attr(result, "structured_content", "structuredContent")
                return result, structured

            result, data = await call("estimate", {"orders": 8, "bpm": 160})
            checks.check("estimate", not attr(result, "is_error", "isError") and data["duration_seconds"] == 48.0, data)
            summary["estimate"] = data["duration_seconds"]
            checks.check("estimate text mirrors structuredContent", json.loads(text_of(result)) == data)

            result, data = await call("validate", {"source": "song.project.json", "report": True})
            checks.check("validate", not attr(result, "is_error", "isError") and data.get("ok") is True, data)
            summary["validate"] = {key: data.get(key) for key in ("ok", "orders", "title") if key in data}

            result, data = await call("inspect", {"source": "song.project.json", "pattern": 0, "grid": True, "rows": 4})
            checks.check("inspect grid", not attr(result, "is_error", "isError") and len(data.get("pattern", {}).get("grid", [])) == 4, data)
            summary["inspect_grid_rows"] = len(data.get("pattern", {}).get("grid", []))

            patched = work / "patched.project.json"
            original = project.read_bytes()
            ops = [{"op": "set", "pattern": 0, "row": 2, "channel": 0, "cell": "G-2 04 ..."}]
            result, data = await call("patch", {"source": "song.project.json", "output": "patched.project.json",
                                                "ops": ops, "label": "smoke"})
            checks.check("patch writes a validated copy", not attr(result, "is_error", "isError") and patched.exists(), data)
            checks.check("patch left the source untouched", project.read_bytes() == original)

            result, data = await call("report", {"source": "patched.project.json"})
            checks.check("report", not attr(result, "is_error", "isError") and data.get("ok") is not False, data)
            summary["report_keys"] = sorted(data)[:8]

            result, data = await call("synth_types")
            checks.check("synth_types", not attr(result, "is_error", "isError") and bool(data.get("types")), data)
            summary["synth_types"] = [item["type"] for item in data["types"]]

            # Failures arrive as tool results the model can read.
            result, data = await call("patch", {"source": "song.project.json", "output": "bad.project.json", "ops": [
                {"op": "set", "pattern": 0, "row": 2, "channel": 0, "note": "H-2"}]})
            checks.check("CLI failure is a tool error with its code",
                         attr(result, "is_error", "isError") is True and data.get("code") == "NOTE_UNKNOWN", data)
            checks.check("failed patch wrote nothing", not (work / "bad.project.json").exists())
            result, data = await call("estimate", {"orders": "eight"})
            checks.check("bad arguments are a tool error with INVALID_ARGUMENTS",
                         attr(result, "is_error", "isError") is True and data.get("code") == "INVALID_ARGUMENTS", data)
            try:
                await session.call_tool("no_such_tool", {})
                checks.check("unknown tool is a protocol error", False)
            except Exception as exc:  # noqa: BLE001
                checks.check("unknown tool is a protocol error (-32602)", error_code(exc) == -32602, repr(exc))

            # Live tools against the headless session started above.
            result, data = await call("live_sessions")
            sessions = data.get("sessions", [])
            checks.check("live_sessions finds the headless server",
                         any(item.get("pid") == live_info["pid"] for item in sessions) and all("token" not in item for item in sessions), data)
            result, status = await call("live_status")
            checks.check("live_status", not attr(result, "is_error", "isError") and status.get("revision") == 0, status)
            result, data = await call("live_score", {"pattern": 0, "row": 0, "rows": 4})
            checks.check("live_score", not attr(result, "is_error", "isError") and bool(data.get("lines")), data)
            result, data = await call("live_patch", {"ops": ops, "base_revision": status["revision"],
                                                     "label": "smoke live edit", "author": "mcp-smoke"})
            checks.check("live_patch applies with base_revision", not attr(result, "is_error", "isError"), data)
            result, data = await call("live_changes", {"since": 0})
            changes = data.get("changes") or data.get("entries") or []
            checks.check("live_changes lists the agent edit", bool(changes) and "smoke live edit" in json.dumps(data), data)
            result, data = await call("live_patch", {"ops": [{"op": "set", "pattern": 0, "row": 2, "channel": 0, "cell": "A-2 04 ..."}],
                                                     "base_revision": 0, "label": "stale overlap"})
            checks.check("live_patch refuses an overlap with an old base_revision as a tool error",
                         attr(result, "is_error", "isError") is True and data.get("code") == "LIVE_CONFLICT", data)
            result, data = await call("live_patch", {"ops": [{"op": "set", "pattern": 0, "row": 6, "channel": 1, "cell": "C-2 04 ..."}],
                                                     "propose": True, "label": "smoke proposal"})
            checks.check("live_patch propose=true creates a proposal", not attr(result, "is_error", "isError"), data)
            proposal = data.get("proposal", {}).get("id") or data.get("id")
            result, data = await call("live_proposals")
            checks.check("live_proposals lists it", not attr(result, "is_error", "isError") and "smoke proposal" in json.dumps(data), data)
            if proposal:
                result, data = await call("live_withdraw", {"id": proposal})
                checks.check("live_withdraw", not attr(result, "is_error", "isError"), data)
            result, data = await call("live_save", {"output": "live-copy.project.json"})
            checks.check("live_save copy", not attr(result, "is_error", "isError") and (work / "live-copy.project.json").exists(), data)
            summary["live"] = {"pid": live_info["pid"], "revision_after_patch": (await call("live_status"))[1].get("revision")}
        summary["server_stderr_bytes"] = log_path.stat().st_size
    finally:
        stop_process(live_process, live_info.get("pid"))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--server-python", default=sys.executable, help="Interpreter that runs `chiploom mcp`.")
    parser.add_argument("--repo", type=Path, default=REPO, help="Checkout providing the tracker4agents package.")
    arguments = parser.parse_args()
    checks = Checks()
    try:
        version = metadata.version("mcp")
    except metadata.PackageNotFoundError:
        print(json.dumps({"ok": False, "error": "The `mcp` package is not installed in this interpreter."}))
        return 2
    with tempfile.TemporaryDirectory(prefix="chiploom-mcp-smoke-", ignore_cleanup_errors=True) as temporary:
        try:
            summary = asyncio.run(run(arguments.server_python, arguments.repo.resolve(), Path(temporary), checks))
        except Exception as exc:  # noqa: BLE001 - report any SDK or transport failure in the summary
            summary = {}
            checks.failed.append(f"exception: {type(exc).__name__}: {exc}")
    report = {"ok": not checks.failed, "mcp_sdk": version, "python": sys.version.split()[0], **summary,
              "passed": len(checks.passed), "failed": checks.failed}
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
