"""N-channel modules: 2 to 32 channels in a MOD (6CHN, 8CHN, 10CH ...), through every layer.

Binary fixtures are assembled here byte by byte, independently of `mod.encode`.
"""
from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import struct
import tempfile
import unittest

from tracker4agents import audio, cli, demo, document, mod, project, review
from tracker4agents.model import (
    Cell, Module, Pattern, Sample, ValidationError, cell, playback_plan, validate,
)
from tracker4agents.patch import apply_ops, pattern_grid, row_cells
from tracker4agents.realtime import XmpEngine, find_library
from tracker4agents.report import analyze

ROOT = Path(__file__).resolve().parents[1]
PCM = (0, 0, 60, 100, 60, 0, -60, -100, -60, 0)


def raw_nch(channels: int, *, signature: bytes | None = None, orders=(0,), patterns=1, cells=None) -> bytes:
    """A MOD with `channels` channels assembled field by field (one 10-byte looped sample in slot 1)."""
    header = bytearray(1084)
    header[:7] = b"Channel"
    for slot in range(1, 32):
        struct.pack_into(">HBBHH", header, 20 + (slot - 1) * 30 + 22, 0, 0, 0, 0, 1)
    struct.pack_into(">HBBHH", header, 42, 5, 0, 64, 0, 5)
    header[950], header[951] = len(orders), 0x7F
    header[952:952 + len(orders)] = bytes(orders)
    header[1080:1084] = signature or (f"{channels}CHN" if channels < 10 else f"{channels}CH").encode()
    body = bytearray(patterns * 64 * channels * 4)
    for (pattern, row, channel), event in (cells or {}).items():
        offset = ((pattern * 64 + row) * channels + channel) * 4
        body[offset:offset + 4] = event
    return bytes(header + body + bytes(value & 255 for value in PCM))


def flow_module(channels: int, cells: dict, orders=(0,), patterns=1) -> Module:
    built = [Pattern() for _ in range(patterns)]
    for (pattern, row, channel), text in cells.items():
        built[pattern].put(row, channel, cell(effect=text))
    return Module("Flow", [Sample("", (), volume=0)], built, list(orders), {}, channels)


class ModelDefaultsTests(unittest.TestCase):
    def test_four_channel_defaults_are_unchanged(self):
        module = demo.create()
        self.assertEqual((module.channels, module.format), (4, "mod"))
        self.assertEqual({pattern.rows for pattern in module.patterns}, {64})
        self.assertEqual(Cell().volume, 0)
        self.assertEqual(mod.encode(module)[1080:1084], b"M.K.")
        self.assertNotIn("channels", project.to_dict(module))
        self.assertEqual(project.to_dict(module)["profile"], "protracker-4ch-pal-v1")

    def test_channel_count_is_validated(self):
        for channels in (0, 1, 33, True, "4"):
            module = flow_module(4, {})
            module.channels = channels
            with self.subTest(channels=channels), self.assertRaises(ValidationError):
                validate(module)

    def test_cells_beyond_the_channel_count_are_rejected(self):
        module = flow_module(4, {})
        module.patterns[0].put(0, 5, cell("C-2", 1))
        with self.assertRaises(ValidationError):
            validate(module)
        module.channels = 6
        validate(module)


