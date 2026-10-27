"""Batch edit operations: one validated transaction, grid text and three-way merge."""
from __future__ import annotations

import copy
from pathlib import Path
import unittest

from tracker4agents import mod
from tracker4agents.document import Document
from tracker4agents.model import EMPTY, Module, Pattern, Sample, ValidationError, cell
from tracker4agents.patch import (
    apply_ops, cell_text, diff_modules, merge_modules, parse_cell, pattern_grid, summarize, touched,
)

ROOT = Path(__file__).resolve().parents[1]


def tiny() -> Module:
    pattern = Pattern("Intro")
    pattern.put(0, 0, cell("C-2", 1, "F06"))
    pattern.put(4, 1, cell("E-2", 2))
    samples = [Sample("Pulse", (0, 0, 40, -40) * 8, 40, 0, 0, 0), Sample("Bass", (0, 0, 60, -60) * 8)]
    return Module("Tiny", samples, [pattern], [0])


class GridTextTests(unittest.TestCase):
    def test_cell_text_round_trip(self):
        for text in ("C-2 01 C20", "--- -- ...", "G#3 1F ...", "--- 02 A03"):
            self.assertEqual(cell_text(parse_cell(text)), text)
        self.assertEqual(parse_cell(""), EMPTY)
        self.assertEqual(parse_cell("C-3"), cell("C-3"))
        self.assertEqual(parse_cell("e-2 0a"), cell("E-2", 10))

    def test_bad_cell_text_has_a_code(self):
        for text in ("C-2 XY 000", "C-2 01 0000 extra", 12):
            with self.assertRaises(ValidationError) as caught:
                parse_cell(text)
            self.assertEqual(caught.exception.code, "PATCH_CELL")

    def test_grid_lines(self):
        lines = pattern_grid(tiny(), 0, 0, 5)
        self.assertEqual(lines[0], "00 | C-2 01 F06 | --- -- ... | --- -- ... | --- -- ...")
        self.assertEqual(lines[4], "04 | --- -- ... | E-2 02 ... | --- -- ... | --- -- ...")


class OperationTests(unittest.TestCase):
    def test_write_set_and_lines(self):
        module = tiny()
        apply_ops(module, [
            {"op": "write", "pattern": 0, "channel": 2, "row": 8, "step": 2, "cells": ["G-2 01", "", "A-2 01 C20"]},
            {"op": "set", "pattern": 0, "row": 4, "channel": 1, "effect": "C10"},
            {"op": "write", "pattern": 0, "row": 16, "lines": ["10 | C-1 02 ... | --- -- ... | --- -- ... | --- -- E01"]},
        ])
        grid = pattern_grid(module, 0)
        self.assertIn("G-2 01 ...", grid[8])
        self.assertIn("--- -- ...", grid[10].split("|")[3])
        self.assertIn("A-2 01 C20", grid[12])
        self.assertIn("E-2 02 C10", grid[4])
        self.assertTrue(grid[16].endswith("--- -- E01"))

    def test_move_and_copy_blocks(self):
        module = tiny()
        apply_ops(module, [{"op": "move", "pattern": 0, "row": 0, "channel": 0, "rows": 5, "channels": 2, "to_row": 1}])
        self.assertEqual(module.patterns[0].get(0, 0), EMPTY)
        self.assertEqual(module.patterns[0].get(1, 0).note, "C-2")
        self.assertEqual(module.patterns[0].get(5, 1).note, "E-2")
        apply_ops(module, [{"op": "copy", "pattern": 0, "row": 1, "rows": 1, "to_channel": 3}])
        self.assertEqual(module.patterns[0].get(1, 3), module.patterns[0].get(1, 0))
        with self.assertRaises(ValidationError) as caught:
            apply_ops(module, [{"op": "move", "pattern": 0, "row": 60, "rows": 4, "to_row": 62}])
        self.assertEqual(caught.exception.code, "PATCH_BOUNDS")

    def test_structure_operations(self):
        module = tiny()
        results = apply_ops(module, [
            {"op": "add_pattern", "copy_of": 0, "name": "Chorus"},
            {"op": "add_pattern", "insert_order": 0},
            {"op": "move_order", "at": 0, "to": 2},
            {"op": "rename_pattern", "pattern": 0, "name": "Verse"},
            {"op": "title", "title": "Renamed"},
            {"op": "sample", "slot": 2, "volume": 30, "finetune": -2, "name": "Bass Low"},
        ])
        self.assertEqual(results[0], {"op": "add_pattern", "pattern": 1, "order": 1})
        self.assertEqual(module.orders, [0, 1, 2])
        self.assertEqual(module.patterns[1].name, "Chorus")
        self.assertEqual((module.samples[1].volume, module.samples[1].finetune), (30, -2))
        apply_ops(module, [{"op": "remove_order", "at": 1}, {"op": "remove_pattern", "pattern": 1}])
        self.assertEqual(module.orders, [0, 1])
        self.assertEqual(len(module.patterns), 2)

    def test_unknown_operation_or_field_is_rejected_with_index(self):
        for ops, code in (([{"op": "explode"}], "PATCH_OP"),
                          ([{"op": "title", "title": "x"}, {"op": "set", "pattern": 0, "row": 0, "channel": 0, "colour": 1}],
                           "UNKNOWN_FIELD"),
                          ([], "PATCH_FORMAT")):
            with self.assertRaises(ValidationError) as caught:
                apply_ops(tiny(), ops)
            self.assertEqual(caught.exception.code, code)
        with self.assertRaisesRegex(ValidationError, r"ops\[1\]"):
            apply_ops(tiny(), [{"op": "title", "title": "x"}, {"op": "set", "pattern": 0, "row": 0, "channel": 0, "colour": 1}])


