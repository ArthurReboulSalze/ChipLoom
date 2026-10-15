from __future__ import annotations

import copy
import struct
import unittest

from tracker4agents import demo, mod, project
from tracker4agents.model import Cell, Module, Pattern, Sample, ValidationError, cell, playback_plan, validate
from tracker4agents.synth import from_recipe


def fixture_bytes() -> bytes:
    """An independently assembled, minimal documented M.K. binary fixture."""
    header = bytearray(1084)
    header[:7] = b"Fixture"
    header[20:24] = b"Test"
    # Four-byte sample, finetune -1, volume 64, no-loop word at offset zero.
    struct.pack_into(">HBBHH", header, 42, 2, 15, 64, 0, 1)
    for index in range(1, 31):
        struct.pack_into(">H", header, 20 + index * 30 + 28, 1)
    header[950], header[951] = 1, 127
    header[1080:1084] = b"M.K."
    pattern = bytearray(1024)
    pattern[0:4] = bytes.fromhex("01 AC 1C 20")  # C-2 / sample 1 / volume 32.
    return bytes(header + pattern + bytes((0, 0, 127, 128)))


class ModCodecTests(unittest.TestCase):
    def test_independent_binary_fixture(self):
        payload = fixture_bytes()
        module = mod.decode(payload)
        self.assertEqual(module.title, "Fixture")
        self.assertEqual(module.samples[0].pcm, (0, 0, 127, -128))
        self.assertEqual(module.samples[0].finetune, -1)
        self.assertEqual(module.patterns[0].get(0, 0), cell("C-2", 1, "C20"))
        self.assertEqual(mod.encode(module), payload)

    def test_sample_31_uses_both_sample_nibbles(self):
        samples = [Sample("", (), volume=0) for _ in range(30)] + [Sample("Last", (0, 0, 1, -1))]
        pattern = Pattern(cells={(0, 3): cell("B-3", 31, "F06")})
        payload = mod.encode(Module("Last slot", samples, [pattern], [0]))
        self.assertEqual(payload[1084 + 12:1084 + 16], bytes.fromhex("10 71 FF 06"))
        self.assertEqual(mod.decode(payload).patterns[0].get(0, 3).sample, 31)

    def test_maximum_sample_length_is_encoded_in_words(self):
        sample = Sample("Largest", (0, 0) + (1, -1) * 32766)
        module = Module("Boundary", [sample], [Pattern()], [0])
        payload = mod.encode(module)
        self.assertEqual(payload[42:44], b"\x7f\xff")
        self.assertEqual(len(mod.decode(payload).samples[0].pcm), 65534)

    def test_truncation_trailing_data_and_unsupported_magic_are_rejected(self):
        good = fixture_bytes()
        bad_magic = bytearray(good)
        bad_magic[1080:1084] = b"8CHN"
        for payload in (good[:-1], good + b"extra", bytes(bad_magic), good[:1000]):
            with self.subTest(length=len(payload)), self.assertRaises(ValidationError):
                mod.decode(payload)

    def test_invalid_order_or_sample_length_is_rejected(self):
        for offset, value in ((950, 0), (952, 64), (42, 255), (951, 0)):
            payload = bytearray(fixture_bytes())
            payload[offset] = value
            with self.subTest(offset=offset), self.assertRaises(ValidationError):
                mod.decode(bytes(payload))

    def test_profile_rejects_lossy_or_ambiguous_values(self):
        base = Module("Valid", [Sample("Tone", (0, 0, 1, -1))], [Pattern()], [0])
        variants = []
        bad = copy.deepcopy(base)
        bad.title = "This title is too long"
        variants.append(bad)
        bad = copy.deepcopy(base)
        bad.samples[0].pcm = (0, 0, 1)
        variants.append(bad)
        bad = copy.deepcopy(base)
        bad.samples[0].pcm = (0, 1, 2, 3)
        variants.append(bad)
        bad = copy.deepcopy(base)
        bad.samples[0].loop_length = 4
        bad.samples[0].loop_start = 2
        variants.append(bad)
        for effect in ("800", "F00", "F20", "E60", "EE1", "EF1", "C41", "D64", "D0A", "B01"):
            bad = copy.deepcopy(base)
            bad.patterns[0].put(0, 0, cell("C-2", 1, effect))
            variants.append(bad)
        bad = copy.deepcopy(base)
        bad.patterns[0].put(0, 0, Cell(period=429, sample=1))
        variants.append(bad)
        for bad in variants:
            with self.subTest(module=bad.title, cells=bad.patterns[0].cells), self.assertRaises(ValidationError):
                validate(bad)