class NChannelModTests(unittest.TestCase):
    def test_signatures_round_trip_byte_for_byte(self):
        for channels in (2, 3, 6, 8, 10, 16, 32):
            with self.subTest(channels=channels):
                cells = {(0, 0, channels - 1): bytes.fromhex("01 AC 10 00"), (0, 5, 0): bytes.fromhex("00 00 0F 03")}
                payload = raw_nch(channels, cells=cells)
                module = mod.decode(payload)
                self.assertEqual(module.channels, channels)
                self.assertEqual(module.metadata, {})
                self.assertEqual(module.patterns[0].get(0, channels - 1), cell("C-2", 1))
                self.assertEqual(mod.encode(module), payload)
                self.assertEqual(mod.encode(project.from_dict(project.to_dict(module))), payload)

    def test_unsupported_variants_have_their_own_codes(self):
        for signature, code in ((b"FLT8", "MOD_FLT8"), (b"CD81", "MOD_VARIANT"), (b"OCTA", "MOD_VARIANT"),
                                (b"TDZ3", "MOD_VARIANT"), (b"33CH", "MOD_FORMAT"), (b"1CHN", "MOD_FORMAT"),
                                (b"M&K!", "MOD_FORMAT")):
            with self.subTest(signature=signature), self.assertRaises(ValidationError) as caught:
                mod.decode(raw_nch(4, signature=signature))
            self.assertEqual(caught.exception.code, code)

    def test_size_must_match_the_channel_count(self):
        with self.assertRaises(ValidationError):
            mod.decode(raw_nch(4, signature=b"8CHN"))  # four-channel data under an eight-channel name

    def test_four_channel_signature_variants_still_work_and_n_channel_rejects_a_stored_one(self):
        module = mod.decode(raw_nch(4, signature=b"4CHN"))
        self.assertEqual(module.metadata["mod"]["signature"], "4CHN")
        six = mod.decode(raw_nch(6))
        six.metadata = {"mod": {"signature": "4CHN"}}
        with self.assertRaises(ValidationError):
            validate(six)

    def test_project_schema_for_n_channels(self):
        module = mod.decode(raw_nch(6, cells={(0, 3, 5): bytes.fromhex("01 AC 1C 20")}))
        data = project.to_dict(module)
        self.assertEqual((data["profile"], data["channels"]), ("protracker-nch-pal-v1", 6))
        self.assertNotIn("format", data)
        line = data["patterns"][0]["rows"]["03"]
        self.assertEqual(line.count("|"), 5)
        self.assertTrue(line.endswith("C-2 01 C20"))
        self.assertEqual(project.to_dict(project.from_dict(data)), data)
        text = project.dumps(data)
        self.assertEqual(project.from_dict(json.loads(text)).channels, 6)
        # the profile and the channel count must agree
        for broken in ({**data, "profile": "protracker-4ch-pal-v1"}, {**data, "channels": 4}, {**data, "channels": 40}):
            with self.assertRaises(ValidationError):
                project.from_dict(broken)

    def test_events_layout_and_row_cell_count(self):
        module = mod.decode(raw_nch(8, cells={(0, 1, 7): bytes.fromhex("01 AC 10 00")}))
        events = project.to_dict(module, layout="events")
        self.assertEqual(events["patterns"][0]["events"], [{"row": 1, "channel": 7, "note": "C-2", "sample": 1}])
        self.assertEqual(project.from_dict(events).patterns[0].get(1, 7), cell("C-2", 1))
        with self.assertRaises(ValidationError):
            project.from_dict({**project.to_dict(module), "patterns": [
                {"name": "P", "rows": {"00": "C-2 01 ... | --- -- ... | --- -- ..."}}]})
        with self.assertRaisesRegex(ValidationError, "eight cells"):
            row_cells("--- -- ... | --- -- ...", 8)

    def test_diagnose_reports_channel_errors(self):
        data = project.to_dict(mod.decode(raw_nch(6)))
        data["patterns"][0]["rows"] = {"00": "C-2 01 ... | " * 5 + "C-2 01 ..."}
        self.assertEqual(project.diagnose(data), [])
        data["patterns"][0]["rows"] = {"00": "C-2 01 ... | --- -- ..."}
        self.assertTrue(project.diagnose(data))


