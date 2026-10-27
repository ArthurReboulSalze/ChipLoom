"""The MCP stdio adapter, exercised as a real child process speaking JSON-RPC."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tracker4agents import project
from tracker4agents.mcp_server import TOOLS, Server

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
                self.assertEqual(invalid["error"]["code"], -32602)
                self.assertEqual(server.request("nope")["error"]["code"], -32601)
                self.assertEqual(server.request("ping")["result"], {})
            finally:
                server.close()

    def test_schemas_are_strict_and_cover_every_tool(self):
        server = Server()
        for tool in TOOLS:
            self.assertFalse(tool["inputSchema"]["additionalProperties"])
            response = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                      "params": {"name": tool["name"], "arguments": {"unexpected": 1}}})
            self.assertEqual(response["error"]["code"], -32602, tool["name"])
        self.assertIsNone(server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        self.assertEqual(server.handle({"jsonrpc": "1.0", "id": 3, "method": "ping"})["error"]["code"], -32600)


if __name__ == "__main__":
    unittest.main()