class DocumentPatchTests(unittest.TestCase):
    def test_patch_is_one_atomic_undoable_transaction(self):
        document = Document(tiny())
        before = copy.deepcopy(document.module)
        result = document.patch([{"op": "set", "pattern": 0, "row": 2, "channel": 0, "cell": "D-2 01 ..."},
                                 {"op": "transpose", "pattern": 0, "channel": 0, "semitones": 12}], "Agent line")
        self.assertTrue(result["changed"])
        self.assertEqual(document.module.patterns[0].get(2, 0).note, "D-3")
        self.assertEqual(len(result["diff"]["cells"]), 2)
        self.assertTrue(document.undo())
        self.assertEqual(document.module, before)
        # A failing later operation leaves no partial edit behind.
        with self.assertRaises(ValidationError):
            document.patch([{"op": "set", "pattern": 0, "row": 2, "channel": 0, "cell": "D-2 01 ..."},
                            {"op": "set", "pattern": 0, "row": 3, "channel": 0, "sample": 9}])
        self.assertEqual(document.module, before)

    def test_unused_pattern_without_order_is_rejected(self):
        document = Document(tiny())
        with self.assertRaises(ValidationError):
            document.patch([{"op": "add_pattern", "insert_order": None}])

    def test_patched_example_exports(self):
        document = Document.open(ROOT / "examples/pixel_rush.project.json")
        document.patch([{"op": "add_pattern", "copy_of": 2, "name": "Echo"},
                        {"op": "transpose", "pattern": 7, "channel": 3, "semitones": -12}])
        self.assertEqual(mod.decode(mod.encode(document.module)).orders[-1], 7)


class DiffAndMergeTests(unittest.TestCase):
    def test_diff_summary_and_touched_keys(self):
        before, after = tiny(), tiny()
        apply_ops(after, [{"op": "set", "pattern": 0, "row": 4, "channel": 1, "note": "G-2"},
                          {"op": "add_pattern"}, {"op": "title", "title": "New"}])
        diff = diff_modules(before, after)
        self.assertEqual(diff["cells"], [{"pattern": 0, "row": 4, "channel": 1, "before": "E-2 02 ...", "after": "G-2 02 ..."}])
        self.assertIn(("cell", 0, 4, 1), touched(diff))
        self.assertIn(("structure",), touched(diff))
        self.assertIn("P00 r04 ch2: E-2 02 ... → G-2 02 ...", summarize(diff))

    def test_three_way_merge_keeps_both_sides_and_reports_conflicts(self):
        base = tiny()
        mine, theirs = copy.deepcopy(base), copy.deepcopy(base)
        apply_ops(mine, [{"op": "set", "pattern": 0, "row": 8, "channel": 0, "cell": "A-2 01 ..."},
                         {"op": "set", "pattern": 0, "row": 9, "channel": 0, "cell": "B-2 01 ..."}])
        apply_ops(theirs, [{"op": "set", "pattern": 0, "row": 12, "channel": 2, "cell": "C-3 02 ..."},
                           {"op": "set", "pattern": 0, "row": 9, "channel": 0, "cell": "G-2 01 ..."},
                           {"op": "title", "title": "Agent"}])
        merged, conflicts = merge_modules(base, mine, theirs)
        self.assertEqual(merged.patterns[0].get(8, 0).note, "A-2")
        self.assertEqual(merged.patterns[0].get(12, 2).note, "C-3")
        self.assertEqual(merged.patterns[0].get(9, 0).note, "G-2")
        self.assertEqual(merged.title, "Agent")
        self.assertEqual(conflicts, [{"unit": "cell", "pattern": 0, "row": 9, "channel": 0,
                                      "mine": "B-2 01 ...", "theirs": "G-2 01 ..."}])

    def test_merge_structure_from_one_side(self):
        base = tiny()
        mine, theirs = copy.deepcopy(base), copy.deepcopy(base)
        apply_ops(mine, [{"op": "add_pattern", "copy_of": 0}])
        apply_ops(theirs, [{"op": "set", "pattern": 0, "row": 1, "channel": 3, "cell": "C-2 02 ..."}])
        merged, conflicts = merge_modules(base, mine, theirs)
        self.assertEqual(conflicts, [])
        self.assertEqual(merged.orders, [0, 1])
        self.assertEqual(merged.patterns[0].get(1, 3).note, "C-2")


if __name__ == "__main__":
    unittest.main()
