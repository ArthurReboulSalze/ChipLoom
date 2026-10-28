"""The XM workflow: start an XM, add library and created samples, edit its structure and header,
convert with recipes kept, and the playback-plan warnings."""

from __future__ import annotations

import copy
import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import tempfile
import unittest

from tracker4agents import cli, convert, mod, project, synth_tools, xm
from tracker4agents.mcp_server import TOOLS_BY_NAME
from tracker4agents.model import Module, Pattern, Sample, ValidationError, cell, playback_plan, validate
from tracker4agents.patch import apply_ops
from tracker4agents.sample_library import SampleLibrary
from tracker4agents.sample_source import enforce


def run_cli(*args):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main([str(arg) for arg in args])
    return code, json.loads(out.getvalue() or err.getvalue())


def library_reference() -> bytes:
    """A MOD whose one sample has MOD finetune -2 and a loop, to extract into a temporary bank."""
    sample = Sample("Square", (0, 90, 0, -90) * 4, 40, -2, 0, 16)
    return mod.encode(Module("Bank source", [sample], [Pattern(cells={(0, 0): cell("C-2", 1)})], [0]))


class ConvertKeepsRecipesTests(unittest.TestCase):
    def test_mod_to_xm_and_back_keeps_every_recipe_and_stays_lossless(self):
        module, _ = synth_tools.palette()
        converted, report = convert.convert(module, "xm")
        self.assertTrue(report["lossless"])
        self.assertIn("RECIPES_KEPT", [note["code"] for note in report["notes"]])
        self.assertEqual([s.recipe for s in converted.samples], [s.recipe for s in module.samples])
        self.assertEqual(enforce(converted, "synthesized")["recipe"], 13)
        reloaded = project.from_dict(json.loads(project.dumps(project.to_dict(converted))))
        self.assertEqual(xm.encode(reloaded), xm.encode(converted))      # the recipes rebuild the same PCM
        back, report = convert.convert(converted, "mod")
        self.assertTrue(report["lossless"])
        self.assertEqual([s.recipe for s in back.samples], [s.recipe for s in module.samples])
        self.assertEqual(mod.encode(back), mod.encode(module))

    def test_header_defaults_follow_the_first_row_and_the_round_trip_stays_byte_identical(self):
        module, _ = synth_tools.palette()
        apply_ops(module, [{"op": "timing", "bpm": 140, "speed": 4}])
        converted, report = convert.convert(module, "xm")
        block = converted.metadata["xm"]
        self.assertEqual((block["default_speed"], block["default_bpm"]), (4, 140))
        self.assertIn("HEADER_TIMING", [note["code"] for note in report["notes"]])
        self.assertEqual(converted.patterns[0].get(0, 0).command, 15)    # the Fxx stay
        back, _ = convert.convert(converted, "mod")
        self.assertEqual(mod.encode(back), mod.encode(module))
        again, _ = convert.convert(back, "xm")
        self.assertEqual(xm.encode(again), xm.encode(converted))

    def test_xm_header_timing_without_a_matching_first_row_is_still_refused(self):
        module, _ = synth_tools.palette(fmt="xm")
        apply_ops(module, [{"op": "xm_header", "default_speed": 3}])
        with self.assertRaises(convert.ConversionRefused) as caught:
            convert.convert(module, "mod")
        self.assertIn("DEFAULT_TIMING", [item["code"] for item in caught.exception.reasons])

    def test_convert_command_writes_recipes_and_infers_the_other_format_for_json(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            source = folder / "palette.json"
            self.assertEqual(run_cli("synth", "palette", "--output", source, "--no-match")[0], 0)
            code, result = run_cli("convert", source, "--output", folder / "song.json")
            self.assertEqual(code, 0, result)
            self.assertEqual((result["from"], result["to"]), ("mod", "xm"))
            data = project.read_json(folder / "song.json")
            self.assertEqual(data["format"], "xm")
            self.assertTrue(all("recipe" in item for item in data["samples"]))
            code, result = run_cli("validate", folder / "song.json", "--sample-source", "synthesized")
            self.assertEqual(code, 0, result)
            code, result = run_cli("convert", folder / "song.json", "--output", folder / "back.json")
            self.assertEqual((code, result["to"]), (0, "mod"))
            code, result = run_cli("convert", source, "--output", folder / "copy.json", "--to", "mod")
            self.assertEqual((code, result["to"]), (0, "mod"))
            code, result = run_cli("convert", source, "--output", folder / "song.txt")
            self.assertEqual((code, result["code"]), (2, "OUTPUT_PATH"))


class LibrarySamplesIntoXmTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="chiploom xm bank ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        source = self.root / "source.mod"
        source.write_bytes(library_reference())
        self.bank = SampleLibrary(self.root / "bank")
        self.bank.extract(source)

    def test_a_library_sample_enters_an_xm_exactly_as_convert_would_convert_it(self):
        blank = xm.blank("Lib", 6, metadata={"sample_source": "library"})
        module, info = self.bank.insert(blank, "SMP-0001")
        sample = module.samples[0]
        expected = convert.mod_sample_to_xm(self.bank.sample("SMP-0001")[0])
        self.assertEqual(sample, expected)
        self.assertEqual((sample.finetune, sample.relative_note, sample.bits, sample.loop_mode, sample.panning),
                         (-52, 0, 8, "forward", 128))
        self.assertEqual(module.metadata["sample_sources"]["1"]["library_id"], "SMP-0001")
        self.assertEqual(info["xm"]["finetune"], -52)
        enforce(module, "library")

    def test_the_patch_operation_and_samples_add_both_work_on_an_xm(self):
        blank = xm.blank("Lib", 8, metadata={"sample_source": "library"})
        op = {"op": "library_sample", "id": "SMP-0001", "library": str(self.bank.path)}
        apply_ops(blank, [op, op])
        validate(blank)
        self.assertEqual([s.finetune for s in blank.samples], [-52, -52])
        start = self.root / "start.json"
        project.write_json(start, project.to_dict(xm.blank("Lib", 8, metadata={"sample_source": "library"})))
        code, result = run_cli("samples", "add", "SMP-0001", "--library", self.bank.path, "--project", start,
                               "--output", self.root / "added.json")
        self.assertEqual(code, 0, result)
        added = project.load(self.root / "added.json")
        self.assertEqual((added.format, added.samples[0].finetune), ("xm", -52))

    def test_a_library_sample_is_still_refused_in_a_synthesized_xm(self):
        blank = xm.blank("Syn", 4, metadata={"sample_source": "synthesized"})
        with self.assertRaises(ValidationError) as caught:
            self.bank.insert(blank, "SMP-0001")
        self.assertEqual(caught.exception.code, "SAMPLE_SOURCE")


class RecipesIntoXmTests(unittest.TestCase):
    def test_recipe_sample_converts_keeps_the_recipe_and_reaches_slots_past_31(self):
        module = xm.blank("Syn", 6, metadata={"sample_source": "synthesized"})
        recipe = {"type": "wave", "shape": "pulse", "duty": 0.25}
        apply_ops(module, [{"op": "recipe_sample", "name": "Lead", "recipe": recipe, "finetune": -2, "volume": 40}])
        sample = module.samples[0]
        self.assertEqual((sample.finetune, sample.recipe, sample.volume), (-52, recipe, 40))
        for index in range(2, 34):
            apply_ops(module, [{"op": "recipe_sample", "name": f"W{index}", "recipe": recipe, "volume": 30}])
        self.assertEqual(len(module.samples), 33)
        validate(module)
        enforce(module, "synthesized")
        reloaded = project.from_dict(json.loads(project.dumps(project.to_dict(module))))
        self.assertEqual(xm.encode(reloaded), xm.encode(module))

    def test_pcm_editing_operations_stay_refused_on_an_xm(self):
        module, _ = synth_tools.palette(fmt="xm")
        for op in ({"op": "sample_trim", "slot": 1, "start": 0, "end": 10}, {"op": "sample_gain", "slot": 1, "db": 1},
                   {"op": "sample_loop", "slot": 6, "loop_start": 0, "loop_length": 0}):
            with self.subTest(op=op["op"]), self.assertRaises(ValidationError) as caught:
                apply_ops(copy.deepcopy(module), [op])
            self.assertEqual(caught.exception.code, "XM_OP_UNSUPPORTED")


class NewXmAndPaletteTests(unittest.TestCase):
    def test_new_format_xm_writes_a_blank_xm(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "song.json"
            code, result = run_cli("new", "--format", "xm", "--channels", "6", "--rows", "96", "--patterns", "3",
                                   "--speed", "4", "--bpm", "140", "--sample-source", "synthesized", "--output", output)
            self.assertEqual(code, 0, result)
            self.assertEqual((result["profile"], result["channels"], result["rows_per_pattern"]),
                             ("fasttracker2-xm-v1", 6, 96))
            module = project.load(output)
            self.assertEqual((module.format, len(module.samples), module.orders), ("xm", 1, [0, 1, 2]))
            self.assertEqual([pattern.rows for pattern in module.patterns], [96, 96, 96])
            block = module.metadata["xm"]
            self.assertEqual((block["default_speed"], block["default_bpm"], block["restart_position"]), (4, 140, 0))
            self.assertEqual(module.metadata["sample_source"], "synthesized")
            self.assertFalse(any(pattern.cells for pattern in module.patterns))     # timing lives in the header
            self.assertEqual(playback_plan(module)["timeline"][0]["speed"], 4)
            code, result = run_cli("synth", "add", output, "--recipe", '{"type": "kick"}', "--name", "Kick",
                                   "--output", Path(folder) / "kick.json", "--no-match")
            self.assertEqual(code, 0, result)

    def test_new_refuses_rows_on_a_mod_and_out_of_range_values(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            for args, code_name in ((["--rows", "32"], "PATTERNS"),
                                    (["--format", "xm", "--rows", "257"], "PATTERNS"),
                                    (["--format", "xm", "--channels", "33"], "CHANNELS"),
                                    (["--format", "xm", "--bpm", "31"], "TIMING")):
                with self.subTest(args=args):
                    code, result = run_cli("new", *args, "--output", folder / "x.json")
                    self.assertEqual((code, result["code"]), (2, code_name))
                    self.assertFalse((folder / "x.json").exists())

    def test_palette_takes_a_channel_count_and_an_xm_format(self):
        module, info = synth_tools.palette(channels=8)
        self.assertEqual((module.format, module.channels, info["free_slots"]), ("mod", 8, "14-31"))
        module, info = synth_tools.palette(channels=6, fmt="xm")
        self.assertEqual((module.format, module.channels, info["free_slots"]), ("xm", 6, "14-128"))
        self.assertTrue(all(sample.recipe for sample in module.samples))
        self.assertEqual(module.samples[0].finetune, -20)
        enforce(module, "synthesized")
        with tempfile.TemporaryDirectory() as folder:
            code, result = run_cli("synth", "palette", "--channels", "6", "--format", "xm", "--no-match",
                                   "--output", Path(folder) / "p.json")
            self.assertEqual((code, result["format"], result["channels"]), (0, "xm", 6), result)
            self.assertIn("C-4", result["notation"])
            code, result = run_cli("synth", "palette", "--channels", "40", "--output", Path(folder) / "q.json")
            self.assertEqual((code, result["code"]), (2, "CHANNELS"))

    def test_mcp_schemas_carry_the_new_parameters(self):
        new = TOOLS_BY_NAME["new_project"]
        self.assertTrue({"format", "rows"} <= set(new["inputSchema"]["properties"]))
        self.assertEqual(new["argv"]({"output": "x.json", "format": "xm", "rows": 32}),
                         ["new", "--output", "x.json", "--format", "xm", "--rows", "32"])
        palette = TOOLS_BY_NAME["synth_palette"]
        self.assertTrue({"channels", "format"} <= set(palette["inputSchema"]["properties"]))
        self.assertEqual(palette["argv"]({"output": "p.json", "channels": 6, "format": "xm"}),
                         ["synth", "palette", "--output", "p.json", "--channels", "6", "--format", "xm"])


class XmStructureOperationsTests(unittest.TestCase):
    def setUp(self):
        self.module = xm.blank("Ops", 4, patterns=2)
        apply_ops(self.module, [{"op": "set", "pattern": 0, "row": 60, "channel": 1, "cell": "C-4 01 -- ..."}])

    def test_pattern_length_grows_and_needs_truncate_to_cut_notes(self):
        result = apply_ops(self.module, [{"op": "pattern_length", "pattern": 0, "rows": 128}])
        self.assertEqual((result[0]["rows_before"], result[0]["rows"]), (64, 128))
        with self.assertRaises(ValidationError) as caught:
            apply_ops(self.module, [{"op": "pattern_length", "pattern": 0, "rows": 32}])
        self.assertEqual(caught.exception.code, "PATTERN_TRUNCATE")
        result = apply_ops(self.module, [{"op": "pattern_length", "pattern": 0, "rows": 32, "truncate": True}])
        self.assertEqual((result[0]["cells_dropped"], self.module.patterns[0].rows), (1, 32))
        validate(self.module)
        for op in ({"op": "pattern_length", "pattern": 0, "rows": 257}, {"op": "pattern_length", "pattern": 5, "rows": 8},
                   {"op": "pattern_length", "pattern": 0, "rows": 8, "truncate": "yes"}):
            with self.subTest(op=op), self.assertRaises(ValidationError):
                apply_ops(copy.deepcopy(self.module), [op])

    def test_xm_header_sets_restart_speed_bpm_and_table(self):
        result = apply_ops(self.module, [{"op": "xm_header", "restart_position": 1, "default_speed": 3,
                                          "default_bpm": 150, "frequency_table": "amiga"}])
        block = self.module.metadata["xm"]
        self.assertEqual((block["restart_position"], block["default_speed"], block["default_bpm"],
                          block["frequency_table"]), (1, 3, 150, "amiga"))
        self.assertEqual(result[0]["before"]["frequency_table"], "linear")
        self.assertIn("note", result[0])
        self.assertEqual(playback_plan(self.module)["timeline"][0]["bpm"], 150)
        for op in ({"op": "xm_header"}, {"op": "xm_header", "restart_position": 2}, {"op": "xm_header", "default_speed": 0},
                   {"op": "xm_header", "default_bpm": 256}, {"op": "xm_header", "frequency_table": "log"},
                   {"op": "xm_header", "tracker_name": "x"}):
            with self.subTest(op=op), self.assertRaises(ValidationError):
                apply_ops(copy.deepcopy(self.module), [op])

    def test_xm_structure_operations_are_refused_on_a_mod(self):
        module, _ = synth_tools.palette()
        for op in ({"op": "pattern_length", "pattern": 0, "rows": 32}, {"op": "xm_header", "default_speed": 3}):
            with self.subTest(op=op["op"]), self.assertRaises(ValidationError) as caught:
                apply_ops(copy.deepcopy(module), [op])
            self.assertEqual(caught.exception.code, "MOD_OP_UNSUPPORTED")


class PlanWarningTests(unittest.TestCase):
    def test_an_xm_break_past_the_target_pattern_end_is_valid_but_warned(self):
        module = xm.blank("Flow", 4, patterns=2)
        apply_ops(module, [{"op": "pattern_length", "pattern": 1, "rows": 16},
                           {"op": "set", "pattern": 0, "row": 3, "channel": 0, "cell": "--- -- -- D20"}])
        plan = playback_plan(module)
        self.assertEqual(len(plan["warnings"]), 1)
        self.assertIn("breaks to row 20", plan["warnings"][0])
        self.assertIn("16 rows", plan["warnings"][0])
        apply_ops(module, [{"op": "set", "pattern": 0, "row": 3, "channel": 0, "cell": "--- -- -- D10"}])
        self.assertEqual(playback_plan(module)["warnings"], [])

    def test_a_loop_back_at_another_tempo_is_warned(self):
        module = xm.blank("Loop", 4, patterns=2, speed=6, bpm=125)
        apply_ops(module, [{"op": "set", "pattern": 1, "row": 0, "channel": 0, "cell": "--- -- -- F03"}])
        warnings = playback_plan(module)["warnings"]
        self.assertEqual(len(warnings), 1)
        self.assertIn("speed 3 / 125 BPM", warnings[0])
        self.assertIn("speed 6 / 125 BPM", warnings[0])
        apply_ops(module, [{"op": "set", "pattern": 0, "row": 0, "channel": 0, "cell": "--- -- -- F06"}])
        self.assertEqual(playback_plan(module)["warnings"], [])               # the tempo is restated

    def test_restart_position_and_mod_backward_jumps_are_checked_too(self):
        module = xm.blank("Restart", 4, patterns=3)
        apply_ops(module, [{"op": "xm_header", "restart_position": 1},
                           {"op": "set", "pattern": 2, "row": 0, "channel": 0, "cell": "--- -- -- F7D"},
                           {"op": "set", "pattern": 1, "row": 0, "channel": 0, "cell": "--- -- -- F04"}])
        self.assertEqual(playback_plan(module)["warnings"], [])               # order 1 restates speed, BPM stays 125
        apply_ops(module, [{"op": "set", "pattern": 2, "row": 0, "channel": 0, "cell": "--- -- -- F90"}])
        self.assertIn("order 1", playback_plan(module)["warnings"][0])
        song, _ = synth_tools.palette()
        apply_ops(song, [{"op": "add_pattern"}, {"op": "set", "pattern": 1, "row": 0, "channel": 0, "cell": "--- -- F05"},
                         {"op": "set", "pattern": 1, "row": 63, "channel": 1, "cell": "--- -- B00"}])
        self.assertEqual(len(playback_plan(song)["warnings"]), 1)

    def test_validate_inspect_and_patch_report_the_plan_warnings(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            start = folder / "song.json"
            module = xm.blank("Flow", 4, patterns=2)
            project.write_json(start, project.to_dict(module))
            code, result = run_cli("patch", start, "--output", folder / "next.json", "--op",
                                   '{"op": "set", "pattern": 1, "row": 0, "channel": 0, "cell": "--- -- -- F7D"}',
                                   "--op", '{"op": "xm_header", "default_bpm": 140}')
            self.assertEqual(code, 0, result)
            self.assertTrue(any("loops back" in item for item in result["warnings"]))
            for command in ("validate", "inspect"):
                code, result = run_cli(command, folder / "next.json")
                self.assertEqual(code, 0, result)
                self.assertTrue(any("loops back" in item for item in result["warnings"]), command)


class SmallItemsTests(unittest.TestCase):
    def test_estimate_accepts_xm_pattern_lengths(self):
        code, result = run_cli("estimate", "--orders", "2", "--rows", "256")
        self.assertEqual((code, result["rows_per_order"]), (0, 256))
        code, result = run_cli("estimate", "--orders", "2", "--rows", "257")
        self.assertEqual(code, 2)

    def test_previews_explain_xm_note_labels(self):
        with tempfile.TemporaryDirectory() as folder:
            code, result = run_cli("synth", "preview", "--recipe", '{"type": "kick"}', "--note", "C-4",
                                   "--output", Path(folder) / "kick.wav")
            self.assertEqual((code, result["code"]), (2, "NOTE_UNKNOWN"))
            self.assertIn("C-4 (XM) is C-2 (MOD)", result["message"])


if __name__ == "__main__":
    unittest.main()
