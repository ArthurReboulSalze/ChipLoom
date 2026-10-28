"""`chiploom mcp` driven by the official Python MCP SDK as a real client.

The SDK is not a ChipLoom dependency. Point CHIPLOOM_MCP_CLIENT_PYTHON at a Python
interpreter that has the `mcp` package (for example one in a separate virtual
environment); without it these tests are skipped. See docs/MCP.md.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

from tracker4agents.mcp_server import TOOLS

ROOT = Path(__file__).resolve().parents[1]
CLIENT_PYTHON = os.environ.get("CHIPLOOM_MCP_CLIENT_PYTHON", "").strip()


@unittest.skipUnless(CLIENT_PYTHON and Path(CLIENT_PYTHON).exists(),
                     "set CHIPLOOM_MCP_CLIENT_PYTHON to a Python interpreter that has the `mcp` package")
class OfficialSdkClientTests(unittest.TestCase):
    def test_smoke_script_passes_with_the_official_sdk(self):
        completed = subprocess.run(
            [CLIENT_PYTHON, str(ROOT / "tools" / "mcp_smoke.py"), "--server-python", sys.executable,
             "--repo", str(ROOT)],
            capture_output=True, text=True, encoding="utf-8", timeout=600, stdin=subprocess.DEVNULL)
        try:
            report = json.loads(completed.stdout)
        except ValueError:
            self.fail(f"The smoke script printed no JSON.\nstdout: {completed.stdout}\nstderr: {completed.stderr}")
        self.assertEqual(report["failed"], [], json.dumps(report, indent=2))
        self.assertTrue(report["ok"])
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(report["server"]["name"], "chiploom")
        self.assertEqual(report["tool_count"], len(TOOLS))
        self.assertGreaterEqual(report["passed"], 25)
        self.assertEqual(report["server_stderr_bytes"], 0)  # Nothing but protocol traffic on the pipes.


if __name__ == "__main__":
    unittest.main()