class NChannelPatchTests(unittest.TestCase):
    def setUp(self):
        self.module = mod.decode(raw_nch(6))

    def test_write_set_and_grid_text(self):
        results = apply_ops(self.module, [
            {"op": "write", "pattern": 0, "row": 0, "lines": ["C-2 01 ... | --- -- ... | --- -- ... | --- -- ... | --- -- ... | E-2 01 C20"]},
            {"op": "set", "pattern": 0, "row": 1, "channel": 5, "cell": "G-2 01 ..."},
        ])
        self.assertEqual(len(results), 2)
        self.assertEqual(self.module.patterns[0].get(0, 5).text(), "E-2 01 C20")
        grid = pattern_grid(self.module, 0, 0, 2)
        self.assertEqual(grid[0], "00 | C-2 01 ... | --- -- ... | --- -- ... | --- -- ... | --- -- ... | E-2 01 C20")
        self.assertEqual(grid[1].count("|"), 6)
        validate(self.module)

    def test_bounds_follow_the_module(self):
        for op in ({"op": "set", "pattern": 0, "row": 0, "channel": 6, "cell": "C-2 01 ..."},
                   {"op": "write", "pattern": 0, "cells": ["C-2 01 ..."], "channel": 6},
                   {"op": "write", "pattern": 0, "lines": ["C-2 01 ... | --- -- ... | --- -- ... | --- -- ..."]},
                   {"op": "clear", "pattern": 0, "channel": 4, "channels": 3},
                   {"op": "copy", "pattern": 0, "channels": 1, "to_channel": 6}):
            with self.subTest(op=op), self.assertRaises(ValidationError):
                apply_ops(self.module, [op])

    def test_copy_move_transpose_clear_across_channels(self):
        apply_ops(self.module, [{"op": "set", "pattern": 0, "row": 2, "channel": 0, "cell": "C-2 01 C30"}])
        apply_ops(self.module, [{"op": "copy", "pattern": 0, "row": 2, "channel": 0, "to_channel": 5}])
        self.assertEqual(self.module.patterns[0].get(2, 5), self.module.patterns[0].get(2, 0))
        apply_ops(self.module, [{"op": "transpose", "pattern": 0, "channel": 5, "semitones": 12, "rows": 8}])
        self.assertEqual(self.module.patterns[0].get(2, 5).note, "C-3")
        apply_ops(self.module, [{"op": "move", "pattern": 0, "row": 2, "channel": 5, "to_channel": 4}])
        self.assertEqual(self.module.patterns[0].get(2, 4).note, "C-3")
        apply_ops(self.module, [{"op": "clear", "pattern": 0, "row": 2, "channels": 6}])
        self.assertEqual(self.module.patterns[0].cells, {})

    def test_timing_uses_free_effect_columns_of_all_channels(self):
        module = flow_module(6, {(0, 0, 0): "C20", (0, 0, 1): "C20", (0, 0, 2): "C20", (0, 0, 3): "C20"})
        apply_ops(module, [{"op": "timing", "bpm": 150, "speed": 5}])
        self.assertEqual([module.patterns[0].get(0, channel).effect for channel in (4, 5)], ["F05", "F96"])
        tight = flow_module(6, {(0, 0, channel): "C20" for channel in range(5)})
        with self.assertRaises(ValidationError):
            apply_ops(tight, [{"op": "timing", "bpm": 150, "speed": 5}])

    def test_diff_and_merge_carry_channel_five(self):
        from tracker4agents.patch import diff_modules, merge_modules, touched
        import copy
        base = copy.deepcopy(self.module)
        mine = copy.deepcopy(base)
        theirs = copy.deepcopy(base)
        apply_ops(mine, [{"op": "set", "pattern": 0, "row": 0, "channel": 5, "cell": "C-2 01 ..."}])
        apply_ops(theirs, [{"op": "set", "pattern": 0, "row": 0, "channel": 4, "cell": "D-2 01 ..."}])
        diff = diff_modules(base, mine)
        self.assertEqual(diff["cells"][0]["channel"], 5)
        self.assertEqual(touched(diff), {("cell", 0, 0, 5)})
        merged, conflicts = merge_modules(base, mine, theirs)
        self.assertEqual(conflicts, [])
        self.assertEqual((merged.patterns[0].get(0, 4).note, merged.patterns[0].get(0, 5).note), ("D-2", "C-2"))