class MusicProjectTests(unittest.TestCase):
    def test_demo_score_rebuilds_same_binary_and_uses_all_channels(self):
        module = demo.create()
        payload = mod.encode(module)
        self.assertEqual(payload, mod.encode(project.from_dict(project.to_dict(module))))
        self.assertEqual(payload, mod.encode(mod.decode(payload)))
        self.assertEqual(len(module.samples), 8)
        self.assertEqual(len(module.patterns), 4)
        self.assertEqual({channel for p in module.patterns for (_, channel), c in p.cells.items() if c.period}, {0, 1, 2, 3})
        plan = playback_plan(module)
        self.assertEqual(plan["duration_seconds"], 30.72)
        self.assertEqual(plan["rows"], 256)
        self.assertEqual(plan["loop_start_seconds"], 0)

    def test_synthesis_is_repeatable_and_has_real_signal(self):
        recipe = {"type": "snare", "seed": 42}
        first = from_recipe("Snare", recipe)
        self.assertEqual(first.pcm, from_recipe("Snare", recipe).pcm)
        self.assertNotEqual(first.pcm, from_recipe("Snare", {**recipe, "seed": 43}).pcm)
        self.assertEqual(first.pcm[:2], (0, 0))
        self.assertEqual(first.pcm[-2:], (0, 0))
        self.assertGreater(max(first.pcm), 40)
        self.assertLess(min(first.pcm), -40)

    def test_drawn_wave_is_looped_and_in_tune_within_quantization(self):
        recipe = {"type": "draw", "frequency": 130.812783, "cycles": 16, "points": [0, 1, 0, -1]}
        sample = from_recipe("Draw", recipe)
        self.assertEqual(sample.loop_start, 0)
        self.assertEqual(sample.loop_length, len(sample.pcm))
        self.assertEqual(len(sample.pcm) % 2, 0)
        from tracker4agents.model import SAMPLE_RATE
        self.assertLess(abs(SAMPLE_RATE * 16 / len(sample.pcm) - recipe["frequency"]), 0.2)

    def test_duplicate_cells_unknown_fields_and_wrong_note_types_fail(self):
        base = project.to_dict(demo.create())
        variants = []
        bad = copy.deepcopy(base)
        bad["patterns"][0]["events"].append(bad["patterns"][0]["events"][0].copy())
        variants.append(bad)
        bad = copy.deepcopy(base)
        bad["patternz"] = []
        variants.append(bad)
        bad = copy.deepcopy(base)
        bad["patterns"][0]["events"][0]["note"] = ["C-2"]
        variants.append(bad)
        for bad in variants:
            with self.assertRaises(ValidationError):
                project.from_dict(bad)

    def test_nonfinite_or_out_of_range_recipes_fail(self):
        for recipe in ({"type": "pluck", "duration": float("nan")},
                       {"type": "hat", "duration": 100000},
                       {"type": "draw", "points": [0, 0, 0, 0]},
                       {"type": "hat", "seed": True}):
            with self.subTest(recipe=recipe), self.assertRaises(ValidationError):
                from_recipe("Invalid", recipe)

    def test_timing_changes_and_bcd_break_rows(self):
        first = Pattern(cells={(0, 0): cell(effect="F03"), (0, 1): cell(effect="F64"), (1, 0): cell(effect="D10")})
        second = Pattern(cells={(10, 0): cell(effect="B00")})
        module = Module("Timing", [Sample("", (), volume=0)], [first, second], [0, 1])
        plan = playback_plan(module)
        self.assertEqual([(row["order"], row["row"]) for row in plan["timeline"][:3]], [(0, 0), (0, 1), (1, 10)])
        self.assertAlmostEqual(plan["timeline"][2]["seconds"], 0.15)
        self.assertAlmostEqual(plan["duration_seconds"], 0.225)
        self.assertEqual(plan["rows"], 3)


if __name__ == "__main__":
    unittest.main()
