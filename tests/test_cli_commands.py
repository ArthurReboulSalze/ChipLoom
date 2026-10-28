"""CLI contracts for patch, inspect --grid, report and feedback."""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from tracker4agents import cli, mod, project

ROOT = Path(__file__).resolve().parents[1]


def run(*argv: str) -> tuple[int, dict]:
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        status = cli.main([str(value) for value in argv])
    return status, json.loads(stdout.getvalue() if status == 0 else stderr.getvalue())


class CliCommandTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.source = self.directory / "song.json"
        self.source.write_bytes((ROOT / "examples/pixel_rush.project.json").read_bytes())
        self.original = self.source.read_bytes()

    def tearDown(self):
        self.temporary.cleanup()

    def test_patch_writes_a_compact_v2_project_and_keeps_the_source(self):
        ops = self.directory / "ops.json"
        ops.write_text(json.dumps([{"op": "write", "pattern": 0, "channel": 3, "row": 2, "cells": ["C-3 08 ...", "D-3 08"]}]),
                       encoding="utf-8")
        status, result = run("patch", self.source, "--output", self.directory / "out.json", "--ops", ops,
                             "--op", '{"op": "title", "title": "Pixel Rush 2"}')
        self.assertEqual((status, result.get("code")), (2, "PATCH_FORMAT"))  # --ops and --op are exclusive
        status, result = run("patch", self.source, "--output", self.directory / "out.json", "--ops", ops)
        self.assertEqual(status, 0, result)
        self.assertEqual(result["changes"], ["P00 r02 ch3: --- -- 603 → C-3 08 ...", "P00 r03 ch3: --- -- C00 → D-3 08 ..."])
        written = json.loads((self.directory / "out.json").read_text(encoding="utf-8"))
        self.assertEqual(written["schema"], project.SCHEMA_V2)
        self.assertEqual(written["patterns"][0]["rows"]["02"].split(" | ")[3], "C-3 08 ...")
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertLess((self.directory / "out.json").stat().st_size, len(self.original) / 4)

    def test_patch_refuses_to_overwrite_without_in_place_and_reports_codes(self):
        status, result = run("patch", self.source, "--output", self.source, "--op", '{"op": "title", "title": "x"}')
        self.assertEqual((status, result["code"]), (2, "OUTPUT_PATH"))
        status, result = run("patch", self.source, "--output", self.source, "--in-place",
                             "--op", '[{"op": "title", "title": "Edited"}, {"op": "sample", "slot": 1, "volume": 99}]')
        self.assertEqual((status, result["code"]), (2, "INTEGER_RANGE"))
        self.assertIn("ops[1]", result["message"])
        self.assertEqual(self.source.read_bytes(), self.original)
        status, result = run("patch", self.source, "--output", self.source, "--in-place", "--op", '{"op": "title", "title": "Edited"}')
        self.assertEqual(status, 0, result)
        self.assertEqual(project.load(self.source).title, "Edited")

    def test_patch_guards_revisions_and_reports_what_changed(self):
        first = self.directory / "v2.json"
        status, result = run("patch", self.source, "--output", first,
                             "--op", '[{"op": "sample", "slot": 1, "volume": 30, "name": "Kick 2"},'
                                     ' {"op": "rename_pattern", "pattern": 0, "name": "Opening"}]')
        self.assertEqual(status, 0, result)
        self.assertIn("sample 01 changed: name, volume", result["changes"])
        self.assertIn("pattern 00 renamed", result["changes"])
        status, result = run("patch", self.source, "--output", first, "--op", '{"op": "title", "title": "x"}')
        self.assertEqual((status, result["code"]), (2, "OUTPUT_PATH"))  # an earlier revision is never clobbered
        self.assertEqual(project.load(first).title, project.load(self.source).title)
        status, result = run("patch", self.source, "--output", first, "--overwrite", "--op", '{"op": "title", "title": "x"}')
        self.assertEqual(status, 0, result)
        status, result = run("patch", self.source, "--output", self.directory / "v3.json", "--ops", self.directory / "none.json")
        self.assertEqual((status, result["code"]), (2, "IO_ERROR"))
        self.assertIn(str((self.directory / "none.json").resolve()), result["message"])
        (self.directory / "object.json").write_text('{"title": "x"}', encoding="utf-8")
        status, result = run("patch", self.source, "--output", self.directory / "v3.json", "--ops", self.directory / "object.json")
        self.assertEqual((status, result["code"]), (2, "PATCH_FORMAT"))
        status, result = run("patch", self.source, "--output", self.directory / "v3.json", "--op", '{"title": "x"}')
        self.assertEqual((status, result["code"]), (2, "PATCH_OP"))
        self.assertIn('missing "op"', result["message"])

    def test_timing_takes_bpm_or_speed_and_flow_losses_are_warned(self):
        status, result = run("patch", self.source, "--output", self.directory / "fast.json",
                             "--op", '{"op": "timing", "bpm": 150}')
        self.assertEqual(status, 0, result)
        self.assertEqual(result["results"][0], {"op": "timing", "bpm": 150, "speed": 6})
        self.assertEqual(result["warnings"], [])
        before = project.load(self.source)
        speed_cell = next(channel for channel in range(4) if before.patterns[before.orders[0]].get(0, channel).command == 15)
        status, result = run("patch", self.source, "--output", self.directory / "lost.json",
                             "--op", json.dumps({"op": "clear", "pattern": before.orders[0], "channel": speed_cell}))
        self.assertEqual(status, 0, result)
        self.assertTrue(any("Bxx/Dxx/Fxx" in warning for warning in result["warnings"]), result["warnings"])

    def test_inspect_grid_rows(self):
        status, result = run("inspect", self.source, "--pattern", 0, "--grid", "--row", 4, "--rows", 2)
        self.assertEqual(status, 0, result)
        self.assertEqual(result["pattern"]["grid"], ["04 | C-2 05 C31 | --- -- A03 | E-2 08 037 | B-2 0B C21",
                                                     "05 | --- -- ... | --- -- C00 | --- -- 037 | --- 0C 412"])

    def test_report_and_feedback(self):
        status, result = run("report", self.source)
        self.assertEqual(status, 0, result)
        self.assertEqual(result["timing"]["duration_seconds"], 48.0)
        output = self.directory / "rated.json"
        status, result = run("feedback", self.source, "--text", "Better drop", "--rating", 4, "--version", "v2",
                             "--output", output)
        self.assertEqual(status, 0, result)
        feedback = project.load(output).metadata["feedback"]
        self.assertEqual((feedback[-1]["text"], feedback[-1]["rating"], feedback[-1]["version"]), ("Better drop", 4, "v2"))
        self.assertEqual(mod.encode(project.load(output)), mod.encode(project.load(self.source)))
        status, result = run("feedback", self.source, "--text", "", "--output", self.directory / "empty.json")
        self.assertEqual(status, 2)


if __name__ == "__main__":
    unittest.main()