class NChannelLayersTests(unittest.TestCase):
    def setUp(self):
        self.module = mod.decode(raw_nch(6, orders=(0, 0), cells={
            (0, 0, 5): bytes.fromhex("01 AC 10 00"), (0, 8, 2): bytes.fromhex("01 7D 10 00")}))

    def test_listening_copy_mutes_by_channel_and_checks_the_count(self):
        copy = document.listening_copy(self.module, (True, True, True, True, True, False))
        self.assertEqual(copy.patterns[0].get(0, 5).period, 0)
        self.assertEqual(copy.patterns[0].get(8, 2).period, 0x17D)
        with self.assertRaises(ValidationError):
            document.listening_copy(self.module, (True,) * 4)

    def test_report_has_one_entry_per_channel(self):
        report = analyze(self.module)
        self.assertEqual([entry["channel"] for entry in report["channels"]], [1, 2, 3, 4, 5, 6])
        self.assertEqual(report["channels"][5]["note_ons"], 2)
        self.assertEqual(len(report["repetition"]["blocks"]["8"]["channels"]), 6)

    def test_pattern_html_shows_every_channel(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "preview.html"
            review.write_preview(self.module, output, "module.wav", "validation.json")
            page = output.read_text(encoding="utf-8")
        self.assertIn("6CHN", page)
        self.assertIn("td:nth-child(7){color", page)
        self.assertEqual(page.count("<th>Track "), 6)
        self.assertIn("<strong>06</strong>", page)

    def test_four_channel_page_is_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "preview.html"
            review.write_preview(demo.create(), output, "module.wav", "validation.json")
            page = output.read_text(encoding="utf-8")
        self.assertIn("PROTRACKER / PAL / M.K.", page)
        self.assertIn("td:nth-child(2){color:#8fd8e8}td:nth-child(3){color:#f6bc7a}td:nth-child(4){color:#bbd996}td:nth-child(5){color:#c4a5ef}", page)
        self.assertIn("<strong>04</strong>", page)

    def test_cli_inspect_and_validate(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "six.mod"
            source.write_bytes(raw_nch(6, cells={(0, 3, 5): bytes.fromhex("01 AC 10 00")}))
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = cli.main(["inspect", str(source), "--pattern", "0", "--grid", "--row", "3", "--rows", "1"])
            self.assertEqual(code, 0, err.getvalue())
            result = json.loads(out.getvalue())
            self.assertEqual((result["channels"], result["profile"]), (6, "protracker-nch-pal-v1"))
            self.assertEqual(result["pattern"]["grid"][0].count("|"), 6)
            self.assertIn("track 6", result["pattern"]["columns"])
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(cli.main(["validate", str(source)]), 0)

    def test_cli_export_import_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "eight.mod"
            payload = raw_nch(8, cells={(0, 3, 7): bytes.fromhex("01 AC 10 00")})
            source.write_bytes(payload)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(["import", str(source), "--output", str(Path(folder) / "eight.json")]), 0)
                self.assertEqual(cli.main(["export", str(Path(folder) / "eight.json"), "--output",
                                           str(Path(folder) / "again.mod")]), 0)
            self.assertEqual((Path(folder) / "again.mod").read_bytes(), payload)


@unittest.skipUnless(find_library(), "libxmp is required for real-time playback tests.")
class NChannelRealtimeTests(unittest.TestCase):
    def test_engine_mutes_n_channels_and_plays_a_six_channel_mod(self):
        module = mod.decode(raw_nch(6, cells={(0, 0, 5): bytes.fromhex("01 AC 10 00")}))
        engine = XmpEngine()
        try:
            engine.load(module)
            self.assertEqual(len(engine.audible), 6)
            pcm, markers = engine.render(4800)
            self.assertEqual(len(pcm), 4800 * 4)
            self.assertGreater(max(abs(int.from_bytes(pcm[i:i + 2], "little", signed=True)) for i in range(0, len(pcm), 2)), 500)
            with self.assertRaises(ValidationError):
                engine.set_audible((True,) * 4)
            engine.set_audible((True,) * 5 + (False,))
            engine.seek(0, 0)
            muted, _ = engine.render(4800)
            self.assertEqual(max(abs(int.from_bytes(muted[i:i + 2], "little", signed=True)) for i in range(0, len(muted), 2)), 0)
        finally:
            engine.close()


class FlowAgreementTests(unittest.TestCase):
    """The plan against libxmp's trace on 2, 6, 8 and 16 channels (skipped without libxmp)."""

    CASES = {
        "loop": {(0, 2, 0): "E60", (0, 4, 1): "E62", (0, 6, 2): "B00"},
        "channels_apart": {(0, 0, 3): "E60", (0, 1, 1): "E60", (0, 2, 1): "E62", (0, 4, 3): "E61", (0, 6, 1): "B00"},
        "delay": {(0, 1, 1): "EE1", (0, 1, 0): "EE3", (0, 3, 1): "D00"},
        "break_cancels_loop": {(0, 2, 0): "E61", (0, 2, 1): "D03", (0, 6, 0): "B00"},
    }

    @classmethod
    def setUpClass(cls):
        try:
            cls.library = audio.default_xmp_library()
        except audio.RenderError as exc:
            raise unittest.SkipTest(str(exc)) from exc

    def test_plan_matches_the_libxmp_trace(self):
        for channels in (2, 6, 8, 16):
            for name, cells in self.CASES.items():
                with self.subTest(channels=channels, case=name), tempfile.TemporaryDirectory() as folder:
                    module = flow_module(channels, {key: text for key, text in cells.items() if key[2] < channels})
                    plan = playback_plan(module)
                    source = Path(folder) / "case.mod"
                    source.write_bytes(mod.encode(module))
                    trace = audio.render(source, Path(folder) / "case.wav", "xmp", plan["duration_seconds"],
                                         xmp_library=self.library)["trace"]
                    self.assertEqual(len(trace), len(plan["timeline"]))
                    for expected, actual in zip(plan["timeline"], trace):
                        for key in ("order", "pattern", "row", "speed", "bpm"):
                            self.assertEqual(expected[key], actual[key], (channels, name))
                        self.assertAlmostEqual(expected["seconds"], actual["seconds"], delta=2 / 48000)


if __name__ == "__main__":
    unittest.main()
