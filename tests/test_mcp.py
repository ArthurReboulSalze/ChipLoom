"""The MCP stdio adapter, exercised as a real child process speaking JSON-RPC."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tracker4agents import project
from tracker4agents.mcp_server import TOOLS, Server, cli_prefix

ROOT = Path(__file__).resolve().parents[1]


class McpProcess:
    def __init__(self, cwd: Path):
        self.process = subprocess.Popen([sys.executable, "-m", "tracker4agents", "mcp"], cwd=cwd, text=True,
                                        encoding="utf-8", stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE)
        self.counter = 0

    def request(self, method, params=None):
        self.counter += 1
        message = {"jsonrpc": "2.0", "id": self.counter, "method": method}
        if params is not None:
            message["params"] = params
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()
        return json.loads(self.process.stdout.readline())

    def notify(self, method):
        self.process.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method}) + "\n")
        self.process.stdin.flush()

    def close(self):
        self.process.stdin.close()
        self.process.wait(timeout=20)
        self.process.stdout.close()
        self.process.stderr.close()


class McpProtocolTests(unittest.TestCase):
    def test_a_frozen_cli_starts_itself_without_dash_m(self):
        # The standalone chiploom-cli has no `-m`: its MCP tools must call the program itself.
        self.assertEqual(cli_prefix(), [sys.executable, "-m", "tracker4agents"])
        with patch.object(sys, "frozen", True, create=True):
            self.assertEqual(cli_prefix(), [sys.executable])

    def test_handshake_listing_and_tool_calls(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            source = directory / "song.json"
            source.write_bytes((ROOT / "examples/pixel_rush.project.json").read_bytes())
            server = McpProcess(directory)
            try:
                hello = server.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                                      "clientInfo": {"name": "test", "version": "1"}})
                self.assertEqual(hello["result"]["protocolVersion"], "2025-06-18")
                self.assertEqual(hello["result"]["serverInfo"]["name"], "chiploom")
                self.assertIn("tools", hello["result"]["capabilities"])
                server.notify("notifications/initialized")
                names = {tool["name"] for tool in server.request("tools/list")["result"]["tools"]}
                self.assertTrue({"estimate", "validate", "patch", "live_patch", "report"} <= names)
                self.assertTrue({"synth_types", "synth_levels", "synth_preview", "synth_add", "synth_palette"} <= names)

                types = server.request("tools/call", {"name": "synth_types", "arguments": {}})
                self.assertFalse(types["result"]["isError"])
                self.assertIn("wave", [item["type"] for item in types["result"]["structuredContent"]["types"]])
                palette = server.request("tools/call", {"name": "synth_palette", "arguments": {
                    "output": "palette.json", "no_match": True}})
                self.assertFalse(palette["result"]["isError"], palette)
                added = server.request("tools/call", {"name": "synth_add", "arguments": {
                    "project": "palette.json", "output": "palette2.json", "name": "Saw",
                    "recipe": {"type": "wave", "shape": "saw", "frequency": 130.8}, "no_match": True}})
                self.assertFalse(added["result"]["isError"], added)
                self.assertEqual(added["result"]["structuredContent"]["slot"], 14)
                refused = server.request("tools/call", {"name": "validate", "arguments": {
                    "source": "song.json", "sample_source": "library"}})
                self.assertEqual(refused["result"]["structuredContent"]["code"], "SAMPLE_SOURCE")

                estimate = server.request("tools/call", {"name": "estimate", "arguments": {"orders": 8, "bpm": 160}})
                self.assertFalse(estimate["result"]["isError"])
                self.assertEqual(estimate["result"]["structuredContent"]["duration_seconds"], 48.0)

                patched = server.request("tools/call", {"name": "patch", "arguments": {
                    "source": "song.json", "output": "song-v2.json",
                    "ops": [{"op": "set", "pattern": 0, "row": 2, "channel": 0, "cell": "G-2 04 ..."}]}})
                self.assertFalse(patched["result"]["isError"], patched)
                self.assertEqual(project.load(directory / "song-v2.json").patterns[0].get(2, 0).note, "G-2")

                failure = server.request("tools/call", {"name": "patch", "arguments": {
                    "source": "song.json", "output": "bad.json",
                    "ops": [{"op": "set", "pattern": 0, "row": 2, "channel": 0, "note": "H-2"}]}})
                self.assertTrue(failure["result"]["isError"])
                self.assertEqual(failure["result"]["structuredContent"]["code"], "NOTE_UNKNOWN")
                self.assertFalse((directory / "bad.json").exists())

                invalid = server.request("tools/call", {"name": "estimate", "arguments": {"orders": "eight"}})
                self.assertTrue(invalid["result"]["isError"])  # A tool error the model can read and correct.
                self.assertEqual(invalid["result"]["structuredContent"]["code"], "INVALID_ARGUMENTS")
                unknown = server.request("tools/call", {"name": "no_such_tool", "arguments": {}})
                self.assertEqual(unknown["error"]["code"], -32602)
                self.assertEqual(server.request("nope")["error"]["code"], -32601)
                self.assertEqual(server.request("ping")["result"], {})
            finally:
                server.close()

    def test_library_song_from_a_blank_eight_channel_project(self):
        # A library-mode song from scratch: new_project, then library_sample with the default bank and ops_file.
        from tracker4agents import mod
        from tracker4agents.model import Module, Pattern, Sample, cell
        from tracker4agents.sample_library import SampleLibrary
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            reference = directory / "ref.mod"
            reference.write_bytes(mod.encode(Module("t", [Sample("a", (50, -50) * 8, 64, 0, 0, 16)],
                                                    [Pattern(cells={(0, 0): cell("C-2", 1)})], [0])))
            SampleLibrary(directory / "exports" / "sample_library").extract(reference)
            server = McpProcess(directory)
            try:
                server.request("initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                                              "clientInfo": {"name": "test", "version": "1"}})
                created = server.request("tools/call", {"name": "new_project", "arguments": {
                    "output": "songs/blank.json", "channels": 8, "bpm": 120, "patterns": 2, "title": "Eight"}})
                self.assertFalse(created["result"]["isError"], created)
                content = created["result"]["structuredContent"]
                self.assertEqual((content["channels"], content["profile"], content["sample_source"]),
                                 (8, "protracker-nch-pal-v1", "library"))
                again = server.request("tools/call", {"name": "new_project", "arguments": {"output": "songs/blank.json"}})
                self.assertEqual(again["result"]["structuredContent"]["code"], "OUTPUT_PATH")

                (directory / "ops.json").write_text(json.dumps([
                    {"op": "library_sample", "id": "SMP-0001"},
                    {"op": "set", "pattern": 1, "row": 0, "channel": 7, "cell": "C-2 01 ..."}]), encoding="utf-8")
                patched = server.request("tools/call", {"name": "patch", "arguments": {
                    "source": "songs/blank.json", "output": "songs/v1.json", "ops_file": "ops.json"}})
                self.assertFalse(patched["result"]["isError"], patched)
                self.assertIn("P01 r00 ch7: --- -- ... → C-2 01 ...", patched["result"]["structuredContent"]["changes"])
                song = project.load(directory / "songs/v1.json")
                self.assertEqual((song.channels, song.patterns[1].get(0, 7).note), (8, "C-2"))
                self.assertEqual(len(song.samples), 1)  # the empty slot was filled, not followed
                checked = server.request("tools/call", {"name": "validate", "arguments": {
                    "source": "songs/v1.json", "sample_source": "library"}})
                self.assertFalse(checked["result"]["isError"], checked)

                for arguments in ({}, {"ops": [], "ops_file": "ops.json"}):
                    refused = server.request("tools/call", {"name": "patch", "arguments": {
                        "source": "songs/blank.json", "output": "songs/x.json", **arguments}})
                    self.assertEqual(refused["result"]["structuredContent"]["code"], "INVALID_ARGUMENTS")
                empty = directory / "empty.json"
                data = project.read_json(directory / "songs/blank.json")
                project.write_json(empty, {**data, "samples": []})
                invalid = server.request("tools/call", {"name": "validate", "arguments": {"source": "empty.json",
                                                                                          "report": True}})
                message = invalid["result"]["structuredContent"]["errors"][0]["message"]
                self.assertIn("array of 1 to 31 entries expected", message)
                self.assertIn("new_project", message)
            finally:
                server.close()

    def test_schemas_are_strict_and_cover_every_tool(self):
        server = Server()
        for tool in TOOLS:
            self.assertFalse(tool["inputSchema"]["additionalProperties"])
            response = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                      "params": {"name": tool["name"], "arguments": {"unexpected": 1}}})
            self.assertTrue(response["result"]["isError"], tool["name"])
            self.assertEqual(response["result"]["structuredContent"]["code"], "INVALID_ARGUMENTS", tool["name"])
        self.assertIsNone(server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        self.assertIsNone(server.handle({"jsonrpc": "2.0", "id": 9, "result": {}}))  # A client's answer: no reply.
        self.assertEqual(server.handle({"jsonrpc": "1.0", "id": 3, "method": "ping"})["error"]["code"], -32600)

    def test_schemas_suit_strict_clients(self):
        for tool in TOOLS:
            schema = tool["inputSchema"]
            self.assertNotEqual(schema.get("required"), [], tool["name"])  # Omitted rather than empty.
            self.assertTrue(set(schema.get("required", ())) <= set(schema["properties"]), tool["name"])
            for name, spec in schema["properties"].items():
                self.assertIn("type", spec, f"{tool['name']}.{name}")  # Enums carry their type too.
            self.assertFalse(tool["annotations"]["openWorldHint"])

    def test_protocol_negotiation_and_object_results(self):
        server = Server()
        for requested, expected in (("2025-11-25", "2025-11-25"), ("2024-11-05", "2024-11-05"),
                                    ("2026-07-28", "2025-11-25"), (None, "2025-11-25")):
            params = {"capabilities": {}} | ({"protocolVersion": requested} if requested else {})
            result = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": params})["result"]
            self.assertEqual(result["protocolVersion"], expected)
        self.assertEqual(Server._tool_result(True, ["a"])["structuredContent"], {"result": ["a"]})
        self.assertIsInstance(server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {"cursor": "x"}})
                              ["result"]["tools"], list)

    def test_sound_workshop_tools(self):
        """Sample editing, drawn waves, waveform summaries and instruments, through the tool interface."""
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "song.json").write_bytes((ROOT / "examples/pixel_rush.project.json").read_bytes())
            server = Server(directory)

            def call(name, arguments):
                result = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                        "params": {"name": name, "arguments": arguments}})["result"]
                return result["isError"], result["structuredContent"]

            names = {tool["name"] for tool in TOOLS}
            self.assertTrue({"sample_schema", "sample_edit", "sample_draw", "sample_waveform", "instruments_list",
                             "instruments_show", "instruments_save", "instruments_delete",
                             "instruments_apply"} <= names)
            error, schema = call("sample_schema", {})
            self.assertFalse(error)
            self.assertIn("draw", [item["type"] for item in schema["types"]])
            error, edited = call("sample_edit", {"project": "song.json", "slot": 1, "output": "edited.json",
                                                 "trim": [0, 400], "fade": [0, 40], "gain": -2})
            self.assertFalse(error, edited)
            self.assertEqual((edited["sample"]["bytes"], edited["sample"]["recipe"]), (400, False))
            self.assertEqual(edited["sample"]["provenance"]["derived_from"], "recipe")
            error, refused = call("sample_edit", {"project": "song.json", "slot": 1, "output": "x.json", "gain": 30})
            self.assertEqual((error, refused["code"]), (True, "SAMPLE_CLIP"))
            error, waveform = call("sample_waveform", {"source": "edited.json", "slot": 1, "buckets": 8})
            self.assertEqual((error, len(waveform["buckets"])), (False, 8))
            error, drawn = call("sample_draw", {"project": "song.json", "slot": 14, "points": [0, 1, 0, -1],
                                                "cycles": 8, "output": "drawn.json", "name": "Hand"})
            self.assertFalse(error, drawn)
            self.assertEqual((drawn["sample"]["slot"], drawn["sample"]["looped"]), (14, True))
            error, saved = call("instruments_save", {"dir": "inst", "name": "Pluck", "phrase": ["000", "C30", "C10"],
                                                     "recipe": {"type": "wave", "shape": "triangle"}, "tag": ["bass"]})
            self.assertFalse(error, saved)
            self.assertEqual(saved["instrument"]["id"], "INS-0001")
            error, listing = call("instruments_list", {"dir": "inst", "tag": ["bass"]})
            self.assertEqual((error, listing["total"]), (False, 1))
            error, shown = call("instruments_show", {"dir": "inst", "id": "INS-0001"})
            self.assertEqual(shown["instrument"]["phrase"], ["000", "C30", "C10"])
            error, applied = call("instruments_apply", {"project": "song.json", "output": "applied.json", "dir": "inst",
                                                        "instrument": "INS-0001", "pattern": 0, "channel": 1,
                                                        "row": 2, "note": "C-2"})
            self.assertFalse(error, applied)
            self.assertEqual(applied["applied"]["slot"], 14)
            self.assertEqual(project.load(directory / "applied.json").patterns[0].get(2, 1).sample, 14)
            error, deleted = call("instruments_delete", {"dir": "inst", "id": "INS-0001"})
            self.assertEqual((error, deleted["deleted"]), (False, "INS-0001"))
            error, missing = call("instruments_show", {"dir": "inst", "id": "INS-0001"})
            self.assertEqual((error, missing["code"]), (True, "INSTRUMENT_NOT_FOUND"))
            # The edit operations are also reachable through the generic patch tool.
            error, patched = call("patch", {"source": "song.json", "output": "patched.json", "ops": [
                {"op": "sample_gain", "slot": 1, "db": -3}, {"op": "sample_match_level", "slot": 2, "role": "snare"}]})
            self.assertFalse(error, patched)
            self.assertEqual([item["op"] for item in patched["results"]], ["sample_gain", "sample_match_level"])

    def test_documentation_lists_exactly_the_tools(self):
        sys.path.insert(0, str(ROOT / "tools"))
        try:
            import mcp_docs
        finally:
            sys.path.remove(str(ROOT / "tools"))
        self.assertTrue(mcp_docs.is_current(), "docs/MCP.md is out of date; run: python tools/mcp_docs.py --write")


if __name__ == "__main__":
    unittest.main()
